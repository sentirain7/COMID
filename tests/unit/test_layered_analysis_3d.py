"""Tests for the layered structure 3D analysis endpoint schemas and helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.schemas.structures import LayeredAnalysis3DPoint, LayeredAnalysis3DResponse
from database.models import (
    Base,
    CrystalStructureModel,
    ExperimentModel,
    LayeredExperimentSourceModel,
    MetricModel,
)

# ---------------------------------------------------------------------------
# Schema instantiation tests
# ---------------------------------------------------------------------------


class TestLayeredAnalysis3DSchemas:
    """Verify schema defaults and validation for the 3D analysis models."""

    def test_point_defaults(self) -> None:
        point = LayeredAnalysis3DPoint(exp_id="test_001", name="test")
        assert point.exp_id == "test_001"
        assert point.temperature_K is None
        assert point.layer_type is None
        assert point.layer_count == 0
        assert point.has_water is False
        assert point.adhesion_energy is None
        assert point.ghg_emission is None

    def test_point_full(self) -> None:
        point = LayeredAnalysis3DPoint(
            exp_id="layer_exp_001",
            name="SiO2 + AAA1 interface",
            temperature_K=298.0,
            layer_type="interface",
            layer_count=2,
            crystal_material="SiO2",
            crystal_surface="001",
            binder_type="AAA1",
            aging_state="non_aging",
            additive_type=None,
            additive_wt=None,
            has_water=False,
            adhesion_energy=125.3,
            tensile_strength=45.2,
            elastic_modulus=2.1,
            toughness=0.35,
            work_of_separation=80.0,
            ductility=0.15,
            orientation_order=0.42,
            e_inter_interface_1=-350.0,
            ghg_emission=0.48,
        )
        assert point.layer_type == "interface"
        assert point.crystal_material == "SiO2"
        assert point.adhesion_energy == 125.3
        assert point.ghg_emission == 0.48

    def test_response_empty(self) -> None:
        resp = LayeredAnalysis3DResponse(total=0)
        assert resp.total == 0
        assert resp.items == []
        assert resp.available_layer_types == []
        assert resp.temp_range is None

    def test_response_with_items(self) -> None:
        pt = LayeredAnalysis3DPoint(exp_id="e1", name="e1", layer_count=2)
        resp = LayeredAnalysis3DResponse(
            total=1,
            available_layer_types=["interface", "3-layer"],
            available_crystal_materials=["SiO2"],
            available_aging_states=["non_aging"],
            available_binder_types=["AAA1"],
            temp_range=[253.0, 333.0],
            items=[pt],
        )
        assert resp.total == 1
        assert len(resp.items) == 1
        assert resp.temp_range == [253.0, 333.0]

    def test_secondary_binder_fields(self) -> None:
        pt = LayeredAnalysis3DPoint(
            exp_id="e2",
            name="aged-fresh",
            layer_count=3,
            binder_type="AAA1",
            aging_state="long_aging",
            binder_type_secondary="AAA1",
            aging_state_secondary="non_aging",
        )
        assert pt.binder_type_secondary == "AAA1"
        assert pt.aging_state_secondary == "non_aging"


# ---------------------------------------------------------------------------
# Layer type inference tests
# ---------------------------------------------------------------------------


class TestLayerTypeInference:
    """Verify the _LAYER_TYPE_MAP and _infer_layer_type helper."""

    def test_all_patterns(self) -> None:
        from features.layered_structures.service import _LAYER_TYPE_MAP

        expected_types = {
            "interface",
            "water-interface",
            "3-layer",
            "aged-fresh",
            "water-aged-fresh",
            "binder-binder",
        }
        assert set(_LAYER_TYPE_MAP.values()) == expected_types

    def test_interface_pattern(self) -> None:
        from features.layered_structures.service import _LAYER_TYPE_MAP

        assert _LAYER_TYPE_MAP[("crystal_structure", "binder_cell")] == "interface"

    def test_water_interface_pattern(self) -> None:
        from features.layered_structures.service import _LAYER_TYPE_MAP

        assert (
            _LAYER_TYPE_MAP[("crystal_structure", "amorphous_cell", "binder_cell")]
            == "water-interface"
        )

    def test_three_layer_pattern(self) -> None:
        from features.layered_structures.service import _LAYER_TYPE_MAP

        assert (
            _LAYER_TYPE_MAP[("crystal_structure", "binder_cell", "crystal_structure")] == "3-layer"
        )

    def test_unknown_pattern_returns_none(self) -> None:
        from features.layered_structures.service import _LAYER_TYPE_MAP

        assert _LAYER_TYPE_MAP.get(("binder_cell",)) is None


# ---------------------------------------------------------------------------
# Router registration test
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Verify the analysis 3D route is registered."""

    def test_route_exists(self) -> None:
        from features.layered_structures.router import router

        paths = [r.path for r in router.routes]
        assert "/layered-structures/analysis/3d" in paths


