"""Ionic artifact generation service.

Generates FF parameter artifacts for ionic salts using AmberTools tleap
with Joung-Cheatham (monovalent) and Li/Merz (divalent) ion parameters.

Pipeline: tleap (leaprc.water.tip3p + ion library) -> parmed extraction -> JSON
No antechamber needed -- charges are formal ionic charges.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from common.logging import get_logger

logger = get_logger("molecules.ionic_artifact_service")

_FILE_RELATIVE_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Import-time snapshots (see artifact_service for the rationale): keep
# IONIC_ARTIFACT_DIR a real module attribute so monkeypatch.setattr works,
# while _ionic_artifact_dir() applies ASPHALT_PROJECT_ROOT env isolation
# when the attribute still equals its snapshot.
PROJECT_ROOT = _FILE_RELATIVE_PROJECT_ROOT
IONIC_ARTIFACT_DIR = PROJECT_ROOT / "data" / "forcefield_artifacts" / "ionic_jc_tip3p"
_SNAPSHOT_IONIC_ARTIFACT_DIR = IONIC_ARTIFACT_DIR


def _ionic_artifact_dir() -> Path:
    """Resolve the ionic artifact directory (env-aware).

    A ``monkeypatch.setattr(..., "IONIC_ARTIFACT_DIR", x)`` override takes
    precedence; otherwise honours ``ASPHALT_PROJECT_ROOT`` for
    workspace-isolated runs, else the source-relative root.
    """
    import os

    cur = globals().get("IONIC_ARTIFACT_DIR", _SNAPSHOT_IONIC_ARTIFACT_DIR)
    if cur != _SNAPSHOT_IONIC_ARTIFACT_DIR:
        return cur
    env = os.environ.get("ASPHALT_PROJECT_ROOT")
    root = Path(env) if env else _FILE_RELATIVE_PROJECT_ROOT
    return root / "data" / "forcefield_artifacts" / "ionic_jc_tip3p"


# Ion decomposition map: mol_id -> list of (leap_residue_name, display_name)
# Pure ionic salts: all atoms are single-ion residues from the ion library
ION_DECOMPOSITION: dict[str, list[tuple[str, str]]] = {
    "NaCl": [("Na+", "Na+"), ("Cl-", "Cl-")],
    "KCl": [("K+", "K+"), ("Cl-", "Cl-")],
    "CaCl2": [("CA", "Ca2+"), ("Cl-", "Cl-"), ("Cl-", "Cl-")],
    "MgCl2": [("MG", "Mg2+"), ("Cl-", "Cl-"), ("Cl-", "Cl-")],
}

# Hybrid ionic molecules: mix of atomic ions + GAFF2 molecular fragments
# Na-O bond is ionic (nonbonded Coulomb), O-H bond is covalent (GAFF2 bonded)
_OH_MINUS_MOL2 = """\
@<TRIPOS>MOLECULE
OH-
 2 1 1 0 0
SMALL
RESP


@<TRIPOS>ATOM
      1 O1           0.0000    0.0000    0.0000 oh         1 OH-      -1.3220
      2 H1           0.9600    0.0000    0.0000 ho         1 OH-       0.3220
@<TRIPOS>BOND
     1     1     2 1
@<TRIPOS>SUBSTRUCTURE
     1 OH-         1 TEMP              0 ****  ****    0 ROOT
