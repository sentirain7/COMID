"""Unit tests for Pipeline tier promotion wiring."""

from unittest.mock import MagicMock, patch

from orchestrator.pipeline import Pipeline


def _make_pipeline(metric_repository, job_manager):
    return Pipeline(
        builder=MagicMock(),
        protocol=MagicMock(),
        calculator=MagicMock(),
        repository=MagicMock(),
        metric_repository=metric_repository,
        job_manager=job_manager,
    )


def test_check_tier_promotion_passes_job_manager_to_promoter():
    """TierPromoter should receive injected job_manager from Pipeline."""
    mock_metric_repo = MagicMock()
    mock_job_manager = MagicMock()
    pipeline = _make_pipeline(metric_repository=mock_metric_repo, job_manager=mock_job_manager)

    mock_promoter = MagicMock()
    mock_promoter.maybe_promote.return_value = None

    with (
        patch("orchestrator.zscore_service.ZScoreService") as zscore_cls,
        patch(
            "orchestrator.tier_promoter.TierPromoter", return_value=mock_promoter
        ) as promoter_cls,
    ):
        pipeline._check_tier_promotion(
            exp_id="exp_001",
            current_tier="screening",
            material_id="AAA1_X1_non_aging",
            temperature_k=293.0,
            composition={"asphaltene": 20.0},
            seed=1,
        )

    promoter_cls.assert_called_once_with(
        zscore_service=zscore_cls.return_value,
        experiment_repo=pipeline.repository,
        job_manager=mock_job_manager,
    )
    mock_promoter.maybe_promote.assert_called_once()


def test_check_tier_promotion_skips_without_metric_repository():
    """Promotion check should no-op when metric repository is absent."""
    pipeline = _make_pipeline(metric_repository=None, job_manager=MagicMock())

    with patch("orchestrator.tier_promoter.TierPromoter") as promoter_cls:
        pipeline._check_tier_promotion(
            exp_id="exp_001",
            current_tier="screening",
            material_id="AAA1_X1_non_aging",
            temperature_k=293.0,
            composition={"asphaltene": 20.0},
            seed=1,
        )

    promoter_cls.assert_not_called()