# ---------------------------------------------------------------------------
# Seeded service behavior tests (in-memory SQLite)
# ---------------------------------------------------------------------------


def _seed_db(session: Session) -> None:
    """Seed the DB with two layered experiments for filter/limit testing.

    Experiment 1 (newest): interface — crystal(SiO2) + binder(A1_X1_NA_none_298K_h1)
    Experiment 2 (older):  aged-fresh — crystal(SiO2) + binder_aged(A1_X1_LA_none_298K_h2)
                                                       + binder_fresh(A1_X1_NA_none_298K_h3)
    """
    # Crystal structure
    crystal = CrystalStructureModel(
        crystal_id="SiO2_001_preset",
        name="SiO2 (001)",
        source_type="preset",
        material="SiO2",
        surface="001",
        atom_count=1000,
    )
    session.add(crystal)

    # Binder source experiment (for exp_id parsing: A1 → AAA1 via BINDER_ABBREV_REVERSE)
    binder_src = ExperimentModel(
        exp_id="A1_X1_NA_none_298K_h1",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        temperature_K=298.0,
        comp_saturate_wt=15.0,
        comp_aromatic_wt=35.0,
        comp_resin_wt=32.0,
        comp_asphaltene_wt=18.0,
    )
    binder_aged = ExperimentModel(
        exp_id="A1_X1_LA_none_298K_h2",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        temperature_K=298.0,
        comp_saturate_wt=15.0,
        comp_aromatic_wt=35.0,
        comp_resin_wt=32.0,
        comp_asphaltene_wt=18.0,
    )
    binder_fresh = ExperimentModel(
        exp_id="A1_X1_NA_none_298K_h3",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        temperature_K=298.0,
        comp_saturate_wt=15.0,
        comp_aromatic_wt=35.0,
        comp_resin_wt=32.0,
        comp_asphaltene_wt=18.0,
    )
    session.add_all([binder_src, binder_aged, binder_fresh])

    # Layered experiment 1: interface (newest)
    exp1 = ExperimentModel(
        exp_id="layered_interface_001",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        temperature_K=298.0,
        comp_saturate_wt=15.0,
        comp_aromatic_wt=35.0,
        comp_resin_wt=32.0,
        comp_asphaltene_wt=18.0,
    )
    session.add(exp1)
    session.flush()
    exp1.completed_at = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)

    # Layered experiment 2: aged-fresh (older)
    exp2 = ExperimentModel(
        exp_id="layered_aged_fresh_001",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        temperature_K=298.0,
        comp_saturate_wt=15.0,
        comp_aromatic_wt=35.0,
        comp_resin_wt=32.0,
        comp_asphaltene_wt=18.0,
    )
    session.add(exp2)
    session.flush()
    exp2.completed_at = datetime(2026, 3, 22, 9, 0, 0, tzinfo=UTC)

    # Sources for exp1: crystal + binder (interface)
    session.add_all(
        [
            LayeredExperimentSourceModel(
                exp_id="layered_interface_001",
                layer_index=0,
                source_type="crystal_structure",
                source_id="SiO2_001_preset",
            ),
            LayeredExperimentSourceModel(
                exp_id="layered_interface_001",
                layer_index=1,
                source_type="binder_cell",
                source_id="A1_X1_NA_none_298K_h1",
            ),
        ]
    )

    # Sources for exp2: crystal + binder_aged + binder_fresh (aged-fresh)
    session.add_all(
        [
            LayeredExperimentSourceModel(
                exp_id="layered_aged_fresh_001",
                layer_index=0,
                source_type="crystal_structure",
                source_id="SiO2_001_preset",
            ),
            LayeredExperimentSourceModel(
                exp_id="layered_aged_fresh_001",
                layer_index=1,
                source_type="binder_cell",
                source_id="A1_X1_LA_none_298K_h2",
            ),
            LayeredExperimentSourceModel(
                exp_id="layered_aged_fresh_001",
                layer_index=2,
                source_type="binder_cell",
                source_id="A1_X1_NA_none_298K_h3",
            ),
        ]
    )

    # Metric for exp1
    session.add(
        MetricModel(
            experiment_id=exp1.id,
            exp_id="layered_interface_001",
            metric_name="work_of_separation",
            namespace="mechanical",
            value=125.0,
            unit="mJ/m2",
        )
    )
    session.flush()


