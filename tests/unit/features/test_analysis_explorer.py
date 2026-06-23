"""Tests for Analysis Explorer schemas and catalog."""

from api.schemas.analysis_explorer import (
    ExplorerAggregateRequest,
    ExplorerDataRequest,
    ExplorerDataResponse,
    ExplorerRangeFilter,
    ExplorerSortSpec,
)
from features.analysis_explorer.catalog import CATALOG, CATALOG_BY_MODE


class TestCatalog:
    """Catalog returns expected modes and structure."""

    def test_three_modes(self):
        assert len(CATALOG) == 3
        modes = {c.mode for c in CATALOG}
        assert modes == {"bulk_binder_cell", "single_molecule", "layered_structure"}

    def test_bulk_has_density(self):
        bulk = CATALOG_BY_MODE["bulk_binder_cell"]
        metric_keys = [m.key for m in bulk.metrics]
        assert "density" in metric_keys
        assert "ghg_emission" in metric_keys

    def test_single_molecule_has_e_intra(self):
        sm = CATALOG_BY_MODE["single_molecule"]
        metric_keys = [m.key for m in sm.metrics]
        assert "e_intra" in metric_keys
        assert "ghg_emission" not in metric_keys

    def test_layered_has_produced_metrics(self):
        lay = CATALOG_BY_MODE["layered_structure"]
        metric_keys = [m.key for m in lay.metrics]
        assert "work_of_separation" in metric_keys
        assert "tensile_strength" in metric_keys
        assert "interfacial_tensile_strength" in metric_keys
        # adhesion_energy removed (produced=False)
        assert "adhesion_energy" not in metric_keys

    def test_defaults_set(self):
        for cat in CATALOG:
            assert cat.default_x, f"{cat.mode} missing default_x"
            assert cat.default_y, f"{cat.mode} missing default_y"
            assert cat.default_chart, f"{cat.mode} missing default_chart"

    def test_dimensions_have_types(self):
        for cat in CATALOG:
            for dim in cat.dimensions:
                assert dim.type in ("categorical", "continuous"), (
                    f"{cat.mode}.{dim.key} has invalid type: {dim.type}"
                )


class TestSchemas:
    """Pydantic schemas validate correctly."""

    def test_data_request_defaults(self):
        req = ExplorerDataRequest(dataset_mode="bulk_binder_cell")
        assert req.limit == 200
        assert req.offset == 0
        assert req.filters == {}
        assert req.columns is None
        assert req.sort is None

    def test_data_request_with_filters(self):
        req = ExplorerDataRequest(
            dataset_mode="single_molecule",
            filters={
                "sara_type": ["asphaltene", "resin"],
                "temperature_K": {"min": 273, "max": 373},
            },
            sort=[{"key": "temperature_K", "direction": "asc"}],
            limit=50,
        )
        assert req.dataset_mode == "single_molecule"
        assert req.limit == 50
        assert len(req.sort) == 1

    def test_aggregate_request(self):
        req = ExplorerAggregateRequest(
            dataset_mode="layered_structure",
            x_dimension="crystal_material",
            metric="adhesion_energy",
            reducer="mean",
        )
        assert req.series_dimension is None
        assert req.temperature_bin_width is None

    def test_data_response(self):
        resp = ExplorerDataResponse(
            rows=[{"exp_id": "e1", "density": 1.0}],
            matched_total=10,
            returned_total=1,
            available_filters={"aging_state": {"values": ["non_aging"], "selected": []}},
            sort_applied=[ExplorerSortSpec(key="exp_id")],
        )
        assert resp.matched_total == 10
        assert resp.returned_total == 1

    def test_sort_spec_defaults(self):
        s = ExplorerSortSpec(key="temperature_K")
        assert s.direction == "asc"

    def test_range_filter(self):
        rf = ExplorerRangeFilter(min=273.0, max=373.0)
        assert rf.min == 273.0
        assert rf.max == 373.0


class TestDatasetBuilderBase:
    """DatasetBuilder helper methods."""

    def test_categorical_filter(self):
        from features.analysis_explorer.dataset_builders.base import DatasetBuilder

        records = [
            {"aging_state": "non_aging", "exp_id": "e1"},
            {"aging_state": "short_aging", "exp_id": "e2"},
            {"aging_state": "long_aging", "exp_id": "e3"},
        ]
        filtered = DatasetBuilder._apply_categorical_filter(
            records, {"aging_state": ["non_aging", "short_aging"]}, "aging_state"
        )
        assert len(filtered) == 2
        assert {r["exp_id"] for r in filtered} == {"e1", "e2"}

    def test_range_filter(self):
        from features.analysis_explorer.dataset_builders.base import DatasetBuilder

        records = [
            {"temperature_K": 273, "exp_id": "e1"},
            {"temperature_K": 298, "exp_id": "e2"},
            {"temperature_K": 373, "exp_id": "e3"},
        ]
        filtered = DatasetBuilder._apply_range_filter(
            records, {"temperature_K": {"min": 280, "max": 350}}, "temperature_K"
        )
        assert len(filtered) == 1
        assert filtered[0]["exp_id"] == "e2"

    def test_categorical_filter_no_key(self):
        from features.analysis_explorer.dataset_builders.base import DatasetBuilder

        records = [{"aging_state": "non_aging", "exp_id": "e1"}]
        filtered = DatasetBuilder._apply_categorical_filter(records, {}, "aging_state")
        assert len(filtered) == 1

    def test_collect_available_categorical(self):
        from features.analysis_explorer.dataset_builders.base import DatasetBuilder

        records = [
            {"aging_state": "non_aging"},
            {"aging_state": "short_aging"},
            {"aging_state": "non_aging"},
            {"aging_state": None},
        ]
        avail = DatasetBuilder._collect_available_categorical(records, "aging_state")
        assert avail["values"] == ["non_aging", "short_aging"]
        assert avail["selected"] == []

    def test_collect_available_range(self):
        from features.analysis_explorer.dataset_builders.base import DatasetBuilder

        records = [
            {"temperature_K": 273},
            {"temperature_K": 298},
            {"temperature_K": 373},
        ]
        avail = DatasetBuilder._collect_available_range(records, "temperature_K")
        assert avail["min"] == 273
        assert avail["max"] == 373
