"""Analysis service."""

from __future__ import annotations

import functools
from collections import defaultdict

import numpy as np
from sqlalchemy import and_, select

from common.logging import get_logger
from common.pathing import BINDER_ABBREV_REVERSE, parse_exp_id
from contracts.policies.ghg import GHGPolicy
from database.models import (
    ExperimentModel,
    ExperimentMoleculeModel,
    MetricModel,
    MoleculeModel,
)
from features.common import run_in_session
from features.metrics.analytics import _build_additive_name_map

logger = get_logger("features.analysis")

_XY_GROUP_KEYS = {"binder", "size", "aging", "additive"}


def _group_sort_key(group_by: str, label: str) -> tuple[int, str]:
    from features.common.canonical_ordering import group_sort_key

    return group_sort_key(group_by, label)


@functools.lru_cache(maxsize=1)
def _get_ghg_policy() -> GHGPolicy:
    from common.library_config import load_ghg_inventory

    cfg = load_ghg_inventory()
    return GHGPolicy(
        binder_molecules=cfg.get("binder_molecules", {}),
        sara_fallback=cfg.get("sara_fallback", {}),
        additives=cfg.get("additives", {}),
        default_binder_ef=cfg.get("defaults", {}).get("binder", 0.50),
        default_additive_ef=cfg.get("defaults", {}).get("additive", 0.0),
        version=cfg.get("version", "1.0"),
    )


async def get_analysis_embedding(ff_type: str = "bulk_ff_gaff2") -> list[dict]:
    points = []
    try:

        def _collect(session):
            nonlocal points
            stmt = (
                select(
                    ExperimentModel.exp_id,
                    ExperimentModel.temperature_K,
                    ExperimentModel.additive_type,
                    ExperimentModel.additive_mol_id,
                    ExperimentModel.additive_wt,
                    ExperimentModel.comp_saturate_wt,
                    ExperimentModel.comp_aromatic_wt,
                    ExperimentModel.comp_resin_wt,
                    ExperimentModel.comp_asphaltene_wt,
                    MetricModel.metric_name,
                    MetricModel.value,
                )
                .join(
                    MetricModel,
                    and_(
                        MetricModel.exp_id == ExperimentModel.exp_id,
                        MetricModel.metric_name.in_(["density", "cohesive_energy_density"]),
                    ),
                )
                .where(
                    ExperimentModel.status == "completed",
                    ExperimentModel.ff_type == ff_type,
                )
                .order_by(ExperimentModel.created_at.desc())
                .limit(2000)
            )
            rows = session.execute(stmt).all()
            if len(rows) == 0:
                points = []
                return

            by_exp: dict[str, dict] = {}
            for row in rows:
                exp_id = str(row.exp_id)
                payload = by_exp.get(exp_id)
                if payload is None:
                    payload = {
                        "exp_id": exp_id,
                        "temperature_k": float(row.temperature_K or 0.0),
                        "additive_type": row.additive_type,
                        "additive_mol_id": row.additive_mol_id,
                        "additive_wt": float(row.additive_wt or 0.0),
                        "comp_saturate_wt": float(row.comp_saturate_wt or 0.0),
                        "comp_aromatic_wt": float(row.comp_aromatic_wt or 0.0),
                        "comp_resin_wt": float(row.comp_resin_wt or 0.0),
                        "comp_asphaltene_wt": float(row.comp_asphaltene_wt or 0.0),
                        "density": None,
                        "ced": None,
                    }
                    by_exp[exp_id] = payload

                metric_name = str(row.metric_name)
                if metric_name == "density":
                    payload["density"] = float(row.value)
                elif metric_name == "cohesive_energy_density":
                    payload["ced"] = float(row.value)

            name_map = _build_additive_name_map(session)

            raw_points: list[dict] = []
            for exp in by_exp.values():
                if exp["density"] is None or exp["ced"] is None:
                    continue
                parsed = parse_exp_id(str(exp["exp_id"]))
                binder_abbrev = str(parsed.get("binder_type") or "").strip()
                binder_type = BINDER_ABBREV_REVERSE.get(binder_abbrev, binder_abbrev or "unknown")
                raw_mol_id = (
                    str(
                        exp["additive_mol_id"]
                        or exp["additive_type"]
                        or parsed.get("additive")
                        or "none"
                    )
                    .strip()
                    .replace("__none__", "none")
                )
                additive = name_map.get(raw_mol_id, raw_mol_id) if raw_mol_id != "none" else "none"

                sara_weights = {
                    "saturate": exp["comp_saturate_wt"],
                    "aromatic": exp["comp_aromatic_wt"],
                    "resin": exp["comp_resin_wt"],
                    "asphaltene": exp["comp_asphaltene_wt"],
                }
                dominant = max(sara_weights, key=sara_weights.get)

                aging_raw = str(parsed.get("aging_state") or "").strip()
                if not aging_raw:
                    aging_raw = "non_aging"
                raw_points.append(
                    {
                        "exp_id": exp["exp_id"],
                        "mol_id": exp["exp_id"],
                        "mol_name": exp["exp_id"],
                        "category": dominant,
                        "binder_type": binder_type,
                        "additive": additive,
                        "aging_state": aging_raw,
                        "additive_wt": exp["additive_wt"],
                        "temperature_k": exp["temperature_k"],
                        "density": float(exp["density"]),
                        "ced": float(exp["ced"]),
                        "experiment_count": 1,
                    }
                )

            if len(raw_points) == 0:
                points = []
                return

            temps = [p["temperature_k"] for p in raw_points]
            densities = [p["density"] for p in raw_points]
            ceds = [p["ced"] for p in raw_points]
            density_mean = float(np.mean(densities))
            ced_mean = float(np.mean(ceds))

            temp_min, temp_max = min(temps), max(temps)
            den_min, den_max = min(densities), max(densities)
            ced_min, ced_max = min(ceds), max(ceds)

            def _normalize(value: float, low: float, high: float, span: float = 10.0) -> float:
                if high <= low:
                    return 0.0
                ratio = (value - low) / (high - low)
                return (ratio - 0.5) * span

            for item in raw_points:
                item["position"] = [
                    _normalize(item["temperature_k"], temp_min, temp_max, 12.0),
                    _normalize(item["density"], den_min, den_max, 10.0),
                    _normalize(item["ced"], ced_min, ced_max, 12.0),
                ]
                item["metrics"] = {
                    "density_impact": item["density"] - density_mean,
                    "ced_impact": item["ced"] - ced_mean,
                }

            from features.common.canonical_ordering import stable_sort_records

            points = stable_sort_records(
                raw_points,
                ["binder_type", "aging_state", "additive", "additive_wt", "temperature_k"],
                exp_id_key="exp_id",
            )

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to generate embedding: {exc}")
        return []

    return points


