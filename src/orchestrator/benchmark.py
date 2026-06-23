"""Phase 4 benchmark infrastructure.

Provides the ``BenchmarkRunner`` which orchestrates the 45-run
(3 binders x 3 temperatures x 5 seeds) benchmark batch job and validates
results against literature reference values.

Validation gates (from ``docs/PHASE3_6_EXECUTION_PLAN.md``):
  * density:  ±2 %
  * CED:      ±10 %
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from common.logging import get_logger
from common.seed import generate_seed
from orchestrator.batch_job_binder_cell import BatchJobBinderCellResult, BatchJobBinderCellSpec
from orchestrator.temperature_scan import ALL_BINDER_TYPES

if TYPE_CHECKING:
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

logger = get_logger("orchestrator.benchmark")


# ── Literature reference values ────────────────────────────────────
# Sources:
#   Li & Greenfield (2014) — density at 298 K
#   Yun (2024) — CED values
#   Values are approximate midpoints used for automated validation.

LITERATURE_REFERENCES: dict[str, dict[str, dict[str, float]]] = {
    "AAA1": {
        "density": {
            "273.0": 1.04,
            "293.0": 1.02,
            "313.0": 1.00,
            "333.0": 0.98,
            "373.0": 0.94,
        },
        "cohesive_energy_density": {
            "273.0": 380.0,
            "293.0": 360.0,
            "313.0": 340.0,
            "333.0": 320.0,
            "373.0": 290.0,
        },
    },
    "AAK1": {
        "density": {
            "273.0": 1.03,
            "293.0": 1.01,
            "313.0": 0.99,
            "333.0": 0.97,
            "373.0": 0.93,
        },
        "cohesive_energy_density": {
            "273.0": 370.0,
            "293.0": 350.0,
            "313.0": 330.0,
            "333.0": 310.0,
            "373.0": 280.0,
        },
    },
    "AAM1": {
        "density": {
            "273.0": 1.05,
            "293.0": 1.03,
            "313.0": 1.01,
            "333.0": 0.99,
            "373.0": 0.95,
        },
        "cohesive_energy_density": {
            "273.0": 390.0,
            "293.0": 370.0,
            "313.0": 350.0,
            "333.0": 330.0,
            "373.0": 300.0,
        },
    },
}


# ── Validation gate tolerances (Phase 4-1) ─────────────────────────

BENCHMARK_TOLERANCES: dict[str, float] = {
    "density": 0.02,  # ±2 %
    "cohesive_energy_density": 0.10,  # ±10 %
}

BENCHMARK_TEMPERATURES: list[float] = [293.0, 313.0, 333.0]
DEFAULT_BENCHMARK_SEEDS: list[int] = [1, 2, 3, 4, 5]


# ── Data classes ───────────────────────────────────────────────────


@dataclass
class MetricValidation:
    """Validation result for a single metric of a single experiment."""

    exp_id: str
    binder_type: str
    temperature_k: float
    metric_name: str
    simulated_value: float | None
    reference_value: float | None
    relative_error: float | None
    tolerance: float
    passed: bool | None  # None = no data

    def to_dict(self) -> dict[str, Any]:
        return {
            "exp_id": self.exp_id,
            "binder_type": self.binder_type,
            "temperature_k": self.temperature_k,
            "metric_name": self.metric_name,
            "simulated_value": self.simulated_value,
            "reference_value": self.reference_value,
            "relative_error": self.relative_error,
            "tolerance": self.tolerance,
            "passed": self.passed,
        }


@dataclass
class BenchmarkReport:
    """Aggregate benchmark report across all 45 runs."""

    batch_job_result: BatchJobBinderCellResult | None = None
    validations: list[MetricValidation] = field(default_factory=list)
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    missing_data: int = 0

    @property
    def pass_rate(self) -> float:
        evaluated = self.passed_checks + self.failed_checks
        if evaluated == 0:
            return 0.0
        return self.passed_checks / evaluated

    @property
    def all_gates_passed(self) -> bool:
        return self.failed_checks == 0 and self.passed_checks > 0

    def summary(self) -> dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "missing_data": self.missing_data,
            "pass_rate": round(self.pass_rate, 4),
            "all_gates_passed": self.all_gates_passed,
        }

    def per_binder_summary(self) -> dict[str, dict[str, Any]]:
        """Summarise pass/fail per binder type."""
        binders: dict[str, dict[str, int]] = {}
        for v in self.validations:
            b = binders.setdefault(v.binder_type, {"passed": 0, "failed": 0, "missing": 0})
            if v.passed is None:
                b["missing"] += 1
            elif v.passed:
                b["passed"] += 1
            else:
                b["failed"] += 1
        return binders

    def per_metric_summary(self) -> dict[str, dict[str, Any]]:
        """Summarise pass/fail per metric."""
        metrics: dict[str, dict[str, int]] = {}
        for v in self.validations:
            m = metrics.setdefault(v.metric_name, {"passed": 0, "failed": 0, "missing": 0})
            if v.passed is None:
                m["missing"] += 1
            elif v.passed:
                m["passed"] += 1
            else:
                m["failed"] += 1
        return metrics

    def format_table(self) -> str:
        """Format results as a human-readable text table."""
        header = (
            f"{'Binder':<8} {'T(K)':<8} {'Metric':<28} "
            f"{'Sim':>10} {'Ref':>10} {'Err%':>8} {'Gate':>6}"
        )
        sep = "-" * len(header)
        lines = [header, sep]
        for v in sorted(
            self.validations, key=lambda x: (x.binder_type, x.temperature_k, x.metric_name)
        ):
            sim = f"{v.simulated_value:.4f}" if v.simulated_value is not None else "N/A"
            ref = f"{v.reference_value:.1f}" if v.reference_value is not None else "N/A"
            err = f"{v.relative_error * 100:.2f}" if v.relative_error is not None else "N/A"
            gate = "PASS" if v.passed else ("FAIL" if v.passed is False else "N/A")
            lines.append(
                f"{v.binder_type:<8} {v.temperature_k:<8.1f} {v.metric_name:<28} {sim:>10} {ref:>10} {err:>8} {gate:>6}"
            )
        lines.append(sep)
        lines.append(
            f"Total: {self.total_checks} checks | "
            f"Passed: {self.passed_checks} | Failed: {self.failed_checks} | "
            f"Missing: {self.missing_data} | Rate: {self.pass_rate:.1%}"
        )
        return "\n".join(lines)


# ── Benchmark runner ───────────────────────────────────────────────


class BenchmarkRunner:
    """Orchestrate the Phase 4 benchmark (45 runs) and validate results.

    Usage::

        runner = BenchmarkRunner(experiment_repo, metric_repo)

        # Option A — validate already-completed experiments
        report = runner.validate_results()

        # Option B — generate batch-job spec for submission
        spec = runner.create_batch_job_spec()
    """

    def __init__(
        self,
        experiment_repo: ExperimentRepository | None = None,
        metric_repo: MetricRepository | None = None,
        references: dict | None = None,
        tolerances: dict[str, float] | None = None,
    ) -> None:
        self.experiment_repo = experiment_repo
        self.metric_repo = metric_repo
        self.references = references or LITERATURE_REFERENCES
        self.tolerances = tolerances or BENCHMARK_TOLERANCES

    # ── batch-job helpers ─────────────────────────────────────────

    @staticmethod
    def create_batch_job_spec(
        binder_types: list[str] | None = None,
        seed: int | None = None,
    ) -> BatchJobBinderCellSpec:
        """Create a single-seed 9-run benchmark batch-job spec.

        Args:
            binder_types: Override binders (default AAA1/AAK1/AAM1).
            seed: Random seed.

        Returns:
            BatchJobBinderCellSpec ready for ``BatchJobBinderCellRunner.submit()``.
        """
        return BatchJobBinderCellSpec(
            binder_types=binder_types or ALL_BINDER_TYPES,
            structure_sizes=["X1"],
            temperatures_k=BENCHMARK_TEMPERATURES,
            aging_states=["non_aging"],
            tier="screening",
            seed=generate_seed(seed),
            temperature_priority=[293.0, 313.0],
        )

    @staticmethod
    def create_batch_job_specs(
        binder_types: list[str] | None = None,
        seeds: list[int] | None = None,
    ) -> list[BatchJobBinderCellSpec]:
        """Create benchmark batch-job specs across seeds (default: 45 total runs)."""
        resolved_seeds = BenchmarkRunner._resolve_seeds(seed=None, seeds=seeds)
        return [
            BenchmarkRunner.create_batch_job_spec(binder_types=binder_types, seed=s)
            for s in resolved_seeds
        ]

    @staticmethod
    def _resolve_seeds(seed: int | None, seeds: list[int] | None) -> list[int]:
        """Resolve seed input into a unique, ordered list."""
        if seeds is not None:
            # Preserve user-provided order while removing duplicates.
            return list(dict.fromkeys(seeds))
        if seed is not None:
            return [seed]
        return DEFAULT_BENCHMARK_SEEDS.copy()

    @staticmethod
    def expected_exp_ids(
        binder_types: list[str] | None = None,
        seed: int | None = None,
        seeds: list[int] | None = None,
    ) -> list[str]:
        """Return the list of exp_ids that make up the benchmark.

        Useful for checking completeness without a DB connection.
        """
        from common.pathing import generate_exp_id
        from contracts.policies.tier import DEFAULT_TIER_POLICY

        binders = binder_types or ALL_BINDER_TYPES
        resolved_seeds = BenchmarkRunner._resolve_seeds(seed=seed, seeds=seeds)
        target_atoms = DEFAULT_TIER_POLICY.get_target_atoms("screening")
        ids: list[str] = []
        for current_seed in resolved_seeds:
            for binder in binders:
                for temp in BENCHMARK_TEMPERATURES:
                    eid = generate_exp_id(
                        binder_type=binder,
                        structure_size="X1",
                        temperature_k=temp,
                        ff_type="bulk_ff_gaff2",
                        aging_state="non_aging",
                        atom_count=target_atoms,
                        seed=current_seed,
                    )
                    ids.append(eid)
        return ids

    # ── validation ────────────────────────────────────────────────

    def validate_single(
        self,
        binder_type: str,
        temperature_k: float,
        metric_name: str,
        simulated_value: float | None,
        exp_id: str = "",
    ) -> MetricValidation:
        """Validate a single metric value against literature reference.

        Args:
            binder_type: e.g. "AAA1"
            temperature_k: Temperature in Kelvin
            metric_name: "density" or "cohesive_energy_density"
            simulated_value: Simulation result (None if missing)
            exp_id: Experiment ID for traceability

        Returns:
            MetricValidation result.
        """
        temp_key = str(temperature_k)
        ref_value: float | None = (
            self.references.get(binder_type, {}).get(metric_name, {}).get(temp_key)
        )
        tolerance = self.tolerances.get(metric_name, 0.10)

        if simulated_value is None or ref_value is None:
            return MetricValidation(
                exp_id=exp_id,
                binder_type=binder_type,
                temperature_k=temperature_k,
                metric_name=metric_name,
                simulated_value=simulated_value,
                reference_value=ref_value,
                relative_error=None,
                tolerance=tolerance,
                passed=None,
            )

        rel_err = abs(simulated_value - ref_value) / abs(ref_value) if ref_value != 0 else 0.0
        passed = rel_err <= tolerance

        return MetricValidation(
            exp_id=exp_id,
            binder_type=binder_type,
            temperature_k=temperature_k,
            metric_name=metric_name,
            simulated_value=simulated_value,
            reference_value=ref_value,
            relative_error=rel_err,
            tolerance=tolerance,
            passed=passed,
        )

    def validate_results(
        self,
        binder_types: list[str] | None = None,
        seed: int | None = None,
        seeds: list[int] | None = None,
    ) -> BenchmarkReport:
        """Validate all benchmark experiments against literature.

        Reads completed experiments from the database and checks each
        metric against the tolerance gates.

        Args:
            binder_types: Override binders (default: AAA1/AAK1/AAM1).
            seed: Optional single seed for backward-compatible 9-run mode.
            seeds: Optional seed list (default: ``[1,2,3,4,5]`` for 45 runs).

        Returns:
            BenchmarkReport with all validation results.
        """
        if self.experiment_repo is None or self.metric_repo is None:
            raise RuntimeError("validate_results() requires experiment_repo and metric_repo.")

        binders = binder_types or ALL_BINDER_TYPES
        exp_ids = self.expected_exp_ids(binder_types=binders, seed=seed, seeds=seeds)

        report = BenchmarkReport()

        for exp_id in exp_ids:
            experiment = self.experiment_repo.get_by_id(exp_id)

            # Parse binder & temperature from the batch Binder Cell jobs
            binder, temp = self._parse_binder_temp(exp_id, binders)

            for metric_name in self.tolerances:
                sim_value: float | None = None

                if experiment is not None:
                    sim_value = self._get_metric_value(exp_id, metric_name)

                validation = self.validate_single(
                    binder_type=binder,
                    temperature_k=temp,
                    metric_name=metric_name,
                    simulated_value=sim_value,
                    exp_id=exp_id,
                )
                report.validations.append(validation)
                report.total_checks += 1

                if validation.passed is None:
                    report.missing_data += 1
                elif validation.passed:
                    report.passed_checks += 1
                else:
                    report.failed_checks += 1

        return report

    # ── internal helpers ──────────────────────────────────────────

    def _parse_binder_temp(self, exp_id: str, binders: list[str]) -> tuple[str, float]:
        """Extract binder type and temperature from exp_id."""
        from common.pathing import parse_exp_id

        parsed = parse_exp_id(exp_id)

        binder = str(parsed.get("binder_type") or parsed.get("material", ""))
        temp_val = parsed.get("temperature_k")
        temp = float(temp_val) if temp_val is not None else 293.0

        # Fallback: match against known binder list
        if binder not in binders:
            for b in binders:
                if b.lower() in exp_id.lower():
                    binder = b
                    break

        return binder, temp

    def _get_metric_value(self, exp_id: str, metric_name: str) -> float | None:
        """Retrieve a scalar metric value from the metric repository."""
        assert self.metric_repo is not None
        try:
            metric = self.metric_repo.get_latest(exp_id, metric_name)
            if metric is not None:
                return metric.value
        except Exception as e:
            logger.warning(f"Failed to retrieve {metric_name} for {exp_id}: {e}")
        return None
