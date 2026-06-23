"""Unit tests for TierPromoter automatic tier promotion."""

from unittest.mock import MagicMock

import pytest

from orchestrator.tier_promoter import TierPromoter


@pytest.fixture
def mock_zscore_service():
    """Create a mock ZScoreService."""
    return MagicMock()


@pytest.fixture
def mock_experiment_repo():
    """Create a mock ExperimentRepository."""
    repo = MagicMock()
    repo.get_by_id.return_value = None  # no duplicates by default
    return repo


@pytest.fixture
def mock_job_manager():
    """Create a mock CeleryJobManager."""
    jm = MagicMock()
    jm.submit.return_value = "job_001"
    return jm


@pytest.fixture
def tier_promoter(mock_zscore_service, mock_experiment_repo, mock_job_manager):
    """Create a TierPromoter with mocked deps."""
    return TierPromoter(
        zscore_service=mock_zscore_service,
        experiment_repo=mock_experiment_repo,
        job_manager=mock_job_manager,
    )


class TestMaybePromote:
    """Tests for TierPromoter.maybe_promote()."""

    def test_submits_promoted_job(self, tier_promoter, mock_zscore_service, mock_job_manager):
        """When promotion is warranted, a job is submitted via job_manager.submit()."""
        mock_zscore_service.check_tier_promotion.return_value = "confirm"

        result = tier_promoter.maybe_promote(
            exp_id="exp_001",
            current_tier="screening",
            material_id="AAA1_X1_non_aging",
            temperature_k=298.0,
            composition={"U-SA-Squalane-0293": 4},
            seed=1,
        )

        assert result is not None
        mock_job_manager.submit.assert_called_once()
        call_kwargs = mock_job_manager.submit.call_args[1]
        assert "build_request" in call_kwargs
        assert "protocol_request" in call_kwargs
        assert "material_id" in call_kwargs
        assert "exp_id" in call_kwargs

    def test_returns_none_when_no_promotion(self, tier_promoter, mock_zscore_service):
        """Returns None when promotion is not warranted."""
        mock_zscore_service.check_tier_promotion.return_value = None

        result = tier_promoter.maybe_promote(
            exp_id="exp_001",
            current_tier="screening",
            material_id="AAA1_X1_non_aging",
            temperature_k=298.0,
            composition={"asphaltene": 20.0},
            seed=1,
        )

        assert result is None

    def test_skips_duplicate(
        self, tier_promoter, mock_zscore_service, mock_experiment_repo, mock_job_manager
    ):
        """Skips submission when promoted experiment already exists."""
        mock_zscore_service.check_tier_promotion.return_value = "confirm"
        existing = MagicMock()
        existing.status = "completed"
        mock_experiment_repo.get_by_id.return_value = existing

        result = tier_promoter.maybe_promote(
            exp_id="exp_001",
            current_tier="screening",
            material_id="AAA1_X1_non_aging",
            temperature_k=298.0,
            composition={"asphaltene": 20.0},
            seed=1,
        )

        assert result is None
        mock_job_manager.submit.assert_not_called()

    def test_submit_kwargs_include_material_id(
        self, tier_promoter, mock_zscore_service, mock_job_manager
    ):
        """submit() receives material_id and exp_id as keyword arguments."""
        mock_zscore_service.check_tier_promotion.return_value = "viscosity"

        tier_promoter.maybe_promote(
            exp_id="exp_001",
            current_tier="confirm",
            material_id="AAA1_X1_non_aging",
            temperature_k=298.0,
            composition={"asphaltene": 20.0},
            seed=1,
        )

        mock_job_manager.submit.assert_called_once()
        call_kwargs = mock_job_manager.submit.call_args[1]
        assert call_kwargs["material_id"] == "AAA1_X1_non_aging"
        assert call_kwargs["exp_id"] is not None

    def test_submit_without_job_manager_raises(self, mock_zscore_service, mock_experiment_repo):
        """maybe_promote() raises RuntimeError if job_manager is not provided."""
        promoter = TierPromoter(
            zscore_service=mock_zscore_service,
            experiment_repo=mock_experiment_repo,
        )
        mock_zscore_service.check_tier_promotion.return_value = "confirm"

        with pytest.raises(RuntimeError, match="requires a job_manager"):
            promoter.maybe_promote(
                exp_id="exp_001",
                current_tier="screening",
                material_id="AAA1_X1_non_aging",
                temperature_k=298.0,
                composition={"asphaltene": 20.0},
                seed=1,
            )
