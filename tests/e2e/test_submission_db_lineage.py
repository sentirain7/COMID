"""E2E Level 2: Submission + DB Lineage (docs/WORKFLOW_VERIFICATION_PLAN.md §6).

API 제출 후 실제 DB row / queue metadata / study_type / lineage 가 요청과 일치하는지
라우터 → service → repository → SQLite 경로로 검증한다. Celery / GPU / LAMMPS /
Packmol / antechamber 만 mock 하고, DB 저장 및 lineage 생성은 전부 실제 코드로 탄다.

검증 시나리오 (각각 제출 후 실제 DB row 를 query 해 단언):
1. 단일 실험 ``POST /experiments`` → ``ExperimentModel`` row 1개,
   study_type=="bulk", ff_type/run_tier/temperature_K 일치, status=="queued",
   celery_task_id 설정.
2. 배치 binder-cell ``POST /batch-job/binder-cell`` (binder 2 × temp 2 = 4) →
   row 수 == 조합 수, 각 row 의 temperature_K / run_tier / ff_type 일치, 전부 queued.
3. 단일분자 배치 ``POST /experiments/single-molecule/batch`` (temp N개) →
   study_type=="single_molecule_vacuum" row 가 N개 (실제 규칙: temp 당 1 row),
   temperature 분포 일치.
4. layered 제출 ``POST /layered-structures/submit`` (crystal+amorphous+interface) →
   ``LayeredExperimentSourceModel`` lineage 가 layer 순서/source_id 보존,
   ``ExperimentModel.study_type`` == "layer_bulkff".
5. 중복 제출: ``/experiments`` 동일 입력 재제출 → seed-shift 로 별개 exp_id row 생성
   (실제 코드: ``_resolve_unique_exp_id`` 가 collision 시 seed 증가).
6. 유사 실험: completed 실험을 seed 한 뒤 batch-job binder-cell ``validate`` →
   similar_existing / similar_experiment_ids / requires_similarity_decision 가
   응답에 반영. ``UNSPECIFIED`` 액션으로 ``create`` 하면 422 거절.

Mock 경계 (시뮬레이션 / 외부 도구 경계에서만):
- Celery job 제출: ``api.deps.get_job_manager`` → ``_FakeJobManager``
- antechamber typing/charge precompute (amorphous):
  ``features.amorphous_cells.service.precompute_typing_charge``
- MD 안정화 실행 (amorphous):
  ``features.amorphous_cells.service.submit_molecule_experiment``
- Packmol / GAFF2 토폴로지 (interface molecule cell):
  ``builder.packmol_wrapper.PackmolWrapper.pack`` /
  ``builder.topology_helpers.generate_single_component_topology``
- single-molecule FF resolution / mol lookup: ``resolve_ff_hint`` /
  ``api.deps.get_molecule_db`` (FF gate 통과 + atom_count 제공)
"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from config.settings import reset_settings  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import (  # noqa: E402
    ExperimentModel,
    LayeredExperimentSourceModel,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_minimal_data_file(path: Path, *, lx: float, ly: float, lz: float) -> None:
    """Write a 2-atom full-style LAMMPS data file (same shape as lineage fixtures)."""
    lines = [
        "LAMMPS data file - submission lineage test",
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


class _FakeJobManager:
    """Celery/GPU 실행 경계 mock: 제출 호출만 기록하고 task id 를 부여한다."""

    def __init__(self) -> None:
        self.submit_calls: list[dict] = []

    def submit(self, **kwargs):
        self.submit_calls.append(kwargs)
        return f"job-sub-{len(self.submit_calls):03d}"

    def get_task_id(self, job_id):
        return f"task-{job_id}"

    def cancel_job(self, job_id):  # pragma: no cover - defensive
        return None


async def _fake_precompute(_request):
    """antechamber typing/charge 경계 mock (성공 응답)."""
    return SimpleNamespace(failed=0, cached=0, computed=1, details=[])


async def _fake_submit_molecule_experiment(_request, **kwargs):
    """MD 안정화 제출 경계 mock: 서비스가 넘긴 exp_id_override 를 그대로 보존."""
    exp_id = kwargs.get("exp_id_override") or "amor_exp_sublineage_fallback"
    return SimpleNamespace(exp_id=exp_id, job_id="job-amorphous-001", status="queued")


def _clear_singleton_caches() -> None:
    import api.deps as api_deps
    from features.interface_molecules.catalog import clear_molecule_info_cache

    api_deps.get_molecule_db.cache_clear()
    api_deps.get_aging_config.cache_clear()
    clear_molecule_info_cache()


class TestSubmissionDbLineage:
    """Level 2 submission + DB lineage 검증."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        # 격리 워크스페이스 + 분자 라이브러리 SSOT 복사 (binder/single/additive lookup).
        molecules_src = REPO_ROOT / "data" / "molecules"
        if not molecules_src.exists():  # pragma: no cover - repo layout guard
            pytest.skip("data/molecules library not found in repository")
        shutil.copytree(
            molecules_src,
            tmp_path / "data" / "molecules",
            ignore=shutil.ignore_patterns("*.lock", "crystal_structures.yaml"),
        )
        # Curated FF artifact store 복사: fail-closed FF eligibility gate 를
        # 실제 로직 그대로 통과시키기 위함 (layered/batch FF compatibility).
        ff_artifacts_src = REPO_ROOT / "data" / "forcefield_artifacts"
        if ff_artifacts_src.exists():
            shutil.copytree(ff_artifacts_src, tmp_path / "data" / "forcefield_artifacts")

        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_submission_db_lineage.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        fake_job_manager = _FakeJobManager()
        monkeypatch.setattr("api.deps.get_job_manager", lambda: fake_job_manager)
        monkeypatch.setattr(
            "config.dashboard_settings.load_dashboard_settings",
            lambda: {"selected_gpus": []},
        )
        # 시뮬레이션 실행 경계 mock (amorphous 안정화 체인).
        monkeypatch.setattr(
            "features.amorphous_cells.service.precompute_typing_charge",
            _fake_precompute,
        )
        monkeypatch.setattr(
            "features.amorphous_cells.service.submit_molecule_experiment",
            _fake_submit_molecule_experiment,
        )

        close_db()
        reset_settings()
        _clear_singleton_caches()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            c.fake_job_manager = fake_job_manager  # type: ignore[attr-defined]
            yield c
        close_db()
        reset_settings()
        _clear_singleton_caches()

    # ------------------------------------------------------------------
    # Scenario 1: single bulk experiment
    # ------------------------------------------------------------------

    def test_single_experiment_persists_bulk_row(self, client):
        """``POST /experiments`` → 1 bulk row with request-matching fields + task id."""
        payload = {
            "composition": {
                "asphaltene_wt": 0.2,
                "resin_wt": 0.3,
                "aromatic_wt": 0.35,
                "saturate_wt": 0.15,
            },
            "target_atoms": 5000,
            "temperature_K": 313.0,
            "pressure_atm": 1.0,
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "seed": 4242,
        }
        resp = client.post("/experiments", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        exp_id = body["exp_id"]
        assert body["status"] == "queued"
        assert body["job_id"] == "job-sub-001"
        assert client.fake_job_manager.submit_calls, "job manager submit boundary not reached"

        with session_scope() as session:
            rows = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).all()
            assert len(rows) == 1
            row = rows[0]
            assert row.study_type == "bulk"
            assert row.ff_type == "bulk_ff_gaff2"
            assert row.run_tier == "screening"
            assert row.temperature_K == pytest.approx(313.0)
            assert row.target_atoms == 5000
            assert row.status in {"queued", "pending"}
            # celery_task_id wired from the fake job manager's get_task_id().
            assert row.celery_task_id == f"task-{body['job_id']}"

    # ------------------------------------------------------------------
    # Scenario 2: batch binder-cell (combination count)
    # ------------------------------------------------------------------

    def test_batch_binder_cell_creates_combination_rows(self, client):
        """``POST /batch-job/binder-cell`` (2 binders × 2 temps) → 4 queued rows."""
        binder_types = ["AAA1", "AAK1"]
        temperatures = [293.0, 313.0]
        payload = {
            "binder_types": binder_types,
            "structure_sizes": ["X1"],
            "temperatures_k": temperatures,
            "aging_states": ["non_aging"],
            "tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "seed": 7777,
            "similar_existing_action": "unspecified",
        }
        # FF eligibility gate → no-blocked so the runner actually submits.
        with patch(
            "forcefield.eligibility.collect_binder_ff_issues",
            return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
        ):
            resp = client.post("/batch-job/binder-cell", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        expected = len(binder_types) * len(temperatures)  # 1 size × 1 aging × 1 seed
        assert body["total"] == expected, body
        assert body["submitted"] == expected, body
        assert body["new"] == expected, body
        submitted_exp_ids = [j["exp_id"] for j in body["jobs"] if j["status"] == "submitted"]
        assert len(submitted_exp_ids) == expected

        with session_scope() as session:
            rows = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id.in_(submitted_exp_ids))
                .all()
            )
            assert len(rows) == expected
            for row in rows:
                assert row.run_tier == "screening"
                assert row.ff_type == "bulk_ff_gaff2"
                assert row.study_type == "bulk"
                assert row.status in {"queued", "pending"}
                assert row.temperature_K in temperatures
            # temperature distribution: each temp appears once per binder (2 binders).
            temp_counts: dict[float, int] = {}
            for row in rows:
                temp_counts[float(row.temperature_K)] = (
                    temp_counts.get(float(row.temperature_K), 0) + 1
                )
            assert temp_counts == {293.0: 2, 313.0: 2}, temp_counts

    # ------------------------------------------------------------------
    # Scenario 3: single-molecule batch (temp-per-row rule)
    # ------------------------------------------------------------------

    def test_single_molecule_batch_creates_one_row_per_temperature(self, client):
        """``/experiments/single-molecule/batch`` (3 temps) → 3 vacuum rows.

        실제 규칙(features/experiments/single_molecule.py): 온도당 정확히 1 row,
        study_type=="single_molecule_vacuum", additive_mol_id==mol_id.
        """
        mol_id = "U-AS-Thio"
        temperatures = [293.0, 313.0, 333.0]
        payload = {
            "selected_mol_id": mol_id,
            "temperatures_k": temperatures,
            "ff_type": "bulk_ff_gaff2",
            "force_recompute": False,
        }
        # FF resolution (server SSOT) + mol lookup are mocked: keep DB writes real.
        mol_db = SimpleNamespace(
            get=lambda _mol_id: SimpleNamespace(atom_count=42),
            get_temperature_code=lambda _config, _temp: "0293",
        )
        with (
            patch("api.deps.get_molecule_db", return_value=mol_db),
            patch(
                "features.molecules.catalog.resolve_ff_hint",
                return_value={
                    "submit_ff_type": "bulk_ff_gaff2",
                    "is_submittable": True,
                    "blocked_reason": None,
                    "ff_hint": "gaff2",
                    "ff_display_label": "GAFF2",
                },
            ),
        ):
            resp = client.post("/experiments/single-molecule/batch", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == len(temperatures)
        assert body["submitted"] == len(temperatures), body
        assert body["skipped_existing"] == 0, body
        submitted_ids = [it["exp_id"] for it in body["items"] if it["status"] == "submitted"]
        assert len(submitted_ids) == len(temperatures)

        with session_scope() as session:
            rows = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.study_type == "single_molecule_vacuum")
                .all()
            )
            assert len(rows) == len(temperatures), [r.exp_id for r in rows]
            for row in rows:
                assert row.additive_mol_id == mol_id
                assert row.status in {"queued", "pending"}
            db_temps = sorted(float(r.temperature_K) for r in rows)
            assert db_temps == sorted(temperatures)

    # ------------------------------------------------------------------
    # Scenario 4: layered submit lineage + study_type
    # ------------------------------------------------------------------

    def _create_crystal(self, client) -> dict:
        payload = {
            "name": "SubLineageQuartz",
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
        create_resp = client.post("/crystal-structures", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        crystal_id = created["crystal_id"]
        preview_resp = client.get(f"/crystal-structures/{crystal_id}/preview")
        assert preview_resp.status_code == 200, preview_resp.text
        box = [float(v) for v in preview_resp.json()["box_size"]]
        return {"crystal_id": crystal_id, "atom_count": int(created["atom_count"]), "box": box}

    def _create_amorphous(self, client, tmp_path: Path, *, lx: float, ly: float) -> dict:
        payload = {
            "name": "SubLineageAmorphous",
            "component_mol_id": "Ethanol",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": 12.0,
            "initial_density": 0.8,
            "boundary_mode": "ppf",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "seed": 11,
        }
        create_resp = client.post("/amorphous-cells", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        amorphous_id = created["amorphous_id"]
        stabilization_exp_id = created["stabilization_exp_id"]

        # 실행 경계 시뮬레이션: 안정화 실험을 완료 상태로 만든다 (ready 전환 트리거).
        data_file = tmp_path / "compositions" / "sublineage" / stabilization_exp_id / "data.lammps"
        _write_minimal_data_file(data_file, lx=lx, ly=ly, lz=12.0)
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id=stabilization_exp_id,
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
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
        assert row is not None and row["status"] == "ready"
        return {"amorphous_id": amorphous_id}

    def _create_interface_cell(self, client, monkeypatch, *, lx: float, ly: float) -> dict:
        from builder.packmol_wrapper import PackmolResult, PackmolWrapper

        def _fake_pack(
            _self, molecules, output_file, total_mass_g_mol, box_dimensions, work_dir, **_kwargs
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
            "name": "SubLineageWaterFilm",
            "mol_id": "H2O",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": 10.0,
            "target_density": 0.5,
            "boundary_mode": "ppf",
            "seed": 7,
        }
        create_resp = client.post("/interface-molecule-cells", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        assert created["status"] == "ready"
        return {"cell_id": created["cell_id"]}

    def test_layered_submit_preserves_lineage_and_study_type(self, client, monkeypatch, tmp_path):
        """layered submit → LayeredExperimentSourceModel lineage 순서/source_id 보존,
        ExperimentModel.study_type == 'layer_bulkff'."""
        crystal = self._create_crystal(client)
        lx, ly = crystal["box"][0], crystal["box"][1]
        amorphous = self._create_amorphous(client, tmp_path, lx=lx, ly=ly)
        interface = self._create_interface_cell(client, monkeypatch, lx=lx, ly=ly)

        layers = [
            {"source_type": "amorphous_cell", "source_id": amorphous["amorphous_id"]},
            {"source_type": "crystal_structure", "source_id": crystal["crystal_id"]},
            {"source_type": "interface_molecule_cell", "source_id": interface["cell_id"]},
        ]
        submit_payload = {
            "layers": layers,
            "xy_tolerance_pct": 10.0,
            "min_xy_to_z_ratio": 0.2,
            "name": "SubLineageLayeredSubmit",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 21,
        }
        submit_resp = client.post("/layered-structures/submit", json=submit_payload)
        assert submit_resp.status_code == 200, submit_resp.text
        submitted = submit_resp.json()
        exp_id = submitted["exp_id"]
        assert submitted["status"] == "queued"

        with session_scope() as session:
            exp = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
            assert exp is not None
            assert exp.study_type == "layer_bulkff"
            assert exp.run_tier == "screening"
            assert exp.ff_type == "bulk_ff_gaff2"
            assert exp.status in {"queued", "pending"}

            lineage = (
                session.query(LayeredExperimentSourceModel)
                .filter(LayeredExperimentSourceModel.exp_id == exp_id)
                .order_by(LayeredExperimentSourceModel.layer_index)
                .all()
            )
            assert [r.source_id for r in lineage] == [
                amorphous["amorphous_id"],
                crystal["crystal_id"],
                interface["cell_id"],
            ]
            assert lineage[1].source_type == "crystal_structure"
            # legacy amorphous_cell 입력은 canonical alias 로 정규화될 수 있다.
            assert lineage[0].source_type in {"amorphous_cell", "interface_molecule_cell"}
            assert lineage[2].source_type == "interface_molecule_cell"

    # ------------------------------------------------------------------
    # Scenario 5: duplicate submission → seed-shifted distinct row
    # ------------------------------------------------------------------

    def test_duplicate_experiment_submission_shifts_seed(self, client):
        """동일 입력 재제출 → ``_resolve_unique_exp_id`` 가 collision 시 seed 를 증가시켜
        별개 exp_id row 를 생성한다 (409 가 아닌 seed-shift idempotency)."""
        payload = {
            "composition": {
                "asphaltene_wt": 0.2,
                "resin_wt": 0.3,
                "aromatic_wt": 0.35,
                "saturate_wt": 0.15,
            },
            "target_atoms": 5000,
            "temperature_K": 293.0,
            "pressure_atm": 1.0,
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "seed": 9001,
        }
        resp1 = client.post("/experiments", json=payload)
        assert resp1.status_code == 200, resp1.text
        resp2 = client.post("/experiments", json=payload)
        assert resp2.status_code == 200, resp2.text

        exp1 = resp1.json()["exp_id"]
        exp2 = resp2.json()["exp_id"]
        assert exp1 != exp2, "duplicate submit must seed-shift to a distinct exp_id"

        with session_scope() as session:
            rows = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id.in_([exp1, exp2]))
                .all()
            )
            assert len(rows) == 2
            seeds = sorted(int(r.seed) for r in rows)
            # base seed 9001 → collision → 9002 (offset +1).
            assert seeds == [9001, 9002], seeds

    # ------------------------------------------------------------------
    # Scenario 6: similar-existing detection on batch validate
    # ------------------------------------------------------------------

    def _seed_completed_similar(self, *, temperature_k: float) -> None:
        """Seed a completed AAA1/non_aging experiment that the batch validate path
        should flag as a similar existing experiment."""
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id=f"similar_seed_{int(temperature_k)}",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    study_type="bulk",
                    status="completed",
                    comp_asphaltene_wt=11.1,
                    comp_resin_wt=44.4,
                    comp_aromatic_wt=33.3,
                    comp_saturate_wt=11.1,
                    target_atoms=100000,
                    temperature_K=temperature_k,
                    pressure_atm=1.0,
                    seed=1,
                    additive_mol_id=None,
                    additive_wt=0.0,
                    metadata_json={
                        "binder_type": "AAA1",
                        "aging_state": "non_aging",
                    },
                    created_at=datetime.now(UTC),
                )
            )

    def test_batch_validate_flags_similar_existing(self, client):
        """completed 유사 실험이 있으면 batch validate 가 similar_existing /
        similar_experiment_ids / requires_similarity_decision 를 반영하고,
        UNSPECIFIED 액션으로 create 하면 400(E1007, INVALID_REQUEST)으로 거절된다."""
        temp = 293.0
        self._seed_completed_similar(temperature_k=temp)

        payload = {
            "binder_types": ["AAA1"],
            "structure_sizes": ["X1"],
            "temperatures_k": [temp],
            "aging_states": ["non_aging"],
            "tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "seed": 5151,
            "similar_existing_action": "unspecified",
        }
        with patch(
            "forcefield.eligibility.collect_binder_ff_issues",
            return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
        ):
            validate_resp = client.post("/batch-job/binder-cell/validate", json=payload)
        assert validate_resp.status_code == 200, validate_resp.text
        vbody = validate_resp.json()
        assert vbody["requires_similarity_decision"] is True, vbody
        assert vbody["similar_job_count"] >= 1, vbody
        flagged = [j for j in vbody["jobs"] if j["similar_existing"]]
        assert flagged, vbody
        assert "similar_seed_293" in flagged[0]["similar_experiment_ids"], flagged[0]

        # create with unspecified action must be rejected (decision required).
        # 실제 코드: runner.submit() 가 ContractError(INVALID_REQUEST) → HTTP 400 / E1007.
        with patch(
            "forcefield.eligibility.collect_binder_ff_issues",
            return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
        ):
            create_resp = client.post("/batch-job/binder-cell", json=payload)
        assert create_resp.status_code == 400, create_resp.text
        assert create_resp.json()["code"] == "E1007", create_resp.text

        # 거절된 batch 는 어떤 새 row 도 남기지 않아야 한다 (half-write 방지).
        with session_scope() as session:
            new_rows = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.status.in_(["queued", "pending"]))
                .filter(~ExperimentModel.exp_id.like("similar_seed_%"))
                .all()
            )
            assert new_rows == [], [r.exp_id for r in new_rows]
