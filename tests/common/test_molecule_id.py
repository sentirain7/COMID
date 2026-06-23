"""
Tests for molecule ID parsing and validation utilities.
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from common.molecule_id import (
    AGING_PREFIXES,
    SARA_PREFIXES,
    build_aging_mol_id,
    get_aging_category,
    get_sara_category,
    parse_molecule_id,
    validate_molecule_id,
)


class TestParseMoleculeId:
    """Tests for parse_molecule_id function."""

    def test_parse_base_id_saturate(self):
        """Test parsing base ID for saturate molecule."""
        parsed = parse_molecule_id("SA-Squalane")
        assert parsed.aging_prefix is None
        assert parsed.sara_prefix == "SA"
        assert parsed.name == "Squalane"
        assert parsed.temp_code is None
        assert parsed.sara_category == "saturate"
        assert parsed.base_id == "SA-Squalane"
        assert not parsed.is_aged

    def test_parse_base_id_aromatic(self):
        """Test parsing base ID for aromatic molecule."""
        parsed = parse_molecule_id("AR-PHPN")
        assert parsed.aging_prefix is None
        assert parsed.sara_prefix == "AR"
        assert parsed.name == "PHPN"
        assert parsed.temp_code is None
        assert parsed.sara_category == "aromatic"

    def test_parse_base_id_resin(self):
        """Test parsing base ID for resin molecule."""
        parsed = parse_molecule_id("RE-Benzo")
        assert parsed.aging_prefix is None
        assert parsed.sara_prefix == "RE"
        assert parsed.name == "Benzo"
        assert parsed.sara_category == "resin"

    def test_parse_base_id_asphaltene(self):
        """Test parsing base ID for asphaltene molecule."""
        parsed = parse_molecule_id("AS-Thio")
        assert parsed.aging_prefix is None
        assert parsed.sara_prefix == "AS"
        assert parsed.name == "Thio"
        assert parsed.sara_category == "asphaltene"

    def test_parse_aging_id_non_aging(self):
        """Test parsing aging ID with non-aging prefix."""
        parsed = parse_molecule_id("U-AS-Thio-0293")
        assert parsed.aging_prefix == "U"
        assert parsed.sara_prefix == "AS"
        assert parsed.name == "Thio"
        assert parsed.temp_code == "0293"
        assert parsed.sara_category == "asphaltene"
        assert parsed.aging_category == "non_aging"
        assert parsed.base_id == "AS-Thio"
        assert parsed.full_id == "U-AS-Thio-0293"
        assert parsed.is_aged

    def test_parse_aging_id_short_aging(self):
        """Test parsing aging ID with short-aging prefix."""
        parsed = parse_molecule_id("S-AR-PHPN-0313")
        assert parsed.aging_prefix == "S"
        assert parsed.sara_prefix == "AR"
        assert parsed.name == "PHPN"
        assert parsed.temp_code == "0313"
        assert parsed.aging_category == "short_aging"

    def test_parse_aging_id_long_aging(self):
        """Test parsing aging ID with long-aging prefix."""
        parsed = parse_molecule_id("L-RE-Quin-0373")
        assert parsed.aging_prefix == "L"
        assert parsed.sara_prefix == "RE"
        assert parsed.name == "Quin"
        assert parsed.temp_code == "0373"
        assert parsed.aging_category == "long_aging"

    def test_parse_invalid_empty_string(self):
        """Test parsing empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid molecule ID"):
            parse_molecule_id("")

    def test_parse_invalid_none(self):
        """Test parsing None raises ValueError."""
        with pytest.raises(ValueError, match="Invalid molecule ID"):
            parse_molecule_id(None)

    def test_parse_invalid_format(self):
        """Test parsing invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid molecule ID format"):
            parse_molecule_id("invalid_format")

    def test_parse_invalid_sara_prefix(self):
        """Test parsing invalid SARA prefix raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SARA prefix"):
            parse_molecule_id("XX-Something")

    def test_parse_invalid_aging_sara_prefix(self):
        """Test parsing invalid SARA prefix in aging format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid SARA prefix"):
            parse_molecule_id("U-XX-Something-0293")


class TestGetSaraCategory:
    """Tests for get_sara_category function."""

    def test_get_sara_category_base_id(self):
        """Test getting SARA category from base ID."""
        assert get_sara_category("SA-Squalane") == "saturate"
        assert get_sara_category("AR-PHPN") == "aromatic"
        assert get_sara_category("RE-Thio") == "resin"
        assert get_sara_category("AS-Pyrrole") == "asphaltene"

    def test_get_sara_category_aging_id(self):
        """Test getting SARA category from aging ID."""
        assert get_sara_category("U-SA-Hopane-0293") == "saturate"
        assert get_sara_category("S-AR-DOCHN-0313") == "aromatic"
        assert get_sara_category("L-RE-Pyrid-0373") == "resin"
        assert get_sara_category("U-AS-Phenol-0293") == "asphaltene"


class TestGetAgingCategory:
    """Tests for get_aging_category function."""

    def test_get_aging_category_base_id(self):
        """Test getting aging category from base ID returns None."""
        assert get_aging_category("SA-Squalane") is None
        assert get_aging_category("AS-Thio") is None

    def test_get_aging_category_aging_id(self):
        """Test getting aging category from aging ID."""
        assert get_aging_category("U-AS-Thio-0293") == "non_aging"
        assert get_aging_category("S-AR-PHPN-0313") == "short_aging"
        assert get_aging_category("L-RE-Quin-0373") == "long_aging"


class TestValidateMoleculeId:
    """Tests for validate_molecule_id function."""

    def test_validate_valid_base_ids(self):
        """Test validation of valid base IDs."""
        assert validate_molecule_id("SA-Squalane") is True
        assert validate_molecule_id("AR-PHPN") is True
        assert validate_molecule_id("RE-Benzo") is True
        assert validate_molecule_id("AS-Thio") is True

    def test_validate_valid_aging_ids(self):
        """Test validation of valid aging IDs."""
        assert validate_molecule_id("U-SA-Hopane-0293") is True
        assert validate_molecule_id("S-AR-DOCHN-0313") is True
        assert validate_molecule_id("L-RE-Trim-0373") is True

    def test_validate_invalid_ids(self):
        """Test validation of invalid IDs."""
        assert validate_molecule_id("") is False
        assert validate_molecule_id("invalid") is False
        assert validate_molecule_id("XX-Something") is False
        assert validate_molecule_id("U-XX-Mol-0293") is False


class TestBuildAgingMolId:
    """Tests for build_aging_mol_id function."""

    def test_build_non_aging_id(self):
        """Test building non-aging molecule ID."""
        mol_id = build_aging_mol_id("SA-Squalane", "non_aging", "0293")
        assert mol_id == "U-SA-Squalane-0293"

    def test_build_short_aging_id(self):
        """Test building short-aging molecule ID."""
        mol_id = build_aging_mol_id("AR-PHPN", "short_aging", "0313")
        assert mol_id == "S-AR-PHPN-0313"

    def test_build_long_aging_id(self):
        """Test building long-aging molecule ID."""
        mol_id = build_aging_mol_id("AS-Thio", "long_aging", "0373")
        assert mol_id == "L-AS-Thio-0373"

    def test_build_default_temp_code(self):
        """Test building with default temperature code."""
        mol_id = build_aging_mol_id("RE-Benzo", "non_aging")
        assert mol_id == "U-RE-Benzo-0293"

    def test_build_from_aging_id_raises_error(self):
        """Test building from aging ID raises ValueError."""
        with pytest.raises(ValueError, match="Expected base ID"):
            build_aging_mol_id("U-SA-Squalane-0293", "non_aging")

    def test_build_invalid_aging_category(self):
        """Test building with invalid aging category raises ValueError."""
        with pytest.raises(ValueError, match="Unknown aging category"):
            build_aging_mol_id("SA-Squalane", "invalid_aging")

    def test_build_invalid_base_id(self):
        """Test building with invalid base ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid molecule ID format"):
            build_aging_mol_id("invalid", "non_aging")


class TestParsedMoleculeIdProperties:
    """Tests for ParsedMoleculeId properties."""

    def test_full_id_base(self):
        """Test full_id property for base ID."""
        parsed = parse_molecule_id("SA-Squalane")
        assert parsed.full_id == "SA-Squalane"

    def test_full_id_aging(self):
        """Test full_id property for aging ID."""
        parsed = parse_molecule_id("U-AS-Thio-0293")
        assert parsed.full_id == "U-AS-Thio-0293"

    def test_base_id_from_aging(self):
        """Test base_id property extracts base from aging ID."""
        parsed = parse_molecule_id("S-AR-PHPN-0313")
        assert parsed.base_id == "AR-PHPN"


class TestConstants:
    """Tests for module constants."""

    def test_sara_prefixes(self):
        """Test SARA_PREFIXES contains all valid prefixes."""
        assert SARA_PREFIXES == {"SA", "AR", "RE", "AS"}

    def test_aging_prefixes(self):
        """Test AGING_PREFIXES contains all valid prefixes."""
        assert AGING_PREFIXES == {"U", "S", "L"}
