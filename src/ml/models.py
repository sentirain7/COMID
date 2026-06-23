"""
ML Models for property prediction.

Implements XGBoost and LightGBM models for ML v1.
"""

import json
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np


class ModelType(Enum):
    """Type of ML model."""

    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    RANDOM_FOREST = "random_forest"
    LINEAR = "linear"


@dataclass
class ModelConfig:
    """Configuration for ML models."""

    model_type: ModelType = ModelType.XGBOOST
    target_name: str = "density"

    # Common parameters
    n_estimators: int = 100
    max_depth: int = 6
    learning_rate: float = 0.1
    random_state: int = 42

    # XGBoost specific
    xgb_objective: str = "reg:squarederror"
    xgb_eval_metric: str = "rmse"
    xgb_early_stopping_rounds: int = 10
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8

    # LightGBM specific
    lgb_objective: str = "regression"
    lgb_metric: str = "rmse"
    lgb_num_leaves: int = 31
    lgb_min_child_samples: int = 20

    # Feature names
    feature_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_type": self.model_type.value,
            "target_name": self.target_name,
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "random_state": self.random_state,
            "xgb_objective": self.xgb_objective,
            "xgb_eval_metric": self.xgb_eval_metric,
            "xgb_early_stopping_rounds": self.xgb_early_stopping_rounds,
            "xgb_subsample": self.xgb_subsample,
            "xgb_colsample_bytree": self.xgb_colsample_bytree,
            "lgb_objective": self.lgb_objective,
            "lgb_metric": self.lgb_metric,
            "lgb_num_leaves": self.lgb_num_leaves,
            "lgb_min_child_samples": self.lgb_min_child_samples,
            "feature_names": self.feature_names,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        """Create from dictionary."""
        data = data.copy()
        if "model_type" in data:
            data["model_type"] = ModelType(data["model_type"])
        return cls(**data)

    @classmethod
    def for_density(cls) -> "ModelConfig":
        """Create config optimized for density prediction."""
        return cls(
            model_type=ModelType.XGBOOST,
            target_name="density",
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
        )

    @classmethod
    def for_ced(cls) -> "ModelConfig":
        """Create config optimized for CED prediction."""
        return cls(
            model_type=ModelType.XGBOOST,
            target_name="cohesive_energy_density",
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
        )


