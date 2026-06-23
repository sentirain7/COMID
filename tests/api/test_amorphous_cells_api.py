"""API tests for amorphous cell library endpoints."""

import shutil
from contextlib import asynccontextmanager

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from common.pathing import get_amorphous_cell_path  # noqa: E402
from database.connection import close_db  # noqa: E402
from database.repositories.amorphous_repo import AmorphousCellRepository  # noqa: E402
from features.common import run_in_session_commit  # noqa: E402


def _write_minimal_lammps_data(path):
    path.write_text(
        "\n".join(
            [
                "LAMMPS data file",
                "",
                "1 atoms",
                "0 bonds",
                "1 atom types",
                "",
                "0.0 10.0 xlo xhi",
                "0.0 10.0 ylo yhi",
                "0.0 10.0 zlo zhi",
                "",
                "Masses",
                "",
                "1 12.011",
                "",
                "Atoms # full",
                "",
                "1 1 1 0.0 5.0 5.0 5.0",
            ]
        ),
        encoding="utf-8",
    )


class _DummyPrecomputeResult:
    def __init__(self):
        self.failed = 0
        self.cached = 0
        self.computed = 1
        self.details = []


class _DummySubmitResult:
    def __init__(self):
        self.exp_id = "C_X1_NA_none_298K_test01"
        self.job_id = "job_test_001"
        self.status = "queued"
        self.binder_type = "custom"
        self.structure_size = "X1"
        self.total_molecules = 120
        self.estimated_atoms = 2400


class TestAmorphousCellsAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        db_path = tmp_path / "test_amorphous_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        async def _fake_precompute(_request):
            return _DummyPrecomputeResult()

        async def _fake_submit(_request, **_kwargs):
            return _DummySubmitResult()

        monkeypatch.setattr(
            "features.amorphous_cells.service.precompute_typing_charge",
            _fake_precompute,
        )
        monkeypatch.setattr(
            "features.amorphous_cells.service.submit_molecule_experiment",
            _fake_submit,
        )

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def test_amorphous_cell_create_and_list(self, client):
        payload = {
            "name": "Water-Amorphous-01",
            "component_mol_id": "SA-Squalane",
            "lx_angstrom": 40.0,
            "ly_angstrom": 50.0,
            "lz_angstrom": 20.0,
            "initial_density": 1.0,
            "boundary_mode": "ppf",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
        }

        create_resp = client.post("/amorphous-cells", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        assert created["name"] == "Water-Amorphous-01"
        assert created["boundary_mode"] == "ppf"
        assert created["status"] == "queued"
        assert created["component_count"] == 1
        assert created["component_mol_id"] == "SA-Squalane"
        assert created["stabilization_exp_id"] == "C_X1_NA_none_298K_test01"

        list_resp = client.get("/amorphous-cells?limit=20")
        assert list_resp.status_code == 200
        listing = list_resp.json()
        assert listing["total"] == 0
        assert all(item["amorphous_id"] != created["amorphous_id"] for item in listing["items"])

        list_all_resp = client.get("/amorphous-cells?limit=20&visibility=all")
        assert list_all_resp.status_code == 200
        listing_all = list_all_resp.json()
        assert listing_all["total"] >= 1
        assert any(item["amorphous_id"] == created["amorphous_id"] for item in listing_all["items"])

    def test_amorphous_cell_dedupes_same_source_hash(self, client):
        payload = {
            "name": "Dedupe-Amorphous",
            "component_mol_id": "SA-Squalane",
            "lx_angstrom": 40.0,
            "ly_angstrom": 40.0,
            "lz_angstrom": 20.0,
            "initial_density": 1.0,
            "boundary_mode": "ppp",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
        }

        first = client.post("/amorphous-cells", json=payload)
        assert first.status_code == 200, first.text
        first_body = first.json()

        second = client.post("/amorphous-cells", json=payload)
        assert second.status_code == 200, second.text
        second_body = second.json()

        assert second_body["amorphous_id"] == first_body["amorphous_id"]

    def test_amorphous_cell_create_rejects_multi_component_payload(self, client):
        payload = {
            "name": "Invalid-Multi",
            "components": [
                {"mol_id": "SA-Squalane", "weight_ratio": 70.0},
                {"mol_id": "AR-PHPN", "weight_ratio": 30.0},
            ],
            "lx_angstrom": 40.0,
            "ly_angstrom": 40.0,
            "lz_angstrom": 20.0,
            "initial_density": 1.0,
            "boundary_mode": "ppp",
            "ff_type": "bulk_ff_gaff2",
            "temperature_K": 298.0,
        }
        resp = client.post("/amorphous-cells", json=payload)
        assert resp.status_code == 422

    def test_amorphous_cell_preview(self, client):
        amorphous_id = "amor_preview_001"
        data_path = get_amorphous_cell_path(amorphous_id, "amorphous.data", create=True)
        _write_minimal_lammps_data(data_path)

        def _insert(session):
            repo = AmorphousCellRepository(session)
            repo.create(
                amorphous_id=amorphous_id,
                name="Preview-Amorphous",
                status="ready",
                source_hash="preview_hash",
                components_json=[{"mol_id": "SA-Squalane", "weight_ratio": 100.0}],
                component_count=1,
                lx_angstrom=10.0,
                ly_angstrom=10.0,
                lz_angstrom=10.0,
                target_density=1.0,
                boundary_mode="ppp",
                ff_type="bulk_ff_gaff2",
                temperature_K=298.0,
                lammps_data_file_path=str(data_path),
            )

        run_in_session_commit(_insert)

        preview_resp = client.get(f"/amorphous-cells/{amorphous_id}/preview")
        assert preview_resp.status_code == 200
        payload = preview_resp.json()
        assert payload["amorphous_id"] == amorphous_id
        assert payload["n_atoms"] == 1
        assert len(payload["box_size"]) == 3
        shutil.rmtree(get_amorphous_cell_path(amorphous_id), ignore_errors=True)

    def test_amorphous_cell_preview_not_found(self, client):
        resp = client.get("/amorphous-cells/amor_missing_001/preview")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "E7001"
