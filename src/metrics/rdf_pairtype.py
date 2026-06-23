"""
Pair-type Radial Distribution Function (RDF) calculator.

Computes g(r) between specific molecular groups (e.g., SARA pairs),
extending the all-all RDF in rdf.py with atom-type -> group mapping.

Reference: Yao et al. (2016) — pair-type g(r) for selective binding
identification in asphalt binder systems.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from common.logging import get_logger
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import ArrayMetricStorage, MetricResult

logger = get_logger("metrics.rdf_pairtype")

_FOUR_THIRDS_PI = 4.0 / 3.0 * math.pi


@dataclass
class PairRDFCurve:
    """RDF curve for a single pair of groups."""

    pair_label: str
    r: np.ndarray
    g_r: np.ndarray
    first_peak_r: float | None = None
    first_peak_g: float | None = None
    coordination_number: float | None = None


@dataclass
class PairTypeRDFResult:
    """Result from pair-type RDF calculation."""

    curves: list[PairRDFCurve] = field(default_factory=list)


class PairTypeRDFCalculator:
    """Calculator for pair-type RDF between molecular groups.

    Computes g_AB(r) for each pair of groups (A, B) using atom
    membership assignments. Ensures symmetry: g_AB(r) == g_BA(r).

    Args:
        r_max: Maximum distance for g(r) in Angstrom.
        n_bins: Number of histogram bins.
        skip_fraction: Fraction of frames to skip (equilibration).
        registry: MetricsRegistry for SSOT validation.
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
        self.edges = np.linspace(0.0, r_max, n_bins + 1)
        self.centers = 0.5 * (self.edges[:-1] + self.edges[1:])

    def compute(
        self,
        positions_per_frame: list[np.ndarray],
        box_dims_per_frame: list[tuple[float, float, float]],
        group_assignments: dict[str, list[int]],
    ) -> PairTypeRDFResult:
        """Compute pair-type RDF for all group combinations.

        Args:
            positions_per_frame: List of (N, 3) position arrays per frame.
            box_dims_per_frame: (Lx, Ly, Lz) per frame.
            group_assignments: {group_name: [atom_indices]} mapping.
                              Indices are 0-based into the positions array.

        Returns:
            PairTypeRDFResult with curves for each unique pair.
        """
        n_frames = len(positions_per_frame)
        if n_frames == 0 or len(group_assignments) < 2:
            return PairTypeRDFResult()

        start = int(n_frames * self.skip_fraction)
        if start >= n_frames:
            start = max(0, n_frames - 1)

        group_names = sorted(group_assignments.keys())
        # Generate unique pairs (including self-pairs A-A)
        pairs: list[tuple[str, str]] = []
        for i, name_a in enumerate(group_names):
            for name_b in group_names[i:]:
                pairs.append((name_a, name_b))

        # Accumulate histograms per pair
        histograms: dict[str, np.ndarray] = {}
        for name_a, name_b in pairs:
            label = f"{name_a}_{name_b}"
            histograms[label] = np.zeros(self.n_bins, dtype=np.float64)

        n_counted = 0

        for idx in range(start, n_frames):
            pos = positions_per_frame[idx]
            box = np.array(box_dims_per_frame[idx], dtype=np.float64)
            if len(pos) < 2:
                continue

            for name_a, name_b in pairs:
                label = f"{name_a}_{name_b}"
                indices_a = group_assignments[name_a]
                indices_b = group_assignments[name_b]

                hist = self._histogram_pair(
                    pos, box, indices_a, indices_b, same_group=(name_a == name_b)
                )
                histograms[label] += hist

            n_counted += 1

        if n_counted == 0:
            return PairTypeRDFResult()

        # Normalize to g(r)
        avg_box = np.mean(
            [box_dims_per_frame[i] for i in range(start, n_frames)],
            axis=0,
        )
        volume = float(avg_box[0] * avg_box[1] * avg_box[2])

        curves: list[PairRDFCurve] = []
        for name_a, name_b in pairs:
            label = f"{name_a}_{name_b}"
            hist = histograms[label] / n_counted

            n_a = len(group_assignments[name_a])
            n_b = len(group_assignments[name_b])

            if n_a == 0 or n_b == 0 or volume <= 0:
                continue

            # Number density of type B
            rho_b = n_b / volume

            g_r = np.zeros(self.n_bins, dtype=np.float64)
            for i in range(self.n_bins):
                r_inner = self.edges[i]
                r_outer = self.edges[i + 1]
                shell_vol = _FOUR_THIRDS_PI * (r_outer**3 - r_inner**3)
                ideal = rho_b * shell_vol
                if ideal > 0 and n_a > 0:
                    g_r[i] = hist[i] / (n_a * ideal)

            peak_r, peak_g = self._find_peak(g_r)
            coord = self._coordination_number(g_r, rho_b, peak_r)

            curves.append(
                PairRDFCurve(
                    pair_label=label,
                    r=self.centers.copy(),
                    g_r=g_r,
                    first_peak_r=peak_r,
                    first_peak_g=peak_g,
                    coordination_number=coord,
                )
            )

        return PairTypeRDFResult(curves=curves)

    # ------------------------------------------------------------------
    # Per-frame histogram for a pair of groups
    # ------------------------------------------------------------------

    def _histogram_pair(
        self,
        pos: np.ndarray,
        box: np.ndarray,
        indices_a: list[int],
        indices_b: list[int],
        same_group: bool = False,
    ) -> np.ndarray:
        """Build pair-distance histogram between two groups.

        Args:
            pos: (N, 3) positions array.
            box: (3,) box dimensions.
            indices_a: Atom indices for group A.
            indices_b: Atom indices for group B.
            same_group: If True, avoid double-counting i-j and j-i.

        Returns:
            Histogram array of pair counts.
        """
        hist = np.zeros(self.n_bins, dtype=np.float64)
        pos_a = pos[indices_a]

        if same_group:
            # Self-pair: count each unique pair once, multiply by 2
            n = len(indices_a)
            for i in range(n):
                if i + 1 >= n:
                    continue
                delta = pos_a[i + 1 :] - pos_a[i]
                delta -= box * np.round(delta / box)
                dist = np.sqrt(np.sum(delta**2, axis=1))
                mask = dist < self.r_max
                bins = (dist[mask] / self.dr).astype(np.intp)
                bins = np.clip(bins, 0, self.n_bins - 1)
                np.add.at(hist, bins, 1.0)
            hist *= 2.0
        else:
            # Cross-pair: count all (i in A, j in B)
            pos_b = pos[indices_b]
            for i in range(len(pos_a)):
                delta = pos_b - pos_a[i]
                delta -= box * np.round(delta / box)
                dist = np.sqrt(np.sum(delta**2, axis=1))
                mask = dist < self.r_max
                bins = (dist[mask] / self.dr).astype(np.intp)
                bins = np.clip(bins, 0, self.n_bins - 1)
                np.add.at(hist, bins, 1.0)

        return hist

    # ------------------------------------------------------------------
    # Peak detection (reuses logic from rdf.py pattern)
    # ------------------------------------------------------------------

    def _find_peak(
        self,
        g_r: np.ndarray,
        start_bin: int = 1,
    ) -> tuple[float | None, float | None]:
        """Find the first peak in g(r)."""
        if len(g_r) <= start_bin:
            return None, None

        for i in range(start_bin + 1, len(g_r) - 1):
            if g_r[i] > g_r[i - 1] and g_r[i] >= g_r[i + 1] and g_r[i] > 1.0:
                return float(self.centers[i]), float(g_r[i])

        peak_idx = np.argmax(g_r[start_bin:]) + start_bin
        if g_r[peak_idx] > 1.0:
            return float(self.centers[peak_idx]), float(g_r[peak_idx])

        return None, None

    def _coordination_number(
        self,
        g_r: np.ndarray,
        rho: float,
        first_peak_r: float | None,
    ) -> float | None:
        """Integrate g(r) up to first minimum for coordination number."""
        if first_peak_r is None or rho <= 0:
            return None

        first_peak_bin = int(first_peak_r / self.dr)
        r_min_bin = None
        for i in range(first_peak_bin + 1, len(g_r) - 1):
            if g_r[i] <= g_r[i - 1] and g_r[i] <= g_r[i + 1]:
                r_min_bin = i
                break

        if r_min_bin is None:
            r_min_bin = min(first_peak_bin + 10, len(g_r) - 1)

        cn = 0.0
        for i in range(r_min_bin + 1):
            r = self.centers[i]
            cn += 4.0 * math.pi * rho * r * r * g_r[i] * self.dr

        return float(cn)

    # ------------------------------------------------------------------
    # Metric creation
    # ------------------------------------------------------------------

    def create_array_metric(
        self,
        result: PairTypeRDFResult,
        array_storage: ArrayMetricStorage,
        namespace: str = "bulk_ff_gaff2",
        frames_total: int | None = None,
        frames_used: int | None = None,
    ) -> MetricResult:
        """Create array MetricResult for pair-type RDF curves.

        Args:
            result: Pair-type RDF result.
            array_storage: Storage info from ArrayStorage.store_metric().
            namespace: Metric namespace.
            frames_total: Total number of frames in trajectory.
            frames_used: Number of frames actually used for RDF calculation.

        Returns:
            MetricResult for rdf_pair_curve.
        """
        from typing import Any

        summary: dict[str, Any] = {}
        for curve in result.curves:
            if curve.first_peak_r is not None:
                summary[f"{curve.pair_label}_peak_r"] = curve.first_peak_r
            if curve.first_peak_g is not None:
                summary[f"{curve.pair_label}_peak_g"] = curve.first_peak_g

        # Add provenance metadata for reproducibility tracking (v00.97.00)
        frames_skipped = None
        if frames_total is not None and frames_used is not None:
            frames_skipped = frames_total - frames_used

        summary["provenance"] = {
            "skip_fraction": self.skip_fraction,
            "computation_version": "rdf_pairtype_v1.1",
            "r_max": self.r_max,
            "n_bins": self.n_bins,
            "frames_total": frames_total,
            "frames_used": frames_used,
            "frames_skipped": frames_skipped,
        }

        return MetricResult(
            metric_name="rdf_pair_curve",
            value=None,
            unit=self.registry.get_unit("rdf_pair_curve"),
            namespace=namespace,
            array_storage=array_storage,
            array_summary=summary,
        )

    @staticmethod
    def prepare_storage_data(result: PairTypeRDFResult) -> dict[str, list[float | str]]:
        """Prepare data dict for ArrayStorage.store_metric().

        Concatenates all pair curves into a single table with pair_label column.

        Args:
            result: Pair-type RDF result.

        Returns:
            Dict with 'r', 'g_r', 'pair_label' columns.
        """
        all_r: list[float | str] = []
        all_g_r: list[float | str] = []
        all_labels: list[float | str] = []

        for curve in result.curves:
            r_list = curve.r.tolist()
            g_list = curve.g_r.tolist()
            all_r.extend(r_list)
            all_g_r.extend(g_list)
            all_labels.extend([curve.pair_label] * len(r_list))

        return {"r": all_r, "g_r": all_g_r, "pair_label": all_labels}