async def get_binder_cell_xy_summary(
    *,
    group_by: str = "binder",
    ff_type: str = "bulk_ff_gaff2",
) -> dict:
    """Return grouped average XY box sizes and core metric overview for completed binder cells."""
    if group_by not in _XY_GROUP_KEYS:
        raise ValueError(
            f"Unsupported group_by '{group_by}'. Expected one of {sorted(_XY_GROUP_KEYS)}"
        )

    summary = {
        "group_by": group_by,
        "total_samples": 0,
        "overview": {
            "sample_count": 0,
            "avg_density": None,
            "avg_total_energy": None,
            "avg_potential_energy": None,
            "avg_kinetic_energy": None,
        },
        "items": [],
    }

    try:
        from features.experiments.query import _get_box_dims, _resolve_experiment_catalog_labels

        def _collect(session):
            nonlocal summary
            experiments = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.status == "completed")
                .filter(ExperimentModel.ff_type == ff_type)
                .order_by(ExperimentModel.created_at.desc())
                .all()
            )

            buckets: dict[str, dict[str, float | int | str]] = {}
            exp_ids: list[str] = []

            for exp in experiments:
                lx, ly, _ = _get_box_dims(exp)
                if lx is None or ly is None:
                    logger.debug("Analysis: skipping %s (box dims unavailable)", exp.exp_id)
                    continue

                labels = _resolve_experiment_catalog_labels(exp)
                group_label = {
                    "binder": labels["binder_code"],
                    "size": labels["structure_size"],
                    "aging": labels["aging_code"],
                    "additive": labels["additive_label"],
                }[group_by]
                if not group_label:
                    continue

                exp_ids.append(str(exp.exp_id))
                bucket = buckets.setdefault(
                    group_label,
                    {
                        "group_key": group_label,
                        "group_label": group_label,
                        "sample_count": 0,
                        "sum_lx": 0.0,
                        "sum_ly": 0.0,
                    },
                )
                bucket["sample_count"] = int(bucket["sample_count"]) + 1
                bucket["sum_lx"] = float(bucket["sum_lx"]) + float(lx)
                bucket["sum_ly"] = float(bucket["sum_ly"]) + float(ly)

            if not buckets:
                total_exp = len(experiments)
                logger.warning(
                    "XY summary empty: %d experiments queried, all filtered out "
                    "(check box_lx/box_ly and data_file_path)",
                    total_exp,
                )

            items = []
            for _label, bucket in sorted(
                buckets.items(), key=lambda item: _group_sort_key(group_by, item[0])
            ):
                sample_count = int(bucket["sample_count"])
                avg_lx = float(bucket["sum_lx"]) / sample_count
                avg_ly = float(bucket["sum_ly"]) / sample_count
                items.append(
                    {
                        "group_key": str(bucket["group_key"]),
                        "group_label": str(bucket["group_label"]),
                        "sample_count": sample_count,
                        "avg_lx": avg_lx,
                        "avg_ly": avg_ly,
                        "avg_xy": (avg_lx + avg_ly) * 0.5,
                    }
                )

            metric_means: dict[str, float | None] = {
                "avg_density": None,
                "avg_total_energy": None,
                "avg_potential_energy": None,
                "avg_kinetic_energy": None,
            }
            if exp_ids:
                metric_rows = (
                    session.query(MetricModel.exp_id, MetricModel.metric_name, MetricModel.value)
                    .filter(MetricModel.exp_id.in_(exp_ids))
                    .filter(
                        MetricModel.metric_name.in_(
                            ["density", "total_energy", "potential_energy", "kinetic_energy"]
                        )
                    )
                    .all()
                )
                metric_values: dict[str, list[float]] = defaultdict(list)
                metric_key_map = {
                    "density": "avg_density",
                    "total_energy": "avg_total_energy",
                    "potential_energy": "avg_potential_energy",
                    "kinetic_energy": "avg_kinetic_energy",
                }
                for row in metric_rows:
                    key = metric_key_map.get(str(row.metric_name))
                    if key is not None and row.value is not None:
                        metric_values[key].append(float(row.value))
                for key, values in metric_values.items():
                    if values:
                        metric_means[key] = float(np.mean(values))

            summary = {
                "group_by": group_by,
                "total_samples": len(exp_ids),
                "overview": {
                    "sample_count": len(exp_ids),
                    **metric_means,
                },
                "items": items,
            }

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to generate binder-cell XY summary: {exc}")
        return summary

    return summary


