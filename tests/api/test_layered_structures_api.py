"""API tests for layered-structure composer endpoints."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import (  # noqa: E402
    AmorphousCellModel,
    CrystalStructureModel,
    ExperimentModel,
    LayeredExperimentSourceModel,
    MetricModel,
)


def _write_minimal_data_file(path: Path, *, lx: float, ly: float, lz: float) -> None:
    lines = [
        "LAMMPS data file - test",
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
        "1 1 1 0.0 1.0 1.0 1.0",
        "2 1 1 0.0 2.0 2.0 2.0",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeJobManager:
    def submit(self, **_kwargs):
        return "job-layered-001"

    def get_task_id(self, _job_id):
        return "task-layered-001"


class TestLayeredStructuresAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_layered_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def _seed_sources(self, root: Path):
        crystal_data = root / "database" / "crystal_structures" / "crys_test01" / "crystal.data"
        crystal_failed_data = (
            root / "database" / "crystal_structures" / "crys_failed01" / "crystal.data"
        )
        amorphous_data = root / "database" / "amorphous_cells" / "amor_test01" / "amorphous.data"
        amorphous_running_data = (
            root / "database" / "amorphous_cells" / "amor_running01" / "amorphous.data"
        )
        binder_data = root / "compositions" / "A1" / "none" / "exp_test01" / "input" / "data.lammps"
        binder_running_data = (
            root / "compositions" / "A1" / "none" / "exp_running01" / "input" / "data.lammps"
        )
        _write_minimal_data_file(crystal_data, lx=40.0, ly=40.0, lz=16.0)
        _write_minimal_data_file(crystal_failed_data, lx=40.0, ly=40.0, lz=16.0)
        _write_minimal_data_file(amorphous_data, lx=40.0, ly=40.0, lz=12.0)
        _write_minimal_data_file(amorphous_running_data, lx=40.0, ly=40.0, lz=12.0)
        _write_minimal_data_file(binder_data, lx=40.0, ly=40.0, lz=18.0)
        _write_minimal_data_file(binder_running_data, lx=40.0, ly=40.0, lz=18.0)
        crystal_yaml = root / "data" / "molecules" / "crystal_structures.yaml"
        crystal_yaml.parent.mkdir(parents=True, exist_ok=True)
        crystal_yaml.write_text(
            yaml.safe_dump(
                {
                    "library": {"name": "crystal_structures"},
                    "directory": "crystal_structures",
                    "structures": [
                        {
                            "crystal_id": "crys_test01",
                            "name": "CrystalTest01",
                            "status": "ready",
                            "material": "SiO2",
                            "surface": "001",
                            "atom_count": 2,
                            "thickness_angstrom": 16.0,
                            "xy_size_angstrom": 40.0,
                            "hydroxylated": False,
                            "hydroxyl_density": 0.0,
                            "lammps_data_file_path": str(crystal_data),
                        },
                        {
                            "crystal_id": "crys_failed01",
                            "name": "CrystalFailed01",
                            "status": "failed",
                            "material": "SiO2",
                            "surface": "001",
                            "atom_count": 2,
                            "thickness_angstrom": 16.0,
                            "xy_size_angstrom": 40.0,
                            "hydroxylated": False,
                            "hydroxyl_density": 0.0,
                            "lammps_data_file_path": str(crystal_failed_data),
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        with session_scope() as session:
            session.query(CrystalStructureModel).filter(
                CrystalStructureModel.crystal_id.in_(["crys_test01", "crys_failed01"])
            ).delete(synchronize_session=False)
            session.query(AmorphousCellModel).filter(
                AmorphousCellModel.amorphous_id.in_(["amor_test01", "amor_running01"])
            ).delete(synchronize_session=False)
            session.query(ExperimentModel).filter(
                ExperimentModel.exp_id.in_(["exp_test01", "exp_running01"])
            ).delete(synchronize_session=False)

            session.add(
                CrystalStructureModel(
                    crystal_id="crys_test01",
                    name="CrystalTest01",
                    source_type="preset",
                    status="ready",
                    material="SiO2",
                    surface="001",
                    atom_count=2,
                    nx=1,
                    ny=1,
                    nz=1,
                    thickness_angstrom=16.0,
                    xy_size_angstrom=40.0,
                    hydroxylated=False,
                    hydroxyl_density=0.0,
                    lammps_data_file_path=str(crystal_data),
                )
            )
            session.add(
                CrystalStructureModel(
                    crystal_id="crys_failed01",
                    name="CrystalFailed01",
                    source_type="preset",
                    status="failed",
                    material="SiO2",
                    surface="001",
                    atom_count=2,
                    nx=1,
                    ny=1,
                    nz=1,
                    thickness_angstrom=16.0,
                    xy_size_angstrom=40.0,
                    hydroxylated=False,
                    hydroxyl_density=0.0,
                    lammps_data_file_path=str(crystal_failed_data),
                )
            )
            session.add(
                AmorphousCellModel(
                    amorphous_id="amor_test01",
                    name="AmorphousTest01",
                    status="ready",
                    components_json=[{"mol_id": "H2O", "weight_ratio": 100.0}],
                    component_count=1,
                    lx_angstrom=40.0,
                    ly_angstrom=40.0,
                    lz_angstrom=12.0,
                    target_density=1.0,
                    boundary_mode="ppp",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    atom_count=2,
                    lammps_data_file_path=str(amorphous_data),
                )
            )
            session.add(
                AmorphousCellModel(
                    amorphous_id="amor_running01",
                    name="AmorphousRunning01",
                    status="running",
                    components_json=[{"mol_id": "H2O", "weight_ratio": 100.0}],
                    component_count=1,
                    lx_angstrom=40.0,
                    ly_angstrom=40.0,
                    lz_angstrom=12.0,
                    target_density=1.0,
                    boundary_mode="ppp",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    atom_count=2,
                    lammps_data_file_path=str(amorphous_running_data),
                )
            )
            session.add(
                ExperimentModel(
                    exp_id="exp_test01",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
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
                    data_file_path=str(binder_data),
                    created_at=datetime.now(UTC),
                )
            )
            session.add(
                ExperimentModel(
                    exp_id="exp_running01",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    status="running",
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                    target_atoms=2,
                    actual_atoms=2,
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    seed=2,
                    data_file_path=str(binder_running_data),
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

    def test_layered_structure_preview_and_submit(self, client, monkeypatch, tmp_path):
        self._seed_sources(tmp_path)

        crystal_source_resp = client.get("/layered-structures/sources/crystal_structure?limit=20")
        assert crystal_source_resp.status_code == 200, crystal_source_resp.text
        crystal_items = crystal_source_resp.json()["items"]
        crystal_ids = {item["source_id"] for item in crystal_items}
        assert "crys_test01" in crystal_ids
        assert "crys_failed01" not in crystal_ids

        amorphous_source_resp = client.get("/layered-structures/sources/amorphous_cell?limit=20")
        assert amorphous_source_resp.status_code == 200, amorphous_source_resp.text
        amorphous_items = amorphous_source_resp.json()["items"]
        amorphous_ids = {item["source_id"] for item in amorphous_items}
        assert "amor_test01" in amorphous_ids
        assert "amor_running01" not in amorphous_ids

        binder_source_resp = client.get("/layered-structures/sources/binder_cell?limit=20")
        assert binder_source_resp.status_code == 200, binder_source_resp.text
        binder_items = binder_source_resp.json()["items"]
        binder_ids = {item["source_id"] for item in binder_items}
        assert "exp_test01" in binder_ids
        assert "exp_running01" not in binder_ids

        amorphous_all_resp = client.get(
            "/layered-structures/sources/amorphous_cell?limit=20&visibility=all"
        )
        assert amorphous_all_resp.status_code == 200, amorphous_all_resp.text
        amorphous_all_ids = {item["source_id"] for item in amorphous_all_resp.json()["items"]}
        assert "amor_test01" in amorphous_all_ids
        assert "amor_running01" in amorphous_all_ids

        preview_payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_test01"},
                {"source_type": "crystal_structure", "source_id": "crys_test01"},
            ],
            "xy_tolerance_pct": 5.0,
            "min_xy_to_z_ratio": 1.0,
        }
        preview_resp = client.post("/layered-structures/preview", json=preview_payload)
        assert preview_resp.status_code == 200, preview_resp.text
        preview_body = preview_resp.json()
        assert preview_body["n_atoms"] == 4
        assert len(preview_body["checks"]) >= 4

        monkeypatch.setattr("api.deps.get_job_manager", lambda: _FakeJobManager())
        submit_payload = {
            **preview_payload,
            "name": "LayeredSubmit01",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "z_vacuum_angstrom": 35.0,
            "seed": 9,
        }
        submit_resp = client.post("/layered-structures/submit", json=submit_payload)
        assert submit_resp.status_code == 200, submit_resp.text
        submit_body = submit_resp.json()
        assert submit_body["status"] == "queued"
        assert submit_body["job_id"] == "job-layered-001"
        assert submit_body["exp_id"]

    def test_layered_structure_preview_source_not_found(self, client):
        payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_missing"},
                {"source_type": "crystal_structure", "source_id": "crys_missing"},
            ],
        }
        resp = client.post("/layered-structures/preview", json=payload)
        assert resp.status_code == 404
        assert resp.json()["code"] == "E7001"

    def test_submit_with_tensile_enabled_uses_tensile_layer_chain(
        self, client, monkeypatch, tmp_path
    ):
        """tensile_enabled=True + run_tier='screening' → tensile_layer chain으로 처리."""
        self._seed_sources(tmp_path)
        monkeypatch.setattr("api.deps.get_job_manager", lambda: _FakeJobManager())

        submit_payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_test01"},
                {"source_type": "crystal_structure", "source_id": "crys_test01"},
            ],
            "name": "TensileLayerSubmit",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 42,
            "boundary_mode": "ppf",
            "tensile_enabled": True,
            "tensile_pull_velocity": 0.00005,
            "tensile_grip_thickness": 20.0,
            "tensile_max_strain": 0.5,
        }
        resp = client.post("/layered-structures/submit", json=submit_payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"

    def test_submit_with_tensile_enabled_accepts_tensile_stage_overrides(
        self, client, monkeypatch, tmp_path
    ):
        """tensile_enabled=True → annealing_cycles override가 tensile_layer chain에서 허용."""
        self._seed_sources(tmp_path)
        monkeypatch.setattr("api.deps.get_job_manager", lambda: _FakeJobManager())

        submit_payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_test01"},
                {"source_type": "crystal_structure", "source_id": "crys_test01"},
            ],
            "name": "TensileOverrideSubmit",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 43,
            "boundary_mode": "ppf",
            "tensile_enabled": True,
            "tensile_pull_velocity": 0.00005,
            "tensile_grip_thickness": 20.0,
            "tensile_max_strain": 0.5,
            "stage_durations": [
                {"stage_name": "annealing_cycles", "duration_ps": 1500},
                {"stage_name": "npt_equilibration", "duration_ps": 3000},
            ],
        }
        resp = client.post("/layered-structures/submit", json=submit_payload)
        assert resp.status_code == 200, resp.text

    def test_layered_structure_submit_rejects_non_ready_sources(
        self, client, monkeypatch, tmp_path
    ):
        self._seed_sources(tmp_path)
        monkeypatch.setattr("api.deps.get_job_manager", lambda: _FakeJobManager())

        submit_payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_running01"},
                {"source_type": "amorphous_cell", "source_id": "amor_test01"},
            ],
            "name": "LayeredSubmitNotReady",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 9,
        }
        resp = client.post("/layered-structures/submit", json=submit_payload)
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["code"] == "E1000"
        assert "blocked_sources" in body.get("details", {})

    def test_layered_preview_reports_crystal_orientation_checks(self, client, tmp_path):
        self._seed_sources(tmp_path)

        preview_payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "exp_test01"},
                {"source_type": "crystal_structure", "source_id": "crys_test01"},
                {"source_type": "binder_cell", "source_id": "exp_test01"},
            ],
            "xy_tolerance_pct": 5.0,
            "min_xy_to_z_ratio": 0.5,
            "inter_layer_gap_angstrom": 0.0,
        }

        resp = client.post("/layered-structures/preview", json=preview_payload)
        assert resp.status_code == 200, resp.text
        checks = {item["code"]: item for item in resp.json()["checks"]}

        assert checks["crystal_interface_orientation"]["status"] == "pass"
        assert checks["crystal_interface_orientation"]["details"]["flipped_layer_indices"] == [2]
        assert checks["crystal_dual_interface_limit"]["status"] == "warn"
        assert checks["crystal_dual_interface_limit"]["details"][
            "interior_crystal_layer_indices"
        ] == [2]

    def test_interface_molecule_cell_sources_returns_merged_yaml_and_db(
        self, client, monkeypatch, tmp_path
    ):
        """GET /layered-structures/sources/interface_molecule_cell returns
        merged YAML ifc_* and legacy DB amor_* sources under the canonical type."""
        from unittest.mock import patch

        self._seed_sources(tmp_path)

        # Mock list_interface_cells_for_sources to return a YAML-backed cell
        yaml_cell = {
            "cell_id": "ifc_yaml_test01",
            "name": "NaCl_d2.16_40x40x10",
            "status": "ready",
            "mol_id": "NaCl",
            "atom_count": 120,
            "molecule_count": 60,
            "target_density": 2.16,
            "boundary_mode": "ppf",
            "lx_angstrom": 40.0,
            "ly_angstrom": 40.0,
            "lz_angstrom": 10.0,
        }

        with patch(
            "features.interface_molecules.service.list_interface_cells_for_sources",
            return_value=[yaml_cell],
        ):
            resp = client.get("/layered-structures/sources/interface_molecule_cell?limit=20")

        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        source_ids = {item["source_id"] for item in items}

        # Both YAML ifc_* and legacy DB amor_* should appear
        assert "ifc_yaml_test01" in source_ids, f"YAML source missing; got {source_ids}"
        assert "amor_test01" in source_ids, f"Legacy DB source missing; got {source_ids}"

        # All items must carry the canonical source_type
        for item in items:
            assert item["source_type"] == "interface_molecule_cell", (
                f"Expected canonical source_type, got {item['source_type']} for {item['source_id']}"
            )


class TestLayeredSubmitQSValidation:
    """QS cross-field validation at API boundary."""

    def test_qs_force_avg_exceeds_relax_raises(self):
        """force_average_steps > relax_steps in QS → ValidationError."""
        from pydantic import ValidationError

        from api.schemas.structures import LayeredStructureSubmitRequest

        with pytest.raises(ValidationError, match="force_average_steps"):
            LayeredStructureSubmitRequest(
                layers=[
                    {"source_type": "binder_cell", "source_id": "test1"},
                    {"source_type": "crystal_structure", "source_id": "test2"},
                ],
                tensile_enabled=True,
                tensile_mode="quasi_static",
                tensile_relax_steps=1000,
                tensile_force_average_steps=2000,
            )

    def test_qs_valid_params_accepted(self):
        """force_average_steps <= relax_steps → no error."""
        from api.schemas.structures import LayeredStructureSubmitRequest

        req = LayeredStructureSubmitRequest(
            layers=[
                {"source_type": "binder_cell", "source_id": "test1"},
                {"source_type": "crystal_structure", "source_id": "test2"},
            ],
            tensile_enabled=True,
            tensile_mode="quasi_static",
            tensile_relax_steps=10000,
            tensile_force_average_steps=1000,
        )
        assert req.tensile_force_average_steps == 1000

    def test_continuous_mode_no_cross_check(self):
        """Continuous mode does not enforce force_avg <= relax."""
        from api.schemas.structures import LayeredStructureSubmitRequest

        req = LayeredStructureSubmitRequest(
            layers=[
                {"source_type": "binder_cell", "source_id": "test1"},
                {"source_type": "crystal_structure", "source_id": "test2"},
            ],
            tensile_enabled=True,
            tensile_mode="continuous",
            tensile_relax_steps=1000,
            tensile_force_average_steps=2000,
        )
        assert req.tensile_force_average_steps == 2000


class TestLayeredSubmitQSRoute:
    """Route-level 422 test: invalid QS payload via actual HTTP POST."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_qs_route.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def test_qs_invalid_payload_returns_422(self, client):
        """POST /layered-structures/submit with invalid QS params → 422."""
        payload = {
            "layers": [
                {"source_type": "binder_cell", "source_id": "b1"},
                {"source_type": "crystal_structure", "source_id": "c1"},
            ],
            "name": "QS_invalid",
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "seed": 1,
            "tensile_enabled": True,
            "tensile_mode": "quasi_static",
            "tensile_relax_steps": 1000,
            "tensile_force_average_steps": 2000,
        }
        resp = client.post("/layered-structures/submit", json=payload)
        assert resp.status_code == 422


