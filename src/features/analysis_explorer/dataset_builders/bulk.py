"""Bulk Binder Cell dataset builder."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from api.schemas.analysis_explorer import ExplorerAggregateRequest, ExplorerDataRequest
from features.analysis_explorer.dataset_builders.base import DatasetBuilder

_METRIC_NAMES = [
    "density",
    "cohesive_energy_density",
    "viscosity",
    "msd_diffusion_coefficient",
    "rdf_first_peak_r",
    "rdf_first_peak_g",
    "rdf_coordination_number",
    "e_inter_total",
    "glass_transition_temperature_k",
    "bulk_modulus",
    "total_energy",
    "potential_energy",
    "kinetic_energy",
]

_CAT_DIMS = ["binder_type", "aging_state", "additive", "run_tier", "ff_type", "structure_size"]
_RANGE_DIMS = ["temperature_K", "additive_wt"]


class BulkBinderCellBuilder(DatasetBuilder):
    """Builder for bulk binder cell analysis dataset."""

    def list_rows(
        self,
        session: Session,
        request: ExplorerDataRequest,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        records = self._load_all(session)

        # Collect available_filters from candidate universe (before categorical filter)
        avail = self._build_available(records)

        # Apply filters
        for dim in _CAT_DIMS:
            records = self._apply_categorical_filter(records, request.filters, dim)
        for dim in _RANGE_DIMS:
            records = self._apply_range_filter(records, request.filters, dim)

        matched = len(records)

        # Sort
        from features.common.canonical_ordering import stable_sort_records

        sort_keys = [s.key for s in request.sort] if request.sort else ["temperature_K"]
        records = stable_sort_records(records, sort_keys, exp_id_key="exp_id")

        # Paginate
        records = records[request.offset : request.offset + request.limit]

        # Column projection
        if request.columns:
            cols = set(request.columns) | {"exp_id"}
            records = [{k: v for k, v in r.items() if k in cols} for r in records]

        return records, matched, avail

    def aggregate(
        self,
        session: Session,
        request: ExplorerAggregateRequest,
    ) -> dict[str, Any]:
        records = self._load_all(session)
        for dim in _CAT_DIMS:
            records = self._apply_categorical_filter(records, request.filters, dim)
        for dim in _RANGE_DIMS:
            records = self._apply_range_filter(records, request.filters, dim)

        return self._compute_aggregate(records, request)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_all(self, session: Session) -> list[dict[str, Any]]:
        from sqlalchemy import or_

        from common.pathing import parse_exp_id
        from database.models import (
            ExperimentModel,
            MetricModel,
        )
        from features.analysis.service import (
            _batch_load_mol_fractions,
            _compute_ghg_for_experiment,
            _get_ghg_policy,
        )
        from features.metrics.analytics import _build_additive_name_map, _resolve_additive_display

        exps = (
            session.query(ExperimentModel)
            .filter(
                ExperimentModel.status == "completed",
                or_(
                    ExperimentModel.study_type == "bulk",
                    ExperimentModel.study_type.is_(None),
                ),
            )
            .order_by(ExperimentModel.created_at.desc())
            .limit(5000)
            .all()
        )
        if not exps:
            return []

        exp_ids = [e.exp_id for e in exps]
        name_map = _build_additive_name_map(session)

        # Batch load metrics
        metric_rows = (
            session.query(MetricModel.exp_id, MetricModel.metric_name, MetricModel.value)
            .filter(MetricModel.exp_id.in_(exp_ids), MetricModel.metric_name.in_(_METRIC_NAMES))
            .all()
        )
        metrics_by_exp: dict[str, dict[str, float]] = {}
        for r in metric_rows:
            metrics_by_exp.setdefault(r.exp_id, {})[r.metric_name] = r.value

        # GHG (derived)
        ghg_policy = None
        mol_fractions_cache: dict[int, list[tuple[str, float]]] = {}
        try:
            ghg_policy = _get_ghg_policy()
            int_ids = [e.id for e in exps]
            mol_fractions_cache = _batch_load_mol_fractions(session, int_ids)
        except Exception:
            pass

        records: list[dict[str, Any]] = []
        for exp in exps:
            additive, additive_wt = _resolve_additive_display(exp, name_map)
            parsed = parse_exp_id(exp.exp_id)
            metrics = metrics_by_exp.get(exp.exp_id, {})

            ghg: float | None = None
            if ghg_policy:
                ghg = _compute_ghg_for_experiment(exp, ghg_policy, mol_fractions_cache)

            rec: dict[str, Any] = {
                "exp_id": exp.exp_id,
                "binder_type": parsed.get("binder_type") or getattr(exp, "binder_type", None),
                "aging_state": parsed.get("aging_state")
                or getattr(exp, "aging_state", None)
                or "non_aging",
                "additive": additive,
                "additive_wt": additive_wt,
                "temperature_K": exp.temperature_K or 298.0,
                "run_tier": exp.run_tier,
                "ff_type": exp.ff_type,
                "structure_size": exp.structure_size,
            }
            for m in _METRIC_NAMES:
                rec[m] = metrics.get(m)
            rec["ghg_emission"] = ghg
            records.append(rec)

        return records

    def _build_available(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        avail: dict[str, Any] = {}
        for dim in _CAT_DIMS:
            avail[dim] = self._collect_available_categorical(records, dim)
        for dim in _RANGE_DIMS:
            avail[dim] = self._collect_available_range(records, dim)
        return avail

    def _compute_aggregate(
        self,
        records: list[dict[str, Any]],
        request: ExplorerAggregateRequest,
    ) -> dict[str, Any]:
        from features.common.canonical_ordering import canonical_value_key

        x_dim = request.x_dimension
        series_dim = request.series_dimension
        metric = request.metric
        reducer = request.reducer

        # Bin temperature if requested
        if request.temperature_bin_width and x_dim == "temperature_K":
            bw = request.temperature_bin_width
            for r in records:
                t = r.get("temperature_K")
                if t is not None:
                    lo = math.floor(t / bw) * bw
                    r["_x_bin"] = f"{lo:.0f}-{lo + bw:.0f} K"
            x_key = "_x_bin"
        else:
            x_key = x_dim

        # Group
        buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for r in records:
            gv = str(r.get(x_key, ""))
            sv = str(r.get(series_dim, "value")) if series_dim else "value"
            mv = r.get(metric)
            if mv is not None:
                buckets[gv][sv].append(float(mv))

        groups = sorted(buckets.keys(), key=lambda g: canonical_value_key(x_dim, g))
        all_series: set[str] = set()
        for sv_map in buckets.values():
            all_series.update(sv_map.keys())
        series = sorted(all_series, key=lambda s: canonical_value_key(series_dim or "", s))

        def _reduce(vals: list[float]) -> float | None:
            if not vals:
                return None
            if reducer == "mean":
                return sum(vals) / len(vals)
            if reducer == "std":
                if len(vals) < 2:
                    return 0.0
                mean = sum(vals) / len(vals)
                return (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
            if reducer == "count":
                return float(len(vals))
            if reducer == "min":
                return min(vals)
            if reducer == "max":
                return max(vals)
            return None

        values: list[list[float | None]] = []
        for g in groups:
            row: list[float | None] = []
            for s in series:
                row.append(_reduce(buckets[g].get(s, [])))
            values.append(row)

        return {
            "groups": groups,
            "series": series,
            "values": values,
            "matched_total": len(records),
        }