@pytest.fixture()
def seeded_session():
    """In-memory SQLite with seeded layered experiments."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        _seed_db(session)
        session.commit()
        yield session


class TestLayeredAnalysis3DService:
    """Service behavior tests with seeded in-memory DB."""

    def _call(self, session, **kwargs):
        """Call the service function inside the given session."""
        from features.layered_structures.service import get_layered_analysis_3d

        # Patch run_in_session to use our test session
        def fake_run(fn):
            return fn(session)

        with patch("features.common.run_in_session", side_effect=fake_run):
            return get_layered_analysis_3d(**kwargs)

    def test_returns_both_experiments(self, seeded_session):
        result = self._call(seeded_session)
        assert result["total"] == 2
        exp_ids = {it["exp_id"] for it in result["items"]}
        assert "layered_interface_001" in exp_ids
        assert "layered_aged_fresh_001" in exp_ids

    def test_layer_type_uses_contract_tokens(self, seeded_session):
        result = self._call(seeded_session)
        types = {it["layer_type"] for it in result["items"]}
        assert "interface" in types
        assert "aged-fresh" in types
        # Must NOT contain underscore versions
        assert "aged_fresh" not in types

    def test_binder_abbreviation_normalized(self, seeded_session):
        """parse_exp_id returns 'A1'; service must normalize to 'AAA1'."""
        result = self._call(seeded_session)
        binder_types = {it["binder_type"] for it in result["items"]}
        assert "AAA1" in binder_types
        assert "A1" not in binder_types

    def test_aged_fresh_has_secondary_fields(self, seeded_session):
        result = self._call(seeded_session)
        af = next(it for it in result["items"] if it["layer_type"] == "aged-fresh")
        assert af["aging_state"] == "long_aging"
        assert af["aging_state_secondary"] == "non_aging"
        assert af["binder_type_secondary"] == "AAA1"

    def test_categorical_filter_precedes_limit(self, seeded_session):
        """With limit=1, aged-fresh filter should still return the matching item."""
        result = self._call(seeded_session, layer_types=["aged-fresh"], limit=1)
        assert result["total"] == 1
        assert result["items"][0]["layer_type"] == "aged-fresh"

    def test_aging_filter_matches_secondary(self, seeded_session):
        """aging_states=['non_aging'] should match the aged-fresh item
        whose secondary aging is non_aging."""
        result = self._call(seeded_session, aging_states=["non_aging"])
        exp_ids = {it["exp_id"] for it in result["items"]}
        # Interface has primary non_aging → matches
        assert "layered_interface_001" in exp_ids
        # Aged-fresh has secondary non_aging → also matches
        assert "layered_aged_fresh_001" in exp_ids

    def test_crystal_material_in_response(self, seeded_session):
        result = self._call(seeded_session)
        assert "SiO2" in result["available_crystal_materials"]
        for it in result["items"]:
            assert it["crystal_material"] == "SiO2"

    def test_metric_work_of_separation(self, seeded_session):
        result = self._call(seeded_session)
        iface = next(it for it in result["items"] if it["layer_type"] == "interface")
        assert iface["work_of_separation"] == 125.0
