"""Structured failure contract for organic GAFF2 artifact generation.

Phase 3 (v00.99.41) — Concentrates the heterogeneous error surface that used
to be raised as ``RuntimeError`` from ``artifact_service.generate_gaff2_artifact``
into a single typed exception. Downstream code (admin sidecar, batch worker,
CLI scripts, public API) keys off ``stage`` + ``failure_code`` to decide
retry policy, status messages, and operator action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArtifactFailureCode(StrEnum):
    """Closed enum of artifact pipeline failure modes.

    Values are stored verbatim on the admin sidecar JSON, so renames are a
    schema migration. New codes append-only.
    """

    SQM_TIMEOUT = "sqm_timeout"
    SQM_NONCONVERGED = "sqm_nonconverged"
    ANTECHAMBER_FAILED = "antechamber_failed"
    PARMCHK2_FAILED = "parmchk2_failed"
    TLEAP_FAILED = "tleap_failed"
    PARMED_FAILED = "parmed_failed"
    INPUT_INVALID = "input_invalid"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SHARED_SOURCE_ID_CONFLICT = "shared_source_id_conflict"
    PASSTHROUGH_UNSUPPORTED = "passthrough_unsupported"


_RETRYABLE_CODES: frozenset[ArtifactFailureCode] = frozenset(
    {
        ArtifactFailureCode.SQM_TIMEOUT,
        ArtifactFailureCode.SQM_NONCONVERGED,
    }
)


@dataclass
class ArtifactGenerationError(Exception):
    """Structured failure raised by the AmberTools pipeline.

    Attributes:
        stage: Pipeline phase that triggered the failure
            (``preflight | antechamber | parmchk2 | tleap | parmed``).
        failure_code: Canonical code from :class:`ArtifactFailureCode`.
        message: Human-readable summary (used in 5xx response bodies).
        stderr_excerpt: Truncated subprocess stderr (≤2 KiB).
        retryable: Whether the admin layer is allowed to attempt
            ``sqm_robust`` recovery for this failure code. Defaults to
            ``True`` only for SQM convergence/timeout failures; everything
            else surfaces immediately.
    """

    stage: str
    failure_code: ArtifactFailureCode
    message: str = ""
    stderr_excerpt: str = ""

    def __post_init__(self) -> None:
        # Cap stderr to 2 KiB so the sidecar JSON does not balloon when
        # AmberTools dumps verbose backtraces or repeats the same warning
        # thousands of times.
        if self.stderr_excerpt and len(self.stderr_excerpt) > 2048:
            self.stderr_excerpt = self.stderr_excerpt[:2045] + "..."
        if not self.message:
            self.message = f"{self.stage} failed ({self.failure_code.value})"
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        """True iff admin ``sqm_robust`` is allowed to retry this failure."""
        return self.failure_code in _RETRYABLE_CODES

    def to_admin_payload(self) -> dict[str, object]:
        """Serialize for :class:`AdminStatusStore` sidecar persistence."""
        return {
            "stage": self.stage,
            "failure_code": self.failure_code.value,
            "stderr_excerpt": self.stderr_excerpt,
            "message": self.message,
            "retryable": self.retryable,
        }
