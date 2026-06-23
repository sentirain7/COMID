"""Tests for TgPostProcessor — cross-experiment Tg calculation pipeline integration.

Covers:
- Density-temperature point gathering from mock repos
- Tg computation with sufficient / insufficient temperature data
- Metric save with metadata in array_summary
- Material ID matching logic
"""

from __future__ import annotations

from common.pathing import exp_id_to_material_id, generate_exp_id
from contracts.schemas import ExperimentRecord, ExperimentStatus, FFType, MetricResult, RunTier
from metrics.tg import TgCalculator
from orchestrator.tg_post_processor import TgPostProcessor

# ======================================================================
# Mock repositories for TgPostProcessor tests
# ======================================================================


class MockMetricRepoForTg:
    """Minimal mock metric repository with density look-up and save."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[MetricResult]] = {}
        self.saved: list[MetricResult] = []

    def add_metric(self, exp_id: str, metric: MetricResult) -> None:
        """Seed a metric for testing."""
        self._metrics.setdefault(exp_id, []).append(metric)

    # IMetricRepository interface
    def save(self, metric: MetricResult) -> None:
        self.saved.append(metric)

    def save_batch(self, metrics: list[MetricResult]) -> int:
        self.saved.extend(metrics)
        return len(metrics)

    def get_by_exp(self, exp_id: str) -> list[MetricResult]:
        return self._metrics.get(exp_id, [])

    def get_by_name(
        self,
        exp_id: str,
        metric_name: str,
        namespace: str | None = None,
    ) -> MetricResult | None:
        for m in self._metrics.get(exp_id, []):
            if m.metric_name == metric_name:
                if namespace is None or m.namespace == namespace:
                    return m
        return None


class MockExperimentRepoForTg:
    """Minimal mock experiment repository with find_by_tier."""

    def __init__(self) -> None:
        self.experiments: dict[str, ExperimentRecord] = {}

    def add_experiment(self, record: ExperimentRecord) -> None:
        self.experiments[record.exp_id] = record

    # IExperimentRepository interface
    def save(self, record: ExperimentRecord) -> str:
        self.experiments[record.exp_id] = record
        return record.exp_id

    def get(self, exp_id: str) -> ExperimentRecord | None:
        return self.experiments.get(exp_id)

    def update_status(self, exp_id: str, status: str) -> None:
        pass

    def find_by_tier(self, tier: str) -> list[ExperimentRecord]:
        return [
            e
            for e in self.experiments.values()
            if (e.run_tier.value if hasattr(e.run_tier, "value") else e.run_tier) == tier
        ]


# ======================================================================
# Helpers
# ======================================================================


def _make_exp_id(temperature_k: float, seed: int = 42) -> str:
    """Generate an exp_id for AAA1_X1_non_aging at given temperature."""
    return generate_exp_id(
        binder_type="AAA1",
        structure_size="X1",
        temperature_k=temperature_k,
        ff_type="bulk_ff_gaff2",
        aging_state="non_aging",
        atom_count=100000,
        seed=seed,
    )


def _make_experiment_record(
    temperature_k: float,
    seed: int = 42,
    material_id: str = "AAA1_X1_non_aging",
) -> ExperimentRecord:
    """Create a completed ExperimentRecord at given temperature."""
    exp_id = _make_exp_id(temperature_k, seed)
    return ExperimentRecord(
        exp_id=exp_id,
        material_id=material_id,
        force_field_type=FFType.BULK_FF_GAFF2,
        force_field_name="GAFF2",
        force_field_version="1.0",
        study_type="bulk",
        run_tier=RunTier.SCREENING,
        temperature_k=temperature_k,
        pressure_atm=1.0,
        target_atoms=100000,
        status=ExperimentStatus.COMPLETED,
        metrics=[],
    )


def _bilinear_density(
    temperature_k: float,
    tg: float = 300.0,
    slope_glassy: float = -3e-4,
    slope_rubbery: float = -6e-4,
    rho_at_tg: float = 1.05,
) -> float:
    """Compute bilinear density at a given temperature."""
    if temperature_k <= tg:
        return slope_glassy * (temperature_k - tg) + rho_at_tg
    return slope_rubbery * (temperature_k - tg) + rho_at_tg


def _seed_multi_temp_experiments(
    metric_repo: MockMetricRepoForTg,
    experiment_repo: MockExperimentRepoForTg,
    temperatures: list[float],
    tg: float = 300.0,
    material_id: str = "AAA1_X1_non_aging",
) -> list[str]:
    """Create experiments at multiple temperatures with bilinear density data."""
    exp_ids = []
    for temp in temperatures:
        record = _make_experiment_record(temp, material_id=material_id)
        experiment_repo.add_experiment(record)

        density = _bilinear_density(temp, tg=tg)
        metric_repo.add_metric(
            record.exp_id,
            MetricResult(
                exp_id=record.exp_id,
                metric_name="density",
                value=density,
                unit="g/cm3",
                namespace="bulk_ff_gaff2",
            ),
        )
        exp_ids.append(record.exp_id)
    return exp_ids


# ======================================================================
# TestGatherDensityPoints
# ======================================================================


class TestGatherDensityPoints:
    """Test _gather_density_points correctly collects (T, ρ) data."""

    def test_collects_all_matching_experiments(self):
        """Should gather density from all experiments with matching material_id."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        temperatures = [273.0, 293.0, 313.0, 333.0, 373.0]
        _seed_multi_temp_experiments(metric_repo, experiment_repo, temperatures)

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
        )
        points = processor._gather_density_points("AAA1_X1_non_aging", "screening")

        assert len(points) == 5
        collected_temps = sorted(p.temperature_k for p in points)
        assert collected_temps == sorted(temperatures)

    def test_filters_by_material_id(self):
        """Should not include experiments from a different material."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()

        # AAA1 experiments
        _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            [273.0, 293.0, 313.0],
            material_id="AAA1_X1_non_aging",
        )

        # AAK1 experiment (different material)
        record = ExperimentRecord(
            exp_id=generate_exp_id(
                binder_type="AAK1",
                structure_size="X1",
                temperature_k=273.0,
                ff_type="bulk_ff_gaff2",
                aging_state="non_aging",
                atom_count=100000,
                seed=42,
            ),
            material_id="AAK1_X1_non_aging",
            force_field_type=FFType.BULK_FF_GAFF2,
            force_field_name="GAFF2",
            force_field_version="1.0",
            study_type="bulk",
            run_tier=RunTier.SCREENING,
            temperature_k=273.0,
            pressure_atm=1.0,
            target_atoms=100000,
            status=ExperimentStatus.COMPLETED,
            metrics=[],
        )
        experiment_repo.add_experiment(record)
        metric_repo.add_metric(
            record.exp_id,
            MetricResult(
                exp_id=record.exp_id,
                metric_name="density",
                value=1.05,
                unit="g/cm3",
                namespace="bulk_ff_gaff2",
            ),
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
        )
        points = processor._gather_density_points("AAA1_X1_non_aging", "screening")

        # Should only have the 3 AAA1 experiments
        assert len(points) == 3

    def test_skips_experiments_without_density(self):
        """Experiments without density metric should be skipped."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()

        # 3 experiments with density
        _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            [273.0, 293.0, 313.0],
        )

        # 1 experiment without density metric
        record = _make_experiment_record(333.0, seed=99)
        experiment_repo.add_experiment(record)
        # Intentionally don't add density metric

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
        )
        points = processor._gather_density_points("AAA1_X1_non_aging", "screening")

        assert len(points) == 3


