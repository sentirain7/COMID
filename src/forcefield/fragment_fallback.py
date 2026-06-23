"""Fragment-based GAFF2 fallback artifact generator.

This module provides an automatic fallback when antechamber fails (bond path
explosion, SQM timeout, etc.) to generate a GAFF2-compatible artifact using
RDKit atom environment analysis and gaff2.dat parameter lookup.

The approach:
1. Parse the MOL file with RDKit.
2. Verify applicability (allowed elements, neutral molecule).
3. Assign GAFF2 atom types based on local atom environments.
4. Assign partial charges from fragment-environment reference values.
5. Look up LJ, bond, and angle parameters from GAFF2 tables.
6. Return a schema v2 artifact dict compatible with
   :mod:`forcefield.organic_curated_artifact`.

Limitations:
- Dihedral/improper parameters are not assigned (empty lists) — these
  require the full antechamber torsion scanner or parmchk2 for accuracy.
- Charges are approximate (fragment-environment AM1-BCC references), not
  per-molecule optimized. Suitable for screening-tier simulations.

References:
    - Wang et al., JCIM 2006, 46, 2030 (GAFF2 atom typing rules)
    - Jakalian et al., J. Comput. Chem. 2002, 23, 1623 (AM1-BCC)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.logging import get_logger

logger = get_logger("forcefield.fragment_fallback")

# ---------------------------------------------------------------------------
# Allowed elements for fragment fallback (common organic CHONS subset)
# ---------------------------------------------------------------------------

_ALLOWED_ELEMENTS: frozenset[str] = frozenset({"C", "H", "O", "N", "S"})

# ---------------------------------------------------------------------------
# GAFF2 LJ parameters: {type: (epsilon kcal/mol, sigma Angstrom)}
# ---------------------------------------------------------------------------

GAFF2_LJ: dict[str, tuple[float, float]] = {
    "ca": (0.098800, 3.3152),
    "ha": (0.016100, 2.6255),
    "c3": (0.107800, 3.3977),
    "hc": (0.020800, 2.6002),
    "c2": (0.098800, 3.3152),
    "c1": (0.098800, 3.3152),
    "c": (0.098800, 3.3152),
    "o": (0.146300, 3.0481),
    "oh": (0.093000, 3.2429),
    "os": (0.072600, 3.1561),
    "ho": (0.004700, 0.5379),
    "n3": (0.085800, 3.3651),
    "nb": (0.094100, 3.3842),
    "na": (0.204200, 3.2058),
    "nh": (0.215000, 3.1900),
    "hn": (0.010000, 1.1065),
    "n": (0.163600, 3.1809),
    "ss": (0.282400, 3.5324),
    "sh": (0.282400, 3.5324),
    "hs": (0.012400, 1.0890),
    "h1": (0.020800, 2.4220),
    "h4": (0.016100, 2.5364),
}

# ---------------------------------------------------------------------------
# GAFF2 bonded parameters: {canonical_key: (k kcal/mol/A^2, r0 Angstrom)}
# ---------------------------------------------------------------------------

GAFF2_BONDS: dict[str, tuple[float, float]] = {
    "ca-ca": (354.2, 1.3986),
    "ca-ha": (360.7, 1.0860),
    "c3-c3": (228.9, 1.5354),
    "c3-hc": (345.2, 1.0962),
    "ca-oh": (348.6, 1.3644),
    "ca-c3": (243.9, 1.5147),
    "ca-nb": (386.5, 1.3392),
    "ca-na": (329.3, 1.3858),
    "ca-ss": (213.5, 1.7847),
    "c3-oh": (285.5, 1.4260),
    "c3-h1": (345.2, 1.0962),
    "c3-os": (285.5, 1.4260),
    "c3-n3": (252.2, 1.4690),
    "c3-ss": (186.0, 1.8360),
    "c3-sh": (186.0, 1.8360),
    "c2-c2": (441.8, 1.3370),
    "c2-ha": (360.7, 1.0860),
    "c2-h4": (360.7, 1.0860),
    "c2-c3": (243.9, 1.5147),
    "c-o": (570.0, 1.2290),
    "c-oh": (348.6, 1.3644),
    "c-os": (348.6, 1.3644),
    "c-c3": (243.9, 1.5147),
    "c-n": (370.9, 1.3790),
    "c-ca": (243.9, 1.5147),
    "ca-nh": (329.3, 1.3858),
    "n-hn": (401.2, 1.0120),
    "n3-hn": (369.0, 1.0170),
    "oh-ho": (369.6, 0.9740),
    "sh-hs": (264.5, 1.3460),
    "na-ca": (329.3, 1.3858),
    "nb-ca": (386.5, 1.3392),
    "na-hn": (401.2, 1.0120),
    "c1-c1": (600.0, 1.2060),
}

# ---------------------------------------------------------------------------
# GAFF2 angle parameters: {canonical_key: (k kcal/mol/rad^2, theta0 degrees)}
# ---------------------------------------------------------------------------

GAFF2_ANGLES: dict[str, tuple[float, float]] = {
    "ca-ca-ca": (66.6, 120.0),
    "ca-ca-ha": (48.2, 120.0),
    "c3-c3-c3": (62.9, 111.51),
    "c3-c3-hc": (46.3, 110.07),
    "hc-c3-hc": (39.2, 108.35),
    "ca-ca-c3": (63.5, 120.77),
    "ca-c3-hc": (46.3, 110.07),
    "ca-ca-oh": (69.8, 119.20),
    "ca-oh-ho": (49.9, 109.47),
    "ca-ca-nb": (69.2, 122.63),
    "ca-nb-ca": (68.6, 117.22),
    "ca-ca-na": (66.6, 120.0),
    "ca-na-ca": (66.6, 120.0),
    "ca-na-hn": (46.8, 126.35),
    "ca-ca-ss": (62.7, 120.0),
    "ca-ss-ca": (62.7, 100.0),
    "ca-ca-nh": (66.6, 120.0),
    "ca-nh-hn": (46.8, 113.0),
    "c3-c3-oh": (67.7, 109.43),
    "c3-oh-ho": (47.1, 108.16),
    "c3-c3-os": (67.7, 109.43),
    "c3-c3-n3": (65.9, 112.13),
    "c3-n3-c3": (62.9, 111.51),
    "c3-n3-hn": (47.1, 109.92),
    "h1-c3-oh": (50.9, 109.88),
    "h1-c3-os": (50.9, 109.88),
    "h1-c3-n3": (49.3, 109.92),
    "o-c-oh": (77.4, 122.88),
    "o-c-os": (77.4, 122.88),
    "o-c-c3": (68.0, 123.11),
    "o-c-n": (75.8, 122.03),
    "o-c-ca": (68.7, 123.44),
    "c-n-hn": (49.2, 118.46),
    "c-n-c3": (63.9, 121.35),
    "c3-c3-ss": (62.7, 108.0),
    "c3-c3-sh": (62.7, 108.0),
    "c3-sh-hs": (42.0, 96.0),
    "c3-ss-c3": (62.7, 100.0),
    "c2-c2-ha": (50.0, 120.0),
    "c2-c2-h4": (50.0, 120.0),
    "c2-c2-c3": (63.5, 123.42),
    "c3-c2-ha": (45.1, 117.0),
    "h1-c3-h1": (39.2, 108.35),
}

# ---------------------------------------------------------------------------
# Fragment-environment reference charges (AM1-BCC literature values)
# ---------------------------------------------------------------------------

_REFERENCE_CHARGES: dict[str, float] = {
    # Aromatic carbon/hydrogen (benzene)
    "ca": -0.130,
    "ha": +0.130,
    # sp3 carbon/hydrogen (ethane)
    "c3": -0.094,
    "hc": +0.031,
    # Carbonyl
    "c": +0.600,
    "o": -0.520,
    # Alkene
    "c2": -0.130,
    "c1": -0.130,
    "h4": +0.130,
    # Hydroxyl (phenol)
    "oh": -0.580,
    "ho": +0.400,
    # Ether
    "os": -0.330,
    # Amine
    "n3": -0.780,
    "hn": +0.340,
    # Amide nitrogen
    "n": -0.420,
    # Aromatic nitrogen
    "nb": -0.680,
    "na": -0.220,
    "nh": -0.780,
    # Sulfur
    "ss": -0.270,
    "sh": -0.310,
    "hs": +0.190,
    # H on heteroatom-adjacent sp3 C
    "h1": +0.060,
}

# ---------------------------------------------------------------------------
# Electron-withdrawing group SMARTS for hydrogen sub-classification
# ---------------------------------------------------------------------------

_EWG_ELEMENTS: frozenset[str] = frozenset({"O", "N", "S", "F", "Cl", "Br"})


# ---------------------------------------------------------------------------
# Atom type classification
# ---------------------------------------------------------------------------


def _classify_atom(atom: Any, mol: Any) -> str:
    """Classify a single RDKit atom into a GAFF2 atom type.

    Args:
        atom: RDKit Atom object.
        mol: RDKit Mol object (parent molecule).

    Returns:
        GAFF2 atom type string (e.g. "ca", "c3", "ha").
    """
    from rdkit.Chem import rdchem

    symbol = atom.GetSymbol()
    is_aromatic = atom.GetIsAromatic()
    hybridization = atom.GetHybridization()
    degree = atom.GetDegree()  # heavy atom neighbors
    total_hs = atom.GetTotalNumHs()

    # --- Carbon ---
    if symbol == "C":
        if is_aromatic:
            return "ca"

        if hybridization == rdchem.HybridizationType.SP3:
            return "c3"

        if hybridization == rdchem.HybridizationType.SP2:
            # Check for carbonyl: C=O (double bond to oxygen)
            for neighbor in atom.GetNeighbors():
                if neighbor.GetSymbol() == "O":
                    bond = mol.GetBondBetweenAtoms(atom.GetIdx(), neighbor.GetIdx())
                    if bond is not None and bond.GetBondTypeAsDouble() == 2.0:
                        return "c"  # carbonyl carbon
            return "c2"  # generic sp2 alkene

        if hybridization == rdchem.HybridizationType.SP:
            return "c1"

        # Fallback: treat as sp3
        return "c3"

    # --- Hydrogen ---
    if symbol == "H":
        neighbors = atom.GetNeighbors()
        if not neighbors:
            return "hc"  # isolated H (shouldn't happen in a valid mol)
        parent = neighbors[0]
        parent_symbol = parent.GetSymbol()

        if parent_symbol == "O":
            return "ho"
        if parent_symbol == "N":
            return "hn"
        if parent_symbol == "S":
            return "hs"

        # Parent is carbon
        if parent.GetIsAromatic():
            return "ha"

        parent_hybridization = parent.GetHybridization()
        if parent_hybridization == rdchem.HybridizationType.SP2:
            return "h4"

        # sp3 carbon: count electron-withdrawing groups attached to parent
        ewg_count = 0
        for nbr in parent.GetNeighbors():
            if nbr.GetIdx() == atom.GetIdx():
                continue
            if nbr.GetSymbol() in _EWG_ELEMENTS:
                ewg_count += 1

        if ewg_count >= 1:
            return "h1"  # H on C with >= 1 EWG neighbor
        return "hc"  # H on plain sp3 C

    # --- Oxygen ---
    if symbol == "O":
        # Check for double bond (carbonyl O: C=O)
        for neighbor in atom.GetNeighbors():
            bond = mol.GetBondBetweenAtoms(atom.GetIdx(), neighbor.GetIdx())
            if bond is not None and bond.GetBondTypeAsDouble() == 2.0:
                return "o"  # C=O oxygen

        # Single-bonded oxygen
        if total_hs > 0:
            return "oh"  # hydroxyl
        return "os"  # ether/ester

    # --- Nitrogen ---
    if symbol == "N":
        if is_aromatic:
            # Aromatic N with 2 connections = pyridine-like (nb)
            # Aromatic N with 3 connections = pyrrole/indole-like (na)
            if degree <= 2:
                return "nb"
            return "na"

        if hybridization == rdchem.HybridizationType.SP3:
            return "n3"  # amine

        if hybridization == rdchem.HybridizationType.SP2:
            # Check for amide: N bonded to C=O
            for neighbor in atom.GetNeighbors():
                if neighbor.GetSymbol() == "C":
                    for nbr2 in neighbor.GetNeighbors():
                        if nbr2.GetSymbol() == "O":
                            bond = mol.GetBondBetweenAtoms(neighbor.GetIdx(), nbr2.GetIdx())
                            if bond is not None and bond.GetBondTypeAsDouble() == 2.0:
                                return "n"  # amide N
            # Non-amide sp2 N with H
            if total_hs > 0:
                return "nh"
            return "n3"  # fallback

        return "n3"

    # --- Sulfur ---
    if symbol == "S":
        if total_hs > 0:
            return "sh"  # thiol
        return "ss"  # thioether

    # Fallback (should not be reached if element check passed)
    logger.warning("Unexpected element '%s' in _classify_atom, defaulting to c3", symbol)
    return "c3"


# ---------------------------------------------------------------------------
# Canonical key helpers
# ---------------------------------------------------------------------------


def _canonical_bond_key(type_a: str, type_b: str) -> str:
    """Return canonical bond key with types in alphabetical order."""
    pair = sorted([type_a, type_b])
    return f"{pair[0]}-{pair[1]}"


def _canonical_angle_key(type_a: str, type_b: str, type_c: str) -> str:
    """Return canonical angle key (middle atom fixed, ends sorted)."""
    ends = sorted([type_a, type_c])
    return f"{ends[0]}-{type_b}-{ends[1]}"


# ---------------------------------------------------------------------------
# Charge normalization
# ---------------------------------------------------------------------------


def _normalize_charges(charges: list[float], target_charge: int) -> list[float]:
    """Normalize charges so they sum to the target formal charge.

    Distributes the residual uniformly across all atoms.

    Args:
        charges: Per-atom charge list.
        target_charge: Desired total charge (typically 0).

    Returns:
        Adjusted charge list.
    """
    if not charges:
        return charges
    total = sum(charges)
    residual = float(target_charge) - total
    correction = residual / len(charges)
    return [q + correction for q in charges]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_fragment_fallback_artifact(
    mol_path: Path,
    mol_id: str,
    formal_charge: int = 0,
) -> dict[str, Any] | None:
    """Generate a GAFF2-compatible artifact via fragment-based typing.

    This function is the fallback when antechamber fails (bond path explosion,
    SQM timeout, etc.). It uses RDKit atom environment analysis to assign
    GAFF2 atom types and reference AM1-BCC charges.

    Args:
        mol_path: Path to the .mol (or .sdf) file.
        mol_id: Molecule identifier for the artifact.
        formal_charge: Expected total formal charge of the molecule.

    Returns:
        Schema v2 artifact dict compatible with
        :func:`forcefield.organic_curated_artifact.parse_artifact_payload`,
        or ``None`` if the molecule does not meet applicability conditions.

    Raises:
        No exceptions are raised; returns None on any failure condition.
    """
    try:
        from rdkit import Chem
    except ImportError:
        logger.error("RDKit is not available; cannot generate fragment fallback artifact")
        return None

    # --- Step 1: Parse the MOL file ---
    mol = Chem.MolFromMolFile(str(mol_path), removeHs=False, sanitize=True)
    if mol is None:
        logger.warning(
            "RDKit cannot parse MOL file: %s — fragment fallback not applicable",
            mol_path,
        )
        return None

    # --- Step 2: Applicability checks ---

    # 2a. Element check
    elements_in_mol: set[str] = set()
    for atom in mol.GetAtoms():
        elements_in_mol.add(atom.GetSymbol())
    if not elements_in_mol.issubset(_ALLOWED_ELEMENTS):
        disallowed = elements_in_mol - _ALLOWED_ELEMENTS
        logger.info(
            "Molecule '%s' contains disallowed elements %s — fragment fallback not applicable",
            mol_id,
            sorted(disallowed),
        )
        return None

    # 2b. Per-atom formal charge check (must all be 0)
    for atom in mol.GetAtoms():
        if atom.GetFormalCharge() != 0:
            logger.info(
                "Molecule '%s' has non-zero per-atom formal charge on atom %d "
                "— fragment fallback not applicable (non-ionic molecules only)",
                mol_id,
                atom.GetIdx(),
            )
            return None

    # 2c. Total formal charge check
    mol_total_charge = Chem.GetFormalCharge(mol)
    if mol_total_charge != formal_charge:
        logger.info(
            "Molecule '%s' total formal charge %d does not match expected %d "
            "— fragment fallback not applicable",
            mol_id,
            mol_total_charge,
            formal_charge,
        )
        return None

    # --- Step 3: Assign GAFF2 atom types ---
    n_atoms = mol.GetNumAtoms()
    atom_types: list[str] = []
    for atom in mol.GetAtoms():
        atype = _classify_atom(atom, mol)
        atom_types.append(atype)

    logger.debug(
        "Fragment fallback typing for '%s': %d atoms, types=%s",
        mol_id,
        n_atoms,
        atom_types,
    )

    # --- Step 4: Assign charges ---
    charges: list[float] = []
    for atype in atom_types:
        ref_charge = _REFERENCE_CHARGES.get(atype, 0.0)
        charges.append(ref_charge)

    charges = _normalize_charges(charges, formal_charge)

    # --- Step 5: Build atoms list ---
    atoms_list: list[dict[str, Any]] = []
    for i, atom in enumerate(mol.GetAtoms()):
        atype = atom_types[i]
        lj = GAFF2_LJ.get(atype)
        epsilon = lj[0] if lj else 0.0
        sigma = lj[1] if lj else 0.0
        atoms_list.append(
            {
                "index": i + 1,  # 1-based
                "element": atom.GetSymbol(),
                "ff_type": atype,
                "charge": round(charges[i], 6),
                "epsilon": epsilon,
                "sigma": sigma,
            }
        )

    # --- Step 6: Extract bond types ---
    bond_type_set: dict[str, dict[str, Any]] = {}
    for bond in mol.GetBonds():
        idx_a = bond.GetBeginAtomIdx()
        idx_b = bond.GetEndAtomIdx()
        type_a = atom_types[idx_a]
        type_b = atom_types[idx_b]
        key = _canonical_bond_key(type_a, type_b)
        if key not in bond_type_set:
            params = GAFF2_BONDS.get(key)
            if params is not None:
                bond_type_set[key] = {"key": key, "k": params[0], "r0": params[1]}
            else:
                logger.debug(
                    "No GAFF2 bond parameter for key '%s' in mol '%s' — skipping",
                    key,
                    mol_id,
                )

    # Fail-closed: if molecule has bonds but no recognized bond types, refuse
    if mol.GetNumBonds() > 0 and not bond_type_set:
        logger.warning("Fragment fallback: no bond types recognized for %s — refusing", mol_id)
        return None

    # --- Step 7: Extract angle types ---
    angle_type_set: dict[str, dict[str, Any]] = {}
    for atom in mol.GetAtoms():
        # Central atom of an angle
        center_idx = atom.GetIdx()
        center_type = atom_types[center_idx]
        neighbors = atom.GetNeighbors()
        if len(neighbors) < 2:
            continue
        # Generate all pairs of neighbors
        for i_n in range(len(neighbors)):
            for j_n in range(i_n + 1, len(neighbors)):
                type_a = atom_types[neighbors[i_n].GetIdx()]
                type_c = atom_types[neighbors[j_n].GetIdx()]
                key = _canonical_angle_key(type_a, center_type, type_c)
                if key not in angle_type_set:
                    params = GAFF2_ANGLES.get(key)
                    if params is not None:
                        angle_type_set[key] = {
                            "key": key,
                            "k": params[0],
                            "theta0": params[1],
                        }
                    else:
                        logger.debug(
                            "No GAFF2 angle parameter for key '%s' in mol '%s' — skipping",
                            key,
                            mol_id,
                        )

    # --- Step 8: Compute canonical SMILES for provenance ---
    canonical_smiles = ""
    try:
        # Remove explicit H for canonical SMILES
        mol_no_h = Chem.RemoveHs(mol)
        canonical_smiles = Chem.MolToSmiles(mol_no_h) or ""
    except Exception:
        pass  # Non-critical; provenance only

    # --- Step 9: Build the schema v2 artifact dict ---
    charge_sum = sum(charges)

    artifact: dict[str, Any] = {
        "schema_version": 2,
        "ff_family": "organic_gaff2",
        "mol_id": mol_id,
        "generator": "fragment_fallback_gaff2",
        "generator_version": "1.0",
        "charge_model": "fragment_env_am1bcc",
        "provenance": (
            f"Auto-generated fragment-based GAFF2 fallback from {mol_path.name}. "
            "Atom types assigned by RDKit environment analysis; charges from "
            "AM1-BCC fragment reference values (normalized)."
        ),
        "formal_charge": formal_charge,
        "canonical_smiles": canonical_smiles,
        "topology_hash": "",
        "charge_sum": round(charge_sum, 6),
        "atoms": atoms_list,
        "bond_types": list(bond_type_set.values()),
        "angle_types": list(angle_type_set.values()),
        "dihedral_types": [],
        "improper_types": [],
        "improper_instances": [],
    }

    logger.info(
        "Generated fragment fallback artifact for '%s': %d atoms, %d bond types, "
        "%d angle types, charge_sum=%.6f",
        mol_id,
        n_atoms,
        len(bond_type_set),
        len(angle_type_set),
        charge_sum,
    )

    return artifact


__all__ = [
    "generate_fragment_fallback_artifact",
    "GAFF2_LJ",
    "GAFF2_BONDS",
    "GAFF2_ANGLES",
]
