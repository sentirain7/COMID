"""
Crystal Slab Builder for layered systems.

Generates crystal slabs (SiO2, CaCO3, etc.) for interface studies.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from common.constants import ATOMIC_WEIGHTS
from common.logging import get_logger

from .layer_spec import CrystalCellMode, CrystalMaterial, CrystalSpec, SurfaceOrientation
from .supercell_search import (
    SupercellResult,
    _best_nz,
    enumerate_unit_cells,
    find_optimal_supercell,
)


def _base_element(label: str) -> str:
    """Map subtype label to base element for mass lookup.

    'Si_s' → 'Si', 'Os' → 'O', 'Hoh' → 'H', 'Si' → 'Si'.
    """
    _LABEL_TO_ELEMENT = {"Os": "O", "Hoh": "H"}
    if label in _LABEL_TO_ELEMENT:
        return _LABEL_TO_ELEMENT[label]
    if label.endswith("_s"):
        return label[:-2]
    return label


@dataclass
class Atom:
    """Represents a single atom."""

    id: int
    type: int
    x: float
    y: float
    z: float
    element: str
    charge: float = 0.0
    mol_id: int = 1


@dataclass
class CrystalSlab:
    """Crystal slab structure."""

    atoms: list[Atom]
    box: tuple[float, float, float]  # lx, ly, lz
    material: CrystalMaterial
    surface: SurfaceOrientation
    n_atoms: int
    atom_types: dict[str, int]  # element -> type_id
    nx: int = 1
    ny: int = 1
    nz: int = 1
    transformation_matrix: list[list[int]] | None = None
    n_cells_xy: int | None = None
    error_xy_pct: float | None = None
    matrix_search_used: bool = False
    matrix_search_fallback_reason: str | None = None

    def get_positions(self) -> np.ndarray:
        """Get atom positions as numpy array."""
        return np.array([[a.x, a.y, a.z] for a in self.atoms])

    def get_surface_atoms(self, tolerance: float = 1.0) -> list[Atom]:
        """Get atoms at the top surface."""
        z_max = max(a.z for a in self.atoms)
        return [a for a in self.atoms if abs(a.z - z_max) < tolerance]

    def translate(self, dx: float, dy: float, dz: float) -> None:
        """Translate all atoms."""
        for atom in self.atoms:
            atom.x += dx
            atom.y += dy
            atom.z += dz

    def to_xyz(self, filepath: Path) -> None:
        """Write to XYZ file."""
        with open(filepath, "w") as f:
            f.write(f"{len(self.atoms)}\n")
            f.write(f"Crystal slab: {self.material.value} {self.surface.value}\n")
            for atom in self.atoms:
                f.write(f"{atom.element} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}\n")

    def to_lammps_data(self, filepath: Path, title: str = "Crystal slab") -> None:
        """Write to LAMMPS data file format."""
        with open(filepath, "w") as f:
            f.write(f"{title}\n\n")
            f.write(f"{len(self.atoms)} atoms\n")
            f.write(f"{len(self.atom_types)} atom types\n\n")
            f.write(f"0.0 {self.box[0]:.6f} xlo xhi\n")
            f.write(f"0.0 {self.box[1]:.6f} ylo yhi\n")
            f.write(f"0.0 {self.box[2]:.6f} zlo zhi\n\n")
            f.write("Masses\n\n")

            for elem, type_id in sorted(self.atom_types.items(), key=lambda x: x[1]):
                base = _base_element(elem)
                f.write(f"{type_id} {ATOMIC_WEIGHTS.get(base, 12.0):.4f}  # {elem}\n")

            f.write("\nAtoms\n\n")
            for atom in self.atoms:
                f.write(
                    f"{atom.id} {atom.mol_id} {atom.type} {atom.charge:.4f} "
                    f"{atom.x:.6f} {atom.y:.6f} {atom.z:.6f}\n"
                )


logger = get_logger("builder.crystal_builder")


# Hardcoded fallback for the per-material mineral charges. The editable SSOT
# lives at ``data/forcefields/mineral_charge_catalog.yaml`` and is loaded into
# ``CrystalBuilder.CHARGES`` at import time. The two are kept identical by
# ``tests/unit/test_mineral_charge_ssot.py`` (which also binds them to the
# curated CLAYFF profiles in ``inorganic_profiles.yaml``). The fallback exists
# so module import never depends on the yaml being present (tmp_path tests,
# fresh checkouts). When updating a charge, edit BOTH this dict AND the yaml.
_CHARGES_HARDCODED_FALLBACK: dict[CrystalMaterial, dict[str, float]] = {
    CrystalMaterial.SIO2: {"Si": 2.1, "O": -1.05},
    CrystalMaterial.CITE: {"Ca": 2.0, "C": 1.123, "O": -1.041},
    CrystalMaterial.AL2O3: {"Al": 1.575, "O": -1.05},
    CrystalMaterial.MGO: {"Mg": 2.0, "O": -2.0},
    CrystalMaterial.FE2O3: {"Fe": 1.8, "O": -1.2},
    CrystalMaterial.MGCO3: {"Mg": 2.0, "C": 1.123, "O": -1.041},
    CrystalMaterial.CAO: {"Ca": 2.0, "O": -2.0},
    CrystalMaterial.TIO2: {"Ti": 2.196, "O": -1.098},
    CrystalMaterial.ZNO: {"Zn": 1.2, "O": -1.2},
    CrystalMaterial.NACL: {"Na": 1.0, "Cl": -1.0},
    CrystalMaterial.KCL: {"K": 1.0, "Cl": -1.0},
    CrystalMaterial.AL: {"Al": 0.0},
    CrystalMaterial.FE: {"Fe": 0.0},
    CrystalMaterial.CU: {"Cu": 0.0},
    CrystalMaterial.NI: {"Ni": 0.0},
}


def _load_crystal_charges() -> dict[CrystalMaterial, dict[str, float]]:
    """Load mineral charges from the yaml SSOT, falling back to the hardcoded dict.

    Mirrors the Wave 4 pattern used by ``forcefield.interface_ff``: the yaml is
    the editable SSOT and wins when it loads cleanly; otherwise the hardcoded
    fallback is used so import never breaks.
    """
    try:
        from forcefield.mineral_charge_loader import (
            MineralChargeLoadError,
            load_mineral_charges,
        )
    except Exception as exc:  # pragma: no cover - loader import should not fail
        logger.debug("crystal charges: loader import failed (%s); using fallback", exc)
        return {k: dict(v) for k, v in _CHARGES_HARDCODED_FALLBACK.items()}

    try:
        raw = load_mineral_charges()
    except MineralChargeLoadError as exc:
        logger.debug("crystal charges: yaml SSOT not loadable (%s); using fallback", exc)
        return {k: dict(v) for k, v in _CHARGES_HARDCODED_FALLBACK.items()}
    except Exception as exc:
        logger.warning("crystal charges: unexpected error loading yaml SSOT (%s); using fallback", exc)
        return {k: dict(v) for k, v in _CHARGES_HARDCODED_FALLBACK.items()}

    mapped: dict[CrystalMaterial, dict[str, float]] = {}
    for value, charges in raw.items():
        try:
            mapped[CrystalMaterial(value)] = dict(charges)
        except ValueError:
            logger.warning(
                "crystal charges: yaml has unknown material %r; using hardcoded fallback", value
            )
            return {k: dict(v) for k, v in _CHARGES_HARDCODED_FALLBACK.items()}
    return mapped


class CrystalBuilder:
    """
    Builder for crystal slabs.

    Generates periodic crystal structures for interface studies.
    """

    # Unit cell parameters (Angstroms and degrees)
    UNIT_CELLS = {
        CrystalMaterial.SIO2: {
            "a": 4.913,
            "b": 4.913,
            "c": 5.405,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Alpha-quartz unit cell (simplified)
                ("Si", 0.4697, 0.0000, 0.0000),
                ("Si", 0.0000, 0.4697, 0.6667),
                ("Si", 0.5303, 0.5303, 0.3333),
                ("O", 0.4135, 0.2669, 0.1191),
                ("O", 0.2669, 0.4135, 0.5476),
                ("O", 0.7331, 0.1466, 0.7858),
                ("O", 0.5865, 0.8534, 0.4524),
                ("O", 0.8534, 0.5865, 0.2142),
                ("O", 0.1466, 0.7331, 0.8809),
            ],
        },
        CrystalMaterial.CITE: {
            "a": 4.990,
            "b": 4.990,
            "c": 17.062,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Calcite CaCO3, R-3c (hex), 30 atoms/cell
                # Ref: Markgraf & Reeder (1985), Am. Min. 70, 590
                # Ca at 6b: basis (0,0,0),(0,0,½) + R centering (0,0,0),(⅔,⅓,⅓),(⅓,⅔,⅔)
                ("Ca", 0.0, 0.0, 0.0),
                ("Ca", 0.0, 0.0, 0.5),
                ("Ca", 2 / 3, 1 / 3, 1 / 3),
                ("Ca", 2 / 3, 1 / 3, 5 / 6),
                ("Ca", 1 / 3, 2 / 3, 2 / 3),
                ("Ca", 1 / 3, 2 / 3, 1 / 6),
                # C at 6a: basis (0,0,¼),(0,0,¾) + R centering
                ("C", 0.0, 0.0, 0.25),
                ("C", 0.0, 0.0, 0.75),
                ("C", 2 / 3, 1 / 3, 7 / 12),
                ("C", 2 / 3, 1 / 3, 1 / 12),
                ("C", 1 / 3, 2 / 3, 11 / 12),
                ("C", 1 / 3, 2 / 3, 5 / 12),
                # O at 18e: basis x=0.2578
                # (x,0,¼),(-x,-x,¼),(0,x,¼),(0,-x,¾),(x,x,¾),(-x,0,¾) + R centering
                ("O", 0.2578, 0.0, 0.25),
                ("O", -0.2578, -0.2578, 0.25),
                ("O", 0.0, 0.2578, 0.25),
                ("O", 0.0, -0.2578, 0.75),
                ("O", 0.2578, 0.2578, 0.75),
                ("O", -0.2578, 0.0, 0.75),
                ("O", 0.2578 + 2 / 3, 0.0 + 1 / 3, 0.25 + 1 / 3),
                ("O", -0.2578 + 2 / 3, -0.2578 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, 0.2578 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, -0.2578 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.2578 + 2 / 3, 0.2578 + 1 / 3, 0.75 + 1 / 3),
                ("O", -0.2578 + 2 / 3, 0.0 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.2578 + 1 / 3, 0.0 + 2 / 3, 0.25 + 2 / 3),
                ("O", -0.2578 + 1 / 3, -0.2578 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, 0.2578 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, -0.2578 + 2 / 3, 0.75 + 2 / 3),
                ("O", 0.2578 + 1 / 3, 0.2578 + 2 / 3, 0.75 + 2 / 3),
                ("O", -0.2578 + 1 / 3, 0.0 + 2 / 3, 0.75 + 2 / 3),
            ],
        },
        CrystalMaterial.AL2O3: {
            "a": 4.759,
            "b": 4.759,
            "c": 12.991,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Corundum Al2O3, R-3c (hex), 30 atoms/cell
                # Ref: Ishizawa et al. (1980), Acta Cryst. B36, 228
                # Al at 12c: basis (0,0,z),(0,0,-z),(0,0,z+½),(0,0,½-z) z=0.3523
                # + R centering (0,0,0),(⅔,⅓,⅓),(⅓,⅔,⅔)
                ("Al", 0.0, 0.0, 0.3523),
                ("Al", 0.0, 0.0, -0.3523),
                ("Al", 0.0, 0.0, 0.8523),
                ("Al", 0.0, 0.0, 0.1477),
                ("Al", 2 / 3, 1 / 3, 0.3523 + 1 / 3),
                ("Al", 2 / 3, 1 / 3, -0.3523 + 1 / 3),
                ("Al", 2 / 3, 1 / 3, 0.8523 + 1 / 3),
                ("Al", 2 / 3, 1 / 3, 0.1477 + 1 / 3),
                ("Al", 1 / 3, 2 / 3, 0.3523 + 2 / 3),
                ("Al", 1 / 3, 2 / 3, -0.3523 + 2 / 3),
                ("Al", 1 / 3, 2 / 3, 0.8523 + 2 / 3),
                ("Al", 1 / 3, 2 / 3, 0.1477 + 2 / 3),
                # O at 18e: basis x=0.3064
                # (x,0,¼),(-x,-x,¼),(0,x,¼),(0,-x,¾),(x,x,¾),(-x,0,¾)
                # + R centering
                ("O", 0.3064, 0.0, 0.25),
                ("O", -0.3064, -0.3064, 0.25),
                ("O", 0.0, 0.3064, 0.25),
                ("O", 0.0, -0.3064, 0.75),
                ("O", 0.3064, 0.3064, 0.75),
                ("O", -0.3064, 0.0, 0.75),
                ("O", 0.3064 + 2 / 3, 0.0 + 1 / 3, 0.25 + 1 / 3),
                ("O", -0.3064 + 2 / 3, -0.3064 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, 0.3064 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, -0.3064 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.3064 + 2 / 3, 0.3064 + 1 / 3, 0.75 + 1 / 3),
                ("O", -0.3064 + 2 / 3, 0.0 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.3064 + 1 / 3, 0.0 + 2 / 3, 0.25 + 2 / 3),
                ("O", -0.3064 + 1 / 3, -0.3064 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, 0.3064 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, -0.3064 + 2 / 3, 0.75 + 2 / 3),
                ("O", 0.3064 + 1 / 3, 0.3064 + 2 / 3, 0.75 + 2 / 3),
                ("O", -0.3064 + 1 / 3, 0.0 + 2 / 3, 0.75 + 2 / 3),
            ],
        },
        CrystalMaterial.MGO: {
            "a": 4.213,
            "b": 4.213,
            "c": 4.213,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # Rocksalt MgO, Fm-3m, 8 atoms/cell
                # Wyckoff 4a (Mg) + FCC centering
                ("Mg", 0.0, 0.0, 0.0),
                ("Mg", 0.0, 0.5, 0.5),
                ("Mg", 0.5, 0.0, 0.5),
                ("Mg", 0.5, 0.5, 0.0),
                # Wyckoff 4b (O) + FCC centering
                ("O", 0.5, 0.5, 0.5),
                ("O", 0.5, 0.0, 0.0),
                ("O", 0.0, 0.5, 0.0),
                ("O", 0.0, 0.0, 0.5),
            ],
        },
        CrystalMaterial.FE2O3: {
            "a": 5.035,
            "b": 5.035,
            "c": 13.750,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Hematite Fe2O3, R-3c (hex), 30 atoms/cell
                # Ref: Blake et al. (1966), Am. Min. 51, 123
                # Fe at 12c: basis (0,0,z),(0,0,-z),(0,0,z+½),(0,0,½-z) z=0.3553
                # + R centering (0,0,0),(⅔,⅓,⅓),(⅓,⅔,⅔)
                ("Fe", 0.0, 0.0, 0.3553),
                ("Fe", 0.0, 0.0, -0.3553),
                ("Fe", 0.0, 0.0, 0.8553),
                ("Fe", 0.0, 0.0, 0.1447),
                ("Fe", 2 / 3, 1 / 3, 0.3553 + 1 / 3),
                ("Fe", 2 / 3, 1 / 3, -0.3553 + 1 / 3),
                ("Fe", 2 / 3, 1 / 3, 0.8553 + 1 / 3),
                ("Fe", 2 / 3, 1 / 3, 0.1447 + 1 / 3),
                ("Fe", 1 / 3, 2 / 3, 0.3553 + 2 / 3),
                ("Fe", 1 / 3, 2 / 3, -0.3553 + 2 / 3),
                ("Fe", 1 / 3, 2 / 3, 0.8553 + 2 / 3),
                ("Fe", 1 / 3, 2 / 3, 0.1447 + 2 / 3),
                # O at 18e: basis x=0.3059
                # (x,0,¼),(-x,-x,¼),(0,x,¼),(0,-x,¾),(x,x,¾),(-x,0,¾)
                # + R centering
                ("O", 0.3059, 0.0, 0.25),
                ("O", -0.3059, -0.3059, 0.25),
                ("O", 0.0, 0.3059, 0.25),
                ("O", 0.0, -0.3059, 0.75),
                ("O", 0.3059, 0.3059, 0.75),
                ("O", -0.3059, 0.0, 0.75),
                ("O", 0.3059 + 2 / 3, 0.0 + 1 / 3, 0.25 + 1 / 3),
                ("O", -0.3059 + 2 / 3, -0.3059 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, 0.3059 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, -0.3059 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.3059 + 2 / 3, 0.3059 + 1 / 3, 0.75 + 1 / 3),
                ("O", -0.3059 + 2 / 3, 0.0 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.3059 + 1 / 3, 0.0 + 2 / 3, 0.25 + 2 / 3),
                ("O", -0.3059 + 1 / 3, -0.3059 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, 0.3059 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, -0.3059 + 2 / 3, 0.75 + 2 / 3),
                ("O", 0.3059 + 1 / 3, 0.3059 + 2 / 3, 0.75 + 2 / 3),
                ("O", -0.3059 + 1 / 3, 0.0 + 2 / 3, 0.75 + 2 / 3),
            ],
        },
        CrystalMaterial.MGCO3: {
            "a": 4.633,
            "b": 4.633,
            "c": 15.020,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Magnesite MgCO3, R-3c (hex), 30 atoms/cell
                # Ref: Markgraf & Reeder (1985), Am. Min. 70, 590
                # Mg at 6b: basis (0,0,0),(0,0,½) + R centering
                ("Mg", 0.0, 0.0, 0.0),
                ("Mg", 0.0, 0.0, 0.5),
                ("Mg", 2 / 3, 1 / 3, 1 / 3),
                ("Mg", 2 / 3, 1 / 3, 5 / 6),
                ("Mg", 1 / 3, 2 / 3, 2 / 3),
                ("Mg", 1 / 3, 2 / 3, 1 / 6),
                # C at 6a: basis (0,0,¼),(0,0,¾) + R centering
                ("C", 0.0, 0.0, 0.25),
                ("C", 0.0, 0.0, 0.75),
                ("C", 2 / 3, 1 / 3, 7 / 12),
                ("C", 2 / 3, 1 / 3, 1 / 12),
                ("C", 1 / 3, 2 / 3, 11 / 12),
                ("C", 1 / 3, 2 / 3, 5 / 12),
                # O at 18e: basis x=0.2773
                # (x,0,¼),(-x,-x,¼),(0,x,¼),(0,-x,¾),(x,x,¾),(-x,0,¾)
                # + R centering
                ("O", 0.2773, 0.0, 0.25),
                ("O", -0.2773, -0.2773, 0.25),
                ("O", 0.0, 0.2773, 0.25),
                ("O", 0.0, -0.2773, 0.75),
                ("O", 0.2773, 0.2773, 0.75),
                ("O", -0.2773, 0.0, 0.75),
                ("O", 0.2773 + 2 / 3, 0.0 + 1 / 3, 0.25 + 1 / 3),
                ("O", -0.2773 + 2 / 3, -0.2773 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, 0.2773 + 1 / 3, 0.25 + 1 / 3),
                ("O", 0.0 + 2 / 3, -0.2773 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.2773 + 2 / 3, 0.2773 + 1 / 3, 0.75 + 1 / 3),
                ("O", -0.2773 + 2 / 3, 0.0 + 1 / 3, 0.75 + 1 / 3),
                ("O", 0.2773 + 1 / 3, 0.0 + 2 / 3, 0.25 + 2 / 3),
                ("O", -0.2773 + 1 / 3, -0.2773 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, 0.2773 + 2 / 3, 0.25 + 2 / 3),
                ("O", 0.0 + 1 / 3, -0.2773 + 2 / 3, 0.75 + 2 / 3),
                ("O", 0.2773 + 1 / 3, 0.2773 + 2 / 3, 0.75 + 2 / 3),
                ("O", -0.2773 + 1 / 3, 0.0 + 2 / 3, 0.75 + 2 / 3),
            ],
        },
        CrystalMaterial.CAO: {
            "a": 4.810,
            "b": 4.810,
            "c": 4.810,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # Rocksalt CaO, Fm-3m, 8 atoms/cell
                # Wyckoff 4a (Ca) + FCC centering
                ("Ca", 0.0, 0.0, 0.0),
                ("Ca", 0.0, 0.5, 0.5),
                ("Ca", 0.5, 0.0, 0.5),
                ("Ca", 0.5, 0.5, 0.0),
                # Wyckoff 4b (O) + FCC centering
                ("O", 0.5, 0.5, 0.5),
                ("O", 0.5, 0.0, 0.0),
                ("O", 0.0, 0.5, 0.0),
                ("O", 0.0, 0.0, 0.5),
            ],
        },
        CrystalMaterial.TIO2: {
            "a": 4.594,
            "b": 4.594,
            "c": 2.958,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # Rutile TiO2 (simplified)
                ("Ti", 0.0, 0.0, 0.0),
                ("Ti", 0.5, 0.5, 0.5),
                ("O", 0.305, 0.305, 0.0),
                ("O", 0.695, 0.695, 0.0),
                ("O", 0.805, 0.195, 0.5),
                ("O", 0.195, 0.805, 0.5),
            ],
        },
        CrystalMaterial.ZNO: {
            "a": 3.250,
            "b": 3.250,
            "c": 5.207,
            "alpha": 90,
            "beta": 90,
            "gamma": 120,
            "atoms": [
                # Wurtzite ZnO (simplified)
                ("Zn", 0.0, 0.0, 0.0),
                ("Zn", 2.0 / 3.0, 1.0 / 3.0, 0.5),
                ("O", 0.0, 0.0, 0.382),
                ("O", 2.0 / 3.0, 1.0 / 3.0, 0.882),
            ],
        },
        CrystalMaterial.NACL: {
            "a": 5.640,
            "b": 5.640,
            "c": 5.640,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # Rocksalt NaCl, Fm-3m, 8 atoms/cell
                # Wyckoff 4a (Na) + FCC centering
                ("Na", 0.0, 0.0, 0.0),
                ("Na", 0.0, 0.5, 0.5),
                ("Na", 0.5, 0.0, 0.5),
                ("Na", 0.5, 0.5, 0.0),
                # Wyckoff 4b (Cl) + FCC centering
                ("Cl", 0.5, 0.5, 0.5),
                ("Cl", 0.5, 0.0, 0.0),
                ("Cl", 0.0, 0.5, 0.0),
                ("Cl", 0.0, 0.0, 0.5),
            ],
        },
        CrystalMaterial.KCL: {
            "a": 6.292,
            "b": 6.292,
            "c": 6.292,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # Rocksalt KCl, Fm-3m, 8 atoms/cell
                # Wyckoff 4a (K) + FCC centering
                ("K", 0.0, 0.0, 0.0),
                ("K", 0.0, 0.5, 0.5),
                ("K", 0.5, 0.0, 0.5),
                ("K", 0.5, 0.5, 0.0),
                # Wyckoff 4b (Cl) + FCC centering
                ("Cl", 0.5, 0.5, 0.5),
                ("Cl", 0.5, 0.0, 0.0),
                ("Cl", 0.0, 0.5, 0.0),
                ("Cl", 0.0, 0.0, 0.5),
            ],
        },
        CrystalMaterial.AL: {
            "a": 4.049,
            "b": 4.049,
            "c": 4.049,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # FCC Al
                ("Al", 0.0, 0.0, 0.0),
                ("Al", 0.0, 0.5, 0.5),
                ("Al", 0.5, 0.0, 0.5),
                ("Al", 0.5, 0.5, 0.0),
            ],
        },
        CrystalMaterial.FE: {
            "a": 2.866,
            "b": 2.866,
            "c": 2.866,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # BCC Fe
                ("Fe", 0.0, 0.0, 0.0),
                ("Fe", 0.5, 0.5, 0.5),
            ],
        },
        CrystalMaterial.CU: {
            "a": 3.615,
            "b": 3.615,
            "c": 3.615,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # FCC Cu
                ("Cu", 0.0, 0.0, 0.0),
                ("Cu", 0.0, 0.5, 0.5),
                ("Cu", 0.5, 0.0, 0.5),
                ("Cu", 0.5, 0.5, 0.0),
            ],
        },
        CrystalMaterial.NI: {
            "a": 3.524,
            "b": 3.524,
            "c": 3.524,
            "alpha": 90,
            "beta": 90,
            "gamma": 90,
            "atoms": [
                # FCC Ni
                ("Ni", 0.0, 0.0, 0.0),
                ("Ni", 0.0, 0.5, 0.5),
                ("Ni", 0.5, 0.0, 0.5),
                ("Ni", 0.5, 0.5, 0.0),
            ],
        },
    }

    # Per-material mineral charges (CLAYFF family). Loaded from the yaml SSOT
    # ``data/forcefields/mineral_charge_catalog.yaml`` with a hardcoded fallback.
    CHARGES = _load_crystal_charges()

    @classmethod
    def preferred_surface(cls, material: CrystalMaterial) -> SurfaceOrientation:
        """Determine the thermodynamically preferred surface from crystal structure.

        The optimal surface is derived from crystal-system properties rather
        than a per-material lookup table:

        * **Hexagonal / trigonal** (gamma != 90): (001) basal plane — always the
          most stable cleavage face for layered/hexagonal oxides and carbonates.
        * **Cubic, single element, 4 atoms/cell** (FCC metals): (111) close-packed.
        * **Cubic, single element, 2 atoms/cell** (BCC metals): (110) close-packed.
        * **Tetragonal, multi-element** (rutile-type): (110) thermodynamic minimum.
        * **Cubic, multi-element** (rocksalt-type): (001) non-polar cleavage.
        * **Fallback**: (001).

        Returns:
            Preferred :class:`SurfaceOrientation` for the given material.
        """
        unit_cell: dict[str, Any] | None = cls.UNIT_CELLS.get(material)
        if unit_cell is None:
            return SurfaceOrientation.ORIENT_001

        a = float(unit_cell["a"])
        b = float(unit_cell["b"])
        c = float(unit_cell["c"])
        gamma = float(unit_cell["gamma"])
        atoms: list[tuple[str, float, float, float]] = unit_cell["atoms"]
        elements = {elem for elem, *_ in atoms}
        n_atoms = len(atoms)

        # Hexagonal / trigonal: basal plane (001)
        if not math.isclose(gamma, 90.0, abs_tol=1.0):
            return SurfaceOrientation.ORIENT_001

        # Cubic / tetragonal (gamma ~ 90)
        is_cubic = math.isclose(a, b, rel_tol=0.02) and math.isclose(b, c, rel_tol=0.02)
        is_tetragonal = math.isclose(a, b, rel_tol=0.02) and not math.isclose(b, c, rel_tol=0.02)

        # Pure metals (single element)
        if len(elements) == 1:
            if n_atoms == 4 and is_cubic:
                # FCC: close-packed plane is (111)
                return SurfaceOrientation.ORIENT_111
            if n_atoms == 2 and is_cubic:
                # BCC: close-packed plane is (110)
                return SurfaceOrientation.ORIENT_110
            return SurfaceOrientation.ORIENT_001

        # Tetragonal compounds (rutile-type TiO2)
        if is_tetragonal and n_atoms == 6 and len(elements) == 2:
            return SurfaceOrientation.ORIENT_110

        # Cubic compounds (rocksalt MgO, CaO, NaCl, KCl)
        if is_cubic and n_atoms == 8 and len(elements) == 2:
            return SurfaceOrientation.ORIENT_001

        return SurfaceOrientation.ORIENT_001

    def __init__(self) -> None:
        """Initialize crystal builder."""
        pass

    def build(self, spec: CrystalSpec) -> CrystalSlab:
        """
        Build a crystal slab from specification.

        Args:
            spec: Crystal specification

        Returns:
            CrystalSlab structure
        """
        if spec.material == CrystalMaterial.AGGREGATE:
            return self._build_generic_aggregate(spec)

        unit_cell = self.UNIT_CELLS.get(spec.material)
        if unit_cell is None:
            raise ValueError(f"Unknown crystal material: {spec.material}")

        return self._build_from_unit_cell(spec, unit_cell)

    def build_from_unit_cell(
        self,
        spec: CrystalSpec,
        unit_cell: dict[str, Any],
        material: CrystalMaterial = CrystalMaterial.AGGREGATE,
    ) -> CrystalSlab:
        """
        Build crystal slab from an externally provided unit cell (e.g., CIF import).

        Args:
            spec: Crystal build specification (replication/target geometry)
            unit_cell: Unit-cell payload with {a,b,c,alpha,beta,gamma,atoms}
            material: Material label used for charge lookup and metadata

        Notes:
            Current Cartesian conversion supports orthogonal alpha/beta (near 90 deg)
            with in-plane skew handled via gamma.
        """
        required = {"a", "b", "c", "alpha", "beta", "gamma", "atoms"}
        missing = sorted(required - set(unit_cell.keys()))
        if missing:
            raise ValueError(f"Unit cell missing required fields: {missing}")

        alpha = float(unit_cell["alpha"])
        beta = float(unit_cell["beta"])
        if not math.isclose(alpha, 90.0, abs_tol=0.1) or not math.isclose(beta, 90.0, abs_tol=0.1):
            raise ValueError(
                "Unit cell with non-orthogonal alpha/beta is not supported yet: "
                f"alpha={alpha}, beta={beta}"
            )

        spec_copy = CrystalSpec(
            material=material,
            surface=spec.surface,
            cell_mode=spec.cell_mode,
            thickness_angstrom=spec.thickness_angstrom,
            xy_size_angstrom=spec.xy_size_angstrom,
            nx=spec.nx,
            ny=spec.ny,
            nz=spec.nz,
            hydroxylated=spec.hydroxylated,
            hydroxyl_density=spec.hydroxyl_density,
            use_matrix_search=getattr(spec, "use_matrix_search", True),
            max_cells_xy=getattr(spec, "max_cells_xy", 200),
            matrix_ortho_tolerance=getattr(spec, "matrix_ortho_tolerance", 1e-8),
        )
        return self._build_from_unit_cell(spec_copy, unit_cell)

    def _build_from_unit_cell(
        self,
        spec: CrystalSpec,
        unit_cell: dict[str, Any],
    ) -> CrystalSlab:
        """Build crystal by replicating unit cell."""
        a, b, c = unit_cell["a"], unit_cell["b"], unit_cell["c"]
        gamma_deg = float(unit_cell["gamma"])
        gamma = math.radians(gamma_deg)
        sin_gamma = math.sin(gamma)
        if abs(sin_gamma) < 1e-6:
            raise ValueError(f"Unsupported gamma for crystal build: {unit_cell['gamma']}")
        cell_mode = self._resolve_cell_mode(spec)

        use_matrix = (
            bool(getattr(spec, "use_matrix_search", True))
            and spec.xy_size_angstrom > 0
            and cell_mode == CrystalCellMode.ORTHOGONALIZED
            and abs(gamma_deg - 90.0) > 0.1
        )
        if use_matrix:
            matrix_result = find_optimal_supercell(
                a=float(a),
                b=float(b),
                gamma_deg=gamma_deg,
                c=float(c),
                target_xy=float(spec.xy_size_angstrom),
                target_z=float(spec.thickness_angstrom),
                max_cells_xy=int(getattr(spec, "max_cells_xy", 200)),
                ortho_tol=float(getattr(spec, "matrix_ortho_tolerance", 1e-8)),
                min_nz=1,  # nz determined by target_z, not default spec.nz
            )
            if matrix_result.fallback_reason is None:
                return self._build_with_matrix(
                    spec=spec,
                    unit_cell=unit_cell,
                    result=matrix_result,
                    sin_gamma=sin_gamma,
                )

            diag_nx = max(1, int(matrix_result.matrix[0][0]))
            diag_ny = max(1, int(matrix_result.matrix[1][1]))
            return self._build_with_replicates(
                spec=spec,
                unit_cell=unit_cell,
                nx=diag_nx,
                ny=diag_ny,
                nz=matrix_result.nz,
                lx=matrix_result.lx,
                ly=matrix_result.ly,
                lz=matrix_result.lz,
                cell_mode=cell_mode,
                transformation_matrix=[
                    list(matrix_result.matrix[0]),
                    list(matrix_result.matrix[1]),
                ],
                n_cells_xy=matrix_result.det,
                error_xy_pct=matrix_result.error_xy_pct,
                matrix_search_used=False,
                matrix_search_fallback_reason=matrix_result.fallback_reason,
            )

        nx, ny, nz, a, b, c, lx, ly, lz = self._resolve_replication_and_lattice(
            spec=spec,
            a=a,
            b=b,
            c=c,
            sin_gamma=sin_gamma,
        )
        return self._build_with_replicates(
            spec=spec,
            unit_cell=unit_cell,
            nx=nx,
            ny=ny,
            nz=nz,
            lx=lx,
            ly=ly,
            lz=lz,
            cell_mode=cell_mode,
        )

    @staticmethod
    def _find_nearest_atom(
        target: Atom,
        candidates: list[Atom],
        lx: float,
        ly: float,
        cutoff: float = 3.0,
    ) -> Atom | None:
        """Find nearest candidate atom with PBC in x,y."""
        best, best_d2 = None, cutoff * cutoff
        for c in candidates:
            dx = target.x - c.x
            dy = target.y - c.y
            dz = target.z - c.z
            # Minimum image convention (x, y only — z is slab direction)
            dx -= lx * round(dx / lx) if lx > 0 else 0
            dy -= ly * round(dy / ly) if ly > 0 else 0
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < best_d2:
                best_d2 = d2
                best = c
        return best

    def _add_hydroxyl_groups(
        self,
        atoms: list[Atom],
        atom_types: dict[str, int],
        spec: CrystalSpec,
        lx: float,
        ly: float,
        charges: dict[str, float],
    ) -> tuple[list[Atom], dict[str, int], set[int]]:
        """Add hydroxyl groups to crystal surface.

        Returns:
            Tuple of (atoms, atom_types, hydroxylated_o_ids).
        """
        # Get surface oxygen atoms
        z_max = max(a.z for a in atoms)
        surface_oxygens = [a for a in atoms if a.element == "O" and abs(a.z - z_max) < 1.0]

        # Calculate number of -OH groups
        area_nm2 = (lx * ly) / 100  # Å² to nm²
        n_oh = int(spec.hydroxyl_density * area_nm2)

        # Add H atoms above selected O atoms
        atom_id = len(atoms) + 1
        oh_bond_length = 0.96  # Å

        hydroxylated_o_ids: set[int] = set()

        # Select random O atoms for -OH
        np.random.seed(42)
        if len(surface_oxygens) > 0:
            # Ensure we have H atom type only when OH groups will be added
            if "H" not in atom_types:
                atom_types["H"] = len(atom_types) + 1
            selected = np.random.choice(
                len(surface_oxygens),
                min(n_oh, len(surface_oxygens)),
                replace=False,
            )

            for idx in selected:
                o_atom = surface_oxygens[idx]
                hydroxylated_o_ids.add(o_atom.id)
                atoms.append(
                    Atom(
                        id=atom_id,
                        type=atom_types["H"],
                        x=o_atom.x,
                        y=o_atom.y,
                        z=o_atom.z + oh_bond_length,
                        element="H",
                        charge=charges.get("H", 0.4),
                    )
                )
                atom_id += 1

        return atoms, atom_types, hydroxylated_o_ids

    def _finalize_hydroxyl_types(
        self,
        atoms: list[Atom],
        atom_types: dict[str, int],
        hydroxylated_o_ids: set[int],
        material: CrystalMaterial,
        lx: float,
        ly: float,
    ) -> tuple[list[Atom], dict[str, int]]:
        """Reclassify H→Hoh, selected O→Os, and nearest cation→{elem}_s.

        Intentional subtype expansion for crystal slab data files:
        - Os/Hoh: charge-neutral hydroxyl types (q_Os = q_O - q_H, q_Hoh = q_H)
        - {elem}_s: surface cation type (charge unchanged, type ID only differs)

        The cation_s subtype distinguishes surface cations adjacent to hydroxyl
        oxygens from bulk cations.  In the layered merge path these subtypes are
        mapped back to bare elements for INTERFACE FF lookup, which is expected.
        The type separation is preserved in standalone crystal .data files for
        readability and as a basis for future surface-specific FF parameterisation.

        Structural cation selection: max positive charge element from CHARGES
        dict (e.g. Ca for CaCO3, not C).
        """
        if not hydroxylated_o_ids:
            return atoms, atom_types

        charges = self.CHARGES.get(material, {})
        if "O" not in charges:
            return atoms, atom_types

        q_H = charges.get("H", 0.4)
        q_Os = charges["O"] - q_H

        # ── Structural cation: max positive charge element ──
        positive = {e: q for e, q in charges.items() if q > 0 and e != "H"}
        cation_elem: str | None = max(positive, key=lambda e: positive[e]) if positive else None

        # ── Surface cation search: nearest cation to each Os ──
        cation_s_ids: set[int] = set()
        if cation_elem is not None:
            cation_atoms = [a for a in atoms if a.element == cation_elem]
            os_atoms = [a for a in atoms if a.id in hydroxylated_o_ids]
            for os_atom in os_atoms:
                nearest = self._find_nearest_atom(os_atom, cation_atoms, lx, ly, cutoff=3.0)
                if nearest is not None:
                    cation_s_ids.add(nearest.id)

        # ── Type ID assignment ──
        hoh_type_id = atom_types.get("H")
        next_id = max(atom_types.values()) + 1

        if "Os" not in atom_types:
            atom_types["Os"] = next_id
            next_id += 1

        cation_s_label: str | None = None
        if cation_elem is not None and cation_s_ids:
            cation_s_label = f"{cation_elem}_s"
            if cation_s_label not in atom_types:
                atom_types[cation_s_label] = next_id
                next_id += 1

        if hoh_type_id is not None:
            del atom_types["H"]
            atom_types["Hoh"] = hoh_type_id
        else:
            atom_types["Hoh"] = next_id
            next_id += 1

        # ── Reclassify atoms ──
        for atom in atoms:
            if atom.element == "H":
                atom.element = "Hoh"
                atom.type = atom_types["Hoh"]
                atom.charge = q_H
            elif atom.id in hydroxylated_o_ids:
                atom.element = "Os"
                atom.type = atom_types["Os"]
                atom.charge = q_Os
            elif atom.id in cation_s_ids and cation_s_label is not None:
                atom.element = cation_s_label
                atom.type = atom_types[cation_s_label]
                # charge unchanged (bulk value preserved)

        # ── Charge neutrality verification ──
        total_q = sum(a.charge for a in atoms)
        assert abs(total_q) < 0.01, (
            f"Charge neutrality violated after hydroxyl finalize: {total_q:.6f}e"
        )

        return atoms, atom_types

    def _build_generic_aggregate(self, spec: CrystalSpec) -> CrystalSlab:
        """Build a generic aggregate surface (simplified)."""
        # Use SiO2 as default for generic aggregate
        spec_copy = CrystalSpec(
            material=CrystalMaterial.SIO2,
            surface=spec.surface,
            cell_mode=spec.cell_mode,
            thickness_angstrom=spec.thickness_angstrom,
            xy_size_angstrom=spec.xy_size_angstrom,
            nx=spec.nx,
            ny=spec.ny,
            nz=spec.nz,
            hydroxylated=spec.hydroxylated,
            hydroxyl_density=spec.hydroxyl_density,
            use_matrix_search=getattr(spec, "use_matrix_search", True),
            max_cells_xy=getattr(spec, "max_cells_xy", 200),
            matrix_ortho_tolerance=getattr(spec, "matrix_ortho_tolerance", 1e-8),
        )
        slab = self.build(spec_copy)
        slab.material = CrystalMaterial.AGGREGATE
        return slab

    def create_sio2_slab(
        self,
        thickness: float = 25.0,
        xy_size: float = 50.0,
        hydroxylated: bool = True,
    ) -> CrystalSlab:
        """Convenience method to create SiO2 slab."""
        spec = CrystalSpec(
            material=CrystalMaterial.SIO2,
            thickness_angstrom=thickness,
            xy_size_angstrom=xy_size,
            hydroxylated=hydroxylated,
        )
        return self.build(spec)

    def create_calcite_slab(
        self,
        thickness: float = 25.0,
        xy_size: float = 50.0,
    ) -> CrystalSlab:
        """Convenience method to create CaCO3 slab."""
        spec = CrystalSpec(
            material=CrystalMaterial.CITE,
            thickness_angstrom=thickness,
            xy_size_angstrom=xy_size,
            hydroxylated=False,
        )
        return self.build(spec)

    @staticmethod
    def _resolve_cell_mode(spec: CrystalSpec) -> CrystalCellMode:
        """Resolve cell mode with backward-compatible fallback."""
        raw = getattr(spec, "cell_mode", CrystalCellMode.ORTHOGONALIZED)
        if isinstance(raw, CrystalCellMode):
            return raw
        try:
            return CrystalCellMode(str(raw))
        except ValueError as exc:
            raise ValueError(f"Unknown crystal cell_mode: {raw}") from exc

    def _build_with_replicates(
        self,
        *,
        spec: CrystalSpec,
        unit_cell: dict[str, Any],
        nx: int,
        ny: int,
        nz: int,
        lx: float,
        ly: float,
        lz: float,
        cell_mode: CrystalCellMode,
        transformation_matrix: list[list[int]] | None = None,
        n_cells_xy: int | None = None,
        error_xy_pct: float | None = None,
        matrix_search_used: bool = False,
        matrix_search_fallback_reason: str | None = None,
    ) -> CrystalSlab:
        """Build atoms for a diagonal replication path."""
        a, b, c = unit_cell["a"], unit_cell["b"], unit_cell["c"]
        gamma = math.radians(unit_cell["gamma"])

        atoms = []
        atom_types: dict[str, int] = {}
        atom_id = 1
        charges = self.CHARGES.get(spec.material, {})

        for iz in range(nz):
            for iy in range(ny):
                for ix in range(nx):
                    for elem, fx, fy, fz in unit_cell["atoms"]:
                        fx = fx % 1.0
                        fy = fy % 1.0
                        fz = fz % 1.0
                        x, y = self._fractional_to_xy(ix, iy, fx, fy, a, b, gamma, cell_mode)
                        z = (iz + fz) * c

                        if elem not in atom_types:
                            atom_types[elem] = len(atom_types) + 1

                        atoms.append(
                            Atom(
                                id=atom_id,
                                type=atom_types[elem],
                                x=x,
                                y=y,
                                z=z,
                                element=elem,
                                charge=charges.get(elem, 0.0),
                            )
                        )
                        atom_id += 1

        if spec.hydroxylated:
            atoms, atom_types, hydroxylated_o_ids = self._add_hydroxyl_groups(
                atoms, atom_types, spec, lx, ly, charges
            )
            atoms, atom_types = self._finalize_hydroxyl_types(
                atoms, atom_types, hydroxylated_o_ids, spec.material, lx, ly
            )
            z_max_atom = max(a.z for a in atoms)
            if z_max_atom > lz:
                lz = z_max_atom

        return CrystalSlab(
            atoms=atoms,
            box=(lx, ly, lz),
            material=spec.material,
            surface=spec.surface,
            n_atoms=len(atoms),
            atom_types=atom_types,
            nx=nx,
            ny=ny,
            nz=nz,
            transformation_matrix=transformation_matrix,
            n_cells_xy=n_cells_xy,
            error_xy_pct=error_xy_pct,
            matrix_search_used=matrix_search_used,
            matrix_search_fallback_reason=matrix_search_fallback_reason,
        )

    def _build_with_matrix(
        self,
        *,
        spec: CrystalSpec,
        unit_cell: dict[str, Any],
        result: SupercellResult,
        sin_gamma: float,
    ) -> CrystalSlab:
        """Build atoms from an exact rectangular supercell transformation."""
        c = unit_cell["c"]
        (p, q), (r, s) = result.matrix
        coeff = np.array([[p, r], [q, s]], dtype=float)
        coeff_inv = np.linalg.inv(coeff)
        cell_origins = enumerate_unit_cells(result.matrix)

        lx, ly, lz = result.lx, result.ly, result.lz
        atoms = []
        atom_types: dict[str, int] = {}
        atom_id = 1
        charges = self.CHARGES.get(spec.material, {})

        for iz in range(result.nz):
            for ci, cj in cell_origins:
                for elem, fx, fy, fz in unit_cell["atoms"]:
                    fx = fx % 1.0
                    fy = fy % 1.0
                    fz = fz % 1.0

                    old_frac = np.array([ci + fx, cj + fy], dtype=float)
                    super_frac = coeff_inv @ old_frac
                    super_frac = np.mod(super_frac, 1.0)
                    super_frac[np.isclose(super_frac, 1.0, atol=1e-9)] = 0.0

                    if elem not in atom_types:
                        atom_types[elem] = len(atom_types) + 1

                    atoms.append(
                        Atom(
                            id=atom_id,
                            type=atom_types[elem],
                            x=float(super_frac[0] * lx),
                            y=float(super_frac[1] * ly),
                            z=(iz + fz) * c,
                            element=elem,
                            charge=charges.get(elem, 0.0),
                        )
                    )
                    atom_id += 1

        if spec.hydroxylated:
            atoms, atom_types, hydroxylated_o_ids = self._add_hydroxyl_groups(
                atoms, atom_types, spec, lx, ly, charges
            )
            atoms, atom_types = self._finalize_hydroxyl_types(
                atoms, atom_types, hydroxylated_o_ids, spec.material, lx, ly
            )
            z_max_atom = max(a.z for a in atoms)
            if z_max_atom > lz:
                lz = z_max_atom

        legacy_nx = max(1, round(lx / max(float(unit_cell["a"]), 1e-12)))
        legacy_ny = max(1, round(ly / max(abs(float(unit_cell["b"]) * sin_gamma), 1e-12)))

        return CrystalSlab(
            atoms=atoms,
            box=(lx, ly, lz),
            material=spec.material,
            surface=spec.surface,
            n_atoms=len(atoms),
            atom_types=atom_types,
            nx=legacy_nx,
            ny=legacy_ny,
            nz=result.nz,
            transformation_matrix=[list(result.matrix[0]), list(result.matrix[1])],
            n_cells_xy=result.det,
            error_xy_pct=result.error_xy_pct,
            matrix_search_used=True,
            matrix_search_fallback_reason=None,
        )

    @staticmethod
    def _fractional_to_xy(
        ix: int,
        iy: int,
        fx: float,
        fy: float,
        a: float,
        b: float,
        gamma_rad: float,
        cell_mode: CrystalCellMode,
    ) -> tuple[float, float]:
        """
        Convert fractional XY to Cartesian XY.

        - native_skew: uses full oblique lattice vector with gamma skew
        - orthogonalized: removes in-plane skew to generate rectangular XY box
        """
        if cell_mode == CrystalCellMode.NATIVE_SKEW:
            x = (ix + fx) * a + (iy + fy) * b * math.cos(gamma_rad)
            y = (iy + fy) * b * math.sin(gamma_rad)
            return x, y

        if cell_mode == CrystalCellMode.ORTHOGONALIZED:
            x = (ix + fx) * a
            y = (iy + fy) * b * math.sin(gamma_rad)
            return x, y

        raise ValueError(f"Unsupported crystal cell_mode: {cell_mode}")

    @staticmethod
    def _resolve_replication_and_lattice(
        spec: CrystalSpec,
        a: float,
        b: float,
        c: float,
        sin_gamma: float,
    ) -> tuple[int, int, int, float, float, float, float, float, float]:
        """
        Resolve replication counts without lattice distortion.

        Strategy:
        1. When target sizes are specified, nz/nx/ny are computed from
           target dimensions (thickness_angstrom, xy_size_angstrom).
        2. When target sizes are NOT specified, spec.nx/ny/nz are used directly.
        3. Lattice constants (a, b, c) are never modified — crystal density is preserved exactly.
        4. Box dimensions are exact integer multiples of cell dimensions.
        """
        cell_x = a
        cell_y = b * sin_gamma
        cell_z = c

        if spec.xy_size_angstrom > 0:
            target_xy = float(spec.xy_size_angstrom)
            nx = max(1, round(target_xy / max(cell_x, 1e-9)))
            ny = max(1, round(target_xy / max(cell_y, 1e-9)))
        else:
            nx = max(1, int(spec.nx))
            ny = max(1, int(spec.ny))

        if spec.thickness_angstrom > 0:
            nz = _best_nz(float(spec.thickness_angstrom), cell_z)
        else:
            nz = max(1, int(spec.nz))

        lx = nx * cell_x
        ly = ny * cell_y
        lz = nz * cell_z

        return nx, ny, nz, a, b, c, lx, ly, lz
