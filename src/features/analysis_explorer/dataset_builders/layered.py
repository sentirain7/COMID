"""Layered Structure dataset builder.

Re-uses the internal query logic from layered_analysis to avoid duplication.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from api.schemas.analysis_explorer import ExplorerAggregateRequest, ExplorerDataRequest
from features.analysis_explorer.dataset_builders.base import DatasetBuilder

_CAT_DIMS = [
    "layer_type",
    "crystal_material",
    "crystal_surface",
    "binder_type",
    "aging_state",
    "binder_type_secondary",
    "aging_state_secondary",
    "has_water",
    "additive_type",
]
_RANGE_DIMS = ["temperature_K", "additive_wt"]


class LayeredStructureBuilder(DatasetBuilder):
    """Builder for layered structure analysis dataset."""

    def list_rows(
        self,
        session: Session,
        request: ExplorerDataRequest,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        records = self._load_all(session)

        avail = self._build_available(records)

        for dim in _CAT_DIMS:
            records = self._apply_categorical_filter(records, request.filters, dim)
        for dim in _RANGE_DIMS:
            records = self._apply_range_filter(records, request.filters, dim)

        matched = len(records)

        from features.common.canonical_ordering import stable_sort_records

        sort_keys = (
            [s.key for s in request.sort]
            if request.sort
            else ["layer_type", "crystal_material", "temperature_K"]
        )
        records = stable_sort_records(records, sort_keys, exp_id_key="exp_id")

        records = records[request.offset : request.offset + request.limit]

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
        """Load layered experiment data using the shared query helper."""
        from features.layered_structures.layered_analysis import _build_layered_rows

        return _build_layered_rows(session)

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
