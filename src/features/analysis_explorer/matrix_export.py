"""Unified experiment-metric matrix export for analysis and ML preprocessing.

Builds a (experiments × metrics) DataFrame by reusing existing dataset
builders as SSOT. Supports optional array metric reference and summary columns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import pandas as pd
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DatasetMode = Literal["bulk_binder_cell", "single_molecule", "layered_structure"]


def build_dataset_matrix(
    session: Session,
    *,
    dataset_mode: DatasetMode,
    filters: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    include_array_refs: bool = False,
    include_array_summaries: bool = False,
) -> pd.DataFrame:
    """Build (experiments × metrics) DataFrame from existing dataset builders.

    Args:
        session: DB session.
        dataset_mode: One of bulk_binder_cell, single_molecule, layered_structure.
        filters: Optional dict of filter conditions passed to the builder.
        columns: Optional list of columns to include. None = all.
        include_array_refs: If True, add array metric file_path/shape columns.
        include_array_summaries: If True, add scalar summary columns from
            array metric payloads via array_metric_summaries extractors.

    Returns:
        pandas DataFrame with experiment rows and metric columns.
    """
    import pandas as pd

    from api.schemas.analysis_explorer import ExplorerDataRequest

    builder = _get_builder(dataset_mode)
    request = ExplorerDataRequest(
        limit=5000,
        offset=0,
        filters=filters or {},
    )

    rows, total, _ = builder.list_rows(session, request)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    if columns:
        available = [c for c in columns if c in df.columns]
        df = df[available]

    if include_array_refs and "exp_id" in df.columns:
        df = _attach_array_refs(session, df)

    if include_array_summaries and "exp_id" in df.columns:
        df = _attach_array_summaries(session, df)

    return df


def _get_builder(mode: DatasetMode) -> Any:
    """Get the appropriate dataset builder for the mode."""
    if mode == "bulk_binder_cell":
        from features.analysis_explorer.dataset_builders.bulk import BulkBinderCellBuilder

        return BulkBinderCellBuilder()
    elif mode == "single_molecule":
        from features.analysis_explorer.dataset_builders.single_molecule import (
            SingleMoleculeBuilder,
        )

        return SingleMoleculeBuilder()
    elif mode == "layered_structure":
        from features.analysis_explorer.dataset_builders.layered import (
            LayeredStructureBuilder,
        )

        return LayeredStructureBuilder()
    else:
        raise ValueError(f"Unknown dataset_mode: {mode}")


def _attach_array_refs(session: Session, df: pd.DataFrame) -> pd.DataFrame:
    """Attach array metric file_path and shape columns."""
    from database.models.metric import MetricModel

    exp_ids = df["exp_id"].tolist()
    if not exp_ids:
        return df

    array_rows = (
        session.query(
            MetricModel.exp_id,
            MetricModel.metric_name,
            MetricModel.array_file_path,
            MetricModel.array_shape,
        )
        .filter(
            MetricModel.exp_id.in_(exp_ids),
            MetricModel.array_file_path.isnot(None),
        )
        .all()
    )

    ref_data: dict[str, dict[str, Any]] = {}
    for row in array_rows:
        if row.exp_id not in ref_data:
            ref_data[row.exp_id] = {}
        ref_data[row.exp_id][f"{row.metric_name}__file_path"] = row.array_file_path
        ref_data[row.exp_id][f"{row.metric_name}__shape"] = str(row.array_shape)

    if ref_data:
        import pandas as pd

        ref_df = pd.DataFrame.from_dict(ref_data, orient="index")
        ref_df.index.name = "exp_id"
        df = df.merge(ref_df, left_on="exp_id", right_index=True, how="left")

    return df


def _attach_array_summaries(session: Session, df: pd.DataFrame) -> pd.DataFrame:
    """Attach scalar summary columns from actual array metric files.

    Loads real Parquet array payloads via ArrayStorage, then computes
    summary statistics. Does NOT rely on metadata_json (which may lack
    per-element values).
    """
    from features.metrics.array_metric_summaries import (
        summarize_cross_cut_profile,
        summarize_layer_matrix,
    )

    _SUMMARY_METRICS = {
        "cross_cut_interaction_profile": summarize_cross_cut_profile,
        "e_inter_layer_matrix": summarize_layer_matrix,
    }

    from database.models.metric import MetricModel

    exp_ids = df["exp_id"].tolist()
    if not exp_ids:
        return df

    # Query array file paths for the target metrics
    array_rows = (
        session.query(
            MetricModel.exp_id,
            MetricModel.metric_name,
            MetricModel.array_file_path,
        )
        .filter(
            MetricModel.exp_id.in_(exp_ids),
            MetricModel.metric_name.in_(list(_SUMMARY_METRICS.keys())),
            MetricModel.array_file_path.isnot(None),
        )
        .all()
    )

    summary_data: dict[str, dict[str, Any]] = {}
    for row in array_rows:
        extractor = _SUMMARY_METRICS.get(row.metric_name)
        if not extractor or not row.array_file_path:
            continue
        try:
            from metrics.array_storage import ArrayStorage

            storage = ArrayStorage()
            data = storage.load(row.array_file_path)
            if data is None:
                logger.debug(
                    "Array payload missing for %s/%s: %s",
                    row.exp_id,
                    row.metric_name,
                    row.array_file_path,
                )
                continue
            summaries = extractor(data)
        except Exception:
            logger.debug(
                "Failed to load array file for %s/%s: %s",
                row.exp_id,
                row.metric_name,
                row.array_file_path,
            )
            continue
        if row.exp_id not in summary_data:
            summary_data[row.exp_id] = {}
        for key, val in summaries.items():
            summary_data[row.exp_id][f"{row.metric_name}__{key}"] = val

    if summary_data:
        import pandas as pd

        sum_df = pd.DataFrame.from_dict(summary_data, orient="index")
        sum_df.index.name = "exp_id"
        df = df.merge(sum_df, left_on="exp_id", right_index=True, how="left")

    return df
