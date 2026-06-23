"""
Feature Store for ML training data.

Manages features extracted from experiments for ML model training.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS


class FeatureType(Enum):
    """Type of feature."""

    COMPOSITION = "composition"
    MOLECULAR = "molecular"
    THERMODYNAMIC = "thermodynamic"
    STRUCTURAL = "structural"
    SIMULATION = "simulation"


@dataclass
class Feature:
    """A single feature entry."""

    feature_id: int | None = None
    exp_id: str = ""
    feature_type: FeatureType = FeatureType.COMPOSITION
    feature_name: str = ""
    feature_value: float | None = None
    feature_vector: list[float] | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feature_id": self.feature_id,
            "exp_id": self.exp_id,
            "feature_type": self.feature_type.value,
            "feature_name": self.feature_name,
            "feature_value": self.feature_value,
            "feature_vector": self.feature_vector,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Feature":
        """Create from dictionary."""
        return cls(
            feature_id=data.get("feature_id"),
            exp_id=data.get("exp_id", ""),
            feature_type=FeatureType(data.get("feature_type", "composition")),
            feature_name=data.get("feature_name", ""),
            feature_value=data.get("feature_value"),
            feature_vector=data.get("feature_vector"),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else None,
        )


@dataclass
class CompositionFeatures:
    """Features extracted from composition."""

    asphaltene_wt: float = 0.0
    resin_wt: float = 0.0
    aromatic_wt: float = 0.0
    saturate_wt: float = 0.0
    additive_wt: float = 0.0

    # Derived features
    polar_fraction: float = 0.0  # asphaltene + resin
    nonpolar_fraction: float = 0.0  # aromatic + saturate
    asphaltene_resin_ratio: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Convert to feature vector."""
        return np.array(
            [
                self.asphaltene_wt,
                self.resin_wt,
                self.aromatic_wt,
                self.saturate_wt,
                self.additive_wt,
                self.polar_fraction,
                self.nonpolar_fraction,
                self.asphaltene_resin_ratio,
            ]
        )

    @classmethod
    def from_composition(
        cls,
        asphaltene: float,
        resin: float,
        aromatic: float,
        saturate: float,
        additive: float = 0.0,
    ) -> "CompositionFeatures":
        """Create from raw composition values."""
        polar = asphaltene + resin
        nonpolar = aromatic + saturate
        ar_ratio = asphaltene / resin if resin > 0 else 0.0

        return cls(
            asphaltene_wt=asphaltene,
            resin_wt=resin,
            aromatic_wt=aromatic,
            saturate_wt=saturate,
            additive_wt=additive,
            polar_fraction=polar,
            nonpolar_fraction=nonpolar,
            asphaltene_resin_ratio=ar_ratio,
        )


@dataclass
class CompositionFeaturesV2(CompositionFeatures):
    """V2 composition features (V1 8 + additive 13 = 21 composition-only features)."""

    # Additive one-hot: subcategory
    additive_is_polymer: float = 0.0
    additive_is_surfactant: float = 0.0
    additive_is_nanoparticle: float = 0.0

    # Additive one-hot: functional tag
    additive_func_anti_aging: float = 0.0
    additive_func_anti_stripping: float = 0.0
    additive_func_modifier: float = 0.0

    # Additive molecular descriptors
    additive_mw: float = 0.0
    additive_logp: float = 0.0
    additive_hbd: float = 0.0
    additive_hba: float = 0.0

    # Interaction features
    additive_wt_x_asphaltene_wt: float = 0.0
    additive_wt_x_polar_fraction: float = 0.0
    additive_mw_x_additive_wt: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Convert to feature vector (21 elements: V1 8 + additive 13)."""
        v1 = super().to_vector()  # 8 elements
        v2_extra = np.array(
            [
                self.additive_is_polymer,
                self.additive_is_surfactant,
                self.additive_is_nanoparticle,
                self.additive_func_anti_aging,
                self.additive_func_anti_stripping,
                self.additive_func_modifier,
                self.additive_mw,
                self.additive_logp,
                self.additive_hbd,
                self.additive_hba,
                self.additive_wt_x_asphaltene_wt,
                self.additive_wt_x_polar_fraction,
                self.additive_mw_x_additive_wt,
            ]
        )
        return np.concatenate([v1, v2_extra])  # 21 elements


@dataclass
class MolecularDescriptors:
    """Molecular descriptors for ML features."""

    avg_molecular_weight: float = 0.0
    avg_num_atoms: float = 0.0
    total_molecules: int = 0
    weighted_avg_mw: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Convert to feature vector."""
        return np.array(
            [
                self.avg_molecular_weight,
                self.avg_num_atoms,
                self.total_molecules,
                self.weighted_avg_mw,
            ]
        )


@dataclass
class SimulationParameters:
    """Simulation parameters as features."""

    temperature_k: float = 298.0
    pressure_atm: float = 1.0
    target_atoms: int = DEFAULT_SCREENING_TARGET_ATOMS

    def to_vector(self) -> np.ndarray:
        """Convert to feature vector."""
        return np.array(
            [
                self.temperature_k,
                self.pressure_atm,
                self.target_atoms,
            ]
        )


