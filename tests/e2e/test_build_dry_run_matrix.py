"""E2E Level 1: Build / Protocol Dry-Run Matrix (docs/WORKFLOW_VERIFICATION_PLAN.md §6 Level 1).

LAMMPS 없이 build / topology / protocol / preview 생성이 다양한 조합에서 깨지지
않는지 매트릭스로 검증한다. 외부 도구(packmol / antechamber)가 필수인 빌드 경계만
mock 하고, "조합이 깨지지 않음"에 집중한다. 라우터 → service → repository →
StructureBuilder / topology_helpers / 안정화 체인의 실제 경로는 최대한 실제로 탄다.

검증 슬라이스:
 1. batch binder-cell ``validate()`` 매트릭스
    (binder 2~3 × 온도 3 × aging 2, dry-run / 제출 안 함)
    → 응답의 total / new / duplicates / jobs 구조가 조합 수와 정합.
 2. 단일분자 배치 dry-run (대표 분자 3~4 × 온도 3)
    → 제출 경로(build/typing/charge ensure 경계)가 호출되되 LAMMPS 실행 안 됨;
      온도당 1 제출 규칙 유지.
 3. layered preview dry-run (source type 조합: crystal×binder, amorphous×binder,
    interface×binder) → preview 응답의 n_atoms / fail check 가 깨지지 않음.

Mock 경계: Celery/GPU 제출, dashboard GPU 조회, single-molecule FF/mol lookup,
amorphous typing/charge + MD 안정화, interface packmol/topology 만 mock.

공통 fixture / 상수는 ``tests/e2e/conftest.py`` 에서 가져온다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.e2e.conftest import (
    FF_TYPE,
    REPRESENTATIVE_BINDERS,
    REPRESENTATIVE_SINGLE_MOLECULES,
    SAMPLE_TEMPERATURES_K,
)


def _write_minimal_data_file(path: Path, *, lx: float, ly: float, lz: float) -> None:
    """2-atom full-style LAMMPS data file (안정화/토폴로지 경계 mock 출력용)."""
    lines = [
        "LAMMPS data file - dry-run matrix",
        "",
        "2 atoms",
        "0 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        "1 atom types",
        "0 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
        "1 12.011 # C",
        "",
        "Atoms # full",
        "",
        f"1 1 1 0.0 {lx * 0.25:.3f} {ly * 0.25:.3f} {lz * 0.5:.3f}",
        f"2 1 1 0.0 {lx * 0.75:.3f} {ly * 0.75:.3f} {lz * 0.5:.3f}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _no_ff_block():
    return patch(
        "forcefield.eligibility.collect_binder_ff_issues",
        return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
    )


async def _fake_precompute(_request):
    return SimpleNamespace(failed=0, cached=0, computed=1, details=[])


async def _fake_submit_molecule_experiment(_request, **kwargs):
    exp_id = kwargs.get("exp_id_override") or "amor_exp_drymatrix_fallback"
    return SimpleNamespace(exp_id=exp_id, job_id="job-amorphous-001", status="queued")


# ===========================================================================
# Slice 1: batch binder-cell validate() matrix (dry-run, no submission)
# ===========================================================================


class TestBatchValidateMatrix:
    """binder × 온도 × aging 조합에서 validate dry-run 이 일관된 잡 매트릭스를 만든다."""

    @pytest.mark.parametrize("binders", [REPRESENTATIVE_BINDERS[:2], REPRESENTATIVE_BINDERS[:3]])
    @pytest.mark.parametrize("aging", [("non_aging", "short_aging"), ("non_aging", "long_aging")])
    def test_validate_matrix_job_count_consistent(self, e2e_client, binders, aging):
        temps = list(SAMPLE_TEMPERATURES_K)  # 3 온도
        payload = {
            "binder_types": list(binders),
            "structure_sizes": ["X1"],
            "temperatures_k": temps,
            "aging_states": list(aging),
            "tier": "screening",
            "ff_type": FF_TYPE,
            "seed": 31337,
            "similar_existing_action": "unspecified",
        }
        with _no_ff_block():
            resp = e2e_client.post("/batch-job/binder-cell/validate", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        expected = len(binders) * len(temps) * len(aging)
        # dry-run: 모든 조합이 job 으로 펼쳐지고, 신규 DB 가 비었으니 전부 new.
        assert body["total"] == expected, body
        assert len(body["jobs"]) == expected, body
        assert body["new"] == expected, body
        assert body["duplicates"] == 0, body
        # validate 는 제출하지 않는다 → submitted == 0.
        assert body.get("submitted", 0) == 0, body
        # 각 job 의 축 값이 입력 도메인 안에 있어야 한다.
        for job in body["jobs"]:
            assert job["temperature_k"] in temps
            assert job["binder_type"] in binders
            assert job["aging_state"] in aging

    def test_validate_is_pure_dry_run_no_db_rows(self, e2e_client):
        """validate 호출은 어떤 ExperimentModel row 도 남기지 않는다 (half-write 방지)."""
        from database.connection import session_scope
        from database.models import ExperimentModel

        payload = {
            "binder_types": list(REPRESENTATIVE_BINDERS[:2]),
            "structure_sizes": ["X1"],
            "temperatures_k": list(SAMPLE_TEMPERATURES_K),
            "aging_states": ["non_aging", "short_aging"],
            "tier": "screening",
            "ff_type": FF_TYPE,
            "seed": 4242,
            "similar_existing_action": "unspecified",
        }
        with _no_ff_block():
            resp = e2e_client.post("/batch-job/binder-cell/validate", json=payload)
        assert resp.status_code == 200, resp.text

        with session_scope() as session:
            rows = session.query(ExperimentModel).all()
            assert rows == [], [r.exp_id for r in rows]


# ===========================================================================
# Slice 2: single-molecule batch dry-run (build/typing boundary reached)
# ===========================================================================


class TestSingleMoleculeDryRun:
    """대표 분자 × 온도 조합에서 단일분자 제출 경로가 깨지지 않고 온도당 1 제출."""

    def _patches(self, atom_count: int = 42):
        mol_db = SimpleNamespace(
            get=lambda _mol_id: SimpleNamespace(atom_count=atom_count),
            get_temperature_code=lambda _config, _temp: "0293",
        )
        return (
            patch("api.deps.get_molecule_db", return_value=mol_db),
            patch(
                "features.molecules.catalog.resolve_ff_hint",
                return_value={
                    "submit_ff_type": FF_TYPE,
                    "is_submittable": True,
                    "blocked_reason": None,
                    "ff_hint": "gaff2",
                    "ff_display_label": "GAFF2",
                },
            ),
        )

    @pytest.mark.parametrize("mol_id", REPRESENTATIVE_SINGLE_MOLECULES[:4])
    def test_single_molecule_temp_scan_does_not_break(self, e2e_client, mol_id):
        from database.connection import session_scope
        from database.models import ExperimentModel

        temps = list(SAMPLE_TEMPERATURES_K)  # 3 온도
        mol_db_patch, ff_patch = self._patches()
        with mol_db_patch, ff_patch:
            resp = e2e_client.post(
                "/experiments/single-molecule/batch",
                json={
                    "selected_mol_id": mol_id,
                    "temperatures_k": temps,
                    "ff_type": FF_TYPE,
                    "force_recompute": False,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 온도당 정확히 1 제출 (build/typing 경계 도달, LAMMPS 실행 없음).
        assert body["total"] == len(temps)
        assert body["submitted"] == len(temps), body
        assert body["skipped_existing"] == 0, body

        # 제출 경계(job manager)가 실제로 호출됐다 (LAMMPS 가 아니라 큐 제출까지).
        assert e2e_client.fake_job_manager.submit_calls

        with session_scope() as session:
            rows = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.study_type == "single_molecule_vacuum")
                .filter(ExperimentModel.additive_mol_id == mol_id)
                .all()
            )
            assert len(rows) == len(temps), [r.exp_id for r in rows]
            db_temps = sorted(float(r.temperature_K) for r in rows)
            assert db_temps == sorted(temps)


# ===========================================================================
# Slice 3: layered preview dry-run (source type combinations)
# ===========================================================================


class TestLayeredPreviewMatrix:
    """source 라이브러리 산출물 조합에서 layered preview 가 깨지지 않는다.

    source 생성은 실제 API(크리스탈/비정질/인터페이스)로 만들고(외부 도구 경계만 mock),
    완료된 binder_cell 실험은 DB 에 직접 시드한다. preview 는 실제 build 경로를 탄다.
    """

    def _create_crystal(self, client) -> dict:
        payload = {
            "name": "DryMatrixQuartz",
            "source_type": "preset",
            "material": "SiO2",
            "surface": "001",
            "thickness_angstrom": 8.0,
            "xy_size_angstrom": 12.0,
            "nx": 1,
            "ny": 1,
            "nz": 1,
            "hydroxylated": False,
            "hydroxyl_density": 4.6,
        }
        resp = client.post("/crystal-structures", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()
        crystal_id = created["crystal_id"]
        preview = client.get(f"/crystal-structures/{crystal_id}/preview")
        assert preview.status_code == 200, preview.text
        box = [float(v) for v in preview.json()["box_size"]]
        return {"crystal_id": crystal_id, "atom_count": int(created["atom_count"]), "box": box}

    def _seed_binder_cell(self, client, *, lx: float, ly: float) -> str:
        """완료된 binder_cell 실험을 직접 시드 (data file 포함)."""
        from database.connection import session_scope
        from database.models import ExperimentModel

        exp_id = "drymatrix_binder01"
        data_file = client.project_root / "compositions" / exp_id / "data.lammps"
        _write_minimal_data_file(data_file, lx=lx, ly=ly, lz=12.0)
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id=exp_id,
                    run_tier="screening",
                    ff_type=FF_TYPE,
                    study_type="bulk",
                    status="completed",
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                    target_atoms=2,
                    actual_atoms=2,
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    seed=1,
                    data_file_path=str(data_file),
                    created_at=datetime.now(UTC),
                )
            )
        return exp_id

    def _create_amorphous(self, client, *, lx: float, ly: float) -> str:
        payload = {
            "name": "DryMatrixAmorphous",
            "component_mol_id": "Ethanol",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": 12.0,
            "initial_density": 0.8,
            "boundary_mode": "ppf",
            "ff_type": FF_TYPE,
            "temperature_K": 298.0,
            "seed": 11,
        }
        with (
            patch(
                "features.amorphous_cells.service.precompute_typing_charge",
                _fake_precompute,
            ),
            patch(
                "features.amorphous_cells.service.submit_molecule_experiment",
                _fake_submit_molecule_experiment,
            ),
        ):
            resp = client.post("/amorphous-cells", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()
        amorphous_id = created["amorphous_id"]
        stab_exp_id = created["stabilization_exp_id"]

        from database.connection import session_scope
        from database.models import ExperimentModel

        data_file = client.project_root / "compositions" / stab_exp_id / "data.lammps"
        _write_minimal_data_file(data_file, lx=lx, ly=ly, lz=12.0)
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id=stab_exp_id,
                    run_tier="screening",
                    ff_type=FF_TYPE,
                    status="completed",
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=100.0,
                    target_atoms=2,
                    actual_atoms=2,
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    seed=11,
                    data_file_path=str(data_file),
                    created_at=datetime.now(UTC),
                )
            )
        # 상태 sync (queued → ready) 는 amorphous 목록 조회가 수행한다.
        list_resp = client.get("/amorphous-cells?limit=50&visibility=all")
        assert list_resp.status_code == 200, list_resp.text
        row = next(
            (i for i in list_resp.json()["items"] if i["amorphous_id"] == amorphous_id),
            None,
        )
        assert row is not None and row["status"] == "ready", row
        return amorphous_id

    def _create_interface_cell(self, client, monkeypatch, *, lx: float, ly: float) -> str:
        from builder.packmol_wrapper import PackmolResult, PackmolWrapper

        def _fake_pack(
            _self, molecules, output_file, total_mass_g_mol, box_dimensions, work_dir, **_kw
        ):
            bx, by, bz = box_dimensions
            lines = ["3", "mock packed interface cell"]
            for frac in (0.3, 0.5, 0.7):
                lines.append(f"O {bx * frac:.4f} {by * frac:.4f} {bz * 0.5:.4f}")
            Path(output_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
            return PackmolResult(
                success=True,
                output_file=Path(output_file),
                log="mock packmol",
                box_dimensions=box_dimensions,
            )

        def _fake_topology(
            _mol_path,
            _mol_id,
            _molecule_count,
            _packed_xyz_path,
            output_data_path,
            box_dimensions,
            *_args,
            **_kwargs,
        ):
            _write_minimal_data_file(
                Path(output_data_path),
                lx=float(box_dimensions[0]),
                ly=float(box_dimensions[1]),
                lz=float(box_dimensions[2]),
            )
            return Path(output_data_path)

        monkeypatch.setattr(PackmolWrapper, "pack", _fake_pack)
        monkeypatch.setattr(
            "builder.topology_helpers.generate_single_component_topology",
            _fake_topology,
        )
        payload = {
            "name": "DryMatrixWaterFilm",
            "mol_id": "H2O",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": 10.0,
            "target_density": 0.5,
            "boundary_mode": "ppf",
            "seed": 7,
        }
        resp = client.post("/interface-molecule-cells", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()
        assert created["status"] == "ready"
        return created["cell_id"]

    def test_preview_source_type_combinations(self, e2e_client, monkeypatch):
        """crystal×binder / amorphous×binder / interface×binder preview 전수.

        세 source 조합 모두 preview 가 200 + n_atoms 정합 + fail check 없음.
        """
        client = e2e_client
        crystal = self._create_crystal(client)
        lx, ly = crystal["box"][0], crystal["box"][1]

        binder_id = self._seed_binder_cell(client, lx=lx, ly=ly)
        amorphous_id = self._create_amorphous(client, lx=lx, ly=ly)
        interface_id = self._create_interface_cell(client, monkeypatch, lx=lx, ly=ly)

        # 각 조합: [non-crystal source(2 atoms)] + [crystal(actual atoms)].
        combos = {
            "crystal_x_binder": [
                {"source_type": "binder_cell", "source_id": binder_id},
                {"source_type": "crystal_structure", "source_id": crystal["crystal_id"]},
            ],
            "crystal_x_amorphous": [
                {"source_type": "amorphous_cell", "source_id": amorphous_id},
                {"source_type": "crystal_structure", "source_id": crystal["crystal_id"]},
            ],
            "crystal_x_interface": [
                {"source_type": "interface_molecule_cell", "source_id": interface_id},
                {"source_type": "crystal_structure", "source_id": crystal["crystal_id"]},
            ],
        }

        for label, layers in combos.items():
            preview_payload = {
                "layers": layers,
                "xy_tolerance_pct": 10.0,
                "min_xy_to_z_ratio": 0.2,
            }
            resp = client.post("/layered-structures/preview", json=preview_payload)
            assert resp.status_code == 200, f"{label}: {resp.text}"
            body = resp.json()
            # non-crystal source(2) + crystal(actual atoms) — 조합이 깨지지 않음.
            assert body["n_atoms"] == 2 + crystal["atom_count"], f"{label}: {body['n_atoms']}"
            failed = [c for c in body["checks"] if c["status"] == "fail"]
            assert not failed, f"{label}: preview checks failed: {failed}"
            assert len(body["layer_boundaries_z"]) >= 2, label
