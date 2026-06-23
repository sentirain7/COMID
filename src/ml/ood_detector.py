"""Out-of-distribution detector — Mahalanobis distance based.

Phase 5.2: Detects when input features are outside the training
distribution using Mahalanobis distance with ridge-regularized
covariance (numpy only, no scipy).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from contracts.policies.ml_policy import DEFAULT_ML_POLICY

_logger = logging.getLogger(__name__)


@dataclass
class OODResult:
    """Result of OOD detection for a single sample.

    Attributes:
        is_ood: Whether the sample is out-of-distribution.
        distance: Mahalanobis distance from training distribution.
        threshold: Distance threshold for OOD classification.
        percentile: Percentile of distance in training distribution.
    """

    is_ood: bool
    distance: float
    threshold: float
    percentile: float = 0.0


class OODDetector:
    """Mahalanobis distance-based out-of-distribution detector.

    Fits a multivariate Gaussian to training features and detects OOD
    samples as those with Mahalanobis distance exceeding a threshold.

    Uses ridge regularization (cov + lambda * I) to handle near-singular
    covariance matrices.

    Args:
        threshold_percentile: Percentile of training distances used as
            OOD threshold (default: from policy).
        ridge_lambda: Regularization parameter for covariance inversion.
    """

    def __init__(
        self,
        threshold_percentile: float | None = None,
        ridge_lambda: float = 1e-6,
    ) -> None:
        self.threshold_percentile = (
            threshold_percentile or DEFAULT_ML_POLICY.ood_threshold_percentile
        )
        self.ridge_lambda = ridge_lambda
        self._mean: np.ndarray | None = None
        self._cov_inv: np.ndarray | None = None
        self._threshold: float = 0.0
        self._is_fitted: bool = False
        self._training_distances: np.ndarray | None = None
        self.metadata: dict[str, object] = {}

    @property
    def is_fitted(self) -> bool:
        """Whether the detector is fitted."""
        return self._is_fitted

    def fit(self, X_train: np.ndarray) -> OODDetector:
        """Fit detector on training features.

        Computes mean vector, ridge-regularized covariance inverse,
        and threshold from training distance percentile.

        Args:
            X_train: Training feature matrix (n_samples x n_features).

        Returns:
            Self for method chaining.
        """
        if X_train.ndim == 1:
            X_train = X_train.reshape(-1, 1)

        n_samples, n_features = X_train.shape

        self._mean = np.mean(X_train, axis=0)

        # Covariance with ridge regularization
        cov = np.cov(X_train, rowvar=False)
        if cov.ndim == 0:
            # Single feature: scalar covariance
            cov = np.array([[float(cov)]])
        cov_reg = cov + self.ridge_lambda * np.eye(n_features)

        self._cov_inv = np.linalg.inv(cov_reg)

        # Compute training distances for threshold
        self._training_distances = self._compute_distances(X_train)

        # Threshold: percentile of training distances
        self._threshold = float(np.percentile(self._training_distances, self.threshold_percentile))

        self._is_fitted = True
        _logger.info(
            f"OODDetector fitted: {n_samples} samples, {n_features} features, "
            f"threshold={self._threshold:.4f} ({self.threshold_percentile}th percentile)"
        )
        return self

    def _compute_distances(self, X: np.ndarray) -> np.ndarray:
        """Compute Mahalanobis distances for all rows.

        Args:
            X: Feature matrix (n_samples x n_features).

        Returns:
            Array of Mahalanobis distances.
        """
        if self._mean is None or self._cov_inv is None:
            raise RuntimeError("Detector is not fitted. Call fit() first.")

        diff = X - self._mean  # (n_samples, n_features)
        # d(x) = sqrt((x - mu)^T @ Sigma^{-1} @ (x - mu))
        left = diff @ self._cov_inv  # (n_samples, n_features)
        distances = np.sqrt(np.sum(left * diff, axis=1))
        return distances

    def detect(self, X: np.ndarray) -> list[OODResult]:
        """Detect OOD samples.

        Args:
            X: Feature matrix (n_samples x n_features).

        Returns:
            List of OODResult, one per sample.
        """
        if not self._is_fitted:
            raise RuntimeError("Detector is not fitted. Call fit() first.")

        if X.ndim == 1:
            X = X.reshape(1, -1)

        distances = self._compute_distances(X)
        results = []

        for dist in distances:
            # Compute approximate percentile in training distribution
            if self._training_distances is not None:
                pct = float(np.mean(self._training_distances <= dist) * 100.0)
            else:
                pct = 0.0

            results.append(
                OODResult(
                    is_ood=float(dist) > self._threshold,
                    distance=float(dist),
                    threshold=self._threshold,
                    percentile=pct,
                )
            )

        return results

    def save(self, filepath: Path | str) -> None:
        """Save detector state to JSON.

        Args:
            filepath: Path to save file.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "threshold_percentile": self.threshold_percentile,
            "ridge_lambda": self.ridge_lambda,
            "threshold": self._threshold,
            "is_fitted": self._is_fitted,
            "metadata": self.metadata,
        }

        if self._mean is not None:
            data["mean"] = self._mean.tolist()
        if self._cov_inv is not None:
            data["cov_inv"] = self._cov_inv.tolist()
        if self._training_distances is not None:
            data["training_distances"] = self._training_distances.tolist()

        filepath.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, filepath: Path | str) -> OODDetector:
        """Load detector from JSON.

        Args:
            filepath: Path to saved file.

        Returns:
            Loaded OODDetector.
        """
        filepath = Path(filepath)
        data = json.loads(filepath.read_text())

        detector = cls(
            threshold_percentile=data["threshold_percentile"],
            ridge_lambda=data["ridge_lambda"],
        )
        detector._threshold = data["threshold"]
        detector._is_fitted = data["is_fitted"]
        detector.metadata = dict(data.get("metadata") or {})

        if "mean" in data:
            detector._mean = np.array(data["mean"])
        if "cov_inv" in data:
            detector._cov_inv = np.array(data["cov_inv"])
        if "training_distances" in data:
            detector._training_distances = np.array(data["training_distances"])

        return detector
