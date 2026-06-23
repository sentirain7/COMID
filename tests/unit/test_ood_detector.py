"""Tests for OODDetector (Phase 5.2).

Covers inlier/outlier detection, known Mahalanobis values,
and ridge regularization for singular covariance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ml.ood_detector import OODDetector, OODResult


class TestOODDetector:
    def test_inlier_not_ood(self):
        """Points from training distribution are classified as NOT OOD."""
        rng = np.random.RandomState(42)
        X_train = rng.randn(100, 3)

        detector = OODDetector(threshold_percentile=95.0)
        detector.fit(X_train)

        # Test with a point near the center
        X_test = np.array([[0.0, 0.0, 0.0]])
        results = detector.detect(X_test)

        assert len(results) == 1
        assert not results[0].is_ood
        assert results[0].distance >= 0.0
        assert results[0].threshold > 0.0

    def test_outlier_detected(self):
        """Points far from training distribution are classified as OOD."""
        rng = np.random.RandomState(42)
        X_train = rng.randn(100, 3)

        detector = OODDetector(threshold_percentile=95.0)
        detector.fit(X_train)

        # Very far from training data
        X_outlier = np.array([[100.0, 100.0, 100.0]])
        results = detector.detect(X_outlier)

        assert len(results) == 1
        assert results[0].is_ood
        assert results[0].distance > results[0].threshold

    def test_mahalanobis_known_values(self):
        """Verify Mahalanobis distance for identity covariance = Euclidean."""
        # With identity covariance, Mahalanobis = Euclidean from mean
        X_train = np.eye(3) * 10  # just to get non-singular cov
        # Use larger dataset with identity-like covariance
        rng = np.random.RandomState(42)
        X_train = rng.randn(200, 2)

        detector = OODDetector(threshold_percentile=99.0, ridge_lambda=0.0)
        detector.fit(X_train)

        # For a standard normal, the mean ≈ 0 and cov ≈ I
        # Mahalanobis distance of a point at (3, 0) from mean (0, 0) with cov≈I
        # should be approximately 3.0 (Euclidean)
        X_test = np.array([[3.0, 0.0]])
        results = detector.detect(X_test)

        # Should be approximately 3.0 (with some variance due to finite sample)
        assert abs(results[0].distance - 3.0) < 1.0  # generous tolerance

    def test_singular_covariance(self):
        """Ridge regularization prevents failure with singular covariance."""
        # Linearly dependent features → singular covariance
        X_train = np.zeros((50, 3))
        X_train[:, 0] = np.arange(50)
        X_train[:, 1] = np.arange(50) * 2  # linearly dependent
        X_train[:, 2] = np.arange(50) * 3  # linearly dependent

        detector = OODDetector(ridge_lambda=1e-4)
        detector.fit(X_train)  # should not raise

        X_test = np.array([[25.0, 50.0, 75.0]])
        results = detector.detect(X_test)
        assert len(results) == 1
        assert results[0].distance >= 0.0

    def test_save_and_load(self, tmp_path: Path):
        """OODDetector round-trips through save/load."""
        rng = np.random.RandomState(42)
        X_train = rng.randn(50, 3)

        detector = OODDetector(threshold_percentile=90.0)
        detector.fit(X_train)

        # Save
        save_path = tmp_path / "ood.json"
        detector.save(save_path)

        # Load
        loaded = OODDetector.load(save_path)
        assert loaded.is_fitted
        assert loaded._threshold == detector._threshold

        # Predictions should match
        X_test = rng.randn(5, 3)
        orig_results = detector.detect(X_test)
        loaded_results = loaded.detect(X_test)

        for orig, load in zip(orig_results, loaded_results, strict=True):
            assert abs(orig.distance - load.distance) < 1e-10
            assert orig.is_ood == load.is_ood

    def test_batch_detection(self):
        """Multiple samples are processed correctly."""
        rng = np.random.RandomState(42)
        X_train = rng.randn(100, 3)

        detector = OODDetector(threshold_percentile=95.0)
        detector.fit(X_train)

        X_test = rng.randn(10, 3)
        results = detector.detect(X_test)

        assert len(results) == 10
        for r in results:
            assert isinstance(r, OODResult)
            assert r.distance >= 0.0

    def test_single_feature(self):
        """Works with 1D features."""
        rng = np.random.RandomState(42)
        X_train = rng.randn(50, 1)

        detector = OODDetector()
        detector.fit(X_train)

        X_test = np.array([[0.0]])
        results = detector.detect(X_test)
        assert len(results) == 1
        assert not results[0].is_ood
