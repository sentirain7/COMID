"""RDKit-based preflight diagnostics for the admin FF Parameters page.

Phase 5 (v00.99.41) — Surfaces "is this entry plausibly generatable?"
verdicts before the admin operator pays for an antechamber+sqm round
trip. Findings are advisory; the typing router and artifact_service
remain the authority on actual blocking.

Phase 6 (v01.02.11) — Adds ionic character classification for SDBS-like
hybrid ionic molecules, H2SO4-like polar neutrals, and pure ionic salts.

Returns a structured dict (JSON-friendly so it serialises straight into
the admin status sidecar). When RDKit is unavailable the function falls
back to ``preflight.mode == "degraded"`` and returns only what can be
inferred from catalog metadata.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

# Metallic / ionic symbols that the AmberTools GAFF2 pipeline cannot
# parameterize at all (alkali, alkaline earth, transition metals, post-
# transition metals up to Bi). Defensive: missing entries just downgrade
# the verdict, never elevate it. Count is intentionally complete for the
# elements GAFF2 rejects — the set length must equal len(_METAL_ELEMENTS).
_METAL_ELEMENTS: frozenset[str] = frozenset(
    {
        "Li",
        "Be",
        "Na",
        "Mg",
        "K",
        "Ca",
        "Sc",
        "Ti",
        "V",
        "Cr",
        "Mn",
        "Fe",
        "Co",
        "Ni",
        "Cu",
        "Zn",
        "Ga",
        "Rb",
        "Sr",
        "Y",
        "Zr",
        "Nb",
        "Mo",
        "Tc",
        "Ru",
        "Rh",
        "Pd",
        "Ag",
        "Cd",
        "In",
        "Sn",
        "Cs",
        "Ba",
        "Hf",
        "Ta",
        "W",
        "Re",
        "Os",
        "Ir",
        "Pt",
        "Au",
        "Hg",
        "Tl",
        "Pb",
        "Bi",
    }
)
assert len(_METAL_ELEMENTS) == 45  # invariant: keep comment & set in sync


# ---------------------------------------------------------------------------
# Ionic Classification (Phase 6)
# ---------------------------------------------------------------------------


class IonicClass(StrEnum):
    """Ionic character classification of molecules.

    Used by the typing router and ionic_artifact_service to determine
    the appropriate parameterization route.
    """

    PURE_IONIC = "pure_ionic"  # All atoms are single ions (NaCl, CaCl2)
    HYBRID_IONIC = "hybrid_ionic"  # Metal cation + organic anion (SDBS, NaOH)
    CHARGED_ORGANIC = "charged_organic"  # Organic with formal charge (RSO3-)
    NEUTRAL_POLAR = "neutral_polar"  # Neutral polar molecule (H2SO4, H3PO4)
    ORGANIC = "organic"  # Standard organic molecule


# SMARTS patterns for detecting polar functional groups in neutral molecules.
# Used to distinguish NEUTRAL_POLAR from plain ORGANIC.
_POLAR_SMARTS: dict[str, str] = {
    "sulfonic_acid": "[SX4](=O)(=O)[OH]",
    "sulfonate": "[SX4](=O)(=O)[O-]",
    "sulfuric_acid": "[SX4](=O)(=O)([OH])[OH]",
    "phosphoric_acid": "[PX4](=O)([OH])([OH])[OH]",
    "phosphate": "[PX4](=O)([O-])([O-])[O-]",
    "carboxylic_acid": "[CX3](=O)[OH]",
    "nitro": "[NX3+](=O)[O-]",
    "nitric_acid": "[NX3+](=O)([O-])[OH]",
}


def _try_import_rdkit():
    try:
        from rdkit import Chem  # type: ignore[import-not-found]

        return Chem
    except Exception:  # pragma: no cover - environment dependent
        return None


def run_rdkit_preflight(
    *,
    mol_id: str,
    structure_file: Path | None,
    smiles: str | None,
    formal_charge: int = 0,
    is_passthrough: bool = False,
) -> dict[str, Any]:
    """Run preflight checks for an organic GAFF2 candidate.

    Args:
        mol_id: Diagnostic identifier (echoed back).
        structure_file: Path to the MOL/MOL2 (may be None).
        smiles: Canonical SMILES (may be None).
        formal_charge: Net formal charge from the catalog.
        is_passthrough: Whether the entry is parameterized via the
            organic_gaff2_passthrough mode (which has no AM1-BCC
            executor).

    Returns:
        A JSON-friendly dict with keys::

            mode: "rdkit" | "degraded"
            verdict: "ok" | "warning" | "manual_review"
            findings: list[dict]   # {kind, severity, detail}
            mol_id, structure_file, smiles, formal_charge

        ``verdict == "manual_review"`` indicates that AmberTools should
        not be invoked. ``warning`` means proceed with caution; ``ok``
        means no obvious issues were found.
    """
    findings: list[dict[str, Any]] = []
    structure_path = Path(structure_file) if structure_file else None

    if is_passthrough:
        findings.append(
            {
                "kind": "passthrough",
                "severity": "manual_review",
                "detail": (
                    "parameterization.mode=organic_gaff2_passthrough — no "
                    "AM1-BCC executor available."
                ),
            }
        )

    if structure_path is None or not structure_path.exists():
        findings.append(
            {
                "kind": "structure_missing",
                "severity": "manual_review",
                "detail": f"Structure file not found: {structure_path}",
            }
        )

    Chem = _try_import_rdkit()
    if Chem is None:
        # Degraded — only what catalog metadata + filesystem can tell us.
        verdict = _aggregate_verdict(findings)
        return {
            "mode": "degraded",
            "verdict": verdict,
            "findings": findings,
            "mol_id": mol_id,
            "structure_file": str(structure_path) if structure_path else None,
            "smiles": smiles,
            "formal_charge": formal_charge,
        }

    mol = None
    parse_source = ""
    if structure_path is not None and structure_path.exists():
        suffix = structure_path.suffix.lower()
        try:
            if suffix == ".mol":
                mol = Chem.MolFromMolFile(str(structure_path), removeHs=False)
                parse_source = "mol"
            elif suffix == ".mol2":
                mol = Chem.MolFromMol2File(str(structure_path), removeHs=False)
                parse_source = "mol2"
        except Exception as exc:  # pragma: no cover - rdkit raises rarely
            findings.append(
                {
                    "kind": "rdkit_parse_exception",
                    "severity": "manual_review",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )

    if mol is None and smiles:
        try:
            mol = Chem.MolFromSmiles(smiles)
            parse_source = parse_source or "smiles"
        except Exception as exc:  # pragma: no cover
            findings.append(
                {
                    "kind": "rdkit_parse_exception",
                    "severity": "manual_review",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )

    if mol is None:
        findings.append(
            {
                "kind": "rdkit_parse_failed",
                "severity": "manual_review",
                "detail": (
                    "RDKit could not parse structure_file or smiles — "
                    "the molecule cannot be sanity-checked automatically."
                ),
            }
        )
        verdict = _aggregate_verdict(findings)
        return {
            "mode": "rdkit",
            "verdict": verdict,
            "findings": findings,
            "mol_id": mol_id,
            "structure_file": str(structure_path) if structure_path else None,
            "smiles": smiles,
            "formal_charge": formal_charge,
        }

    # ── Sanitize / valence ----------------------------------------------------
    try:
        Chem.SanitizeMol(mol)
    except Exception as exc:
        findings.append(
            {
                "kind": "sanitize_failed",
                "severity": "manual_review",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    # ── Element / charge inspection ------------------------------------------
    metals_found: set[str] = set()
    radical_atoms = 0
    formal_charge_sum = 0
    n_electrons = 0
    for atom in mol.GetAtoms():
        sym = atom.GetSymbol()
        if sym in _METAL_ELEMENTS:
            metals_found.add(sym)
        formal_charge_sum += atom.GetFormalCharge()
        radical_atoms += atom.GetNumRadicalElectrons()
        n_electrons += atom.GetAtomicNum()

    if metals_found:
        findings.append(
            {
                "kind": "metal_or_ionic_element",
                "severity": "manual_review",
                "detail": f"Metal/ionic elements present: {sorted(metals_found)}",
            }
        )

    if radical_atoms:
        findings.append(
            {
                "kind": "radical_or_odd_electron",
                "severity": "manual_review",
                "detail": (
                    f"{radical_atoms} unpaired electrons detected — AM1-BCC "
                    "does not converge reliably for radical species."
                ),
            }
        )

    if formal_charge_sum != int(formal_charge):
        findings.append(
            {
                "kind": "formal_charge_mismatch",
                "severity": "warning",
                "detail": (
                    f"Sum of per-atom formal charges ({formal_charge_sum}) "
                    f"differs from declared formal_charge ({formal_charge})."
                ),
            }
        )

    # Odd-electron heuristic (independent of explicit radicals): for a
    # neutral molecule the total electron count must be even.
    declared_total_electrons = n_electrons - int(formal_charge)
    if declared_total_electrons % 2 != 0:
        findings.append(
            {
                "kind": "odd_electron_count",
                "severity": "manual_review",
                "detail": (
                    f"Total electrons ({declared_total_electrons}) is odd — "
                    "AM1-BCC will not converge."
                ),
            }
        )

    # Ionic classification (Phase 6)
    ionic_classification = classify_ionic_character(mol)

    verdict = _aggregate_verdict(findings)
    return {
        "mode": "rdkit",
        "verdict": verdict,
        "findings": findings,
        "mol_id": mol_id,
        "structure_file": str(structure_path) if structure_path else None,
        "smiles": smiles,
        "formal_charge": formal_charge,
        "parse_source": parse_source,
        "ionic_classification": ionic_classification,
    }


def classify_ionic_character(mol: Any) -> dict[str, Any]:
    """Classify a molecule's ionic character using RDKit.

    Determines whether a molecule is:
    - PURE_IONIC: All atoms are single ions (NaCl, CaCl2)
    - HYBRID_IONIC: Metal cation + organic anion (SDBS, NaOH)
    - CHARGED_ORGANIC: Organic with formal charge (RSO3- alone)
    - NEUTRAL_POLAR: Neutral with polar functional groups (H2SO4)
    - ORGANIC: Standard organic molecule

    Args:
        mol: RDKit Mol object.

    Returns:
        Classification dict with keys:
            mol_class: IonicClass value
            metal_ions: List of detected metal ion elements
            organic_fragment_smiles: SMILES of organic part (if hybrid)
            organic_fragment_charge: Formal charge of organic part
            polar_groups: List of detected polar functional groups
            separation_confidence: Confidence in metal/organic separation
            recommended_route: Suggested FF route
            recommended_generator: Suggested generator
    """
    Chem = _try_import_rdkit()
    if Chem is None:
        return {
            "mol_class": IonicClass.ORGANIC,
            "metal_ions": [],
            "organic_fragment_smiles": None,
            "organic_fragment_charge": 0,
            "polar_groups": [],
            "separation_confidence": 0.0,
            "recommended_route": "organic_curated_artifact",
            "recommended_generator": "antechamber_gaff2",
            "error": "RDKit unavailable",
        }

    atoms = [a.GetSymbol() for a in mol.GetAtoms()]
    metal_atoms = [a for a in atoms if a in _METAL_ELEMENTS]

    if metal_atoms:
        # Molecule contains metal atoms — check for pure vs hybrid ionic
        try:
            frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
        except Exception:
            frags = [mol]  # Fallback: treat as single fragment

        single_atom_frags = [f for f in frags if f.GetNumAtoms() == 1]
        organic_frags = [f for f in frags if f.GetNumAtoms() > 1]

        if len(organic_frags) == 0:
            # All fragments are single atoms — pure ionic salt
            return {
                "mol_class": IonicClass.PURE_IONIC,
                "metal_ions": sorted(set(metal_atoms)),
                "organic_fragment_smiles": None,
                "organic_fragment_charge": 0,
                "polar_groups": [],
                "separation_confidence": 1.0,
                "recommended_route": "ionic_profile",
                "recommended_generator": "tleap_ionsjc_tip3p",
            }
        else:
            # Mixed: metal ions + organic fragment(s) — hybrid ionic
            org_charge = 0
            org_smiles = None
            try:
                for f in organic_frags:
                    org_charge += Chem.GetFormalCharge(f)
                if organic_frags:
                    org_smiles = Chem.MolToSmiles(organic_frags[0])
            except Exception:
                pass  # SMILES conversion may fail

            # Confidence based on clean separation
            confidence = (
                0.95 if len(frags) == (len(single_atom_frags) + len(organic_frags)) else 0.7
            )

            return {
                "mol_class": IonicClass.HYBRID_IONIC,
                "metal_ions": sorted(set(metal_atoms)),
                "organic_fragment_smiles": org_smiles,
                "organic_fragment_charge": org_charge,
                "polar_groups": [],
                "separation_confidence": confidence,
                "recommended_route": "ionic_profile",
                "recommended_generator": "tleap_hybrid",
            }
    else:
        # No metal atoms — check for charged organic or neutral polar
        try:
            formal_charge = Chem.GetFormalCharge(mol)
        except Exception:
            formal_charge = 0

        if formal_charge != 0:
            # Charged organic molecule (standalone organic ion)
            return {
                "mol_class": IonicClass.CHARGED_ORGANIC,
                "metal_ions": [],
                "organic_fragment_smiles": None,
                "organic_fragment_charge": formal_charge,
                "polar_groups": [],
                "separation_confidence": 1.0,
                "recommended_route": "organic_curated_artifact",
                "recommended_generator": "antechamber_gaff2",
            }

        # Check for polar functional groups using SMARTS
        polar_groups: list[str] = []
        for name, smarts in _POLAR_SMARTS.items():
            try:
                pattern = Chem.MolFromSmarts(smarts)
                if pattern and mol.HasSubstructMatch(pattern):
                    polar_groups.append(name)
            except Exception:
                pass

        if polar_groups:
            return {
                "mol_class": IonicClass.NEUTRAL_POLAR,
                "metal_ions": [],
                "organic_fragment_smiles": None,
                "organic_fragment_charge": 0,
                "polar_groups": polar_groups,
                "separation_confidence": 1.0,
                "recommended_route": "organic_curated_artifact",
                "recommended_generator": "antechamber_gaff2",
            }

        # Standard organic molecule
        return {
            "mol_class": IonicClass.ORGANIC,
            "metal_ions": [],
            "organic_fragment_smiles": None,
            "organic_fragment_charge": 0,
            "polar_groups": [],
            "separation_confidence": 1.0,
            "recommended_route": "organic_curated_artifact",
            "recommended_generator": "antechamber_gaff2",
        }


def _aggregate_verdict(findings: list[dict[str, Any]]) -> str:
    """Reduce per-finding severities into the top-level verdict."""
    severities = {f.get("severity") for f in findings}
    if "manual_review" in severities:
        return "manual_review"
    if "warning" in severities:
        return "warning"
    return "ok"
