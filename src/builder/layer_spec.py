"""Layer specification adapter — backward compatibility re-exports.

Data definitions live in contracts/schemas.py (SSOT).
This module re-exports for existing import paths.
"""

from contracts.schemas import (
    AgingState,
    BinderLayerConfig,
    CrystalCellMode,
    CrystalLayerSpec,
    CrystalMaterial,
    LayerScenario,
    LayerSpec,
    LayerType,
    SurfaceOrientation,
    WaterLayerSpec,
    WaterModel,
)

# Backward-compat aliases for existing import paths
CrystalSpec = CrystalLayerSpec
WaterSpec = WaterLayerSpec
BinderLayerSpec = BinderLayerConfig

__all__ = [
    "AgingState",
    "BinderLayerConfig",
    "BinderLayerSpec",
    "CrystalCellMode",
    "CrystalLayerSpec",
    "CrystalMaterial",
    "CrystalSpec",
    "LayerScenario",
    "LayerSpec",
    "LayerType",
    "SurfaceOrientation",
    "WaterLayerSpec",
    "WaterModel",
    "WaterSpec",
]
