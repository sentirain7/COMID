"""
Amorphous cell feature extractor for V4 feature set.

Extracts 3 features from amorphous cell metadata for layered experiments.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 3 amorphous features
AMORPHOUS_FEATURE_NAMES: list[str] = [
    "amorphous_present",
    "amorphous_density",
    "amorphous_atom_count_norm",
]

assert len(AMORPHOUS_FEATURE_NAMES) == 3  # noqa: S101

_ATOM_COUNT_NORM = 10000.0


class AmorphousFeatureExtractor:
    """Extract amorphous cell features for layered ML models."""

    def extract(self, amorphous_info: dict[str, Any] | None) -> dict[str, float]:
        """Extract 3 amorphous features.

        Args:
            amorphous_info: Dict with keys from AmorphousCellModel fields:
                density, atom_count. None if no amorphous cell.

        Returns:
            Dict of 3 feature name -> value.
        """
        if amorphous_info is None:
            return self.zeros()

        density = amorphous_info.get("density") or 0.0
        atom_count = amorphous_info.get("atom_count") or 0

        return {
            "amorphous_present": 1.0,
            "amorphous_density": float(density),
            "amorphous_atom_count_norm": float(atom_count) / _ATOM_COUNT_NORM,
        }

    def extract_from_model(self, amorphous_model: Any) -> dict[str, float]:
        """Extract features from an AmorphousCellModel ORM instance.

        Args:
            amorphous_model: AmorphousCellModel instance.

        Returns:
            Dict of 3 feature name -> value.
        """
        if amorphous_model is None:
            return self.zeros()
        return self.extract(
            {
                "density": amorphous_model.density,
                "atom_count": amorphous_model.atom_count,
            }
        )

    @staticmethod
    def zeros() -> dict[str, float]:
        """Return zero-valued amorphous features (no amorphous cell)."""
        return dict.fromkeys(AMORPHOUS_FEATURE_NAMES, 0.0)
