"""Validate additive MOL files against force-field element support."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_atomic_weights() -> dict[str, float]:
    try:
        from common.constants import ATOMIC_WEIGHTS

        return ATOMIC_WEIGHTS
    except Exception:
        try:
            from src.common.constants import ATOMIC_WEIGHTS

            return ATOMIC_WEIGHTS
        except Exception:
            module_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
            spec = importlib.util.spec_from_file_location("_standalone_constants", module_path)
            if spec is None or spec.loader is None:
                raise
            module = importlib.util.module_from_spec(spec)
            sys.modules.setdefault("_standalone_constants", module)
            spec.loader.exec_module(module)
            return module.ATOMIC_WEIGHTS


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_uff_element_fallbacks() -> dict[str, dict[str, Any]]:
    module_path = _project_root() / "src" / "forcefield" / "uff_element_fallback.py"
    spec = importlib.util.spec_from_file_location("_standalone_uff_fallback", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load UFF fallback module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_standalone_uff_fallback", module)
    spec.loader.exec_module(module)
    return dict(module.UFF_ELEMENT_FALLBACKS)


ATOMIC_WEIGHTS = _load_atomic_weights()
UFF_ELEMENT_FALLBACKS = _load_uff_element_fallbacks()


def _read_mol_atom_elements(mol_path: Path) -> list[str]:
    """Parse atom elements from MDL MOL V2000 or V3000 file."""
    lines = mol_path.read_text(errors="ignore").splitlines()
    if len(lines) < 4:
        raise ValueError(f"Invalid MOL file: {mol_path}")

    counts_line = lines[3]

    # Check for V3000 format
    if "V3000" in counts_line:
        return _read_mol_v3000_elements(lines, mol_path)

    # Parse V2000 format
    try:
        atom_count = int(counts_line[:3].strip())
    except Exception as exc:
        raise ValueError(f"Invalid MOL counts line: {mol_path}") from exc

    if len(lines) < 4 + atom_count:
        raise ValueError(f"Truncated MOL atom block: {mol_path}")

    elements: list[str] = []
    for line in lines[4 : 4 + atom_count]:
        symbol = line[31:34].strip() if len(line) >= 34 else ""
        if not symbol:
            parts = line.split()
            symbol = parts[3].strip() if len(parts) >= 4 else ""
        if not symbol:
            raise ValueError(f"Failed to parse atom element in {mol_path}")
        elements.append(symbol)
    return elements


def _read_mol_v3000_elements(lines: list[str], mol_path: Path) -> list[str]:
    """Parse atom elements from V3000 format MOL file."""
    elements: list[str] = []
    in_atom_block = False

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("M  V30 BEGIN ATOM"):
            in_atom_block = True
            continue
        if line.startswith("M  V30 END ATOM"):
            in_atom_block = False
            continue

        if not in_atom_block:
            continue
        if not line.startswith("M  V30 "):
            continue

        # V3000 atom format: M  V30 idx element x y z aamap [props...]
        payload = line[len("M  V30 ") :].strip()
        parts = payload.split()
        if len(parts) < 2:
            continue

        # parts[0] = index, parts[1] = element
        element = parts[1]
        elements.append(element)

    if not elements:
        raise ValueError(f"No atoms found in V3000 MOL file: {mol_path}")

    return elements


def _try_rdkit_metadata(mol_path: Path) -> dict[str, Any]:
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors
    except ImportError:
        return {}

    mol = Chem.MolFromMolFile(str(mol_path), removeHs=False)
    if mol is None:
        return {}

    return {
        "atom_count": int(mol.GetNumAtoms()),
        "molecular_weight": float(Descriptors.MolWt(mol)),
        "smiles": Chem.MolToSmiles(mol),
        "elements": sorted({atom.GetSymbol() for atom in mol.GetAtoms()}),
    }


def validate_additive_mol(mol_path: Path, *, ff_name: str = "bulk_ff_gaff2") -> dict[str, Any]:
    """Return additive structure metadata and missing force-field elements."""
    mol_path = Path(mol_path)
    atom_elements = _read_mol_atom_elements(mol_path)
    fallback_result = {
        "atom_count": len(atom_elements),
        "molecular_weight": round(
            sum(ATOMIC_WEIGHTS.get(element, 0.0) for element in atom_elements), 6
        ),
        "smiles": None,
        "elements": sorted(set(atom_elements)),
    }
    result = {**fallback_result, **_try_rdkit_metadata(mol_path)}

    registry_path = _project_root() / "data" / "forcefields" / "registry.yaml"
    registry = yaml.safe_load(registry_path.read_text())
    forcefields = dict((registry or {}).get("forcefields") or {})
    ff_data = forcefields.get(ff_name) or forcefields.get((registry or {}).get("default"))
    if not ff_data:
        raise ValueError(f"Force field not available: {ff_name}")

    # Fail-closed policy (v00.99.29): only explicit atom_types and
    # element_fallbacks are considered supported. UFF implicit fallback
    # via element_fallback_source is no longer honored.
    supported = set((ff_data.get("atom_types") or {}).keys())
    supported.update((ff_data.get("element_fallbacks") or {}).keys())
    # Note: element_fallback_source: uff is no longer checked.
    # All LJ params must be explicit in the artifact or profile.

    result["missing_ff_params"] = [
        element for element in result["elements"] if element not in supported
    ]
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mol_path", type=Path)
    parser.add_argument("--ff", dest="ff_name", default="bulk_ff_gaff2")
    args = parser.parse_args(argv)

    result = validate_additive_mol(args.mol_path, ff_name=args.ff_name)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