class TestLayeredStructuresLibraryAPI:
    """Tests for GET /layered-structures library endpoint."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_layered_library.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def _seed_layered_experiment(self, *, exp_id="lay_test_01", status="completed"):
        with session_scope() as session:
            exp = ExperimentModel(
                exp_id=exp_id,
                status=status,
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                temperature_K=298.0,
                pressure_atm=1.0,
                target_atoms=5000,
                seed=42,
                comp_asphaltene_wt=0.0,
                comp_resin_wt=0.0,
                comp_aromatic_wt=0.0,
                comp_saturate_wt=0.0,
                metadata_json={"name": "Test Layered", "source": "layered_structures"},
            )
            session.add(exp)
            session.flush()

            for idx, (stype, sid, label) in enumerate(
                [
                    ("crystal_structure", "crys_01", "SiO2 slab"),
                    ("binder_cell", "binder_01", "AAA1 binder"),
                ]
            ):
                src = LayeredExperimentSourceModel(
                    exp_id=exp_id,
                    layer_index=idx,
                    source_type=stype,
                    source_id=sid,
                    label=label,
                )
                session.add(src)

            # Add a scalar metric
            metric = MetricModel(
                exp_id=exp_id,
                metric_name="tensile_strength",
                value=125.5,
                unit="MPa",
                namespace="mechanical",
            )
            session.add(metric)

    def test_library_returns_only_layered_experiments(self, client):
        """Only experiments with lineage rows appear in library."""
        # Seed one layered + one non-layered experiment
        self._seed_layered_experiment(exp_id="lay_01")
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="bulk_01",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=1,
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                )
            )

        resp = client.get("/layered-structures?status=completed")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["exp_id"] == "lay_01"

    def test_library_layers_ordered_by_index(self, client):
        self._seed_layered_experiment()
        resp = client.get("/layered-structures")
        assert resp.status_code == 200
        layers = resp.json()["items"][0]["layers"]
        assert len(layers) == 2
        assert layers[0]["layer_index"] == 0
        assert layers[1]["layer_index"] == 1
        assert layers[0]["source_type"] == "crystal_structure"
        assert layers[0]["source_id"] == "crys_01"

    def test_library_includes_metric_when_present(self, client):
        self._seed_layered_experiment(exp_id="lay_metric_01")
        resp = client.get("/layered-structures")
        item = resp.json()["items"][0]
        assert item["tensile_strength"] == 125.5
        # Metrics not seeded should be None
        assert item["elastic_modulus"] is None

    def test_library_name_falls_back_to_exp_id(self, client):
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="lay_noname_only",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=2,
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=0.0,
                    # metadata_json intentionally omitted — no "name" key
                )
            )
            session.add(
                LayeredExperimentSourceModel(
                    exp_id="lay_noname_only",
                    layer_index=0,
                    source_type="binder_cell",
                    source_id="b1",
                )
            )
        resp = client.get("/layered-structures")
        # Find the item with no metadata name
        noname_item = next(it for it in resp.json()["items"] if it["exp_id"] == "lay_noname_only")
        assert noname_item["name"] == "lay_noname_only"


class TestStressStrainAPI:
    """Tests for GET /experiments/{exp_id}/stress-strain."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_ss_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def test_stress_strain_returns_404_when_missing(self, client):
        resp = client.get("/experiments/nonexistent/stress-strain")
        assert resp.status_code == 404

    def test_stress_strain_returns_data_when_present(self, client, monkeypatch, tmp_path):
        """Mock ArrayStorage.load to return test curve data."""
        test_data = {
            "strain": [0.0, 0.01, 0.02, 0.03],
            "stress_MPa": [0.0, 50.0, 100.0, 75.0],
        }

        def _mock_load(self, metric_name, exp_id=None, **_kw):
            if metric_name == "stress_strain_curve":
                return test_data
            return None

        monkeypatch.setattr("metrics.array_storage.ArrayStorage.load", _mock_load)

        resp = client.get("/experiments/test_exp/stress-strain")
        assert resp.status_code == 200
        body = resp.json()
        assert body["exp_id"] == "test_exp"
        assert len(body["strain"]) == 4
        assert body["peak_index"] == 2
        assert body["peak_stress_MPa"] == 100.0

    def test_stress_strain_handles_length_mismatch(self, client, monkeypatch):
        """Mismatched array lengths should truncate, not crash."""
        mismatched = {
            "strain": [0.0, 0.01, 0.02],
            "stress_MPa": [0.0, 50.0, 100.0, 75.0, 60.0],  # longer than strain
        }

        def _mock_load(self, metric_name, exp_id=None, **_kw):
            if metric_name == "stress_strain_curve":
                return mismatched
            return None

        monkeypatch.setattr("metrics.array_storage.ArrayStorage.load", _mock_load)

        resp = client.get("/experiments/mismatch_exp/stress-strain")
        assert resp.status_code == 200
        body = resp.json()
        # Should truncate to shorter length (3)
        assert len(body["strain"]) == 3
        assert len(body["stress_MPa"]) == 3


