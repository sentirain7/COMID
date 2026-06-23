"""Runtime tests for matrix_export array summary loading."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "src")

pd = pytest.importorskip("pandas")


def test_build_dataset_matrix_exists():
    from features.analysis_explorer.matrix_export import build_dataset_matrix

    assert callable(build_dataset_matrix)


def test_attach_array_summaries_uses_array_storage_payload():
    from features.analysis_explorer.matrix_export import _attach_array_summaries

    df = pd.DataFrame({"exp_id": ["exp1"]})
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(
            exp_id="exp1",
            metric_name="cross_cut_interaction_profile",
            array_file_path="/tmp/cross.parquet",
        ),
        SimpleNamespace(
            exp_id="exp1",
            metric_name="e_inter_layer_matrix",
            array_file_path="/tmp/layer.parquet",
        ),
    ]

    def _load(_self, file_path: str):
        if file_path.endswith("cross.parquet"):
            return {"cut_index": [0, 1], "cross_cut_mJ_m2": [2.5, 4.0]}
        if file_path.endswith("layer.parquet"):
            return {"pair_label": ["L0_L1", "L1_L2"], "e_inter": [-1.0, -3.0]}
        return None

    with patch("metrics.array_storage.ArrayStorage.load", autospec=True, side_effect=_load) as load:
        out = _attach_array_summaries(session, df)

    assert load.call_count == 2
    assert out.loc[0, "cross_cut_interaction_profile__weakest_cut_mJ_m2"] == 2.5
    assert out.loc[0, "cross_cut_interaction_profile__strongest_cut_mJ_m2"] == 4.0
    assert out.loc[0, "e_inter_layer_matrix__layer_e_inter_total"] == -4.0
    assert out.loc[0, "e_inter_layer_matrix__layer_pair_count"] == 2


def test_attach_array_summaries_skips_missing_payload():
    from features.analysis_explorer.matrix_export import _attach_array_summaries

    df = pd.DataFrame({"exp_id": ["exp1"]})
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(
            exp_id="exp1",
            metric_name="cross_cut_interaction_profile",
            array_file_path="/tmp/missing.parquet",
        )
    ]

    with patch("metrics.array_storage.ArrayStorage.load", autospec=True, return_value=None):
        out = _attach_array_summaries(session, df)

    assert list(out.columns) == ["exp_id"]
