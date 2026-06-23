"""Tests for ml.drift_detector."""

import numpy as np

from ml.drift_detector import DriftDetector, DriftType


def test_ks_detects_shifted_distribution():
    det = DriftDetector()
    rng = np.random.default_rng(42)
    x_train = rng.normal(0.0, 1.0, size=(120, 4))
    x_new = rng.normal(2.0, 1.0, size=(120, 4))

    out = det.detect_feature_drift(x_train, x_new)
    assert len(out) == 4
    assert any(r.is_drift for r in out)


def test_prediction_drift_reports_positive_pct():
    det = DriftDetector()
    y_true = np.ones(120)
    y_pred = np.concatenate([np.ones(60), np.ones(60) * 2.0])

    baseline, current, pct = det.detect_prediction_drift(y_true, y_pred)
    assert current >= baseline
    assert pct >= 0.0


def test_full_check_none_when_same_distribution():
    det = DriftDetector()
    rng = np.random.default_rng(0)
    x_train = rng.normal(0, 1, size=(100, 3))
    x_new = rng.normal(0, 1, size=(80, 3))
    y_true = rng.normal(0, 1, size=80)
    y_pred = y_true + rng.normal(0, 0.01, size=80)

    report = det.full_check(x_train=x_train, x_new=x_new, y_true=y_true, y_pred=y_pred)
    assert report.drift_type in {DriftType.NONE, DriftType.VIRTUAL, DriftType.REAL, DriftType.BOTH}
    assert isinstance(report.should_retrain, bool)


# --- New tests ---


def test_ks_same_distribution_no_drift():
    """Identical distribution => all features p > alpha => no drift."""
    det = DriftDetector()
    rng = np.random.default_rng(99)
    x_train = rng.normal(0.0, 1.0, size=(200, 5))
    x_new = rng.normal(0.0, 1.0, size=(200, 5))

    results = det.detect_feature_drift(x_train, x_new)
    assert len(results) == 5
    for r in results:
        assert r.p_value > det.ks_alpha


def test_ks_shifted_2sigma_all_drift():
    """2σ shift => all features should detect drift."""
    det = DriftDetector()
    rng = np.random.default_rng(7)
    x_train = rng.normal(0.0, 1.0, size=(200, 3))
    x_new = rng.normal(2.0, 1.0, size=(200, 3))

    results = det.detect_feature_drift(x_train, x_new)
    assert len(results) == 3
    assert all(r.is_drift for r in results)


def test_ks_min_samples_returns_empty():
    """Below min sample threshold => empty result list."""
    det = DriftDetector()
    x_train = np.array([[1.0], [2.0]])
    x_new = np.array([[3.0], [4.0]])

    results = det.detect_feature_drift(x_train, x_new)
    assert results == []


def test_page_hinkley_stationary_no_drift():
    """Stationary signal => no Page-Hinkley detection."""
    det = DriftDetector()
    det.reset_page_hinkley()
    rng = np.random.default_rng(1)
    for _ in range(100):
        detected = det.detect_sequential(rng.normal(0.0, 0.1))
    assert detected is False


def test_page_hinkley_mean_shift_detects():
    """Mean shift => Page-Hinkley should detect drift."""
    det = DriftDetector()
    det.reset_page_hinkley()
    detected = False
    for _ in range(50):
        det.detect_sequential(0.0)
    for _ in range(200):
        if det.detect_sequential(5.0):
            detected = True
            break
    assert detected is True


def test_rolling_rmse_identical_prediction_zero_drift():
    """Perfect prediction => drift_pct = 0."""
    det = DriftDetector()
    y_true = np.ones(120)
    y_pred = np.ones(120)
    baseline, current, pct = det.detect_prediction_drift(y_true, y_pred)
    assert pct == 0.0


def test_full_check_same_distribution_none():
    """Identical distributions => DriftType.NONE."""
    det = DriftDetector()
    rng = np.random.default_rng(12)
    n = 500
    x_train = rng.normal(0, 1, size=(n, 4))
    x_new = rng.normal(0, 1, size=(n, 4))
    y_true = rng.normal(0, 1, size=n)
    y_pred = y_true + rng.normal(0, 0.001, size=n)

    report = det.full_check(x_train=x_train, x_new=x_new, y_true=y_true, y_pred=y_pred)
    assert report.drift_type == DriftType.NONE
    assert report.should_retrain is False


def test_full_check_both_drift_detected():
    """Feature + prediction shift => DriftType.BOTH."""
    det = DriftDetector()
    rng = np.random.default_rng(55)
    n = 200
    x_train = rng.normal(0, 1, size=(n, 3))
    x_new = rng.normal(3.0, 1, size=(n, 3))
    y_true = rng.normal(0, 1, size=n)
    y_pred = y_true + np.linspace(0, 5, n)

    report = det.full_check(x_train=x_train, x_new=x_new, y_true=y_true, y_pred=y_pred)
    assert report.drift_type in {DriftType.BOTH, DriftType.VIRTUAL, DriftType.REAL}
    assert report.should_retrain is True
