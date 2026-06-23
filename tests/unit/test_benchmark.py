"""
Unit tests for orchestrator.benchmark module.

Tests BenchmarkRunner validation logic, report generation,
and batch-job spec creation — without requiring a live database.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from orchestrator.benchmark import (
    BENCHMARK_TEMPERATURES,
    BENCHMARK_TOLERANCES,
    DEFAULT_BENCHMARK_SEEDS,
    LITERATURE_REFERENCES,
    BenchmarkReport,
    BenchmarkRunner,
    MetricValidation,
)

# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def runner():
    """BenchmarkRunner without DB (for validate_single tests)."""
    return BenchmarkRunner()


# ── MetricValidation dataclass ────────────────────────────────────


class TestMetricValidation:
    def test_to_dict(self):
        v = MetricValidation(
            exp_id="exp_001",
            binder_type="AAA1",
            temperature_k=293.0,
            metric_name="density",
            simulated_value=1.01,
            reference_value=1.02,
            relative_error=0.0098,
            tolerance=0.02,
            passed=True,
        )
        d = v.to_dict()
        assert d["binder_type"] == "AAA1"
        assert d["passed"] is True

    def test_missing_data(self):
        v = MetricValidation(
            exp_id="exp_002",
            binder_type="AAK1",
            temperature_k=313.0,
            metric_name="density",
            simulated_value=None,
            reference_value=0.99,
            relative_error=None,
            tolerance=0.02,
            passed=None,
        )
        assert v.passed is None


# ── BenchmarkReport ───────────────────────────────────────────────


class TestBenchmarkReport:
    def test_pass_rate_empty(self):
        r = BenchmarkReport()
        assert r.pass_rate == 0.0
        assert not r.all_gates_passed

    def test_pass_rate_all_passed(self):
        r = BenchmarkReport(passed_checks=10, failed_checks=0, total_checks=10)
        assert r.pass_rate == 1.0
        assert r.all_gates_passed

    def test_pass_rate_partial(self):
        r = BenchmarkReport(passed_checks=8, failed_checks=2, total_checks=12, missing_data=2)
        assert r.pass_rate == 0.8

    def test_summary(self):
        r = BenchmarkReport(total_checks=5, passed_checks=3, failed_checks=1, missing_data=1)
        s = r.summary()
        assert s["total_checks"] == 5
        assert s["pass_rate"] == 0.75

    def test_per_binder_summary(self):
        r = BenchmarkReport(
            validations=[
                MetricValidation("e1", "AAA1", 293.0, "density", 1.0, 1.02, 0.02, 0.02, True),
                MetricValidation("e2", "AAA1", 293.0, "ced", None, 360.0, None, 0.10, None),
                MetricValidation("e3", "AAK1", 293.0, "density", 0.8, 1.01, 0.2, 0.02, False),
            ]
        )
        bs = r.per_binder_summary()
        assert bs["AAA1"]["passed"] == 1
        assert bs["AAA1"]["missing"] == 1
        assert bs["AAK1"]["failed"] == 1

    def test_per_metric_summary(self):
        r = BenchmarkReport(
            validations=[
                MetricValidation("e1", "AAA1", 293.0, "density", 1.0, 1.02, 0.02, 0.02, True),
                MetricValidation("e2", "AAK1", 293.0, "density", 0.8, 1.01, 0.2, 0.02, False),
                MetricValidation("e3", "AAA1", 293.0, "ced", 350.0, 360.0, 0.028, 0.10, True),
            ]
        )
        ms = r.per_metric_summary()
        assert ms["density"]["passed"] == 1
        assert ms["density"]["failed"] == 1
        assert ms["ced"]["passed"] == 1

    def test_format_table(self):
        r = BenchmarkReport(
            total_checks=1,
            passed_checks=1,
            validations=[
                MetricValidation("e1", "AAA1", 293.0, "density", 1.01, 1.02, 0.0098, 0.02, True),
            ],
        )
        table = r.format_table()
        assert "AAA1" in table
        assert "PASS" in table
        assert "density" in table


# ── BenchmarkRunner.validate_single ───────────────────────────────


class TestValidateSingle:
    def test_within_tolerance_passes(self, runner):
        v = runner.validate_single("AAA1", 293.0, "density", 1.019)
        assert v.passed is True
        assert v.relative_error is not None
        assert v.relative_error < 0.02

    def test_outside_tolerance_fails(self, runner):
        v = runner.validate_single("AAA1", 293.0, "density", 0.90)
        assert v.passed is False
        assert v.relative_error is not None
        assert v.relative_error > 0.02

    def test_missing_simulated_value(self, runner):
        v = runner.validate_single("AAA1", 293.0, "density", None)
        assert v.passed is None
        assert v.simulated_value is None

    def test_missing_reference_value(self, runner):
        v = runner.validate_single("AAA1", 999.0, "density", 1.0)
        assert v.passed is None
        assert v.reference_value is None

    def test_ced_within_tolerance(self, runner):
        ref = LITERATURE_REFERENCES["AAA1"]["cohesive_energy_density"]["293.0"]
        v = runner.validate_single("AAA1", 293.0, "cohesive_energy_density", ref * 1.05)
        assert v.passed is True
        assert v.relative_error < 0.10

    def test_ced_outside_tolerance(self, runner):
        ref = LITERATURE_REFERENCES["AAA1"]["cohesive_energy_density"]["293.0"]
        v = runner.validate_single("AAA1", 293.0, "cohesive_energy_density", ref * 1.15)
        assert v.passed is False

    def test_all_binders_have_references(self, runner):
        for binder in ["AAA1", "AAK1", "AAM1"]:
            for temp in [273.0, 293.0, 313.0, 333.0, 373.0]:
                for metric in ["density", "cohesive_energy_density"]:
                    v = runner.validate_single(binder, temp, metric, 1.0)
                    assert v.reference_value is not None, (
                        f"Missing ref for {binder}/{temp}/{metric}"
                    )

    def test_custom_tolerances(self):
        strict = BenchmarkRunner(tolerances={"density": 0.001})
        # ref=1.02, sim=1.05 → rel_err=2.94% >> 0.1%
        v = strict.validate_single("AAA1", 293.0, "density", 1.05)
        assert v.passed is False


# ── BenchmarkRunner.create_batch_job_spec ─────────────────────────


class TestCreateBatchJobSpec:
    def test_single_spec_is_9_runs(self):
        spec = BenchmarkRunner.create_batch_job_spec()
        total = len(spec.binder_types) * len(spec.temperatures_k)
        assert total == 9
        assert spec.temperatures_k == BENCHMARK_TEMPERATURES

    def test_default_multi_seed_specs_are_45_runs(self):
        specs = BenchmarkRunner.create_batch_job_specs()
        total = sum(len(spec.binder_types) * len(spec.temperatures_k) for spec in specs)
        assert len(specs) == len(DEFAULT_BENCHMARK_SEEDS)
        assert total == 45

    def test_custom_binders(self):
        spec = BenchmarkRunner.create_batch_job_spec(binder_types=["AAA1"])
        assert len(spec.binder_types) == 1
        assert spec.binder_types == ["AAA1"]

    def test_spec_tier_is_screening(self):
        spec = BenchmarkRunner.create_batch_job_spec()
        assert spec.tier == "screening"

    def test_spec_seed_propagated(self):
        spec = BenchmarkRunner.create_batch_job_spec(seed=42)
        assert spec.seed == 42


# ── BenchmarkRunner.expected_exp_ids ──────────────────────────────


class TestExpectedExpIds:
    def test_default_45_ids_generated(self):
        ids = BenchmarkRunner.expected_exp_ids()
        assert len(ids) == 45

    def test_ids_are_unique(self):
        ids = BenchmarkRunner.expected_exp_ids()
        assert len(ids) == len(set(ids)), "Duplicate exp_ids generated"

    def test_each_binder_has_15_runs(self):
        """Each binder should produce 15 IDs (3 temps x 5 seeds)."""
        for binder in ["AAA1", "AAK1", "AAM1"]:
            ids = BenchmarkRunner.expected_exp_ids(binder_types=[binder])
            assert len(ids) == 15

    def test_custom_binder_subset(self):
        ids = BenchmarkRunner.expected_exp_ids(binder_types=["AAA1"])
        assert len(ids) == 15

    def test_single_seed_back_compat(self):
        ids = BenchmarkRunner.expected_exp_ids(seed=42)
        assert len(ids) == 9


# ── BenchmarkRunner.validate_results (no DB) ─────────────────────


class TestValidateResultsNoDB:
    def test_requires_repos(self):
        runner = BenchmarkRunner()
        with pytest.raises(RuntimeError, match="experiment_repo"):
            runner.validate_results()


# ── Literature references sanity checks ───────────────────────────


class TestLiteratureReferences:
    def test_all_binders_present(self):
        for b in ["AAA1", "AAK1", "AAM1"]:
            assert b in LITERATURE_REFERENCES

    def test_all_temps_present(self):
        for binder in LITERATURE_REFERENCES:
            for metric in LITERATURE_REFERENCES[binder]:
                temps = LITERATURE_REFERENCES[binder][metric]
                for t in ["273.0", "293.0", "313.0", "333.0", "373.0"]:
                    assert t in temps, f"Missing {t} for {binder}/{metric}"

    def test_density_in_physical_range(self):
        for binder in LITERATURE_REFERENCES:
            for t, v in LITERATURE_REFERENCES[binder]["density"].items():
                assert 0.85 < v < 1.15, f"Unrealistic density {v} for {binder} at {t}K"

    def test_ced_in_physical_range(self):
        for binder in LITERATURE_REFERENCES:
            for t, v in LITERATURE_REFERENCES[binder]["cohesive_energy_density"].items():
                assert 200 < v < 600, f"Unrealistic CED {v} for {binder} at {t}K"

    def test_density_decreases_with_temperature(self):
        for binder in LITERATURE_REFERENCES:
            densities = LITERATURE_REFERENCES[binder]["density"]
            ordered = [densities[str(t)] for t in [273.0, 293.0, 313.0, 333.0, 373.0]]
            for i in range(len(ordered) - 1):
                assert ordered[i] >= ordered[i + 1], f"{binder}: density should decrease with T"


class TestBenchmarkTolerances:
    def test_density_gate(self):
        assert BENCHMARK_TOLERANCES["density"] == 0.02

    def test_ced_gate(self):
        assert BENCHMARK_TOLERANCES["cohesive_energy_density"] == 0.10
