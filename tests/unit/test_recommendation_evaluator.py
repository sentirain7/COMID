"""Unit tests for recommendation-quality evaluation metrics."""

import numpy as np

from ml.recommendation_evaluator import RecommendationEvalInput, RecommendationEvaluator


def test_recommendation_evaluator_computes_summary_metrics():
    evaluator = RecommendationEvaluator(top_k=2, feasibility_rel_error=0.1)

    metrics = evaluator.evaluate(
        {
            "density": RecommendationEvalInput(
                y_true=np.array([1.0, 1.1, 1.2]),
                y_pred=np.array([1.02, 1.08, 1.19]),
                uncertainties=np.array([0.03, 0.03, 0.03]),
                ood_flags=np.array([False, True, False]),
            ),
            "viscosity": RecommendationEvalInput(
                y_true=np.array([5.0, 4.0, 3.0]),
                y_pred=np.array([4.8, 4.1, 3.1]),
                uncertainties=np.array([0.2, 0.2, 0.2]),
                ood_flags=np.array([True, False, False]),
                direction="minimize",
            ),
        }
    )

    assert 0.0 <= metrics["feasibility_rate"] <= 1.0
    assert 0.0 <= metrics["top_k_hit_rate"] <= 1.0
    assert 0.0 <= metrics["calibration_ece"] <= 1.0
    assert 0.0 <= metrics["ood_precision"] <= 1.0


def test_not_degraded_requires_non_worse_metrics():
    evaluator = RecommendationEvaluator(degradation_tolerance=0.01)

    champion = {
        "feasibility_rate": 0.80,
        "top_k_hit_rate": 0.70,
        "calibration_ece": 0.08,
        "ood_precision": 0.60,
    }
    challenger = {
        "feasibility_rate": 0.81,
        "top_k_hit_rate": 0.70,
        "calibration_ece": 0.07,
        "ood_precision": 0.61,
    }
    degraded = {
        "feasibility_rate": 0.70,
        "top_k_hit_rate": 0.60,
        "calibration_ece": 0.12,
        "ood_precision": 0.40,
    }

    assert evaluator.not_degraded(challenger, champion) is True
    assert evaluator.not_degraded(degraded, champion) is False
