"""E2E Level 3: Source-to-Source 연결 검증 (docs/WORKFLOW_VERIFICATION_PLAN.md §6).

구조 라이브러리 산출물이 다음 단계에서 실제 source로 재사용되는지 검증한다.

필수 체인:
1. ``POST /crystal-structures`` 생성 →
   ``GET /layered-structures/sources/crystal_structure`` 조회
2. ``POST /amorphous-cells`` 생성 →
   ``sources/amorphous_cell`` (+ canonical ``interface_molecule_cell`` alias) 조회
3. ``POST /interface-molecule-cells`` 생성 → detail / preview 조회
4. 생성된 source 선택 → ``POST /layered-structures/preview`` 성공
5. preview 성공 입력 → ``POST /layered-structures/submit`` 수락 + lineage row 저장

Mock 경계 (시뮬레이션 실행 / 외부 도구 경계에서만):
- Celery job 제출: ``api.deps.get_job_manager`` → ``_FakeJobManager``
- antechamber typing/charge precompute:
  ``features.amorphous_cells.service.precompute_typing_charge``
- MD 안정화 실행: ``features.amorphous_cells.service.submit_molecule_experiment``
  + 완료된 ``ExperimentModel`` row 직접 삽입 (실행 경계 시뮬레이션)
- Packmol 패킹: ``builder.packmol_wrapper.PackmolWrapper.pack``
- GAFF2 토폴로지 생성: ``builder.topology_helpers.generate_single_component_topology``

라우터 → service → repository → DB(SQLite)/YAML SSOT 경로는 전부 실제로 탄다.
LAMMPS / Celery / Packmol / antechamber 없이 통과해야 한다.

v01.05.x: barrel export 버그(EInterRecommendationResponse 미노출, v01.02.22~)는
이 테스트 작성 과정에서 발견되어 수정되었다. 테스트는 실제 barrel을 그대로 사용하고
나머지 경로는 전부 실제 코드로 검증한다.
"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
    """Write a 2-atom full-style LAMMPS data file (same shape as tests/api fixtures)."""
    lines = [
        "LAMMPS data file - lineage test",
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
    """Celery/GPU 실행 경계 mock: 제출 호출만 기록한다."""

    def __init__(self) -> None:
        self.submit_calls: list[dict] = []

    def submit(self, **kwargs):
        self.submit_calls.append(kwargs)
        return f"job-lineage-{len(self.submit_calls):03d}"

    def get_task_id(self, job_id):
        return f"task-{job_id}"

    def cancel_job(self, job_id):  # pragma: no cover - defensive
        return None


async def _fake_precompute(_request):
    """antechamber typing/charge 경계 mock (성공 응답)."""
    return SimpleNamespace(failed=0, cached=0, computed=1, details=[])


async def _fake_submit_molecule_experiment(_request, **kwargs):
    """MD 안정화 제출 경계 mock: 서비스가 넘긴 exp_id_override를 그대로 보존."""
    exp_id = kwargs.get("exp_id_override") or "amor_exp_lineage_fallback"
    return SimpleNamespace(exp_id=exp_id, job_id="job-amorphous-001", status="queued")


def _clear_singleton_caches() -> None:
    import api.deps as api_deps
    from features.interface_molecules.catalog import clear_molecule_info_cache

    api_deps.get_molecule_db.cache_clear()
    api_deps.get_aging_config.cache_clear()
    clear_molecule_info_cache()


class TestSourceLineageChain:
    """Level 3 source-to-source 연결 검증."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        # 격리 워크스페이스 + 분자 라이브러리 SSOT 복사 (MW lookup / MOL 파일용).
        molecules_src = REPO_ROOT / "data" / "molecules"
        if not molecules_src.exists():  # pragma: no cover - repo layout guard
            pytest.skip("data/molecules library not found in repository")
        shutil.copytree(
            molecules_src,
            tmp_path / "data" / "molecules",
            ignore=shutil.ignore_patterns("*.lock", "crystal_structures.yaml"),
        )
        # Curated FF artifact store 복사: preview의 fail-closed FF eligibility
        # gate (organic_curated_artifact route)를 실제 로직 그대로 통과시키기 위함.
        ff_artifacts_src = REPO_ROOT / "data" / "forcefield_artifacts"
        if ff_artifacts_src.exists():
            shutil.copytree(ff_artifacts_src, tmp_path / "data" / "forcefield_artifacts")

        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_source_lineage.db"
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
    # Chain step helpers
    # ------------------------------------------------------------------

    def _create_crystal_and_verify_source(self, client) -> dict:
        """Step 1: crystal 생성 → crystal_structure source 조회."""
        payload = {
            "name": "LineageQuartz",
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
        assert crystal_id.startswith("crys_")
        assert created["atom_count"] > 0

        detail_resp = client.get(f"/crystal-structures/{crystal_id}")
        assert detail_resp.status_code == 200, detail_resp.text
        assert detail_resp.json()["crystal_id"] == crystal_id

        preview_resp = client.get(f"/crystal-structures/{crystal_id}/preview")
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        assert preview["n_atoms"] > 0
        assert len(preview["box_size"]) == 3

        sources_resp = client.get("/layered-structures/sources/crystal_structure?limit=50")
        assert sources_resp.status_code == 200, sources_resp.text
        items = sources_resp.json()["items"]
        match = next((i for i in items if i["source_id"] == crystal_id), None)
        assert match is not None, f"crystal {crystal_id} missing from layer sources"
        assert match["source_type"] == "crystal_structure"
        assert match["status"] == "ready"

        return {
            "crystal_id": crystal_id,
            "atom_count": int(created["atom_count"]),
            "box_size": [float(v) for v in preview["box_size"]],
        }

    def _create_amorphous_and_verify_source(
        self, client, tmp_path: Path, *, lx: float, ly: float
    ) -> dict:
        """Step 2: amorphous 생성 → 안정화 완료(경계 mock) → amorphous_cell source 조회."""
        # NOTE: 컴포넌트는 base-id 그대로 curated artifact가 존재하는 단일 분자여야
        # 한다 (Ethanol.json). 바인더 분자(SA-Squalane 등)는 artifact가 aging prefix
        # (U-...)로 저장되는데 amorphous 서비스가 base-id로 정규화해 저장하므로
        # layered preview의 ff_compatibility fail-closed gate에 걸린다.
        lz = 12.0
        payload = {
            "name": "LineageAmorphous",
            "component_mol_id": "Ethanol",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": lz,
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
        assert amorphous_id.startswith("amor_")
        assert created["status"] == "queued"
        assert stabilization_exp_id, "stabilization exp_id lineage missing"

        # 음성 gating: 안정화 완료 전에는 library source로 노출되면 안 된다.
        early_resp = client.get("/layered-structures/sources/amorphous_cell?limit=50")
        assert early_resp.status_code == 200, early_resp.text
        early_ids = {i["source_id"] for i in early_resp.json()["items"]}
        assert amorphous_id not in early_ids, "non-ready amorphous cell leaked into sources"

        # 실행 경계 시뮬레이션: 안정화 실험을 완료 상태로 만든다.
        data_file = tmp_path / "compositions" / "lineage" / stabilization_exp_id / "data.lammps"
        _write_minimal_data_file(data_file, lx=lx, ly=ly, lz=lz)
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

        # 실험 상태 sync 경로 (queued → ready) 는 amorphous 목록 조회가 수행한다.
        list_resp = client.get("/amorphous-cells?limit=50&visibility=all")
        assert list_resp.status_code == 200, list_resp.text
        row = next(
            (i for i in list_resp.json()["items"] if i["amorphous_id"] == amorphous_id),
            None,
        )
        assert row is not None
        assert row["status"] == "ready"
        assert row["stabilization_exp_id"] == stabilization_exp_id

        sources_resp = client.get("/layered-structures/sources/amorphous_cell?limit=50")
        assert sources_resp.status_code == 200, sources_resp.text
        items = sources_resp.json()["items"]
        match = next((i for i in items if i["source_id"] == amorphous_id), None)
        assert match is not None, f"amorphous {amorphous_id} missing from legacy alias sources"
        assert match["status"] == "ready"

        # canonical interface_molecule_cell alias로도 동일 source가 조회돼야 한다.
        canonical_resp = client.get("/layered-structures/sources/interface_molecule_cell?limit=50")
        assert canonical_resp.status_code == 200, canonical_resp.text
        canonical_items = canonical_resp.json()["items"]
        canonical = next(
            (i for i in canonical_items if i["source_id"] == amorphous_id),
            None,
        )
        assert canonical is not None, "amorphous cell missing from canonical alias sources"
        assert canonical["source_type"] == "interface_molecule_cell"

        return {"amorphous_id": amorphous_id, "stabilization_exp_id": stabilization_exp_id}

    def _create_interface_cell_and_verify(
        self, client, monkeypatch, *, lx: float, ly: float
    ) -> dict:
        """Step 3: interface molecule cell 생성 → detail/preview → source 조회."""
        from builder.packmol_wrapper import PackmolResult, PackmolWrapper

        def _fake_pack(
            _self,
            molecules,
            output_file,
            total_mass_g_mol,
            box_dimensions,
            work_dir,
            **_kwargs,
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

        # 외부 도구 경계 mock: Packmol 바이너리 + antechamber 기반 토폴로지 생성.
        monkeypatch.setattr(PackmolWrapper, "pack", _fake_pack)
        monkeypatch.setattr(
            "builder.topology_helpers.generate_single_component_topology",
            _fake_topology,
        )

        lz = 10.0
        payload = {
            "name": "LineageWaterFilm",
            "mol_id": "H2O",
            "lx_angstrom": lx,
            "ly_angstrom": ly,
            "lz_angstrom": lz,
            "target_density": 0.5,
            "boundary_mode": "ppf",
            "seed": 7,
        }
        create_resp = client.post("/interface-molecule-cells", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        cell_id = created["cell_id"]
        assert cell_id.startswith("ifc_")
        assert created["status"] == "ready"
        assert created["mol_id"] == "H2O"

        detail_resp = client.get(f"/interface-molecule-cells/{cell_id}")
        assert detail_resp.status_code == 200, detail_resp.text
        assert detail_resp.json()["cell_id"] == cell_id

        preview_resp = client.get(f"/interface-molecule-cells/{cell_id}/preview")
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        assert preview["n_atoms"] == 2
        assert preview["box_size"][0] == pytest.approx(lx, abs=0.1)
        assert preview["box_size"][2] == pytest.approx(lz, abs=0.1)

        sources_resp = client.get("/layered-structures/sources/interface_molecule_cell?limit=50")
        assert sources_resp.status_code == 200, sources_resp.text
        items = sources_resp.json()["items"]
        match = next((i for i in items if i["source_id"] == cell_id), None)
        assert match is not None, f"interface cell {cell_id} missing from layer sources"
        assert match["source_type"] == "interface_molecule_cell"
        assert match["status"] == "ready"

        return {"cell_id": cell_id}

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_source_to_source_lineage_chain(self, client, monkeypatch, tmp_path):
        """crystal/amorphous/interface 생성물이 preview → submit까지 재사용된다."""
        crystal = self._create_crystal_and_verify_source(client)
        lx, ly = crystal["box_size"][0], crystal["box_size"][1]

        amorphous = self._create_amorphous_and_verify_source(client, tmp_path, lx=lx, ly=ly)
        interface = self._create_interface_cell_and_verify(client, monkeypatch, lx=lx, ly=ly)

        layers = [
            {"source_type": "amorphous_cell", "source_id": amorphous["amorphous_id"]},
            {"source_type": "crystal_structure", "source_id": crystal["crystal_id"]},
            {"source_type": "interface_molecule_cell", "source_id": interface["cell_id"]},
        ]
        preview_payload = {
            "layers": layers,
            "xy_tolerance_pct": 10.0,
            "min_xy_to_z_ratio": 0.2,
        }

        # Step 4: 생성된 source id들로 preview가 성공해야 한다.
        preview_resp = client.post("/layered-structures/preview", json=preview_payload)
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        # amorphous(2 atoms) + crystal(actual) + interface(2 atoms)
        assert preview["n_atoms"] == 2 + crystal["atom_count"] + 2
        failed_checks = [c for c in preview["checks"] if c["status"] == "fail"]
        assert not failed_checks, f"preview checks failed: {failed_checks}"
        assert len(preview["layer_boundaries_z"]) >= 2

        # Step 5: preview 성공 입력 그대로 submit이 수락돼야 한다.
        submit_payload = {
            **preview_payload,
            "name": "LineageLayeredSubmit",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 21,
        }
        submit_resp = client.post("/layered-structures/submit", json=submit_payload)
        assert submit_resp.status_code == 200, submit_resp.text
        submitted = submit_resp.json()
        assert submitted["status"] == "queued"
        assert submitted["exp_id"]
        assert submitted["job_id"] == "job-lineage-001"
        assert client.fake_job_manager.submit_calls, "job manager submit boundary not reached"

        # lineage row가 layer 순서/소스 id 그대로 DB에 보존돼야 한다.
        with session_scope() as session:
            rows = (
                session.query(LayeredExperimentSourceModel)
                .filter(LayeredExperimentSourceModel.exp_id == submitted["exp_id"])
                .order_by(LayeredExperimentSourceModel.layer_index)
                .all()
            )
            assert [r.source_id for r in rows] == [
                amorphous["amorphous_id"],
                crystal["crystal_id"],
                interface["cell_id"],
            ]
            assert rows[1].source_type == "crystal_structure"
            # legacy amorphous_cell 입력은 canonical alias로 정규화될 수 있다.
            assert rows[0].source_type in {"amorphous_cell", "interface_molecule_cell"}
            assert rows[2].source_type == "interface_molecule_cell"

        # 최종 소비 경로: layered library에서 lineage가 함께 조회된다.
        library_resp = client.get("/layered-structures")
        assert library_resp.status_code == 200, library_resp.text
        library_item = next(
            (i for i in library_resp.json()["items"] if i["exp_id"] == submitted["exp_id"]),
            None,
        )
        assert library_item is not None, "submitted layered experiment missing from library"
        library_source_ids = [layer["source_id"] for layer in library_item["layers"]]
        assert library_source_ids == [
            amorphous["amorphous_id"],
            crystal["crystal_id"],
            interface["cell_id"],
        ]

    def test_preview_with_unknown_source_ids_returns_404(self, client):
        """음성 케이스: 존재하지 않는 source id로 preview → 404 + E7001."""
        payload = {
            "layers": [
                {"source_type": "amorphous_cell", "source_id": "amor_does_not_exist"},
                {"source_type": "crystal_structure", "source_id": "crys_does_not_exist"},
            ],
        }
        resp = client.post("/layered-structures/preview", json=payload)
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "E7001"

    def test_sources_endpoint_rejects_unknown_source_type(self, client):
        """음성 케이스: 알 수 없는 source type 조회 → 422."""
        resp = client.get("/layered-structures/sources/not_a_source_type")
        assert resp.status_code == 422, resp.text
