"""FF Stack Governance Policy (SSOT).

Canonical source of truth for force-field stack approval status.
Each stack_id maps to a validation level that determines allowed
workflows.  The policy is static metadata; benchmark/ReaxFF evidence
is stored separately and referenced by governance consumers.

See also: ``docs/architecture/ff-governance-and-ml-readiness.md``

Vocabulary
----------
- **validated** – benchmark gates passed; production submit allowed.
- **research_only** – insufficient benchmark evidence; submit requires
  explicit admin flag; ML dataset goes to a separate slice.
- **blocked** – fail-closed; no submit, no dataset inclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from common.logging import get_logger

logger = get_logger("contracts.policies.stack_governance")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Policy-local Literal type.  Kept as Literal (not StrEnum) because
# validation_level is a stack policy concept, not a universal schema enum.
# Promotion to contracts/schema_enums.py StrEnum is deferred until Phase 6+
# when schema-wide usage is confirmed.
ValidationLevel = Literal["validated", "research_only", "blocked"]

# ---------------------------------------------------------------------------
# Stack Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StackPolicy:
    """Immutable policy descriptor for a single FF stack.

    Attributes:
        stack_id: Canonical stack identifier (from ``build_ff_provenance``).
        validation_level: Current approval state.
        allowed_workflows: Workflow keys where this stack may run.
        required_benchmark_suite: Benchmark suites that must pass before
            the stack can be promoted to *validated*.
        requires_reaxff_review: Whether outlier candidates must go through
            a ReaxFF comparison lane before production use.
        notes: Free-text rationale or reference.
    """

    stack_id: str
    validation_level: ValidationLevel = "research_only"
    allowed_workflows: tuple[str, ...] = ("preview", "list", "precompute", "artifact_generation")
    required_benchmark_suite: tuple[str, ...] = ()
    requires_reaxff_review: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Canonical policy registry
# ---------------------------------------------------------------------------

_STACK_POLICIES: dict[str, StackPolicy] = {
    "gaff2_am1bcc_v1": StackPolicy(
        stack_id="gaff2_am1bcc_v1",
        validation_level="validated",
        allowed_workflows=(
            "preview",
            "list",
            "precompute",
            "artifact_generation",
            "submit",
            "build",
            "benchmark",
            "ml_dataset_export",
        ),
        required_benchmark_suite=("density_tolerance", "ced_tolerance"),
        requires_reaxff_review=False,
        notes="Primary bulk organic stack. Benchmark tolerances: density ±2%, CED ±10%.",
    ),
    "gaff2_org__inorganic_profile__arith_v1": StackPolicy(
        stack_id="gaff2_org__inorganic_profile__arith_v1",
        validation_level="research_only",
        allowed_workflows=(
            "preview",
            "list",
            "precompute",
            "artifact_generation",
            "submit",
            "build",
            "benchmark",
        ),
        required_benchmark_suite=(),
        requires_reaxff_review=True,
        notes="Layered organic+inorganic stack. Arithmetic mixing. No benchmark suite yet.",
    ),
    "reaxff_v1": StackPolicy(
        stack_id="reaxff_v1",
        validation_level="research_only",
        allowed_workflows=(
            "preview",
            "list",
            "precompute",
            "submit",
            "build",
        ),
        required_benchmark_suite=(),
        requires_reaxff_review=False,
        notes="Reactive FF validation lane. Always research_only.",
    ),
    "gaff2_fragment_fallback_v1": StackPolicy(
        stack_id="gaff2_fragment_fallback_v1",
        validation_level="research_only",
        # build + benchmark allowed, but NO submit and NO ml_dataset_export:
        # production submit requires an explicit admin flag, and the lower-
        # confidence fragment-derived charges (fragment-boundary electronics
        # not captured by a whole-molecule AM1 SCF) are firewalled from the
        # validated ML training set.
        allowed_workflows=(
            "preview",
            "list",
            "precompute",
            "artifact_generation",
            "build",
            "benchmark",
        ),
        required_benchmark_suite=(),
        requires_reaxff_review=False,
        notes=(
            "Fragment-based GAFF2 fallback (RDKit hybridization typing, no AM1 "
            "SCF) for neutral CHONS molecules where baseline+sqm_robust both "
            "fail to converge. research_only: charge accuracy is molecule-"
            "dependent (small for symmetric non-polar systems, larger for polar "
            "ones), so excluded from the validated ML dataset."
        ),
    ),
}


def get_stack_policy(stack_id: str) -> StackPolicy | None:
    """Look up the governance policy for a stack.

    Returns ``None`` if the stack_id is unknown (caller should treat as
    *research_only* or *blocked* depending on context).
    """
    return _STACK_POLICIES.get(stack_id)


def get_validation_level(
    stack_id: str, default: ValidationLevel = "research_only"
) -> ValidationLevel:
    """Convenience: return the validation_level for a stack, with a safe default."""
    policy = get_stack_policy(stack_id)
    return policy.validation_level if policy else default


def is_workflow_allowed(stack_id: str, workflow: str) -> bool:
    """Check whether *workflow* is permitted for *stack_id*.

    Unknown stacks conservatively disallow everything except preview/list.
    """
    policy = get_stack_policy(stack_id)
    if policy is None:
        return workflow in ("preview", "list")
    return workflow in policy.allowed_workflows


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------


def assert_submit_allowed(stack_id: str) -> None:
    """Raise ``ContractError`` if the stack is not allowed to submit.

    Delegates to ``is_workflow_allowed(stack_id, "submit")`` so that
    unknown stacks are fail-closed (submit not in their default
    allowed_workflows of preview/list only).

    Called from all submission gates (molecule, dependent, layered).
    """
    if not is_workflow_allowed(stack_id, "submit"):
        from contracts.errors import ContractError, ErrorCode

        level = get_validation_level(stack_id)
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Stack '{stack_id}' (validation_level={level}) is not "
            "allowed to submit. Check stack_governance policy.",
            {"stack_id": stack_id, "validation_level": level},
        )


# ---------------------------------------------------------------------------
# Benchmark Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkEvidence:
    """Evidence from a benchmark run, linked to a stack."""

    stack_id: str
    suite_id: str  # e.g., "density_tolerance"
    all_gates_passed: bool
    pass_rate: float
    total_checks: int
    passed_checks: int
    failed_checks: int
    run_at: float | None = None  # Unix timestamp
    seed: int | None = None
    notes: str = ""


_benchmark_evidence: dict[str, list[BenchmarkEvidence]] = {}


def record_benchmark_evidence(evidence: BenchmarkEvidence) -> None:
    """Record benchmark evidence for a stack (in-memory cache)."""
    _benchmark_evidence.setdefault(evidence.stack_id, []).append(evidence)


def get_benchmark_evidence(stack_id: str) -> list[BenchmarkEvidence]:
    """Get all benchmark evidence for a stack."""
    return list(_benchmark_evidence.get(stack_id, []))


def check_benchmark_requirements(stack_id: str) -> dict[str, bool | list[str]]:
    """Check if all required benchmark suites have passed for a stack."""
    policy = get_stack_policy(stack_id)
    if not policy or not policy.required_benchmark_suite:
        return {"all_required_passed": True, "missing_suites": []}
    evidence = get_benchmark_evidence(stack_id)
    passed_suites = {e.suite_id for e in evidence if e.all_gates_passed}
    missing = [s for s in policy.required_benchmark_suite if s not in passed_suites]
    return {"all_required_passed": len(missing) == 0, "missing_suites": missing}


def check_stack_readiness(stack_id: str) -> dict[str, object]:
    """Comprehensive readiness check combining benchmark + ReaxFF review.

    Returns a dict summarizing all governance checks for the stack.
    Consumers can use this at submit time, promotion decisions, or
    ML dataset export filtering.
    """
    policy = get_stack_policy(stack_id)
    bench = check_benchmark_requirements(stack_id)

    reaxff_pending = False
    if policy and policy.requires_reaxff_review:
        # ReaxFF review is required but we check if any evidence exists
        reaxff_evidence = [
            e for e in get_benchmark_evidence(stack_id) if "reaxff" in e.suite_id.lower()
        ]
        reaxff_pending = len(reaxff_evidence) == 0

    return {
        "stack_id": stack_id,
        "validation_level": get_validation_level(stack_id),
        "submit_allowed": is_workflow_allowed(stack_id, "submit"),
        "benchmark_passed": bench["all_required_passed"],
        "benchmark_missing_suites": bench["missing_suites"],
        "reaxff_review_required": policy.requires_reaxff_review if policy else False,
        "reaxff_review_pending": reaxff_pending,
        "ready_for_production": (
            bench["all_required_passed"]
            and not reaxff_pending
            and get_validation_level(stack_id) == "validated"
        ),
    }


# ---------------------------------------------------------------------------
# ML Dataset Manifest
# ---------------------------------------------------------------------------


@dataclass
class MLDatasetManifest:
    """Manifest for an ML training dataset with FF provenance."""

    dataset_id: str
    stack_ids: list[str]  # which stacks contributed data
    validation_levels: list[str]  # validation levels of included stacks
    ff_types: list[str]
    experiment_count: int
    temperature_range_k: tuple[float, float] | None = None
    binder_types: list[str] = field(default_factory=list)
    aging_states: list[str] = field(default_factory=list)
    additive_types: list[str] = field(default_factory=list)
    exclusion_rules: dict[str, str] = field(default_factory=dict)
    label_type: str = (
        "classical_reference"  # classical_reference | literature_curated | qm_reference
    )
    created_at: float | None = None
