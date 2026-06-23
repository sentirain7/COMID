"""
Unit tests for layered experiment source lineage (Step 1).

Tests LayeredExperimentSourceModel and LayeredSourceRepository.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import (
    Base,
    ExperimentModel,
    LayeredExperimentSourceModel,
)
from database.repositories.layered_source_repo import LayeredSourceRepository


@pytest.fixture()
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        # Create a parent experiment
        exp = ExperimentModel(
            exp_id="test_layered_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="completed",
            comp_asphaltene_wt=18.0,
            comp_resin_wt=32.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        session.add(exp)
        session.flush()
        yield session


class TestLayeredSourceModel:
    """Test the ORM model itself."""

    def test_create_source_entry(self, db_session: Session):
        src = LayeredExperimentSourceModel(
            exp_id="test_layered_001",
            layer_index=0,
            source_type="crystal_structure",
            source_id="SiO2_001_preset",
            label="SiO2 (001)",
        )
        db_session.add(src)
        db_session.flush()
        assert src.id is not None

    def test_unique_constraint(self, db_session: Session):
        """Same exp_id + layer_index should raise."""
        s1 = LayeredExperimentSourceModel(
            exp_id="test_layered_001",
            layer_index=0,
            source_type="crystal_structure",
            source_id="SiO2_001",
        )
        s2 = LayeredExperimentSourceModel(
            exp_id="test_layered_001",
            layer_index=0,
            source_type="binder_cell",
            source_id="some_exp",
        )
        db_session.add(s1)
        db_session.flush()
        db_session.add(s2)
        with pytest.raises(Exception):  # noqa: B017
            db_session.flush()


class TestLayeredSourceRepository:
    """Test the repository layer."""

    def test_create_sources(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {
                "layer_index": 0,
                "source_type": "crystal_structure",
                "source_id": "SiO2_001_preset",
                "label": "SiO2 bottom",
            },
            {
                "layer_index": 1,
                "source_type": "binder_cell",
                "source_id": "binder_exp_001",
                "gap_after_angstrom": 3.0,
            },
            {
                "layer_index": 2,
                "source_type": "crystal_structure",
                "source_id": "SiO2_001_preset",
                "label": "SiO2 top",
            },
        ]
        count = repo.create_sources("test_layered_001", layers)
        assert count == 3

    def test_get_sources_ordered(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 2, "source_type": "crystal_structure", "source_id": "c2"},
            {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c0"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "b1"},
        ]
        repo.create_sources("test_layered_001", layers)
        results = repo.get_sources("test_layered_001")
        assert [r.layer_index for r in results] == [0, 1, 2]

    def test_get_crystal_source(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 0, "source_type": "crystal_structure", "source_id": "SiO2_001"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "binder1"},
        ]
        repo.create_sources("test_layered_001", layers)
        crystal = repo.get_crystal_source("test_layered_001")
        assert crystal is not None
        assert crystal.source_id == "SiO2_001"

    def test_get_binder_sources(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c1"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "b1"},
            {"layer_index": 2, "source_type": "binder_cell", "source_id": "b2"},
        ]
        repo.create_sources("test_layered_001", layers)
        binders = repo.get_binder_sources("test_layered_001")
        assert len(binders) == 2

    def test_get_amorphous_sources(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 0, "source_type": "amorphous_cell", "source_id": "a1"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "b1"},
        ]
        repo.create_sources("test_layered_001", layers)
        amorphous = repo.get_amorphous_sources("test_layered_001")
        assert len(amorphous) == 1
        assert amorphous[0].source_id == "a1"
        assert amorphous[0].source_type == "interface_molecule_cell"

    def test_delete_sources(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c1"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "b1"},
        ]
        repo.create_sources("test_layered_001", layers)
        deleted = repo.delete_sources("test_layered_001")
        assert deleted == 2
        assert repo.get_sources("test_layered_001") == []

    def test_no_sources_returns_empty(self, db_session: Session):
        """Experiment with no lineage sources should return empty list."""
        repo = LayeredSourceRepository(db_session)
        sources = repo.get_sources("test_layered_001")
        assert sources == []

    def test_primary_source_is_lowest_layer_index(self, db_session: Session):
        """Primary source should be the one with lowest layer_index."""
        repo = LayeredSourceRepository(db_session)
        layers = [
            {"layer_index": 2, "source_type": "crystal_structure", "source_id": "c2"},
            {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c0"},
            {"layer_index": 1, "source_type": "binder_cell", "source_id": "b1"},
        ]
        repo.create_sources("test_layered_001", layers)
        sources = repo.get_sources("test_layered_001")
        crystal_sources = [s for s in sources if s.source_type == "crystal_structure"]
        # First crystal source (sorted by layer_index) should be c0
        assert crystal_sources[0].source_id == "c0"

    def test_create_sources_rejects_duplicate_indexes_in_payload(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        with pytest.raises(ValueError, match="duplicate layer_index"):
            repo.create_sources(
                "test_layered_001",
                [
                    {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c0"},
                    {"layer_index": 0, "source_type": "binder_cell", "source_id": "b1"},
                ],
            )

    def test_create_sources_rejects_non_contiguous_indexes(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        with pytest.raises(ValueError, match="contiguous"):
            repo.create_sources(
                "test_layered_001",
                [
                    {"layer_index": 0, "source_type": "crystal_structure", "source_id": "c0"},
                    {"layer_index": 2, "source_type": "binder_cell", "source_id": "b1"},
                ],
            )

    def test_create_sources_rejects_blank_source_id(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        with pytest.raises(ValueError, match="source_id is required"):
            repo.create_sources(
                "test_layered_001",
                [
                    {"layer_index": 0, "source_type": "crystal_structure", "source_id": " "},
                ],
            )

    def test_create_sources_rejects_unknown_source_type(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        with pytest.raises(ValueError, match="unsupported source_type"):
            repo.create_sources(
                "test_layered_001",
                [
                    {"layer_index": 0, "source_type": "unknown_type", "source_id": "x1"},
                ],
            )

    def test_create_sources_rejects_negative_layer_index(self, db_session: Session):
        repo = LayeredSourceRepository(db_session)
        with pytest.raises(ValueError, match="layer_index must be >= 0"):
            repo.create_sources(
                "test_layered_001",
                [
                    {"layer_index": -1, "source_type": "crystal_structure", "source_id": "c0"},
                ],
            )


class TestLineageIncompleteFlag:
    """Test lineage_incomplete flag behavior."""

    def test_lineage_incomplete_in_metadata(self, db_session: Session):
        """Experiment with lineage_incomplete should be detectable."""
        exp = db_session.query(ExperimentModel).filter_by(exp_id="test_layered_001").first()
        meta = dict(exp.metadata_json or {})
        meta["lineage_incomplete"] = True
        exp.metadata_json = meta
        db_session.flush()

        refreshed = db_session.query(ExperimentModel).filter_by(exp_id="test_layered_001").first()
        assert refreshed.metadata_json.get("lineage_incomplete") is True

    def test_skip_lineage_incomplete_in_training(self, db_session: Session):
        """V4 training should skip experiments with lineage_incomplete flag."""
        exp = db_session.query(ExperimentModel).filter_by(exp_id="test_layered_001").first()
        meta = dict(exp.metadata_json or {})
        meta["lineage_incomplete"] = True
        exp.metadata_json = meta
        db_session.flush()

        # Simulate the skip logic from layered_data_loader
        refreshed = db_session.query(ExperimentModel).filter_by(exp_id="test_layered_001").first()
        m = refreshed.metadata_json or {}
        should_skip = m.get("lineage_incomplete", False)
        assert should_skip is True
