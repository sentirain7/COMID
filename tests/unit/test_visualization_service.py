"""Tests for ML diagnostics visualization service."""

from unittest.mock import MagicMock, patch

import numpy as np

from api.schemas.ml_visualization import (
    FeatureImportanceResponse,
    LearningCurveResponse,
    StructuralEvalResponse,
    StructuralTrainResponse,
)


class _FakeEnsemble:
    is_fitted = True

    def __init__(self, n_features: int = 5) -> None:
        self._n_features = n_features
        self.predictors = [self._FakeMember(n_features)]

    class _FakeMember:
        def __init__(self, n_features: int) -> None:
            self._n = n_features
            self.config = MagicMock()
            self.config.feature_names = [f"f{i}" for i in range(n_features)]

        def get_feature_importances(self) -> dict[str, float]:
            return {f"f{i}": 1.0 / self._n for i in range(self._n)}

    def predict(self, X: np.ndarray, return_std: bool = False):
        mean = np.ones(X.shape[0]) * 1.0
        std = np.ones(X.shape[0]) * 0.1
        if return_std:
            return mean, std
        return mean


class _FakePredictor:
    fitted_targets = ["density"]

    def __init__(self) -> None:
        self._ensembles = {"density": _FakeEnsemble()}
        self._feature_masks: dict = {}
        self._target_transforms: dict = {}
        self._uncertainty_estimators: dict = {}
        self._ood_detector = None

    def predict_batch(self, X, targets=None):
        from ml.multi_target import MultiTargetResult

        results = []
        for i in range(X.shape[0]):
            r = MultiTargetResult()
            r.predictions = {"density": 1.0 + i * 0.01}
            r.uncertainties = {"density": 0.05}
            results.append(r)
        return results


class _FakeModelVersion:
    version_id = "mt_20260315_120000"
    model_artifact_path = "/tmp/fake_artifact"
    training_data_snapshot_path = "/tmp/fake_snapshot.json"
    feature_set_version = "v1"
    status = "champion"
    training_samples = 100
    train_metrics_json = {"density": {"rmse": 0.01}}
    val_metrics_json = {"density": {"rmse": 0.02}}
    test_metrics_json = {"density": {"rmse": 0.03}}
    promoted_at = None


class TestGetFeatureImportance:
    @patch("features.mlops.visualization_service._load_champion_and_snapshot")
    def test_returns_ranked_features(self, mock_load) -> None:
        from features.mlops.visualization_service import get_feature_importance

        predictor = _FakePredictor()
        mock_load.return_value = (_FakeModelVersion(), {}, predictor)

        result = get_feature_importance(MagicMock(), "density", top_k=3)
        assert isinstance(result, FeatureImportanceResponse)
        assert result.target == "density"
        assert len(result.features) <= 3
        assert result.features[0].rank == 1


class TestGetLearningCurve:
    @patch("database.repositories.model_version_repo.ModelVersionRepository")
    def test_returns_points(self, mock_repo_cls) -> None:
        from features.mlops.visualization_service import get_learning_curve

        mock_repo = MagicMock()
        v1 = MagicMock()
        v1.training_samples = 50
        v1.version_id = "mt_v1"
        v1.train_metrics_json = {"density": {"rmse": 0.05}}
        v1.val_metrics_json = {"density": {"rmse": 0.06}}
        v1.test_metrics_json = {"density": {"rmse": 0.07}}
        v2 = MagicMock()
        v2.training_samples = 100
        v2.version_id = "mt_v2"
        v2.train_metrics_json = {"density": {"rmse": 0.03}}
        v2.val_metrics_json = {"density": {"rmse": 0.04}}
        v2.test_metrics_json = {"density": {"rmse": 0.05}}
        mock_repo.get_history.return_value = [v2, v1]
        mock_repo_cls.return_value = mock_repo

        result = get_learning_curve(MagicMock(), "density")
        assert isinstance(result, LearningCurveResponse)
        assert len(result.points) == 2
        assert result.points[0].training_samples == 50
        assert result.points[1].training_samples == 100


class TestRunStructuralEval:
    """A2: on-demand V7 평가 래퍼가 challenger 결과를 응답으로 매핑."""

    @patch("ml.structural_challenger.evaluate_v7_random_repeats")
    def test_maps_models_and_winner(self, mock_eval) -> None:
        from features.mlops.visualization_service import run_structural_eval

        mock_eval.return_value = {
            "target": "density",
            "n_samples": 165,
            "n_repeats": 3,
            "transform": "identity",
            "models": {
                "xgboost": {"rmse_mean": 0.02, "rmse_std": 0.003, "per_repeat": [0.02, 0.018, 0.022]},
                "random_forest": {"rmse_mean": 0.03, "rmse_std": 0.004, "per_repeat": [0.03, 0.028, 0.032]},
            },
            "winner": "xgboost",
        }
        out = run_structural_eval(MagicMock(), target="density", n_repeats=3)
        assert isinstance(out, StructuralEvalResponse)
        assert out.winner == "xgboost"
        assert out.n_samples == 165
        assert set(out.models) == {"xgboost", "random_forest"}
        assert out.models["xgboost"].rmse_mean == 0.02
        assert len(out.models["xgboost"].per_repeat) == 3

    @patch("ml.structural_challenger.evaluate_v7_random_repeats")
    def test_error_path_is_graceful(self, mock_eval) -> None:
        from features.mlops.visualization_service import run_structural_eval

        mock_eval.return_value = {"error": "insufficient internal V7 data for 'density'"}
        out = run_structural_eval(MagicMock(), target="density")
        assert isinstance(out, StructuralEvalResponse)
        assert out.error and "insufficient" in out.error
        assert out.models == {}
        assert out.winner is None


class TestRunStructuralTrain:
    """A2: on-demand V7 학습 래퍼가 ChallengerOutcome을 응답으로 매핑."""

    @patch("ml.structural_challenger.train_structural_challenger")
    def test_maps_outcome_including_model_types(self, mock_train) -> None:
        from features.mlops.visualization_service import run_structural_train
        from ml.structural_challenger import ChallengerOutcome

        mock_train.return_value = ChallengerOutcome(
            version_id=None,
            targets_trained=["density"],
            training_samples=132,
            holdout_samples=33,
            promoted=False,
            per_target_holdout_rmse={"density": 0.019},
            model_types={"density": "xgboost"},
            notes=["register=False (dry-run)"],
        )
        out = run_structural_train(MagicMock(), targets=["density"], register=False)
        assert isinstance(out, StructuralTrainResponse)
        assert out.targets_trained == ["density"]
        assert out.model_types == {"density": "xgboost"}
        assert out.per_target_holdout_rmse["density"] == 0.019
        assert out.promoted is False
        # register 기본 False 경로가 train_structural_challenger에 전달됐는지
        _, kwargs = mock_train.call_args
        assert kwargs["register"] is False
