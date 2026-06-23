"""
Feature registry — SSOT for ML feature names and versions.

All feature name lists should be imported from here, not defined elsewhere.
"""

from __future__ import annotations

import numpy as np

from common.hashing import compute_content_hash
from contracts.policies.ml_policy import FeatureSetVersion

from .additive_features import ADDITIVE_FEATURE_NAMES
from .molecule_features import MOLECULE_FEATURE_NAMES

# ── V1 feature names (11 total) ───────────────────────────────────────────

COMPOSITION_FEATURES: list[str] = [
    "asphaltene_wt",
    "resin_wt",
    "aromatic_wt",
    "saturate_wt",
    "additive_wt",
    "polar_fraction",
    "nonpolar_fraction",
    "asphaltene_resin_ratio",
]

SIMULATION_FEATURES: list[str] = [
    "temperature_k",
    "pressure_atm",
    "target_atoms",
]

V1_FEATURES: list[str] = COMPOSITION_FEATURES + SIMULATION_FEATURES  # 11
V2_FEATURES: list[str] = V1_FEATURES + ADDITIVE_FEATURE_NAMES  # 24
V3_FEATURES: list[str] = V2_FEATURES + MOLECULE_FEATURE_NAMES  # 40
CONTEXT_FEATURES: list[str] = [
    "material_id_code",
    "binder_type_code",
    "structure_size_code",
    "aging_state_non_aging",
    "aging_state_short_aging",
    "aging_state_long_aging",
    "force_field_name_code",
    "force_field_version_code",
    "tensile_strain_rate_1_per_ps",
    "tensile_pull_velocity_a_per_fs",
    "shear_rate_1_per_ps",
]
V5_FEATURES: list[str] = V3_FEATURES + CONTEXT_FEATURES  # 51
STACK_FEATURES_V6: list[str] = [
    "stack_n_layers",
    "stack_n_crystal_layers",
    "stack_n_binder_layers",
    "stack_n_interface_layers",
    "stack_has_top_crystal",
    "stack_has_bottom_crystal",
    "stack_has_any_interface",
    "stack_terminal_crystal_symmetry",
    "stack_signature_code",
    "layer_0_is_crystal",
    "layer_0_is_binder",
    "layer_0_is_interface",
    "layer_0_gap_after_norm",
    "layer_1_is_crystal",
    "layer_1_is_binder",
    "layer_1_is_interface",
    "layer_1_gap_after_norm",
    "layer_2_is_crystal",
    "layer_2_is_binder",
    "layer_2_is_interface",
    "layer_2_gap_after_norm",
    "layer_3_is_crystal",
    "layer_3_is_binder",
    "layer_3_is_interface",
    "layer_3_gap_after_norm",
    "layer_4_is_crystal",
    "layer_4_is_binder",
    "layer_4_is_interface",
    "layer_4_gap_after_norm",
]

# V4: V3 + crystal(10) + amorphous(3) — imported lazily to avoid circular deps
_V4_FEATURES: list[str] | None = None


def _get_v4_features() -> list[str]:
    """Lazy-load V4 features (crystal + amorphous)."""
    global _V4_FEATURES  # noqa: PLW0603
    if _V4_FEATURES is None:
        from .amorphous_features import AMORPHOUS_FEATURE_NAMES
        from .crystal_features import CRYSTAL_FEATURE_NAMES

        _V4_FEATURES = V3_FEATURES + CRYSTAL_FEATURE_NAMES + AMORPHOUS_FEATURE_NAMES
    return _V4_FEATURES


def _get_v6_features() -> list[str]:
    """Lazy-load V6 features (V5 + layered legacy + stack metadata)."""
    return V5_FEATURES + _get_v4_features()[-13:] + STACK_FEATURES_V6


def _get_v7_features() -> list[str]:
    """Lazy-load V7 features (structural node 30 + system 2 — bulk, MDML parity)."""
    from .structural_features import STRUCTURAL_FEATURE_NAMES

    return list(STRUCTURAL_FEATURE_NAMES)


# ── Registry class ─────────────────────────────────────────────────────────


class FeatureRegistry:
    """Central registry for ML feature sets."""

    @staticmethod
    def get_features(version: FeatureSetVersion) -> list[str]:
        """Get ordered feature names for a given version.

        Args:
            version: Feature set version.

        Returns:
            Ordered list of feature names.
        """
        if version == FeatureSetVersion.V4:
            return list(_get_v4_features())
        if version == FeatureSetVersion.V5:
            return list(V5_FEATURES)
        if version == FeatureSetVersion.V6:
            return list(_get_v6_features())
        if version == FeatureSetVersion.V7:
            return _get_v7_features()
        if version == FeatureSetVersion.V3:
            return list(V3_FEATURES)
        if version == FeatureSetVersion.V2:
            return list(V2_FEATURES)
        return list(V1_FEATURES)

    @staticmethod
    def get_feature_count(version: FeatureSetVersion) -> int:
        """Get feature count for a given version.

        Args:
            version: Feature set version.

        Returns:
            Number of features.
        """
        return len(FeatureRegistry.get_features(version))

    @staticmethod
    def validate_feature_vector(vector: np.ndarray, version: FeatureSetVersion) -> bool:
        """Validate that a feature vector matches the expected dimension.

        Args:
            vector: Feature vector (1D or 2D with last dim = features).
            version: Expected feature set version.

        Returns:
            True if dimension matches.
        """
        return vector.shape[-1] == FeatureRegistry.get_feature_count(version)

    @staticmethod
    def compute_schema_hash(
        version_or_feature_names: FeatureSetVersion | list[str],
    ) -> str:
        """Compute a deterministic schema hash for a feature contract."""
        if isinstance(version_or_feature_names, FeatureSetVersion):
            feature_names = FeatureRegistry.get_features(version_or_feature_names)
        else:
            feature_names = list(version_or_feature_names)
        return compute_content_hash(feature_names)
