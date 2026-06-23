"""v00.99.42 reinforcement tests — admin helpers + source_generation_lock.

Validates the two refactor steps requested by Codex:

1. ``validate_admin_generation_request`` and ``diagnose_artifact_target``
   are the single source of truth for admin gating + preflight; the API
   router and the CLI both delegate to them.
2. ``source_generation_lock`` is the shared fcntl primitive that both
   ``artifact_runtime`` and the admin/public/batch generate paths use,
   so the artifact JSON write and the admin sidecar write live in the
   same critical section.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from features.molecules import artifact_service
from features.molecules.admin_status import AdminStatusStore
from features.molecules.artifact_service import (
    AdminGenerationError,
    ArtifactTarget,
    cleanup_stale_generation_locks,
    diagnose_artifact_target,
    resolve_artifact_target,
    source_generation_lock,
    validate_admin_generation_request,
)
from features.molecules.exceptions import (
    ArtifactFailureCode,
    ArtifactGenerationError,
)

# ─────────────────────────────────────────────────────────────────────────────
# validate_admin_generation_request
# ─────────────────────────────────────────────────────────────────────────────


def _ordinary_target() -> ArtifactTarget:
    return resolve_artifact_target("Toluene")


def _passthrough_target() -> ArtifactTarget:
    """Synthesize a passthrough target via the production resolver.

    The current catalog has no ``organic_gaff2_passthrough`` entries any
    more (carbon allotropes moved to organic_gaff2 + fragment fallback in
    v01.00.12+), so the passthrough gate is exercised through the explicit
    ``ff_assignment.parameterization`` channel that
    ``resolve_artifact_target`` supports for non-YAML sources.
    """
    return resolve_artifact_target(
        "Carbon_Nano_Tube",
        {
            "route": "organic_curated_artifact",
            "source_id": "Carbon_Nano_Tube",
            "parameterization": {"mode": "organic_gaff2_passthrough"},
        },
    )


class TestValidateAdminGenerationRequest:
    def test_unknown_profile_400(self):
        target = _ordinary_target()
        with pytest.raises(AdminGenerationError) as exc:
            validate_admin_generation_request(target, "aggressive", store=None)
        assert exc.value.status_code == 400

    def test_passthrough_405(self):
        target = _passthrough_target()
        with pytest.raises(AdminGenerationError) as exc:
            validate_admin_generation_request(target, "baseline", store=None)
        assert exc.value.status_code == 405

    def test_sqm_robust_blocked_without_prior_failure(self, tmp_path: Path):
        target = _ordinary_target()
        store = AdminStatusStore(tmp_path)
        with pytest.raises(AdminGenerationError) as exc:
            validate_admin_generation_request(target, "sqm_robust", store=store)
        assert exc.value.status_code == 409
        assert "latest_failure_code" in exc.value.detail

    def test_sqm_robust_allowed_after_sqm_timeout(self, tmp_path: Path):
        target = _ordinary_target()
        store = AdminStatusStore(tmp_path)
        store.record_failure(
            target.source_id,
            ArtifactGenerationError(
                stage="antechamber",
                failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            ),
        )
        # Should NOT raise.
        validate_admin_generation_request(target, "sqm_robust", store=store)

    def test_sqm_robust_blocked_after_non_sqm_failure(self, tmp_path: Path):
        target = _ordinary_target()
        store = AdminStatusStore(tmp_path)
        store.record_failure(
            target.source_id,
            ArtifactGenerationError(
                stage="parmchk2",
                failure_code=ArtifactFailureCode.PARMCHK2_FAILED,
            ),
        )
        with pytest.raises(AdminGenerationError) as exc:
            validate_admin_generation_request(target, "sqm_robust", store=store)
        assert exc.value.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# diagnose_artifact_target
# ─────────────────────────────────────────────────────────────────────────────


class TestDiagnoseArtifactTarget:
    def test_passthrough_returns_manual_review(self):
        target = _passthrough_target()
        report = diagnose_artifact_target(target)
        assert report["verdict"] == "manual_review"
        assert any(f["kind"] == "passthrough" for f in report["findings"])

    def test_ordinary_target_runs_preflight(self):
        target = _ordinary_target()
        report = diagnose_artifact_target(target)
        assert "verdict" in report
        assert "findings" in report
        assert report["mol_id"] == "Toluene"


# ─────────────────────────────────────────────────────────────────────────────
# source_generation_lock
# ─────────────────────────────────────────────────────────────────────────────


class TestSourceGenerationLock:
    def test_creates_lock_file_and_keeps_marker(self, tmp_path: Path):
        """v00.99.42 — marker file MUST persist on exit.

        Removing it would let a late writer open a fresh inode while a
        prior waiter still holds the original — see
        ``test_three_thread_inode_stability``. Stale cleanup is the only
        path that may remove the marker.
        """
        with source_generation_lock("Toluene", artifact_dir=tmp_path) as lock_path:
            assert lock_path.exists()
            assert lock_path.name == ".Toluene.generating.lock"
        # Marker must remain — cleanup is owned by
        # cleanup_stale_generation_locks(), not by the context manager.
        assert lock_path.exists()

    def test_serializes_concurrent_threads(self, tmp_path: Path):
        """Two threads acquiring the same source_id must run sequentially."""
        observed: list[str] = []
        gate = threading.Event()

        def _worker(tag: str, sleep_s: float) -> None:
            with source_generation_lock("Toluene", artifact_dir=tmp_path):
                observed.append(f"{tag}-enter")
                gate.set()
                time.sleep(sleep_s)
                observed.append(f"{tag}-exit")

        t1 = threading.Thread(target=_worker, args=("A", 0.10))
        t2 = threading.Thread(target=_worker, args=("B", 0.05))
        t1.start()
        gate.wait()  # ensure A holds the lock before B starts
        t2.start()
        t1.join()
        t2.join()

        # Sequence MUST be A-enter, A-exit, B-enter, B-exit (no interleave).
        assert observed == ["A-enter", "A-exit", "B-enter", "B-exit"]

    def test_different_source_ids_do_not_block(self, tmp_path: Path):
        """Lock is per-source_id — different source_ids can run in parallel."""
        observed: list[str] = []

        def _worker(sid: str) -> None:
            with source_generation_lock(sid, artifact_dir=tmp_path):
                observed.append(f"{sid}-enter")
                time.sleep(0.05)
                observed.append(f"{sid}-exit")

        t1 = threading.Thread(target=_worker, args=("Toluene",))
        t2 = threading.Thread(target=_worker, args=("Methanol",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Both completed; ordering may interleave (no shared lock).
        assert set(observed) == {
            "Toluene-enter",
            "Toluene-exit",
            "Methanol-enter",
            "Methanol-exit",
        }

    def test_cleanup_stale_locks_removes_old_files(self, tmp_path: Path, monkeypatch) -> None:
        # Force stale threshold to 0 so any lock is "old".
        monkeypatch.setattr(artifact_service, "_STALE_LOCK_THRESHOLD_SECONDS", 0)
        stale = tmp_path / ".old.generating.lock"
        stale.write_text("")
        # Make it appear ancient.
        old_ts = time.time() - 3600
        import os

        os.utime(stale, (old_ts, old_ts))
        removed = cleanup_stale_generation_locks(tmp_path)
        assert removed == 1
        assert not stale.exists()

    def test_lock_marker_persists_across_acquisitions(self, tmp_path: Path):
        """v00.99.42 — lock file must NOT be unlinked on normal exit.

        Codex's race: A holds lock, B blocks on the same fd. If A unlinks
        on exit, a third writer C opens a fresh inode and locks it; B
        wakes on the original (now-unlinked) inode, and B + C end up with
        two concurrent exclusive locks. Pinning the marker file prevents
        this.
        """
        with source_generation_lock("Toluene", artifact_dir=tmp_path) as p:
            assert p.exists()
        # Marker MUST persist after release.
        assert p.exists()
        # Acquiring again hits the same inode.
        first_inode = p.stat().st_ino
        with source_generation_lock("Toluene", artifact_dir=tmp_path) as p2:
            assert p2.stat().st_ino == first_inode

    def test_three_thread_inode_stability(self, tmp_path: Path):
        """A holds → B waits → A releases → C arrives. B and C must
        serialize, never overlap, and must lock the same inode."""
        observed: list[str] = []
        a_acquired = threading.Event()
        a_release_now = threading.Event()
        b_started = threading.Event()
        c_started = threading.Event()
        seen_inodes: list[int] = []

        def _a():
            with source_generation_lock("Toluene", artifact_dir=tmp_path) as p:
                seen_inodes.append(p.stat().st_ino)
                observed.append("A-enter")
                a_acquired.set()
                a_release_now.wait()
                observed.append("A-exit")

        def _b():
            b_started.set()
            with source_generation_lock("Toluene", artifact_dir=tmp_path) as p:
                seen_inodes.append(p.stat().st_ino)
                observed.append("B-enter")
                time.sleep(0.05)
                observed.append("B-exit")

        def _c():
            c_started.set()
            with source_generation_lock("Toluene", artifact_dir=tmp_path) as p:
                seen_inodes.append(p.stat().st_ino)
                observed.append("C-enter")
                time.sleep(0.05)
                observed.append("C-exit")

        ta = threading.Thread(target=_a)
        ta.start()
        a_acquired.wait()
        tb = threading.Thread(target=_b)
        tb.start()
        b_started.wait()
        time.sleep(0.05)  # let B park inside flock
        tc = threading.Thread(target=_c)
        tc.start()
        c_started.wait()
        time.sleep(0.05)  # let C park inside flock
        a_release_now.set()
        ta.join()
        tb.join()
        tc.join()

        # No interleave between B and C; A is first.
        assert observed[0] == "A-enter"
        assert observed[1] == "A-exit"
        # B and C run after A in some order, but never overlap.
        rest = observed[2:]
        assert rest in (
            ["B-enter", "B-exit", "C-enter", "C-exit"],
            ["C-enter", "C-exit", "B-enter", "B-exit"],
        )
        # All three threads must have locked the SAME inode — proves the
        # marker file was not recycled mid-flight.
        assert len(set(seen_inodes)) == 1, seen_inodes


# ─────────────────────────────────────────────────────────────────────────────
# Worker defense-in-depth: profile gating
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkerProfileDefense:
    """v00.99.42 — workers re-check admin policy when profile != baseline."""

    def test_worker_blocks_sqm_robust_without_prior_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        # Use a real catalog mol so the path is exercised end-to-end up
        # to (but not into) AmberTools.
        target = resolve_artifact_target("Toluene")
        result = artifact_service._generate_one_worker(
            {
                "mol_id": "Toluene",
                "source_id": target.source_id,
                "consumer_ids": target.consumer_ids,
                "mol_path": str(target.structure_file),
                "ff_assignment": dict(target.ff_assignment),
                "generation_profile": "sqm_robust",
            }
        )
        assert result["status"] == "error"
        assert result["failure_code"] == "manual_review_required"
        assert "admin_policy_blocked" in result["error"]

    def test_worker_baseline_is_unaffected(self, tmp_path: Path, monkeypatch) -> None:
        """baseline must NOT trigger admin re-validation (cost/perf)."""
        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
        # Force an early exit by pointing to a non-existent mol so we
        # don't actually invoke AmberTools.
        result = artifact_service._generate_one_worker(
            {
                "mol_id": "Toluene",
                "source_id": "Toluene",
                "consumer_ids": ["Toluene"],
                "mol_path": str(tmp_path / "missing.mol"),
                "ff_assignment": {},
                "generation_profile": "baseline",
            }
        )
        # Should hit the input_invalid branch, NOT manual_review_required.
        assert result["failure_code"] == "input_invalid"


# ─────────────────────────────────────────────────────────────────────────────
# Worker integration: lock + sidecar atomicity
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkerLockSidecarAtomicity:
    def test_input_invalid_path_writes_sidecar(self, tmp_path: Path, monkeypatch) -> None:
        """A worker run that fails preflight still writes the sidecar."""
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

        sidecar = AdminStatusStore(tmp_path).get("Ghost")
        assert sidecar is not None
        assert sidecar.failure_code == "input_invalid"
