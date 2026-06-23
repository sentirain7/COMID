"""Unit tests for ZScoreService and tier promotion checks."""

from unittest.mock import MagicMock

import pytest

from orchestrator.zscore_service import ZSCORE_METRICS, ZScoreResult, ZScoreService

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_metric_repo():
    """Create a mock MetricRepository."""
    repo = MagicMock()
    return repo


@pytest.fixture
def mock_experiment_repo():
    """Create a mock ExperimentRepository."""
    repo = MagicMock()
    return repo


@pytest.fixture
def zscore_service(mock_metric_repo, mock_experiment_repo):
    """Create a ZScoreService with mocked repos."""
    return ZScoreService(
        metric_repo=mock_metric_repo,
        experiment_repo=mock_experiment_repo,
        min_population=5,
    )


# ── calculate_zscores tests ─────────────────────────────────────────


class TestCalculateZscores:
    """Tests for ZScoreService.calculate_zscores()."""

    def test_normal_zscore_calculation(self, zscore_service, mock_metric_repo):
        """Z-score is correctly calculated when population is sufficient."""
        # density metric: value=1.02, avg=1.00, stddev=0.02 → zscore=1.0
        density_metric = MagicMock()
        density_metric.value = 1.02

        ced_metric = MagicMock()
        ced_metric.value = 350.0

        def get_by_name_side_effect(exp_id, metric_name, **kwargs):
            if metric_name == "density":
                return density_metric
            if metric_name == "cohesive_energy_density":
                return ced_metric
            return None

        mock_metric_repo.get_by_name.side_effect = get_by_name_side_effect

        def get_statistics_side_effect(metric_name, **kwargs):
            if metric_name == "density":
                return {"count": 10, "avg": 1.00, "stddev": 0.02, "min": 0.96, "max": 1.04}
            if metric_name == "cohesive_energy_density":
                return {"count": 10, "avg": 340.0, "stddev": 20.0, "min": 300.0, "max": 380.0}
            return {"count": 0, "avg": 0, "stddev": 0, "min": 0, "max": 0}

        mock_metric_repo.get_statistics.side_effect = get_statistics_side_effect

        result = zscore_service.calculate_zscores("exp_001", "screening", 298.0)

        assert isinstance(result, ZScoreResult)
        assert result.exp_id == "exp_001"
        assert abs(result.zscores["density"] - 1.0) < 1e-6
        assert abs(result.zscores["cohesive_energy_density"] - 0.5) < 1e-6
        assert len(result.skipped) == 0

    def test_skip_when_population_too_small(self, zscore_service, mock_metric_repo):
        """Metrics are skipped when population < min_population."""
        density_metric = MagicMock()
        density_metric.value = 1.02
        mock_metric_repo.get_by_name.return_value = density_metric
        mock_metric_repo.get_statistics.return_value = {
            "count": 3,
            "avg": 1.00,
            "stddev": 0.02,
            "min": 0.98,
            "max": 1.02,
        }

        result = zscore_service.calculate_zscores("exp_001", "screening", 298.0)

        assert "density" in result.skipped
        assert "cohesive_energy_density" in result.skipped
        assert len(result.zscores) == 0

    def test_skip_when_metric_not_found(self, zscore_service, mock_metric_repo):
        """Metrics are skipped when the experiment has no such metric."""
        mock_metric_repo.get_by_name.return_value = None

        result = zscore_service.calculate_zscores("exp_001", "screening", 298.0)

        assert len(result.skipped) == len(ZSCORE_METRICS)
        assert len(result.zscores) == 0

    def test_zero_stddev_returns_zero_zscore(self, zscore_service, mock_metric_repo):
        """Zero stddev produces zero z-score (no division by zero)."""
        metric = MagicMock()
        metric.value = 1.00
        mock_metric_repo.get_by_name.return_value = metric
        mock_metric_repo.get_statistics.return_value = {
            "count": 10,
            "avg": 1.00,
            "stddev": 0.0,
            "min": 1.00,
            "max": 1.00,
        }

        result = zscore_service.calculate_zscores("exp_001", "screening", 298.0)

        for metric_name in ZSCORE_METRICS:
            if metric_name in result.zscores:
                assert result.zscores[metric_name] == 0.0

    def test_passes_tier_and_temperature_filters(self, zscore_service, mock_metric_repo):
        """Verify tier and temperature are passed to get_statistics."""
        metric = MagicMock()
        metric.value = 1.00
        mock_metric_repo.get_by_name.return_value = metric
        mock_metric_repo.get_statistics.return_value = {
            "count": 10,
            "avg": 1.00,
            "stddev": 0.02,
            "min": 0.96,
            "max": 1.04,
        }

        zscore_service.calculate_zscores("exp_001", "confirm", 313.0)

        # Check that get_statistics was called with correct filters
        for call in mock_metric_repo.get_statistics.call_args_list:
            assert call.kwargs.get("run_tier") == "confirm"
            assert call.kwargs.get("temperature_k") == 313.0


