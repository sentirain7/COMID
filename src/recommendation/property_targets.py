"""Property targets for inverse design.

Defines target specifications for multi-objective optimization
(user-specified property targets → composition/additive recommendation).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from contracts.schemas import FFType, RunTier, StudyType


@dataclass
class PropertyTarget:
    """A single property target for optimization.

    Args:
        metric_name: Must be registered in MetricsRegistry.
        target_min: Lower bound (None = no lower bound).
        target_max: Upper bound (None = no upper bound).
        direction: "maximize", "minimize", or "target" (stay within range).
        weight: Relative importance weight.
        unit: Unit string (validated against registry if provided).
    """

    metric_name: str
    target_min: float | None = None
    target_max: float | None = None
    direction: str = "maximize"
    weight: float = 1.0
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in ("maximize", "minimize", "target"):
            raise ValueError(f"Invalid direction: {self.direction}")

    def is_satisfied(self, value: float) -> bool:
        """Check whether a predicted value meets this target."""
        if self.target_min is not None and value < self.target_min:
            return False
        if self.target_max is not None and value > self.target_max:
            return False
        return True

    def distance_to_target(self, value: float) -> float:
        """Compute normalised distance to the feasible range.

        Returns 0.0 if *value* is inside [target_min, target_max].
        Otherwise returns the absolute shortfall / overshoot.
        """
        if self.target_min is not None and value < self.target_min:
            return self.target_min - value
        if self.target_max is not None and value > self.target_max:
            return value - self.target_max
        return 0.0


@dataclass
class PropertyTargetSet:
    """A named collection of property targets (e.g. a PG preset).

    Args:
        name: Human-readable identifier (e.g. "PG_64_22").
        description: Short explanation.
        targets: List of individual PropertyTarget items.
    """

    name: str
    description: str
    targets: list[PropertyTarget] = field(default_factory=list)

    def validate_against_registry(self) -> tuple[bool, list[str]]:
        """Validate every metric_name against MetricsRegistry.

        Returns:
            (ok, errors) where *errors* lists any invalid metric names.
        """
        errors: list[str] = []
        for t in self.targets:
            if not DEFAULT_METRICS_REGISTRY.is_valid_metric(t.metric_name):
                errors.append(f"Unknown metric: {t.metric_name}")
            elif t.unit is not None:
                registry_unit = DEFAULT_METRICS_REGISTRY.get_unit(t.metric_name)
                if t.unit != registry_unit:
                    errors.append(
                        f"Unit mismatch for {t.metric_name}: "
                        f"target={t.unit}, registry={registry_unit}"
                    )
        return (len(errors) == 0, errors)

    def get_objectives(self) -> list[dict]:
        """Convert targets to BayesianOptimizer-compatible objective dicts."""
        objectives: list[dict] = []
        for t in self.targets:
            objectives.append(
                {
                    "name": t.metric_name,
                    "direction": t.direction if t.direction != "target" else "maximize",
                    "weight": t.weight,
                }
            )
        return objectives

    def are_all_satisfied(self, values: dict[str, float]) -> bool:
        """Check if all targets are satisfied by *values*."""
        for t in self.targets:
            v = values.get(t.metric_name)
            if v is None or not t.is_satisfied(v):
                return False
        return True

    def compute_distances(self, values: dict[str, float]) -> dict[str, float]:
        """Compute distance-to-target for each metric."""
        distances: dict[str, float] = {}
        for t in self.targets:
            v = values.get(t.metric_name)
            if v is not None:
                distances[t.metric_name] = t.distance_to_target(v)
            else:
                distances[t.metric_name] = float("inf")
        return distances

# ── EvalCondition / TargetSpec (wrapper — BayesianOptimizer 회귀 방지) ───


@dataclass
class EvalCondition:
    """Evaluation condition for DB search, simulation planning, and result comparison.

    Separated from PropertyTarget to avoid regressing InverseDesigner/BayesianOptimizer.

    Args:
        temperature_K: Evaluation temperature in Kelvin.
        ff_type: Force field type for simulation.
        run_tier: Simulation tier (screening, confirm, etc.).
        study_type: Simulation study type (bulk, layer_bulkff, etc.).
        namespace: Metric namespace filter for DB queries.
    """

    temperature_K: float = 298.0
    ff_type: FFType = FFType.BULK_FF_GAFF2
    run_tier: RunTier = RunTier.SCREENING
    study_type: StudyType = StudyType.BULK
    namespace: str | None = None

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "temperature_K": self.temperature_K,
            "ff_type": self.ff_type.value,
            "run_tier": self.run_tier.value,
            "study_type": self.study_type.value,
            "namespace": self.namespace,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EvalCondition:
        """Deserialize from JSON storage."""
        raw_ff = d.get("ff_type", "bulk_ff_gaff2")
        try:
            ff_type = FFType(raw_ff)
        except ValueError:
            raise ValueError(
                f"Stale ff_type='{raw_ff}' found in persisted data. "
                "Run scripts/migrate_bulk_ff_to_gaff2.py --verify"
            ) from None
        return cls(
            temperature_K=d.get("temperature_K", 298.0),
            ff_type=ff_type,
            run_tier=RunTier(d.get("run_tier", "screening")),
            study_type=StudyType(d.get("study_type", "bulk")),
            namespace=d.get("namespace"),
        )


@dataclass
class TargetSpec:
    """Bundle a PropertyTarget with its evaluation condition.

    Used only in DB search, simulation planning, and result comparison.
    InverseDesigner/BayesianOptimizer continue to use PropertyTarget directly.

    Args:
        target: Optimization target (unchanged).
        condition: Evaluation/search condition (new).
    """

    target: PropertyTarget
    condition: EvalCondition = field(default_factory=EvalCondition)

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "metric_name": self.target.metric_name,
            "target_min": self.target.target_min,
            "target_max": self.target.target_max,
            "direction": self.target.direction,
            "weight": self.target.weight,
            "unit": self.target.unit,
            "condition": self.condition.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> TargetSpec:
        """Deserialize from JSON storage."""
        condition_data = d.get("condition", {})
        return cls(
            target=PropertyTarget(
                metric_name=d["metric_name"],
                target_min=d.get("target_min"),
                target_max=d.get("target_max"),
                direction=d.get("direction", "maximize"),
                weight=d.get("weight", 1.0),
                unit=d.get("unit"),
            ),
            condition=EvalCondition.from_dict(condition_data),
        )
