"""
Builder module - Structure generation using Packmol.

This module provides tools for generating molecular structures
for MD simulations, including bulk and layer systems.
"""

from .composition_calculator import CompositionCalculator
from .crystal_builder import Atom, CrystalBuilder, CrystalSlab
from .layer_builder import LayerBuilder, LayerBuildResult

# Layer building
from .layer_spec import (
    BinderLayerSpec,
    CrystalMaterial,
    CrystalSpec,
    LayerSpec,
    LayerType,
    SurfaceOrientation,
    WaterModel,
    WaterSpec,
)
from .molecule_db import MoleculeDB
from .packing_validator import PackingValidator
from .packmol_wrapper import PackmolWrapper
from .topology_generator import TopologyGenerator

__all__ = [
    # Bulk building
    "PackmolWrapper",
    "MoleculeDB",
    "CompositionCalculator",
    "TopologyGenerator",
    "PackingValidator",
    # Layer building
    "LayerSpec",
    "LayerType",
    "CrystalSpec",
    "WaterSpec",
    "BinderLayerSpec",
    "CrystalMaterial",
    "SurfaceOrientation",
    "WaterModel",
    "CrystalBuilder",
    "CrystalSlab",
    "Atom",
    "LayerBuilder",
    "LayerBuildResult",
]
