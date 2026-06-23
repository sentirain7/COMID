"""
ML Module for Asphalt Binder Property Prediction.

This module provides ML v1/v2 implementation for predicting:
- Density (g/cm3)
- Cohesive Energy Density (J/cm3)
- And 11 additional targets (Phase 5.2)

Based on composition, simulation parameters, and additive features (V2).
"""

from .additive_features import AdditiveFeatureExtractor
from .data_loader import DataLoader, DataSplitter, TargetVariable, TrainingDataset
from .drift_detector import DriftDetector, DriftReport, DriftType
from .feature_registry import FeatureRegistry
from .feature_store import CompositionFeaturesV2, Feature, FeatureStore, FeatureType
from .models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor
from .multi_target import MultiTargetConfig, MultiTargetPredictor, MultiTargetResult
from .ood_detector import OODDetector, OODResult
from .predictor import PredictionInputV2, PredictionResult, Predictor
from .trainer import Trainer, TrainingConfig, TrainingResult
from .uncertainty import UncertaintyEstimator, UncertaintyResult

try:
    from .model_registry import ComparisonResult, ModelRegistry  # noqa: F401
    from .retrainer import ModelRetrainer, RetrainingResult  # noqa: F401

    _HAS_MLOPS = True
except ModuleNotFoundError:
    # Optional in minimal test/runtime environments without SQLAlchemy.
    _HAS_MLOPS = False

__all__ = [
    # Feature Store
    "FeatureStore",
    "Feature",
    "FeatureType",
    "CompositionFeaturesV2",
    # Feature Registry
    "FeatureRegistry",
    # Additive Features
    "AdditiveFeatureExtractor",
    # Data Loading
    "DataLoader",
    "DataSplitter",
    "TrainingDataset",
    "TargetVariable",
    # Drift (Phase 8)
    "DriftDetector",
    "DriftType",
    "DriftReport",
    # Models
    "PropertyPredictor",
    "EnsemblePredictor",
    "ModelConfig",
    "ModelType",
    # Multi-Target (Phase 5.2)
    "MultiTargetPredictor",
    "MultiTargetConfig",
    "MultiTargetResult",
    # Uncertainty (Phase 5.2)
    "UncertaintyEstimator",
    "UncertaintyResult",
    # OOD Detection (Phase 5.2)
    "OODDetector",
    "OODResult",
    # Training
    "Trainer",
    "TrainingConfig",
    "TrainingResult",
    # Prediction
    "Predictor",
    "PredictionResult",
    "PredictionInputV2",
]

if _HAS_MLOPS:
    __all__.extend(
        [
            "ModelRegistry",
            "ComparisonResult",
            "ModelRetrainer",
            "RetrainingResult",
        ]
    )
