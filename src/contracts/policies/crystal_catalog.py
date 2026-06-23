"""
Crystal catalog policy — SSOT for crystal material classification and surface energy proxies.

Used by CrystalFeatureExtractor for ML feature generation.
"""

from __future__ import annotations

from pydantic import BaseModel


class CrystalCatalogPolicy(BaseModel):
    """Crystal material metadata for ML feature extraction (SSOT)."""

    # Material class mapping: chemical formula -> class label
    material_classes: dict[str, str] = {
        "SiO2": "oxide",
        "Al2O3": "oxide",
        "MgO": "oxide",
        "TiO2": "oxide",
        "Fe2O3": "oxide",
        "CaCO3": "carbonate",
        "MgCO3": "carbonate",
        "NaCl": "halide",
        "KCl": "halide",
        "CaF2": "halide",
        "Al": "metal",
        "Fe": "metal",
        "Cu": "metal",
    }

    # Surface energy proxy (dimensionless, relative scale 0-2)
    surface_energy_proxy: dict[str, float] = {
        "SiO2": 1.0,
        "Al2O3": 1.4,
        "MgO": 1.2,
        "TiO2": 1.1,
        "Fe2O3": 1.3,
        "CaCO3": 0.6,
        "MgCO3": 0.7,
        "NaCl": 0.3,
        "KCl": 0.25,
        "CaF2": 0.5,
        "Al": 1.1,
        "Fe": 1.5,
        "Cu": 1.3,
    }

    # One-hot class labels (canonical order)
    class_labels: list[str] = ["oxide", "carbonate", "halide", "metal"]

    def get_material_class(self, material: str) -> str:
        """Get material class, defaulting to 'oxide'."""
        return self.material_classes.get(material, "oxide")

    def get_surface_energy_proxy(self, material: str) -> float:
        """Get surface energy proxy, defaulting to 1.0."""
        return self.surface_energy_proxy.get(material, 1.0)


DEFAULT_CRYSTAL_CATALOG = CrystalCatalogPolicy()
