"""
Molecule ID parsing and validation utilities.

Molecule IDs follow specific naming conventions:
- Base format: {SARA}-{Name} (e.g., "SA-Squalane", "AS-Thio")
- Aging format: {Aging}-{SARA}-{Name}-{TempCode} (e.g., "U-AS-Thio-0293")

SARA prefixes:
- SA: Saturate
- AR: Aromatic
- RE: Resin
- AS: Asphaltene

Aging prefixes:
- U: Unaged (non_aging)
- S: Short-term aged (short_aging)
- L: Long-term aged (long_aging)
"""

import re
from dataclasses import dataclass

# Valid SARA category prefixes
SARA_PREFIXES = {"SA", "AR", "RE", "AS"}

# Valid aging prefixes
AGING_PREFIXES = {"U", "S", "L"}

# SARA prefix to category name mapping
SARA_CATEGORY_MAP = {
    "SA": "saturate",
    "AR": "aromatic",
    "RE": "resin",
    "AS": "asphaltene",
}

# Aging prefix to category name mapping
AGING_CATEGORY_MAP = {
    "U": "non_aging",
    "S": "short_aging",
    "L": "long_aging",
}


@dataclass
class ParsedMoleculeId:
    """Parsed components of a molecule ID."""

    aging_prefix: str | None  # U, S, L or None for base IDs
    sara_prefix: str  # SA, AR, RE, AS
    name: str  # Squalane, PHPN, Thio, etc.
    temp_code: str | None  # 0293, 0313, etc. or None for base IDs

    @property
    def base_id(self) -> str:
        """Get the base molecule ID (without aging prefix and temp code)."""
        return f"{self.sara_prefix}-{self.name}"

    @property
    def sara_category(self) -> str:
        """Get the SARA category name."""
        return SARA_CATEGORY_MAP.get(self.sara_prefix, "unknown")

    @property
    def aging_category(self) -> str | None:
        """Get the aging category name if aging prefix is present."""
        if self.aging_prefix is None:
            return None
        return AGING_CATEGORY_MAP.get(self.aging_prefix)

    @property
    def full_id(self) -> str:
        """Get the full molecule ID."""
        if self.aging_prefix and self.temp_code:
            return f"{self.aging_prefix}-{self.sara_prefix}-{self.name}-{self.temp_code}"
        return self.base_id

    @property
    def is_aged(self) -> bool:
        """Check if this is an aged molecule ID."""
        return self.aging_prefix is not None


def parse_molecule_id(mol_id: str) -> ParsedMoleculeId:
    """
    Parse a molecule ID into its components.

    Args:
        mol_id: Molecule ID string in either base or aging format

    Returns:
        ParsedMoleculeId with extracted components

    Raises:
        ValueError: If the molecule ID format is invalid

    Examples:
        >>> parse_molecule_id("SA-Squalane")
        ParsedMoleculeId(aging_prefix=None, sara_prefix='SA', name='Squalane', temp_code=None)

        >>> parse_molecule_id("U-AS-Thio-0293")
        ParsedMoleculeId(aging_prefix='U', sara_prefix='AS', name='Thio', temp_code='0293')
    """
    if not mol_id or not isinstance(mol_id, str):
        raise ValueError(f"Invalid molecule ID: {mol_id}")

    # Try aging format first: {Aging}-{SARA}-{Name}-{TempCode}
    # Pattern: U-AS-Thio-0293
    aging_pattern = re.match(r"^([USL])-([A-Z]{2})-([A-Za-z0-9]+)-(\d{4})$", mol_id)
    if aging_pattern:
        aging_prefix, sara_prefix, name, temp_code = aging_pattern.groups()

        if sara_prefix not in SARA_PREFIXES:
            raise ValueError(f"Invalid SARA prefix '{sara_prefix}' in molecule ID: {mol_id}")

        return ParsedMoleculeId(
            aging_prefix=aging_prefix,
            sara_prefix=sara_prefix,
            name=name,
            temp_code=temp_code,
        )

    # Try base format: {SARA}-{Name}
    # Pattern: SA-Squalane, AS-Thio
    base_pattern = re.match(r"^([A-Z]{2})-([A-Za-z0-9]+)$", mol_id)
    if base_pattern:
        sara_prefix, name = base_pattern.groups()

        if sara_prefix not in SARA_PREFIXES:
            raise ValueError(f"Invalid SARA prefix '{sara_prefix}' in molecule ID: {mol_id}")

        return ParsedMoleculeId(
            aging_prefix=None,
            sara_prefix=sara_prefix,
            name=name,
            temp_code=None,
        )

    raise ValueError(
        f"Invalid molecule ID format: '{mol_id}'. "
        f"Expected 'SARA-Name' (e.g., 'SA-Squalane') or "
        f"'Aging-SARA-Name-TempCode' (e.g., 'U-AS-Thio-0293')"
    )


def get_sara_category(mol_id: str) -> str:
    """
    Extract SARA category from any molecule ID format.

    Args:
        mol_id: Molecule ID string in either base or aging format

    Returns:
        SARA category name: 'saturate', 'aromatic', 'resin', or 'asphaltene'

    Raises:
        ValueError: If the molecule ID format is invalid

    Examples:
        >>> get_sara_category("SA-Squalane")
        'saturate'

        >>> get_sara_category("U-AS-Thio-0293")
        'asphaltene'
    """
    parsed = parse_molecule_id(mol_id)
    return parsed.sara_category


def get_aging_category(mol_id: str) -> str | None:
    """
    Extract aging category from a molecule ID.

    Args:
        mol_id: Molecule ID string

    Returns:
        Aging category name or None for base IDs

    Examples:
        >>> get_aging_category("U-AS-Thio-0293")
        'non_aging'

        >>> get_aging_category("SA-Squalane")
        None
    """
    parsed = parse_molecule_id(mol_id)
    return parsed.aging_category


def validate_molecule_id(mol_id: str) -> bool:
    """
    Check if a molecule ID is valid.

    Args:
        mol_id: Molecule ID string to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        parse_molecule_id(mol_id)
        return True
    except ValueError:
        return False


def build_aging_mol_id(base_id: str, aging: str, temp_code: str = "0293") -> str:
    """
    Build a full aging molecule ID from components.

    Args:
        base_id: Base molecule ID (e.g., "SA-Squalane")
        aging: Aging category ("non_aging", "short_aging", "long_aging")
        temp_code: Temperature code (default: "0293")

    Returns:
        Full molecule ID (e.g., "U-SA-Squalane-0293")

    Raises:
        ValueError: If base_id is invalid or aging category is unknown
    """
    # Parse base_id to validate and extract components
    parsed = parse_molecule_id(base_id)

    if parsed.is_aged:
        raise ValueError(f"Expected base ID but got aging ID: {base_id}")

    # Map aging category to prefix
    aging_to_prefix = {
        "non_aging": "U",
        "short_aging": "S",
        "long_aging": "L",
    }

    prefix = aging_to_prefix.get(aging)
    if prefix is None:
        raise ValueError(f"Unknown aging category: {aging}")

    return f"{prefix}-{parsed.sara_prefix}-{parsed.name}-{temp_code}"
