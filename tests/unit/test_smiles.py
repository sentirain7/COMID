"""
Unit tests for SMILES Utilities.
"""

import pytest

from forcefield.smiles_utils import (
    MoleculeSearcher,
    SMILESValidator,
    ValidationLevel,
    compute_smiles_hash,
    validate_smiles,
)


class TestSMILESValidator:
    """Tests for SMILESValidator."""

    def test_validate_simple_alkane(self):
        """Test validating simple alkane."""
        validator = SMILESValidator()
        info = validator.validate("CCCC")

        assert info.is_valid
        assert info.carbon_count == 4
        assert info.smiles_hash != ""
        assert not info.error_message

    def test_validate_branched_alkane(self):
        """Test validating branched alkane."""
        validator = SMILESValidator()
        info = validator.validate("CC(C)C")

        assert info.is_valid
        assert info.carbon_count == 4

    def test_validate_aromatic(self):
        """Test validating aromatic compound."""
        validator = SMILESValidator()
        info = validator.validate("c1ccccc1")  # benzene

        assert info.is_valid
        assert info.carbon_count == 6
        assert info.aromatic_ring_count > 0

    def test_validate_naphthalene(self):
        """Test validating naphthalene."""
        validator = SMILESValidator()
        info = validator.validate("c1ccc2ccccc2c1")

        assert info.is_valid
        assert info.carbon_count == 10

    def test_validate_heteroatoms(self):
        """Test validating molecules with heteroatoms."""
        validator = SMILESValidator()

        # Nitrogen
        info = validator.validate("c1ccncc1")  # pyridine
        assert info.is_valid
        assert info.nitrogen_count == 1

        # Oxygen
        info = validator.validate("CCO")  # ethanol
        assert info.is_valid
        assert info.oxygen_count == 1

        # Sulfur
        info = validator.validate("c1ccc2sccc2c1")  # benzothiophene
        assert info.is_valid
        assert info.sulfur_count == 1

    def test_validate_bracket_atoms(self):
        """Test validating bracket atoms."""
        validator = SMILESValidator()

        # Explicit hydrogen
        info = validator.validate("[CH4]")
        assert info.is_valid

        # Charged atom
        info = validator.validate("[NH4+]")
        assert info.is_valid

    def test_validate_halogens(self):
        """Test validating halogenated compounds."""
        validator = SMILESValidator()

        info = validator.validate("CCCl")  # chloroethane
        assert info.is_valid
        assert info.halogen_count >= 1

        info = validator.validate("CCBr")  # bromoethane
        assert info.is_valid
        assert info.halogen_count >= 1

    def test_validate_stereochemistry(self):
        """Test detecting stereochemistry."""
        validator = SMILESValidator()

        info = validator.validate("C/C=C/C")  # E-2-butene
        assert info.is_valid
        assert info.has_stereochemistry

        info = validator.validate("C[C@H](O)F")  # chiral center
        assert info.is_valid
        assert info.has_stereochemistry

    def test_validate_mixture(self):
        """Test validating mixtures."""
        validator = SMILESValidator()

        info = validator.validate("CC.CCC")  # ethane + propane
        assert info.is_valid
        assert info.is_mixture

    def test_invalid_empty(self):
        """Test invalid empty string."""
        validator = SMILESValidator()

        info = validator.validate("")
        assert not info.is_valid
        assert "Empty" in info.error_message

        info = validator.validate(None)
        assert not info.is_valid

    def test_invalid_unbalanced_brackets(self):
        """Test invalid unbalanced brackets."""
        validator = SMILESValidator()

        info = validator.validate("[CH3")
        assert not info.is_valid
        assert "bracket" in info.error_message.lower()

        info = validator.validate("C(C")
        assert not info.is_valid
        assert "parenthes" in info.error_message.lower()

    def test_invalid_unbalanced_rings(self):
        """Test invalid unbalanced ring closures."""
        validator = SMILESValidator()

        info = validator.validate("C1CCC")  # Ring 1 never closed
        assert not info.is_valid
        assert "ring" in info.error_message.lower()

    def test_estimated_molecular_weight(self):
        """Test molecular weight estimation."""
        validator = SMILESValidator()

        # Methane: C=12, H*4=4, total ~16
        info = validator.validate("C")
        assert info.is_valid
        mw = info.estimated_molecular_weight
        assert 10 < mw < 25  # Rough estimate

        # Benzene: C*6=72, H*6=6, total ~78
        info = validator.validate("c1ccccc1")
        assert info.is_valid
        mw = info.estimated_molecular_weight
        assert 60 < mw < 100

    def test_heavy_atom_count(self):
        """Test heavy atom counting."""
        validator = SMILESValidator()

        # Ethanol: 2 C + 1 O = 3
        info = validator.validate("CCO")
        assert info.is_valid
        assert info.heavy_atom_count == 3

    def test_validation_levels(self):
        """Test different validation levels."""
        # Basic level
        basic = SMILESValidator(ValidationLevel.BASIC)
        info = basic.validate("CCCC")
        assert info.is_valid

        # Structure level
        structure = SMILESValidator(ValidationLevel.STRUCTURE)
        info = structure.validate("c1ccccc1")
        assert info.is_valid

        # Full level
        full = SMILESValidator(ValidationLevel.FULL)
        info = full.validate("CCO")
        assert info.is_valid