# ======================================================================
# TestTryComputeTg
# ======================================================================


class TestTryComputeTg:
    """Test try_compute_tg with sufficient data."""

    def test_computes_tg_with_five_temperatures(self):
        """5-temperature scan should yield a Tg result."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        true_tg = 300.0
        temperatures = [253.0, 273.0, 293.0, 333.0, 373.0]
        exp_ids = _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            temperatures,
            tg=true_tg,
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
            tg_calculator=TgCalculator(bootstrap_n=0),
            min_temperatures=4,
        )
        result = processor.try_compute_tg(
            exp_id=exp_ids[0],
            material_id="AAA1_X1_non_aging",
            run_tier="screening",
        )

        assert result is not None
        assert result.tg_k is not None
        assert abs(result.tg_k - true_tg) < 15.0

    def test_saves_metric_to_repo(self):
        """Successful Tg should be saved via metric_repo.save()."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        temperatures = [253.0, 273.0, 293.0, 333.0, 373.0]
        exp_ids = _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            temperatures,
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
            tg_calculator=TgCalculator(bootstrap_n=0),
            min_temperatures=4,
        )
        processor.try_compute_tg(
            exp_id=exp_ids[0],
            material_id="AAA1_X1_non_aging",
            run_tier="screening",
        )

        # Check that a Tg metric was saved
        assert len(metric_repo.saved) == 1
        saved = metric_repo.saved[0]
        assert saved.metric_name == "glass_transition_temperature_k"
        assert saved.unit == "K"
        assert saved.namespace == "bulk_ff_gaff2"
        assert saved.exp_id == exp_ids[0]


