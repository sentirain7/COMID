"""
Pareto Front calculation for multi-objective optimization.

Provides efficient Pareto dominance checking and front extraction.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

from common.logging import get_logger

logger = get_logger("recommendation.pareto")


@dataclass
class ParetoPoint:
    """A point in the objective space with associated data."""

    objectives: np.ndarray  # Objective values (to be maximized after sign flip)
    composition: dict[str, float]
    predicted_properties: dict[str, float]
    index: int = -1
    is_pareto: bool = False
    crowding_distance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "objectives": self.objectives.tolist(),
            "composition": self.composition,
            "predicted_properties": self.predicted_properties,
            "index": self.index,
            "is_pareto": self.is_pareto,
            "crowding_distance": self.crowding_distance,
        }


@dataclass
class ParetoFront:
    """Result of Pareto front calculation."""

    points: list[ParetoPoint]
    objective_names: list[str]
    directions: list[str]  # "maximize" or "minimize"
    n_total_points: int = 0

    def get_pareto_points(self) -> list[ParetoPoint]:
        """Get only the Pareto-optimal points."""
        return [p for p in self.points if p.is_pareto]

    def get_top_k(self, k: int = 5, sort_by: str = "crowding_distance") -> list[ParetoPoint]:
        """
        Get top-k points from Pareto front.

        Args:
            k: Number of points to return
            sort_by: Criterion for sorting ("crowding_distance" or objective name)

        Returns:
            Top-k Pareto points
        """
        pareto_points = self.get_pareto_points()

        if sort_by == "crowding_distance":
            # Higher crowding distance = more diverse
            pareto_points.sort(key=lambda p: p.crowding_distance, reverse=True)
        elif sort_by in self.objective_names:
            idx = self.objective_names.index(sort_by)
            # Sort by objective value (after normalization direction)
            pareto_points.sort(key=lambda p: p.objectives[idx], reverse=True)

        return pareto_points[:k]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "points": [p.to_dict() for p in self.points],
            "objective_names": self.objective_names,
            "directions": self.directions,
            "n_total_points": self.n_total_points,
            "n_pareto_points": len(self.get_pareto_points()),
        }


class ParetoCalculator:
    """
    Calculator for Pareto fronts in multi-objective optimization.
    """

    def __init__(
        self,
        objectives: list[str],
        directions: list[str] | None = None,
    ):
        """
        Initialize Pareto calculator.

        Args:
            objectives: List of objective names
            directions: "maximize" or "minimize" for each objective
                       (default: all "maximize")
        """
        self.objectives = objectives
        self.directions = directions or ["maximize"] * len(objectives)

        if len(self.directions) != len(self.objectives):
            raise ValueError("Number of directions must match number of objectives")

        # Sign multipliers for converting to maximization problem
        self.signs = np.array([1.0 if d == "maximize" else -1.0 for d in self.directions])

    def dominates(self, a: np.ndarray, b: np.ndarray) -> bool:
        """
        Check if point a dominates point b.

        A dominates B if A is at least as good in all objectives
        and strictly better in at least one.

        Args:
            a: Objective values for point A (after sign normalization)
            b: Objective values for point B (after sign normalization)

        Returns:
            True if a dominates b
        """
        return np.all(a >= b) and np.any(a > b)

    def is_pareto_optimal(
        self,
        point: np.ndarray,
        other_points: np.ndarray,
    ) -> bool:
        """
        Check if a point is Pareto optimal.

        Args:
            point: The point to check
            other_points: All other points

        Returns:
            True if point is not dominated by any other point
        """
        for other in other_points:
            if self.dominates(other, point):
                return False
        return True

    def calculate_pareto_front(
        self,
        points: list[ParetoPoint],
    ) -> ParetoFront:
        """
        Calculate the Pareto front from a set of points.

        Args:
            points: List of ParetoPoints with objective values

        Returns:
            ParetoFront with dominance information
        """
        if len(points) == 0:
            return ParetoFront(
                points=[],
                objective_names=self.objectives,
                directions=self.directions,
                n_total_points=0,
            )

        n_points = len(points)

        # Convert objectives to numpy array and apply sign normalization
        objectives_matrix = np.array([p.objectives for p in points])
        normalized = objectives_matrix * self.signs

        # Find Pareto optimal points
        pareto_mask = np.ones(n_points, dtype=bool)

        for i in range(n_points):
            if not pareto_mask[i]:
                continue

            for j in range(n_points):
                if i == j or not pareto_mask[j]:
                    continue

                if self.dominates(normalized[j], normalized[i]):
                    pareto_mask[i] = False
                    break

        # Update points with Pareto status
        for i, point in enumerate(points):
            point.is_pareto = pareto_mask[i]
            point.index = i

        # Calculate crowding distance for Pareto points
        pareto_indices = np.where(pareto_mask)[0]
        if len(pareto_indices) > 0:
            crowding = self._calculate_crowding_distance(normalized[pareto_indices])
            for i, idx in enumerate(pareto_indices):
                points[idx].crowding_distance = crowding[i]

        return ParetoFront(
            points=points,
            objective_names=self.objectives,
            directions=self.directions,
            n_total_points=n_points,
        )

    def _calculate_crowding_distance(self, points: np.ndarray) -> np.ndarray:
        """
        Calculate crowding distance for diversity preservation.

        Args:
            points: Pareto optimal points (n_points, n_objectives)

        Returns:
            Crowding distance for each point
        """
        n_points, n_objectives = points.shape
        distances = np.zeros(n_points)

        for obj_idx in range(n_objectives):
            # Sort by this objective
            sorted_indices = np.argsort(points[:, obj_idx])

            # Boundary points get infinite distance
            distances[sorted_indices[0]] = np.inf
            distances[sorted_indices[-1]] = np.inf

            # Calculate range for normalization
            obj_range = points[sorted_indices[-1], obj_idx] - points[sorted_indices[0], obj_idx]

            if obj_range > 0:
                for i in range(1, n_points - 1):
                    idx = sorted_indices[i]
                    prev_idx = sorted_indices[i - 1]
                    next_idx = sorted_indices[i + 1]

                    distances[idx] += (
                        points[next_idx, obj_idx] - points[prev_idx, obj_idx]
                    ) / obj_range

        return distances

    def hypervolume_indicator(
        self,
        pareto_front: ParetoFront,
        reference_point: np.ndarray | None = None,
    ) -> float:
        """
        Calculate hypervolume indicator for the Pareto front.

        Args:
            pareto_front: The Pareto front
            reference_point: Reference point for hypervolume calculation

        Returns:
            Hypervolume value
        """
        pareto_points = pareto_front.get_pareto_points()
        if len(pareto_points) == 0:
            return 0.0

        # Get normalized objectives
        objectives = np.array([p.objectives for p in pareto_points]) * self.signs

        # Default reference point: slightly worse than worst point in each dimension
        if reference_point is None:
            reference_point = np.min(objectives, axis=0) - 1.0

        # Simple 2D hypervolume calculation
        if objectives.shape[1] == 2:
            return self._hypervolume_2d(objectives, reference_point)

        # For higher dimensions, use approximation
        return self._hypervolume_monte_carlo(objectives, reference_point)

    def _hypervolume_2d(
        self,
        points: np.ndarray,
        reference: np.ndarray,
    ) -> float:
        """Calculate exact hypervolume for 2D case."""
        # Sort by first objective
        sorted_indices = np.argsort(points[:, 0])
        sorted_points = points[sorted_indices]

        hypervolume = 0.0
        prev_x = reference[0]

        for point in sorted_points:
            if point[0] > reference[0] and point[1] > reference[1]:
                width = point[0] - prev_x
                height = point[1] - reference[1]
                hypervolume += width * height
                prev_x = point[0]

        return hypervolume

    def _hypervolume_monte_carlo(
        self,
        points: np.ndarray,
        reference: np.ndarray,
        n_samples: int = 10000,
    ) -> float:
        """Approximate hypervolume using Monte Carlo sampling."""
        # Find bounding box
        upper = np.max(points, axis=0)

        # Calculate bounding box volume
        box_volume = np.prod(upper - reference)

        if box_volume <= 0:
            return 0.0

        # Sample random points
        np.random.seed(42)
        samples = np.random.uniform(reference, upper, (n_samples, len(reference)))

        # Count dominated samples
        dominated = 0
        for sample in samples:
            for point in points:
                if np.all(point >= sample):
                    dominated += 1
                    break

        return box_volume * dominated / n_samples


def find_knee_point(pareto_front: ParetoFront) -> ParetoPoint | None:
    """
    Find the knee point of the Pareto front.

    The knee point is the point with maximum distance to the line
    connecting the extreme points.

    Args:
        pareto_front: The Pareto front

    Returns:
        The knee point, or None if front has < 3 points
    """
    pareto_points = pareto_front.get_pareto_points()
    if len(pareto_points) < 3:
        return pareto_points[0] if pareto_points else None

    objectives = np.array([p.objectives for p in pareto_points])

    # Find extreme points
    extreme_indices = []
    for i in range(objectives.shape[1]):
        extreme_indices.append(np.argmax(objectives[:, i]))
        extreme_indices.append(np.argmin(objectives[:, i]))
    extreme_indices = list(set(extreme_indices))

    if len(extreme_indices) < 2:
        return pareto_points[0]

    # For 2D: find point with max perpendicular distance to line
    if objectives.shape[1] == 2:
        # Line from min to max of first objective
        p1 = objectives[np.argmin(objectives[:, 0])]
        p2 = objectives[np.argmax(objectives[:, 0])]

        # Calculate perpendicular distance for each point
        line_vec = p2 - p1
        line_len = np.linalg.norm(line_vec)

        if line_len == 0:
            return pareto_points[0]

        max_dist = -1
        knee_idx = 0

        for i, point in enumerate(objectives):
            # Distance to line
            t = np.dot(point - p1, line_vec) / (line_len**2)
            proj = p1 + t * line_vec
            dist = np.linalg.norm(point - proj)

            if dist > max_dist:
                max_dist = dist
                knee_idx = i

        return pareto_points[knee_idx]

    # For higher dimensions, use point with maximum sum of normalized objectives
    normalized = (objectives - objectives.min(axis=0)) / (
        objectives.max(axis=0) - objectives.min(axis=0) + 1e-10
    )
    scores = np.sum(normalized, axis=1)
    return pareto_points[np.argmax(scores)]
