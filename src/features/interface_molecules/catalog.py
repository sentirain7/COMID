"""Interface molecule catalog lookup and cache logic.

Pure functions for loading molecule info from YAML SSOT, computing molecule
sizes, extracting elements, and probing generation support.
"""

from __future__ import annotations

import math

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("features.interface_molecules.catalog")

# =============================================================================
# Interface Molecule Category Definitions (loaded from SSOT YAML)
# =============================================================================

CATEGORY_LABELS = {
    "deicing": "Deicing Agents",
    "atmospheric": "Atmospheric / Aging",
    "fuel": "Fuel Spills",
    "organic_acid": "Organic Acids",
    "solvent": "Solvents",
    "aging": "Aging / Corrosive",
}

# Cache for molecule info loaded from YAML
_MOLECULE_INFO_CACHE: dict[str, dict] | None = None


def _load_molecule_info_from_yaml() -> dict[str, dict]:
    """Load interface molecule info from single_moles.yaml SSOT."""
    global _MOLECULE_INFO_CACHE
    if _MOLECULE_INFO_CACHE is not None:
        return _MOLECULE_INFO_CACHE

    import yaml

    yaml_path = get_project_root() / "data" / "molecules" / "single_moles.yaml"
    if not yaml_path.exists():
        _MOLECULE_INFO_CACHE = {}
        return _MOLECULE_INFO_CACHE

    with yaml_path.open() as f:
        data = yaml.safe_load(f) or {}

    molecules = data.get("molecules", [])
    result = {}

    for mol in molecules:
        base_id = mol.get("base_id", "")
        if not base_id:
            continue

        # Extract elements from MOL file or estimate from name
        elements = _extract_elements_from_mol(base_id)

        result[base_id] = {
            "category": mol.get("category", "other"),
            "name": mol.get("name", base_id),
            "formula": mol.get("paper_name", base_id),
            "atom_count": mol.get("atom_count", 0),
            "molecular_weight": mol.get("molecular_weight", 0.0),
            "elements": elements,
            "recommended_density": mol.get("recommended_density"),
        }

    _MOLECULE_INFO_CACHE = result
    return _MOLECULE_INFO_CACHE


def _extract_elements_from_mol(mol_id: str) -> list[str]:
    """Extract unique elements from MOL file."""
    mol_path = get_project_root() / "data" / "molecules" / "single_moles" / f"{mol_id}.mol"
    if not mol_path.exists():
        return []

    elements = set()
    try:
        with mol_path.open() as f:
            lines = f.readlines()

        if len(lines) < 4:
            return []

        counts_line = lines[3].strip().split()
        if len(counts_line) < 2:
            return []

        n_atoms = int(counts_line[0])
        for i in range(4, min(4 + n_atoms, len(lines))):
            parts = lines[i].split()
            if len(parts) >= 4:
                elem = parts[3]
                elements.add(elem)
    except Exception:
        return []

    return sorted(elements)


def _compute_mol_size(mol_id: str) -> tuple[tuple[float, float, float], float] | None:
    """Compute bounding box dimensions and max radial extent of a molecule.

    Args:
        mol_id: Molecule identifier (matches filename in single_moles/).

    Returns:
        Tuple of ((sx, sy, sz), max_radius) or None if MOL file missing/unparseable.
    """
    from builder.mol_parser import parse_mol_topology

    mol_path = get_project_root() / "data" / "molecules" / "single_moles" / f"{mol_id}.mol"
    if not mol_path.exists():
        return None
    topo = parse_mol_topology(mol_path, mol_id)
    if topo is None or not topo.atoms:
        return None
    coords = [(a.x, a.y, a.z) for a in topo.atoms]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    sx = max(xs) - min(xs)
    sy = max(ys) - min(ys)
    sz = max(zs) - min(zs)
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    cz = sum(zs) / len(zs)
    max_r = max(math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) for x, y, z in coords)
    return (round(sx, 2), round(sy, 2), round(sz, 2)), round(max_r, 2)


def get_interface_molecule_info() -> dict[str, dict]:
    """Get interface molecule info dictionary (cached)."""
    return _load_molecule_info_from_yaml()


def clear_molecule_info_cache() -> None:
    """Clear molecule info cache (for testing/reload)."""
    global _MOLECULE_INFO_CACHE
    _MOLECULE_INFO_CACHE = None


# =============================================================================
# Generation Support Cache (lazy, settings-fingerprint-aware)
# =============================================================================

_GENERATION_SUPPORT_CACHE: dict[str, tuple[bool, str | None]] | None = None
_GENERATION_SUPPORT_FINGERPRINT: str | None = None


def _settings_fingerprint() -> str:
    """Compute a short hash of typing/charge settings for cache invalidation."""
    import hashlib

    from config.settings import get_settings

    settings = get_settings().typing_charge
    raw = (
        f"{settings.enabled}:{settings.charge_model_primary}:"
        f"{settings.charge_model_fallback}:{settings.strict_param_coverage}:"
        f"{settings.total_charge_tolerance}"
    )
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def _get_generation_support() -> dict[str, tuple[bool, str | None]]:
    """Probe generation support for all interface molecules (lazy cached).

    Wave 2: queries the MoleculeDB for each molecule's ff_assignment SSOT
    record and threads it through the support probe so blocked / ionic /
    inorganic species are reported as unsupported here too. Without this,
    the interface molecule cell UI would happily list NaCl as "supported"
    even though the build path now blocks it.
    """
    global _GENERATION_SUPPORT_CACHE, _GENERATION_SUPPORT_FINGERPRINT

    fp = _settings_fingerprint()
    if _GENERATION_SUPPORT_CACHE is not None and _GENERATION_SUPPORT_FINGERPRINT == fp:
        return _GENERATION_SUPPORT_CACHE

    from api.deps import get_molecule_db
    from builder.topology_helpers import probe_single_component_generation_support

    db = get_molecule_db()
    cache: dict[str, tuple[bool, str | None]] = {}
    for mol_id in get_interface_molecule_info():
        mol_path = get_project_root() / "data" / "molecules" / "single_moles" / f"{mol_id}.mol"
        if not mol_path.exists():
            cache[mol_id] = (False, "MOL file not found")
            continue

        try:
            ff_assignment = db.get_ff_assignment(mol_id)
        except Exception:
            ff_assignment = None
        try:
            additive_def = db.get_additive_definition(mol_id)
        except Exception:
            additive_def = None

        # v00.99.72: interface molecule list/detail is a preview surface —
        # the cached support flag must never trigger AM1-BCC generation.
        # Callers that need generation (build/submit) call
        # ensure_organic_artifact directly.
        cache[mol_id] = probe_single_component_generation_support(
            mol_path,
            mol_id,
            ff_assignment=ff_assignment,
            additive_def=additive_def,
            observe_only=True,
        )

    _GENERATION_SUPPORT_CACHE = cache
    _GENERATION_SUPPORT_FINGERPRINT = fp
    return cache


def clear_generation_support_cache() -> None:
    """Clear generation support cache (for testing/reload)."""
    global _GENERATION_SUPPORT_CACHE, _GENERATION_SUPPORT_FINGERPRINT
    _GENERATION_SUPPORT_CACHE = None
    _GENERATION_SUPPORT_FINGERPRINT = None
