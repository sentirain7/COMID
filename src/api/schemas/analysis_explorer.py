"""Analysis Explorer public schemas (SSOT)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExplorerDatasetMode = Literal["bulk_binder_cell", "single_molecule", "layered_structure"]
ExplorerReducer = Literal["mean", "std", "count", "min", "max"]


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ExplorerSortSpec(BaseModel):
    key: str
    direction: Literal["asc", "desc"] = "asc"


class ExplorerRangeFilter(BaseModel):
    min: float | None = None
    max: float | None = None


class ExplorerDataRequest(BaseModel):
    dataset_mode: ExplorerDatasetMode
    filters: dict[str, list[str] | ExplorerRangeFilter] = Field(default_factory=dict)
    columns: list[str] | None = None
    sort: list[ExplorerSortSpec] | None = None
    limit: int = Field(default=200, ge=1, le=2000)
    offset: int = Field(default=0, ge=0)


class ExplorerAggregateRequest(BaseModel):
    dataset_mode: ExplorerDatasetMode
    filters: dict[str, list[str] | ExplorerRangeFilter] = Field(default_factory=dict)
    x_dimension: str
    series_dimension: str | None = None
    metric: str
    reducer: ExplorerReducer = "mean"
    temperature_bin_width: float | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ExplorerDataResponse(BaseModel):
    rows: list[dict[str, Any]]
    matched_total: int
    returned_total: int
    available_filters: dict[str, Any]
    sort_applied: list[ExplorerSortSpec]


class ExplorerAggregateResponse(BaseModel):
    groups: list[str]
    series: list[str]
    values: list[list[float | None]]
    matched_total: int


class DatasetDimensionDef(BaseModel):
    key: str
    label: str
    type: Literal["categorical", "continuous"] = "categorical"


class DatasetMetricDef(BaseModel):
    key: str
    label: str
    unit: str = ""


class DatasetCatalogEntry(BaseModel):
    mode: ExplorerDatasetMode
    label: str
    dimensions: list[DatasetDimensionDef]
    metrics: list[DatasetMetricDef]
    array_metrics: list[DatasetMetricDef] = Field(
        default_factory=list,
        description="Array metrics available for this dataset (curves, profiles)",
    )
    chart_types: list[str]
    default_chart: str
    default_x: str
    default_y: str
    default_series: str | None = None