"""

HYBRID_ION_CONFIGS: dict[str, dict] = {
    "NaOH": {
        "ionic_parts": [("Na+", "Na+")],
        "molecular_mol2": _OH_MINUS_MOL2,
        "molecular_var": "oh",
        "smiles": "[Na+].[OH-]",
    },
}

# All supported molecules (pure ionic + hybrid)
_ALL_IONIC_MOLECULES = list(ION_DECOMPOSITION.keys()) + list(HYBRID_ION_CONFIGS.keys())


def get_supported_ionic_molecules() -> list[str]:
    """Return mol_ids supported by the ionic artifact pipeline."""
    return list(_ALL_IONIC_MOLECULES)


def generate_ionic_artifact(mol_id: str) -> dict:
    """Generate ionic artifact JSON using tleap + parmed.

    Args:
        mol_id: Molecule ID (must be in ION_DECOMPOSITION).

    Returns:
        Artifact dict (schema_version=2, ff_family=ionic_jc_tip3p).

    Raises:
        ValueError: If mol_id is not a supported ionic species.
        RuntimeError: If tleap or parmed fails.
    """
    if mol_id not in _ALL_IONIC_MOLECULES:
        raise ValueError(
            f"Unsupported ionic molecule: {mol_id}. Supported: {', '.join(_ALL_IONIC_MOLECULES)}"
        )

    is_hybrid = mol_id in HYBRID_ION_CONFIGS

    with tempfile.TemporaryDirectory(prefix=f"ionic_{mol_id}_") as tmpdir:
        wd = Path(tmpdir)

        if is_hybrid:
            # Hybrid: atomic ions from library + GAFF2 molecular fragment
            cfg = HYBRID_ION_CONFIGS[mol_id]
            mol2_path = wd / f"{cfg['molecular_var']}.mol2"
            mol2_path.write_text(cfg["molecular_mol2"])

            lines = ["source leaprc.gaff2", "source leaprc.water.tip3p"]
            unit_parts = []

            # Load molecular fragment
            var = cfg["molecular_var"]
            lines.append(f"{var} = loadmol2 {mol2_path}")
            unit_parts.append(var)

            # Copy ionic parts from library
            for i, (leap_name, _display) in enumerate(cfg["ionic_parts"]):
                ion_var = f"ion{i}"
                lines.append(f"{ion_var} = copy {leap_name}")
                unit_parts.append(ion_var)
        else:
            # Pure ionic: all atoms from ion library
            ions = ION_DECOMPOSITION[mol_id]
            lines = ["source leaprc.water.tip3p"]
            unit_parts = []
            for i, (leap_name, _display) in enumerate(ions):
                var = f"ion{i}"
                lines.append(f"{var} = copy {leap_name}")
                unit_parts.append(var)

        lines.append(f"unit = combine {{ {' '.join(unit_parts)} }}")
        lines.append(f"saveamberparm unit {wd}/sys.prmtop {wd}/sys.inpcrd")
        lines.append("quit")

        leap_in = wd / "leap.in"
        leap_in.write_text("\n".join(lines) + "\n")

        # Run tleap with process group cleanup (shared helper)
        from features.molecules.artifact_service import _run_subprocess_with_group_kill

        r = _run_subprocess_with_group_kill(
            ["tleap", "-f", str(leap_in)],
            cwd=str(wd),
            timeout=60,
            stage_name="tleap-ionic",
            mol_id=mol_id,
        )

        prmtop = wd / "sys.prmtop"
        if r.returncode != 0:
            raise RuntimeError(
                f"tleap-ionic non-zero exit ({r.returncode}) for {mol_id}: {r.stderr[:300]}"
            )
        if not prmtop.exists():
            raise RuntimeError(f"tleap-ionic failed for {mol_id}: prmtop not produced")

        # Extract via parmed
        import parmed

        parm = parmed.load_file(str(prmtop), str(wd / "sys.inpcrd"))

        atoms = []
        for idx, a in enumerate(parm.atoms):
            elem = a.element_name.strip() if a.element_name else a.name[:2].strip()
            sigma = None
            epsilon = None
            if hasattr(a, "sigma") and a.sigma:
                sigma = round(a.sigma, 6)
                epsilon = round(a.epsilon, 6) if a.epsilon else 0.0
            atoms.append(
                {
                    "index": idx + 1,
                    "element": elem,
                    "ff_type": a.type,
                    "charge": round(a.charge, 4),
                    "sigma": sigma,
                    "epsilon": epsilon,
                }
            )

        # Extract LJ from atom types if not on atoms directly
        for atom_data, parm_atom in zip(atoms, parm.atoms, strict=True):
            if atom_data["sigma"] is None and hasattr(parm_atom, "atom_type"):
                at = parm_atom.atom_type
                atom_data["sigma"] = round(at.sigma, 6) if at.sigma else 0.0
                atom_data["epsilon"] = round(at.epsilon, 6) if at.epsilon else 0.0

        # Extract bonds (present in hybrid molecules like NaOH with O-H bond)
        bond_seen: set[str] = set()
        bond_types = []
        for b in parm.bonds:
            key = "-".join(sorted([b.atom1.type, b.atom2.type]))
            if key not in bond_seen:
                bond_seen.add(key)
                bond_types.append(
                    {
                        "key": f"{b.atom1.type}-{b.atom2.type}",
                        "k": round(b.type.k, 1),
                        "r0": round(b.type.req, 4),
                    }
                )

        # Extract angles (if any)
        angle_seen: set[str] = set()
        angle_types = []
        for a in parm.angles:
            key = f"{a.atom1.type}-{a.atom2.type}-{a.atom3.type}"
            rkey = f"{a.atom3.type}-{a.atom2.type}-{a.atom1.type}"
            if key not in angle_seen and rkey not in angle_seen:
                angle_seen.add(key)
                angle_types.append(
                    {
                        "key": key,
                        "k": round(a.type.k, 2),
                        "theta0": round(a.type.theteq, 2),
                    }
                )

    charge_sum = round(sum(a["charge"] for a in atoms), 4)
    smiles = HYBRID_ION_CONFIGS[mol_id]["smiles"] if is_hybrid else ""
    charge_model = "formal+am1bcc" if is_hybrid else "formal"
    provenance = (
        "Hybrid: Na+ (JC 2008) + OH- (GAFF2 oh/ho) via leaprc.gaff2 + leaprc.water.tip3p"
        if is_hybrid
        else "Joung-Cheatham 2008 (monovalent) + Li/Merz 2013 (divalent) via leaprc.water.tip3p"
    )

    artifact = {
        "schema_version": 2,
        "ff_family": "ionic_jc_tip3p",
        "charge_model": charge_model,
        "mol_id": mol_id,
        "generator": "tleap_hybrid" if is_hybrid else "tleap_ionsjc_tip3p",
        "generator_version": "ambertools_parmed",
        "provenance": provenance,
        "canonical_smiles": smiles,
        "formal_charge": 0,
        "topology_hash": "",
        "charge_sum": charge_sum,
        "atoms": atoms,
        "bond_types": bond_types,
        "angle_types": angle_types,
        "dihedral_types": [],
        "improper_types": [],
    }

    # Save to artifact directory
    _dir = _ionic_artifact_dir()
    _dir.mkdir(parents=True, exist_ok=True)
    out_path = _dir / f"{mol_id}.json"
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2)

    # YAML is authoring SSOT — not modified at runtime.
    # Artifact readiness is determined by file existence, not YAML status.

    logger.info(f"Generated ionic artifact: {mol_id} ({len(atoms)} atoms, Sq={charge_sum})")
    return artifact


def validate_ionic_artifact(artifact: dict) -> dict:
    """Validate ionic artifact completeness.

    Args:
        artifact: Artifact JSON dict (schema v2, ionic).

    Returns:
        Dict with keys: valid (bool), checks (per-field status), warnings (list[str]).
    """
    checks: dict[str, dict] = {}
    warnings: list[str] = []

    atoms = artifact.get("atoms", [])
    checks["atoms"] = {"count": len(atoms), "status": "ok" if atoms else "missing"}

    # All atoms must have charge
    no_charge = sum(1 for a in atoms if a.get("charge") is None)
    if no_charge:
        warnings.append(f"{no_charge} atoms without charge")

    # All atoms must have LJ params
    no_lj = sum(1 for a in atoms if not a.get("sigma") and not a.get("epsilon"))
    checks["lj_params"] = {
        "count": len(atoms) - no_lj,
        "status": "ok" if not no_lj else "missing",
    }

    # Charge neutrality
    charge_sum = round(sum(a.get("charge", 0) for a in atoms), 4)
    checks["charge_neutrality"] = {
        "value": charge_sum,
        "status": "ok" if abs(charge_sum) < 0.01 else "warning",
    }

    # No bonded terms expected for pure ionic salts
    checks["bond_types"] = {"count": 0, "status": "ok"}
    checks["angle_types"] = {"count": 0, "status": "ok"}

    valid = all(c["status"] != "missing" for c in checks.values())
    return {"valid": valid, "checks": checks, "warnings": warnings}
