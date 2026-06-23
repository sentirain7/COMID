"""Analysis embedding, scatter, and metric schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Analysis Models
# =============================================================================


class AnalysisEmbeddingPoint(BaseModel):
    """Embedding point for 3D visualization."""

    model_config = ConfigDict(title="AnalysisEmbeddingPoint")

    mol_id: str
    mol_name: str
    category: str
    position: list[float]  # [x, y, z]
    metrics: dict
    experiment_count: int
    exp_id: str | None = None
    binder_type: str | None = None
    additive: str | None = None
    additive_wt: float | None = None
    aging_state: str | None = None
    temperature_k: float | None = None
    density: float | None = None
    ced: float | None = None


class AnalysisEmbeddingResponse(BaseModel):
    """Analysis embedding response."""

    model_config = ConfigDict(title="AnalysisEmbeddingResponse")

    points: list[AnalysisEmbeddingPoint]
    method: str
    ff_type: str


class Scatter3DPoint(BaseModel):
    """Generic 3-axis scatter data point."""

    model_config = ConfigDict(title="Scatter3DPoint")

    exp_id: str
    axis_x_value: float
    axis_y_value: float
    axis_z_value: float
    binder_type: str | None = None
    additive: str | None = None
    additive_mol_id: str | None = None
    aging_state: str | None = None
    temperature_k: float | None = None
    position: list[float]  # [x, y, z] normalized


class BinderCellMetricOverview(BaseModel):
    """Average metric snapshot for completed binder-cell experiments."""

    model_config = ConfigDict(title="BinderCellMetricOverview")

    sample_count: int
    avg_density: float | None = None
    avg_total_energy: float | None = None
    avg_potential_energy: float | None = None
    avg_kinetic_energy: float | None = None


class BinderCellXYSummaryPoint(BaseModel):
    """Average XY box-size summary for a single grouping category."""

    model_config = ConfigDict(title="BinderCellXYSummaryPoint")

    group_key: str
    group_label: str
    sample_count: int
    avg_lx: float
    avg_ly: float
    avg_xy: float


class BinderCellXYSummaryResponse(BaseModel):
    """Grouped XY-size summary plus metric overview for analysis."""

    model_config = ConfigDict(title="BinderCellXYSummaryResponse")

    group_by: str
    total_samples: int
    overview: BinderCellMetricOverview
    items: list[BinderCellXYSummaryPoint]


# =============================================================================
# Metric Retrieval Models (v00.69.06)
# =============================================================================


class MetricValueItem(BaseModel):
    """Single metric value item."""

    model_config = ConfigDict(title="MetricValueItem")

    exp_id: str
    value: float


class MetricValuesResponse(BaseModel):
    """Response for metric values across experiments."""

    model_config = ConfigDict(title="MetricValuesResponse")

    metric_name: str
    namespace: str | None = None
    total: int
    offset: int
    limit: int
    values: list[MetricValueItem]


class MetricStatisticsResponse(BaseModel):
    """Response for metric statistics."""

    model_config = ConfigDict(title="MetricStatisticsResponse")

    metric_name: str
    namespace: str | None = None
    count: int
    avg: float
    min: float
    max: float
    stddev: float | None = None


# =============================================================================
# Array Metric Data Models (Curve Analysis)
# =============================================================================


class ArrayMetricDataResponse(BaseModel):
    """Single experiment array metric data."""

    model_config = ConfigDict(title="ArrayMetricDataResponse")

    exp_id: str
    metric_name: str
    namespace: str
    columns: dict[str, list[Any]]
    metadata: dict | None = None


class ArrayMetricCompareRequest(BaseModel):
    """Request to compare array metrics across experiments."""

    model_config = ConfigDict(title="ArrayMetricCompareRequest")

    exp_ids: list[str]  # max 8
    metric_name: str


class ArrayMetricCompareItem(BaseModel):
    """Single experiment entry in a compare response."""

    model_config = ConfigDict(title="ArrayMetricCompareItem")

    exp_id: str
    label: str
    columns: dict[str, list[Any]]
    metadata: dict | None = None


class ArrayMetricCompareResponse(BaseModel):
    """Response for comparing array metrics across experiments."""

    model_config = ConfigDict(title="ArrayMetricCompareResponse")

    metric_name: str
    experiments: list[ArrayMetricCompareItem]


class ExperimentArrayMetricEntry(BaseModel):
    """Experiment entry in the list of experiments with a given array metric."""

    model_config = ConfigDict(title="ExperimentArrayMetricEntry")

    exp_id: str
    label: str
    binder_type: str | None = None
    temperature_k: float | None = None
    additive: str | None = None


# =============================================================================
# Array Metric Info (existing)
# =============================================================================


class ArrayMetricInfo(BaseModel):
    """Array metric information."""

    model_config = ConfigDict(title="ArrayMetricInfo")

    metric_name: str
    namespace: str
    array_file_path: str | None = None
    array_shape: list | None = None


class ArrayMetricsResponse(BaseModel):
    """Response for array metrics list."""

    model_config = ConfigDict(title="ArrayMetricsResponse")

    exp_id: str
    array_metrics: list[ArrayMetricInfo]