async def get_molecule_impact(ff_type: str = "bulk_ff_gaff2") -> dict:
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    result = {"rows": [], "columns": ["density", "ced", "viscosity"], "cells": []}

    try:

        def _collect(session):
            nonlocal result
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)

            all_exps = exp_repo.list_all(limit=1000)
            completed_exps = [
                e for e in all_exps if e.status == "completed" and e.ff_type == ff_type
            ]
            if len(completed_exps) < 3:
                return result

            all_metrics = {"density": [], "ced": [], "viscosity": []}
            sara_metrics = {
                cat: {"density": [], "ced": [], "viscosity": []}
                for cat in ["saturate", "aromatic", "resin", "asphaltene"]
            }

            for exp in completed_exps:
                density = metric_repo.get_by_name(exp.exp_id, "density")
                ced = metric_repo.get_by_name(exp.exp_id, "cohesive_energy_density")
                viscosity = metric_repo.get_by_name(exp.exp_id, "viscosity")

                sara_weights = {
                    "saturate": exp.comp_saturate_wt or 0,
                    "aromatic": exp.comp_aromatic_wt or 0,
                    "resin": exp.comp_resin_wt or 0,
                    "asphaltene": exp.comp_asphaltene_wt or 0,
                }
                dominant = max(sara_weights, key=sara_weights.get)

                if density:
                    all_metrics["density"].append(density.value)
                    sara_metrics[dominant]["density"].append(density.value)
                if ced:
                    all_metrics["ced"].append(ced.value)
                    sara_metrics[dominant]["ced"].append(ced.value)
                if viscosity:
                    all_metrics["viscosity"].append(viscosity.value)
                    sara_metrics[dominant]["viscosity"].append(viscosity.value)

            global_stats = {}
            for metric, values in all_metrics.items():
                if len(values) > 1:
                    global_stats[metric] = {"mean": np.mean(values), "std": np.std(values) or 1.0}

            for category in ["saturate", "aromatic", "resin", "asphaltene"]:
                result["rows"].append(category)
                for metric in result["columns"]:
                    values = sara_metrics[category][metric]
                    if values and metric in global_stats:
                        avg = np.mean(values)
                        z = (avg - global_stats[metric]["mean"]) / global_stats[metric]["std"]
                        result["cells"].append(
                            {
                                "mol_id": f"{category.upper()[:3]}_AGG",
                                "mol_name": category.capitalize(),
                                "metric": metric,
                                "z_score": round(z, 2),
                                "raw_value": round(avg, 4),
                                "unit": {
                                    "density": "g/cm3",
                                    "ced": "MJ/m³",
                                    "viscosity": "mPa·s",
                                }.get(metric, ""),
                            }
                        )

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to generate molecule impact analysis: {exc}")

    return result