class TestValidateSmiles:
    """Tests for validate_smiles function."""

    def test_convenience_function(self):
        """Test convenience function."""
        info = validate_smiles("CCCC")
        assert info.is_valid
        assert info.carbon_count == 4


class TestComputeSmilesHash:
    """Tests for compute_smiles_hash function."""

    def test_hash_consistency(self):
        """Test hash is consistent."""
        hash1 = compute_smiles_hash("CCCC")
        hash2 = compute_smiles_hash("CCCC")
        assert hash1 == hash2

    def test_hash_different_smiles(self):
        """Test different SMILES give different hashes."""
        hash1 = compute_smiles_hash("CCCC")
        hash2 = compute_smiles_hash("CCCCC")
        assert hash1 != hash2

    def test_hash_whitespace_handling(self):
        """Test whitespace is stripped."""
        hash1 = compute_smiles_hash("CCCC")
        hash2 = compute_smiles_hash("  CCCC  ")
        assert hash1 == hash2


class TestMoleculeSearcher:
    """Tests for MoleculeSearcher."""

    @pytest.fixture
    def sample_molecules(self):
        """Sample molecule data."""
        return [
            {
                "mol_id": "SAT_001",
                "sara_type": "saturate",
                "smiles": "CCCCCCCCCCCCCCCC",
                "molecular_weight": 226.44,
                "num_atoms": 50,
            },
            {
                "mol_id": "ARO_001",
                "sara_type": "aromatic",
                "smiles": "c1ccc2ccccc2c1",
                "molecular_weight": 128.17,
                "num_atoms": 18,
            },
            {
                "mol_id": "RES_001",
                "sara_type": "resin",
                "smiles": "c1ccc2sccc2c1",
                "molecular_weight": 134.20,
                "num_atoms": 15,
            },
            {
                "mol_id": "ASP_001",
                "sara_type": "asphaltene",
                "smiles": "c1cc2ccc3ccc4ccc5ccc6ccc1c7c2c3c4c5c67",
                "molecular_weight": 300.35,
                "num_atoms": 36,
            },
        ]

    def test_get_by_id(self, sample_molecules):
        """Test get by mol_id."""
        searcher = MoleculeSearcher(sample_molecules)

        mol = searcher.get_by_id("SAT_001")
        assert mol is not None
        assert mol["sara_type"] == "saturate"

        mol = searcher.get_by_id("NONEXISTENT")
        assert mol is None

    def test_get_by_smiles(self, sample_molecules):
        """Test get by SMILES."""
        searcher = MoleculeSearcher(sample_molecules)

        mol = searcher.get_by_smiles("c1ccc2ccccc2c1")  # naphthalene
        assert mol is not None
        assert mol["mol_id"] == "ARO_001"

    def test_search_by_sara(self, sample_molecules):
        """Test search by SARA type."""
        searcher = MoleculeSearcher(sample_molecules)

        aromatics = searcher.search_by_sara("aromatic")
        assert len(aromatics) == 1
        assert aromatics[0]["mol_id"] == "ARO_001"

        saturates = searcher.search_by_sara("saturate")
        assert len(saturates) == 1

        unknowns = searcher.search_by_sara("unknown")
        assert len(unknowns) == 0

    def test_search_by_mw_range(self, sample_molecules):
        """Test search by molecular weight range."""
        searcher = MoleculeSearcher(sample_molecules)

        # All molecules
        results = searcher.search_by_mw_range(0, 500)
        assert len(results) == 4

        # Only small molecules
        results = searcher.search_by_mw_range(0, 150)
        assert len(results) == 2  # ARO_001 and RES_001

        # Only large molecules
        results = searcher.search_by_mw_range(200, 400)
        assert len(results) == 2  # SAT_001 and ASP_001

    def test_search_by_atom_count(self, sample_molecules):
        """Test search by atom count."""
        searcher = MoleculeSearcher(sample_molecules)

        # Small molecules
        results = searcher.search_by_atom_count(0, 20)
        assert len(results) == 2  # ARO_001 and RES_001

        # Large molecules
        results = searcher.search_by_atom_count(30, 100)
        assert len(results) == 2  # SAT_001 and ASP_001

    def test_search_by_elements_required(self, sample_molecules):
        """Test search by required elements."""
        searcher = MoleculeSearcher(sample_molecules)

        # Molecules with sulfur
        results = searcher.search_by_elements(required={"S"})
        assert len(results) == 1
        assert results[0]["mol_id"] == "RES_001"

    def test_search_by_elements_excluded(self, sample_molecules):
        """Test search by excluded elements."""
        searcher = MoleculeSearcher(sample_molecules)

        # Molecules without sulfur
        results = searcher.search_by_elements(excluded={"S"})
        assert len(results) == 3  # All except RES_001

    def test_find_similar(self, sample_molecules):
        """Test finding similar molecules."""
        searcher = MoleculeSearcher(sample_molecules)

        # Find similar to naphthalene
        similar = searcher.find_similar("c1ccc2ccccc2c1")
        assert len(similar) > 0

        # First result should be naphthalene itself
        assert similar[0][0]["mol_id"] == "ARO_001"
        assert similar[0][1] > 0.9  # High similarity


