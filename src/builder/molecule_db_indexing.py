"""
Molecule indexing and aging library loading utilities.

Standalone functions for indexing .mol files, loading aging library
configurations, and managing force field assignments from YAML.

Extracted from molecule_db.py following the same pattern as mol_parser.py.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from builder import mol_parser
from builder.mol_types import MoleculeRecord
from common.hashing import compute_content_hash
from common.pathing import get_project_root
from contracts.schemas import MoleculeCategory, MoleculeSpec


def _index_mol_directory(
    mol_dir: Path,
    mol_def: dict[str, Any],
    aging_key: str,
    prefix: str,
    sara_category: str,
    config: dict[str, Any],
    molecules: dict[str, MoleculeRecord],
) -> int:
    """
    Index all MOL files in a molecule directory.

    Args:
        mol_dir: Path to molecule directory
        mol_def: Molecule definition from config
        aging_key: Aging category key (non_aging, short_aging, long_aging)
        prefix: Aging prefix (U, S, L)
        sara_category: SARA category string
        config: Full config dict
        molecules: Molecule registry to populate

    Returns:
        Number of molecules indexed
    """
    return _index_mol_files(
        mol_files=list(mol_dir.glob("*.mol")),
        mol_def=mol_def,
        prefix=prefix,
        sara_category=sara_category,
        relative_root=mol_dir.parent.parent,
        molecules=molecules,
    )


def _index_mol_files(
    mol_files: list[Path],
    mol_def: dict[str, Any],
    prefix: str,
    sara_category: str,
    relative_root: Path,
    molecules: dict[str, MoleculeRecord],
) -> int:
    """Index MOL files into MoleculeSpec records.

    Args:
        mol_files: List of .mol file paths to index
        mol_def: Molecule definition from config
        prefix: Aging prefix (U, S, L)
        sara_category: SARA category string
        relative_root: Root path for computing relative structure_file paths
        molecules: Molecule registry to populate

    Returns:
        Number of molecules indexed
    """
    count = 0

    # Map SARA string to MoleculeCategory enum
    category_map = {
        "aromatic": MoleculeCategory.AROMATIC,
        "asphaltene": MoleculeCategory.ASPHALTENE,
        "resin": MoleculeCategory.RESIN,
        "saturate": MoleculeCategory.SATURATE,
    }
    category = category_map.get(sara_category, MoleculeCategory.AROMATIC)

    for mol_file in mol_files:
        try:
            # Parse filename to extract temperature code
            # Format: U-AS-Thio-0293NPT_Mol.mol
            filename = mol_file.stem  # U-AS-Thio-0293NPT_Mol
            temp_match = re.search(r"-(\d{4})NPT", filename)
            temp_code = temp_match.group(1) if temp_match else "0293"

            # Create unique mol_id including temperature
            # e.g., "U-AS-Thio-0293"
            base_id = mol_def["base_id"]
            mol_id = f"{prefix}-{base_id}-{temp_code}"

            # Parse MOL file for atom count and estimate molecular weight
            atom_count, estimated_mw = mol_parser._parse_mol_file(mol_file)

            # Generate topology hash
            topology_hash = compute_content_hash(
                f"{mol_id}:{atom_count}:{mol_file.stat().st_size}", length=8
            )

            # Create MoleculeSpec
            spec = MoleculeSpec(
                mol_id=mol_id,
                smiles=f"[{mol_def['name']}]",  # Placeholder SMILES
                molecular_weight=estimated_mw,
                atom_count=atom_count,
                category=category,
                structure_file=str(mol_file.relative_to(relative_root)),
                topology_hash=topology_hash,
            )

            # Add to database
            if mol_id not in molecules:
                molecules[mol_id] = MoleculeRecord(spec=spec)
                count += 1

        except Exception:
            # Skip invalid files
            continue

    return count


def _index_additives_from_config(
    config: dict[str, Any],
    base_dir: Path,
    molecules: dict[str, MoleculeRecord],
    additive_defs: dict[str, dict[str, Any]],
) -> int:
    """Index additive molecules defined under config['additives'].

    Args:
        config: Loaded YAML config dict
        base_dir: Base directory for resolving structure file paths
        molecules: Molecule registry to populate
        additive_defs: Additive definitions dict to populate

    Returns:
        Number of additives indexed
    """
    additives = dict(config.get("additives") or {})
    if not additives:
        return 0

    count = 0
    for additive_id, additive_def in additives.items():
        if not additive_id:
            continue

        # Store raw additive definition for parameterization lookup
        if additive_def:
            additive_defs[str(additive_id)] = dict(additive_def)

        structure_file = str((additive_def or {}).get("structure_file", "")).strip()
        if not structure_file:
            continue

        mol_path = base_dir / structure_file
        if not mol_path.exists():
            continue

        atom_count, _ = mol_parser._parse_mol_file(mol_path)
        topology_hash = compute_content_hash(
            f"{additive_id}:{atom_count}:{mol_path.stat().st_size}", length=8
        )

        spec = MoleculeSpec(
            mol_id=str(additive_id),
            smiles=f"[{(additive_def or {}).get('name', additive_id)}]",
            molecular_weight=float((additive_def or {}).get("molecular_weight", 0.0) or 0.0),
            atom_count=int(atom_count or (additive_def or {}).get("atom_count", 0) or 0),
            category=MoleculeCategory.ADDITIVE,
            structure_file=structure_file,
            topology_hash=topology_hash,
        )

        if spec.mol_id not in molecules:
            molecules[spec.mol_id] = MoleculeRecord(spec=spec)
            count += 1

    return count


def _index_explicit_structure_file(
    mol_def: dict[str, Any],
    structure_file: Path,
    sara_category: str,
    base_dir: Path,
    molecules: dict[str, MoleculeRecord],
) -> int:
    """Index one explicitly configured structure file using base_id as mol_id.

    Args:
        mol_def: Molecule definition from config
        structure_file: Relative path to structure file
        sara_category: SARA category string
        base_dir: Base directory for resolving structure file path
        molecules: Molecule registry to populate

    Returns:
        1 if indexed, 0 otherwise
    """
    mol_path = base_dir / structure_file
    if not mol_path.exists():
        return 0

    category_map = {
        "aromatic": MoleculeCategory.AROMATIC,
        "asphaltene": MoleculeCategory.ASPHALTENE,
        "resin": MoleculeCategory.RESIN,
        "saturate": MoleculeCategory.SATURATE,
    }
    category = category_map.get(sara_category, MoleculeCategory.AROMATIC)

    atom_count, _ = mol_parser._parse_mol_file(mol_path)
    mol_id = str(mol_def["base_id"])
    topology_hash = compute_content_hash(
        f"{mol_id}:{atom_count}:{mol_path.stat().st_size}", length=8
    )

    spec = MoleculeSpec(
        mol_id=mol_id,
        smiles=f"[{mol_def['name']}]",
        molecular_weight=float(mol_def.get("molecular_weight", 0.0) or 0.0),
        atom_count=int(atom_count or mol_def.get("atom_count", 0) or 0),
        category=category,
        structure_file=str(structure_file),
        topology_hash=topology_hash,
    )

    if mol_id not in molecules:
        molecules[mol_id] = MoleculeRecord(spec=spec)
        return 1
    return 0


def load_aging_library(
    config_path: Path,
    molecules: dict[str, MoleculeRecord],
    additive_defs: dict[str, dict[str, Any]],
) -> tuple[int, Path]:
    """
    Load aging-based molecule library from YAML configuration.

    Args:
        config_path: Path to asphalt_binder.yaml (or combined config path)
        molecules: Molecule registry to populate
        additive_defs: Additive definitions dict to populate

    Returns:
        Tuple of (number of molecules loaded, config_path for storage)

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config = yaml.safe_load(config_path.read_text())
    base_dir = config_path.parent
    count = load_aging_library_from_config(
        config=config,
        base_dir=base_dir,
        molecules=molecules,
        additive_defs=additive_defs,
    )
    return count, config_path


