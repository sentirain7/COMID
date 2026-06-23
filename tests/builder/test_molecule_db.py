"""
Unit tests for molecule database with aging library support.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from builder.molecule_db import MoleculeDB
from contracts.schemas import MoleculeCategory, MoleculeSpec

# Path to test data
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "molecules"
CONFIG_PATH = DATA_DIR / "molecule_library.yaml"


class TestMoleculeDBBasic:
    """Test basic MoleculeDB functionality."""

    def test_create_db(self, tmp_path: Path) -> None:
        """Test creating a new molecule database."""
        db = MoleculeDB(db_path=tmp_path / "molecules")
        assert db.count() == 0

    def test_add_and_get_molecule(self, tmp_path: Path) -> None:
        """Test adding and retrieving a molecule."""
        db = MoleculeDB(db_path=tmp_path / "molecules")
        spec = MoleculeSpec(
            mol_id="test_mol",
            smiles="CCCC",
            molecular_weight=58.12,
            atom_count=14,
            category=MoleculeCategory.SATURATE,
            structure_file="test.mol",
            topology_hash="abcd1234",
        )
        db.add(spec)
        retrieved = db.get("test_mol")
        assert retrieved is not None
        assert retrieved.mol_id == "test_mol"
        assert retrieved.molecular_weight == 58.12

    def test_has_molecule(self, tmp_path: Path) -> None:
        """Test checking if molecule exists."""
        db = MoleculeDB(db_path=tmp_path / "molecules")
        spec = MoleculeSpec(
            mol_id="exists",
            smiles="C",
            molecular_weight=16.04,
            atom_count=5,
            category=MoleculeCategory.SATURATE,
            structure_file="exists.mol",
            topology_hash="hash1234",
        )
        db.add(spec)
        assert db.has("exists") is True
        assert db.has("not_exists") is False

    def test_get_structure_file_resolves_data_molecules_relative_path(self, tmp_path, monkeypatch):
        """Relative structure_file entries should resolve under data/molecules."""
        from contracts.schemas import MoleculeCategory, MoleculeSpec

        project_root = tmp_path / "project"
        mol_path = project_root / "data" / "molecules" / "additives" / "sample.mol"
        mol_path.parent.mkdir(parents=True, exist_ok=True)
        mol_path.write_text("sample")

        monkeypatch.setattr("builder.molecule_db.get_project_root", lambda: project_root)

        db = MoleculeDB(db_path=tmp_path / "molecules")
        spec = MoleculeSpec(
            mol_id="sample",
            smiles="[sample]",
            molecular_weight=1.0,
            atom_count=1,
            category=MoleculeCategory.ADDITIVE,
            structure_file="additives/sample.mol",
            topology_hash="hash0001",
        )
        db.add(spec)

        resolved = db.get_structure_file("sample", "mol")
        assert resolved == mol_path


@pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
class TestAgingLibrary:
    """Test aging library loading and query functionality."""

    def test_load_aging_library(self) -> None:
        """Test loading the aging molecule library from YAML config."""
        db = MoleculeDB()
        count = db.load_aging_library(CONFIG_PATH)

        # Should load molecules from all aging categories
        assert count > 0

        # Check that molecules from different aging states are loaded
        all_mols = db.list_all()
        u_mols = [m for m in all_mols if m.startswith("U-")]
        s_mols = [m for m in all_mols if m.startswith("S-")]
        l_mols = [m for m in all_mols if m.startswith("L-")]

        # Should have molecules in all three aging categories
        assert len(u_mols) > 0, "No non-aging molecules loaded"
        assert len(s_mols) > 0, "No short-aging molecules loaded"
        assert len(l_mols) > 0, "No long-aging molecules loaded"

    def test_molecule_spec_fields(self) -> None:
        """Test that loaded molecules have correct spec fields."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)

        # Get a specific molecule
        mol = db.get("U-AS-Thio-0293")
        if mol is None:
            # Try with different available molecule
            all_mols = db.list_all()
            u_as_mols = [m for m in all_mols if m.startswith("U-AS-")]
            assert len(u_as_mols) > 0, "No U-AS molecules loaded"
            mol = db.get(u_as_mols[0])

        assert mol is not None
        assert mol.mol_id.startswith("U-")
        assert mol.category == MoleculeCategory.ASPHALTENE
        assert mol.atom_count > 0
        assert mol.molecular_weight > 0
        assert len(mol.topology_hash) == 8

    def test_saturate_only_in_non_aging(self) -> None:
        """Test that saturates are only in non-aging category."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)

        all_mols = db.list_all()

        # Saturates should only exist with U- prefix (non-aging)
        sa_mols = [m for m in all_mols if "-SA-" in m]
        for mol_id in sa_mols:
            assert mol_id.startswith("U-"), f"Saturate {mol_id} should only be non-aging"

    def test_fallback_saturate(self) -> None:
        """Test fallback mechanism for saturates in aged categories."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)
        config = db.get_aging_config(CONFIG_PATH)

        # Try to get saturate with short_aging - should fallback to non_aging
        mol = db.get_with_fallback("SA-Hopane", "short_aging", config)

        if mol is not None:
            # Should get the non-aging version via fallback
            assert mol.mol_id.startswith("U-"), "Fallback should return non-aging molecule"
            assert mol.category == MoleculeCategory.SATURATE

    def test_fallback_for_long_aging(self) -> None:
        """Test fallback for long aging category."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)
        config = db.get_aging_config(CONFIG_PATH)

        # Try to get saturate with long_aging - should fallback to non_aging
        mol = db.get_with_fallback("SA-Squalane", "long_aging", config)

        if mol is not None:
            assert mol.mol_id.startswith("U-"), "Fallback should return non-aging molecule"

    def test_no_fallback_needed(self) -> None:
        """Test direct lookup without fallback."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)
        config = db.get_aging_config(CONFIG_PATH)

        # Asphaltenes should exist in all aging categories
        mol = db.get_with_fallback("AS-Thio", "short_aging", config)

        if mol is not None:
            # Should get short-aging version directly
            assert mol.mol_id.startswith("S-"), "Should get short-aging version directly"

    def test_list_by_aging(self) -> None:
        """Test listing molecules by aging category."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)
        config = db.get_aging_config(CONFIG_PATH)

        non_aging = db.list_by_aging("non_aging", config)
        short_aging = db.list_by_aging("short_aging", config)
        long_aging = db.list_by_aging("long_aging", config)

        # All should have molecules
        assert len(non_aging) > 0
        assert len(short_aging) > 0
        assert len(long_aging) > 0

        # Verify prefixes
        for mol_id in non_aging:
            assert mol_id.startswith("U-")
        for mol_id in short_aging:
            assert mol_id.startswith("S-")
        for mol_id in long_aging:
            assert mol_id.startswith("L-")

    def test_get_structure_file_aging(self) -> None:
        """Test getting structure file path for aging library molecule."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)

        # Get any loaded molecule
        all_mols = db.list_all()
        if not all_mols:
            pytest.skip("No molecules loaded")

        mol_id = all_mols[0]
        structure_path = db.get_structure_file_aging(mol_id, CONFIG_PATH)

        if structure_path is not None:
            assert structure_path.exists()
            assert structure_path.suffix == ".mol"


@pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
class TestMolFileParsing:
    """Test MOL file parsing functionality."""

    def test_parse_mol_file(self) -> None:
        """Test parsing a MOL file for atom count and molecular weight."""
        db = MoleculeDB()

        # Find a MOL file
        mol_files = list(DATA_DIR.glob("**/*.mol"))
        if not mol_files:
            pytest.skip("No MOL files found")

        mol_file = mol_files[0]
        atom_count, mw = db._parse_mol_file(mol_file)

        assert atom_count > 0, "Atom count should be positive"
        assert mw > 0, "Molecular weight should be positive"

    def test_parse_mol_file_asphaltene(self) -> None:
        """Test parsing an asphaltene MOL file."""
        db = MoleculeDB()

        # Find an asphaltene MOL file
        mol_files = list((DATA_DIR / "Non_Aging_Moles").glob("U-AS-*/*.mol"))
        if not mol_files:
            pytest.skip("No asphaltene MOL files found")

        mol_file = mol_files[0]
        atom_count, mw = db._parse_mol_file(mol_file)

        # Asphaltenes typically have 50-150 atoms and MW > 500
        assert atom_count > 30, "Asphaltene should have many atoms"
        assert mw > 200, "Asphaltene should have significant molecular weight"


class TestConfigValidation:
    """Test config file validation."""

    def test_config_not_found(self, tmp_path: Path) -> None:
        """Test error when config file not found."""
        db = MoleculeDB()
        with pytest.raises(FileNotFoundError):
            db.load_aging_library(tmp_path / "nonexistent.yaml")

    def test_get_aging_config_not_found(self, tmp_path: Path) -> None:
        """Test error when getting config that doesn't exist."""
        db = MoleculeDB()
        with pytest.raises(FileNotFoundError):
            db.get_aging_config(tmp_path / "nonexistent.yaml")

    @pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
    def test_get_aging_config_success(self) -> None:
        """Test successfully loading aging config."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        assert "library" in config
        assert "aging_categories" in config
        assert "molecules" in config
        assert config["library"]["name"] == "asphalt_aging"


@pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
class TestIntegration:
    """Integration tests for aging library."""

    def test_full_workflow(self) -> None:
        """Test complete workflow: load, query, fallback."""
        db = MoleculeDB()

        # Load library
        count = db.load_aging_library(CONFIG_PATH)
        assert count > 0

        # Get config and verify it's valid
        config = db.get_aging_config(CONFIG_PATH)
        assert "aging_categories" in config

        # Query by category
        asphaltenes = db.get_by_category(MoleculeCategory.ASPHALTENE)
        resins = db.get_by_category(MoleculeCategory.RESIN)
        aromatics = db.get_by_category(MoleculeCategory.AROMATIC)
        saturates = db.get_by_category(MoleculeCategory.SATURATE)

        # Should have molecules in each category
        assert len(asphaltenes) > 0, "Should have asphaltenes"
        assert len(resins) > 0, "Should have resins"
        assert len(aromatics) > 0, "Should have aromatics"
        assert len(saturates) > 0, "Should have saturates"

    def test_temperature_variants(self) -> None:
        """Test loading molecules with different temperature variants."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)

        all_mols = db.list_all()

        # Check for different temperature codes
        temp_codes = set()
        for mol_id in all_mols:
            # Extract temperature code (last 4 digits before suffix)
            parts = mol_id.split("-")
            if len(parts) >= 3:
                temp_codes.add(parts[-1])

        # Should have multiple temperature variants
        assert len(temp_codes) > 1, "Should have multiple temperature variants"

    def test_molecule_counts_by_aging(self) -> None:
        """Test molecule counts match expected distribution."""
        db = MoleculeDB()
        db.load_aging_library(CONFIG_PATH)
        config = db.get_aging_config(CONFIG_PATH)

        non_aging = db.list_by_aging("non_aging", config)
        short_aging = db.list_by_aging("short_aging", config)
        long_aging = db.list_by_aging("long_aging", config)

        # Non-aging should have more (includes saturates)
        # Short and long aging should have equal counts (no saturates)
        assert len(non_aging) >= len(short_aging)
        assert len(non_aging) >= len(long_aging)


@pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
class TestBinderComposition:
    """Test binder composition functions from YAML config (SSOT)."""

    def test_get_binder_composition_x1(self) -> None:
        """Test getting AAA1 binder composition for X1 size."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        composition = db.get_binder_composition(config, "AAA1", "X1")

        # Verify total matches Table 1 from Li & Greenfield (2014)
        assert sum(composition.values()) == 72

        # Verify specific counts from Table 1
        assert composition["SA-Squalane"] == 4
        assert composition["SA-Hopane"] == 4
        assert composition["AR-PHPN"] == 11
        assert composition["AR-DOCHN"] == 13
        assert composition["RE-Quin"] == 4
        assert composition["RE-Pyrid"] == 4
        assert composition["RE-Thio"] == 4
        assert composition["RE-Benzo"] == 15
        assert composition["RE-Trim"] == 5
        assert composition["AS-Pyrrole"] == 2
        assert composition["AS-Phenol"] == 3
        assert composition["AS-Thio"] == 3

    def test_get_binder_composition_x2(self) -> None:
        """Test getting AAA1 binder composition for X2 size (2x)."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        composition = db.get_binder_composition(config, "AAA1", "X2")

        # Total should be 144 (2x of 72)
        assert sum(composition.values()) == 144

        # Each count should be 2x of X1
        assert composition["SA-Squalane"] == 8
        assert composition["AR-PHPN"] == 22
        assert composition["RE-Benzo"] == 30
        assert composition["AS-Pyrrole"] == 4

    def test_get_binder_composition_x3(self) -> None:
        """Test getting AAA1 binder composition for X3 size (3x)."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        composition = db.get_binder_composition(config, "AAA1", "X3")

        # Total should be 216 (3x of 72)
        assert sum(composition.values()) == 216

        # Each count should be 3x of X1
        assert composition["SA-Squalane"] == 12
        assert composition["AR-PHPN"] == 33
        assert composition["RE-Benzo"] == 45
        assert composition["AS-Pyrrole"] == 6

    def test_get_binder_composition_invalid_type(self) -> None:
        """Test error handling for invalid binder type."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        with pytest.raises(ValueError) as exc_info:
            db.get_binder_composition(config, "INVALID", "X1")
        assert "Unknown binder type" in str(exc_info.value)

    def test_get_binder_composition_invalid_size(self) -> None:
        """Test error handling for invalid size."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        with pytest.raises(ValueError) as exc_info:
            db.get_binder_composition(config, "AAA1", "X4")
        assert "Invalid size" in str(exc_info.value)

    def test_get_binder_composition_with_aging(self) -> None:
        """Test getting composition with aging prefix and temperature."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        # Non-aging composition
        non_aging_comp = db.get_binder_composition_with_aging(
            config, "AAA1", "X1", "non_aging", "0293"
        )

        # All should have U- prefix
        for mol_id in non_aging_comp.keys():
            assert mol_id.startswith("U-"), f"{mol_id} should start with U-"
            assert mol_id.endswith("-0293"), f"{mol_id} should end with -0293"

        # Total should still be 72
        assert sum(non_aging_comp.values()) == 72

    def test_get_binder_composition_with_aging_fallback(self) -> None:
        """Test that saturates fallback to non_aging in short_aging."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        # Short-aging composition
        short_aging_comp = db.get_binder_composition_with_aging(
            config, "AAA1", "X1", "short_aging", "0293"
        )

        # Count prefixes
        u_count = sum(1 for k in short_aging_comp if k.startswith("U-"))
        s_count = sum(1 for k in short_aging_comp if k.startswith("S-"))

        # Saturates (2 types) should fallback to U- prefix
        assert u_count == 2, "Saturates should fallback to non_aging"
        # Others (10 types) should have S- prefix
        assert s_count == 10, "Non-saturates should have short_aging prefix"

    def test_get_binder_types(self) -> None:
        """Test getting available binder types."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        binder_types = db.get_binder_types(config)

        assert "AAA1" in binder_types

    def test_get_binder_totals(self) -> None:
        """Test getting total molecule counts."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        totals = db.get_binder_totals(config, "AAA1")

        assert totals["X1"] == 72
        assert totals["X2"] == 144
        assert totals["X3"] == 216

    def test_get_sara_fractions(self) -> None:
        """Test getting SARA weight fractions."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        fractions = db.get_sara_fractions(config, "AAA1")

        assert "saturate" in fractions
        assert "aromatic" in fractions
        assert "resin" in fractions
        assert "asphaltene" in fractions

        # Sum should be approximately 1.0
        total = sum(fractions.values())
        assert 0.99 < total < 1.01, f"SARA fractions should sum to ~1.0, got {total}"

    def test_get_structure_sizes(self) -> None:
        """Test getting structure size definitions."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        sizes = db.get_structure_sizes(config)

        assert "X1" in sizes
        assert "X2" in sizes
        assert "X3" in sizes

        assert sizes["X1"]["multiplier"] == 1
        assert sizes["X2"]["multiplier"] == 2
        assert sizes["X3"]["multiplier"] == 3

        # X3 should be recommended for RDF
        assert "rdf" in sizes["X3"]["recommended_for"]


@pytest.mark.skipif(not CONFIG_PATH.exists(), reason="Aging library config not found")
class TestSaraAggregation:
    """Test SARA category aggregation methods."""

    def test_get_binder_composition_by_sara_x1(self) -> None:
        """Test SARA category aggregation for X1 size."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        sara_counts = db.get_binder_composition_by_sara(config, "AAA1", "X1")

        # Verify from Li & Greenfield (2014) Table 1:
        # Saturates: 4 + 4 = 8
        assert sara_counts["saturate"] == 8

        # Aromatics: 11 + 13 = 24
        assert sara_counts["aromatic"] == 24

        # Resins: 4 + 4 + 4 + 15 + 5 = 32
        assert sara_counts["resin"] == 32

        # Asphaltenes: 2 + 3 + 3 = 8
        assert sara_counts["asphaltene"] == 8

        # Total should be 72
        assert sum(sara_counts.values()) == 72

    def test_get_binder_composition_by_sara_x3(self) -> None:
        """Test SARA category aggregation for X3 size (3x)."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        sara_counts = db.get_binder_composition_by_sara(config, "AAA1", "X3")

        # All values should be 3x of X1
        assert sara_counts["saturate"] == 24
        assert sara_counts["aromatic"] == 72
        assert sara_counts["resin"] == 96
        assert sara_counts["asphaltene"] == 24

        # Total should be 216
        assert sum(sara_counts.values()) == 216

    def test_get_molecule_atom_count(self) -> None:
        """Test getting atom count from YAML config."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        # Test specific molecules from YAML (SSOT)
        assert db.get_molecule_atom_count(config, "SA-Squalane") == 62
        assert db.get_molecule_atom_count(config, "SA-Hopane") == 54
        assert db.get_molecule_atom_count(config, "AS-Pyrrole") == 100

        # Test default for unknown molecule
        assert db.get_molecule_atom_count(config, "UNKNOWN") == 50
        assert db.get_molecule_atom_count(config, "UNKNOWN", default=100) == 100

    def test_get_molecule_molecular_weight(self) -> None:
        """Test getting molecular weight from YAML config."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        # Test specific molecules from YAML (SSOT)
        assert db.get_molecule_molecular_weight(config, "SA-Squalane") == 422.81
        assert db.get_molecule_molecular_weight(config, "AS-Pyrrole") == 888.35

        # Test default for unknown molecule
        assert db.get_molecule_molecular_weight(config, "UNKNOWN") == 500.0

    def test_get_additive_atom_count(self) -> None:
        """Test getting additive atom count from YAML config."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        # Test specific additives from YAML (SSOT)
        assert db.get_additive_atom_count(config, "SiO2") == 57
        assert db.get_additive_atom_count(config, "Lignin") == 350

        # Test default for unknown additive
        assert db.get_additive_atom_count(config, "UNKNOWN") == 50

    def test_get_all_molecule_atom_counts(self) -> None:
        """Test getting all molecule atom counts as dictionary."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        atom_counts = db.get_all_molecule_atom_counts(config)

        # Should contain baseline binder molecules (>=12) plus optional extensions.
        assert len(atom_counts) >= 12

        # Verify specific values
        assert atom_counts["SA-Squalane"] == 62
        assert atom_counts["SA-Hopane"] == 54
        assert atom_counts["AR-PHPN"] == 60
        assert atom_counts["AR-DOCHN"] == 50
        assert atom_counts["AS-Pyrrole"] == 100
        assert atom_counts["AS-Phenol"] == 90
        assert atom_counts["AS-Thio"] == 95

        # Non-binder probe molecules
        assert atom_counts["AR-H2O"] == 3
        assert atom_counts["RE-NaCl"] == 2
        assert atom_counts["AR-O2"] == 2
        assert atom_counts["AR-Toluene"] == 15
        assert atom_counts["SA-nHeptane"] == 23

    def test_calculate_total_atoms_x1(self) -> None:
        """Test calculating total atoms for X1 composition."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        total_atoms = db.calculate_total_atoms(config, "AAA1", "X1")

        # Calculate expected total manually:
        # SA-Squalane: 4 * 62 = 248
        # SA-Hopane: 4 * 54 = 216
        # AR-PHPN: 11 * 60 = 660
        # AR-DOCHN: 13 * 50 = 650
        # RE-Quin: 4 * 65 = 260
        # RE-Pyrid: 4 * 55 = 220
        # RE-Thio: 4 * 50 = 200
        # RE-Benzo: 15 * 45 = 675
        # RE-Trim: 5 * 40 = 200
        # AS-Pyrrole: 2 * 100 = 200
        # AS-Phenol: 3 * 90 = 270
        # AS-Thio: 3 * 95 = 285
        # Total: 4084
        expected = 248 + 216 + 660 + 650 + 260 + 220 + 200 + 675 + 200 + 200 + 270 + 285
        assert total_atoms == expected

    def test_calculate_total_atoms_with_additives(self) -> None:
        """Test calculating total atoms including additives."""
        db = MoleculeDB()
        config = db.get_aging_config(CONFIG_PATH)

        additives = [
            {"mol_id": "SiO2", "count": 2},  # 2 * 57 = 114
            {"mol_id": "Lignin", "count": 1},  # 1 * 350 = 350
        ]

        total_with_additives = db.calculate_total_atoms(config, "AAA1", "X1", additives=additives)

        base_total = db.calculate_total_atoms(config, "AAA1", "X1")
        expected_additive_atoms = 2 * 57 + 1 * 350

        assert total_with_additives == base_total + expected_additive_atoms
