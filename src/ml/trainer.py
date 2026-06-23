"""
Trainer for ML models.

Handles training, evaluation, and cross-validation.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .data_loader import DataSplit, DataSplitter, TargetVariable
from .models import ModelConfig, PropertyPredictor


@dataclass
class TrainingConfig:
    """Configuration for training."""

    # Model config
    model_config: ModelConfig = field(default_factory=ModelConfig)

    # Training parameters
    normalize_features: bool = True
    normalization_method: str = "standard"

    # Cross-validation
    cv_folds: int = 5
    use_cv: bool = True

    # Early stopping
    early_stopping: bool = True
    early_stopping_rounds: int = 10

    # Output
    output_dir: Path | None = None
    save_model: bool = True
    save_predictions: bool = True

    # Minimum data requirements
    min_samples: int = 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_config": self.model_config.to_dict(),
            "normalize_features": self.normalize_features,
            "normalization_method": self.normalization_method,
            "cv_folds": self.cv_folds,
            "use_cv": self.use_cv,
            "early_stopping": self.early_stopping,
            "early_stopping_rounds": self.early_stopping_rounds,
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "save_model": self.save_model,
            "save_predictions": self.save_predictions,
            "min_samples": self.min_samples,
        }


@dataclass
class TrainingResult:
    """Result of model training."""

    # Metrics
    train_rmse: float = 0.0
    val_rmse: float = 0.0
    test_rmse: float = 0.0
    train_mae: float = 0.0
    val_mae: float = 0.0
    test_mae: float = 0.0
    train_r2: float = 0.0
    val_r2: float = 0.0
    test_r2: float = 0.0

    # Cross-validation results
    cv_rmse_mean: float | None = None
    cv_rmse_std: float | None = None
    cv_scores: list[float] | None = None

    # Feature importance
    feature_importances: dict[str, float] | None = None

    # Metadata
    n_train_samples: int = 0
    n_val_samples: int = 0
    n_test_samples: int = 0
    training_time_seconds: float = 0.0
    timestamp: str = ""
    model_path: str | None = None

    # Predictions (for analysis)
    test_predictions: np.ndarray | None = None
    test_actuals: np.ndarray | None = None
    test_exp_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "train_rmse": self.train_rmse,
            "val_rmse": self.val_rmse,
            "test_rmse": self.test_rmse,
            "train_mae": self.train_mae,
            "val_mae": self.val_mae,
            "test_mae": self.test_mae,
            "train_r2": self.train_r2,
            "val_r2": self.val_r2,
            "test_r2": self.test_r2,
            "cv_rmse_mean": self.cv_rmse_mean,
            "cv_rmse_std": self.cv_rmse_std,
            "cv_scores": self.cv_scores,
            "feature_importances": self.feature_importances,
            "n_train_samples": self.n_train_samples,
            "n_val_samples": self.n_val_samples,
            "n_test_samples": self.n_test_samples,
            "training_time_seconds": self.training_time_seconds,
            "timestamp": self.timestamp,
            "model_path": self.model_path,
        }

    def summary(self) -> str:
        """Get training summary string."""
        lines = [
            "=" * 50,
            "Training Result Summary",
            "=" * 50,
            f"Target: {self.timestamp}",
            f"Samples: Train={self.n_train_samples}, Val={self.n_val_samples}, Test={self.n_test_samples}",
            "",
            "Metrics (RMSE / MAE / R²):",
            f"  Train: {self.train_rmse:.4f} / {self.train_mae:.4f} / {self.train_r2:.4f}",
            f"  Val:   {self.val_rmse:.4f} / {self.val_mae:.4f} / {self.val_r2:.4f}",
            f"  Test:  {self.test_rmse:.4f} / {self.test_mae:.4f} / {self.test_r2:.4f}",
        ]

        if self.cv_rmse_mean is not None:
            lines.append(f"\nCV RMSE: {self.cv_rmse_mean:.4f} ± {self.cv_rmse_std:.4f}")

        if self.feature_importances:
            lines.append("\nTop 5 Feature Importances:")
            sorted_fi = sorted(
                self.feature_importances.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            for name, imp in sorted_fi:
                lines.append(f"  {name}: {imp:.4f}")

        lines.append("=" * 50)
        return "\n".join(lines)


class Trainer:
    """
    Trainer for ML models.

    Handles the complete training pipeline including:
    - Data preprocessing and normalization
    - Model training
    - Cross-validation
    - Evaluation
    - Model saving
    """

    def __init__(self, config: TrainingConfig | None = None):
        """
        Initialize trainer.

        Args:
            config: Training configuration
        """
        self.config = config or TrainingConfig()
        self._normalization_params: dict[str, Any] | None = None

    def train(
        self,
        data_split: DataSplit,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> TrainingResult:
        """
        Train a model on the provided data split.

        Args:
            data_split: Train/val/test data split
            progress_callback: Optional callback for progress updates

        Returns:
            TrainingResult with metrics and model info
        """
        import time

        start_time = time.time()

        train = data_split.train
        val = data_split.val
        test = data_split.test

        # Check minimum samples
        if train.n_samples < self.config.min_samples:
            raise ValueError(
                f"Insufficient training samples: {train.n_samples} < {self.config.min_samples}"
            )

        if progress_callback:
            progress_callback("Preparing data", 0.1)

        # Normalize features if enabled
        X_train, X_val, X_test = train.X, val.X, test.X

        if self.config.normalize_features:
            X_train, self._normalization_params = self._normalize(X_train)
            X_val = self._apply_normalization(X_val)
            X_test = self._apply_normalization(X_test)

        if progress_callback:
            progress_callback("Training model", 0.3)

        # Create and train model
        self.config.model_config.feature_names = train.feature_names
        model = PropertyPredictor(self.config.model_config)

        model.fit(X_train, train.y, X_val, val.y)

        if self._normalization_params:
            model.set_normalization_params(self._normalization_params)

        if progress_callback:
            progress_callback("Evaluating model", 0.6)

        # Evaluate
        train_preds = model.predict(X_train)
        val_preds = model.predict(X_val)
        test_preds = model.predict(X_test)

        train_metrics = self._calculate_metrics(train.y, train_preds)
        val_metrics = self._calculate_metrics(val.y, val_preds)
        test_metrics = self._calculate_metrics(test.y, test_preds)

        # Cross-validation — pass group labels if available from split_info
        cv_results = None
        if self.config.use_cv and train.n_samples >= self.config.cv_folds * 10:
            if progress_callback:
                progress_callback("Running cross-validation", 0.7)
            cv_groups = None
            if data_split.split_info.get("method") == "group":
                # Extract train-split group labels from metadata
                cv_groups = train.metadata.get("cv_groups")
            cv_results = self._cross_validate(X_train, train.y, groups=cv_groups)

        if progress_callback:
            progress_callback("Saving results", 0.9)

        # Save model
        model_path = None
        if self.config.save_model and self.config.output_dir:
            model_path = self.config.output_dir / f"model_{train.target_name}"
            model.save(model_path)

        training_time = time.time() - start_time

        result = TrainingResult(
            train_rmse=train_metrics["rmse"],
            train_mae=train_metrics["mae"],
            train_r2=train_metrics["r2"],
            val_rmse=val_metrics["rmse"],
            val_mae=val_metrics["mae"],
            val_r2=val_metrics["r2"],
            test_rmse=test_metrics["rmse"],
            test_mae=test_metrics["mae"],
            test_r2=test_metrics["r2"],
            cv_rmse_mean=cv_results["mean"] if cv_results else None,
            cv_rmse_std=cv_results["std"] if cv_results else None,
            cv_scores=cv_results["scores"] if cv_results else None,
            feature_importances=model.get_feature_importances(),
            n_train_samples=train.n_samples,
            n_val_samples=val.n_samples,
            n_test_samples=test.n_samples,
            training_time_seconds=training_time,
            timestamp=datetime.now().isoformat(),
            model_path=str(model_path) if model_path else None,
            test_predictions=test_preds,
            test_actuals=test.y,
            test_exp_ids=test.exp_ids,
        )

        # Save result
        if self.config.output_dir:
            result_path = self.config.output_dir / f"result_{train.target_name}.json"
            with open(result_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)

        if progress_callback:
            progress_callback("Complete", 1.0)

        return result

    def _normalize(
        self,
        X: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Normalize features."""
        method = self.config.normalization_method

        if method == "standard":
            mean = np.mean(X, axis=0)
            std = np.std(X, axis=0)
            std[std == 0] = 1
            X_norm = (X - mean) / std
            params = {"method": "standard", "mean": mean.tolist(), "std": std.tolist()}

        elif method == "minmax":
            min_val = np.min(X, axis=0)
            max_val = np.max(X, axis=0)
            range_val = max_val - min_val
            range_val[range_val == 0] = 1
            X_norm = (X - min_val) / range_val
            params = {"method": "minmax", "min": min_val.tolist(), "max": max_val.tolist()}

        else:
            raise ValueError(f"Unknown normalization method: {method}")

        return X_norm, params

    def _apply_normalization(self, X: np.ndarray) -> np.ndarray:
        """Apply saved normalization."""
        if self._normalization_params is None:
            return X

        params = self._normalization_params

        if params["method"] == "standard":
            mean = np.array(params["mean"])
            std = np.array(params["std"])
            return (X - mean) / std

        elif params["method"] == "minmax":
            min_val = np.array(params["min"])
            max_val = np.array(params["max"])
            range_val = max_val - min_val
            range_val[range_val == 0] = 1
            return (X - min_val) / range_val

        return X

    def _calculate_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> dict[str, float]:
        """Calculate evaluation metrics."""
        rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
        mae = float(np.mean(np.abs(y_true - y_pred)))

        # R² score
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {"rmse": rmse, "mae": mae, "r2": r2}

    def _cross_validate(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """Run cross-validation.

        Args:
            X: Feature matrix.
            y: Target values.
            groups: Group labels for GroupKFold (e.g. additive_mol_id).
                    If provided, GroupKFold is used to prevent leakage.
        """
        if groups is not None:
            from sklearn.model_selection import GroupKFold

            n_unique = len(set(groups))
            n_splits = min(self.config.cv_folds, n_unique)
            if n_splits < 2:
                return {"scores": [], "mean": 0.0, "std": 0.0}
            kf = GroupKFold(n_splits=n_splits)
            splits = kf.split(X, y, groups=groups)
        else:
            from sklearn.model_selection import KFold

            kf = KFold(n_splits=self.config.cv_folds, shuffle=True, random_state=42)
            splits = kf.split(X)

        scores = []
        for train_idx, val_idx in splits:
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            model = PropertyPredictor(self.config.model_config)
            model.fit(X_train, y_train)
            preds = model.predict(X_val)

            rmse = float(np.sqrt(np.mean((y_val - preds) ** 2)))
            scores.append(rmse)

        return {
            "scores": scores,
            "mean": float(np.mean(scores)),
            "std": float(np.std(scores)),
        }


def train_ml_v1(
    experiments: list[dict[str, Any]],
    metrics: dict[str, dict[str, float]],
    output_dir: Path | None = None,
    target: TargetVariable = TargetVariable.DENSITY,
) -> TrainingResult:
    """
    Convenience function to train ML v1 model.

    Args:
        experiments: List of experiment dictionaries
        metrics: Dict mapping exp_id to metrics
        output_dir: Output directory for model
        target: Target variable to predict

    Returns:
        TrainingResult
    """
    from .data_loader import DataLoader

    # Load data
    loader = DataLoader()
    dataset = loader.create_ml_v1_dataset(experiments, metrics, target)

    if len(dataset) < 100:
        raise ValueError(f"Insufficient data: {len(dataset)} samples (need 100+)")

    # Split data
    splitter = DataSplitter(train_ratio=0.70, val_ratio=0.15, test_ratio=0.15)
    data_split = splitter.split(dataset)

    # Configure training
    config = TrainingConfig(
        model_config=ModelConfig.for_density()
        if target == TargetVariable.DENSITY
        else ModelConfig.for_ced(),
        normalize_features=True,
        use_cv=True,
        cv_folds=5,
        output_dir=output_dir,
        save_model=output_dir is not None,
    )

    # Train
    trainer = Trainer(config)
    result = trainer.train(data_split)

    return result
