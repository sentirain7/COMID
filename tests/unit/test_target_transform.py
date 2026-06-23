"""Tests for target variable transformations."""

import numpy as np

from ml.target_transform import TargetTransformer


class TestTargetTransformer:
    def setup_method(self) -> None:
        self.tf = TargetTransformer()

    def test_identity_transform_roundtrip(self) -> None:
        y = np.array([0.95, 1.00, 1.05, 1.10])
        y_t, params = self.tf.fit_transform("density", y)
        np.testing.assert_array_almost_equal(y_t, y)
        assert params["type"] == "identity"

        y_back = self.tf.inverse_transform("density", y_t, params)
        np.testing.assert_array_almost_equal(y_back, y)

    def test_log_transform_roundtrip(self) -> None:
        y = np.array([0.5, 1.0, 10.0, 100.0, 500.0])
        y_t, params = self.tf.fit_transform("viscosity", y)
        assert params["type"] == "log"
        assert params["offset"] == 0.0

        y_back = self.tf.inverse_transform("viscosity", y_t, params)
        np.testing.assert_array_almost_equal(y_back, y, decimal=10)

    def test_log_transform_with_offset(self) -> None:
        y = np.array([-1.0, 0.0, 1.0, 10.0])
        y_t, params = self.tf.fit_transform("viscosity", y)
        assert params["type"] == "log"
        assert params["offset"] > 0

        y_back = self.tf.inverse_transform("viscosity", y_t, params)
        np.testing.assert_array_almost_equal(y_back, y, decimal=6)

    def test_msd_uses_log(self) -> None:
        assert self.tf.get_transform_type("msd_diffusion_coefficient") == "log"

    def test_density_uses_identity(self) -> None:
        assert self.tf.get_transform_type("density") == "identity"

    def test_transform_method_matches_fit_transform(self) -> None:
        y_train = np.array([1.0, 10.0, 100.0])
        _, params = self.tf.fit_transform("viscosity", y_train)

        y_test = np.array([5.0, 50.0])
        y_test_t = self.tf.transform("viscosity", y_test, params)
        expected = np.log(y_test)
        np.testing.assert_array_almost_equal(y_test_t, expected)

    def test_rmse_on_original_scale(self) -> None:
        """RMSE should be computed on original scale after inverse transform."""
        y_true = np.array([1.0, 10.0, 100.0, 1000.0])
        y_t, params = self.tf.fit_transform("viscosity", y_true)

        # Simulate predictions in log space with small error
        y_pred_log = y_t + 0.01
        y_pred_orig = self.tf.inverse_transform("viscosity", y_pred_log, params)

        rmse_orig = float(np.sqrt(np.mean((y_true - y_pred_orig) ** 2)))
        assert rmse_orig > 0
        assert rmse_orig < 100  # Reasonable for small log-space perturbation
