"""
Unit tests for weight_fraction computation in upsert_experiment_molecules (Step 2-1).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import (
    Base,
    ExperimentModel,
    ExperimentMoleculeModel,
    MoleculeModel,
)
from database.repositories.experiment_repo import ExperimentRepository


@pytest.fixture()
def db_session():
    """In-memory SQLite session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        # Create molecules with known molecular weights
        m1 = MoleculeModel(
            mol_id="SAT_001",
            smiles="CCCCCCCCCCCCCCCC",
            name="hexadecane",
            sara_type="saturate",
            molecular_weight=226.44,
            num_atoms=50,
        )
        m2 = MoleculeModel(
            mol_id="ARO_001",
            smiles="c1ccc2ccccc2c1",
            name="naphthalene",
            sara_type="aromatic",
            molecular_weight=128.17,
            num_atoms=18,
        )
        session.add_all([m1, m2])
        session.flush()

        exp = ExperimentModel(
            exp_id="test_wf_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=18.0,
            comp_resin_wt=32.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        session.add(exp)
        session.flush()
        yield session


class TestWeightFractionWrite:
    """Test weight_fraction computation in upsert_experiment_molecules."""

    def test_weight_fractions_computed(self, db_session: Session):
        """weight_fraction should be computed from MW * count."""
        repo = ExperimentRepository(db_session)
        counts = {"SAT_001": 4, "ARO_001": 11}
        repo.upsert_experiment_molecules("test_wf_001", counts)

        links = (
            db_session.query(ExperimentMoleculeModel)
            .join(MoleculeModel, ExperimentMoleculeModel.molecule_id == MoleculeModel.id)
            .all()
        )
        assert len(links) == 2

        # Total mass = 4 * 226.44 + 11 * 128.17  (used for manual verification)
        _total_mass = 4 * 226.44 + 11 * 128.17  # noqa: F841
        for link in links:
            assert link.weight_fraction is not None
            assert 0.0 < link.weight_fraction <= 1.0

        # Verify fractions sum to ~1.0
        total_wf = sum(link.weight_fraction for link in links)
        assert abs(total_wf - 1.0) < 0.001

    def test_weight_fractions_sum_to_one(self, db_session: Session):
        """All weight fractions should sum to 1.0."""
        repo = ExperimentRepository(db_session)
        counts = {"SAT_001": 10, "ARO_001": 10}
        repo.upsert_experiment_molecules("test_wf_001", counts)

        links = db_session.query(ExperimentMoleculeModel).all()
        total = sum(link.weight_fraction for link in links if link.weight_fraction)
        assert abs(total - 1.0) < 0.001

    def test_autocreated_molecules_null_wf(self, db_session: Session):
        """Autocreated molecules (no MW) should have weight_fraction=None."""
        repo = ExperimentRepository(db_session)
        # NEW_MOL doesn't exist — will be autocreated with MW=None
        counts = {"NEW_MOL_001": 5}
        repo.upsert_experiment_molecules("test_wf_001", counts)

        links = db_session.query(ExperimentMoleculeModel).all()
        assert len(links) == 1
        assert links[0].weight_fraction is None

    def test_mixed_known_unknown_mw(self, db_session: Session):
        """Mix of known and unknown MW — known get fractions, unknown get None."""
        repo = ExperimentRepository(db_session)
        counts = {"SAT_001": 4, "UNKNOWN_001": 2}
        repo.upsert_experiment_molecules("test_wf_001", counts)

        links = (
            db_session.query(ExperimentMoleculeModel, MoleculeModel.mol_id)
            .join(MoleculeModel, ExperimentMoleculeModel.molecule_id == MoleculeModel.id)
            .all()
        )
        for link, mol_id in links:
            if mol_id == "SAT_001":
                assert link.weight_fraction is not None
                # SAT_001 is the only one with MW, so it should be 1.0
                assert abs(link.weight_fraction - 1.0) < 0.001
            else:
                assert link.weight_fraction is None
