"""Molecule structure operations."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.logging import get_logger
from contracts.errors import ErrorCode, ParserError, SecurityError

logger = get_logger("features.molecules.structure")

# Dedicated executor for preview requests to avoid contention with FF generation
# batch (ProcessPoolExecutor consumes 80% CPU during sqm runs).
_preview_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")


def _topology_to_xyz(topology) -> str:
    """Convert MolTopology to XYZ format string."""
    sorted_atoms = sorted(topology.atoms, key=lambda a: a.index)
    lines = [str(len(sorted_atoms)), topology.mol_id or "molecule"]
    for atom in sorted_atoms:
        lines.append(f"{atom.element} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}")
    return "\n".join(lines)


def _resolve_mol_path(mol_id: str) -> tuple[Path, object, object]:
    """Resolve molecule MOL file path.

    Returns:
        (mol_path, mol_spec, db) tuple.

    Raises:
        SecurityError: If structure file not found.
    """
    from api.deps import get_aging_config, get_molecule_db
    from common.pathing import get_project_root

    db = get_molecule_db()
    mol_path = None

    mol_spec = db.get(mol_id)
    if not mol_spec:
        for full_mol_id in db.list_all():
            if mol_id in full_mol_id:
                mol_spec = db.get(full_mol_id)
                if mol_spec and mol_spec.structure_file:
                    logger.debug(f"Matched base_id '{mol_id}' to full mol_id '{full_mol_id}'")
                    break

    if mol_spec and mol_spec.structure_file:
        mol_path = get_project_root() / "data" / "molecules" / mol_spec.structure_file
        if mol_path.exists():
            logger.debug(f"Found structure file via MoleculeDB: {mol_path}")

    if not mol_path or not mol_path.exists():
        config = get_aging_config()
        if config:
            additives = config.get("additives", {})
            if mol_id in additives:
                structure_file = additives[mol_id].get("structure_file")
                if structure_file:
                    mol_path = get_project_root() / "data" / "molecules" / structure_file
                    if mol_path.exists():
                        logger.debug(f"Found structure file via additives config: {mol_path}")

    if not mol_path or not mol_path.exists():
        for aging_dir in [
            "asphalt_binder/non_aging_moles",
            "asphalt_binder/short_aging_moles",
            "asphalt_binder/long_aging_moles",
        ]:
            candidates = list(
                (get_project_root() / "data" / "molecules" / aging_dir).glob(f"**/*{mol_id}*.mol")
            )
            if candidates:
                mol_path = candidates[0]
                logger.debug(f"Found structure file via glob search: {mol_path}")
                break

    # Additives fallback: search in data/molecules/additives directory
    if not mol_path or not mol_path.exists():
        additives_dir = get_project_root() / "data" / "molecules" / "additives"
        if additives_dir.exists():
            # Try exact match first (e.g., SiO2.mol, Lignin.mol)
            exact_candidates = list(additives_dir.glob(f"**/{mol_id}.mol"))
            if exact_candidates:
                mol_path = exact_candidates[0]
                logger.debug(f"Found additive structure file (exact): {mol_path}")
            else:
                # v00.99.66: Case-insensitive fallback for Linux compatibility
                # (Linux glob is case-sensitive, so "sio2" won't match "SiO2.mol")
                all_mols = list(additives_dir.glob("**/*.mol"))
                mol_id_lower = mol_id.lower()
                case_insensitive = [m for m in all_mols if m.stem.lower() == mol_id_lower]
                if case_insensitive:
                    mol_path = case_insensitive[0]
                    logger.debug(f"Found additive structure file (case-insensitive): {mol_path}")
                else:
                    # Partial match fallback
                    partial_candidates = list(additives_dir.glob(f"**/*{mol_id}*.mol"))
                    if partial_candidates:
                        mol_path = partial_candidates[0]
                        logger.debug(f"Found additive structure file (partial): {mol_path}")

    if not mol_path or not mol_path.exists():
        raise SecurityError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"Structure file not found for molecule: {mol_id}",
            {"mol_id": mol_id},
        )

    return mol_path, mol_spec, db


def _analyze_topology(topology, mol_path: Path, mol_id: str) -> dict:
    """Analyze topology for elements, formal charges, and FF availability.

    Wave 2: passes the ff_assignment SSOT record to the support probe so
    blocked / ionic / inorganic species are reported as unsupported with
    the same fail-closed reason the build path emits.
    """
    elements = sorted({atom.element for atom in topology.atoms})

    has_formal_charges = any(atom.charge_defined for atom in topology.atoms)
    formal_charge_sum = round(sum(atom.charge for atom in topology.atoms if atom.charge_defined), 2)

    ff_available = False
    ff_check_message = ""
    try:
        from api.deps import get_molecule_db
        from builder.topology_helpers import probe_single_component_generation_support

        db = get_molecule_db()
        ff_assignment = None
        additive_def = None
        try:
            ff_assignment = db.get_ff_assignment(mol_id)
        except Exception:
            ff_assignment = None
        try:
            additive_def = db.get_additive_definition(mol_id)
        except Exception:
            additive_def = None

        # v00.99.72: preview uses observe_only so a missing artifact returns
        # "not generated" immediately instead of blocking the thread pool on
        # a synchronous AM1-BCC run. Generation is performed via the explicit
        # FF Parameters flow (/artifacts/admin/generate-*) or at submit time.
        supported, reason = probe_single_component_generation_support(
            mol_path,
            mol_id,
            ff_name="GAFF2",
            ff_assignment=ff_assignment,
            additive_def=additive_def,
            observe_only=True,
        )
        ff_available = supported
        if reason:
            ff_check_message = reason
    except Exception as e:
        ff_check_message = str(e)[:150]

    return {
        "elements": elements,
        "has_formal_charges": has_formal_charges,
        "formal_charge_sum": formal_charge_sum,
        "ff_available": ff_available,
        "ff_check_message": ff_check_message,
    }


def _get_molecule_structure_sync(mol_id: str) -> dict:
    """Synchronous implementation of molecule structure retrieval."""
    mol_path, _, db = _resolve_mol_path(mol_id)

    topology = db.parse_mol_topology(mol_path, mol_id)
    if not topology or not topology.atoms:
        raise ParserError(
            ErrorCode.PARSER_ERROR,
            f"Failed to parse structure file for molecule: {mol_id}",
            file_path=str(mol_path),
            details={"mol_id": mol_id},
        )

    xyz_data = _topology_to_xyz(topology)
    bonds = []
    if topology.bonds:
        bonds = [[bond.atom1 - 1, bond.atom2 - 1] for bond in topology.bonds]

    analysis = _analyze_topology(topology, mol_path, mol_id)

    return {
        "mol_id": mol_id,
        "xyz": xyz_data,
        "atom_count": len(topology.atoms),
        "bonds": bonds,
        **analysis,
    }


async def get_molecule_structure(mol_id: str) -> dict:
    """Get molecule structure with dedicated thread pool.

    Uses a separate executor to avoid contention with FF generation batch
    (ProcessPoolExecutor consumes 80% CPU during sqm runs). This ensures
    preview API responses stay fast even during batch operations.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_preview_executor, _get_molecule_structure_sync, mol_id)


