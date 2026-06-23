"""
Common utilities module - shared across all sessions.

All sessions must use these utilities instead of implementing their own.
"""

from .additive_ids import (
    canonicalize_additive_mol_id,
    expand_additive_mol_id_aliases,
    infer_additive_mol_id,
)
from .artifacts import (
    ArtifactType,
    list_artifacts,
    load_artifact,
    save_artifact,
)
from .constants import (
    ATOMIC_WEIGHTS,
)
from .hashing import (
    compute_content_hash,
    compute_file_hash,
    compute_protocol_hash,
    compute_topology_hash,
)
from .logging import (
    LogLevel,
    configure_logging,
    get_logger,
)
from .molecule_id import (
    AGING_CATEGORY_MAP,
    AGING_PREFIXES,
    SARA_CATEGORY_MAP,
    SARA_PREFIXES,
    ParsedMoleculeId,
    build_aging_mol_id,
    get_aging_category,
    get_sara_category,
    parse_molecule_id,
    validate_molecule_id,
)
from .pathing import (
    exp_id_to_material_id,
    generate_amorphous_exp_id,
    generate_exp_id,
    get_array_storage_path,
    get_cache_path,
    get_experiment_path,
    get_molecule_path,
    parse_exp_id,
)
from .tooling import (
    resolve_executable,
    resolve_lammps_executable,
    resolve_packmol_executable,
)
from .units import (
    UnitConverter,
    convert_density,
    convert_energy,
    convert_pressure,
    convert_time,
)

__all__ = [
    # Pathing
    "get_experiment_path",
    "get_molecule_path",
    "get_array_storage_path",
    "get_cache_path",
    "generate_exp_id",
    "generate_amorphous_exp_id",
    "parse_exp_id",
    "exp_id_to_material_id",
    "resolve_executable",
    "resolve_lammps_executable",
    "resolve_packmol_executable",
    # Hashing
    "compute_topology_hash",
    "compute_file_hash",
    "compute_protocol_hash",
    "compute_content_hash",
    # Logging
    "get_logger",
    "configure_logging",
    "LogLevel",
    # Artifacts
    "save_artifact",
    "load_artifact",
    "list_artifacts",
    "ArtifactType",
    # Units
    "UnitConverter",
    "convert_energy",
    "convert_pressure",
    "convert_density",
    "convert_time",
    # Additive mol_id helpers
    "canonicalize_additive_mol_id",
    "expand_additive_mol_id_aliases",
    "infer_additive_mol_id",
    # Molecule ID parsing
    "ParsedMoleculeId",
    "parse_molecule_id",
    "get_sara_category",
    "get_aging_category",
    "validate_molecule_id",
    "build_aging_mol_id",
    "SARA_PREFIXES",
    "AGING_PREFIXES",
    "SARA_CATEGORY_MAP",
    "AGING_CATEGORY_MAP",
    # Constants
    "ATOMIC_WEIGHTS",
]