class TestDeleteCleanupConfinement:
    """Verify delete cleanup respects workspace path boundaries."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_delete_confine.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def test_delete_removes_workspace_array_file(self, client, tmp_path):
        """Array file inside workspace is deleted on experiment delete."""
        arr_dir = tmp_path / "data" / "arrays" / "test_del"
        arr_dir.mkdir(parents=True)
        arr_file = arr_dir / "stress_strain_curve.parquet"
        arr_file.write_text("fake parquet data")

        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="test_del",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=99,
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=0.0,
                )
            )
            session.add(
                MetricModel(
                    exp_id="test_del",
                    metric_name="stress_strain_curve",
                    namespace="mechanical",
                    unit="[-,MPa]",
                    array_file_path=str(arr_file),
                )
            )

        resp = client.delete("/experiments/test_del")
        assert resp.status_code == 200
        assert not arr_file.exists(), "Array file should be deleted"

    def test_delete_ignores_out_of_workspace_path(self, client, tmp_path):
        """Array file outside workspace boundary is NOT deleted."""
        outside = Path("/tmp/_test_outside_workspace.parquet")
        outside.write_text("should not be deleted")

        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="test_escape",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=100,
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=0.0,
                )
            )
            session.add(
                MetricModel(
                    exp_id="test_escape",
                    metric_name="stress_strain_curve",
                    namespace="mechanical",
                    unit="[-,MPa]",
                    array_file_path=str(outside),
                )
            )

        resp = client.delete("/experiments/test_escape")
        assert resp.status_code == 200
        assert outside.exists(), "File outside workspace must NOT be deleted"
        outside.unlink(missing_ok=True)


class TestLibraryReadOnly:
    """Verify GET /layered-structures does not mutate DB."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_readonly.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def test_get_library_does_not_write_box_dims(self, client):
        """GET /layered-structures must not persist box_lx/ly/lz to DB."""
        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="lay_ro",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=77,
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=0.0,
                    # box_lx/ly/lz intentionally NULL
                )
            )
            session.add(
                LayeredExperimentSourceModel(
                    exp_id="lay_ro",
                    layer_index=0,
                    source_type="binder_cell",
                    source_id="b1",
                )
            )

        resp = client.get("/layered-structures")
        assert resp.status_code == 200

        # Verify DB was NOT mutated — box dims should still be NULL
        with session_scope() as session:
            exp = session.query(ExperimentModel).filter_by(exp_id="lay_ro").one()
            assert exp.box_lx is None, "GET must not mutate box_lx"
            assert exp.box_ly is None, "GET must not mutate box_ly"
            assert exp.box_lz is None, "GET must not mutate box_lz"

    def test_get_library_parses_box_from_file_without_db_write(self, client, tmp_path):
        """GET parses box from data file but does NOT persist to DB."""
        data_file = tmp_path / "layer_system.data"
        _write_minimal_data_file(data_file, lx=50.0, ly=50.0, lz=30.0)

        with session_scope() as session:
            session.add(
                ExperimentModel(
                    exp_id="lay_ro_file",
                    status="completed",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    temperature_K=298.0,
                    pressure_atm=1.0,
                    target_atoms=5000,
                    seed=78,
                    comp_asphaltene_wt=0.0,
                    comp_resin_wt=0.0,
                    comp_aromatic_wt=0.0,
                    comp_saturate_wt=0.0,
                    data_file_path=str(data_file),
                    # box_lx/ly/lz NULL — should be parsed from file
                )
            )
            session.add(
                LayeredExperimentSourceModel(
                    exp_id="lay_ro_file",
                    layer_index=0,
                    source_type="binder_cell",
                    source_id="b1",
                )
            )

        resp = client.get("/layered-structures")
        assert resp.status_code == 200

        # Response should include parsed box dims
        item = next(it for it in resp.json()["items"] if it["exp_id"] == "lay_ro_file")
        assert item["box_lx"] == pytest.approx(50.0, abs=0.1)
        assert item["box_lz"] == pytest.approx(30.0, abs=0.1)

        # But DB must NOT be mutated
        with session_scope() as session:
            exp = session.query(ExperimentModel).filter_by(exp_id="lay_ro_file").one()
            assert exp.box_lx is None, "GET must not persist box_lx to DB"
            assert exp.box_ly is None, "GET must not persist box_ly to DB"
            assert exp.box_lz is None, "GET must not persist box_lz to DB"
