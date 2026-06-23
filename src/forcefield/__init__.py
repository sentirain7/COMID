"""
Force Field Module.

This module provides force field parameter management for molecular
dynamics simulations, including:

- Curated artifact-based typing/charge assignment (GAFF2)
- Inorganic parameter service (CLAYFF + INTERFACE FF)
- Topology file generation for LAMMPS
- SMILES validation and molecule search
"""

from .organic_typing_executor import (
    TypingChargeAssignmentError,
    normalize_ff_name,
)
from .smiles_utils import (
    MoleculeSearcher,
    SMILESError,
    SMILESInfo,
    SMILESValidator,
    ValidationLevel,
    compute_smiles_hash,
    validate_smiles,
)
from .topology import (
    Angle,
    AngleType,
    Atom,
    AtomType,
    Bond,
    BondType,
    Dihedral,
    DihedralType,
    Improper,
    ImproperType,
    MoleculeTopology,
    SystemTopology,
    TopologyBuilder,
)

__all__ = [
    # Topology
    "TopologyBuilder",
    "SystemTopology",
    "MoleculeTopology",
    "AtomType",
    "BondType",
    "AngleType",
    "DihedralType",
    "ImproperType",
    "Atom",
    "Bond",
    "Angle",
    "Dihedral",
    "Improper",
    # SMILES
    "SMILESValidator",
    "SMILESInfo",
    "SMILESError",
    "MoleculeSearcher",
    "ValidationLevel",
    "validate_smiles",
    "compute_smiles_hash",
    # Typing/Charge (migrated from deleted typing_charge_assigner)
    "TypingChargeAssignmentError",
    "normalize_ff_name",
]