class TestIntegration:
    """Integration tests for SMILES utilities."""

    def test_asphalt_molecules(self):
        """Test with typical asphalt molecules."""
        validator = SMILESValidator()

        # Hexadecane (saturate)
        info = validator.validate("CCCCCCCCCCCCCCCC")
        assert info.is_valid
        assert info.carbon_count == 16

        # Naphthalene (aromatic)
        info = validator.validate("c1ccc2ccccc2c1")
        assert info.is_valid
        assert info.aromatic_ring_count > 0

        # Benzothiophene (resin)
        info = validator.validate("c1ccc2sccc2c1")
        assert info.is_valid
        assert info.sulfur_count == 1

        # Coronene (asphaltene)
        info = validator.validate("c1cc2ccc3ccc4ccc5ccc6ccc1c7c2c3c4c5c67")
        assert info.is_valid
        assert info.carbon_count == 24

    def test_full_molecule_library(self):
        """Test loading and searching full molecule library."""
        from pathlib import Path

        import yaml

        lib_path = (
            Path(__file__).parent.parent.parent / "data" / "molecules" / "molecule_library.yaml"
        )
        if not lib_path.exists():
            pytest.skip("Molecule library not found")

        with open(lib_path) as f:
            lib_data = yaml.safe_load(f)

        molecules = lib_data.get("molecules", [])

        searcher = MoleculeSearcher(molecules)

        # Test SARA type searches
        saturates = searcher.search_by_sara("saturate")
        aromatics = searcher.search_by_sara("aromatic")
        resins = searcher.search_by_sara("resin")
        asphaltenes = searcher.search_by_sara("asphaltene")

        assert len(saturates) > 0
        assert len(aromatics) > 0
        assert len(resins) > 0
        assert len(asphaltenes) > 0
