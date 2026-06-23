"""Per-target feature selection based on cumulative importance.

Selects a subset of features per target by accumulating importance scores
until a threshold is reached (e.g. 95% of total importance), with a minimum
feature count guarantee.

The selected feature masks are stored alongside the model artifact in
``multi_target_meta.json`` — no DB schema changes required.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

_logger = logging.getLogger(__name__)


class PerTargetFeatureSelector:
    """Feature selection via cumulative importance pruning.

    After training, call ``select()`` with the feature importances from
    the trained ensemble.  The resulting index mask can be applied during
    prediction via ``apply_mask()``.
    """

    def __init__(self) -> None:
        self._masks: dict[str, np.ndarray] = {}

    @property
    def masks(self) -> dict[str, np.ndarray]:
        """Target → selected feature index array."""
        return self._masks

    def select(
        self,
        target: str,
        importances: dict[str, float],
        feature_names: list[str],
        min_features: int = 5,
        importance_threshold: float = 0.95,
    ) -> np.ndarray:
        """Select features for a target based on cumulative importance.

        Args:
            target: Target variable name.
            importances: Feature name → importance score mapping.
            feature_names: Ordered list of all feature names (matches X columns).
            min_features: Minimum number of features to keep.
            importance_threshold: Cumulative importance fraction to retain
                (e.g. 0.95 keeps features covering 95% of total importance).

        Returns:
            Sorted array of selected feature indices.
        """
        n_features = len(feature_names)
        imp_values = np.array(
            [importances.get(fname, 0.0) for fname in feature_names],
            dtype=float,
        )

        total = imp_values.sum()
        if total <= 0:
            mask = np.arange(n_features, dtype=int)
            self._masks[target] = mask
            return mask

        # Sort by importance descending
        ranked = np.argsort(imp_values)[::-1]
        cumsum = np.cumsum(imp_values[ranked]) / total

        # Find cutoff: first index where cumsum >= threshold
        cutoff = int(np.searchsorted(cumsum, importance_threshold)) + 1
        cutoff = max(cutoff, min_features)
        cutoff = min(cutoff, n_features)

        selected = np.sort(ranked[:cutoff])
        self._masks[target] = selected

        _logger.info(
            "Feature selection for '%s': %d/%d features (%.1f%% importance)",
            target,
            len(selected),
            n_features,
            float(cumsum[min(cutoff - 1, len(cumsum) - 1)]) * 100,
        )

        return selected

    def apply_mask(self, target: str, X: np.ndarray) -> np.ndarray | None:
        """Apply feature mask to input matrix.

        Args:
            target: Target variable name.
            X: Input feature matrix.

        Returns:
            Subset of columns, or None if no mask is stored for this target.
        """
        mask = self._masks.get(target)
        if mask is None:
            return None
        return X[:, mask]

    def save(self, path: Path) -> None:
        """Save all masks to a JSON file.

        Args:
            path: Output file path.
        """
        data = {target: mask.tolist() for target, mask in self._masks.items()}
        path.write_text(json.dumps(data, indent=2))

    def load(self, path: Path) -> None:
        """Load masks from a JSON file.

        Args:
            path: Input file path.
        """
        data = json.loads(path.read_text())
        self._masks = {target: np.array(indices, dtype=int) for target, indices in data.items()}

    def to_dict(self) -> dict[str, list[int]]:
        """Serialize masks to a dict (for embedding in meta JSON)."""
        return {target: mask.tolist() for target, mask in self._masks.items()}

    @classmethod
    def from_dict(cls, data: dict[str, list[int]]) -> PerTargetFeatureSelector:
        """Create from a serialized dict."""
        selector = cls()
        selector._masks = {target: np.array(indices, dtype=int) for target, indices in data.items()}
        return selector
