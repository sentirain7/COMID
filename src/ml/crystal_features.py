"""
Crystal structure feature extractor for V4 feature set.

Extracts 10 features from crystal structure metadata for layered experiments.
"""

from __future__ import annotations

import logging
from typing import Any

from contracts.policies.crystal_catalog import DEFAULT_CRYSTAL_CATALOG

logger = logging.getLogger(__name__)

# 10 crystal features
CRYSTAL_FEATURE_NAMES: list[str] = [
    "crystal_is_oxide",
    "crystal_is_carbonate",
    "crystal_is_halide",
    "crystal_hydroxyl_density",
    "crystal_thickness_norm",
    "crystal_xy_size_norm",
    "crystal_atom_count_norm",
    "crystal_surface_energy_proxy",
    "crystal_miller_index_sq",
    "crystal_is_high_index",
]

assert len(CRYSTAL_FEATURE_NAMES) == 10  # noqa: S101

# Normalization constants (reasonable ranges for crystal structures)
_THICKNESS_NORM = 50.0  # Angstrom
_XY_SIZE_NORM = 100.0  # Angstrom
_ATOM_COUNT_NORM = 10000.0


class CrystalFeatureExtractor:
    """Extract crystal structure features for layered ML models."""

    def extract(self, crystal_info: dict[str, Any]) -> dict[str, float]:
        """Extract 10 crystal features from crystal info dict.

        Args:
            crystal_info: Dict with keys from CrystalStructureModel fields:
                material, surface, hydroxyl_density, thickness_angstrom,
                xy_size_angstrom, atom_count

        Returns:
            Dict of 10 feature name -> value.
        """
        material = crystal_info.get("material", "SiO2")
        surface = crystal_info.get("surface", "001")
        hydroxyl_density = crystal_info.get("hydroxyl_density", 0.0)
        thickness = crystal_info.get("thickness_angstrom", 25.0)
        xy_size = crystal_info.get("xy_size_angstrom", 50.0)
        atom_count = crystal_info.get("atom_count", 0)

        # Material class one-hot (3 of 4 classes — 'metal' is implicit zero)
        mat_class = DEFAULT_CRYSTAL_CATALOG.get_material_class(material)
        features: dict[str, float] = {
            "crystal_is_oxide": 1.0 if mat_class == "oxide" else 0.0,
            "crystal_is_carbonate": 1.0 if mat_class == "carbonate" else 0.0,
            "crystal_is_halide": 1.0 if mat_class == "halide" else 0.0,
        }

        # Continuous features
        features["crystal_hydroxyl_density"] = float(hydroxyl_density or 0.0)
        features["crystal_thickness_norm"] = float(thickness) / _THICKNESS_NORM
        features["crystal_xy_size_norm"] = float(xy_size) / _XY_SIZE_NORM
        features["crystal_atom_count_norm"] = float(atom_count) / _ATOM_COUNT_NORM

        # Surface energy proxy from policy
        features["crystal_surface_energy_proxy"] = DEFAULT_CRYSTAL_CATALOG.get_surface_energy_proxy(
            material
        )

        # Miller index features
        h, k, el = self._parse_miller(surface)
        miller_sq = float(h * h + k * k + el * el)
        features["crystal_miller_index_sq"] = miller_sq
        features["crystal_is_high_index"] = 1.0 if miller_sq > 2 else 0.0

        return features

    def extract_from_model(self, crystal_model: Any) -> dict[str, float]:
        """Extract features from a CrystalStructureModel ORM instance.

        Args:
            crystal_model: CrystalStructureModel instance.

        Returns:
            Dict of 10 feature name -> value.
        """
        return self.extract(
            {
                "material": crystal_model.material,
                "surface": crystal_model.surface,
                "hydroxyl_density": crystal_model.hydroxyl_density,
                "thickness_angstrom": crystal_model.thickness_angstrom,
                "xy_size_angstrom": crystal_model.xy_size_angstrom,
                "atom_count": crystal_model.atom_count,
            }
        )

    @staticmethod
    def zeros() -> dict[str, float]:
        """Return zero-valued crystal features (for non-crystal experiments)."""
        return dict.fromkeys(CRYSTAL_FEATURE_NAMES, 0.0)

    @staticmethod
    def _parse_miller(surface: str) -> tuple[int, int, int]:
        """Parse Miller index string like '001', '110', '111'.

        Args:
            surface: Miller index string (3 digits).

        Returns:
            (h, k, l) tuple.
        """
        s = str(surface).strip()
        if len(s) >= 3 and s.isdigit():
            return int(s[0]), int(s[1]), int(s[2])
        return 0, 0, 1  # Default (001)
