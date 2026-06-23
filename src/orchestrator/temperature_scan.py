"""Temperature scan presets — convenience factories for BatchJobBinderCellSpec.

Standard temperatures from asphalt_binder.yaml.
"""

from common.seed import generate_seed
from contracts.policies.temperature import (
    DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K,
    DEFAULT_TEMPERATURE_PRIORITY_K,
)
from orchestrator.batch_job_binder_cell import BatchJobBinderCellSpec

STANDARD_TEMPERATURES: list[float] = list(DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K)
PRIORITY_TEMPERATURES: list[float] = list(DEFAULT_TEMPERATURE_PRIORITY_K)
ALL_BINDER_TYPES: list[str] = ["AAA1", "AAK1", "AAM1"]
ALL_AGING_STATES: list[str] = ["non_aging", "short_aging", "long_aging"]


def full_screening_scan(
    binder_types: list[str] | None = None,
    seed: int | None = None,
) -> BatchJobBinderCellSpec:
    """3 binders x 5 temperatures x 1 aging = 15 jobs.

    Args:
        binder_types: Override binder list (default: AAA1, AAK1, AAM1)
        seed: Random seed

    Returns:
        BatchJobBinderCellSpec for full screening
    """
    return BatchJobBinderCellSpec(
        binder_types=binder_types or ALL_BINDER_TYPES,
        structure_sizes=["X1"],
        temperatures_k=STANDARD_TEMPERATURES,
        aging_states=["non_aging"],
        tier="screening",
        seed=generate_seed(seed),
        temperature_priority=PRIORITY_TEMPERATURES,
    )


def aging_comparison_scan(
    binder_type: str = "AAA1",
    seed: int | None = None,
) -> BatchJobBinderCellSpec:
    """1 binder x 5 temperatures x 3 aging states = 15 jobs.

    Args:
        binder_type: Binder type to compare aging
        seed: Random seed

    Returns:
        BatchJobBinderCellSpec for aging comparison
    """
    return BatchJobBinderCellSpec(
        binder_types=[binder_type],
        structure_sizes=["X1"],
        temperatures_k=STANDARD_TEMPERATURES,
        aging_states=ALL_AGING_STATES,
        tier="screening",
        seed=generate_seed(seed),
        temperature_priority=PRIORITY_TEMPERATURES,
    )


def quick_validation_scan(
    binder_types: list[str] | None = None,
    seed: int | None = None,
) -> BatchJobBinderCellSpec:
    """3 binders x 2 priority temperatures = 6 jobs (fast check).

    Args:
        binder_types: Override binder list (default: AAA1, AAK1, AAM1)
        seed: Random seed

    Returns:
        BatchJobBinderCellSpec for quick validation
    """
    return BatchJobBinderCellSpec(
        binder_types=binder_types or ALL_BINDER_TYPES,
        structure_sizes=["X1"],
        temperatures_k=PRIORITY_TEMPERATURES,
        aging_states=["non_aging"],
        tier="screening",
        seed=generate_seed(seed),
        temperature_priority=PRIORITY_TEMPERATURES,
    )


def additive_doe_scan(
    additive_types: list[str] | None = None,
    additive_concentrations: list[float] | None = None,
    seed: int | None = None,
) -> BatchJobBinderCellSpec:
    """Priority additive DOE scan for baseline known-additive data collection."""
    return BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        structure_sizes=["X1"],
        temperatures_k=PRIORITY_TEMPERATURES,
        aging_states=["non_aging"],
        tier="screening",
        seed=generate_seed(seed),
        temperature_priority=PRIORITY_TEMPERATURES,
        additive_types=additive_types
        or ["SBS", "PPA", "Elvaloy", "Sasobit", "NanoClay", "CRM", "Lignin"],
        additive_concentrations=additive_concentrations or [2.0, 5.0, 8.0],
    )


def exploration_scan(
    *,
    additive_types: list[str],
    binder_types: list[str] | None = None,
    temperatures_k: list[float] | None = None,
    concentrations: list[float] | None = None,
    seed: int | None = None,
) -> BatchJobBinderCellSpec:
    """Gap-filling exploration scan for untested additive conditions.

    Same spec factory pattern as additive_doe_scan, used by the planning
    orchestrator to fill coverage gaps identified by AdditiveCoverageReport.

    Args:
        additive_types: Additive types to explore (from gap analysis).
        binder_types: Override binder list (default: AAA1).
        temperatures_k: Override temperatures (default: priority temperatures).
        concentrations: Override concentrations (default: from exploration policy).
        seed: Random seed.

    Returns:
        BatchJobBinderCellSpec for exploration wave.
    """
    from contracts.policies.exploration_policy import DEFAULT_EXPLORATION_POLICY

    return BatchJobBinderCellSpec(
        binder_types=binder_types or ["AAA1"],
        structure_sizes=["X1"],
        temperatures_k=temperatures_k or PRIORITY_TEMPERATURES,
        aging_states=["non_aging"],
        tier="screening",
        seed=generate_seed(seed),
        temperature_priority=PRIORITY_TEMPERATURES,
        additive_types=additive_types,
        additive_concentrations=concentrations
        or DEFAULT_EXPLORATION_POLICY.default_exploration_concentrations,
    )
