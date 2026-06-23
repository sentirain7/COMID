"""API tests for crystal structure library endpoints."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from common.pathing import get_project_root  # noqa: E402
from config.settings import reset_settings  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import CrystalStructureModel  # noqa: E402


class _FakeJobManager:
    def __init__(self):
        self.submit_calls = 0
        self.cancel_calls: list[str] = []

    def submit(self, **_kwargs):
        self.submit_calls += 1
        return f"job-crystal-{self.submit_calls:03d}"

    def get_task_id(self, job_id):
        return f"task-{job_id}"

    def cancel_job(self, job_id):
        self.cancel_calls.append(str(job_id))


def _resolve_artifact_path(path_value: str | None) -> Path:
    assert path_value
    raw = Path(path_value)
    if raw.is_absolute():
        return raw
    return get_project_root() / raw


_CRYSTAL_SMALL_DIMS = {
    "thickness_angstrom": 8.0,
    "xy_size_angstrom": 12.0,
    "nx": 1,
    "ny": 1,
    "nz": 1,
}


class TestCrystalStructuresAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_crystal_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        fake_job_manager = _FakeJobManager()
        monkeypatch.setattr("api.deps.get_job_manager", lambda: fake_job_manager)
        monkeypatch.setattr(
            "config.dashboard_settings.load_dashboard_settings",
            lambda: {"selected_gpus": []},
        )
        close_db()
        reset_settings()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            c.fake_job_manager = fake_job_manager  # type: ignore[attr-defined]
            yield c
        close_db()
        reset_settings()

    def test_crystal_structure_crud(self, client):
        payload = {
            "name": "QuartzTemplate",
            "source_type": "preset",
            "material": "SiO2",
            "surface": "001",
            **_CRYSTAL_SMALL_DIMS,
            "hydroxylated": True,
            "hydroxyl_density": 4.6,
        }

        create_resp = client.post("/crystal-structures", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        crystal_id = created["crystal_id"]
        # Name is auto-generated from actual build dimensions (SSOT),
        # not the client-supplied name. Format: {Material}_{avgXY}A_{lz}A_{surface}
        assert created["name"].startswith("SiO2_")
        assert created["name"].endswith("_001")
        assert created["source_type"] == "preset"
        # create() produces a ready template immediately (no stabilization job).
        assert created["status"] == "ready"
        assert created["atom_count"] > 0

        xyz_path = _resolve_artifact_path(created["xyz_file_path"])
        data_path = _resolve_artifact_path(created["lammps_data_file_path"])
        assert xyz_path.exists()
        assert data_path.exists()

        # Default visibility="library" only shows ready structures; the new
        # structure is ready on create, so it is listed immediately.
        list_resp = client.get("/crystal-structures?limit=20")
        assert list_resp.status_code == 200
        listing = list_resp.json()
        assert listing["total"] >= 1
        assert any(item["crystal_id"] == crystal_id for item in listing["items"])

        list_all_resp = client.get("/crystal-structures?limit=20&visibility=all")
        assert list_all_resp.status_code == 200
        listing_all = list_all_resp.json()
        assert listing_all["total"] >= 1
        assert any(item["crystal_id"] == crystal_id for item in listing_all["items"])

        get_resp = client.get(f"/crystal-structures/{crystal_id}")
        assert get_resp.status_code == 200
        detail = get_resp.json()
        assert detail["crystal_id"] == crystal_id
        assert detail["status"] == "ready"

        preview_resp = client.get(f"/crystal-structures/{crystal_id}/preview")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["crystal_id"] == crystal_id
        assert preview["n_atoms"] > 0
        assert len(preview["box_size"]) == 3
        assert "xyz" in preview

        delete_resp = client.delete(f"/crystal-structures/{crystal_id}")
        assert delete_resp.status_code == 200
        deleted = delete_resp.json()
        assert deleted["deleted"] is True

        get_deleted_resp = client.get(f"/crystal-structures/{crystal_id}")
        assert get_deleted_resp.status_code == 404

    def test_crystal_structure_rejects_path_traversal(self, client):
        payload = {
            "name": "UnsafeCIF",
            "source_type": "cif",
            "cif_path": "/etc/passwd",
        }

        resp = client.post("/crystal-structures", json=payload)
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == "E9501"

    def test_crystal_structure_preview_not_found(self, client):
        resp = client.get("/crystal-structures/crys_missing_001/preview")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "E7001"

    def test_crystal_structure_dedupes_same_source_hash(self, client):
        payload = {
            "name": "QuartzTemplateDedupe",
            "source_type": "preset",
            "material": "SiO2",
            "surface": "001",
            **_CRYSTAL_SMALL_DIMS,
            "hydroxylated": True,
            "hydroxyl_density": 4.6,
        }

        first = client.post("/crystal-structures", json=payload)
        assert first.status_code == 200, first.text
        first_body = first.json()

        second = client.post("/crystal-structures", json=payload)
        assert second.status_code == 200, second.text
        second_body = second.json()

        # Dedup by source_hash: the second create returns the existing crystal.
        assert second_body["crystal_id"] == first_body["crystal_id"]
        assert second_body["name"] == first_body["name"]
        assert second_body["status"] == first_body["status"]
        # create() no longer submits a stabilization job.
        assert client.fake_job_manager.submit_calls == 0  # type: ignore[attr-defined]

        listing = client.get("/crystal-structures?limit=20&visibility=all")
        assert listing.status_code == 200
        rows = listing.json()["items"]
        ids = [row["crystal_id"] for row in rows]
        assert ids.count(first_body["crystal_id"]) == 1

    def test_crystal_structure_preview_missing_data_file(self, client):
        payload = {
            "name": "QuartzTemplateMissingData",
            "source_type": "preset",
            "material": "SiO2",
            "surface": "001",
            **_CRYSTAL_SMALL_DIMS,
            "hydroxylated": True,
            "hydroxyl_density": 4.6,
        }

        create_resp = client.post("/crystal-structures", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        crystal_id = created["crystal_id"]

        data_path = _resolve_artifact_path(created["lammps_data_file_path"])
        assert data_path.exists()
        data_path.unlink()

        preview_resp = client.get(f"/crystal-structures/{crystal_id}/preview")
        assert preview_resp.status_code == 404
        body = preview_resp.json()
        assert body["code"] == "E9505"

    @pytest.mark.parametrize(
        "material",
        [
            "MgO",
            "Fe2O3",
            "MgCO3",
            "CaO",
            "TiO2",
            "ZnO",
            "NaCl",
            "KCl",
            "Al",
            "Fe",
            "Cu",
            "Ni",
        ],
    )
    def test_crystal_structure_supports_extended_preset_materials(self, client, material):
        payload = {
            "name": f"{material}_Template",
            "source_type": "preset",
            "material": material,
            "surface": "001",
            **_CRYSTAL_SMALL_DIMS,
            "hydroxylated": True,
            "hydroxyl_density": 4.6,
        }

        create_resp = client.post("/crystal-structures", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        assert created["material"] == material
        # create() produces a ready template immediately (no stabilization job).
        assert created["status"] == "ready"
        assert created["atom_count"] > 0

    def test_crystal_structure_is_ready_and_listed_in_library(self, client):
        # create() builds the template synchronously and stores it as ready in
        # both the YAML SSOT and DB (no stabilization experiment is queued).
        payload = {
            "name": "QuartzTemplateSync",
            "source_type": "preset",
            "material": "SiO2",
            "surface": "001",
            **_CRYSTAL_SMALL_DIMS,
            "hydroxylated": True,
            "hydroxyl_density": 4.6,
        }

        create_resp = client.post("/crystal-structures", json=payload)
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        crystal_id = created["crystal_id"]
        assert created["status"] == "ready"

        data_path = _resolve_artifact_path(created["lammps_data_file_path"])
        assert data_path.exists()

        # The DB row mirrors the ready status persisted on create.
        with session_scope() as session:
            row = (
                session.query(CrystalStructureModel)
                .filter(CrystalStructureModel.crystal_id == crystal_id)
                .first()
            )
            assert row is not None
            assert row.status == "ready"
            assert int(row.atom_count or 0) == created["atom_count"]

        # Library listing (default visibility) surfaces the ready structure,
        # merging the DB status into the YAML-backed entry.
        list_resp = client.get("/crystal-structures?limit=20")
        assert list_resp.status_code == 200, list_resp.text
        rows = list_resp.json()["items"]
        row = next((item for item in rows if item["crystal_id"] == crystal_id), None)
        assert row is not None
        assert row["status"] == "ready"
        assert row["atom_count"] == created["atom_count"]
        assert str(row["lammps_data_file_path"]).endswith("crystal.data")
