"""Tests for GAFF2 curated artifact loading (Phase 2)."""

import json
from pathlib import Path

import pytest

from builder.topology_helpers import validate_molecule_topologies
from features.molecules.artifact_service import validate_artifact
from forcefield.organic_curated_artifact import (
    OrganicCuratedArtifact,
    apply_artifact_to_topology,
    clear_artifact_cache,
    load_artifact,
    parse_artifact_payload,
)

_TEST_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "forcefield_artifacts"


@pytest.fixture(autouse=True)
def _gaff2_fixture_dir(monkeypatch):
    """Redirect artifact loading to test fixtures and clear cache."""
    clear_artifact_cache()

    def _mock_get_artifact_directory(ff_family: str = "organic_gaff2") -> Path:
        return _TEST_FIXTURE_DIR / ff_family

    monkeypatch.setattr(
        "forcefield.organic_curated_artifact.get_artifact_directory",
        _mock_get_artifact_directory,
    )
    yield
    clear_artifact_cache()


class TestGAFF2ArtifactLoad:
    """Verify GAFF2 v2 artifact loads correctly."""

    def test_load_gaff2_toluene(self):
        """Load GAFF2 Toluene fixture from organic_gaff2 directory."""
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        assert isinstance(artifact, OrganicCuratedArtifact)
        assert artifact.ff_family == "organic_gaff2"
        assert artifact.charge_model == "am1_bcc"
        assert artifact.mol_id == "Toluene"
        assert len(artifact.atoms) == 15
        assert len(artifact.bond_types) == 4
        assert len(artifact.angle_types) == 5
        assert len(artifact.dihedral_types) == 6
        # Aromatic ring planarity enforced by 2 cvff impropers
        assert len(artifact.improper_types) == 2

    def test_gaff2_dihedral_is_fourier(self):
        """GAFF2 dihedrals use fourier style with d=±1 (not phase degrees)."""
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        for dih in artifact.dihedral_types:
            assert dih.style == "fourier"
            assert len(dih.coeffs) % 3 == 0, "fourier coeffs must be multiples of 3"
            assert len(dih.coeffs) >= 3
            # Verify d values are ±1 (LAMMPS fourier convention), not phase degrees
            for i in range(len(dih.coeffs) // 3):
                d = dih.coeffs[3 * i + 1]
                assert d in (-1.0, 1.0), f"fourier d must be ±1, got {d}"

    def test_gaff2_improper_is_cvff(self):
        """GAFF2 impropers use cvff style."""
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        for imp in artifact.improper_types:
            assert imp.style == "cvff"
            assert len(imp.coeffs) == 3  # k, d, n

    def test_gaff2_atom_types_are_gaff2(self):
        """GAFF2 atom types should be lowercase GAFF2 types."""
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        ff_types = {a.ff_type for a in artifact.atoms}
        assert "ca" in ff_types  # aromatic carbon
        assert "c3" in ff_types  # sp3 carbon
        assert "ha" in ff_types  # aromatic H
        assert "hc" in ff_types  # aliphatic H

    def test_gaff2_toluene_charge_neutrality(self):
        """Toluene GAFF2 fixture must be electrically neutral (AM1-BCC contract)."""
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        total_charge = sum(a.charge for a in artifact.atoms)
        assert total_charge == pytest.approx(0.0, abs=1e-4), (
            f"GAFF2 Toluene charge sum {total_charge:.6f} exceeds ±1e-4 e"
        )

    def test_gaff2_is_the_only_organic_ff(self):
        """GAFF2 is the sole organic FF; artifacts load with correct family."""
        gaff2 = load_artifact("Toluene", ff_family="organic_gaff2")
        assert gaff2.ff_family == "organic_gaff2"
        assert gaff2.dihedral_types[0].style == "fourier"
        assert gaff2.charge_model == "am1_bcc"

    def test_apply_curated_artifact_passes_topology_validation(self):
        """Curated artifact application must satisfy the strict runtime validator.

        Uses test fixture (Toluene) instead of repo artifact to avoid
        dependency on repo artifact existence (fail-closed policy).
        """
        # Use fixture artifact instead of repo artifact (fail-closed policy)
        fixture_artifact_path = _TEST_FIXTURE_DIR / "organic_gaff2" / "Toluene.json"
        if not fixture_artifact_path.exists():
            pytest.skip("Toluene fixture not available")

        artifact = parse_artifact_payload(json.loads(fixture_artifact_path.read_text()))

        # Create a mock topology matching the Toluene artifact structure
        from builder.mol_types import MolAtom, MolBond, MolTopology

        atoms = [
            MolAtom(index=a["index"], element=a["element"], x=0.0, y=0.0, z=0.0)
            for a in json.loads(fixture_artifact_path.read_text())["atoms"]
        ]
        # Add bonds between aromatic carbons (ring) and methyl group
        bonds = [
            MolBond(atom1=5, atom2=6, order=1),  # ca-ca
            MolBond(atom1=6, atom2=7, order=1),
            MolBond(atom1=7, atom2=8, order=1),
            MolBond(atom1=8, atom2=9, order=1),
            MolBond(atom1=9, atom2=10, order=1),
            MolBond(atom1=10, atom2=5, order=1),
            MolBond(atom1=5, atom2=1, order=1),  # ca-c3 (methyl)
            MolBond(atom1=1, atom2=2, order=1),  # c3-hc
            MolBond(atom1=1, atom2=3, order=1),
            MolBond(atom1=1, atom2=4, order=1),
            MolBond(atom1=6, atom2=11, order=1),  # ca-ha
            MolBond(atom1=7, atom2=12, order=1),
            MolBond(atom1=8, atom2=13, order=1),
            MolBond(atom1=9, atom2=14, order=1),
            MolBond(atom1=10, atom2=15, order=1),
        ]
        topology = MolTopology(mol_id="Toluene", atoms=atoms, bonds=bonds, molecular_weight=92.14)

        apply_artifact_to_topology(topology, artifact)

        validate_molecule_topologies([(topology, 1)])


class TestGAFF2ArtifactV2Schema:
    """Verify v2 schema parsing."""

    def test_v2_payload_round_trip(self):
        """v2 payload parses correctly."""
        payload = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "charge_model": "am1_bcc",
            "mol_id": "Test",
            "generator": "test",
            "generator_version": "1.0",
            "provenance": "test",
            "canonical_smiles": "C",
            "formal_charge": 0,
            "topology_hash": "sha256:test",
            "atoms": [{"index": 1, "element": "C", "ff_type": "c3", "charge": 0.0}],
            "bond_types": [],
            "angle_types": [],
            "dihedral_types": [
                {
                    "key": "c3-c3-c3-c3",
                    "style": "fourier",
                    "coeffs": [0.18, 1.0, 3.0, 0.25, -1.0, 1.0],
                }
            ],
            "improper_types": [{"key": "c3-c3-c3-h1", "style": "cvff", "coeffs": [1.1, -1.0, 2.0]}],
        }
        artifact = parse_artifact_payload(payload)
        assert artifact.ff_family == "organic_gaff2"
        assert artifact.dihedral_types[0].style == "fourier"
        assert len(artifact.dihedral_types[0].coeffs) == 6  # 2 fourier terms
        assert artifact.improper_types[0].style == "cvff"

    def test_validate_artifact_marks_charge_mismatch_invalid(self):
        """Artifact validity must match the strict runtime neutrality contract."""
        payload = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "charge_model": "am1_bcc",
            "mol_id": "TestMismatch",
            "generator": "test",
            "generator_version": "1.0",
            "provenance": "test",
            "canonical_smiles": "CC",
            "formal_charge": 0,
            "topology_hash": "sha256:test",
            "atoms": [
                {"index": 1, "element": "C", "ff_type": "c3", "charge": 0.1},
                {"index": 2, "element": "H", "ff_type": "hc", "charge": -0.096},
            ],
            "bond_types": [{"key": "c3-hc", "k": 340.0, "r0": 1.09}],
            "angle_types": [],
            "dihedral_types": [],
            "improper_types": [],
        }
        validation = validate_artifact(payload)
        assert validation["valid"] is False
        assert validation["checks"]["charge_neutrality"]["status"] == "warning"


class TestGAFF2FailClosed:
    """Verify fail-closed behavior for missing GAFF2 artifacts."""

    def test_missing_gaff2_artifact_raises(self):
        """Requesting non-existent GAFF2 artifact must raise ArtifactMissingError."""
        from forcefield.organic_curated_artifact import ArtifactMissingError

        with pytest.raises(ArtifactMissingError):
            load_artifact("NonExistentMolecule_XYZ_99", ff_family="organic_gaff2")
