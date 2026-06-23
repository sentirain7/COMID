"""Target variable transformations for ML training.

Applies log transformation to positive, log-scale targets (viscosity,
diffusion coefficient) to improve model accuracy.  All evaluation metrics
(RMSE, R², MAE) are computed on the **original** scale after inverse
transformation.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

_logger = logging.getLogger(__name__)


# Targets that benefit from log transformation.
# Values must be strictly positive; a small offset is added for safety.
_LOG_TARGETS: set[str] = {
    "viscosity",
    "msd_diffusion_coefficient",
}


class TargetTransformer:
    """Fit/transform/inverse-transform target values.

    Usage::

        tf = TargetTransformer()
        y_transformed, params = tf.fit_transform("viscosity", y_train)
        # ... train model on y_transformed ...
        y_pred_orig = tf.inverse_transform("viscosity", y_pred_transformed, params)
    """

    @staticmethod
    def get_transform_type(target_name: str) -> str:
        """Return the transform type for a target ('log' or 'identity')."""
        return "log" if target_name in _LOG_TARGETS else "identity"

    def fit_transform(self, target_name: str, y: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """Transform target values for training.

        Args:
            target_name: Target variable name.
            y: Raw target values (1-D array).

        Returns:
            (transformed_y, params) where params contains transform metadata
            needed for ``inverse_transform``.
        """
        ttype = self.get_transform_type(target_name)

        if ttype == "log":
            offset = 0.0
            y_min = float(np.min(y)) if len(y) else 1.0
            if y_min <= 0:
                offset = abs(y_min) + 1e-8
                _logger.info(
                    "Log transform for '%s': adding offset %.6g to make values positive",
                    target_name,
                    offset,
                )
            y_transformed = np.log(y + offset)
            params = {"type": "log", "offset": offset}
        else:
            y_transformed = y.copy()
            params = {"type": "identity"}

        return y_transformed, params

    def inverse_transform(
        self, target_name: str, y_pred: np.ndarray, params: dict[str, Any]
    ) -> np.ndarray:
        """Inverse-transform predicted values back to original scale.

        Args:
            target_name: Target variable name.
            y_pred: Predicted values in transformed space.
            params: Parameters from ``fit_transform``.

        Returns:
            Predictions in original scale.
        """
        ttype = params.get("type", "identity")

        if ttype == "log":
            offset = params.get("offset", 0.0)
            return np.exp(y_pred) - offset

        return y_pred.copy()

    def transform(self, target_name: str, y: np.ndarray, params: dict[str, Any]) -> np.ndarray:
        """Transform using previously fitted params (for val/test sets).

        Args:
            target_name: Target variable name.
            y: Raw target values.
            params: Parameters from ``fit_transform``.

        Returns:
            Transformed values.
        """
        ttype = params.get("type", "identity")

        if ttype == "log":
            offset = params.get("offset", 0.0)
            return np.log(y + offset)

        return y.copy()
