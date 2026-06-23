"""Phase 5 — v00.99.41: admin control plane API tests.

Validates the env-guarded admin endpoints introduced for the FF
Parameters page:

* ``GET /artifacts/admin/capabilities`` — always 200 (frontend probe).
* ``GET /artifacts/admin/status`` — env-guarded source-centric status.
* ``POST /artifacts/admin/generate/{mol_id}?profile=...`` — env-guarded
  generate with ``sqm_robust`` retry gating.
* ``POST /artifacts/admin/diagnose/{mol_id}`` — env-guarded preflight.

The endpoints are mounted on the molecules router which is registered in
``src/api/application.py``. Each test wraps the router under a fresh
``FastAPI`` app + ``TestClient`` so they stay independent of the rest of
the application.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src/ on path so package imports resolve in CI.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture
def admin_off(monkeypatch):
    monkeypatch.delenv("ASPHALT_ANTECHAMBER_ADMIN", raising=False)
    yield


@pytest.fixture
def admin_on(monkeypatch):
    monkeypatch.setenv("ASPHALT_ANTECHAMBER_ADMIN", "1")
    yield


@pytest.fixture
def client():
    """TestClient as a context manager so lifespan events are run.

    v00.99.42 reinforcement — using ``with TestClient(app) as client:``
    avoids the env-specific hang Codex saw on first request, where the
    test harness blocked because the lifespan portal was never started.
    """
    from features.molecules.router import router as molecules_router

    app = FastAPI()
    app.include_router(molecules_router)
    with TestClient(app) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Capabilities — always 200
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminCapabilities:
    """Capabilities endpoint always returns enabled=True (admin gate removed v00.99.45)."""

    def test_capabilities_always_enabled(self, client):
        r = client.get("/artifacts/admin/capabilities")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert "baseline" in body["profiles"]
        assert "sqm_robust" in body["profiles"]


# ─────────────────────────────────────────────────────────────────────────────
# Admin gate removed (v00.99.45) — endpoints always accessible
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminEndpointsAlwaysAccessible:
    """Admin endpoints no longer return 404 when env var is off."""

    def test_status_accessible_without_env(self, admin_off, client):
        r = client.get("/artifacts/admin/status")
        assert r.status_code == 200

    def test_diagnose_accessible_without_env(self, admin_off, client):
        r = client.post("/artifacts/admin/diagnose/Toluene")
        # May return 4xx for validation, but NOT 404 for admin gate
        assert r.status_code != 404


# ─────────────────────────────────────────────────────────────────────────────
# Admin status — env on
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminStatusShape:
    def test_status_returns_rows_and_conflicts(self, admin_on, client):
        r = client.get("/artifacts/admin/status")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("rows"), list)
        assert isinstance(body.get("conflicts"), list)
        # Each row must expose source_id, primary_mol_id, consumer_ids.
        for row in body["rows"]:
            assert "source_id" in row
            assert "primary_mol_id" in row
            assert "consumer_ids" in row
            assert isinstance(row["consumer_ids"], list)

    def test_status_passthrough_row_marked(self, admin_on, client):
        r = client.get("/artifacts/admin/status")
        body = r.json()
        # Find the carbon_sp2_passthrough_v1 row (CNT/Graphene shared).
        passthrough = next(
            (row for row in body["rows"] if row["source_id"] == "carbon_sp2_passthrough_v1"),
            None,
        )
        assert passthrough is not None
        assert passthrough["is_passthrough"] is True
        assert set(passthrough["consumer_ids"]) >= {
            "Carbon_Nano_Tube",
            "Graphine",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Admin generate — gating
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminGenerateGating:
    def test_invalid_profile_400(self, admin_on, client, monkeypatch):
        # We don't reach the AmberTools check because profile validation
        # runs first.
        r = client.post("/artifacts/admin/generate/Toluene?profile=aggressive")
        assert r.status_code == 400

    def test_passthrough_returns_405(self, admin_on, client, monkeypatch):
        # Force AmberTools check to pass so we reach the passthrough guard.
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)
        r = client.post("/artifacts/admin/generate/Carbon_Nano_Tube?profile=baseline")
        assert r.status_code == 405

    def test_sqm_robust_blocked_without_prior_sqm_failure(
        self, admin_on, client, tmp_path, monkeypatch
    ):
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)
        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        # No sidecar exists → no prior failure → sqm_robust must be 409.
        r = client.post("/artifacts/admin/generate/Toluene?profile=sqm_robust")
        assert r.status_code == 409
        body = r.json()
        # Detail is now a dict carrying message + latest_failure_code so
        # the structured admin helper can be reused by the CLI.
        assert "sqm_robust" in body["detail"]["message"]
        assert body["detail"]["latest_failure_code"] is None

    def test_sqm_robust_allowed_after_sqm_failure(self, admin_on, client, tmp_path, monkeypatch):
        from features.molecules import artifact_service
        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.exceptions import (
            ArtifactFailureCode,
            ArtifactGenerationError,
        )

        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)
        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)

        # Seed a sidecar with sqm_timeout so sqm_robust is permitted.
        store = AdminStatusStore(tmp_path)
        store.record_failure(
            "Toluene",
            ArtifactGenerationError(
                stage="antechamber",
                failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            ),
        )
        # Patch generate_gaff2_artifact so we don't actually invoke AmberTools.

        def _fake_generate(
            *,
            mol_path,
            mol_id,
            smiles,
            formal_charge,
            ff_assignment=None,
            generation_profile="baseline",
        ):
            assert generation_profile == "sqm_robust"
            return {
                "atoms": [],
                "bond_types": [],
                "angle_types": [],
                "dihedral_types": [],
                "improper_types": [],
                "improper_instances": [],
                "charge_sum": 0,
            }

        # Patch router-side imports (re-imported per request).
        monkeypatch.setattr(artifact_service, "generate_gaff2_artifact", _fake_generate)
        monkeypatch.setattr(
            artifact_service,
            "validate_artifact",
            lambda art: {"valid": True, "checks": {}, "warnings": []},
        )

        # The mol_path validation requires the file to exist.
        toluene_mol = ROOT / "data" / "molecules" / "single_moles" / "Toluene.mol"
        assert toluene_mol.exists(), "Toluene catalog mol file expected"

        r = client.post("/artifacts/admin/generate/Toluene?profile=sqm_robust")
        # The fake generate returns a payload; admin endpoint should accept.
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        assert body["generation_profile"] == "sqm_robust"


# ─────────────────────────────────────────────────────────────────────────────
# Admin diagnose
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminDiagnose:
    def test_diagnose_passthrough_returns_manual_review(self, admin_on, client):
        r = client.post("/artifacts/admin/diagnose/Carbon_Nano_Tube")
        assert r.status_code == 200
        body = r.json()
        assert body["verdict"] == "manual_review"
        assert any(f["kind"] == "passthrough" for f in body["findings"])


# ─────────────────────────────────────────────────────────────────────────────
# v00.99.43: Admin generate-all + admin batch-progress + recommended_action
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminBatchProgressEndpoint:
    def test_accessible_without_env(self, admin_off, client):
        """Admin gate removed (v00.99.45) — batch-progress always accessible."""
        r = client.get("/artifacts/admin/batch-progress")
        assert r.status_code == 200

    def test_200_returns_progress_with_metadata_keys(self, admin_on, client):
        r = client.get("/artifacts/admin/batch-progress")
        assert r.status_code == 200
        body = r.json()
        # New v00.99.43 metadata keys present (additive on _batch_progress).
        for key in (
            "running",
            "batch_kind",
            "generation_profile",
            "started_at",
            "total",
            "completed",
            "failed",
            "skipped",
            "current_mol_id",
        ):
            assert key in body, f"missing batch-progress key: {key}"


class TestAdminGenerateAllEndpoint:
    def test_accessible_without_env(self, admin_off, client):
        """Admin gate removed (v00.99.45) — generate-all always accessible."""
        r = client.post("/artifacts/admin/generate-all")
        # May return 4xx for validation (e.g. AmberTools unavailable), but NOT 404
        assert r.status_code != 404

    def test_invalid_profile_400(self, admin_on, client, monkeypatch):
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)
        r = client.post("/artifacts/admin/generate-all?profile=aggressive")
        assert r.status_code == 400

    def test_409_when_batch_already_running(self, admin_on, client, monkeypatch, tmp_path):
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)
        # Pretend a public batch is already running.
        artifact_service.acquire_batch_slot("public", "baseline")
        try:
            # Need at least one eligible row so the slot acquisition is
            # actually attempted (admin endpoint short-circuits on
            # ``nothing_eligible`` before reaching the slot guard).
            def _fake_pending():
                return [
                    {
                        "mol_id": "Toluene",
                        "source_id": "Toluene",
                        "is_complete": False,
                        "artifact_type": "organic",
                        "consumer_ids": ["Toluene"],
                    }
                ]

            monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)
            r = client.post("/artifacts/admin/generate-all?profile=baseline")
            assert r.status_code == 409
            body = r.json()
            assert body["detail"]["batch_kind"] == "public"
        finally:
            artifact_service.release_batch_slot()

    def test_dedupes_then_validates_per_row_for_sqm_robust(
        self, admin_on, client, monkeypatch, tmp_path
    ):
        """sqm_robust requires prior sqm_* failure on each source_id;
        rows without it must end up in 'skipped' (not 'eligible')."""
        from features.molecules import artifact_service
        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.exceptions import (
            ArtifactFailureCode,
            ArtifactGenerationError,
        )

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        # Seed a sidecar with sqm_timeout for Toluene only.
        AdminStatusStore(tmp_path).record_failure(
            "Toluene",
            ArtifactGenerationError(
                stage="antechamber",
                failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            ),
        )

        # Two pending rows: Toluene eligible, Methanol blocked.
        def _fake_pending():
            return [
                {
                    "mol_id": "Toluene",
                    "source_id": "Toluene",
                    "is_complete": False,
                    "artifact_type": "organic",
                    "consumer_ids": ["Toluene"],
                    "atom_count": 15,
                    "mol_path": "",
                },
                {
                    "mol_id": "Methanol",
                    "source_id": "Methanol",
                    "is_complete": False,
                    "artifact_type": "organic",
                    "consumer_ids": ["Methanol"],
                    "atom_count": 6,
                    "mol_path": "",
                },
            ]

        monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)

        try:
            r = client.post("/artifacts/admin/generate-all?profile=sqm_robust")
            assert r.status_code == 202
            body = r.json()
            assert body["batch_kind"] == "admin"
            assert body["generation_profile"] == "sqm_robust"
            assert "Toluene" in body["eligible_source_ids"]
            assert all(s["mol_id"] != "Toluene" for s in body["skipped"])
            assert any(s["mol_id"] == "Methanol" for s in body["skipped"])
        finally:
            artifact_service.release_batch_slot()

    def test_returns_conflicts_alongside_eligible_skipped(
        self, admin_on, client, monkeypatch, tmp_path
    ):
        """Shared source_id with conflicting structure_file must surface
        in the conflicts list, not silently dropped."""
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        def _fake_pending():
            return [
                {
                    "mol_id": "Carbon_Nano_Tube",
                    "source_id": "carbon_sp2_passthrough_v1",
                    "consumer_ids": ["Carbon_Nano_Tube", "Graphine"],
                    "is_complete": False,
                    "artifact_type": "organic",
                    "mol_path": "/tmp/cnt.mol",
                    "is_passthrough": True,
                },
                {
                    "mol_id": "Graphine",
                    "source_id": "carbon_sp2_passthrough_v1",
                    "consumer_ids": ["Carbon_Nano_Tube", "Graphine"],
                    "is_complete": False,
                    "artifact_type": "organic",
                    "mol_path": "/tmp/graph.mol",
                    "is_passthrough": True,
                },
            ]

        monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)

        r = client.post("/artifacts/admin/generate-all?profile=baseline")
        assert r.status_code == 200, r.text  # nothing_eligible (passthrough)
        body = r.json()
        assert body["status"] == "nothing_eligible"
        # The shared source_id pair produces exactly one conflict row.
        assert len(body["conflicts"]) == 1
        # Both rows are passthrough → both end up skipped (dedupe canonical
        # is checked first, the conflict row is reported separately).
        assert len(body["skipped"]) >= 1
        assert all(s["status_code"] == 405 for s in body["skipped"])


class TestRecommendedActionPopulation:
    def test_single_admin_generate_failure_populates_recommended_action(
        self, admin_on, client, monkeypatch, tmp_path
    ):
        """v00.99.43: the single-row admin generate path must populate
        recommended_action via the shared helper, not leave it blank."""
        from features.molecules import artifact_service
        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.exceptions import (
            ArtifactFailureCode,
            ArtifactGenerationError,
        )

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        def _fake_generate(**kwargs):
            raise ArtifactGenerationError(
                stage="antechamber",
                failure_code=ArtifactFailureCode.SQM_TIMEOUT,
                stderr_excerpt="timed out",
            )

        monkeypatch.setattr(artifact_service, "generate_gaff2_artifact", _fake_generate)

        toluene_mol = ROOT / "data" / "molecules" / "single_moles" / "Toluene.mol"
        assert toluene_mol.exists()

        r = client.post("/artifacts/admin/generate/Toluene?profile=baseline")
        assert r.status_code == 500
        sidecar = AdminStatusStore(tmp_path).get("Toluene")
        assert sidecar is not None
        assert sidecar.failure_code == "sqm_timeout"
        assert sidecar.recommended_action == "retry_sqm_robust"


# ─────────────────────────────────────────────────────────────────────────────
# v00.99.43: public /artifacts/generate-all backward-compat regression
# ─────────────────────────────────────────────────────────────────────────────


class TestPublicGenerateAllBackwardCompat:
    """Public batch endpoint must keep returning the legacy operator-client
    keys AND additively expose batch_kind/generation_profile. The frontend
    ArtifactPanel consumer was removed in v00.99.66 but the public route is
    kept for legacy/operator callers (see topology_helpers error messages)."""

    def test_response_includes_batch_kind_public_and_baseline_profile(
        self, admin_off, client, monkeypatch, tmp_path
    ):
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        def _fake_pending():
            return [
                {
                    "mol_id": "Toluene",
                    "source_id": "Toluene",
                    "is_complete": False,
                    "consumer_ids": ["Toluene"],
                }
            ]

        monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)

        try:
            r = client.post("/artifacts/generate-all")
            assert r.status_code == 202, r.text
            body = r.json()
            # Legacy/operator-client keys preserved after v00.99.66.
            assert body["status"] == "accepted"
            assert "total" in body
            assert "message" in body
            # New additive metadata.
            assert body["batch_kind"] == "public"
            assert body["generation_profile"] == "baseline"
        finally:
            artifact_service.release_batch_slot()

    def test_409_when_admin_batch_already_running(self, admin_off, client, monkeypatch, tmp_path):
        """Public batch must back off when an admin batch is in flight."""
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        def _fake_pending():
            return [
                {
                    "mol_id": "Toluene",
                    "source_id": "Toluene",
                    "is_complete": False,
                    "consumer_ids": ["Toluene"],
                }
            ]

        monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)
        artifact_service.acquire_batch_slot("admin", "sqm_robust")
        try:
            r = client.post("/artifacts/generate-all")
            assert r.status_code == 409
            body = r.json()
            assert body["detail"]["batch_kind"] == "admin"
            assert body["detail"]["generation_profile"] == "sqm_robust"
        finally:
            artifact_service.release_batch_slot()


# ─────────────────────────────────────────────────────────────────────────────
# v00.99.43 codex audit reinforcement: counter atomicity
# ─────────────────────────────────────────────────────────────────────────────


class TestAcquireBatchSlotCounterReset:
    """A previous batch's counters must NOT leak into the first
    /batch-progress poll after a fresh acquire."""

    def test_counters_zeroed_atomically_on_acquire(self):
        from features.molecules import artifact_service

        # Seed stale counters from an imaginary previous batch.
        artifact_service._batch_progress.update(
            {
                "running": False,
                "total": 99,
                "completed": 88,
                "failed": 7,
                "skipped": 4,
                "current_mol_id": "stale-mol",
                "percent": 95.0,
                "max_workers": 8,
                "batch_kind": "public",
                "generation_profile": "baseline",
                "started_at": 1.0,
            }
        )
        try:
            assert artifact_service.acquire_batch_slot("admin", "sqm_robust")
            snapshot = artifact_service.get_batch_progress()
            assert snapshot["running"] is True
            assert snapshot["batch_kind"] == "admin"
            assert snapshot["generation_profile"] == "sqm_robust"
            assert snapshot["total"] == 0
            assert snapshot["completed"] == 0
            assert snapshot["failed"] == 0
            assert snapshot["skipped"] == 0
            assert snapshot["percent"] == 0.0
            assert snapshot["current_mol_id"] == ""
            assert snapshot["max_workers"] == 0
            assert snapshot["started_at"] is not None
        finally:
            artifact_service.release_batch_slot()
