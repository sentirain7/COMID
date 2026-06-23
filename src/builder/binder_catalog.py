"""
Binder composition and SARA catalog utilities.

Standalone functions for binder composition lookup, SARA aggregation,
atom count calculation, and temperature code resolution.

Extracted from molecule_db.py following the same pattern as mol_parser.py.
"""

from typing import Any


def get_binder_composition(
    config: dict[str, Any], binder_type: str = "AAA1", size: str = "X1"
) -> dict[str, int]:
    """
    Get molecule counts for a specific binder type and structure size.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")
        size: Structure size ("X1", "X2", or "X3")

    Returns:
        Dict mapping mol_id (base_id) to molecule count

    Raises:
        ValueError: If binder_type or size is invalid
    """
    binder_types = config.get("binder_types", {})
    if binder_type not in binder_types:
        available = list(binder_types.keys())
        raise ValueError(f"Unknown binder type: {binder_type}. Available: {available}")

    size_index = {"X1": 0, "X2": 1, "X3": 2}.get(size)
    if size_index is None:
        raise ValueError(f"Invalid size: {size}. Must be X1, X2, or X3")

    composition = binder_types[binder_type].get("composition", {})
    return {mol_id: counts[size_index] for mol_id, counts in composition.items()}


def get_binder_composition_with_aging(
    config: dict[str, Any],
    binder_type: str = "AAA1",
    size: str = "X1",
    aging: str = "non_aging",
    temp_code: str = "0293",
) -> dict[str, int]:
    """
    Get molecule counts with full mol_id including aging prefix and temperature.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")
        size: Structure size ("X1", "X2", or "X3")
        aging: Aging category ("non_aging", "short_aging", "long_aging")
        temp_code: Temperature code (e.g., "0293")

    Returns:
        Dict mapping full mol_id (e.g., "U-AS-Thio-0293") to molecule count
    """
    base_composition = get_binder_composition(config, binder_type, size)
    aging_categories = config.get("aging_categories", {})
    aging_info = aging_categories.get(aging, {})
    prefix = aging_info.get("prefix", "U")
    fallback_to = aging_info.get("fallback_to")

    result = {}
    for base_id, count in base_composition.items():
        # Determine the appropriate prefix based on molecule availability
        mol_def = _find_molecule_def(config, base_id)
        if mol_def:
            available_aging = mol_def.get("available_aging", ["non_aging"])
            if aging in available_aging:
                full_mol_id = f"{prefix}-{base_id}-{temp_code}"
            elif fallback_to and fallback_to in available_aging:
                # Use fallback prefix (e.g., saturates fallback to non_aging)
                fallback_info = aging_categories.get(fallback_to, {})
                fallback_prefix = fallback_info.get("prefix", "U")
                full_mol_id = f"{fallback_prefix}-{base_id}-{temp_code}"
            else:
                # Default to non_aging prefix
                full_mol_id = f"U-{base_id}-{temp_code}"
        else:
            full_mol_id = f"{prefix}-{base_id}-{temp_code}"

        result[full_mol_id] = count

    return result


def _find_molecule_def(config: dict[str, Any], base_id: str) -> dict[str, Any] | None:
    """Find molecule definition in config by base_id.

    Args:
        config: Loaded YAML config dict
        base_id: Base molecule ID (e.g., "SA-Squalane")

    Returns:
        Molecule definition dict or None if not found
    """
    molecules = config.get("molecules", [])
    for mol_def in molecules:
        if mol_def.get("base_id") == base_id:
            return dict(mol_def)
    return None


def get_binder_composition_by_sara(
    config: dict[str, Any], binder_type: str = "AAA1", size: str = "X1"
) -> dict[str, int]:
    """
    Get molecule counts aggregated by SARA category.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")
        size: Structure size ("X1", "X2", or "X3")

    Returns:
        Dict mapping SARA category to total molecule count
        e.g., {"saturate": 8, "aromatic": 24, "resin": 32, "asphaltene": 8}
    """
    composition = get_binder_composition(config, binder_type, size)
    sara_mapping = config.get("sara_mapping", {})

    sara_counts: dict[str, int] = {
        "saturate": 0,
        "aromatic": 0,
        "resin": 0,
        "asphaltene": 0,
    }

    for mol_id, count in composition.items():
        # Extract SARA prefix from mol_id (e.g., "SA" from "SA-Squalane")
        prefix = mol_id.split("-")[0] if "-" in mol_id else ""
        sara_type = sara_mapping.get(prefix, "unknown")

        if sara_type in sara_counts:
            sara_counts[sara_type] += count

    return sara_counts


def get_sara_fractions(config: dict[str, Any], binder_type: str = "AAA1") -> dict[str, float]:
    """
    Get SARA weight fractions for a binder type.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")

    Returns:
        Dict mapping SARA category to weight fraction
    """
    binder_types = config.get("binder_types", {})
    if binder_type not in binder_types:
        return {}
    return dict(binder_types[binder_type].get("sara_fractions", {}))


def get_binder_types(config: dict[str, Any]) -> list[str]:
    """
    Get list of available binder types.

    Args:
        config: Loaded YAML config dict

    Returns:
        List of binder type names
    """
    return list(config.get("binder_types", {}).keys())


