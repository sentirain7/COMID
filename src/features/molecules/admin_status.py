"""Persistent admin-side diagnostic store for organic GAFF2 artifacts.

Phase 3 (v00.99.41) — Operational state (failure codes, stderr excerpts,
preflight verdict, last attempt timestamps) lives next to the artifact JSON
in a sibling ``.admin_status/`` directory. This keeps successful artifact
JSONs as the science SSOT while letting admin tooling answer "why is this
not generating?" across process restarts.

File layout::

    data/forcefield_artifacts/organic_gaff2/
    ├─ Toluene.json                  # successful artifact (science SSOT)
    └─ .admin_status/                # operational state (this module)
       ├─ Toluene.json               # last_success_at, generation_profile, ...
       └─ carbon_sp2_passthrough_v1.json   # failure_code=passthrough_unsupported, ...

One sidecar file per ``source_id`` so there is no shared writer. Writes are
atomic (tmp-file + ``os.replace``); reads are best-effort and tolerate
missing or corrupt sidecar files (returning ``None``) so a partial state
never blocks the public API.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from common.logging import get_logger

from .exceptions import ArtifactFailureCode, ArtifactGenerationError

logger = get_logger("molecules.admin_status")


SIDECAR_DIRNAME = ".admin_status"

VALID_STATUSES: frozenset[str] = frozenset(
    {
        "complete",
        "incomplete",
        "pending",
        "failed",
        "passthrough",
        "manual_review",
    }
)


# v00.99.43: shared mapping so worker, single-row admin generate, and any
# future caller surface the same operator hint for a given failure_code.
# Empty string means "no canned recommendation; rely on stderr_excerpt".
_RECOMMENDED_ACTIONS: dict[str, str] = {
    "sqm_timeout": "retry_sqm_robust",
    "sqm_nonconverged": "retry_sqm_robust",
    "passthrough_unsupported": "manual_curation_required",
    "shared_source_id_conflict": "split_source_id_or_align_structure",
    "manual_review_required": "manual_curation_required",
    "input_invalid": "fix_structure_file",
}


def recommended_action_for_failure(failure_code: str | None) -> str:
    """Return the canonical operator hint for ``failure_code``.

    Used by ``_generate_one_worker``, the single-row admin generate
    endpoint, and the runtime auto-generation path so the FF Parameters
    table renders the same hint regardless of which surface produced the
    failure. Unknown / None codes return the empty string.
    """
    if not failure_code:
        return ""
    return _RECOMMENDED_ACTIONS.get(failure_code, "")


@dataclass
class AdminStatus:
    """In-memory representation of one ``.admin_status/<source_id>.json``.

    Attributes:
        source_id: Canonical artifact identifier (filename stem).
        artifact_status: One of :data:`VALID_STATUSES`. Default ``pending``.
        failure_code: Last known :class:`ArtifactFailureCode` value or None.
        stage: Pipeline stage where the failure occurred (or ``""``).
        stderr_excerpt: Truncated subprocess stderr (≤2 KiB).
        recommended_action: Operator-readable next step.
        generation_profile: Last-used profile (``baseline | sqm_robust``).
        preflight: Optional dict with RDKit preflight findings.
        consumer_ids: All mol_ids resolving to this source_id.
        last_attempt_at: Unix timestamp of the most recent generation try.
        last_success_at: Unix timestamp of the most recent success or None.
    """

    source_id: str
    artifact_status: str = "pending"
    failure_code: str | None = None
    stage: str = ""
    stderr_excerpt: str = ""
    recommended_action: str = ""
    generation_profile: str = ""
    generator: str = ""
    preflight: dict | None = None
    consumer_ids: list[str] = field(default_factory=list)
    last_attempt_at: float | None = None
    last_success_at: float | None = None

    def __post_init__(self) -> None:
        if self.artifact_status not in VALID_STATUSES:
            raise ValueError(
                f"artifact_status={self.artifact_status!r} not in {sorted(VALID_STATUSES)}"
            )
        if self.stderr_excerpt and len(self.stderr_excerpt) > 2048:
            self.stderr_excerpt = self.stderr_excerpt[:2045] + "..."

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> AdminStatus:
        # Defensive defaults so older sidecars without newer fields still load.
        return cls(
            source_id=str(raw.get("source_id") or ""),
            artifact_status=str(raw.get("artifact_status") or "pending"),
            failure_code=(str(raw["failure_code"]) if raw.get("failure_code") else None),
            stage=str(raw.get("stage") or ""),
            stderr_excerpt=str(raw.get("stderr_excerpt") or ""),
            recommended_action=str(raw.get("recommended_action") or ""),
            generation_profile=str(raw.get("generation_profile") or ""),
            generator=str(raw.get("generator") or ""),
            preflight=raw.get("preflight") if isinstance(raw.get("preflight"), dict) else None,
            consumer_ids=list(raw.get("consumer_ids") or []),
            last_attempt_at=(
                float(raw["last_attempt_at"])  # type: ignore[arg-type]
                if raw.get("last_attempt_at") is not None
                else None
            ),
            last_success_at=(
                float(raw["last_success_at"])  # type: ignore[arg-type]
                if raw.get("last_success_at") is not None
                else None
            ),
        )


class AdminStatusStore:
    """File-backed sidecar store, one JSON per ``source_id``.

    Args:
        artifact_dir: Root organic_gaff2 artifact directory. Sidecar files
            live in ``<artifact_dir>/.admin_status/``.
    """

    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.sidecar_dir = self.artifact_dir / SIDECAR_DIRNAME

    # ------------------------------------------------------------------ paths

    def path_for(self, source_id: str) -> Path:
        """Return the canonical sidecar path for ``source_id``.

        Path-traversal hardened: the resolved path must live inside the
        sidecar directory. Even though source_id today only comes from
        catalog YAML (controlled input), this validation is defense in
        depth for future callers (admin API, scripts).
        """
        if not source_id:
            raise ValueError("source_id must not be empty")
        # Reject characters that would escape the sidecar directory.
        if any(ch in source_id for ch in ("/", "\\", "\x00")):
            raise ValueError(f"source_id contains path-separator characters: {source_id!r}")
        if source_id in {".", ".."} or source_id.startswith(".."):
            raise ValueError(f"source_id resolves outside the sidecar directory: {source_id!r}")
        candidate = self.sidecar_dir / f"{source_id}.json"
        try:
            candidate_resolved = candidate.resolve(strict=False)
            sidecar_resolved = self.sidecar_dir.resolve(strict=False)
            candidate_resolved.relative_to(sidecar_resolved)
        except ValueError as exc:
            raise ValueError(
                f"source_id resolves outside the sidecar directory: {source_id!r}"
            ) from exc
        return candidate

    # ------------------------------------------------------------------- read

    def get(self, source_id: str) -> AdminStatus | None:
        """Return the persisted :class:`AdminStatus`, or None when absent.

        Tolerates missing files and JSON corruption (logs and returns None
        rather than blowing up the public API).
        """
        path = self.path_for(source_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("admin_status sidecar %s unreadable: %s", path, exc)
            return None
        try:
            return AdminStatus.from_json(raw)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("admin_status sidecar %s schema error: %s", path, exc)
            return None

    def list_all(self) -> list[AdminStatus]:
        """Return every readable sidecar (sorted by source_id)."""
        if not self.sidecar_dir.exists():
            return []
        out: list[AdminStatus] = []
        for child in sorted(self.sidecar_dir.glob("*.json")):
            status = self.get(child.stem)
            if status is not None:
                out.append(status)
        return out

    # ------------------------------------------------------------------ write

    def write(self, status: AdminStatus) -> None:
        """Atomically persist ``status``.

        Uses ``tempfile.NamedTemporaryFile`` + ``os.replace`` so a crash
        mid-write never leaves a half-written sidecar. Caller does not need
        to hold a lock — atomic rename is the contract.
        """
        if not status.source_id:
            raise ValueError("AdminStatus.source_id must be non-empty")
        self.sidecar_dir.mkdir(parents=True, exist_ok=True)
        target = self.path_for(status.source_id)
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            dir=str(self.sidecar_dir),
            prefix=f".{status.source_id}.",
            suffix=".tmp",
        ) as tmp:
            json.dump(status.to_json(), tmp, indent=2)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)

    def delete(self, source_id: str) -> bool:
        """Remove the sidecar for ``source_id`` (idempotent)."""
        path = self.path_for(source_id)
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("admin_status delete failed for %s: %s", path, exc)
            return False
        return True

    # ----------------------------------------------------------- helpers

    def record_failure(
        self,
        source_id: str,
        error: ArtifactGenerationError,
        *,
        consumer_ids: list[str] | None = None,
        generation_profile: str = "baseline",
        preflight: dict | None = None,
        recommended_action: str = "",
    ) -> AdminStatus:
        """Convenience helper to translate an :class:`ArtifactGenerationError`
        into a sidecar entry with ``artifact_status=failed``.
        """
        existing = self.get(source_id)
        last_success = existing.last_success_at if existing else None
        status = AdminStatus(
            source_id=source_id,
            artifact_status="failed",
            failure_code=error.failure_code.value,
            stage=error.stage,
            stderr_excerpt=error.stderr_excerpt,
            recommended_action=recommended_action,
            generation_profile=generation_profile,
            preflight=preflight,
            consumer_ids=list(consumer_ids or []),
            last_attempt_at=time.time(),
            last_success_at=last_success,
        )
        self.write(status)
        return status

    def record_success(
        self,
        source_id: str,
        *,
        consumer_ids: list[str] | None = None,
        generation_profile: str = "baseline",
        generator: str = "",
    ) -> AdminStatus:
        """Mark the source_id as successfully (re)generated.

        Clears stale failure fields so the admin UI does not keep showing a
        failure_code that has since been resolved.
        """
        now = time.time()
        status = AdminStatus(
            source_id=source_id,
            artifact_status="complete",
            failure_code=None,
            stage="",
            stderr_excerpt="",
            recommended_action="",
            generation_profile=generation_profile,
            generator=generator,
            preflight=None,
            consumer_ids=list(consumer_ids or []),
            last_attempt_at=now,
            last_success_at=now,
        )
        self.write(status)
        return status

    def record_passthrough(
        self,
        source_id: str,
        *,
        consumer_ids: list[str] | None = None,
    ) -> AdminStatus:
        """Mark a passthrough source_id (no executor available)."""
        status = AdminStatus(
            source_id=source_id,
            artifact_status="passthrough",
            failure_code=ArtifactFailureCode.PASSTHROUGH_UNSUPPORTED.value,
            stage="preflight",
            recommended_action=(
                "No AM1-BCC executor for this source_id. Curate manually or "
                "wait for the catalog-direct LJ runtime strategy."
            ),
            consumer_ids=list(consumer_ids or []),
            last_attempt_at=time.time(),
        )
        self.write(status)
        return status