# ── check_tier_promotion tests ──────────────────────────────────────


class TestCheckTierPromotion:
    """Tests for ZScoreService.check_tier_promotion()."""

    def test_screening_to_confirm_on_high_zscore(self, zscore_service, mock_metric_repo):
        """Screening promotes to confirm when density z-score > 2.0."""
        density_metric = MagicMock()
        density_metric.value = 1.10  # high outlier

        def get_by_name_side_effect(exp_id, metric_name, **kwargs):
            if metric_name == "density":
                return density_metric
            return None

        mock_metric_repo.get_by_name.side_effect = get_by_name_side_effect
        mock_metric_repo.get_statistics.return_value = {
            "count": 10,
            "avg": 1.00,
            "stddev": 0.02,
            "min": 0.96,
            "max": 1.04,
        }

        next_tier = zscore_service.check_tier_promotion("exp_001", "screening", 298.0)

        assert next_tier == "confirm"

    def test_no_promotion_when_zscore_normal(self, zscore_service, mock_metric_repo):
        """No promotion when z-scores are within normal range."""
        density_metric = MagicMock()
        density_metric.value = 1.01  # normal

        def get_by_name_side_effect(exp_id, metric_name, **kwargs):
            if metric_name == "density":
                return density_metric
            return None

        mock_metric_repo.get_by_name.side_effect = get_by_name_side_effect
        mock_metric_repo.get_statistics.return_value = {
            "count": 10,
            "avg": 1.00,
            "stddev": 0.02,
            "min": 0.96,
            "max": 1.04,
        }

        next_tier = zscore_service.check_tier_promotion("exp_001", "screening", 298.0)

        assert next_tier is None

    def test_promotion_with_candidate_flag(self, zscore_service, mock_metric_repo):
        """Screening promotes to confirm when candidate_for_recommendation flag is set."""
        mock_metric_repo.get_by_name.return_value = None  # no metrics needed for flag-based

        next_tier = zscore_service.check_tier_promotion(
            "exp_001",
            "screening",
            298.0,
            flags={"candidate_for_recommendation": True},
        )

        assert next_tier == "confirm"

    def test_confirm_to_viscosity_with_flag(self, zscore_service, mock_metric_repo):
        """Confirm promotes to viscosity when candidate_selected flag is set."""
        mock_metric_repo.get_by_name.return_value = None

        next_tier = zscore_service.check_tier_promotion(
            "exp_001",
            "confirm",
            298.0,
            flags={"candidate_selected_for_recommendation": True},
        )

        assert next_tier == "viscosity"

    def test_no_promotion_when_population_insufficient(self, zscore_service, mock_metric_repo):
        """No promotion when population is too small for z-score."""
        density_metric = MagicMock()
        density_metric.value = 1.10

        def get_by_name_side_effect(exp_id, metric_name, **kwargs):
            if metric_name == "density":
                return density_metric
            return None

        mock_metric_repo.get_by_name.side_effect = get_by_name_side_effect
        mock_metric_repo.get_statistics.return_value = {
            "count": 2,
            "avg": 1.00,
            "stddev": 0.02,
            "min": 0.98,
            "max": 1.02,
        }

        # No flags, and population too small for z-score → no promotion
        next_tier = zscore_service.check_tier_promotion("exp_001", "screening", 298.0)

        assert next_tier is None
