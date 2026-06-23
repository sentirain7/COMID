"""Tests for EIntraRepository temperature tolerance fallback."""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from contracts.policies.forcefield import get_ff_version
from contracts.schemas import EIntraKey, EIntraValue
from database.connection import init_memory_db
from database.models import MoleculeModel
from database.repositories.e_intra_repo import EIntraRepository


def _seed_molecule(session, mol_id: str = "mol_001") -> None:
    session.add(
        MoleculeModel(
            mol_id=mol_id,
            smiles="C",
            name="methane",
            sara_type="saturate",
        )
    )
    session.flush()


def test_get_prefers_exact_temperature_match() -> None:
    session = init_memory_db()
    _seed_molecule(session)
    repo = EIntraRepository(session)
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=298.0),
        EIntraValue(e_intra=-100.0),
    )
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=300.0),
        EIntraValue(e_intra=-120.0),
    )

    value = repo.get(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=300.0)
    )
    assert value == pytest.approx(-120.0)


def test_get_uses_nearest_match_within_tolerance() -> None:
    session = init_memory_db()
    _seed_molecule(session)
    repo = EIntraRepository(session)
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=298.0),
        EIntraValue(e_intra=-100.0),
    )

    value = repo.get(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=299.5)
    )
    assert value == pytest.approx(-100.0)


def test_get_returns_none_outside_tolerance() -> None:
    session = init_memory_db()
    _seed_molecule(session)
    repo = EIntraRepository(session)
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=298.0),
        EIntraValue(e_intra=-100.0),
    )

    value = repo.get(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=310.0)
    )
    assert value is None


def test_get_for_molecules_uses_nearest_per_molecule() -> None:
    session = init_memory_db()
    _seed_molecule(session, "mol_001")
    _seed_molecule(session, "mol_002")
    repo = EIntraRepository(session)
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=298.0),
        EIntraValue(e_intra=-100.0),
    )
    repo.set(
        EIntraKey(mol_id="mol_002", ff_name="GAFF2", ff_version="1.0", temperature_K=301.0),
        EIntraValue(e_intra=-80.0),
    )

    values = repo.get_for_molecules(["mol_001", "mol_002"], "GAFF2", "1.0", 300.0)
    assert values["mol_001"] == pytest.approx(-100.0)
    assert values["mol_002"] == pytest.approx(-80.0)


def test_default_coverage_uses_canonical_gaff2_version() -> None:
    session = init_memory_db()
    _seed_molecule(session)
    repo = EIntraRepository(session)
    canonical_version = get_ff_version("bulk_ff_gaff2")

    repo.set(
        EIntraKey(
            mol_id="mol_001",
            ff_name="GAFF2",
            ff_version=canonical_version,
            temperature_K=213.0,
        ),
        EIntraValue(e_intra=-100.0),
    )
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=233.0),
        EIntraValue(e_intra=-200.0),
    )

    coverage = repo.get_coverage("mol_001", required_temperatures=[213.0, 233.0])

    assert coverage["computed_count"] == 1
    assert coverage["missing_temperatures_k"] == [233.0]
    assert coverage["latest_values_by_temperature"][213.0] == pytest.approx(-100.0)


def test_delete_by_mol_id_is_ff_specific_and_delete_all_removes_all_versions() -> None:
    session = init_memory_db()
    _seed_molecule(session)
    repo = EIntraRepository(session)
    canonical_version = get_ff_version("bulk_ff_gaff2")

    repo.set(
        EIntraKey(
            mol_id="mol_001",
            ff_name="GAFF2",
            ff_version=canonical_version,
            temperature_K=213.0,
        ),
        EIntraValue(e_intra=-100.0),
    )
    repo.set(
        EIntraKey(mol_id="mol_001", ff_name="GAFF2", ff_version="1.0", temperature_K=213.0),
        EIntraValue(e_intra=-200.0),
    )

    assert repo.count() == 2
    assert repo.delete_by_mol_id("mol_001") == 1
    assert repo.count() == 1
    assert repo.delete_all_by_mol_id("mol_001") == 1
    assert repo.count() == 0
