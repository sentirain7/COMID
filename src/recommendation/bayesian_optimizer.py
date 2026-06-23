"""
Bayesian Optimizer for multi-objective optimization.

Uses Gaussian Process surrogate models and acquisition functions
for efficient exploration of the composition space.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

try:
    from scipy.optimize import minimize
    from scipy.stats import norm

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

    GP_AVAILABLE = True
except ImportError:
    GP_AVAILABLE = False

from common.logging import get_logger
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY

logger = get_logger("recommendation.bayesian_optimizer")


class AcquisitionFunction(Enum):
    """Acquisition function types."""

    EI = "expected_improvement"
    UCB = "upper_confidence_bound"
    PI = "probability_of_improvement"
    EHVI = "expected_hypervolume_improvement"


@dataclass
class OptimizationObjective:
    """Definition of an optimization objective."""

    name: str
    direction: str = "maximize"  # "maximize" or "minimize"
    weight: float = 1.0
    target_value: float | None = None  # For satisficing

    def __post_init__(self):
        if self.direction not in ["maximize", "minimize"]:
            raise ValueError(f"Invalid direction: {self.direction}")


@dataclass
class OptimizationConfig:
    """Configuration for Bayesian optimization."""

    objectives: list[OptimizationObjective]
    n_initial_samples: int = 10
    n_iterations: int = 50
    acquisition_function: AcquisitionFunction = AcquisitionFunction.EI
    exploration_weight: float = 0.1  # For UCB
    batch_size: int = 1
    seed: int | None = None


@dataclass
class CandidateSolution:
    """A candidate solution from optimization."""

    composition: dict[str, float]
    predicted_objectives: dict[str, float]
    acquisition_value: float
    uncertainty: dict[str, float] = field(default_factory=dict)
    iteration: int = 0
    is_ood: bool = False
    rationale: str | None = None
    target_distances: dict[str, float] = field(default_factory=dict)
    extrapolation_status: str = "in_domain"
    high_uncertainty: bool = False
    capability_notes: list[str] = field(default_factory=list)
    max_uncertainty_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "composition": self.composition,
            "predicted_objectives": self.predicted_objectives,
            "acquisition_value": self.acquisition_value,
            "uncertainty": self.uncertainty,
            "iteration": self.iteration,
            "is_ood": self.is_ood,
            "rationale": self.rationale,
            "target_distances": self.target_distances,
            "extrapolation_status": self.extrapolation_status,
            "high_uncertainty": self.high_uncertainty,
            "capability_notes": list(self.capability_notes),
            "max_uncertainty_ratio": self.max_uncertainty_ratio,
        }


class SurrogateModel:
    """
    Gaussian Process surrogate model for Bayesian optimization.

    Uses scikit-learn's GaussianProcessRegressor with an RBF + WhiteKernel
    when available, falling back to weighted distance interpolation otherwise.
    """

    def __init__(self, length_scale: float = 1.0, noise: float = 0.1):
        """
        Initialize surrogate model.

        Args:
            length_scale: RBF kernel length scale
            noise: Observation noise level
        """
        self.length_scale = length_scale
        self.noise = noise
        self.X_train: np.ndarray | None = None
        self.y_train: np.ndarray | None = None
        self._fitted = False
        self._gp: Any = None

        if GP_AVAILABLE:
            self._kernel_template = lambda ls, ns: (
                ConstantKernel(1.0) * RBF(length_scale=ls) + WhiteKernel(noise_level=ns**2)
            )
            kernel = self._kernel_template(length_scale, noise)
            self._gp = GaussianProcessRegressor(
                kernel=kernel,
                n_restarts_optimizer=5,
                normalize_y=True,
                alpha=1e-6,
            )

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SurrogateModel":
        """
        Fit the surrogate model.

        Args:
            X: Training inputs (n_samples, n_features)
            y: Training outputs (n_samples,)

        Returns:
            Self
        """
        self.X_train = X.copy()
        self.y_train = y.copy()
        self._fitted = True

        if self._gp is not None:
            try:
                # For very small datasets (< 5 points), hyperparameter optimization
                # can find degenerate solutions. Use fixed hyperparameters instead.
                if len(X) < 5:
                    kernel = self._kernel_template(self.length_scale, self.noise)
                    gp = GaussianProcessRegressor(
                        kernel=kernel,
                        optimizer=None,  # Fix hyperparameters
                        normalize_y=True,
                        alpha=1e-6,
                    )
                    gp.fit(X, y)
                    self._gp = gp
                else:
                    self._gp.fit(X, y)
            except Exception as e:
                logger.warning(f"GP fit failed, falling back to interpolation: {e}")
                self._gp = None

        return self

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Predict mean and standard deviation.

        Args:
            X: Input points (n_points, n_features)

        Returns:
            Tuple of (mean, std) arrays
        """
        if not self._fitted:
            return np.zeros(len(X)), np.ones(len(X))

        if self._gp is not None:
            mean, std = self._gp.predict(X, return_std=True)
            return np.asarray(mean), np.asarray(std)

        # Fallback: weighted distance interpolation
        return self._predict_interpolation(X)

    def _predict_interpolation(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Fallback prediction using weighted distance interpolation."""
        assert self.X_train is not None and self.y_train is not None
        n_test = len(X)
        means = np.zeros(n_test)
        stds = np.zeros(n_test)

        for i in range(n_test):
            dists = np.linalg.norm(self.X_train - X[i], axis=1)
            weights = np.exp(-0.5 * (dists / self.length_scale) ** 2)
            weights /= weights.sum() + 1e-10

            means[i] = np.sum(weights * self.y_train)

            min_dist = np.min(dists)
            stds[i] = self.noise + 0.5 * (1 - np.exp(-min_dist / self.length_scale))

        return means, stds


class BayesianOptimizer:
    """
    Multi-objective Bayesian optimization for composition optimization.
    """

    def __init__(
        self,
        config: OptimizationConfig,
        bounds: dict[str, tuple[float, float]],
        predictor_fn: Callable | None = None,
    ):
        """
        Initialize optimizer.

        Args:
            config: Optimization configuration
            bounds: Search bounds for each parameter
            predictor_fn: Function to predict objectives from composition
        """
        self.config = config
        self.bounds = bounds
        self.predictor_fn = predictor_fn

        self.param_names = list(bounds.keys())
        self.n_params = len(self.param_names)

        # Surrogate models for each objective
        self.surrogates: dict[str, SurrogateModel] = {
            obj.name: SurrogateModel() for obj in config.objectives
        }

        # Optimization history
        self.X_history: list[np.ndarray] = []
        self.y_history: dict[str, list[float]] = {obj.name: [] for obj in config.objectives}
        self.candidates: list[CandidateSolution] = []

        # Random state
        self.rng = np.random.RandomState(config.seed)

    def suggest(self, n_suggestions: int = 1) -> list[dict[str, float]]:
        """
        Suggest next compositions to evaluate.

        Args:
            n_suggestions: Number of suggestions to return

        Returns:
            List of composition dictionaries
        """
        if len(self.X_history) < self.config.n_initial_samples:
            # Initial random sampling
            return self._random_samples(n_suggestions)

        # Fit surrogate models
        X = np.array(self.X_history)
        for obj in self.config.objectives:
            y = np.array(self.y_history[obj.name])
            self.surrogates[obj.name].fit(X, y)

        # Optimize acquisition function with diversity repulsion
        suggestions = []
        suggested_arrays: list[np.ndarray] = []
        for _ in range(n_suggestions):
            x_best = self._optimize_acquisition()

            # Repulsion: push away from already-suggested candidates
            if suggested_arrays:
                for _retry in range(3):
                    min_dist = min(
                        float(np.linalg.norm(x_best - prev)) for prev in suggested_arrays
                    )
                    if min_dist > 0.05:
                        break
                    # Perturb and re-optimize
                    x_best = self._optimize_acquisition()

            suggested_arrays.append(x_best.copy())
            composition = self._array_to_composition(x_best)

            # Normalize only composition-like variables to sum to 100.
            # Context variables such as temperature must stay in physical units.
            composition_keys = {
                "asphaltene",
                "resin",
                "aromatic",
                "saturate",
                "additive",
            }
            total = sum(v for k, v in composition.items() if k in composition_keys)
            if total > 0:
                composition = {
                    k: (v * 100 / total if k in composition_keys else v)
                    for k, v in composition.items()
                }

            suggestions.append(composition)

        return suggestions

    def tell(
        self,
        composition: dict[str, float],
        objectives: dict[str, float],
    ) -> None:
        """
        Report observed objectives for a composition.

        Args:
            composition: The evaluated composition
            objectives: Observed objective values
        """
        x = self._composition_to_array(composition)
        self.X_history.append(x)

        for obj in self.config.objectives:
            if obj.name in objectives:
                self.y_history[obj.name].append(objectives[obj.name])

    def get_best(self, n_best: int = 5) -> list[CandidateSolution]:
        """
        Get the best solutions found so far.

        Args:
            n_best: Number of best solutions to return

        Returns:
            List of best CandidateSolution objects
        """
        if len(self.X_history) == 0:
            return []

        # Calculate scalarized objective for ranking
        scores = []
        for i, _x in enumerate(self.X_history):
            score = 0.0
            for obj in self.config.objectives:
                y = self.y_history[obj.name][i]
                if obj.direction == "maximize":
                    score += obj.weight * y
                else:
                    score -= obj.weight * y
            scores.append(score)

        # Sort by score
        sorted_indices = np.argsort(scores)[::-1][:n_best]

        results = []
        for idx in sorted_indices:
            composition = self._array_to_composition(self.X_history[idx])
            objectives = {obj.name: self.y_history[obj.name][idx] for obj in self.config.objectives}
            results.append(
                CandidateSolution(
                    composition=composition,
                    predicted_objectives=objectives,
                    acquisition_value=scores[idx],
                    iteration=idx,
                )
            )

        return results

    def _random_samples(self, n: int) -> list[dict[str, float]]:
        """Generate random samples within bounds."""
        samples = []
        composition_keys = {"asphaltene", "resin", "aromatic", "saturate", "additive"}
        for _ in range(n):
            composition = {}
            for name, (low, high) in self.bounds.items():
                composition[name] = self.rng.uniform(low, high)

            # Normalize only composition-like variables to sum to 100.
            total = sum(v for k, v in composition.items() if k in composition_keys)
            if total > 0:
                composition = {
                    k: (v * 100 / total if k in composition_keys else v)
                    for k, v in composition.items()
                }

            samples.append(composition)
        return samples

    def _composition_to_array(self, composition: dict[str, float]) -> np.ndarray:
        """Convert composition dict to array."""
        return np.array([composition.get(name, 0) for name in self.param_names])

    def _array_to_composition(self, x: np.ndarray) -> dict[str, float]:
        """Convert array to composition dict."""
        return {name: float(x[i]) for i, name in enumerate(self.param_names)}

    def _optimize_acquisition(self) -> np.ndarray:
        """Optimize acquisition function to find next point."""
        best_x = None
        best_acq = -np.inf

        # Multi-start optimization
        n_starts = DEFAULT_RECOMMENDATION_POLICY.ehvi.n_restarts
        for _ in range(n_starts):
            # Random starting point
            x0 = np.array(
                [self.rng.uniform(low, high) for name, (low, high) in self.bounds.items()]
            )

            if SCIPY_AVAILABLE:
                # Use scipy minimize
                bounds_list = [self.bounds[name] for name in self.param_names]

                def neg_acquisition(x):
                    return -self._acquisition(x)

                result = minimize(
                    neg_acquisition,
                    x0,
                    method="L-BFGS-B",
                    bounds=bounds_list,
                )
                x_opt = result.x
            else:
                # Simple gradient-free search
                x_opt = x0
                for _ in range(100):
                    grad = np.zeros_like(x_opt)
                    eps = 0.01
                    acq_base = self._acquisition(x_opt)

                    for i in range(len(x_opt)):
                        x_plus = x_opt.copy()
                        x_plus[i] += eps
                        grad[i] = (self._acquisition(x_plus) - acq_base) / eps

                    x_opt = x_opt + 0.1 * grad
                    # Clip to bounds
                    for i, name in enumerate(self.param_names):
                        low, high = self.bounds[name]
                        x_opt[i] = np.clip(x_opt[i], low, high)

            acq = self._acquisition(x_opt)
            if acq > best_acq:
                best_acq = acq
                best_x = x_opt

        return best_x if best_x is not None else x0

    def _acquisition(self, x: np.ndarray) -> float:
        """
        Calculate acquisition function value.

        Args:
            x: Input point

        Returns:
            Acquisition value
        """
        x = x.reshape(1, -1)

        if self.config.acquisition_function == AcquisitionFunction.EI:
            return self._expected_improvement(x)
        elif self.config.acquisition_function == AcquisitionFunction.UCB:
            return self._upper_confidence_bound(x)
        elif self.config.acquisition_function == AcquisitionFunction.PI:
            return self._probability_of_improvement(x)
        elif self.config.acquisition_function == AcquisitionFunction.EHVI:
            return self._expected_hypervolume_improvement(x)
        else:
            # Default to scalarized EI
            return self._expected_improvement(x)

    def _expected_improvement(self, x: np.ndarray) -> float:
        """Calculate Expected Improvement."""
        total_ei = 0.0

        for obj in self.config.objectives:
            mean, std = self.surrogates[obj.name].predict(x)
            mean, std = mean[0], std[0]

            if std < 1e-10:
                continue

            # Current best
            if obj.direction == "maximize":
                best = np.max(self.y_history[obj.name]) if self.y_history[obj.name] else 0
                z = (mean - best) / std
            else:
                best = np.min(self.y_history[obj.name]) if self.y_history[obj.name] else 0
                z = (best - mean) / std

            if SCIPY_AVAILABLE:
                ei = std * (z * norm.cdf(z) + norm.pdf(z))
            else:
                # Approximate normal CDF and PDF
                ei = std * max(0, z)

            total_ei += obj.weight * ei

        return total_ei

    def _upper_confidence_bound(self, x: np.ndarray) -> float:
        """Calculate Upper Confidence Bound."""
        total_ucb = 0.0
        beta = self.config.exploration_weight

        for obj in self.config.objectives:
            mean, std = self.surrogates[obj.name].predict(x)
            mean, std = mean[0], std[0]

            if obj.direction == "maximize":
                ucb = mean + beta * std
            else:
                ucb = -mean + beta * std

            total_ucb += obj.weight * ucb

        return total_ucb

    def _probability_of_improvement(self, x: np.ndarray) -> float:
        """Calculate Probability of Improvement."""
        total_pi = 0.0

        for obj in self.config.objectives:
            mean, std = self.surrogates[obj.name].predict(x)
            mean, std = mean[0], std[0]

            if std < 1e-10:
                continue

            if obj.direction == "maximize":
                best = np.max(self.y_history[obj.name]) if self.y_history[obj.name] else 0
                z = (mean - best) / std
            else:
                best = np.min(self.y_history[obj.name]) if self.y_history[obj.name] else 0
                z = (best - mean) / std

            if SCIPY_AVAILABLE:
                pi = norm.cdf(z)
            else:
                # Approximate normal CDF
                pi = 0.5 * (1 + np.tanh(z * 0.7))

            total_pi += obj.weight * pi

        return total_pi

    def _expected_hypervolume_improvement(self, x: np.ndarray) -> float:
        """Calculate Expected Hypervolume Improvement via Monte Carlo.

        Falls back to scalarized EI when:
        1. Number of objectives < 2 (single-objective)
        2. History has < 3 observations (Pareto front unreliable)
        3. Numerical error during MC estimation (NaN/Inf)
        """
        n_objectives = len(self.config.objectives)

        # Fallback condition 1: single objective
        if n_objectives < 2:
            return self._expected_improvement(x)

        # Fallback condition 2: insufficient history
        min_hist = min(len(v) for v in self.y_history.values()) if self.y_history else 0
        if min_hist < 3:
            return self._expected_improvement(x)

        try:
            return self._ehvi_mc(x)
        except Exception as e:
            logger.warning(f"MC-EHVI failed, falling back to EI: {e}")
            return self._expected_improvement(x)

    def _ehvi_mc(self, x: np.ndarray) -> float:
        """Monte Carlo EHVI computation."""
        ehvi_cfg = DEFAULT_RECOMMENDATION_POLICY.ehvi
        n_mc = ehvi_cfg.n_mc_samples

        n_objectives = len(self.config.objectives)

        # Get GP predictions (mean, std) for each objective
        means = np.zeros(n_objectives)
        stds = np.zeros(n_objectives)
        for i, obj in enumerate(self.config.objectives):
            m, s = self.surrogates[obj.name].predict(x)
            means[i] = m[0]
            stds[i] = max(s[0], 1e-10)

        # Get current Pareto front points (sign-normalised to maximise)
        pareto_points = self._get_pareto_front_points()

        # Reference point
        ref = self._get_reference_point(pareto_points)

        # Current hypervolume
        current_hv = self._compute_hv(pareto_points, ref)

        # MC sampling: draw from GP posterior
        rng = np.random.RandomState(42)
        samples = rng.randn(n_mc, n_objectives)  # standard normal
        samples = means + samples * stds  # transform to GP posterior

        # Apply sign normalisation (convert to maximisation)
        signs = np.array(
            [1.0 if obj.direction == "maximize" else -1.0 for obj in self.config.objectives]
        )
        samples_norm = samples * signs

        total_improvement = 0.0
        for s in samples_norm:
            # Augment Pareto front with candidate sample
            augmented = (
                np.vstack([pareto_points, s.reshape(1, -1)])
                if len(pareto_points) > 0
                else s.reshape(1, -1)
            )

            new_hv = self._compute_hv(augmented, ref)
            improvement = max(0.0, new_hv - current_hv)
            total_improvement += improvement

        ehvi = total_improvement / n_mc

        # Fallback condition 3: numerical error
        if not np.isfinite(ehvi):
            logger.warning("MC-EHVI returned non-finite value, falling back to EI")
            return self._expected_improvement(x)

        return ehvi

    def _get_pareto_front_points(self) -> np.ndarray:
        """Extract current Pareto front from history (sign-normalised)."""
        n_obs = min(len(v) for v in self.y_history.values()) if self.y_history else 0
        if n_obs == 0:
            return np.empty((0, len(self.config.objectives)))

        signs = np.array(
            [1.0 if obj.direction == "maximize" else -1.0 for obj in self.config.objectives]
        )

        # Build objectives matrix
        Y = np.zeros((n_obs, len(self.config.objectives)))
        for j, obj in enumerate(self.config.objectives):
            for i in range(n_obs):
                Y[i, j] = self.y_history[obj.name][i]
        Y_norm = Y * signs

        # Find non-dominated points
        n = len(Y_norm)
        is_pareto = np.ones(n, dtype=bool)
        for i in range(n):
            if not is_pareto[i]:
                continue
            for j in range(n):
                if i == j or not is_pareto[j]:
                    continue
                if np.all(Y_norm[j] >= Y_norm[i]) and np.any(Y_norm[j] > Y_norm[i]):
                    is_pareto[i] = False
                    break

        return Y_norm[is_pareto]

    def _get_reference_point(self, pareto_points: np.ndarray) -> np.ndarray:
        """Compute reference point as nadir - offset."""
        offset = DEFAULT_RECOMMENDATION_POLICY.ehvi.reference_point_offset
        if len(pareto_points) == 0:
            return np.zeros(len(self.config.objectives)) - offset
        return np.min(pareto_points, axis=0) - offset

    def _compute_hv(self, points: np.ndarray, ref: np.ndarray) -> float:
        """Compute hypervolume dominated by *points* above *ref*.

        Uses ParetoCalculator for 2D exact; MC for higher dimensions.
        """
        if len(points) == 0:
            return 0.0

        # Filter to points dominating ref
        mask = np.all(points > ref, axis=1)
        pts = points[mask]
        if len(pts) == 0:
            return 0.0

        n_obj = pts.shape[1]
        if n_obj == 2:
            # Exact 2D sweep
            sorted_idx = np.argsort(pts[:, 0])
            sorted_pts = pts[sorted_idx]
            hv = 0.0
            prev_x = ref[0]
            for p in sorted_pts:
                width = p[0] - prev_x
                height = p[1] - ref[1]
                if width > 0 and height > 0:
                    hv += width * height
                prev_x = max(prev_x, p[0])
            return hv

        # MC approximation for higher dimensions
        upper = np.max(pts, axis=0)
        box_vol = float(np.prod(upper - ref))
        if box_vol <= 0:
            return 0.0

        n_samples = 5000
        rng = np.random.RandomState(123)
        samples = rng.uniform(ref, upper, (n_samples, n_obj))

        dominated = 0
        for sample in samples:
            for p in pts:
                if np.all(p >= sample):
                    dominated += 1
                    break

        return box_vol * dominated / n_samples


def create_default_optimizer(
    include_additive: bool = True,
) -> BayesianOptimizer:
    """
    Create a default Bayesian optimizer for asphalt composition.

    Args:
        include_additive: Whether to include additive in optimization

    Returns:
        Configured BayesianOptimizer
    """
    objectives = [
        OptimizationObjective(name="density", direction="maximize", weight=1.0),
        OptimizationObjective(name="cohesive_energy_density", direction="maximize", weight=1.0),
    ]

    config = OptimizationConfig(
        objectives=objectives,
        n_initial_samples=10,
        n_iterations=50,
        acquisition_function=AcquisitionFunction.EI,
    )

    bounds = {
        "asphaltene": (5.0, 30.0),
        "resin": (10.0, 50.0),
        "aromatic": (10.0, 60.0),
        "saturate": (5.0, 40.0),
    }

    if include_additive:
        bounds["additive"] = (0.0, 10.0)

    return BayesianOptimizer(config=config, bounds=bounds)