class PropertyPredictor:
    """
    Property predictor using ensemble models.

    Wraps XGBoost or LightGBM for property prediction.
    """

    def __init__(self, config: ModelConfig | None = None):
        """
        Initialize predictor.

        Args:
            config: Model configuration
        """
        self.config = config or ModelConfig()
        self._model: Any = None
        self._is_fitted = False
        self._feature_importances: np.ndarray | None = None
        self._normalization_params: dict[str, Any] | None = None

    @property
    def is_fitted(self) -> bool:
        """Check if model is fitted."""
        return self._is_fitted

    def _create_model(self) -> Any:
        """Create the underlying model based on config."""
        if self.config.model_type == ModelType.XGBOOST:
            return self._create_xgboost()
        elif self.config.model_type == ModelType.LIGHTGBM:
            return self._create_lightgbm()
        elif self.config.model_type == ModelType.RANDOM_FOREST:
            return self._create_random_forest()
        elif self.config.model_type == ModelType.LINEAR:
            return self._create_linear()
        else:
            raise ValueError(f"Unknown model type: {self.config.model_type}")

    def _create_xgboost(self) -> Any:
        """Create XGBoost model."""
        try:
            import xgboost as xgb

            return xgb.XGBRegressor(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                objective=self.config.xgb_objective,
                subsample=self.config.xgb_subsample,
                colsample_bytree=self.config.xgb_colsample_bytree,
                random_state=self.config.random_state,
                n_jobs=-1,
            )
        except ImportError as e:
            raise ImportError("XGBoost not installed. Install with: pip install xgboost") from e

    def _create_lightgbm(self) -> Any:
        """Create LightGBM model."""
        try:
            import lightgbm as lgb

            return lgb.LGBMRegressor(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                objective=self.config.lgb_objective,
                num_leaves=self.config.lgb_num_leaves,
                min_child_samples=self.config.lgb_min_child_samples,
                random_state=self.config.random_state,
                n_jobs=-1,
                verbose=-1,
            )
        except ImportError as e:
            raise ImportError("LightGBM not installed. Install with: pip install lightgbm") from e

    def _create_random_forest(self) -> Any:
        """Create Random Forest model."""
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            random_state=self.config.random_state,
            n_jobs=-1,
        )

    def _create_linear(self) -> Any:
        """Create Linear Regression model."""
        from sklearn.linear_model import Ridge

        return Ridge(alpha=1.0, random_state=self.config.random_state)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> "PropertyPredictor":
        """
        Fit the model.

        Args:
            X: Training features
            y: Training targets
            X_val: Validation features (optional)
            y_val: Validation targets (optional)

        Returns:
            Self for method chaining
        """
        self._model = self._create_model()

        if self.config.model_type == ModelType.XGBOOST and X_val is not None:
            self._model.fit(
                X,
                y,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )
        elif self.config.model_type == ModelType.LIGHTGBM and X_val is not None:
            self._model.fit(
                X,
                y,
                eval_set=[(X_val, y_val)],
            )
        else:
            self._model.fit(X, y)

        self._is_fitted = True

        # Extract feature importances
        if hasattr(self._model, "feature_importances_"):
            self._feature_importances = self._model.feature_importances_

        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make predictions.

        Args:
            X: Features to predict

        Returns:
            Predicted values
        """
        if not self._is_fitted:
            raise RuntimeError("Model is not fitted. Call fit() first.")

        return self._model.predict(X)

    def get_feature_importances(self) -> dict[str, float] | None:
        """Get feature importances."""
        if self._feature_importances is None:
            return None

        if not self.config.feature_names:
            return {f"feature_{i}": float(imp) for i, imp in enumerate(self._feature_importances)}

        return {
            name: float(imp)
            for name, imp in zip(self.config.feature_names, self._feature_importances, strict=False)
        }

    def save(self, filepath: Path) -> None:
        """
        Save model to disk.

        Args:
            filepath: Path to save model
        """
        if not self._is_fitted:
            raise RuntimeError("Model is not fitted. Call fit() first.")

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save model
        model_path = filepath.with_suffix(".pkl")
        with open(model_path, "wb") as f:
            pickle.dump(self._model, f)

        # Save config
        config_path = filepath.with_suffix(".json")
        config_data = {
            "config": self.config.to_dict(),
            "is_fitted": self._is_fitted,
            "feature_importances": (
                self._feature_importances.tolist()
                if self._feature_importances is not None
                else None
            ),
            "normalization_params": self._normalization_params,
        }
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

    @classmethod
    def load(cls, filepath: Path) -> "PropertyPredictor":
        """
        Load model from disk.

        Args:
            filepath: Path to load model from

        Returns:
            Loaded PropertyPredictor
        """
        filepath = Path(filepath)

        # Load config
        config_path = filepath.with_suffix(".json")
        with open(config_path) as f:
            config_data = json.load(f)

        config = ModelConfig.from_dict(config_data["config"])
        predictor = cls(config)

        # Load model
        model_path = filepath.with_suffix(".pkl")
        with open(model_path, "rb") as f:
            predictor._model = pickle.load(f)

        predictor._is_fitted = config_data["is_fitted"]

        if config_data.get("feature_importances"):
            predictor._feature_importances = np.array(config_data["feature_importances"])

        predictor._normalization_params = config_data.get("normalization_params")

        return predictor

    def set_normalization_params(self, params: dict[str, Any]) -> None:
        """Set normalization parameters for inference."""
        self._normalization_params = params

    def get_normalization_params(self) -> dict[str, Any] | None:
        """Get normalization parameters."""
        return self._normalization_params


class EnsemblePredictor:
    """
    Ensemble of multiple predictors.

    Combines predictions from multiple models for robustness.
    """

    def __init__(self, predictors: list[PropertyPredictor] | None = None):
        """
        Initialize ensemble.

        Args:
            predictors: List of predictors
        """
        self.predictors = predictors or []

    def add_predictor(self, predictor: PropertyPredictor) -> None:
        """Add a predictor to the ensemble."""
        self.predictors.append(predictor)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> "EnsemblePredictor":
        """Fit all predictors."""
        for predictor in self.predictors:
            predictor.fit(X, y, X_val, y_val)
        return self

    def predict(
        self,
        X: np.ndarray,
        return_std: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
        """
        Make ensemble predictions.

        Args:
            X: Features
            return_std: Return standard deviation of predictions

        Returns:
            Predictions (and optionally std)
        """
        predictions = np.array([p.predict(X) for p in self.predictors])
        mean_pred = np.mean(predictions, axis=0)

        if return_std:
            std_pred = np.std(predictions, axis=0)
            return mean_pred, std_pred

        return mean_pred

    @property
    def is_fitted(self) -> bool:
        """Check if all predictors are fitted."""
        return all(p.is_fitted for p in self.predictors)

    def save(self, dirpath: Path) -> None:
        """Save ensemble to directory (one file per sub-predictor + metadata).

        Args:
            dirpath: Directory to save ensemble to.
        """
        if not self.is_fitted:
            raise RuntimeError("Ensemble is not fitted. Call fit() first.")

        dirpath = Path(dirpath)
        dirpath.mkdir(parents=True, exist_ok=True)

        meta = {
            "n_predictors": len(self.predictors),
            "model_configs": [],
        }
        for i, predictor in enumerate(self.predictors):
            predictor.save(dirpath / f"predictor_{i}.json")
            meta["model_configs"].append(predictor.config.to_dict())

        (dirpath / "ensemble_meta.json").write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, dirpath: Path) -> "EnsemblePredictor":
        """Load ensemble from directory.

        Args:
            dirpath: Directory containing saved ensemble.

        Returns:
            Loaded EnsemblePredictor.
        """
        dirpath = Path(dirpath)
        meta = json.loads((dirpath / "ensemble_meta.json").read_text())

        predictors = []
        for i in range(meta["n_predictors"]):
            predictors.append(PropertyPredictor.load(dirpath / f"predictor_{i}.json"))

        return cls(predictors=predictors)