def load_aging_library_from_config(
    config: dict[str, Any],
    base_dir: Path,
    molecules: dict[str, MoleculeRecord],
    additive_defs: dict[str, dict[str, Any]],
) -> int:
    """Load aging/single molecule library from pre-loaded config dict.

    Args:
        config: Loaded YAML config dict
        base_dir: Base directory for resolving paths
        molecules: Molecule registry to populate
        additive_defs: Additive definitions dict to populate

    Returns:
        Number of molecules loaded
    """
    aging_categories = config.get("aging_categories", {})
    molecules_def = config.get("molecules", [])
    sara_mapping = config.get("sara_mapping", {})

    count = 0
    for mol_def in molecules_def:
        base_id = mol_def["base_id"]
        sara_code = base_id.split("-")[0] if "-" in base_id else ""
        sara_category = mol_def.get("sara") or sara_mapping.get(sara_code, "unknown")

        # Explicit structure file mode (single molecules): keep base_id as mol_id.
        explicit_structure = str(mol_def.get("structure_file", "")).strip()
        if explicit_structure:
            loaded = _index_explicit_structure_file(
                mol_def=mol_def,
                structure_file=Path(explicit_structure),
                sara_category=sara_category,
                base_dir=base_dir,
                molecules=molecules,
            )
            count += loaded
            continue

        for aging_key in mol_def.get("available_aging", []):
            aging_info = aging_categories.get(aging_key)
            if not aging_info:
                continue

            prefix = aging_info["prefix"]
            directory = aging_info["directory"]
            aging_dir = base_dir / directory

            # Legacy layout: <aging_dir>/<prefix-base_id>/*.mol
            mol_dir = aging_dir / f"{prefix}-{base_id}"
            if mol_dir.exists():
                loaded = _index_mol_directory(
                    mol_dir=mol_dir,
                    mol_def=mol_def,
                    aging_key=aging_key,
                    prefix=prefix,
                    sara_category=sara_category,
                    config=config,
                    molecules=molecules,
                )
                count += loaded
                continue

            # Flattened layout: <aging_dir>/<prefix-base_id>-0293NPT_Mol.mol
            if aging_dir.exists():
                flat_files = sorted(aging_dir.glob(f"{prefix}-{base_id}-*NPT_Mol.mol"))
                # Future-proof: support fully simplified filename without temp tokens.
                simplified = aging_dir / f"{prefix}-{base_id}.mol"
                if simplified.exists():
                    flat_files.append(simplified)

                if flat_files:
                    loaded = _index_mol_files(
                        mol_files=flat_files,
                        mol_def=mol_def,
                        prefix=prefix,
                        sara_category=sara_category,
                        relative_root=base_dir,
                        molecules=molecules,
                    )
                    count += loaded

    # Index additive structures from split SSOT config (additives.yaml).
    count += _index_additives_from_config(
        config=config,
        base_dir=base_dir,
        molecules=molecules,
        additive_defs=additive_defs,
    )

    return count


