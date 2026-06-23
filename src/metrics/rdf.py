"""
Radial Distribution Function (RDF) calculator.

Computes g(r) from atomic coordinates with periodic boundary conditions,
extracts peak positions and coordination numbers, and stores both
scalar summaries and the full RDF curve as array metrics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from common.logging import get_logger
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import ArrayMetricStorage, MetricResult

logger = get_logger("metrics.rdf")

# Physical constants
_FOUR_THIRDS_PI = 4.0 / 3.0 * math.pi


@dataclass
class RDFResult:
    """Result from RDF calculation."""

    r: np.ndarray  # bin centers (Angstrom)
    g_r: np.ndarray  # g(r) values
    first_peak_r: float | None  # first peak position (Angstrom)
    first_peak_g: float | None  # first peak height
    second_peak_r: float | None  # second peak position (Angstrom)
    second_peak_g: float | None  # second peak height
    coordination_number: float | None  # integral to first minimum


class RDFCalculator:
    """Calculator for radial distribution function g(r).

    Uses a histogram approach over multiple trajectory frames
    with periodic-image-aware minimum-image convention.

    Args:
        r_max: Maximum distance for g(r) in Angstrom.
        n_bins: Number of histogram bins.
        skip_fraction: Fraction of frames to skip from the start
                       (equilibration).
        registry: MetricsRegistry for SSOT name/unit validation.
    """

    def __init__(
        self,
        r_max: float = 15.0,
        n_bins: int = 300,
        skip_fraction: float = 0.3,  # v00.97.00: reduced from 0.5 to use more frames
        registry: MetricsRegistry | None = None,
    ) -> None:
        self.r_max = r_max
        self.n_bins = n_bins
        self.skip_fraction = skip_fraction
        self.registry = registry or MetricsRegistry()

        self.dr = r_max / n_bins
        # Bin edges and centers
        self.edges = np.linspace(0.0, r_max, n_bins + 1)
        self.centers = 0.5 * (self.edges[:-1] + self.edges[1:])

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(
        self,
        positions_per_frame: list[np.ndarray],
        box_dims_per_frame: list[tuple[float, float, float]],
    ) -> RDFResult:
        """Compute RDF averaged over multiple frames.

        Args:
            positions_per_frame: List of (N, 3) arrays per frame.
            box_dims_per_frame: (Lx, Ly, Lz) per frame.

        Returns:
            RDFResult with g(r), peak info, and coordination number.
        """
        n_frames = len(positions_per_frame)
        if n_frames == 0:
            return self._empty_result()

        start = int(n_frames * self.skip_fraction)
        if start >= n_frames:
            start = max(0, n_frames - 1)

        histogram = np.zeros(self.n_bins, dtype=np.float64)
        n_counted = 0

        for idx in range(start, n_frames):
            pos = positions_per_frame[idx]
            box = box_dims_per_frame[idx]
            n_atoms = len(pos)
            if n_atoms < 2:
                continue

            hist_frame = self._histogram_frame(pos, box)
            histogram += hist_frame
            n_counted += 1

        if n_counted == 0:
            return self._empty_result()

        # Average the histogram
        histogram /= n_counted

        # Normalise to g(r)
        n_atoms = len(positions_per_frame[start])
        avg_box = np.mean([box_dims_per_frame[i] for i in range(start, n_frames)], axis=0)
        volume = float(avg_box[0] * avg_box[1] * avg_box[2])
        rho = n_atoms / volume  # number density

        g_r = np.zeros(self.n_bins, dtype=np.float64)
        for i in range(self.n_bins):
            r_inner = self.edges[i]
            r_outer = self.edges[i + 1]
            shell_vol = _FOUR_THIRDS_PI * (r_outer**3 - r_inner**3)
            ideal_count = rho * shell_vol
            if ideal_count > 0 and n_atoms > 1:
                g_r[i] = histogram[i] / (n_atoms * ideal_count)

        # Extract peaks and coordination
        first_peak_r, first_peak_g = self._find_peak(g_r, start_bin=1)
        second_peak_r, second_peak_g = self._find_second_peak(g_r, first_peak_r)
        coordination = self._coordination_number(g_r, rho, first_peak_r)

        return RDFResult(
            r=self.centers.copy(),
            g_r=g_r,
            first_peak_r=first_peak_r,
            first_peak_g=first_peak_g,
            second_peak_r=second_peak_r,
            second_peak_g=second_peak_g,
            coordination_number=coordination,
        )

    # ------------------------------------------------------------------
    # Per-frame histogram (minimum-image convention)
    # ------------------------------------------------------------------

    def _histogram_frame(
        self,
        pos: np.ndarray,
        box: tuple[float, float, float],
    ) -> np.ndarray:
        """Build pair-distance histogram for one frame.

        Uses numpy broadcasting for efficiency.
        """
        box_arr = np.array(box, dtype=np.float64)

        n = len(pos)
        hist = np.zeros(self.n_bins, dtype=np.float64)

        # Process in blocks to limit memory for large systems
        block_size = min(n, 500)
        for i_start in range(0, n, block_size):
            i_end = min(i_start + block_size, n)
            # Compute distances from block to all atoms j > i
            for i in range(i_start, i_end):
                # Only count pairs (i, j) with j > i to avoid double-counting
                if i + 1 >= n:
                    continue
                delta = pos[i + 1 :] - pos[i]
                # Minimum image
                delta -= box_arr * np.round(delta / box_arr)
                dist = np.sqrt(np.sum(delta**2, axis=1))
                # Histogram
                mask = dist < self.r_max
                bins = (dist[mask] / self.dr).astype(np.intp)
                bins = np.clip(bins, 0, self.n_bins - 1)
                np.add.at(hist, bins, 1.0)

        # Factor of 2 because we only counted i < j
        hist *= 2.0
        return hist

    # ------------------------------------------------------------------
    # Peak detection
    # ------------------------------------------------------------------

    def _find_peak(
        self,
        g_r: np.ndarray,
        start_bin: int = 1,
    ) -> tuple[float | None, float | None]:
        """Find the first peak in g(r)."""
        if len(g_r) <= start_bin:
            return None, None

        # Find local maximum (g(r) > 1.0 threshold to skip noise)
        for i in range(start_bin + 1, len(g_r) - 1):
            if g_r[i] > g_r[i - 1] and g_r[i] >= g_r[i + 1] and g_r[i] > 1.0:
                return float(self.centers[i]), float(g_r[i])

        # Fallback: global max above threshold
        peak_idx = np.argmax(g_r[start_bin:]) + start_bin
        if g_r[peak_idx] > 1.0:
            return float(self.centers[peak_idx]), float(g_r[peak_idx])

        return None, None

    def _find_second_peak(
        self,
        g_r: np.ndarray,
        first_peak_r: float | None,
    ) -> tuple[float | None, float | None]:
        """Find the second peak after the first minimum."""
        if first_peak_r is None:
            return None, None

        # Find first minimum after the first peak
        first_peak_bin = int(first_peak_r / self.dr)
        min_bin = None
        for i in range(first_peak_bin + 1, len(g_r) - 1):
            if g_r[i] <= g_r[i - 1] and g_r[i] <= g_r[i + 1]:
                min_bin = i
                break

        if min_bin is None:
            return None, None

        # Find peak after the minimum
        for i in range(min_bin + 1, len(g_r) - 1):
            if g_r[i] > g_r[i - 1] and g_r[i] >= g_r[i + 1] and g_r[i] > 1.0:
                return float(self.centers[i]), float(g_r[i])

        return None, None

    # ------------------------------------------------------------------
    # Coordination number
    # ------------------------------------------------------------------

    def _coordination_number(
        self,
        g_r: np.ndarray,
        rho: float,
        first_peak_r: float | None,
    ) -> float | None:
        """Integrate g(r) up to first minimum to get coordination number.

        CN = 4*pi*rho * integral_0^r_min { r^2 * g(r) dr }
        """
        if first_peak_r is None or rho <= 0:
            return None

        # Find first minimum after the first peak
        first_peak_bin = int(first_peak_r / self.dr)
        r_min_bin = None
        for i in range(first_peak_bin + 1, len(g_r) - 1):
            if g_r[i] <= g_r[i - 1] and g_r[i] <= g_r[i + 1]:
                r_min_bin = i
                break

        if r_min_bin is None:
            r_min_bin = min(first_peak_bin + 10, len(g_r) - 1)

        # Numerical integration (trapezoidal)
        cn = 0.0
        for i in range(r_min_bin + 1):
            r = self.centers[i]
            cn += 4.0 * math.pi * rho * r * r * g_r[i] * self.dr

        return float(cn)

    # ------------------------------------------------------------------
    # Metric creation
    # ------------------------------------------------------------------

    # Mapping from metric name to RDFResult attribute
    _SCALAR_METRIC_MAP: list[tuple[str, str]] = [
        ("rdf_first_peak_r", "first_peak_r"),
        ("rdf_first_peak_g", "first_peak_g"),
        ("rdf_coordination_number", "coordination_number"),
        ("rdf_second_peak_r", "second_peak_r"),
        ("rdf_second_peak_g", "second_peak_g"),
    ]

    def create_scalar_metrics(
        self,
        result: RDFResult,
        namespace: str = "bulk_ff_gaff2",
    ) -> list[MetricResult]:
        """Create scalar MetricResult objects from RDFResult.

        Metric names and units are sourced from the MetricsRegistry (SSOT).

        Args:
            result: RDF calculation result.
            namespace: Metric namespace.

        Returns:
            List of scalar MetricResult objects.
        """
        metrics: list[MetricResult] = []

        for metric_name, attr_name in self._SCALAR_METRIC_MAP:
            value = getattr(result, attr_name)
            if value is None:
                continue

            # Validate name exists in registry and pull canonical unit
            is_valid, error = self.registry.validate_metric(
                name=metric_name,
                unit=self.registry.get_unit(metric_name),
                namespace=namespace,
            )
            if not is_valid:
                logger.warning(f"Registry validation failed for {metric_name}: {error}")
                continue

            metrics.append(
                MetricResult(
                    metric_name=metric_name,
                    value=value,
                    unit=self.registry.get_unit(metric_name),
                    namespace=namespace,
                )
            )

        return metrics

    _ARRAY_METRIC_NAME = "rdf_curve"

    def create_array_metric(
        self,
        result: RDFResult,
        array_storage: ArrayMetricStorage,
        namespace: str = "bulk_ff_gaff2",
        frames_total: int | None = None,
        frames_used: int | None = None,
    ) -> MetricResult:
        """Create array MetricResult for the RDF curve.

        Metric name and unit are sourced from the MetricsRegistry (SSOT).

        Args:
            result: RDF calculation result.
            array_storage: Storage info from ArrayStorage.store_metric().
            namespace: Metric namespace.
            frames_total: Total number of frames in trajectory.
            frames_used: Number of frames actually used for RDF calculation.

        Returns:
            MetricResult for rdf_curve.
        """
        from typing import Any

        summary: dict[str, Any] = {}
        if result.first_peak_r is not None:
            summary["first_peak_r"] = result.first_peak_r
        if result.first_peak_g is not None:
            summary["first_peak_g"] = result.first_peak_g
        if result.coordination_number is not None:
            summary["coordination_number"] = result.coordination_number

        # Add provenance metadata for reproducibility tracking (v00.97.00)
        frames_skipped = None
        if frames_total is not None and frames_used is not None:
            frames_skipped = frames_total - frames_used

        summary["provenance"] = {
            "skip_fraction": self.skip_fraction,
            "computation_version": "rdf_v1.1",
            "r_max": self.r_max,
            "n_bins": self.n_bins,
            "frames_total": frames_total,
            "frames_used": frames_used,
            "frames_skipped": frames_skipped,
        }

        return MetricResult(
            metric_name=self._ARRAY_METRIC_NAME,
            value=None,
            unit=self.registry.get_unit(self._ARRAY_METRIC_NAME),
            namespace=namespace,
            array_storage=array_storage,
            array_summary=summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _empty_result(self) -> RDFResult:
        return RDFResult(
            r=self.centers.copy(),
            g_r=np.zeros(self.n_bins, dtype=np.float64),
            first_peak_r=None,
            first_peak_g=None,
            second_peak_r=None,
            second_peak_g=None,
            coordination_number=None,
        )
