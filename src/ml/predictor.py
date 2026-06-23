"""
Predictor for making predictions on new compositions.

Provides high-level interface for property prediction.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from contracts.policies.ml_policy import FeatureSetVersion
from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS

from .feature_builder import FeatureBuildInput, build_feature_result
from .models import PropertyPredictor

_logger = logging.getLogger(__name__)


@dataclass
class PredictionInput:
    """Input for prediction."""

    # Composition (wt%)
    asphaltene: float = 20.0
    resin: float = 30.0
    aromatic: float = 35.0
    saturate: float = 15.0
    additive: float = 0.0

    # Simulation parameters
    temperature_k: float = 298.0
    pressure_atm: float = 1.0
    target_atoms: int = DEFAULT_SCREENING_TARGET_ATOMS

    def to_feature_vector(self) -> np.ndarray:
        """Convert to ML v1 feature vector."""
        result = build_feature_result(
            FeatureBuildInput(
                asphaltene_wt=self.asphaltene,
                resin_wt=self.resin,
                aromatic_wt=self.aromatic,
                saturate_wt=self.saturate,
                additive_wt=self.additive,
                temperature_k=self.temperature_k,
                pressure_atm=self.pressure_atm,
                target_atoms=float(self.target_atoms),
            ),
            FeatureSetVersion.V1,
        )
        return result.values

    def validate(self) -> tuple[bool, str | None]:
        """Validate input."""
        total = self.asphaltene + self.resin + self.aromatic + self.saturate + self.additive
        if abs(total - 100.0) > 0.1:
            return False, f"Composition must sum to 100%, got {total:.2f}%"

        if any(
            x < 0
            for x in [self.asphaltene, self.resin, self.aromatic, self.saturate, self.additive]
        ):
            return False, "All composition values must be non-negative"

        if self.temperature_k < 200 or self.temperature_k > 500:
            return False, f"Temperature must be between 200-500K, got {self.temperature_k}"

        if self.pressure_atm < 0.1 or self.pressure_atm > 100:
            return False, f"Pressure must be between 0.1-100 atm, got {self.pressure_atm}"

        return True, None


@dataclass
class PredictionInputV2(PredictionInput):
    """V2 prediction input with additive metadata."""

    additive_type: str | None = None
    additive_mol_id: str | None = None

    def to_feature_vector(self) -> np.ndarray:
        """Convert to ML V2 feature vector (24 elements)."""
        result = build_feature_result(
            FeatureBuildInput(
                asphaltene_wt=self.asphaltene,
                resin_wt=self.resin,
                aromatic_wt=self.aromatic,
                saturate_wt=self.saturate,
                additive_wt=self.additive,
                temperature_k=self.temperature_k,
                pressure_atm=self.pressure_atm,
                target_atoms=float(self.target_atoms),
                additive_type=self.additive_type,
                additive_mol_id=self.additive_mol_id,
            ),
            FeatureSetVersion.V2,
        )
        return result.values


@dataclass
class PredictionResult:
    """Result of a prediction."""

    target: str
    value: float
    uncertainty: float | None = None
    confidence_interval: tuple[float, float] | None = None
    input: PredictionInput | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "target": self.target,
            "value": self.value,
            "uncertainty": self.uncertainty,
            "confidence_interval": self.confidence_interval,
            "metadata": self.metadata,
        }


class Predictor:
    """
    High-level predictor for property prediction.

    Manages multiple models for different target properties.
    """

    def __init__(self, model_dir: Path | None = None):
        """
        Initialize predictor.

        Args:
            model_dir: Directory containing saved models
        """
        self.model_dir = Path(model_dir) if model_dir else None
        self._models: dict[str, PropertyPredictor] = {}

    def load_model(self, target: str, model_path: Path | None = None) -> None:
        """
        Load a model for a specific target.

        Args:
            target: Target variable name
            model_path: Path to model (uses model_dir/model_{target} if None)
        """
        if model_path is None:
            if self.model_dir is None:
                raise ValueError("No model_dir specified and no model_path provided")
            model_path = self.model_dir / f"model_{target}"

        self._models[target] = PropertyPredictor.load(model_path)

    def load_all_models(self) -> None:
        """Load all available models from model_dir."""
        if self.model_dir is None:
            raise ValueError("No model_dir specified")

        from .data_loader import TargetVariable

        for target in TargetVariable:
            model_path = self.model_dir / f"model_{target.value}.json"
            if model_path.exists():
                self.load_model(target.value)

    def _get_expected_features(self, model: PropertyPredictor) -> int | None:
        """Get expected feature count from model. Priority chain (v2-4).

        Args:
            model: The property predictor model.

        Returns:
            Expected feature count, or None if undetermined.
        """
        # Priority 1: model.config.feature_names
        if hasattr(model, "config") and hasattr(model.config, "feature_names"):
            if model.config.feature_names:
                return len(model.config.feature_names)
        # Priority 2: scikit-learn standard attribute
        inner = getattr(model, "_model", model)
        n_feat = getattr(inner, "n_features_in_", None)
        if n_feat is not None:
            return int(n_feat)
        # Priority 3: cannot determine
        _logger.warning("Cannot determine expected feature count, skipping dimension check")
        return None

    def predict(
        self,
        input: PredictionInput,
        target: str = "density",
    ) -> PredictionResult:
        """
        Make a prediction for a single input.

        Args:
            input: Prediction input
            target: Target variable to predict

        Returns:
            PredictionResult
        """
        # Validate input
        valid, error = input.validate()
        if not valid:
            raise ValueError(f"Invalid input: {error}")

        # Check model
        if target not in self._models:
            raise ValueError(f"No model loaded for target: {target}")

        model = self._models[target]

        # Get feature vector
        X = input.to_feature_vector().reshape(1, -1)

        # Dimension check
        expected_dim = self._get_expected_features(model)
        if expected_dim is not None and X.shape[1] != expected_dim:
            raise ValueError(
                f"Feature dimension mismatch: input={X.shape[1]}, model expects={expected_dim}"
            )

        # Apply normalization if available
        norm_params = model.get_normalization_params()
        if norm_params:
            X = self._apply_normalization(X, norm_params)

        # Predict
        prediction = model.predict(X)[0]

        return PredictionResult(
            target=target,
            value=float(prediction),
            input=input,
            metadata={"model_type": model.config.model_type.value},
        )

    def predict_batch(
        self,
        inputs: list[PredictionInput],
        target: str = "density",
    ) -> list[PredictionResult]:
        """
        Make predictions for multiple inputs.

        Args:
            inputs: List of prediction inputs
            target: Target variable to predict

        Returns:
            List of PredictionResults
        """
        results = []
        for inp in inputs:
            try:
                result = self.predict(inp, target)
                results.append(result)
            except ValueError as e:
                results.append(
                    PredictionResult(
                        target=target,
                        value=float("nan"),
                        metadata={"error": str(e)},
                    )
                )
        return results

    def predict_all_targets(
        self,
        input: PredictionInput,
    ) -> dict[str, PredictionResult]:
        """
        Predict all available targets.

        Args:
            input: Prediction input

        Returns:
            Dict mapping target name to PredictionResult
        """
        results = {}
        for target in self._models:
            try:
                results[target] = self.predict(input, target)
            except ValueError as e:
                results[target] = PredictionResult(
                    target=target,
                    value=float("nan"),
                    metadata={"error": str(e)},
                )
        return results

    def _apply_normalization(
        self,
        X: np.ndarray,
        params: dict[str, Any],
    ) -> np.ndarray:
        """Apply normalization."""
        if params["method"] == "standard":
            mean = np.array(params["mean"])
            std = np.array(params["std"])
            return (X - mean) / std
        elif params["method"] == "minmax":
            min_val = np.array(params["min"])
            max_val = np.array(params["max"])
            range_val = max_val - min_val
            range_val[range_val == 0] = 1
            return (X - min_val) / range_val
        return X

    @property
    def available_targets(self) -> list[str]:
        """Get list of available targets."""
        return list(self._models.keys())

    def is_loaded(self, target: str) -> bool:
        """Check if model is loaded for target."""
        return target in self._models


def predict_density(
    asphaltene: float,
    resin: float,
    aromatic: float,
    saturate: float,
    additive: float = 0.0,
    temperature_k: float = 298.0,
    pressure_atm: float = 1.0,
    model_path: Path | None = None,
) -> float:
    """
    Convenience function to predict density.

    Args:
        asphaltene: Asphaltene wt%
        resin: Resin wt%
        aromatic: Aromatic wt%
        saturate: Saturate wt%
        additive: Additive wt%
        temperature_k: Temperature in Kelvin
        pressure_atm: Pressure in atm
        model_path: Path to model

    Returns:
        Predicted density (g/cm³)
    """
    input = PredictionInput(
        asphaltene=asphaltene,
        resin=resin,
        aromatic=aromatic,
        saturate=saturate,
        additive=additive,
        temperature_k=temperature_k,
        pressure_atm=pressure_atm,
    )

    predictor = Predictor()
    if model_path:
        predictor.load_model("density", model_path)
    else:
        raise ValueError("model_path is required")

    result = predictor.predict(input, "density")
    return result.value


class CompositionOptimizer:
    """
    Optimizer for finding optimal compositions.

    Uses ML predictions to suggest compositions.
    """

    def __init__(self, predictor: Predictor):
        """
        Initialize optimizer.

        Args:
            predictor: Predictor with loaded models
        """
        self.predictor = predictor

    def optimize_single_target(
        self,
        target: str,
        maximize: bool = True,
        constraints: dict[str, tuple[float, float]] | None = None,
        n_samples: int = 1000,
        temperature_k: float = 298.0,
        pressure_atm: float = 1.0,
    ) -> tuple[PredictionInput, float]:
        """
        Find optimal composition for a single target.

        Args:
            target: Target to optimize
            maximize: True to maximize, False to minimize
            constraints: Dict of component -> (min, max) bounds
            n_samples: Number of random samples to try
            temperature_k: Temperature
            pressure_atm: Pressure

        Returns:
            Tuple of (best_input, best_value)
        """
        if constraints is None:
            constraints = {
                "asphaltene": (5, 30),
                "resin": (10, 50),
                "aromatic": (10, 60),
                "saturate": (5, 40),
                "additive": (0, 10),
            }

        best_input = None
        best_value = float("-inf") if maximize else float("inf")

        np.random.seed(42)

        for _ in range(n_samples):
            # Generate random composition
            comp = {}
            remaining = 100.0

            for component in ["asphaltene", "resin", "aromatic", "saturate"]:
                min_val, max_val = constraints.get(component, (0, 100))
                # Sample within bounds, respecting remaining budget
                max_possible = min(max_val, remaining - 5)  # Leave room for others
                if max_possible < min_val:
                    break
                comp[component] = np.random.uniform(min_val, max_possible)
                remaining -= comp[component]

            # Additive takes the rest (or 0)
            add_min, add_max = constraints.get("additive", (0, 10))
            comp["additive"] = min(max(remaining, add_min), add_max)

            # Adjust to sum to 100
            total = sum(comp.values())
            if abs(total - 100) > 0.1:
                # Scale to 100
                scale = 100.0 / total
                for k in comp:
                    comp[k] *= scale

            inp = PredictionInput(
                asphaltene=comp["asphaltene"],
                resin=comp["resin"],
                aromatic=comp["aromatic"],
                saturate=comp["saturate"],
                additive=comp["additive"],
                temperature_k=temperature_k,
                pressure_atm=pressure_atm,
            )

            try:
                result = self.predictor.predict(inp, target)
                value = result.value

                if (maximize and value > best_value) or (not maximize and value < best_value):
                    best_value = value
                    best_input = inp
            except ValueError:
                continue

        return best_input, best_value
