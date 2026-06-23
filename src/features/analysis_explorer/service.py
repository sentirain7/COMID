"""Analysis Explorer service layer."""

from __future__ import annotations

from typing import Any

from api.schemas.analysis_explorer import (
    DatasetCatalogEntry,
    ExplorerAggregateRequest,
    ExplorerAggregateResponse,
    ExplorerDataRequest,
    ExplorerDataResponse,
    ExplorerSortSpec,
)
from common.logging import get_logger
from features.analysis_explorer.catalog import CATALOG
from features.analysis_explorer.dataset_builders.base import DatasetBuilder
from features.analysis_explorer.dataset_builders.bulk import BulkBinderCellBuilder
from features.analysis_explorer.dataset_builders.layered import LayeredStructureBuilder
from features.analysis_explorer.dataset_builders.single_molecule import SingleMoleculeBuilder
from features.common import run_in_session

logger = get_logger("features.analysis_explorer")

_BUILDERS: dict[str, DatasetBuilder] = {
    "bulk_binder_cell": BulkBinderCellBuilder(),
    "single_molecule": SingleMoleculeBuilder(),
    "layered_structure": LayeredStructureBuilder(),
}


def get_catalog() -> list[DatasetCatalogEntry]:
    """Return the full dataset catalog."""
    return CATALOG


async def query_data(request: ExplorerDataRequest) -> ExplorerDataResponse:
    """Execute a data query against the specified dataset."""
    builder = _BUILDERS.get(request.dataset_mode)
    if not builder:
        raise ValueError(f"Unknown dataset mode: {request.dataset_mode}")

    def _query(session: Any) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        return builder.list_rows(session, request)

    rows, matched_total, available_filters = run_in_session(_query)

    sort_applied = request.sort or [ExplorerSortSpec(key="exp_id")]

    return ExplorerDataResponse(
        rows=rows,
        matched_total=matched_total,
        returned_total=len(rows),
        available_filters=available_filters,
        sort_applied=sort_applied,
    )


async def query_aggregate(request: ExplorerAggregateRequest) -> ExplorerAggregateResponse:
    """Execute an aggregate query against the specified dataset."""
    builder = _BUILDERS.get(request.dataset_mode)
    if not builder:
        raise ValueError(f"Unknown dataset mode: {request.dataset_mode}")

    def _query(session: Any) -> dict[str, Any]:
        return builder.aggregate(session, request)

    result = run_in_session(_query)

    return ExplorerAggregateResponse(
        groups=result["groups"],
        series=result["series"],
        values=result["values"],
        matched_total=result["matched_total"],
    )
