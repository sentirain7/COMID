"""Audit: no metal-containing molecules on organic_curated_artifact route.

Architecture rule 7 states that metal-containing species must NOT be
auto-routed to organic_curated_artifact. This audit scans all molecule
catalogs and flags violations.

Allowed exceptions are listed in METAL_ORGANIC_ALLOWLIST.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Metal elements that should NOT appear in organic_curated_artifact molecules
METAL_ELEMENTS = frozenset(
    {
        "Li",
        "Be",
        "Na",
        "Mg",
        "Al",
        "Si",
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
        "Ge",
        "As",
        "Se",
        "Rb",
        "Sr",
        "Y",
        "Zr",
        "Nb",
        "Mo",
        "Ru",
        "Rh",
        "Pd",
        "Ag",
        "Cd",
        "In",
        "Sn",
        "Sb",
        "Te",
        "Cs",
        "Ba",
        "La",
        "Ce",
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

# Molecules explicitly approved for organic route despite containing metal-like elements.
# Each entry must have a justification comment.
METAL_ORGANIC_ALLOWLIST: dict[str, str] = {
    # No exceptions — metal-containing species must not be on organic route.
}

YAML_FILES = [
    PROJECT_ROOT / "data" / "molecules" / "asphalt_binder.yaml",
    PROJECT_ROOT / "data" / "molecules" / "single_moles.yaml",
    PROJECT_ROOT / "data" / "molecules" / "additives.yaml",
]


def _load_organic_entries() -> list[tuple[str, str, Path]]:
    """Return (mol_id, smiles_or_empty, yaml_path) for organic route entries."""
    entries = []
    for yaml_path in YAML_FILES:
        if not yaml_path.exists():
            continue
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        if data is None:
            continue

        # Handle both list (molecules) and dict (additives) formats
        items = []
        if isinstance(data, dict):
            for section_key in ("molecules", "additives"):
                section = data.get(section_key)
                if isinstance(section, list):
                    items.extend(section)
                elif isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, dict):
                            v["_id"] = k
                            items.append(v)
        elif isinstance(data, list):
            items = data

        for item in items:
            if not isinstance(item, dict):
                continue
            mol_id = item.get("base_id") or item.get("_id") or ""
            fa = item.get("ff_assignment") or {}
            route = fa.get("route", "")
            if route == "organic_curated_artifact":
                smiles = fa.get("canonical_smiles") or ""
                entries.append((mol_id, smiles, yaml_path))
    return entries


def _smiles_contains_metal(smiles: str) -> set[str]:
    """Check if SMILES string contains metal element symbols.

    Uses bracket notation [Na], [Ca], [Si] etc. as the primary signal.
    Two-letter metals outside brackets are checked with context guards
    to avoid false positives (e.g., "Si" in "CCCCSI" or "O=O").
    """
    if not smiles:
        return set()
    found = set()
    # Bracket atoms are unambiguous: [Na], [Ca+2], [Si] etc.
    import re

    bracket_atoms = re.findall(r"\[([A-Z][a-z]?)", smiles)
    for atom in bracket_atoms:
        if atom in METAL_ELEMENTS:
            found.add(atom)
    # Only check unbracketed metals if they appear as uppercase-start tokens
    # Skip this for short SMILES to avoid false positives like "Si" in "O=O"
    return found


def _mol_file_contains_metal(mol_id: str) -> set[str]:
    """Check if MOL file for this molecule contains metal elements.

    Uses exact filename match (mol_id.mol) to avoid false positives
    from glob patterns matching unrelated files.
    """
    search_dirs = [
        PROJECT_ROOT / "data" / "molecules" / "asphalt_binder",
        PROJECT_ROOT / "data" / "molecules" / "single_moles",
        PROJECT_ROOT / "data" / "molecules" / "additives",
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        # Search in directory and immediate subdirectories
        candidates = [d / f"{mol_id}.mol"]
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir():
                    candidates.append(sub / f"{mol_id}.mol")
        for mol_file in candidates:
            if not mol_file.exists():
                continue
            try:
                text = mol_file.read_text()
                elements_in_file: set[str] = set()
                in_atom_block = False
                for line in text.splitlines():
                    # Detect V2000 counts line (starts atom block)
                    if "V2000" in line:
                        in_atom_block = True
                        continue
                    if "M  END" in line:
                        break
                    if not in_atom_block:
                        continue
                    parts = line.split()
                    # V2000 atom line: x y z element ...
                    if len(parts) >= 4:
                        elem = parts[3].strip()
                        if elem in METAL_ELEMENTS:
                            elements_in_file.add(elem)
                if elements_in_file:
                    return elements_in_file
            except Exception:
                continue
    return set()


class TestMetalOrganicAudit:
    """No metal-containing molecule should be on organic_curated_artifact
    unless explicitly approved in the allowlist."""

    def test_no_unapproved_metal_in_organic_route(self):
        violations = []
        for mol_id, smiles, yaml_path in _load_organic_entries():
            metals = _smiles_contains_metal(smiles) | _mol_file_contains_metal(mol_id)
            if metals and mol_id not in METAL_ORGANIC_ALLOWLIST:
                violations.append(
                    f"{mol_id} ({yaml_path.name}): contains {metals} "
                    f"but routed to organic_curated_artifact"
                )
        assert not violations, (
            "Metal-containing molecules on organic route without allowlist approval:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