async def get_e_intra(
    mol_id: str,
    ff_name: str | None = None,
    ff_version: str | None = None,
    e_intra_method: str | None = None,
) -> dict:
    """Return E_intra values for a molecule keyed by temperature.

    Single Molecule UI shows the 293 K value as the representative
    (matches DEFAULT_TEMPERATURE_PRIORITY_K[0]). The full temperature map is
    returned for tooltips / drilldown.

    Args:
        mol_id: Molecule identifier.
        ff_name: Force field name. Defaults to canonical GAFF2 via SSOT.
        ff_version: Force field version. Defaults to canonical version via SSOT.

    Returns:
        Dict with E_intra data, resolved FF parameters, and coverage.
    """
    from contracts.policies.forcefield import get_ff_display_label, get_ff_version
    from contracts.policies.temperature import DEFAULT_TEMPERATURE_PRIORITY_K
    from contracts.schema_enums import coerce_e_intra_method
    from database.repositories.e_intra_repo import EIntraRepository
    from features.common import run_in_session_async

    # Resolve FF parameters via SSOT (repository defaults)
    _default_ff_type = "bulk_ff_gaff2"
    resolved_ff_name = ff_name if ff_name is not None else get_ff_display_label(_default_ff_type)
    resolved_ff_version = ff_version if ff_version is not None else get_ff_version(_default_ff_type)

    primary_t = DEFAULT_TEMPERATURE_PRIORITY_K[0]  # 293.0

    # PR 3 (v01.04.18): use resolve_submission_e_intra_method() for SSOT consistency.
    # When e_intra_method is None, the resolver falls back to Settings default,
    # then env flags, then Method 1 baseline — matching the submission path.
    from config.dashboard_settings import resolve_submission_e_intra_method

    active_method = (
        coerce_e_intra_method(e_intra_method)
        if e_intra_method
        else resolve_submission_e_intra_method(None)
    )

    def _load(session):
        repo = EIntraRepository(session)
        return repo.get_coverage(
            mol_id,
            ff_name=resolved_ff_name,
            ff_version=resolved_ff_version,
            method=active_method,
        )

    method_tag = active_method.value
    try:
        coverage = await run_in_session_async(_load)
    except Exception:
        return {
            "mol_id": mol_id,
            "ff_name": resolved_ff_name,
            "ff_version": resolved_ff_version,
            "resolved_ff_name": resolved_ff_name,
            "resolved_ff_version": resolved_ff_version,
            "e_intra": None,
            "primary_temperature_K": primary_t,
            "values_by_temperature": {},
            "cached": False,
            "method": method_tag,
        }

    values = coverage.get("latest_values_by_temperature") or {}
    primary_value = values.get(primary_t)
    return {
        "mol_id": mol_id,
        "ff_name": resolved_ff_name,
        "ff_version": resolved_ff_version,
        "resolved_ff_name": resolved_ff_name,
        "resolved_ff_version": resolved_ff_version,
        "e_intra": primary_value,
        "primary_temperature_K": primary_t,
        "values_by_temperature": {str(k): v for k, v in values.items()},
        # PR 2 (Codex Round 6): preserve method on detail responses so the
        # UI can disambiguate Method 1 / 1a / 2 values that share key shape.
        "method": coverage.get("method", method_tag),
        "coverage": {
            "computed_count": coverage.get("computed_count", 0),
            "required_count": coverage.get("required_count", 0),
            "needs_calc": coverage.get("needs_calc", True),
            "method": coverage.get("method", method_tag),
        },
        "cached": primary_value is not None,
    }
