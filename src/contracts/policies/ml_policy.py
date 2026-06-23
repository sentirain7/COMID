"""
ML policy definitions for the Asphalt Binder MD/ML Agent.

Defines feature set versions and ML training policies.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class FeatureSetVersion(StrEnum):
    """ML feature set version identifier."""

    V1 = "v1"  # 11 features: composition(8) + simulation(3)
    V2 = "v2"  # 24 features: V1(11) + additive(13)
    V3 = "v3"  # 40 features: V2(24) + molecule_descriptors(16)
    V4 = "v4"  # 53 features: V3(40) + crystal(10) + amorphous(3)
    V5 = "v5"  # 51 features: V3(40) + bulk context/mechanical(11)
    V6 = "v6"  # 93 features: V5(51) + layered crystal/amorphous/stack(42)
    V7 = "v7"  # 32 features: structural node(30, RDKit descriptor) + system(2) — bulk 화학 (MDML parity)


class RetrainingTrigger(BaseModel):
    """Configuration for model retraining triggers."""

    min_new_samples: int = 50
    max_rmse_drift_pct: float = 10.0
    check_interval_hours: int = 24


class DriftDetectionPolicy(BaseModel):
    """Configuration for drift detection."""

    ks_test_alpha: float = 0.05
    ks_test_min_samples: int = 30
    feature_drift_threshold: float = 0.1
    rmse_window_size: int = 50
    rmse_drift_pct: float = 10.0
    page_hinkley_delta: float = 0.005
    page_hinkley_lambda: float = 50.0


class ModelComparisonPolicy(BaseModel):
    """Configuration for champion/challenger model comparison."""

    comparison_test: str = "wilcoxon"  # wilcoxon | paired_t
    comparison_alpha: float = 0.05
    min_comparison_samples: int = 30
    promotion_rmse_improvement_pct: float = 2.0
    promotion_requires_calibration: bool = True
    auto_rollback_on_degradation: bool = True
    rollback_rmse_degradation_pct: float = 15.0


class CalibrationPolicy(BaseModel):
    """Configuration for uncertainty calibration quality."""

    ece_n_bins: int = 10
    max_acceptable_ece: float = 0.10


class ContinuousLearningPolicy(BaseModel):
    """Configuration for continuous learning loop."""

    check_interval_hours: int = 24
    min_new_samples_for_check: int = 20
    training_data_snapshot: bool = True
    holdout_rotation_interval: int = 5
    holdout_fraction: float = 0.15
    max_model_versions: int = 20
    deterministic_seed_base: int = 42


class TargetComparisonWeights(BaseModel):
    """Per-target comparison weights for multi-target champion evaluation."""

    density: float = 0.30
    cohesive_energy_density: float = 0.20
    viscosity: float = 0.10
    elastic_modulus: float = 0.08
    tensile_strength: float = 0.08
    adhesion_energy: float = 0.06
    msd_diffusion_coefficient: float = 0.04
    rdf_first_peak_r: float = 0.03
    rdf_first_peak_g: float = 0.03
    orientation_order: float = 0.03
    interfacial_tensile_strength: float = 0.02
    e_inter_interface_1: float = 0.02
    work_of_separation: float = 0.01
    rdf_coordination_number: float = 0.0
    e_inter_total: float = 0.0
    ductility: float = 0.0
    toughness: float = 0.0

    def get_weight(self, target_name: str) -> float:
        """Get weight for a target, defaulting to equal share if unknown."""
        return getattr(self, target_name, 0.0)


class TargetFeatureSetMapping(BaseModel):
    """Per-target feature set version mapping (SSOT).

    Bulk targets use V3, layered targets use V4.
    """

    density: FeatureSetVersion = FeatureSetVersion.V3
    cohesive_energy_density: FeatureSetVersion = FeatureSetVersion.V3
    viscosity: FeatureSetVersion = FeatureSetVersion.V3
    msd_diffusion_coefficient: FeatureSetVersion = FeatureSetVersion.V3
    rdf_first_peak_r: FeatureSetVersion = FeatureSetVersion.V3
    rdf_first_peak_g: FeatureSetVersion = FeatureSetVersion.V3
    elastic_modulus: FeatureSetVersion = FeatureSetVersion.V3
    tensile_strength: FeatureSetVersion = FeatureSetVersion.V3
    adhesion_energy: FeatureSetVersion = FeatureSetVersion.V4
    orientation_order: FeatureSetVersion = FeatureSetVersion.V4
    interfacial_tensile_strength: FeatureSetVersion = FeatureSetVersion.V4
    e_inter_interface_1: FeatureSetVersion = FeatureSetVersion.V4
    work_of_separation: FeatureSetVersion = FeatureSetVersion.V4
    rdf_coordination_number: FeatureSetVersion = FeatureSetVersion.V3
    e_inter_total: FeatureSetVersion = FeatureSetVersion.V3
    ductility: FeatureSetVersion = FeatureSetVersion.V4
    toughness: FeatureSetVersion = FeatureSetVersion.V4

    def get_version(self, target_name: str) -> FeatureSetVersion:
        """Get feature set version for a target, defaulting to V3 if unknown."""
        return getattr(self, target_name, FeatureSetVersion.V3)


class MLPolicy(BaseModel):
    """ML training and prediction policy."""

    default_feature_set: FeatureSetVersion = FeatureSetVersion.V1
    v1_feature_count: int = 11
    v2_feature_count: int = 24
    v3_feature_count: int = 40
    v4_feature_count: int = 53
    v5_feature_count: int = 51
    v6_feature_count: int = 93
    v7_feature_count: int = 32
    retraining: RetrainingTrigger = Field(default_factory=RetrainingTrigger)
    min_training_samples: int = 100
    min_additive_samples_for_v2: int = 30
    min_molecule_level_samples_for_v3: int = 50
    min_structural_samples_for_v7: int = 30
    min_layered_samples_for_v4: int = 20
    min_layered_samples_for_v6: int = 20
    min_three_plus_layer_samples_for_v6: int = 5
    min_distinct_stack_signatures_for_v6: int = 2
    min_mechanical_context_samples_for_v5: int = 20
    min_distinct_binder_types_for_v5: int = 2
    min_distinct_aging_states_for_v5: int = 1
    # Phase 5.2: Multi-target / UQ settings
    default_ensemble_size: int = 5
    ood_threshold_percentile: float = 95.0
    uncertainty_ci_level: float = 0.95
    calibration_min_samples: int = 50
    drift_detection: DriftDetectionPolicy = Field(default_factory=DriftDetectionPolicy)
    model_comparison: ModelComparisonPolicy = Field(default_factory=ModelComparisonPolicy)
    calibration: CalibrationPolicy = Field(default_factory=CalibrationPolicy)
    continuous_learning: ContinuousLearningPolicy = Field(default_factory=ContinuousLearningPolicy)
    target_comparison_weights: TargetComparisonWeights = Field(
        default_factory=TargetComparisonWeights
    )
    target_feature_sets: TargetFeatureSetMapping = Field(default_factory=TargetFeatureSetMapping)


DEFAULT_ML_POLICY = MLPolicy()