# ======================================================================
# TestTryComputeTgInsufficient
# ======================================================================


class TestTryComputeTgInsufficient:
    """Test try_compute_tg with insufficient data."""

    def test_returns_none_with_three_temperatures(self):
        """3 temperatures < min_temperatures=4 → should return None."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        temperatures = [273.0, 293.0, 313.0]
        exp_ids = _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            temperatures,
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
            tg_calculator=TgCalculator(bootstrap_n=0),
            min_temperatures=4,
        )
        result = processor.try_compute_tg(
            exp_id=exp_ids[0],
            material_id="AAA1_X1_non_aging",
            run_tier="screening",
        )

        assert result is None

    def test_no_metric_saved_when_insufficient(self):
        """No metric should be saved when data is insufficient."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        temperatures = [273.0, 293.0, 313.0]
        exp_ids = _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            temperatures,
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
            min_temperatures=4,
        )
        processor.try_compute_tg(
            exp_id=exp_ids[0],
            material_id="AAA1_X1_non_aging",
            run_tier="screening",
        )

        assert len(metric_repo.saved) == 0


# ======================================================================
# TestSaveTgMetric
# ======================================================================


class TestSaveTgMetric:
    """Test _save_tg_metric metadata inclusion."""

    def test_array_summary_contains_metadata(self):
        """Saved metric's array_summary should contain Tg metadata."""
        metric_repo = MockMetricRepoForTg()
        experiment_repo = MockExperimentRepoForTg()
        temperatures = [253.0, 273.0, 293.0, 333.0, 373.0]
        exp_ids = _seed_multi_temp_experiments(
            metric_repo,
            experiment_repo,
            temperatures,
        )

        processor = TgPostProcessor(
            metric_repo=metric_repo,
            experiment_repo=experiment_repo,
            tg_calculator=TgCalculator(bootstrap_n=0),
            min_temperatures=4,
        )
        processor.try_compute_tg(
            exp_id=exp_ids[0],
            material_id="AAA1_X1_non_aging",
            run_tier="screening",
        )

        assert len(metric_repo.saved) == 1
        saved = metric_repo.saved[0]
        assert saved.array_summary is not None
        assert saved.array_summary["tg_parse_status"] == "success"
        assert saved.array_summary["tg_method"] == "bilinear_breakpoint"
        assert "tg_k" in saved.array_summary
        assert "tg_n_temperatures" in saved.array_summary


# ======================================================================
# TestMaterialIdMatching
# ======================================================================


class TestMaterialIdMatching:
    """Test exp_id_to_material_id matching in TgPostProcessor."""

    def test_matching_material_id_extracted(self):
        """exp_id_to_material_id should correctly round-trip."""
        exp_id = _make_exp_id(298.0)
        material_id = exp_id_to_material_id(exp_id)
        assert material_id == "AAA1_X1_non_aging"

    def test_different_temperatures_same_material(self):
        """Experiments at different temperatures but same material should match."""
        exp_id_1 = _make_exp_id(273.0)
        exp_id_2 = _make_exp_id(373.0)

        mat_1 = exp_id_to_material_id(exp_id_1)
        mat_2 = exp_id_to_material_id(exp_id_2)

        assert mat_1 == mat_2 == "AAA1_X1_non_aging"

    def test_different_materials_do_not_match(self):
        """Experiments on different binder types should not match."""
        exp_id_aaa1 = generate_exp_id(
            binder_type="AAA1",
            structure_size="X1",
            temperature_k=298.0,
            ff_type="bulk_ff_gaff2",
            aging_state="non_aging",
            atom_count=100000,
            seed=42,
        )
        exp_id_aak1 = generate_exp_id(
            binder_type="AAK1",
            structure_size="X1",
            temperature_k=298.0,
            ff_type="bulk_ff_gaff2",
            aging_state="non_aging",
            atom_count=100000,
            seed=42,
        )

        mat_aaa1 = exp_id_to_material_id(exp_id_aaa1)
        mat_aak1 = exp_id_to_material_id(exp_id_aak1)

        assert mat_aaa1 != mat_aak1