def get_binder_totals(config: dict[str, Any], binder_type: str = "AAA1") -> dict[str, int]:
    """
    Get total molecule counts for each structure size.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")

    Returns:
        Dict mapping size to total molecules (e.g., {"X1": 72, "X2": 144, "X3": 216})
    """
    binder_types = config.get("binder_types", {})
    if binder_type not in binder_types:
        return {}
    return dict(binder_types[binder_type].get("totals", {}))


def get_structure_sizes(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Get structure size definitions from config.

    Args:
        config: Loaded YAML config dict

    Returns:
        Dict of structure size definitions
    """
    return dict(config.get("structure_sizes", {}))


def get_valid_structure_sizes(config: dict[str, Any], binder_type: str) -> list[str]:
    """
    Get valid structure sizes for a binder type from YAML config (SSOT).

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type name (e.g., "AAA1")

    Returns:
        List of valid size names (e.g., ["X1", "X2", "X3"])
    """
    binder_data = config.get("binder_types", {}).get(binder_type, {})
    totals = binder_data.get("totals", {})
    return list(totals.keys())


def calculate_total_atoms(
    config: dict[str, Any],
    binder_type: str = "AAA1",
    size: str = "X1",
    additives: list[dict[str, Any]] | None = None,
) -> int:
    """
    Calculate total estimated atoms for a binder composition.

    Args:
        config: Loaded YAML config dict
        binder_type: Binder type (e.g., "AAA1")
        size: Structure size ("X1", "X2", or "X3")
        additives: Optional list of additives with mol_id and count

    Returns:
        Total estimated atom count
    """
    composition = get_binder_composition(config, binder_type, size)
    atom_counts = get_all_molecule_atom_counts(config)

    total = 0
    for mol_id, count in composition.items():
        atom_count = atom_counts.get(mol_id, 50)
        total += count * atom_count

    # Add additives if provided
    if additives:
        for additive in additives:
            add_id = additive.get("mol_id", "")
            add_count = additive.get("count", 0)
            add_atoms = get_additive_atom_count(config, add_id)
            total += add_count * add_atoms

    return total


def get_molecule_atom_count(config: dict[str, Any], mol_id: str, default: int = 50) -> int:
    """
    Get atom count for a molecule from YAML config (SSOT).

    Args:
        config: Loaded YAML config dict
        mol_id: Base molecule ID (e.g., "SA-Squalane")
        default: Default value if not found

    Returns:
        Atom count from config or default
    """
    molecules = config.get("molecules", [])
    for mol in molecules:
        if mol.get("base_id") == mol_id:
            return int(mol.get("atom_count", default))
    return default


def get_all_molecule_atom_counts(config: dict[str, Any]) -> dict[str, int]:
    """
    Get atom counts for all molecules as a dictionary.

    Args:
        config: Loaded YAML config dict

    Returns:
        Dict mapping base_id to atom_count
    """
    result: dict[str, int] = {}
    molecules = config.get("molecules", [])
    for mol in molecules:
        base_id = mol.get("base_id")
        atom_count = mol.get("atom_count", 50)
        if base_id:
            result[base_id] = atom_count
    return result


def get_molecule_molecular_weight(
    config: dict[str, Any], mol_id: str, default: float = 500.0
) -> float:
    """
    Get molecular weight for a molecule from YAML config (SSOT).

    Args:
        config: Loaded YAML config dict
        mol_id: Base molecule ID (e.g., "SA-Squalane")
        default: Default value if not found

    Returns:
        Molecular weight from config or default
    """
    molecules = config.get("molecules", [])
    for mol in molecules:
        if mol.get("base_id") == mol_id:
            return float(mol.get("molecular_weight", default))
    return default


def get_additive_atom_count(config: dict[str, Any], additive_id: str, default: int = 50) -> int:
    """
    Get atom count for an additive from YAML config (SSOT).

    Args:
        config: Loaded YAML config dict
        additive_id: Additive ID (e.g., "SiO2", "Lignin")
        default: Default value if not found

    Returns:
        Atom count from config or default
    """
    additives = config.get("additives", {})
    if additive_id in additives:
        return int(additives[additive_id].get("atom_count", default))
    return default


def get_temperature_code(
    config: dict[str, Any], temperature_k: float, pressure_index: int = 0
) -> str:
    """
    Convert temperature (K) to temp_code using YAML config (SSOT).

    The temp_code format is {pressure_index}{temperature_kelvin} (4 digits).
    For example, 293K at pressure index 0 -> "0293".

    Args:
        config: Loaded YAML config dict containing temperature_codes
        temperature_k: Temperature in Kelvin (e.g., 298.0)
        pressure_index: Pressure index (0-5), default 0

    Returns:
        Temperature code string (e.g., "0293")

    Example:
        >>> get_temperature_code(config, 293.0)
        "0293"
        >>> get_temperature_code(config, 298.0)  # rounds to 293
        "0293"
    """
    temp_codes = config.get("temperature_codes", {})
    rounded_temp = round(temperature_k)

    # Build reverse lookup: temperature -> code (for given pressure index)
    target_prefix = str(pressure_index)
    available_temps: dict[int, str] = {}
    for code, temp in temp_codes.items():
        if code.startswith(target_prefix):
            available_temps[temp] = code

    # Find closest available temperature
    if available_temps:
        closest_temp = min(available_temps.keys(), key=lambda t: abs(t - rounded_temp))
        return available_temps[closest_temp]

    # Fallback: generate code directly (e.g., 293 -> "0293")
    return f"{pressure_index}{rounded_temp:03d}"
