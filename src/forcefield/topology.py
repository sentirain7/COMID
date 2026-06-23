"""
Topology File Generation for LAMMPS Simulations.

Generates combined topology files for multi-molecule systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common.logging import get_logger

if TYPE_CHECKING:
    from contracts.policies.forcefield import ForceFieldConfig, ForceFieldRegistry

logger = get_logger("forcefield.topology")


@dataclass
class AtomType:
    """LAMMPS atom type definition."""

    type_id: int
    mass: float
    element: str
    comment: str = ""
    # LJ parameters (pair_style lj/cut/coul/long)
    epsilon: float = 0.0  # kcal/mol
    sigma: float = 0.0  # Angstrom

    def to_lammps_mass(self) -> str:
        """Generate LAMMPS mass line."""
        return f"{self.type_id} {self.mass:.4f}  # {self.comment or self.element}"

    def to_lammps_pair(self) -> str:
        """Generate LAMMPS pair coefficient line."""
        return (
            f"{self.type_id} {self.epsilon:.4f} {self.sigma:.4f}  # {self.comment or self.element}"
        )


@dataclass
class BondType:
    """LAMMPS bond type definition."""

    type_id: int
    k: float  # kcal/mol/A^2
    r0: float  # Angstrom
    comment: str = ""

    def to_lammps(self) -> str:
        """Generate LAMMPS bond coefficient line."""
        return f"{self.type_id} {self.k:.4f} {self.r0:.4f}  # {self.comment}"


@dataclass
class AngleType:
    """LAMMPS angle type definition."""

    type_id: int
    k: float  # kcal/mol/rad^2
    theta0: float  # degrees
    comment: str = ""

    def to_lammps(self) -> str:
        """Generate LAMMPS angle coefficient line."""
        return f"{self.type_id} {self.k:.4f} {self.theta0:.4f}  # {self.comment}"


@dataclass
class DihedralType:
    """LAMMPS dihedral type definition (FF-neutral).

    Supports opls (4-coefficient), fourier (N-term), and harmonic styles.
    """

    type_id: int
    style: str = "fourier"  # "fourier" | "opls" | "harmonic"
    coeffs: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    comment: str = ""

    # Backward-compatible properties for OPLS-style access
    @property
    def k1(self) -> float:
        """First OPLS dihedral coefficient."""
        return self.coeffs[0] if len(self.coeffs) > 0 else 0.0

    @property
    def k2(self) -> float:
        """Second OPLS dihedral coefficient."""
        return self.coeffs[1] if len(self.coeffs) > 1 else 0.0

    @property
    def k3(self) -> float:
        """Third OPLS dihedral coefficient."""
        return self.coeffs[2] if len(self.coeffs) > 2 else 0.0

    @property
    def k4(self) -> float:
        """Fourth OPLS dihedral coefficient."""
        return self.coeffs[3] if len(self.coeffs) > 3 else 0.0

    def to_lammps(self) -> str:
        """Generate LAMMPS dihedral coefficient line."""
        if self.style == "opls":
            padded = (*self.coeffs, *([0.0] * max(0, 4 - len(self.coeffs))))
            k1, k2, k3, k4 = padded[:4]
            return f"{self.type_id} {k1:.4f} {k2:.4f} {k3:.4f} {k4:.4f}  # {self.comment}"
        elif self.style == "fourier":
            n_terms = len(self.coeffs) // 3
            parts = [f"{self.type_id} {n_terms}"]
            for i in range(n_terms):
                k, d, n = self.coeffs[3 * i : 3 * i + 3]
                parts.append(f"{k:.4f} {int(d)} {int(n)}")
            return f"{' '.join(parts)}  # {self.comment}"
        elif self.style == "harmonic":
            k = self.coeffs[0] if len(self.coeffs) > 0 else 0.0
            d = int(self.coeffs[1]) if len(self.coeffs) > 1 else 1
            n = int(self.coeffs[2]) if len(self.coeffs) > 2 else 1
            return f"{self.type_id} {k:.4f} {d} {n}  # {self.comment}"
        else:
            coeff_str = " ".join(f"{c:.4f}" for c in self.coeffs)
            return f"{self.type_id} {coeff_str}  # {self.comment}"


@dataclass
class ImproperType:
    """LAMMPS improper type definition (FF-neutral).

    Supports harmonic (OPLS) and cvff (GAFF2/AMBER) styles.
    """

    type_id: int
    style: str = "harmonic"  # "harmonic" | "cvff"
    coeffs: tuple[float, ...] = (0.0, 180.0)
    comment: str = ""

    def to_lammps(self) -> str:
        """Generate LAMMPS improper coefficient line."""
        if self.style == "harmonic":
            k = self.coeffs[0] if len(self.coeffs) > 0 else 0.0
            chi_eq = self.coeffs[1] if len(self.coeffs) > 1 else 180.0
            return f"{self.type_id} {k:.4f} {chi_eq:.4f}  # {self.comment}"
        elif self.style == "cvff":
            k = self.coeffs[0] if len(self.coeffs) > 0 else 0.0
            d = int(self.coeffs[1]) if len(self.coeffs) > 1 else -1
            n = int(self.coeffs[2]) if len(self.coeffs) > 2 else 2
            return f"{self.type_id} {k:.4f} {d} {n}  # {self.comment}"
        else:
            coeff_str = " ".join(f"{c:.4f}" for c in self.coeffs)
            return f"{self.type_id} {coeff_str}  # {self.comment}"


@dataclass
class Atom:
    """Single atom in topology."""

    atom_id: int
    mol_id: int
    type_id: int
    charge: float
    x: float
    y: float
    z: float
    comment: str = ""


@dataclass
class Bond:
    """Bond in topology."""

    bond_id: int
    type_id: int
    atom1: int
    atom2: int


@dataclass
class Angle:
    """Angle in topology."""

    angle_id: int
    type_id: int
    atom1: int
    atom2: int
    atom3: int


@dataclass
class Dihedral:
    """Dihedral in topology."""

    dihedral_id: int
    type_id: int
    atom1: int
    atom2: int
    atom3: int
    atom4: int


@dataclass
class Improper:
    """Improper in topology."""

    improper_id: int
    type_id: int
    atom1: int
    atom2: int
    atom3: int
    atom4: int


@dataclass
class MoleculeTopology:
    """Complete topology for a single molecule type."""

    mol_id: str
    smiles: str
    n_atoms: int

    atom_types: list[AtomType] = field(default_factory=list)
    bond_types: list[BondType] = field(default_factory=list)
    angle_types: list[AngleType] = field(default_factory=list)
    dihedral_types: list[DihedralType] = field(default_factory=list)
    improper_types: list[ImproperType] = field(default_factory=list)

    # Template atoms (for one molecule)
    template_atoms: list[Atom] = field(default_factory=list)
    template_bonds: list[Bond] = field(default_factory=list)
    template_angles: list[Angle] = field(default_factory=list)
    template_dihedrals: list[Dihedral] = field(default_factory=list)
    template_impropers: list[Improper] = field(default_factory=list)


@dataclass
class SystemTopology:
    """Complete topology for a multi-molecule system."""

    title: str = "LAMMPS System Topology"

    # Box dimensions
    xlo: float = 0.0
    xhi: float = 100.0
    ylo: float = 0.0
    yhi: float = 100.0
    zlo: float = 0.0
    zhi: float = 100.0

    # Molecule compositions
    molecules: dict[str, MoleculeTopology] = field(default_factory=dict)
    molecule_counts: dict[str, int] = field(default_factory=dict)

    # Combined types (with global IDs)
    atom_types: list[AtomType] = field(default_factory=list)
    bond_types: list[BondType] = field(default_factory=list)
    angle_types: list[AngleType] = field(default_factory=list)
    dihedral_types: list[DihedralType] = field(default_factory=list)
    improper_types: list[ImproperType] = field(default_factory=list)

    # All atoms/bonds/etc
    atoms: list[Atom] = field(default_factory=list)
    bonds: list[Bond] = field(default_factory=list)
    angles: list[Angle] = field(default_factory=list)
    dihedrals: list[Dihedral] = field(default_factory=list)
    impropers: list[Improper] = field(default_factory=list)

    def get_counts(self) -> dict[str, int]:
        """Get topology counts."""
        return {
            "atoms": len(self.atoms),
            "bonds": len(self.bonds),
            "angles": len(self.angles),
            "dihedrals": len(self.dihedrals),
            "impropers": len(self.impropers),
            "atom_types": len(self.atom_types),
            "bond_types": len(self.bond_types),
            "angle_types": len(self.angle_types),
            "dihedral_types": len(self.dihedral_types),
            "improper_types": len(self.improper_types),
        }


class TopologyBuilder:
    """
    Builder for creating combined LAMMPS topology files.
    """

    def __init__(self):
        """Initialize topology builder."""
        self._type_maps: dict[str, dict[int, int]] = {}  # mol_id -> local_type -> global_type

    def write_lammps_data(
        self,
        topology: SystemTopology,
        output_path: Path,
    ) -> None:
        """
        Write LAMMPS data file.

        Args:
            topology: System topology
            output_path: Output file path
        """
        counts = topology.get_counts()

        with open(output_path, "w") as f:
            # Header
            f.write(f"{topology.title}\n\n")

            # Counts
            f.write(f"{counts['atoms']} atoms\n")
            f.write(f"{counts['bonds']} bonds\n")
            f.write(f"{counts['angles']} angles\n")
            f.write(f"{counts['dihedrals']} dihedrals\n")
            if counts.get("impropers", 0) > 0:
                f.write(f"{counts['impropers']} impropers\n")
            f.write("\n")

            f.write(f"{counts['atom_types']} atom types\n")
            f.write(f"{counts['bond_types']} bond types\n")
            f.write(f"{counts['angle_types']} angle types\n")
            f.write(f"{counts['dihedral_types']} dihedral types\n")
            if counts.get("impropers", 0) > 0 and counts.get("improper_types", 0) > 0:
                f.write(f"{counts['improper_types']} improper types\n")
            f.write("\n")

            # Box
            f.write(f"{topology.xlo:.6f} {topology.xhi:.6f} xlo xhi\n")
            f.write(f"{topology.ylo:.6f} {topology.yhi:.6f} ylo yhi\n")
            f.write(f"{topology.zlo:.6f} {topology.zhi:.6f} zlo zhi\n\n")

            # Masses
            f.write("Masses\n\n")
            for at in topology.atom_types:
                f.write(f"{at.to_lammps_mass()}\n")
            f.write("\n")

            # Pair Coeffs
            f.write("Pair Coeffs\n\n")
            for at in topology.atom_types:
                f.write(f"{at.to_lammps_pair()}\n")
            f.write("\n")

            # Bond Coeffs
            if topology.bond_types:
                f.write("Bond Coeffs\n\n")
                for bt in topology.bond_types:
                    f.write(f"{bt.to_lammps()}\n")
                f.write("\n")

            # Angle Coeffs
            if topology.angle_types:
                f.write("Angle Coeffs\n\n")
                for at in topology.angle_types:
                    f.write(f"{at.to_lammps()}\n")
                f.write("\n")

            # Dihedral Coeffs
            if topology.dihedral_types:
                f.write("Dihedral Coeffs\n\n")
                for dt in topology.dihedral_types:
                    f.write(f"{dt.to_lammps()}\n")
                f.write("\n")

            # Improper Coeffs — only when instances exist (avoids LAMMPS parse error)
            if topology.improper_types and topology.impropers:
                f.write("Improper Coeffs\n\n")
                for it in topology.improper_types:
                    f.write(f"{it.to_lammps()}\n")
                f.write("\n")

            # Atoms
            if topology.atoms:
                f.write("Atoms\n\n")
                for atom in topology.atoms:
                    f.write(
                        f"{atom.atom_id} {atom.mol_id} {atom.type_id} "
                        f"{atom.charge:.6f} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}\n"
                    )
                f.write("\n")

            # Bonds
            if topology.bonds:
                f.write("Bonds\n\n")
                for bond in topology.bonds:
                    f.write(f"{bond.bond_id} {bond.type_id} {bond.atom1} {bond.atom2}\n")
                f.write("\n")

            # Angles
            if topology.angles:
                f.write("Angles\n\n")
                for angle in topology.angles:
                    f.write(
                        f"{angle.angle_id} {angle.type_id} "
                        f"{angle.atom1} {angle.atom2} {angle.atom3}\n"
                    )
                f.write("\n")

            # Dihedrals
            if topology.dihedrals:
                f.write("Dihedrals\n\n")
                for dih in topology.dihedrals:
                    f.write(
                        f"{dih.dihedral_id} {dih.type_id} "
                        f"{dih.atom1} {dih.atom2} {dih.atom3} {dih.atom4}\n"
                    )
                f.write("\n")

            # Impropers
            if topology.impropers:
                f.write("Impropers\n\n")
                for imp in topology.impropers:
                    f.write(
                        f"{imp.improper_id} {imp.type_id} "
                        f"{imp.atom1} {imp.atom2} {imp.atom3} {imp.atom4}\n"
                    )
                f.write("\n")

        logger.info(f"Wrote LAMMPS data file: {output_path}")

    def write_lammps_input(
        self,
        topology: SystemTopology,
        output_path: Path,
        data_file: str = "system.data",
    ) -> None:
        """
        Write LAMMPS input file template.

        Args:
            topology: System topology
            output_path: Output file path
            data_file: Name of data file
        """
        with open(output_path, "w") as f:
            f.write(f"# LAMMPS input for {topology.title}\n")
            f.write("# Generated by AsphaltAgent TopologyBuilder\n\n")

            f.write("units real\n")
            f.write("atom_style full\n")
            f.write("boundary p p p\n\n")

            f.write("pair_style lj/cut/coul/long 12.0\n")
            f.write("bond_style harmonic\n")
            f.write("angle_style harmonic\n")
            # Determine dihedral style from types
            dihedral_styles = (
                {dt.style for dt in topology.dihedral_types}
                if hasattr(topology, "dihedral_types") and topology.dihedral_types
                else {"opls"}
            )
            if len(dihedral_styles) == 1:
                f.write(f"dihedral_style {dihedral_styles.pop()}\n")
            else:
                # TODO(Phase 1+): mixed dihedral styles should emit
                #   dihedral_style hybrid <style1> <style2> ...
                # and per-type dihedral_coeff lines must include the sub-style.
                # For now, fall back to fourier which is correct for GAFF2 systems.
                # TODO(Phase 1+): emit proper hybrid once multi-style support lands
                f.write("dihedral_style fourier\n")
            # Determine improper style from types
            if topology.improper_types:
                imp_styles = {it.style for it in topology.improper_types}
                if len(imp_styles) == 1:
                    f.write(f"improper_style {imp_styles.pop()}\n")
                else:
                    # TODO: hybrid support for mixed improper styles
                    f.write("improper_style harmonic\n")
            f.write("kspace_style pppm 1.0e-4\n\n")

            f.write(f"read_data {data_file}\n\n")

            f.write("# Molecule counts:\n")
            for mol_id, count in topology.molecule_counts.items():
                f.write(f"# {mol_id}: {count}\n")

        logger.info(f"Wrote LAMMPS input file: {output_path}")


# Force field parameters are now loaded from the registry (SSOT)
# See: contracts/policies/forcefield.py and data/forcefields/registry.yaml


def _get_default_ff_registry() -> ForceFieldRegistry:
    """Lazy import to avoid circular dependency with contracts.policies.forcefield."""
    from contracts.policies.forcefield import get_default_ff_registry

    return get_default_ff_registry()


def _get_ff_params_dict(ff_config: ForceFieldConfig) -> dict:
    """Convert ForceFieldConfig atom types to legacy dict format for compatibility."""
    params = {}
    for atom_type, atom_params in ff_config.get_all_atom_types().items():
        params[atom_type] = {
            "mass": atom_params.mass,
            "epsilon": atom_params.epsilon,
            "sigma": atom_params.sigma,
            "charge": atom_params.charge,
        }
    return params


def _get_bond_params_dict(ff_config: ForceFieldConfig) -> dict:
    """Convert ForceFieldConfig bond types to legacy tuple-keyed dict format."""
    params = {}
    for bond_key, bond_params in ff_config.bond_types.items():
        parts = bond_key.split("-")
        if len(parts) == 2:
            key = (parts[0], parts[1])
            params[key] = {"k": bond_params.k, "r0": bond_params.r0}
    return params


def _get_angle_params_dict(ff_config: ForceFieldConfig) -> dict:
    """Convert ForceFieldConfig angle types to legacy tuple-keyed dict format."""
    params = {}
    for angle_key, angle_params in ff_config.angle_types.items():
        parts = angle_key.split("-")
        if len(parts) == 3:
            key = (parts[0], parts[1], parts[2])
            params[key] = {"k": angle_params.k, "theta0": angle_params.theta0}
    return params


def _get_dihedral_params_dict(ff_config: ForceFieldConfig) -> dict:
    """Convert ForceFieldConfig dihedral types to legacy tuple-keyed dict format."""
    params = {}
    for dih_key, dih_params in ff_config.dihedral_types.items():
        parts = dih_key.split("-")
        if len(parts) == 4:
            key = (parts[0], parts[1], parts[2], parts[3])
            params[key] = {
                "k1": dih_params.k1,
                "k2": dih_params.k2,
                "k3": dih_params.k3,
                "k4": dih_params.k4,
            }
    return params


class MolTopologyBuilder:
    """
    Builder for creating LAMMPS topology from MOL files.

    Creates topology with force field parameters from the registry.
    Supports dynamic force field selection.
    """

    def __init__(
        self,
        ff_name: str = "gaff2",
        strict_param_coverage: bool = False,
        atom_param_overrides: dict[str, dict[str, float]] | None = None,
        bond_param_overrides: dict[str, dict[str, float]] | None = None,
        angle_param_overrides: dict[str, dict[str, float]] | None = None,
        dihedral_param_overrides: dict[str, dict[str, float]] | None = None,
        improper_param_overrides: dict[str, dict[str, Any]] | None = None,
        dihedral_fallback_policy: str = "strict",
        inorganic_ff_types: set[str] | None = None,
    ):
        """Initialize MOL topology builder.

        Args:
            ff_name: Force field name (e.g., 'opls-aa', 'bulk_ff')
            strict_param_coverage: Global default for fail-closed bonded
                lookups. Set this for builds where every molecule should be
                strict (e.g., a fully curated artifact build). Wave 1 also
                supports per-mol strict policies via the
                ``strict_ff_types`` set populated when ``create_from_mol_topology``
                is called with mol-level strict flags — see
                ``_resolve_strict_lookup``.
            atom_param_overrides: Override atom params by ff_type (e.g., {"Si_tet": {...}}).
                                  Used for inorganic site-specific parameterization.
            bond_param_overrides: Override bond params by type key (e.g., {"Si_tet-O_br": {...}}).
            angle_param_overrides: Override angle params by type key.
            dihedral_param_overrides: Override dihedral params by type key.
            improper_param_overrides: Override improper params by type key
                (e.g., {"ca-ca-ca-ha": {"style": "cvff", "coeffs": (1.1, -1, 2)}}).
                Takes priority over dihedral_param_overrides for improper resolution.
            dihedral_fallback_policy: Policy for missing dihedral params:
                                      "strict" (default) - use strict_param_coverage setting
                                      "allow_default_fallback" - allow default k values for
                                          inorganic ff_types only (scoped by inorganic_ff_types)
            inorganic_ff_types: Set of ff_type names that are inorganic (e.g., {"Si_tet", "O_br"}).
                               Used to scope dihedral_fallback_policy to inorganic dihedrals only.
        """
        self._atom_type_map: dict[str, int] = {}  # ff_type -> type_id
        self._bond_type_map: dict[tuple[str, str], int] = {}
        self._angle_type_map: dict[tuple[str, str, str], int] = {}
        self._dihedral_type_map: dict[tuple[str, str, str, str], int] = {}

        # Store override dictionaries for inorganic parameterization
        self._atom_param_overrides = atom_param_overrides or {}
        self._bond_param_overrides = bond_param_overrides or {}
        self._angle_param_overrides = angle_param_overrides or {}
        self._dihedral_param_overrides = dihedral_param_overrides or {}
        self._improper_param_overrides = improper_param_overrides or {}
        self._dihedral_fallback_policy = dihedral_fallback_policy
        self._inorganic_ff_types = frozenset(inorganic_ff_types or ())

        # Wave 1 route-aware strict policy:
        #   - ``_strict_param_coverage`` is the *global* fallback (Wave 0
        #     behavior, controlled by typing_charge.strict_param_coverage).
        #   - ``_strict_ff_types`` is populated per-build by
        #     ``create_from_mol_topology`` when caller passes mol-level
        #     strict flags. ANY bond/angle/dihedral lookup whose key
        #     touches a strict ff_type is treated as strict regardless of
        #     the global flag.
        #   - organic_curated_artifact and inorganic_profile routes use
        #     strict mode (fail-closed on missing bonded params).
        self._strict_ff_types: set[str] = set()

        # Load force field from registry (lazy import to avoid circular dependency)
        self._ff_registry = _get_default_ff_registry()
        self._ff_config = self._ff_registry.get(ff_name)

        if self._ff_config is None:
            logger.warning(f"Force field '{ff_name}' not found, using default")
            self._ff_config = self._ff_registry.get_default()

        if self._ff_config is None:
            raise ValueError("No force field available. Check registry.yaml")

        # Build parameter dicts from config
        self._atom_params = _get_ff_params_dict(self._ff_config)
        self._bond_params = _get_bond_params_dict(self._ff_config)
        self._angle_params = _get_angle_params_dict(self._ff_config)
        self._dihedral_params = _get_dihedral_params_dict(self._ff_config)
        self._strict_param_coverage = strict_param_coverage

        logger.info(f"Loaded force field: {self._ff_config.name} v{self._ff_config.version}")

    def _resolve_strict_lookup(self, type_key: tuple[str, ...]) -> bool:
        """Wave 1: route-aware strict resolver.

        Returns True if a missing bonded parameter at this type_key should
        fail-closed instead of falling back to a generic default. This is
        true when EITHER:

        - The global ``_strict_param_coverage`` flag is set (Wave 0
          behavior), OR
        - Any ff_type in the lookup key is in ``_strict_ff_types``, which
          is populated per-build by ``create_from_mol_topology`` when the
          caller marks a molecule's route as strict (artifact / inorganic).

        The OR semantics mean: if a lax legacy molecule and a strict
        artifact molecule share an ff_type, the strict requirement wins
        for the shared type — silent default fallback would otherwise be
        a Wave 0 violation for the artifact molecule.
        """
        if self._strict_param_coverage:
            return True
        if not self._strict_ff_types:
            return False
        return any(t in self._strict_ff_types for t in type_key)

    @property
    def ff_config(self) -> ForceFieldConfig:
        """Get the current force field configuration."""
        return self._ff_config

    def _get_element_type(self, element: str, is_aromatic: bool = False) -> str:
        """Map element to force field atom type."""
        if element == "C":
            return "CA" if is_aromatic else "C"
        elif element == "H":
            return "HA" if is_aromatic else "H"
        elif element == "N":
            return "NA" if is_aromatic else "N"
        return element

    def _get_ff_atom_params(self, element: str, is_aromatic: bool = False) -> dict:
        """Get force field parameters for element."""
        ff_type = self._get_element_type(element, is_aromatic)
        return self._get_ff_atom_params_from_type(ff_type=ff_type, element=element)

    def _get_ff_atom_params_from_type(self, ff_type: str, element: str) -> dict:
        """Get force field parameters with override priority.

        Resolution order:
        1. Override (artifact/inorganic site-specific params)
        2. Registry (standard FF params)
        3. Element fallback (blocked for strict curated routes)
        """
        # 1. Check override first (artifact GAFF2 LJ or inorganic site types)
        if ff_type in self._atom_param_overrides:
            return self._atom_param_overrides[ff_type]
        # 2. Check registry
        if ff_type in self._atom_params:
            return self._atom_params[ff_type]
        # 3. Strict gate: block silent element fallback for curated routes
        if self._resolve_strict_lookup((ff_type,)):
            if element in self._atom_params:
                logger.warning(
                    "Strict route: atom LJ for ff_type '%s' resolved via element "
                    "fallback '%s' — this would produce UFF params instead of "
                    "explicit FF params (GAFF2/INTERFACE). "
                    "Ensure the artifact or profile provides explicit LJ parameters.",
                    ff_type,
                    element,
                )
            raise ValueError(
                f"Missing atom LJ parameters for ff_type '{ff_type}' "
                f"(element fallback '{element}') in {self._ff_config.name}; "
                "lookup is strict because the type belongs to a curated "
                "artifact/profile route. Ensure the artifact or profile "
                "provides explicit LJ parameters."
            )
        # 4. Element fallback (non-strict routes only)
        if element in self._atom_params:
            return self._atom_params[element]
        raise ValueError(
            f"Atom type '{ff_type}' / element '{element}' is not defined in "
            f"force field {self._ff_config.name}"
        )

    def _resolve_atom_ff_type(
        self, atom: Any, element: str, is_aromatic: bool, *, mol_strict: bool = False
    ) -> str:
        """Resolve final ff_type for an atom from explicit value or heuristic mapping.

        Priority for explicit ff_type:
        0. Strict curated route (artifact/inorganic) — preserve as-is
        1. Override (inorganic site types)
        2. Registry
        3. Element fallback
        """
        explicit_ff_type = getattr(atom, "ff_type", None)
        if explicit_ff_type:
            # Strict curated route: preserve artifact/inorganic ff_type as-is
            # so bonded lookups match the override keys (e.g. "c3-c3").
            if mol_strict:
                return explicit_ff_type
            # Check override first (for inorganic site types like Si_tet, O_br)
            if explicit_ff_type in self._atom_param_overrides:
                return explicit_ff_type
            if explicit_ff_type in self._atom_params:
                return explicit_ff_type
            if element in self._atom_params:
                logger.warning(
                    f"Atom ff_type '{explicit_ff_type}' not in {self._ff_config.name}; "
                    f"falling back to element '{element}'"
                )
                return element
            raise ValueError(
                f"Atom ff_type '{explicit_ff_type}' is not available for element '{element}' "
                f"in force field {self._ff_config.name}"
            )
        inferred_ff_type = self._get_element_type(element, is_aromatic)
        if inferred_ff_type in self._atom_params:
            return inferred_ff_type
        if element in self._atom_params:
            return element
        raise ValueError(
            f"Unable to infer ff_type for element '{element}' in force field {self._ff_config.name}"
        )

    def _is_aromatic_atom(self, atom_idx: int, bonds: list, atoms: list) -> bool:
        """Check if atom is part of aromatic ring based on bond orders."""
        for bond in bonds:
            if bond.atom1 == atom_idx or bond.atom2 == atom_idx:
                if bond.order == 4:  # Aromatic bond
                    return True
        return False

    def _get_bond_interaction_params(
        self,
        type_key: tuple[str, str],
        element_key: tuple[str, str],
    ) -> tuple[dict[str, float], str]:
        """Resolve bond params with override->type->element fallback and strict mode."""
        # Check override first (string key format: "Si_tet-O_br")
        override_key = f"{type_key[0]}-{type_key[1]}"
        override_key_rev = f"{type_key[1]}-{type_key[0]}"
        if override_key in self._bond_param_overrides:
            return self._bond_param_overrides[override_key], override_key
        if override_key_rev in self._bond_param_overrides:
            return self._bond_param_overrides[override_key_rev], override_key_rev

        params = self._bond_params.get(type_key)
        if params is not None:
            return params, f"{type_key[0]}-{type_key[1]}"

        params = self._bond_params.get(element_key)
        if params is not None:
            return params, f"{element_key[0]}-{element_key[1]}"

        if self._resolve_strict_lookup(type_key):
            raise ValueError(
                f"Missing bond parameters for {type_key[0]}-{type_key[1]} "
                f"(fallback {element_key[0]}-{element_key[1]}) in {self._ff_config.name}; "
                "lookup is strict because the type belongs to a route that "
                "requires fail-closed bonded coverage (Wave 1)."
            )
        return {"k": 300.0, "r0": 1.5}, f"{element_key[0]}-{element_key[1]}(default)"

    def _get_angle_interaction_params(
        self,
        type_key: tuple[str, str, str],
        element_key: tuple[str, str, str],
    ) -> tuple[dict[str, float], str]:
        """Resolve angle params with override->type->element fallback and strict mode."""
        # Check override first (string key format: "O_br-Si_tet-O_br")
        override_key = f"{type_key[0]}-{type_key[1]}-{type_key[2]}"
        override_key_rev = f"{type_key[2]}-{type_key[1]}-{type_key[0]}"
        if override_key in self._angle_param_overrides:
            return self._angle_param_overrides[override_key], override_key
        if override_key_rev in self._angle_param_overrides:
            return self._angle_param_overrides[override_key_rev], override_key_rev

        params = self._angle_params.get(type_key)
        if params is not None:
            return params, f"{type_key[0]}-{type_key[1]}-{type_key[2]}"

        params = self._angle_params.get(element_key)
        if params is not None:
            return params, f"{element_key[0]}-{element_key[1]}-{element_key[2]}"

        if self._resolve_strict_lookup(type_key):
            raise ValueError(
                f"Missing angle parameters for {type_key[0]}-{type_key[1]}-{type_key[2]} "
                f"(fallback {element_key[0]}-{element_key[1]}-{element_key[2]}) "
                f"in {self._ff_config.name}; lookup is strict because the type "
                "belongs to a route that requires fail-closed bonded coverage (Wave 1)."
            )
        return {
            "k": 50.0,
            "theta0": 109.5,
        }, f"{element_key[0]}-{element_key[1]}-{element_key[2]}(default)"

    def _get_dihedral_interaction_params(
        self,
        type_key: tuple[str, str, str, str],
        element_key: tuple[str, str, str, str],
    ) -> tuple[dict[str, float], str]:
        """Resolve dihedral params with override->type->element fallback and policy mode.

        Resolution order:
        1. Override (inorganic/custom dihedral params)
        2. Registry type key
        3. Registry element key
        4. Default fallback (governed by dihedral_fallback_policy)
        """
        # 1. Check override first (string key format: "A-B-C-D")
        override_key = f"{type_key[0]}-{type_key[1]}-{type_key[2]}-{type_key[3]}"
        override_key_rev = f"{type_key[3]}-{type_key[2]}-{type_key[1]}-{type_key[0]}"
        if override_key in self._dihedral_param_overrides:
            return self._dihedral_param_overrides[override_key], override_key
        if override_key_rev in self._dihedral_param_overrides:
            return self._dihedral_param_overrides[override_key_rev], override_key_rev

        # 2. Check registry type key
        params = self._dihedral_params.get(type_key)
        if params is not None:
            return params, f"{type_key[0]}-{type_key[1]}-{type_key[2]}-{type_key[3]}"

        # 3. Check registry element key
        params = self._dihedral_params.get(element_key)
        if params is not None:
            return params, f"{element_key[0]}-{element_key[1]}-{element_key[2]}-{element_key[3]}"

        # 4. Fallback - governed by dihedral_fallback_policy with inorganic scoping
        # Check if this dihedral involves inorganic ff_types
        involves_inorganic = bool(self._inorganic_ff_types.intersection(type_key))

        if self._dihedral_fallback_policy == "allow_default_fallback" and involves_inorganic:
            # Inorganic dihedral: use fourier-compatible zero barrier.
            # GAFF2 registry sets dihedral_style=fourier globally, so the
            # default must be fourier-format: style + coeffs (k, d, n) triples.
            return {
                "style": "fourier",
                "coeffs": (0.0, 1, 1),  # single term: k=0 barrier
            }, (
                f"{element_key[0]}-{element_key[1]}-{element_key[2]}-{element_key[3]}(inorganic-default)"
            )

        if self._resolve_strict_lookup(type_key):
            raise ValueError(
                f"Missing dihedral parameters for "
                f"{type_key[0]}-{type_key[1]}-{type_key[2]}-{type_key[3]} "
                f"(fallback {element_key[0]}-{element_key[1]}-{element_key[2]}-{element_key[3]}) "
                f"in {self._ff_config.name}; lookup is strict because the type "
                "belongs to a route that requires fail-closed bonded coverage (Wave 1)."
            )
        return {
            "style": "fourier",
            "coeffs": (0.0, 1, 1),  # single fourier term: zero barrier
        }, (f"{element_key[0]}-{element_key[1]}-{element_key[2]}-{element_key[3]}(default)")

    def create_from_mol_topology(
        self,
        mol_topologies: list[
            tuple[Any, ...]
        ],  # (MolTopology, count) or (MolTopology, count, strict)
        packed_coords: list[tuple[float, float, float]] | None = None,
        box_bounds: tuple[float, float, float, float, float, float] = (0, 100, 0, 100, 0, 100),
        title: str = "Asphalt System",
    ) -> SystemTopology:
        """
        Create system topology from MOL topologies.

        Args:
            mol_topologies: List of either ``(MolTopology, count)`` or
                ``(MolTopology, count, strict)`` tuples. The optional third
                element is the Wave 1 per-mol strict policy: if True, every
                ff_type contributed by this molecule joins
                ``self._strict_ff_types`` so subsequent bonded lookups
                fail-closed instead of falling back to the generic default
                bond/angle/dihedral params. ``False`` (or absent) preserves
                the legacy lax behavior. Used by structure_builder to mark
                organic_curated_artifact and inorganic_profile molecules as
                strict for curated artifact and inorganic profile molecules.
            packed_coords: Coordinates from Packmol (if available)
            box_bounds: (xlo, xhi, ylo, yhi, zlo, zhi)
            title: System title

        Returns:
            SystemTopology ready for LAMMPS
        """
        system = SystemTopology(
            title=title,
            xlo=box_bounds[0],
            xhi=box_bounds[1],
            ylo=box_bounds[2],
            yhi=box_bounds[3],
            zlo=box_bounds[4],
            zhi=box_bounds[5],
        )

        # Reset type maps and per-build strict ff_type set
        self._atom_type_map = {}
        self._bond_type_map = {}
        self._angle_type_map = {}
        self._dihedral_type_map = {}
        self._improper_type_map: dict[tuple[str, str, str, str], int] = {}
        self._strict_ff_types = set()

        global_atom_id = 1
        global_bond_id = 1
        global_angle_id = 1
        global_dihedral_id = 1
        global_improper_id = 1
        global_mol_id = 1

        coord_index = 0  # Index into packed_coords

        for mol_entry in mol_topologies:
            # Wave 1: accept legacy 2-tuple or new 3-tuple form for backward compat.
            if len(mol_entry) == 2:
                mol_topo, count = mol_entry
                mol_strict = False
            elif len(mol_entry) >= 3:
                mol_topo, count, mol_strict = mol_entry[0], mol_entry[1], bool(mol_entry[2])
            else:
                raise ValueError(
                    f"mol_topologies entries must be (MolTopology, count) or "
                    f"(MolTopology, count, strict); got tuple of length {len(mol_entry)}"
                )

            system.molecule_counts[mol_topo.mol_id] = count

            # Build atom type mapping for this molecule
            mol_atom_types = {}  # local atom index -> (element, is_aromatic, ff_type)
            for atom in mol_topo.atoms:
                is_aromatic = self._is_aromatic_atom(atom.index, mol_topo.bonds, mol_topo.atoms)
                ff_type = self._resolve_atom_ff_type(
                    atom, atom.element, is_aromatic, mol_strict=mol_strict
                )
                mol_atom_types[atom.index] = (atom.element, is_aromatic, ff_type)
                if mol_strict:
                    # Wave 1: every ff_type contributed by a strict molecule
                    # joins the strict set so the route's fail-closed contract
                    # propagates to bond/angle/dihedral lookups for those types.
                    self._strict_ff_types.add(ff_type)

            # For each copy of this molecule
            for _copy_idx in range(count):
                atom_id_offset = global_atom_id - 1

                # Add atoms
                for atom in mol_topo.atoms:
                    element, _is_aromatic, ff_type = mol_atom_types[atom.index]
                    opls_params = self._get_ff_atom_params_from_type(
                        ff_type=ff_type, element=element
                    )
                    opls_type = ff_type

                    # Get or create atom type
                    if opls_type not in self._atom_type_map:
                        type_id = len(self._atom_type_map) + 1
                        self._atom_type_map[opls_type] = type_id
                        system.atom_types.append(
                            AtomType(
                                type_id=type_id,
                                mass=opls_params["mass"],
                                element=element,
                                epsilon=opls_params["epsilon"],
                                sigma=opls_params["sigma"],
                                comment=f"{self._ff_config.name} {opls_type}",
                            )
                        )

                    # Get coordinates
                    if packed_coords and coord_index < len(packed_coords):
                        x, y, z = packed_coords[coord_index]
                        coord_index += 1
                    else:
                        x, y, z = atom.x, atom.y, atom.z

                    # Require explicit per-atom charges (e.g., LigParGen/QM-derived).
                    # Do not silently fall back to FF type default charges.
                    if not getattr(atom, "charge_defined", False):
                        raise ValueError(
                            f"Charge undefined for {mol_topo.mol_id} atom #{atom.index} ({element})"
                        )
                    atom_charge = atom.charge

                    system.atoms.append(
                        Atom(
                            atom_id=global_atom_id,
                            mol_id=global_mol_id,
                            type_id=self._atom_type_map[opls_type],
                            charge=atom_charge,
                            x=x,
                            y=y,
                            z=z,
                            comment=f"{mol_topo.mol_id}:{element}",
                        )
                    )
                    global_atom_id += 1

                # Add bonds
                for bond in mol_topo.bonds:
                    elem1, _arom1, ff1 = mol_atom_types[bond.atom1]
                    elem2, _arom2, ff2 = mol_atom_types[bond.atom2]
                    bond_key = tuple(sorted([ff1, ff2]))
                    element_bond_key = tuple(sorted([elem1, elem2]))

                    # Get or create bond type
                    if bond_key not in self._bond_type_map:
                        type_id = len(self._bond_type_map) + 1
                        self._bond_type_map[bond_key] = type_id

                        # Get bond parameters
                        params, label = self._get_bond_interaction_params(
                            type_key=bond_key,
                            element_key=element_bond_key,
                        )
                        system.bond_types.append(
                            BondType(
                                type_id=type_id,
                                k=params["k"],
                                r0=params["r0"],
                                comment=label,
                            )
                        )

                    system.bonds.append(
                        Bond(
                            bond_id=global_bond_id,
                            type_id=self._bond_type_map[bond_key],
                            atom1=bond.atom1 + atom_id_offset,
                            atom2=bond.atom2 + atom_id_offset,
                        )
                    )
                    global_bond_id += 1

                # Add angles
                for a1, a2, a3 in mol_topo.get_angles():
                    elem1, _arom1, ff1 = mol_atom_types[a1]
                    elem2, _arom2, ff2 = mol_atom_types[a2]
                    elem3, _arom3, ff3 = mol_atom_types[a3]
                    angle_type_key = (ff1, ff2, ff3) if ff1 <= ff3 else (ff3, ff2, ff1)
                    angle_key = (elem1, elem2, elem3) if elem1 <= elem3 else (elem3, elem2, elem1)

                    if angle_type_key not in self._angle_type_map:
                        type_id = len(self._angle_type_map) + 1
                        self._angle_type_map[angle_type_key] = type_id

                        params, label = self._get_angle_interaction_params(
                            type_key=angle_type_key,
                            element_key=angle_key,
                        )
                        system.angle_types.append(
                            AngleType(
                                type_id=type_id,
                                k=params["k"],
                                theta0=params["theta0"],
                                comment=label,
                            )
                        )

                    system.angles.append(
                        Angle(
                            angle_id=global_angle_id,
                            type_id=self._angle_type_map[angle_type_key],
                            atom1=a1 + atom_id_offset,
                            atom2=a2 + atom_id_offset,
                            atom3=a3 + atom_id_offset,
                        )
                    )
                    global_angle_id += 1

                # Add dihedrals
                for a1, a2, a3, a4 in mol_topo.get_dihedrals():
                    elem1, _arom1, ff1 = mol_atom_types[a1]
                    elem2, _arom2, ff2 = mol_atom_types[a2]
                    elem3, _arom3, ff3 = mol_atom_types[a3]
                    elem4, _arom4, ff4 = mol_atom_types[a4]
                    dih_key = (ff1, ff2, ff3, ff4)
                    element_dih_key = (elem1, elem2, elem3, elem4)
                    # Normalize key direction
                    if dih_key > dih_key[::-1]:
                        dih_key = dih_key[::-1]
                    if element_dih_key > element_dih_key[::-1]:
                        element_dih_key = element_dih_key[::-1]

                    if dih_key not in self._dihedral_type_map:
                        type_id = len(self._dihedral_type_map) + 1
                        self._dihedral_type_map[dih_key] = type_id

                        params, label = self._get_dihedral_interaction_params(
                            type_key=dih_key,
                            element_key=element_dih_key,
                        )
                        system.dihedral_types.append(
                            DihedralType(
                                type_id=type_id,
                                style=params.get("style", "fourier"),
                                coeffs=tuple(
                                    params.get(
                                        "coeffs",
                                        (
                                            params.get("k1", 0.0),
                                            params.get("k2", 0.0),
                                            params.get("k3", 0.0),
                                            params.get("k4", 0.0),
                                        ),
                                    )
                                ),
                                comment=label,
                            )
                        )

                    system.dihedrals.append(
                        Dihedral(
                            dihedral_id=global_dihedral_id,
                            type_id=self._dihedral_type_map[dih_key],
                            atom1=a1 + atom_id_offset,
                            atom2=a2 + atom_id_offset,
                            atom3=a3 + atom_id_offset,
                            atom4=a4 + atom_id_offset,
                        )
                    )
                    global_dihedral_id += 1

                # Add impropers (from artifact instances if available)
                improper_instances = getattr(mol_topo, "improper_instances", None) or []
                for a1, a2, a3, a4 in improper_instances:
                    elem1, _arom1, ff1 = mol_atom_types[a1]
                    elem2, _arom2, ff2 = mol_atom_types[a2]
                    elem3, _arom3, ff3 = mol_atom_types[a3]
                    elem4, _arom4, ff4 = mol_atom_types[a4]
                    imp_key = (ff1, ff2, ff3, ff4)

                    if imp_key not in self._improper_type_map:
                        type_id = len(self._improper_type_map) + 1
                        self._improper_type_map[imp_key] = type_id

                        # Resolve improper params with explicit priority chain:
                        # 1. improper_param_overrides (curated artifact)
                        # 2. dihedral_param_overrides (legacy compatibility)
                        # 3. bond_param_overrides __improper__ shim (legacy)
                        # 4. default cvff (1.1, -1, 2)
                        imp_str_key = f"{ff1}-{ff2}-{ff3}-{ff4}"
                        imp_str_key_rev = f"{ff4}-{ff3}-{ff2}-{ff1}"

                        # Priority 1: dedicated improper overrides
                        imp_params = self._improper_param_overrides.get(imp_str_key)
                        if imp_params is None:
                            imp_params = self._improper_param_overrides.get(imp_str_key_rev)
                        if imp_params is not None:
                            system.improper_types.append(
                                ImproperType(
                                    type_id=type_id,
                                    style=imp_params.get("style", "cvff"),
                                    coeffs=tuple(imp_params.get("coeffs", (0.0, -1, 2))),
                                    comment=f"{imp_str_key}(improper_override)",
                                )
                            )
                        else:
                            # Priority 2: dihedral overrides (legacy)
                            dih_imp = self._dihedral_param_overrides.get(imp_str_key)
                            if dih_imp is None:
                                dih_imp = self._dihedral_param_overrides.get(imp_str_key_rev)
                            if dih_imp is not None:
                                system.improper_types.append(
                                    ImproperType(
                                        type_id=type_id,
                                        style=dih_imp.get("style", "cvff"),
                                        coeffs=tuple(dih_imp.get("coeffs", (0.0, -1, 2))),
                                        comment=f"{imp_str_key}(dihedral_fallback)",
                                    )
                                )
                            else:
                                # Priority 3: bond overrides __improper__ shim
                                bo_imp = (self._bond_param_overrides or {}).get(
                                    f"__improper__{imp_str_key}"
                                )
                                if bo_imp is not None:
                                    system.improper_types.append(
                                        ImproperType(
                                            type_id=type_id,
                                            style=bo_imp.get("style", "cvff"),
                                            coeffs=tuple(bo_imp.get("coeffs", (1.1, -1, 2))),
                                            comment=f"{imp_str_key}(bond_shim)",
                                        )
                                    )
                                else:
                                    # Priority 4: default cvff improper
                                    system.improper_types.append(
                                        ImproperType(
                                            type_id=type_id,
                                            style="cvff",
                                            coeffs=(1.1, -1, 2),
                                            comment=f"{imp_str_key}(default)",
                                        )
                                    )

                    system.impropers.append(
                        Improper(
                            improper_id=global_improper_id,
                            type_id=self._improper_type_map[imp_key],
                            atom1=a1 + atom_id_offset,
                            atom2=a2 + atom_id_offset,
                            atom3=a3 + atom_id_offset,
                            atom4=a4 + atom_id_offset,
                        )
                    )
                    global_improper_id += 1

                global_mol_id += 1

        logger.info(
            f"Created topology: {len(system.atoms)} atoms, {len(system.bonds)} bonds, "
            f"{len(system.angles)} angles, {len(system.dihedrals)} dihedrals, "
            f"{len(system.impropers)} impropers"
        )
        return system
