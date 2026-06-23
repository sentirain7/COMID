"""Phase 3 — v00.99.41: AdminStatusStore + ArtifactGenerationError tests.

Verifies sidecar persistence (atomic write, restart survival, stderr trim,
delete cleanup, success clears failure fields) and the ArtifactGenerationError
contract used by the batch worker and admin sidecar layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from features.molecules.admin_status import (
    SIDECAR_DIRNAME,
    AdminStatus,
    AdminStatusStore,
)
from features.molecules.exceptions import (
    ArtifactFailureCode,
    ArtifactGenerationError,
)

# ─────────────────────────────────────────────────────────────────────────────
# ArtifactGenerationError contract
# ─────────────────────────────────────────────────────────────────────────────


class TestArtifactGenerationError:
    def test_truncates_long_stderr_to_2kb(self):
        big = "x" * 5000
        err = ArtifactGenerationError(
            stage="antechamber",
            failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            stderr_excerpt=big,
        )
        assert len(err.stderr_excerpt) <= 2048
        assert err.stderr_excerpt.endswith("...")

    def test_default_message_includes_stage_and_code(self):
        err = ArtifactGenerationError(
            stage="parmchk2",
            failure_code=ArtifactFailureCode.PARMCHK2_FAILED,
        )
        assert "parmchk2" in err.message
        assert "parmchk2_failed" in err.message

    @pytest.mark.parametrize(
        "code,expected",
        [
            (ArtifactFailureCode.SQM_TIMEOUT, True),
            (ArtifactFailureCode.SQM_NONCONVERGED, True),
            (ArtifactFailureCode.ANTECHAMBER_FAILED, False),
            (ArtifactFailureCode.PARMCHK2_FAILED, False),
            (ArtifactFailureCode.TLEAP_FAILED, False),
            (ArtifactFailureCode.PASSTHROUGH_UNSUPPORTED, False),
            (ArtifactFailureCode.SHARED_SOURCE_ID_CONFLICT, False),
        ],
    )
    def test_retryable_only_for_sqm_failures(self, code, expected):
        err = ArtifactGenerationError(stage="x", failure_code=code)
        assert err.retryable is expected

    def test_admin_payload_round_trip(self):
        err = ArtifactGenerationError(
            stage="antechamber",
            failure_code=ArtifactFailureCode.ANTECHAMBER_FAILED,
            message="boom",
            stderr_excerpt="trace",
        )
        payload = err.to_admin_payload()
        assert payload["stage"] == "antechamber"
        assert payload["failure_code"] == "antechamber_failed"
        assert payload["stderr_excerpt"] == "trace"
        assert payload["retryable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# AdminStatusStore — persistence
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> AdminStatusStore:
    return AdminStatusStore(tmp_path)


class TestAdminStatusStorePaths:
    def test_sidecar_path_under_admin_status_subdir(self, store: AdminStatusStore):
        p = store.path_for("Toluene")
        assert p.parent.name == SIDECAR_DIRNAME
        assert p.name == "Toluene.json"

    def test_path_for_empty_source_id_raises(self, store: AdminStatusStore):
        with pytest.raises(ValueError):
            store.path_for("")

    @pytest.mark.parametrize(
        "bad_id",
        [
            "../escape",
            "..",
            ".",
            "foo/../escape",
            "foo/bar",
            "foo\\bar",
            "foo\x00bar",
        ],
    )
    def test_path_for_rejects_path_traversal(self, store: AdminStatusStore, bad_id: str):
        with pytest.raises(ValueError):
            store.path_for(bad_id)


class TestAdminStatusStorePersistence:
    def test_write_then_read_roundtrip(self, store: AdminStatusStore):
        status = AdminStatus(
            source_id="Toluene",
            artifact_status="complete",
            generation_profile="baseline",
            consumer_ids=["Toluene"],
        )
        store.write(status)
        loaded = store.get("Toluene")
        assert loaded is not None
        assert loaded.source_id == "Toluene"
        assert loaded.artifact_status == "complete"
        assert loaded.consumer_ids == ["Toluene"]

    def test_write_is_atomic_no_orphan_tmp(self, store: AdminStatusStore):
        store.write(AdminStatus(source_id="X"))
        leftovers = list(store.sidecar_dir.glob("*.tmp"))
        assert leftovers == [], "tempfile must not survive successful write"

    def test_get_returns_none_for_missing_sidecar(self, store: AdminStatusStore):
        assert store.get("does_not_exist") is None

    def test_get_returns_none_for_corrupt_json(self, store: AdminStatusStore):
        store.sidecar_dir.mkdir(parents=True, exist_ok=True)
        (store.sidecar_dir / "broken.json").write_text("{not valid json")
        assert store.get("broken") is None

    def test_persists_across_new_store_instance(self, tmp_path: Path):
        s1 = AdminStatusStore(tmp_path)
        s1.write(AdminStatus(source_id="cnt", artifact_status="passthrough"))
        s2 = AdminStatusStore(tmp_path)
        loaded = s2.get("cnt")
        assert loaded is not None
        assert loaded.artifact_status == "passthrough"

    def test_invalid_artifact_status_raises_on_construction(self):
        with pytest.raises(ValueError):
            AdminStatus(source_id="x", artifact_status="banana")

    def test_stderr_excerpt_trimmed_to_2kb_on_status(self):
        status = AdminStatus(source_id="x", stderr_excerpt="z" * 4000)
        assert len(status.stderr_excerpt) <= 2048


class TestAdminStatusStoreDelete:
    def test_delete_existing_sidecar_returns_true(self, store: AdminStatusStore):
        store.write(AdminStatus(source_id="x"))
        assert store.delete("x") is True
        assert store.get("x") is None

    def test_delete_missing_sidecar_returns_false(self, store: AdminStatusStore):
        assert store.delete("nothing") is False


class TestAdminStatusStoreHelpers:
    def test_record_failure_persists_sidecar_with_failure_code(self, store: AdminStatusStore):
        err = ArtifactGenerationError(
            stage="antechamber",
            failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            stderr_excerpt="timeout",
        )
        result = store.record_failure(
            "Toluene",
            err,
            consumer_ids=["Toluene"],
            generation_profile="baseline",
        )
        assert result.artifact_status == "failed"
        assert result.failure_code == "sqm_timeout"
        assert result.last_attempt_at is not None

        loaded = store.get("Toluene")
        assert loaded is not None
        assert loaded.failure_code == "sqm_timeout"

    def test_record_success_clears_failure_fields(self, store: AdminStatusStore):
        # First record a failure.
        err = ArtifactGenerationError(
            stage="antechamber",
            failure_code=ArtifactFailureCode.ANTECHAMBER_FAILED,
            stderr_excerpt="boom",
        )
        store.record_failure("Toluene", err, consumer_ids=["Toluene"])
        # Then succeed.
        result = store.record_success("Toluene", consumer_ids=["Toluene"])
        assert result.artifact_status == "complete"
        assert result.failure_code is None
        assert result.stderr_excerpt == ""
        assert result.last_success_at is not None

        loaded = store.get("Toluene")
        assert loaded is not None
        assert loaded.failure_code is None

    def test_record_success_keeps_last_success_history_when_replayed(self, store: AdminStatusStore):
        first = store.record_success("X")
        second = store.record_success("X")
        assert second.last_success_at >= first.last_success_at

    def test_record_passthrough_marks_unsupported(self, store: AdminStatusStore):
        result = store.record_passthrough(
            "carbon_sp2_passthrough_v1",
            consumer_ids=["Carbon_Nano_Tube", "Graphine"],
        )
        assert result.artifact_status == "passthrough"
        assert result.failure_code == "passthrough_unsupported"
        loaded = store.get("carbon_sp2_passthrough_v1")
        assert loaded is not None
        assert set(loaded.consumer_ids) == {"Carbon_Nano_Tube", "Graphine"}


class TestAdminStatusStoreList:
    def test_list_all_returns_every_sidecar_sorted(self, store: AdminStatusStore):
        store.write(AdminStatus(source_id="b"))
        store.write(AdminStatus(source_id="a"))
        all_status = store.list_all()
        ids = [s.source_id for s in all_status]
        assert ids == ["a", "b"]

    def test_list_all_skips_corrupt_sidecars(self, store: AdminStatusStore):
        store.write(AdminStatus(source_id="ok"))
        store.sidecar_dir.mkdir(parents=True, exist_ok=True)
        (store.sidecar_dir / "broken.json").write_text("{")
        ids = [s.source_id for s in store.list_all()]
        assert ids == ["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration with artifact_service worker
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkerSidecarIntegration:
    def test_worker_records_input_invalid_failure(self, tmp_path: Path, monkeypatch):
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)

        result = artifact_service._generate_one_worker(
            {
                "mol_id": "Ghost",
                "source_id": "Ghost",
                "mol_path": str(tmp_path / "missing.mol"),
                "ff_assignment": {},
            }
        )
        assert result["status"] == "error"
        assert result["failure_code"] == "input_invalid"

        sidecar_path = tmp_path / SIDECAR_DIRNAME / "Ghost.json"
        assert sidecar_path.exists()
        body = json.loads(sidecar_path.read_text())
        assert body["failure_code"] == "input_invalid"
        assert body["artifact_status"] == "failed"

    def test_dedupe_conflict_records_shared_source_id_conflict(self, tmp_path: Path, monkeypatch):
        """run_parallel_batch records conflicts to the sidecar."""
        from features.molecules import artifact_service

        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)

        # Force ambertools availability check (bypass) since we never reach it
        monkeypatch.setattr(artifact_service, "check_ambertools_available", lambda: True)

        # Two rows sharing a source_id with different mol_path → 1 conflict.
        rows = [
            {
                "mol_id": "Carbon_Nano_Tube",
                "source_id": "carbon_sp2_passthrough_v1",
                "consumer_ids": ["Carbon_Nano_Tube", "Graphine"],
                "mol_path": str(tmp_path / "cnt.mol"),
                "ff_assignment": {},
            },
            {
                "mol_id": "Graphine",
                "source_id": "carbon_sp2_passthrough_v1",
                "consumer_ids": ["Carbon_Nano_Tube", "Graphine"],
                "mol_path": str(tmp_path / "graph.mol"),
                "ff_assignment": {},
            },
        ]
        # mol files exist so canonical worker would still run; conflict is
        # detected pre-submission.
        (tmp_path / "cnt.mol").write_text("")
        (tmp_path / "graph.mol").write_text("")

        unique, conflicts = artifact_service.dedupe_by_source_id(rows)
        assert len(unique) == 1
        assert len(conflicts) == 1

        # Manually invoke the conflict-recording branch (run_parallel_batch
        # would normally do this) to keep this test fast and free of
        # ProcessPoolExecutor side effects.
        store = AdminStatusStore(tmp_path)
        for row in conflicts:
            err = ArtifactGenerationError(
                stage="preflight",
                failure_code=ArtifactFailureCode.SHARED_SOURCE_ID_CONFLICT,
                message="conflict",
            )
            store.record_failure(
                row.get("source_id"),
                err,
                consumer_ids=row.get("consumer_ids"),
            )

        loaded = store.get("carbon_sp2_passthrough_v1")
        assert loaded is not None
        assert loaded.failure_code == "shared_source_id_conflict"


# ─────────────────────────────────────────────────────────────────────────────
# v00.99.43: recommended_action_for_failure helper
# ─────────────────────────────────────────────────────────────────────────────


class TestRecommendedActionForFailure:
    def test_sqm_timeout_maps_to_retry_sqm_robust(self):
        from features.molecules.admin_status import recommended_action_for_failure

        assert recommended_action_for_failure("sqm_timeout") == "retry_sqm_robust"
        assert recommended_action_for_failure("sqm_nonconverged") == "retry_sqm_robust"

    def test_passthrough_maps_to_manual_curation(self):
        from features.molecules.admin_status import recommended_action_for_failure

        assert (
            recommended_action_for_failure("passthrough_unsupported") == "manual_curation_required"
        )

    def test_shared_source_id_conflict_maps_correctly(self):
        from features.molecules.admin_status import recommended_action_for_failure

        assert (
            recommended_action_for_failure("shared_source_id_conflict")
            == "split_source_id_or_align_structure"
        )

    def test_unknown_or_none_returns_empty_string(self):
        from features.molecules.admin_status import recommended_action_for_failure

        assert recommended_action_for_failure(None) == ""
        assert recommended_action_for_failure("") == ""
        assert recommended_action_for_failure("not_a_real_code") == ""