class FeatureStore:
    """
    Feature Store for managing ML training features.

    Stores and retrieves features extracted from experiments.
    """

    def __init__(self, storage_path: Path | None = None):
        """
        Initialize feature store.

        Args:
            storage_path: Path to store features (optional)
        """
        self.storage_path = storage_path
        self._features: dict[str, list[Feature]] = {}
        self._feature_cache: dict[str, np.ndarray] = {}

        if storage_path and storage_path.exists():
            self._load_from_disk()

    def add_feature(self, feature: Feature) -> None:
        """Add a feature to the store."""
        if feature.exp_id not in self._features:
            self._features[feature.exp_id] = []
        self._features[feature.exp_id].append(feature)

        # Invalidate cache
        if feature.exp_id in self._feature_cache:
            del self._feature_cache[feature.exp_id]

    def add_features(self, features: list[Feature]) -> None:
        """Add multiple features."""
        for feature in features:
            self.add_feature(feature)

    def get_features(
        self,
        exp_id: str,
        feature_type: FeatureType | None = None,
    ) -> list[Feature]:
        """Get features for an experiment."""
        features = self._features.get(exp_id, [])
        if feature_type:
            features = [f for f in features if f.feature_type == feature_type]
        return features

    def get_feature_vector(self, exp_id: str) -> np.ndarray | None:
        """Get combined feature vector for an experiment."""
        if exp_id in self._feature_cache:
            return self._feature_cache[exp_id]

        features = self.get_features(exp_id)
        if not features:
            return None

        # Combine all scalar features
        scalars = []
        for f in features:
            if f.feature_value is not None:
                scalars.append(f.feature_value)
            elif f.feature_vector:
                scalars.extend(f.feature_vector)

        if not scalars:
            return None

        vector = np.array(scalars)
        self._feature_cache[exp_id] = vector
        return vector

    def extract_composition_features(
        self,
        exp_id: str,
        asphaltene: float,
        resin: float,
        aromatic: float,
        saturate: float,
        additive: float = 0.0,
    ) -> list[Feature]:
        """Extract and store composition features."""
        comp = CompositionFeatures.from_composition(asphaltene, resin, aromatic, saturate, additive)

        features = [
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="asphaltene_wt",
                feature_value=comp.asphaltene_wt,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="resin_wt",
                feature_value=comp.resin_wt,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="aromatic_wt",
                feature_value=comp.aromatic_wt,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="saturate_wt",
                feature_value=comp.saturate_wt,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="additive_wt",
                feature_value=comp.additive_wt,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="polar_fraction",
                feature_value=comp.polar_fraction,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="nonpolar_fraction",
                feature_value=comp.nonpolar_fraction,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.COMPOSITION,
                feature_name="asphaltene_resin_ratio",
                feature_value=comp.asphaltene_resin_ratio,
            ),
        ]

        self.add_features(features)
        return features

    def extract_simulation_features(
        self,
        exp_id: str,
        temperature_k: float,
        pressure_atm: float,
        target_atoms: int,
    ) -> list[Feature]:
        """Extract and store simulation parameter features."""
        features = [
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.SIMULATION,
                feature_name="temperature_k",
                feature_value=temperature_k,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.SIMULATION,
                feature_name="pressure_atm",
                feature_value=pressure_atm,
            ),
            Feature(
                exp_id=exp_id,
                feature_type=FeatureType.SIMULATION,
                feature_name="target_atoms",
                feature_value=float(target_atoms),
            ),
        ]

        self.add_features(features)
        return features

    def get_all_exp_ids(self) -> list[str]:
        """Get all experiment IDs in the store."""
        return list(self._features.keys())

    def get_feature_matrix(
        self,
        exp_ids: list[str] | None = None,
        feature_names: list[str] | None = None,
    ) -> tuple[np.ndarray, list[str]]:
        """
        Get feature matrix for multiple experiments.

        Args:
            exp_ids: List of experiment IDs (all if None)
            feature_names: List of feature names to include (all if None)

        Returns:
            Tuple of (feature_matrix, exp_ids_used)
        """
        if exp_ids is None:
            exp_ids = self.get_all_exp_ids()

        vectors = []
        valid_exp_ids = []

        for exp_id in exp_ids:
            vec = self.get_feature_vector(exp_id)
            if vec is not None:
                vectors.append(vec)
                valid_exp_ids.append(exp_id)

        if not vectors:
            return np.array([]), []

        return np.vstack(vectors), valid_exp_ids

    def save_to_disk(self, path: Path | None = None) -> None:
        """Save features to disk."""
        save_path = path or self.storage_path
        if not save_path:
            raise ValueError("No storage path specified")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            exp_id: [f.to_dict() for f in features] for exp_id, features in self._features.items()
        }

        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_from_disk(self) -> None:
        """Load features from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return

        with open(self.storage_path) as f:
            data = json.load(f)

        for exp_id, features in data.items():
            self._features[exp_id] = [Feature.from_dict(f) for f in features]

    def clear(self) -> None:
        """Clear all features."""
        self._features.clear()
        self._feature_cache.clear()

    def __len__(self) -> int:
        """Get total number of experiments with features."""
        return len(self._features)

    def __contains__(self, exp_id: str) -> bool:
        """Check if experiment has features."""
        return exp_id in self._features
