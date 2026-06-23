"""V7 구조 피처 추출기 단위 테스트 (P1).

Pins:
  - 32 피처 이름·순서 SSOT (MDML pt_summary CSV 헤더 패리티)
  - 알려진 분자(벤젠/에탄올)의 RDKit descriptor 값
  - count 가중 mean/sum/std 집계 수식 (모집단 통계)
  - RDKit 부재 graceful (None 반환)
  - 실제 분자 라이브러리(.mol) 통합 경로
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ml import structural_features as sf
from ml.structural_features import (
    NODE_DESCRIPTOR_NAMES,
    STRUCTURAL_FEATURE_NAMES,
    StructuralFeatureExtractor,
    aggregate_structural_features,
    compute_molecule_descriptors,
    zeros,
)

rdkit = pytest.importorskip("rdkit")
from rdkit import Chem  # noqa: E402
from rdkit.Chem import AllChem  # noqa: E402

# ── 이름/순서 SSOT ──────────────────────────────────────────────────────────


class TestFeatureNames:
    def test_exactly_32_features(self):
        assert len(STRUCTURAL_FEATURE_NAMES) == 32

    def test_mdml_csv_header_parity(self):
        """MDML pt_summary CSV 컬럼 순서와 동일해야 혼합 학습 정합."""
        expected: list[str] = []
        for name in [
            "MolWt",
            "TPSA",
            "MolLogP",
            "NumHeteroatoms",
            "NumRotatableBonds",
            "FractionCSP3",
            "NumAliphaticCarbocycles",
            "NumAromaticCarbocycles",
            "PartialCharge",
            "HB_Acc_Don",
        ]:
            expected.extend(
                [f"node_{name}_mean", f"node_{name}_sum", f"node_{name}_std"]
            )
        expected.extend(["sys_NumFragments", "sys_Temperature"])
        assert STRUCTURAL_FEATURE_NAMES == expected

    def test_zeros_covers_all_names(self):
        z = zeros()
        assert set(z) == set(STRUCTURAL_FEATURE_NAMES)
        assert all(v == 0.0 for v in z.values())


# ── descriptor 계산 (알려진 분자) ───────────────────────────────────────────


def _write_mol(tmp_path: Path, name: str, smiles: str) -> Path:
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.Compute2DCoords(mol)
    path = tmp_path / f"{name}.mol"
    path.write_text(Chem.MolToMolBlock(mol))
    return path


class TestComputeMoleculeDescriptors:
    def test_benzene(self, tmp_path):
        path = _write_mol(tmp_path, "benzene", "c1ccccc1")
        values = compute_molecule_descriptors(str(path))
        assert values is not None
        d = dict(zip(NODE_DESCRIPTOR_NAMES, values, strict=True))
        assert d["MolWt"] == pytest.approx(78.0470, abs=0.01)
        assert d["TPSA"] == 0.0
        assert d["NumAromaticCarbocycles"] == 1.0
        assert d["NumHeteroatoms"] == 0.0
        assert d["HB_Acc_Don"] == 0.0
        # 중성 분자 Gasteiger 합 ≈ 0 (MDML 패리티 — 스키마 유지용)
        assert abs(d["PartialCharge"]) < 1e-6

    def test_ethanol(self, tmp_path):
        path = _write_mol(tmp_path, "ethanol", "CCO")
        values = compute_molecule_descriptors(str(path))
        assert values is not None
        d = dict(zip(NODE_DESCRIPTOR_NAMES, values, strict=True))
        assert d["TPSA"] == pytest.approx(20.23, abs=0.01)
        assert d["HB_Acc_Don"] == 2.0  # acceptor 1 + donor 1
        assert d["NumHeteroatoms"] == 1.0
        assert d["FractionCSP3"] == 1.0

    def test_missing_file_returns_none(self, tmp_path):
        assert compute_molecule_descriptors(str(tmp_path / "nope.mol")) is None

    def test_cached_per_path(self, tmp_path):
        path = _write_mol(tmp_path, "methane", "C")
        first = compute_molecule_descriptors(str(path))
        second = compute_molecule_descriptors(str(path))
        assert first is second  # lru_cache 동일 객체


# ── count 가중 집계 수식 ────────────────────────────────────────────────────


class TestAggregation:
    def test_weighted_mean_sum_std(self):
        # 종 A(x=10) 2개 + 종 B(x=40) 1개 → 인스턴스 [10,10,40]
        desc_a = tuple([10.0] + [0.0] * 9)
        desc_b = tuple([40.0] + [0.0] * 9)
        record = aggregate_structural_features(
            {"A": (desc_a, 2), "B": (desc_b, 1)}, temperature_k=300.0
        )
        assert record["node_MolWt_sum"] == pytest.approx(60.0)
        assert record["node_MolWt_mean"] == pytest.approx(20.0)
        # 모집단 std: sqrt(((10-20)^2*2 + (40-20)^2*1)/3) = sqrt(200)
        assert record["node_MolWt_std"] == pytest.approx(math.sqrt(200.0))
        assert record["sys_NumFragments"] == 3.0
        assert record["sys_Temperature"] == 300.0
        assert set(record) == set(STRUCTURAL_FEATURE_NAMES)

    def test_empty_population_raises(self):
        with pytest.raises(ValueError):
            aggregate_structural_features({}, temperature_k=300.0)


# ── RDKit 부재 graceful ────────────────────────────────────────────────────


class TestRdkitUnavailable:
    def test_extract_returns_none(self, monkeypatch):
        monkeypatch.setattr(sf, "RDKIT_AVAILABLE", False)
        extractor = StructuralFeatureExtractor()
        assert extractor.extract_from_counts({"X": 1}, 300.0) is None

    def test_compute_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sf, "RDKIT_AVAILABLE", False)
        compute_molecule_descriptors.cache_clear()
        path = _write_mol(tmp_path, "benzene2", "c1ccccc1")
        assert compute_molecule_descriptors(str(path)) is None
        compute_molecule_descriptors.cache_clear()


# ── 실제 분자 라이브러리 통합 ───────────────────────────────────────────────


class TestRealLibraryIntegration:
    def test_sara_variant_extraction(self):
        """U-SA-Squalane-0293 같은 aging variant id가 .mol로 해석·계산됨."""
        extractor = StructuralFeatureExtractor()
        record = extractor.extract_from_counts(
            {"U-SA-Squalane-0293": 4, "U-AS-Phenol-0293": 2}, temperature_k=293.0
        )
        assert record is not None
        assert record["sys_NumFragments"] == 6.0
        assert record["node_MolWt_mean"] > 100.0  # 실제 분자량 스케일
        assert all(math.isfinite(v) for v in record.values())

    def test_unresolvable_species_skipped(self):
        extractor = StructuralFeatureExtractor()
        record = extractor.extract_from_counts(
            {"U-SA-Squalane-0293": 2, "NOT-A-MOL": 3}, temperature_k=293.0
        )
        assert record is not None
        assert record["sys_NumFragments"] == 2.0  # 미해석 종 제외

    def test_all_unresolvable_returns_none(self):
        extractor = StructuralFeatureExtractor()
        assert extractor.extract_from_counts({"NOPE": 1}, 293.0) is None