# ---------------------------------------------------------------------------
# Generic 3-axis scatter (supports GHG as derived axis)
# ---------------------------------------------------------------------------

_GHG_AXIS = "ghg_emission"


def _batch_load_mol_fractions(
    session: object,
    experiment_ids: list[int],
) -> dict[int, list[tuple[str, float]]]:
    """Batch-load (mol_id, weight_fraction) for many experiments in one query.

    Returns:
        {experiment.id: [(mol_id, weight_fraction), ...]} for experiments
        that have experiment_molecules rows with non-null weight_fraction.
    """
    if not experiment_ids:
        return {}
    stmt = (
        select(
            ExperimentMoleculeModel.experiment_id,
            MoleculeModel.mol_id,
            ExperimentMoleculeModel.weight_fraction,
        )
        .join(MoleculeModel, MoleculeModel.id == ExperimentMoleculeModel.molecule_id)
        .where(
            ExperimentMoleculeModel.experiment_id.in_(experiment_ids),
            ExperimentMoleculeModel.weight_fraction.isnot(None),
        )
    )
    rows = session.execute(stmt).all()  # type: ignore[union-attr]
    result: dict[int, list[tuple[str, float]]] = {}
    for r in rows:
        result.setdefault(r.experiment_id, []).append((str(r.mol_id), float(r.weight_fraction)))
    return result


def _compute_ghg_for_experiment(
    exp: ExperimentModel,
    policy: GHGPolicy,
    mol_fractions_cache: dict[int, list[tuple[str, float]]],
) -> float | None:
    """Compute GHG for a single experiment using pre-loaded mol fractions.

    1st priority: experiment_molecules weight_fraction (from cache).
    Fallback: SARA comp_*_wt columns.
    """
    fractions = mol_fractions_cache.get(exp.id)
    if fractions:
        return policy.calculate_ghg_from_weight_fractions(fractions)

    # Fallback: SARA wt%
    sat = float(exp.comp_saturate_wt or 0)
    aro = float(exp.comp_aromatic_wt or 0)
    res = float(exp.comp_resin_wt or 0)
    asp = float(exp.comp_asphaltene_wt or 0)
    if sat + aro + res + asp <= 0:
        return None

    additive_wt = float(exp.additive_wt or 0)
    return policy.calculate_ghg_from_sara(
        comp_saturate_wt=sat,
        comp_aromatic_wt=aro,
        comp_resin_wt=res,
        comp_asphaltene_wt=asp,
        additive_mol_id=exp.additive_mol_id,
        additive_wt=additive_wt,
    )


_ALLOWED_METRIC_AXES = frozenset(
    {
        "density",
        "cohesive_energy_density",
        "elastic_modulus",
        "bulk_modulus",
        "viscosity",
        "tensile_strength",
        "adhesion_energy",
        "glass_transition_temperature_k",
    }
)
_ALLOWED_AXES = _ALLOWED_METRIC_AXES | {_GHG_AXIS}