def load_ff_assignments(
    ff_assignments: dict[str, dict[str, Any]],
) -> Exception | None:
    """Load ff_assignment metadata from all three molecule SSOT files.

    Wave 0: ff_assignment is the single source of truth for typing/charge
    routing. It is authored directly in asphalt_binder.yaml (keyed by
    base_id), single_moles.yaml (keyed by base_id), and additives.yaml
    (keyed by additive_id). This function eagerly loads all three and
    populates ``ff_assignments`` so that the typing router can
    resolve any mol_id without paying a disk hit per call.

    Args:
        ff_assignments: Dict to populate with ff_assignment data

    Returns:
        Exception if any SSOT file was corrupt, None otherwise
    """
    data_dir = get_project_root() / "data" / "molecules"
    sources: list[tuple[Path, str]] = [
        (data_dir / "asphalt_binder.yaml", "molecules"),
        (data_dir / "single_moles.yaml", "molecules"),
        (data_dir / "additives.yaml", "additives"),
    ]

    load_error: Exception | None = None

    for yaml_path, section in sources:
        if not yaml_path.exists():
            # Missing files are tolerated at runtime; the audit test
            # enforces repo-level presence. This keeps tmp_path-based
            # API tests from being broken by the eager load.
            continue

        try:
            config = yaml.safe_load(yaml_path.read_text()) or {}
        except Exception as exc:
            # A present-but-corrupt SSOT IS fail-closed: the router
            # cannot trust partially-loaded routing metadata, so we
            # surface the error to callers via get_ff_assignment_load_error.
            load_error = exc
            continue

        entries = config.get(section) or {}
        if section == "molecules":
            # molecules: list of dicts with base_id
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                base_id = entry.get("base_id")
                ff_assignment = entry.get("ff_assignment")
                if base_id and isinstance(ff_assignment, dict):
                    ff_assignments[str(base_id)] = dict(ff_assignment)
        else:
            # additives: mapping of additive_id -> definition
            if not isinstance(entries, dict):
                continue
            for additive_id, additive_def in entries.items():
                if not additive_id or not isinstance(additive_def, dict):
                    continue
                ff_assignment = additive_def.get("ff_assignment")
                if isinstance(ff_assignment, dict):
                    ff_assignments[str(additive_id)] = dict(ff_assignment)

    return load_error
