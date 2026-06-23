"""구조 피처 스토어 + 혼합 학습 테스트 (P2/S3).

Pins:
  - 32 피처 + 라벨 + FF 태그 행 upsert (멱등)
  - source/force_field 필터 로드
  - GAFF2-only 필터 (향후 전환 경로)
  - 라벨 없는 target → None
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pyarrow")

from ml.structural_feature_store import (  # noqa: E402
    FF_COMPASS,
    FF_GAFF2,
    SOURCE_MDML,
    SOURCE_OUR,
    StructuralFeatureStore,
)
from ml.structural_features import STRUCTURAL_FEATURE_NAMES  # noqa: E402


def _feats(seed: int) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    return {n: float(rng.normal()) for n in STRUCTURAL_FEATURE_NAMES}


def _row(store, i, *, source, ff, label, group):
    return store.make_row(
        features=_feats(i),
        labels={"density": label},
        source=source,
        force_field=ff,
        group_key=group,
        row_key=f"{source}::{i}",
    )


class TestStoreUpsertLoad:
    def test_upsert_and_load(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        rows = [
            _row(store, i, source=SOURCE_OUR, ff=FF_GAFF2, label=0.9 + i * 0.01, group="none")
            for i in range(6)
        ]
        n = store.upsert(rows, source=SOURCE_OUR)
        assert n == 6
        ds = store.load_dataset("density")
        assert ds is not None
        assert ds.X.shape == (6, 32)
        assert ds.n_samples == 6
        assert set(ds.force_fields) == {FF_GAFF2}

    def test_upsert_idempotent_by_row_key(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        store.upsert(
            [_row(store, 0, source=SOURCE_OUR, ff=FF_GAFF2, label=1.0, group="g")],
            source=SOURCE_OUR,
        )
        # 동일 row_key 재삽입 → 덮어쓰기(중복 없음)
        store.upsert(
            [_row(store, 0, source=SOURCE_OUR, ff=FF_GAFF2, label=2.0, group="g")],
            source=SOURCE_OUR,
        )
        ds = store.load_dataset("density")
        assert ds.n_samples == 1
        assert ds.y[0] == 2.0

    def test_force_field_filter(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        store.upsert(
            [_row(store, i, source=SOURCE_MDML, ff=FF_COMPASS, label=1.0, group="LIG") for i in range(4)],
            source=SOURCE_MDML,
        )
        store.upsert(
            [_row(store, i, source=SOURCE_OUR, ff=FF_GAFF2, label=0.95, group="none") for i in range(3)],
            source=SOURCE_OUR,
        )
        mixed = store.load_dataset("density")
        assert mixed.n_samples == 7
        # GAFF2-only 필터 (향후 전환 경로)
        gaff = store.load_dataset("density", force_fields=[FF_GAFF2])
        assert gaff.n_samples == 3
        assert set(gaff.force_fields) == {FF_GAFF2}
        # source 필터
        mdml = store.load_dataset("density", sources=[SOURCE_MDML])
        assert mdml.n_samples == 4

    def test_missing_label_returns_none(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        store.upsert(
            [_row(store, 0, source=SOURCE_OUR, ff=FF_GAFF2, label=1.0, group="g")],
            source=SOURCE_OUR,
        )
        assert store.load_dataset("viscosity") is None

    def test_make_row_validates_features(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        with pytest.raises(ValueError):
            store.make_row(
                features={"node_MolWt_mean": 1.0},  # 불완전
                labels={"density": 1.0},
                source=SOURCE_OUR,
                force_field=FF_GAFF2,
                group_key="g",
                row_key="x",
            )

    def test_summary(self, tmp_path):
        store = StructuralFeatureStore(tmp_path)
        store.upsert(
            [_row(store, i, source=SOURCE_MDML, ff=FF_COMPASS, label=1.0, group="LIG") for i in range(5)],
            source=SOURCE_MDML,
        )
        summary = store.summary()["sources"][SOURCE_MDML]
        assert summary["rows"] == 5
        assert "density" in summary["labels"]
        assert summary["force_fields"] == [FF_COMPASS]


class TestTrainFromStore:
    def test_mixed_training_dry_run(self, tmp_path, monkeypatch):
        pytest.importorskip("xgboost")
        store = StructuralFeatureStore(tmp_path)
        # 학습 가능한 선형 라벨 (node_MolWt_mean=col0 기반)
        rows = []
        for i in range(60):
            f = _feats(i)
            label = 0.9 + 0.05 * f["node_MolWt_mean"]
            src = SOURCE_MDML if i % 2 else SOURCE_OUR
            ff = FF_COMPASS if src == SOURCE_MDML else FF_GAFF2
            rows.append(
                store.make_row(
                    features=f,
                    labels={"density": label},
                    source=src,
                    force_field=ff,
                    group_key=f"g{i % 5}",
                    row_key=f"{src}::{i}",
                )
            )
        store.upsert([r for r in rows if r["source"] == SOURCE_MDML], source=SOURCE_MDML)
        store.upsert([r for r in rows if r["source"] == SOURCE_OUR], source=SOURCE_OUR)

        from ml.structural_challenger import train_from_store

        # 기본(내부 전용): 외부(COMPASS) 행은 학습에서 제외 — our_production만 사용
        internal = train_from_store(
            session=object(), target="density", register=False, store=store
        )
        assert internal.targets_trained == ["density"]
        internal_total = internal.training_samples + internal.holdout_samples
        assert internal_total == 30  # SOURCE_OUR 30건만 (전체 60건 아님)

        # 명시적 외부 옵트인: 혼합(COMPASS+우리) 전체 사용
        mixed = train_from_store(
            session=object(),
            target="density",
            register=False,
            store=store,
            allow_external=True,
        )
        mixed_total = mixed.training_samples + mixed.holdout_samples
        assert mixed_total == 60  # 전체 60건

    def test_empty_store_graceful(self, tmp_path):
        from ml.structural_challenger import train_from_store

        store = StructuralFeatureStore(tmp_path)
        out = train_from_store(
            session=object(), target="density", register=False, store=store
        )
        assert out.targets_trained == []
        assert any("no/insufficient" in n for n in out.notes)

    def test_store_path_runs_compare_promote(self, tmp_path, monkeypatch):
        # R1 회귀: store 경로도 register→compare→promote를 거쳐야 함
        # (이전엔 promote 블록이 누락돼 영구 challenger).
        pytest.importorskip("xgboost")
        store = StructuralFeatureStore(tmp_path)
        rows = []
        for i in range(40):
            f = _feats(i)
            rows.append(
                store.make_row(
                    features=f, labels={"density": 0.9 + 0.05 * f["node_MolWt_mean"]},
                    source=SOURCE_OUR, force_field=FF_GAFF2,
                    group_key=f"g{i % 4}", row_key=f"our::{i}",
                )
            )
        store.upsert(rows, source=SOURCE_OUR)

        called = {"register": False, "compare": False}

        class _FakeRegistry:
            def __init__(self, session):
                pass

            def register_model(self, predictor, **kw):
                called["register"] = True
                return type("Row", (), {"version_id": "v7-test"})()

            def get_champion_predictor(self):
                return None  # cold-start → 비교 스킵, promote 없음

        monkeypatch.setattr("ml.model_registry.ModelRegistry", _FakeRegistry)
        from ml.structural_challenger import train_from_store

        out = train_from_store(
            session=object(), target="density", register=True, store=store
        )
        # register 경로가 호출됨 + cold-start note (compare/promote 경로 진입 증거)
        assert called["register"] is True
        assert out.version_id == "v7-test"
        assert any("cold-start" in n for n in out.notes)


class TestTransferBenchmark:
    def test_three_strategies_same_holdout(self, tmp_path):
        pytest.importorskip("xgboost")
        from ml.structural_challenger import benchmark_transfer_strategies

        store = StructuralFeatureStore(tmp_path)
        rows_g, rows_c = [], []
        for i in range(40):
            f = _feats(i)
            label = 0.9 + 0.05 * f["node_MolWt_mean"]
            rows_g.append(
                store.make_row(
                    features=f, labels={"density": label},
                    source=SOURCE_OUR, force_field=FF_GAFF2,
                    group_key=f"g{i % 4}", row_key=f"our::{i}",
                )
            )
        for i in range(80):
            f = _feats(1000 + i)
            label = 0.9 + 0.05 * f["node_MolWt_mean"] + 0.01  # FF offset
            rows_c.append(
                store.make_row(
                    features=f, labels={"density": label},
                    source=SOURCE_MDML, force_field=FF_COMPASS,
                    group_key="base", row_key=f"mdml::{i}",
                )
            )
        store.upsert(rows_g, source=SOURCE_OUR)
        store.upsert(rows_c, source=SOURCE_MDML)

        out = benchmark_transfer_strategies(store, target="density", n_estimators=50)
        assert set(out["strategies"]) == {"gaff2_only", "mixed", "finetune"}
        assert out["winner"] in out["strategies"]
        assert out["holdout_n"] > 0
        # 모든 전략이 동일 holdout에서 평가됨 (필드 일관성)
        assert out["train_gaff2_n"] + out["holdout_n"] == 40

    def test_insufficient_gaff2_graceful(self, tmp_path):
        from ml.structural_challenger import benchmark_transfer_strategies

        store = StructuralFeatureStore(tmp_path)
        out = benchmark_transfer_strategies(store, target="density")
        assert "error" in out