async def get_scatter3d(
    axis_x: str = "density",
    axis_y: str = "cohesive_energy_density",
    axis_z: str = "ghg_emission",
    ff_type: str = "bulk_ff_gaff2",
) -> list[dict]:
    """Generic 3-axis scatter data. Any axis may be a DB metric or 'ghg_emission'.

    Raises:
        ValueError: If any axis is not in the supported set.
    """
    for name, val in [("axis_x", axis_x), ("axis_y", axis_y), ("axis_z", axis_z)]:
        if val not in _ALLOWED_AXES:
            raise ValueError(f"Unsupported {name}={val!r}. Allowed: {sorted(_ALLOWED_AXES)}")

    points: list[dict] = []
    metric_axes = [a for a in (axis_x, axis_y, axis_z) if a != _GHG_AXIS]
    needs_ghg = _GHG_AXIS in (axis_x, axis_y, axis_z)

    try:

        def _collect(session):  # type: ignore[no-untyped-def]
            nonlocal points
            # Query experiments + requested metrics
            if metric_axes:
                stmt = (
                    select(
                        ExperimentModel,
                        MetricModel.metric_name,
                        MetricModel.value,
                    )
                    .join(
                        MetricModel,
                        and_(
                            MetricModel.exp_id == ExperimentModel.exp_id,
                            MetricModel.metric_name.in_(metric_axes),
                        ),
                    )
                    .where(
                        ExperimentModel.status == "completed",
                        ExperimentModel.ff_type == ff_type,
                    )
                    .order_by(ExperimentModel.created_at.desc())
                    .limit(2000)
                )
            else:
                # All axes are GHG — just get completed experiments
                stmt = (
                    select(ExperimentModel)
                    .where(
                        ExperimentModel.status == "completed",
                        ExperimentModel.ff_type == ff_type,
                    )
                    .order_by(ExperimentModel.created_at.desc())
                    .limit(500)
                )

            rows = session.execute(stmt).all()
            if not rows:
                return

            # Collect per-experiment metric values
            by_exp: dict[str, dict] = {}
            for row in rows:
                if metric_axes:
                    exp_obj: ExperimentModel = row[0]
                    metric_name = str(row.metric_name)
                    metric_val = float(row.value)
                else:
                    exp_obj = row[0] if isinstance(row, tuple) else row
                    metric_name = None
                    metric_val = None

                eid = str(exp_obj.exp_id)
                if eid not in by_exp:
                    by_exp[eid] = {
                        "_exp": exp_obj,
                        "exp_id": eid,
                        "temperature_k": float(exp_obj.temperature_K or 0),
                        "additive_type": exp_obj.additive_type,
                        "additive_mol_id": exp_obj.additive_mol_id,
                    }
                if metric_name:
                    by_exp[eid][metric_name] = metric_val

            # Compute GHG if needed — batch-load mol fractions in 1 query
            policy = _get_ghg_policy() if needs_ghg else None
            mol_cache: dict[int, list[tuple[str, float]]] = {}
            if needs_ghg:
                exp_ids = [p["_exp"].id for p in by_exp.values()]
                mol_cache = _batch_load_mol_fractions(session, exp_ids)

            name_map = _build_additive_name_map(session)

            raw_points: list[dict] = []
            for payload in by_exp.values():
                vals: dict[str, float | None] = {}
                for axis_name, axis_key in [
                    ("x", axis_x),
                    ("y", axis_y),
                    ("z", axis_z),
                ]:
                    if axis_key == _GHG_AXIS:
                        vals[axis_name] = _compute_ghg_for_experiment(
                            payload["_exp"],
                            policy,
                            mol_cache,  # type: ignore[arg-type]
                        )
                    else:
                        vals[axis_name] = payload.get(axis_key)

                if any(v is None for v in vals.values()):
                    continue

                parsed = parse_exp_id(payload["exp_id"])
                binder_abbrev = str(parsed.get("binder_type") or "").strip()
                binder_type = BINDER_ABBREV_REVERSE.get(binder_abbrev, binder_abbrev or "unknown")
                raw_mol_id = (
                    str(
                        payload["additive_mol_id"]
                        or payload["additive_type"]
                        or parsed.get("additive")
                        or "none"
                    )
                    .strip()
                    .replace("__none__", "none")
                )
                additive = name_map.get(raw_mol_id, raw_mol_id) if raw_mol_id != "none" else "none"

                aging_raw = str(parsed.get("aging_state") or "").strip()
                if not aging_raw:
                    aging_raw = "non_aging"
                raw_points.append(
                    {
                        "exp_id": payload["exp_id"],
                        "axis_x_value": float(vals["x"]),  # type: ignore[arg-type]
                        "axis_y_value": float(vals["y"]),  # type: ignore[arg-type]
                        "axis_z_value": float(vals["z"]),  # type: ignore[arg-type]
                        "binder_type": binder_type,
                        "additive": additive,
                        "aging_state": aging_raw,
                        "additive_mol_id": payload["additive_mol_id"],
                        "temperature_k": payload["temperature_k"],
                    }
                )

            if not raw_points:
                return

            # Normalise to position [x, y, z]
            xs = [p["axis_x_value"] for p in raw_points]
            ys = [p["axis_y_value"] for p in raw_points]
            zs = [p["axis_z_value"] for p in raw_points]

            def _normalize(value: float, low: float, high: float, span: float = 10.0) -> float:
                if high <= low:
                    return 0.0
                return ((value - low) / (high - low) - 0.5) * span

            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            z_min, z_max = min(zs), max(zs)

            for p in raw_points:
                p["position"] = [
                    _normalize(p["axis_x_value"], x_min, x_max, 12.0),
                    _normalize(p["axis_y_value"], y_min, y_max, 10.0),
                    _normalize(p["axis_z_value"], z_min, z_max, 12.0),
                ]

            points = raw_points

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to generate scatter3d: {exc}")
        return []

    return points
