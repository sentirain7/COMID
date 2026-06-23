"""Trajectory-based metric calculation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.schemas import MetricResult
from metrics.rdf_pairtype import PairTypeRDFCalculator

logger = get_logger("metrics.trajectory_metrics")

if TYPE_CHECKING:
    import numpy as np

    from metrics.array_storage import ArrayStorage
    from metrics.msd import MSDCalculator
    from metrics.rdf import RDFCalculator
    from parsers.dump_parser import DumpParser


def calculate_rdf_metrics(
    *,
    dump_files: list[str],
    exp_id: str | None,
    dump_parser: DumpParser,
    rdf_calc: RDFCalculator,
    array_storage: ArrayStorage | None,
) -> list[MetricResult]:
    """Calculate RDF metrics from trajectory dumps."""
    from pathlib import Path as _Path

    positions: list[np.ndarray] = []
    box_dims: list[tuple[float, float, float]] = []

    for dump_path in dump_files:
        p = _Path(dump_path)
        if not p.exists():
            continue
        for frame in dump_parser.parse_frames(p):
            pos = dump_parser.get_positions_array(frame)
            box = dump_parser.get_box_dimensions(frame)
            positions.append(pos)
            box_dims.append(box)

    if not positions:
        return []

    # Calculate frame counts for provenance tracking (v00.97.00)
    frames_total = len(positions)
    skip_fraction = getattr(rdf_calc, "skip_fraction", 0.3)
    frames_skipped = int(frames_total * skip_fraction)
    frames_used = max(1, frames_total - frames_skipped)

    result = rdf_calc.compute(positions, box_dims)
    metrics = list(rdf_calc.create_scalar_metrics(result))

    if array_storage is not None and exp_id is not None:
        try:
            data = {
                "r": result.r.tolist(),
                "g_r": result.g_r.tolist(),
            }
            summary: dict[str, float] = {}
            if result.first_peak_r is not None:
                summary["first_peak_r"] = result.first_peak_r
            if result.first_peak_g is not None:
                summary["first_peak_g"] = result.first_peak_g
            if result.coordination_number is not None:
                summary["coordination_number"] = result.coordination_number

            arr_storage = array_storage.store_metric(
                metric_name="rdf_curve",
                experiment_id=exp_id,
                data=data,
                summary=summary,
            )
            # Pass frame counts for provenance tracking
            array_metric = rdf_calc.create_array_metric(
                result,
                arr_storage,
                frames_total=frames_total,
                frames_used=frames_used,
            )
            metrics.append(array_metric)
        except Exception as e:
            logger.warning(f"RDF array storage failed: {e}")

    return metrics


def calculate_msd_metrics(
    *,
    dump_files: list[str],
    exp_id: str | None,
    dt_fs: float,
    dump_parser: DumpParser,
    msd_calc: MSDCalculator,
    array_storage: ArrayStorage | None,
) -> list[MetricResult]:
    """Calculate MSD metrics from trajectory dumps."""
    positions: list[np.ndarray] = []
    timesteps: list[int] = []
    used_unwrapped: bool | None = None

    for dump_path in dump_files:
        p = Path(dump_path)
        if not p.exists():
            continue
        for frame in dump_parser.parse_frames(p):
            pos, unwrapped = dump_parser.get_sorted_positions(
                frame,
                prefer_unwrapped=True,
            )
            positions.append(pos)
            timesteps.append(frame.timestep)
            if used_unwrapped is None:
                used_unwrapped = unwrapped

    if len(positions) < 2:
        return []

    result = msd_calc.compute(
        positions_per_frame=positions,
        timesteps=timesteps,
        dt_fs=dt_fs,
        used_unwrapped=used_unwrapped if used_unwrapped is not None else False,
    )

    metrics: list[MetricResult] = []
    scalar_metric = msd_calc.create_scalar_metric(result)
    if scalar_metric is not None:
        metrics.append(scalar_metric)

    if array_storage is not None and exp_id is not None and len(result.time_ps) > 0:
        try:
            data = {
                "time_ps": result.time_ps.tolist(),
                "msd": result.msd.tolist(),
            }
            summary: dict[str, float] = {}
            if result.diffusion_coefficient is not None:
                summary["diffusion_coefficient_cm2s"] = result.diffusion_coefficient
            if result.fit_r_squared is not None:
                summary["fit_r_squared"] = result.fit_r_squared

            arr_storage = array_storage.store_metric(
                metric_name="msd_curve",
                experiment_id=exp_id,
                data=data,
                summary=summary,
            )
            array_metric = msd_calc.create_array_metric(result, arr_storage)
            metrics.append(array_metric)
        except Exception as e:
            logger.warning(f"MSD array storage failed: {e}")

    return metrics


def calculate_pair_rdf_metrics(
    *,
    dump_files: list[str],
    group_assignments: dict[str, list[int]],
    exp_id: str | None,
    dump_parser: DumpParser,
    pair_rdf_calc: PairTypeRDFCalculator,
    array_storage: ArrayStorage | None,
) -> list[MetricResult]:
    """Calculate pair-type RDF metrics from trajectory dumps."""
    positions: list[np.ndarray] = []
    box_dims: list[tuple[float, float, float]] = []

    for dump_path in dump_files:
        p = Path(dump_path)
        if not p.exists():
            continue
        for frame in dump_parser.parse_frames(p):
            pos = dump_parser.get_positions_array(frame)
            box = dump_parser.get_box_dimensions(frame)
            positions.append(pos)
            box_dims.append(box)

    if not positions or len(group_assignments) < 2:
        return []

    # Calculate frame counts for provenance tracking (v00.97.00)
    frames_total = len(positions)
    skip_fraction = getattr(pair_rdf_calc, "skip_fraction", 0.3)
    frames_skipped = int(frames_total * skip_fraction)
    frames_used = max(1, frames_total - frames_skipped)

    result = pair_rdf_calc.compute(positions, box_dims, group_assignments)
    metrics: list[MetricResult] = []

    if array_storage is not None and exp_id is not None and result.curves:
        try:
            data = PairTypeRDFCalculator.prepare_storage_data(result)
            arr_storage = array_storage.store_metric(
                metric_name="rdf_pair_curve",
                experiment_id=exp_id,
                data=data,
                summary={},
            )
            # Pass frame counts for provenance tracking
            array_metric = pair_rdf_calc.create_array_metric(
                result,
                arr_storage,
                frames_total=frames_total,
                frames_used=frames_used,
            )
            metrics.append(array_metric)
        except Exception as e:
            logger.warning(f"Pair RDF array storage failed: {e}")

    return metrics
