"""Abstract base for dataset builders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from api.schemas.analysis_explorer import ExplorerAggregateRequest, ExplorerDataRequest


class DatasetBuilder(ABC):
    """Base class for Explorer dataset builders."""

    @abstractmethod
    def list_rows(
        self,
        session: Session,
        request: ExplorerDataRequest,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        """Query rows from the database.

        Returns:
            (rows, matched_total, available_filters)
        """

    @abstractmethod
    def aggregate(
        self,
        session: Session,
        request: ExplorerAggregateRequest,
    ) -> dict[str, Any]:
        """Compute aggregation.

        Returns:
            {"groups": [...], "series": [...], "values": [[...]], "matched_total": int}
        """

    # ------------------------------------------------------------------
    # Shared filter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_categorical_filter(
        records: list[dict[str, Any]],
        filters: dict[str, Any],
        key: str,
    ) -> list[dict[str, Any]]:
        """Filter records by categorical values if *key* is in *filters*."""
        values = filters.get(key)
        if not values or not isinstance(values, list):
            return records
        allowed = set(values)
        return [r for r in records if r.get(key) in allowed]

    @staticmethod
    def _apply_range_filter(
        records: list[dict[str, Any]],
        filters: dict[str, Any],
        key: str,
    ) -> list[dict[str, Any]]:
        """Filter records by numeric range if *key* is in *filters*."""
        spec = filters.get(key)
        if spec is None:
            return records
        # Accept both dict (from JSON) and ExplorerRangeFilter
        if hasattr(spec, "min"):
            lo, hi = spec.min, spec.max
        elif isinstance(spec, dict):
            lo, hi = spec.get("min"), spec.get("max")
        else:
            return records
        result = []
        for r in records:
            v = r.get(key)
            if v is None:
                continue
            if lo is not None and v < lo:
                continue
            if hi is not None and v > hi:
                continue
            result.append(r)
        return result

    @staticmethod
    def _collect_available_categorical(
        records: list[dict[str, Any]],
        key: str,
    ) -> dict[str, Any]:
        values = sorted({str(r[key]) for r in records if r.get(key) is not None})
        return {"values": values, "selected": []}

    @staticmethod
    def _collect_available_range(
        records: list[dict[str, Any]],
        key: str,
    ) -> dict[str, Any]:
        nums = [r[key] for r in records if r.get(key) is not None]
        if not nums:
            return {"min": None, "max": None, "selected_min": None, "selected_max": None}
        return {
            "min": min(nums),
            "max": max(nums),
            "selected_min": None,
            "selected_max": None,
        }
