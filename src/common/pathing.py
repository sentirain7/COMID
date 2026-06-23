"""
Path management utilities - SSOT for path conventions.

All sessions must use these functions for path construction.
"""

import hashlib
from pathlib import Path

# Default base directories (can be overridden via environment)
DEFAULT_PROJECT_ROOT = Path.cwd()
DEFAULT_COMPOSITIONS_DIR = "compositions"
DEFAULT_MOLECULES_DIR = "molecules"
DEFAULT_ARRAYS_DIR = "data/arrays"
DEFAULT_CACHE_DIR = "cache"
DEFAULT_CRYSTAL_STRUCTURES_DIR = "data/crystal_structures"
DEFAULT_AMORPHOUS_CELLS_DIR = "database/amorphous_cells"
DEFAULT_FF_CACHE_DIR = "~/.asphalt_agent/ff_cache"


def get_project_root() -> Path:
    """Get project root directory."""
    import os

    return Path(os.environ.get("ASPHALT_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))


def get_experiment_path(exp_id: str, subdir: str | None = None, create: bool = False) -> Path:
    """
    Get path for experiment data.

    Directory structure:
    compositions/{binder_abbrev}/{additive}/{exp_id}/{input|output|analysis}/

    Args:
        exp_id: Experiment ID
        subdir: Subdirectory (input, output, analysis)
        create: Create directory if not exists

    Returns:
        Path to experiment directory
    """
    # Parse exp_id to extract components
    # Format: {binder}_{size}_{additive}_{temp}K_{hash6}
    parsed = parse_exp_id(exp_id)

    # Extract binder abbreviation (first part)
    binder_id = str(parsed.get("binder_type") or "unknown")

    # Extract additive
    additive = str(parsed.get("additive") or "base")

    root = get_project_root()
    base_path = root / DEFAULT_COMPOSITIONS_DIR / binder_id / additive / exp_id

    if subdir:
        path = base_path / subdir
    else:
        path = base_path

    if create:
        path.mkdir(parents=True, exist_ok=True)

    return path


def get_molecule_path(
    mol_id: str, category: str | None = None, filename: str | None = None
) -> Path:
    """
    Get path for molecule files.

    Directory structure:
    molecules/{category}/{mol_id}/{filename}

    Args:
        mol_id: Molecule ID
        category: SARA category or additive
        filename: Optional specific filename

    Returns:
        Path to molecule file/directory
    """
    root = get_project_root()
    base_path = root / DEFAULT_MOLECULES_DIR

    if category:
        base_path = base_path / category

    base_path = base_path / mol_id

    if filename:
        return base_path / filename
    return base_path


def get_array_storage_path(exp_id: str, metric_name: str, create: bool = False) -> Path:
    """
    Get path for array metric storage.

    Directory structure:
    data/arrays/{exp_id}/{metric_name}.parquet

    Args:
        exp_id: Experiment ID
        metric_name: Metric name
        create: Create directory if not exists

    Returns:
        Path to array file
    """
    root = get_project_root()
    base_path = root / DEFAULT_ARRAYS_DIR / exp_id

    if create:
        base_path.mkdir(parents=True, exist_ok=True)

    return base_path / f"{metric_name}.parquet"


def get_cache_path(cache_type: str, key: str, extension: str = "json") -> Path:
    """
    Get path for cache files.

    Directory structure:
    cache/{cache_type}/{key}.{extension}

    Args:
        cache_type: Type of cache (e_intra, topology, etc.)
        key: Cache key
        extension: File extension

    Returns:
        Path to cache file
    """
    root = get_project_root()
    cache_path = root / DEFAULT_CACHE_DIR / cache_type

    # Sanitize key for filename
    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)

    return cache_path / f"{safe_key}.{extension}"


def get_crystal_structure_path(
    crystal_id: str,
    filename: str | None = None,
    create: bool = False,
) -> Path:
    """
    Get path for persisted crystal structure artifacts.

    Directory structure:
    data/crystal_structures/{crystal_id}/{filename}

    Args:
        crystal_id: Crystal structure ID
        filename: Optional specific filename
        create: Create directory if not exists

    Returns:
        Path to crystal structure directory or file
    """
    root = get_project_root()
    base_path = root / DEFAULT_CRYSTAL_STRUCTURES_DIR / crystal_id

    if create:
        base_path.mkdir(parents=True, exist_ok=True)

    if filename:
        return base_path / filename
    return base_path


def get_amorphous_cell_path(
    amorphous_id: str,
    filename: str | None = None,
    create: bool = False,
) -> Path:
    """
    Get path for persisted amorphous cell artifacts.

    Directory structure:
    database/amorphous_cells/{amorphous_id}/{filename}

    Args:
        amorphous_id: Amorphous cell ID
        filename: Optional specific filename
        create: Create directory if not exists

    Returns:
        Path to amorphous cell directory or file
    """
    root = get_project_root()
    base_path = root / DEFAULT_AMORPHOUS_CELLS_DIR / amorphous_id

    if create:
        base_path.mkdir(parents=True, exist_ok=True)

    if filename:
        return base_path / filename
    return base_path


def get_ff_cache_path() -> Path:
    """
    Get force field cache directory path.

    Default: ~/.asphalt_agent/ff_cache
    Override via FF_CACHE_DIR environment variable.

    Returns:
        Path to force field cache directory
    """
    import os

    cache_dir = os.environ.get("FF_CACHE_DIR", DEFAULT_FF_CACHE_DIR)
    return Path(cache_dir).expanduser()


# Binder abbreviation mapping for exp_id format
BINDER_ABBREV = {
    "AAA1": "A1",
    "AAK1": "K1",
    "AAM1": "M1",
    "custom": "C",
}

# Aging state abbreviation mapping
AGING_ABBREV = {
    "non_aging": "NA",
    "short_aging": "SA",
    "long_aging": "LA",
}

# Reverse mappings for parsing
BINDER_ABBREV_REVERSE = {v: k for k, v in BINDER_ABBREV.items()}
AGING_ABBREV_REVERSE = {v: k for k, v in AGING_ABBREV.items()}


def exp_id_to_material_id(exp_id: str) -> str:
    """
    Extract material_id from experiment ID.

    Converts exp_id (A1_X1_NA_none_298K_hash) back to material_id format (AAA1_X1_non_aging).
    For amorphous exp_ids (H2O_ppp_298K_d1.00_hash), returns the molecule ID directly.

    Args:
        exp_id: Experiment ID string

    Returns:
        Material ID string (e.g., AAA1_X1_non_aging or H2O)
    """
    parsed = parse_exp_id(exp_id)

    # Amorphous format: structure_size holds boundary_mode (ppp/ppf)
    structure_size = str(parsed.get("structure_size") or "X1")
    if structure_size in _AMORPHOUS_BOUNDARY_MODES:
        return str(parsed.get("binder_type") or "unknown")

    # Binder format
    binder_abbrev = str(parsed.get("binder_type") or "A1")
    binder_type = BINDER_ABBREV_REVERSE.get(binder_abbrev, binder_abbrev)

    aging_state = str(parsed.get("aging_state") or "non_aging")

    return f"{binder_type}_{structure_size}_{aging_state}"


def generate_exp_id(
    binder_type: str,
    structure_size: str,
    temperature_k: float = 298.0,
    additive: str | None = None,
    ff_type: str = "bulk_ff_gaff2",
    aging_state: str = "non_aging",
    atom_count: int = 100000,
    seed: int = 0,
) -> str:
    """
    Generate experiment ID with key information visible.

    Format: {binder}_{size}_{aging}_{additive}_{temp}K_{hash6}
    Example: A1_X1_NA_none_298K_a1b2c3

    Hash includes ALL parameters for uniqueness guarantee.

    Args:
        binder_type: Binder type (AAA1, AAK1, AAM1, custom)
        structure_size: Structure size (X1, X2, X3)
        temperature_k: Temperature in Kelvin
        additive: Additive name (optional, None = "none")
        ff_type: Force field type (used in hash for uniqueness)
        aging_state: Aging state (non_aging, short_aging, long_aging)
        atom_count: Target atom count (used in hash for uniqueness)
        seed: Random seed (used in hash for uniqueness)

    Returns:
        Experiment ID string (e.g., A1_X1_NA_none_298K_a1b2c3)
    """
    # Binder abbreviation
    binder_abbrev = BINDER_ABBREV.get(binder_type, binder_type[:2])

    # Aging abbreviation
    aging_abbrev = AGING_ABBREV.get(aging_state, "NA")

    # Additive (none if not specified)
    additive_str = additive if additive else "none"

    # Temperature as integer with K suffix
    temp_str = f"{int(temperature_k)}K"

    # Generate hash from ALL components for uniqueness
    hash_input = f"{binder_type}_{structure_size}_{additive}_{temperature_k}_{ff_type}_{aging_state}_{atom_count}_{seed}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:6]

    return f"{binder_abbrev}_{structure_size}_{aging_abbrev}_{additive_str}_{temp_str}_{hash_value}"


# Amorphous cell boundary modes for exp_id format detection.
# Must match contracts.schemas.AmorphousBoundaryMode values (verified by test).
_AMORPHOUS_BOUNDARY_MODES: frozenset[str] = frozenset({"ppp", "ppf"})


def generate_amorphous_exp_id(
    mol_id: str,
    boundary_mode: str,
    temperature_k: float,
    density: float,
    seed: int,
    ff_type: str = "bulk_ff_gaff2",
) -> str:
    """Generate exp_id for amorphous cell non-binder molecules.

    Format: {mol_id}_{boundary}_{temp}K_d{density}_{hash6}
    Example: H2O_ppp_298K_d1.00_a1b2c3

    Args:
        mol_id: Molecule identifier (e.g., "H2O", "Toluene")
        boundary_mode: Boundary condition ("ppp" or "ppf")
        temperature_k: Temperature in Kelvin
        density: Target density in g/cm3
        seed: Random seed (used in hash for uniqueness)
        ff_type: Force field type (used in hash for uniqueness)

    Returns:
        Experiment ID string (e.g., H2O_ppp_298K_d1.00_a1b2c3)
    """
    temp_str = f"{int(temperature_k)}K"
    density_str = f"d{density:.2f}"
    hash_input = f"{mol_id}_{boundary_mode}_{temperature_k}_{density}_{ff_type}_{seed}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:6]
    return f"{mol_id}_{boundary_mode}_{temp_str}_{density_str}_{hash_value}"


def parse_exp_id(exp_id: str) -> dict[str, str | float | None]:
    """
    Parse experiment ID to extract components.

    Binder format: {binder}_{size}_{aging}_{additive}_{temp}K_{hash6}
    Example: A1_X1_NA_none_298K_a1b2c3

    Amorphous format: {mol_id}_{boundary}_{temp}K_d{density}_{hash6}
    Example: H2O_ppp_298K_d1.00_a1b2c3

    Args:
        exp_id: Experiment ID string

    Returns:
        Dictionary of parsed components
    """
    result: dict[str, str | float | None] = {
        "binder_type": None,
        "structure_size": None,
        "aging_state": None,
        "additive": None,
        "temperature_k": None,
        "hash": None,
    }

    parts = exp_id.split("_")

    # Amorphous format: {mol_id}_{boundary}_{temp}K_d{density}_{hash6}
    if len(parts) >= 5 and parts[1] in _AMORPHOUS_BOUNDARY_MODES:
        result["binder_type"] = parts[0]  # mol_id stored as binder_type for compat
        result["structure_size"] = parts[1]  # boundary_mode stored as structure_size

        # Temperature (third part, e.g., "298K")
        temp_part = parts[2]
        if temp_part.endswith("K"):
            try:
                result["temperature_k"] = float(temp_part[:-1])
            except ValueError:
                pass

        # Density (fourth part, e.g., "d1.00")
        density_part = parts[3]
        if density_part.startswith("d"):
            try:
                result["density"] = float(density_part[1:])
            except ValueError:
                pass

        # Hash (fifth part)
        result["hash"] = parts[4]

        return result

    # Binder format: {binder}_{size}_{aging}_{additive}_{temp}K_{hash6}
    if len(parts) >= 6:
        # Binder abbreviation (first part)
        result["binder_type"] = parts[0]

        # Structure size (second part)
        result["structure_size"] = parts[1]

        # Aging state (third part)
        aging_abbrev = parts[2]
        result["aging_state"] = AGING_ABBREV_REVERSE.get(aging_abbrev, aging_abbrev)

        # Additive (fourth part)
        additive = parts[3]
        result["additive"] = None if additive == "none" else additive

        # Temperature (fifth part, e.g., "298K")
        temp_part = parts[4]
        if temp_part.endswith("K"):
            try:
                result["temperature_k"] = float(temp_part[:-1])
            except ValueError:
                pass

        # Hash (sixth part)
        result["hash"] = parts[5]

    return result
