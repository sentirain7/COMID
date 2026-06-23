"""Interface molecule cell library application service.

Creates environment molecule cells (H2O, NaCl, CO2, etc.) for use as
interface layers in layered structures. No MD simulation - structure only.
"""

from __future__ import annotations

import math
import shutil
from uuid import uuid4

from api.schemas.interface_molecules import (
    BatchFailureItem,
    InterfaceMoleculeBatchGenerateRequest,
    InterfaceMoleculeBatchGenerateResponse,
    InterfaceMoleculeCellCreateRequest,
    InterfaceMoleculeCellListResponse,
    InterfaceMoleculeCellPreviewResponse,
    InterfaceMoleculeCellResponse,
    InterfaceMoleculeInfo,
    InterfaceMoleculeListResponse,
    InterfaceMoleculePreviewResponse,
)
from common.hashing import compute_content_hash
from common.logging import get_logger
from common.pathing import get_project_root
from common.seed import generate_seed
from common.units import AVOGADRO
from contracts.errors import ContractError, DatabaseError, ErrorCode
from features.common.density import (
    density_from_total_mass as _density_from_total_mass,
)
from features.common.density import (
    total_mass_from_types as _total_mass_from_types,
)
from features.common.workspace import (
    as_workspace_relative as _as_workspace_relative,
)
from features.common.workspace import (
    resolve_workspace_path as _resolve_workspace_path,
)
from parsers.data_parser import DataParser

# ---------------------------------------------------------------------------
# Re-exports from catalog.py (backward compatibility)
# ---------------------------------------------------------------------------
from .catalog import (  # noqa: F401
    CATEGORY_LABELS,
    _compute_mol_size,
    _extract_elements_from_mol,
    _get_generation_support,
    _load_molecule_info_from_yaml,
    _settings_fingerprint,
    clear_generation_support_cache,
    clear_molecule_info_cache,
    get_interface_molecule_info,
)

# ---------------------------------------------------------------------------
# Re-exports from yaml_store.py (backward compatibility)
# ---------------------------------------------------------------------------
from .yaml_store import (  # noqa: F401
    _find_yaml_cell_item,
    _get_interface_molecule_cell_path,
    _get_interface_molecules_config_path,
    _iter_yaml_cell_items,
    _load_yaml_catalog_for_write,
    _remove_yaml_cell_entry,
    _response_to_yaml_item,
    _upsert_yaml_cell_entry,
    _write_yaml_catalog_atomic,
    _yaml_item_to_response,
)

logger = get_logger("features.interface_molecules.service")


# =============================================================================
# Molecule List / Preview
# =============================================================================


def list_interface_molecules() -> InterfaceMoleculeListResponse:
    """List available interface molecules with category info."""
    support = _get_generation_support()
    items = []
    for mol_id, info in get_interface_molecule_info().items():
        supported, reason = support.get(mol_id, (True, None))
        size_info = _compute_mol_size(mol_id)
        mol_size = size_info[0] if size_info else None
        max_extent = size_info[1] if size_info else None
        items.append(
            InterfaceMoleculeInfo(
                mol_id=mol_id,
                name=info["name"],
                category=info["category"],
                formula=info["formula"],
                atom_count=info["atom_count"],
                molecular_weight=info["molecular_weight"],
                elements=info["elements"],
                recommended_density=info.get("recommended_density"),
                mol_size_angstrom=mol_size,
                max_extent_angstrom=max_extent,
                generation_supported=supported,
                generation_reason=reason,
            )
        )
    categories = sorted({info["category"] for info in get_interface_molecule_info().values()})
    return InterfaceMoleculeListResponse(
        total=len(items),
        categories=categories,
        items=items,
    )


async def get_molecule_preview(mol_id: str) -> InterfaceMoleculePreviewResponse:
    """Get single molecule preview for 3D viewer."""
    if mol_id not in get_interface_molecule_info():
        raise ContractError(
            ErrorCode.MOLECULE_NOT_FOUND,
            f"Interface molecule not found: {mol_id}",
            {"mol_id": mol_id},
        )

    info = get_interface_molecule_info()[mol_id]
    mol_path = get_project_root() / "data" / "molecules" / "single_moles" / f"{mol_id}.mol"
    if not mol_path.exists():
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"MOL file not found for {mol_id}",
            {"mol_id": mol_id, "path": str(mol_path)},
        )

    # Parse MOL file to XYZ
    xyz_lines = [f"{info['atom_count']}", f"{info['name']} - {info['formula']}"]
    bonds = []

    with mol_path.open() as f:
        lines = f.readlines()

    # Parse V2000 MOL format
    counts_line = lines[3].strip().split()
    n_atoms = int(counts_line[0])
    n_bonds = int(counts_line[1])

    for i in range(4, 4 + n_atoms):
        parts = lines[i].split()
        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        elem = parts[3]
        xyz_lines.append(f"{elem}  {x:.4f}  {y:.4f}  {z:.4f}")

    for i in range(4 + n_atoms, 4 + n_atoms + n_bonds):
        parts = lines[i].split()
        atom1 = int(parts[0]) - 1  # 0-indexed
        atom2 = int(parts[1]) - 1
        bonds.append([atom1, atom2])

    xyz_str = "\n".join(xyz_lines)

    size_info = _compute_mol_size(mol_id)
    mol_size = size_info[0] if size_info else None
    max_extent = size_info[1] if size_info else None

    return InterfaceMoleculePreviewResponse(
        mol_id=mol_id,
        name=info["name"],
        xyz=xyz_str,
        atom_count=info["atom_count"],
        n_bonds=len(bonds),
        bonds=bonds,
        molecular_weight=info["molecular_weight"],
        elements=info["elements"],
        mol_size_angstrom=mol_size,
        max_extent_angstrom=max_extent,
    )


# =============================================================================
# Cell CRUD Operations
# =============================================================================


def _build_source_hash(request: InterfaceMoleculeCellCreateRequest) -> str:
    payload = {
        "mol_id": request.mol_id,
        "lx_angstrom": request.lx_angstrom,
        "ly_angstrom": request.ly_angstrom,
        "lz_angstrom": request.lz_angstrom,
        "target_density": request.target_density,
        "boundary_mode": request.boundary_mode.value,
    }
    return compute_content_hash(payload)


def _build_cell_source_hash(
    mol_id: str,
    lx: float,
    ly: float,
    lz: float,
    target_density: float,
    boundary_mode: str,
) -> str:
    """Build source hash from raw parameters (without creating a request object).

    This avoids the min_length=1 constraint on name field when computing hash
    for deduplication in batch generation.
    """
    payload = {
        "mol_id": mol_id,
        "lx_angstrom": lx,
        "ly_angstrom": ly,
        "lz_angstrom": lz,
        "target_density": target_density,
        "boundary_mode": boundary_mode,
    }
    return compute_content_hash(payload)


def _get_existing_interface_cell(
    mol_id: str,
    lx: float,
    ly: float,
    lz: float,
    target_density: float,
    boundary_mode: str,
) -> dict | None:
    """Return existing cell with same parameters, if present.

    Dedup by source_hash to avoid recreating identical cells.
    """
    source_hash = _build_cell_source_hash(mol_id, lx, ly, lz, target_density, boundary_mode)

    for item in _iter_yaml_cell_items():
        if str(item.get("source_hash", "")) == source_hash:
            return item
    return None


def _enumerate_interface_batch_sizes(
    xy_min: float,
    xy_max: float,
) -> list[float]:
    """Enumerate XY candidate sizes in range [xy_min, xy_max].

    This is a policy function that determines which sizes to generate.
    The internal step size is an implementation detail, not exposed in the API.

    Returns:
        List of distinct XY sizes (Angstrom) within the specified range.
    """
    # Internal policy: 10 Angstrom step for interface molecules
    # (Unlike crystals which enumerate from lattice parameters,
    #  interface molecules use simple box sizes)
    step = 10.0

    sizes = []
    xy = xy_min
    while xy <= xy_max + step * 0.5:
        sizes.append(round(xy, 1))
        xy += step
    return sizes


async def batch_generate_interface_molecule_cells(
    request: InterfaceMoleculeBatchGenerateRequest,
) -> InterfaceMoleculeBatchGenerateResponse:
    """Batch-generate interface molecule cells in [xy_min, xy_max] range.

    Enumerates candidate XY sizes using internal policy, then creates each
    cell that doesn't already exist (dedup by source_hash).
    Reuses existing create_interface_molecule_cell() for actual generation.
    """
    if request.mol_id not in get_interface_molecule_info():
        raise ContractError(
            ErrorCode.MOLECULE_NOT_FOUND,
            f"Interface molecule not found: {request.mol_id}",
            {"mol_id": request.mol_id},
        )

    mol_info = get_interface_molecule_info()[request.mol_id]

    # Policy function determines candidate sizes
    sizes = _enumerate_interface_batch_sizes(request.xy_min, request.xy_max)

    cells_response: list[InterfaceMoleculeCellResponse] = []
    generated_count = 0
    skipped_count = 0
    failures: list[BatchFailureItem] = []

    for xy_size in sizes:
        # Check for existing cell (dedup)
        existing = _get_existing_interface_cell(
            mol_id=request.mol_id,
            lx=xy_size,
            ly=xy_size,
            lz=request.lz_angstrom,
            target_density=request.target_density,
            boundary_mode=request.boundary_mode.value,
        )

        if existing is not None:
            cells_response.append(_yaml_item_to_response(existing))
            skipped_count += 1
            continue

        # Reuse existing create function
        name = f"{request.mol_id}_d{request.target_density:.2f}_{xy_size:.0f}x{xy_size:.0f}x{request.lz_angstrom:.0f}"
        create_req = InterfaceMoleculeCellCreateRequest(
            name=name,
            mol_id=request.mol_id,
            lx_angstrom=xy_size,
            ly_angstrom=xy_size,
            lz_angstrom=request.lz_angstrom,
            target_density=request.target_density,
            boundary_mode=request.boundary_mode,
        )

        try:
            resp = await create_interface_molecule_cell(create_req)
            cells_response.append(resp)
            generated_count += 1
        except ContractError as exc:
            if exc.code == ErrorCode.INVALID_REQUEST:
                failures.append(
                    BatchFailureItem(
                        lx_angstrom=xy_size,
                        ly_angstrom=xy_size,
                        lz_angstrom=request.lz_angstrom,
                        error_code=str(exc.code),
                        message=str(exc.message),
                    )
                )
                continue
            raise

    return InterfaceMoleculeBatchGenerateResponse(
        mol_id=request.mol_id,
        mol_name=mol_info["name"],
        generated_count=generated_count,
        skipped_count=skipped_count,
        failed_count=len(failures),
        failures=failures,
        cells=cells_response,
    )


async def create_interface_molecule_cell(
    request: InterfaceMoleculeCellCreateRequest,
) -> InterfaceMoleculeCellResponse:
    """Create interface molecule cell structure (no MD simulation).

    Uses Packmol to pack molecules into the specified box at target density,
    then generates full-topology LAMMPS .data via topology_helpers.

    Raises:
        ContractError(INVALID_REQUEST): When the molecule is unsupported by
            the current typing/charge settings (user-actionable).
        ContractError(BUILD_ERROR): On unexpected system errors.
    """
    from datetime import UTC, datetime

    from builder.mol_parser import parse_mol_topology
    from builder.packmol_wrapper import PackmolMolecule, PackmolWrapper
    from builder.topology_helpers import convert_mol_to_xyz, generate_single_component_topology
    from contracts.errors import BuildError
    from forcefield.organic_typing_executor import TypingChargeAssignmentError

    if request.mol_id not in get_interface_molecule_info():
        raise ContractError(
            ErrorCode.MOLECULE_NOT_FOUND,
            f"Interface molecule not found: {request.mol_id}",
            {"mol_id": request.mol_id},
        )

    mol_info = get_interface_molecule_info()[request.mol_id]
    source_hash = _build_source_hash(request)

    # Check for existing cell with same parameters
    for item in _iter_yaml_cell_items():
        if str(item.get("source_hash", "")) == source_hash:
            return _yaml_item_to_response(item)

    # Calculate molecule count from density
    volume_a3 = request.lx_angstrom * request.ly_angstrom * request.lz_angstrom
    total_mass_g = request.target_density * volume_a3 * 1e-24
    mw = mol_info["molecular_weight"]
    molecule_count = max(1, int(math.floor(total_mass_g / mw * AVOGADRO + 0.5)))

    cell_id = f"ifc_{uuid4().hex[:8]}"
    work_dir = _get_interface_molecule_cell_path(cell_id, create=True)

    try:
        # 1. Validate MOL file exists
        mol_path = (
            get_project_root() / "data" / "molecules" / "single_moles" / f"{request.mol_id}.mol"
        )
        if not mol_path.exists():
            raise ContractError(
                ErrorCode.STRUCTURE_NOT_FOUND,
                f"MOL file not found for {request.mol_id}",
                {"mol_id": request.mol_id},
            )

        # 2. Parse MOL topology
        mol_topology = parse_mol_topology(mol_path, request.mol_id)
        if mol_topology is None:
            raise ContractError(
                ErrorCode.STRUCTURE_NOT_FOUND,
                f"Failed to parse MOL topology for {request.mol_id}",
                {"mol_id": request.mol_id},
            )

        # 3. Convert MOL to XYZ (Packmol only supports XYZ/PDB/TINKER)
        mol_xyz = convert_mol_to_xyz(
            mol_topology, request.mol_id, work_dir / f"{request.mol_id}.xyz"
        )

        # 4. Run Packmol
        seed = generate_seed(request.seed)
        packmol = PackmolWrapper(seed=seed)
        packed_xyz = work_dir / "packed.xyz"

        result = packmol.pack(
            molecules=[
                PackmolMolecule(structure_file=mol_xyz, count=molecule_count, mol_id=request.mol_id)
            ],
            output_file=packed_xyz,
            total_mass_g_mol=mw * molecule_count,
            box_dimensions=(request.lx_angstrom, request.ly_angstrom, request.lz_angstrom),
            work_dir=work_dir,
            contain_entire_molecules=True,
        )
        if not result.success:
            raise ContractError(
                ErrorCode.PACKMOL_FAILED,
                f"Packmol failed: {result.error_message}",
                {"cell_id": cell_id},
            )

        # 4b. Post-pack box containment validation
        from builder.topology_helpers import parse_xyz_coordinates

        coords = parse_xyz_coordinates(packed_xyz)
        lx, ly, lz = request.lx_angstrom, request.ly_angstrom, request.lz_angstrom
        box_epsilon = 0.5  # Angstrom tolerance
        violations = sum(
            1
            for x, y, z in coords
            if x < -box_epsilon
            or x > lx + box_epsilon
            or y < -box_epsilon
            or y > ly + box_epsilon
            or z < -box_epsilon
            or z > lz + box_epsilon
        )
        if violations > 0:
            if result.containment_feasible:
                # Strict: containment was feasible but atoms still escaped -> error
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)
                raise ContractError(
                    ErrorCode.PACKMOL_FAILED,
                    f"Box containment failed: {violations}/{len(coords)} atoms exceed bounds by > {box_epsilon} Angstrom",
                    {"cell_id": cell_id, "mol_id": request.mol_id, "violations": violations},
                )
            else:
                # Lenient: containment infeasible (molecule too large), warning only
                logger.warning(
                    f"{violations}/{len(coords)} atoms outside box "
                    f"(containment infeasible, using standard margin)"
                )

        # 5. Generate full-topology LAMMPS .data file. Wave 2: thread the
        # ff_assignment SSOT through the helper so blocked / ionic /
        # inorganic species are rejected with the same fail-closed reason
        # the build path emits.
        from api.deps import get_molecule_db

        data_path = work_dir / "cell.data"
        xyz_path = work_dir / "cell.xyz"

        db = get_molecule_db()
        try:
            ff_assignment = db.get_ff_assignment(request.mol_id)
        except Exception:
            ff_assignment = None
        try:
            additive_def = db.get_additive_definition(request.mol_id)
        except Exception:
            additive_def = None

        try:
            generate_single_component_topology(
                mol_path,
                request.mol_id,
                molecule_count,
                packed_xyz,
                data_path,
                (request.lx_angstrom, request.ly_angstrom, request.lz_angstrom),
                ff_assignment=ff_assignment,
                additive_def=additive_def,
            )
        except (TypingChargeAssignmentError, BuildError) as exc:
            # Clean up work_dir for user-actionable failures
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
            if isinstance(exc, TypingChargeAssignmentError):
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Molecule {request.mol_id} not supported with current typing/charge settings: {exc}",
                    {"mol_id": request.mol_id, "stage": "typing_charge"},
                ) from exc
            if isinstance(exc, BuildError) and exc.code == ErrorCode.TOPOLOGY_GENERATION_FAILED:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Topology generation failed for {request.mol_id}: {exc.message}",
                    {"mol_id": request.mol_id, "stage": "topology_generation"},
                ) from exc
            raise  # re-raise other BuildErrors as system errors

        # 6. Generate XYZ preview + calculate actual density
        parser = DataParser()
        info = parser.parse(data_path)
        type_map = parser.estimate_elements_from_info(info)
        xyz_str, box_size = parser.info_to_xyz(
            info, type_map, comment=f"Interface cell {request.name}"
        )
        xyz_path.write_text(xyz_str)

        total_mass_g_mol = _total_mass_from_types(
            atom_types=[atom.atom_type for atom in info.atoms],
            mass_by_type=info.masses,
        )
        actual_density = _density_from_total_mass(total_mass_g_mol, box_size)

        # Save to YAML catalog
        now_iso = datetime.now(UTC).isoformat()
        yaml_entry = {
            "cell_id": cell_id,
            "name": request.name,
            "status": "ready",
            "source_hash": source_hash,
            "mol_id": request.mol_id,
            "atom_count": info.n_atoms,
            "molecule_count": molecule_count,
            "target_density": request.target_density,
            "actual_density": actual_density,
            "boundary_mode": request.boundary_mode.value,
            "lx_angstrom": request.lx_angstrom,
            "ly_angstrom": request.ly_angstrom,
            "lz_angstrom": request.lz_angstrom,
            "lammps_data_file_path": _as_workspace_relative(data_path),
            "xyz_file_path": _as_workspace_relative(xyz_path),
            "metadata": dict(request.metadata or {}),
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _upsert_yaml_cell_entry(yaml_entry)

        return _yaml_item_to_response(yaml_entry)

    except ContractError:
        # Re-raise ContractErrors (including INVALID_REQUEST from B3) as-is
        raise
    except Exception as exc:
        # Cleanup on unexpected failure
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        raise ContractError(
            ErrorCode.BUILD_ERROR,
            f"Failed to create interface molecule cell: {exc}",
            {"cell_id": cell_id, "mol_id": request.mol_id},
        ) from exc


async def list_interface_molecule_cells(
    *,
    status: str | None = None,
    limit: int = 100,
    visibility: str = "library",
) -> InterfaceMoleculeCellListResponse:
    """List interface molecule cells from YAML SSOT."""
    bounded_limit = max(1, min(limit, 500))
    allowed_statuses = {"ready"} if visibility == "library" else None

    yaml_rows = _iter_yaml_cell_items()
    items = []

    for raw in yaml_rows:
        item = _yaml_item_to_response(raw)
        if status and item.status != status:
            continue
        if allowed_statuses is not None and item.status not in allowed_statuses:
            continue
        items.append(item)

    items = items[:bounded_limit]
    return InterfaceMoleculeCellListResponse(total=len(items), items=items)


async def get_interface_molecule_cell(cell_id: str) -> InterfaceMoleculeCellResponse:
    """Get interface molecule cell detail from YAML SSOT."""
    row = _find_yaml_cell_item(cell_id)
    if row is not None:
        return _yaml_item_to_response(row)
    raise DatabaseError(
        ErrorCode.RECORD_NOT_FOUND,
        f"Interface molecule cell not found: {cell_id}",
        {"cell_id": cell_id},
    )


async def get_interface_molecule_cell_preview(cell_id: str) -> InterfaceMoleculeCellPreviewResponse:
    """Get interface molecule cell preview payload for 3D rendering."""
    row = _find_yaml_cell_item(cell_id)
    if row is None:
        raise DatabaseError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Interface molecule cell not found: {cell_id}",
            {"cell_id": cell_id},
        )

    data_path_value = str(row.get("lammps_data_file_path") or "").strip()
    if not data_path_value:
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"LAMMPS data path missing for cell: {cell_id}.",
            {"cell_id": cell_id},
        )

    data_path = _resolve_workspace_path(data_path_value)
    if not data_path.exists():
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"Cell data file not found: {data_path}",
            {"cell_id": cell_id, "data_path": str(data_path)},
        )

    parser = DataParser()
    info = parser.parse(data_path)
    type_map = parser.estimate_elements_from_info(info)
    xyz_str, box_size = parser.info_to_xyz(
        info,
        type_map,
        comment=f"Interface cell preview {row.get('name', cell_id)}",
    )

    atom_id_to_idx = {atom.atom_id: idx for idx, atom in enumerate(info.atoms)}
    bonds: list[list[int]] = []
    for bond in info.bonds:
        idx1 = atom_id_to_idx.get(bond.atom1_id)
        idx2 = atom_id_to_idx.get(bond.atom2_id)
        if idx1 is not None and idx2 is not None:
            bonds.append([idx1, idx2])

    total_mass_g_mol = _total_mass_from_types(
        atom_types=[atom.atom_type for atom in info.atoms],
        mass_by_type=info.masses,
    )
    density = _density_from_total_mass(total_mass_g_mol, box_size)

    return InterfaceMoleculeCellPreviewResponse(
        cell_id=cell_id,
        xyz=xyz_str,
        box_size=box_size,
        n_atoms=info.n_atoms,
        n_bonds=len(bonds),
        bonds=bonds,
        density=density,
        boundary_mode=str(row.get("boundary_mode", "ppf")),
        type_map=type_map,
    )


async def delete_interface_molecule_cell(cell_id: str) -> dict:
    """Delete interface molecule cell from YAML catalog and filesystem."""
    yaml_item = _find_yaml_cell_item(cell_id)
    if yaml_item is None:
        raise DatabaseError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Interface molecule cell not found: {cell_id}",
            {"cell_id": cell_id},
        )

    # Remove from YAML catalog
    _remove_yaml_cell_entry(cell_id)

    # Remove filesystem artifacts
    try:
        work_dir = _get_interface_molecule_cell_path(cell_id, create=False)
        if work_dir.exists() and work_dir.is_dir():
            shutil.rmtree(work_dir)
    except Exception:
        pass

    return {"cell_id": cell_id, "deleted": True}


# =============================================================================
# Public YAML Helpers (for layered structure service integration)
# =============================================================================


def get_interface_cell_by_id(cell_id: str) -> dict | None:
    """Public wrapper for layered structure service."""
    return _find_yaml_cell_item(cell_id)


def list_interface_cells_for_sources(limit: int = 100, visibility: str = "library") -> list[dict]:
    """List interface molecule cells for layered source listing."""
    items = list(_iter_yaml_cell_items())
    if visibility == "library":
        items = [i for i in items if i.get("status") == "ready"]
    return items[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# P2: Async batch generation (202 Accepted)
#
# Background function for non-blocking batch generation.
# Uses asyncio.run() to run async code in sync context (BackgroundTasks).
# ProcessPoolExecutor NOT used due to session/YAML pickling issues.
# ─────────────────────────────────────────────────────────────────────────────


def batch_generate_interface_molecule_cells_background(
    batch_id: str,
    request: InterfaceMoleculeBatchGenerateRequest,
) -> None:
    """Background task: sequential batch generation with progress tracking.

    ⚠️ Sync function — called from BackgroundTasks.add_task().
    Uses asyncio.run() to execute async create_interface_molecule_cell().

    Args:
        batch_id: Unique identifier for progress tracking.
        request: Original batch generate request.
    """
    import asyncio

    from .batch_progress import (
        finalize_batch_progress,
        mark_batch_failed,
        release_batch_slot,
        start_batch_progress,
        update_item_progress,
    )

    async def _run():
        from common.logging import get_logger

        logger = get_logger("features.interface_molecules.batch")

        mol_info = get_interface_molecule_info()
        if request.mol_id not in mol_info:
            logger.error("batch_generate_background: Unknown mol_id %s", request.mol_id)
            # Codex fix: Fatal precondition failure → mark as failed, not completed
            mark_batch_failed(batch_id, f"Unknown mol_id: {request.mol_id}")
            return

        mol_name = mol_info[request.mol_id].get("name", request.mol_id)

        # Policy function determines candidate sizes
        sizes = _enumerate_interface_batch_sizes(request.xy_min, request.xy_max)

        # Codex fix: Transition from queued → running with actual items and metadata
        # Items were not known at router time (computed dynamically)
        size_labels = [f"{s:.0f}x{s:.0f}" for s in sizes]
        start_batch_progress(
            batch_id,
            size_labels,
            metadata={
                "mol_id": request.mol_id,
                "mol_name": mol_name,
            },
        )

        for xy_size in sizes:
            size_label = f"{xy_size:.0f}x{xy_size:.0f}"
            try:
                # Check for existing cell (dedup)
                existing = _get_existing_interface_cell(
                    mol_id=request.mol_id,
                    lx=xy_size,
                    ly=xy_size,
                    lz=request.lz_angstrom,
                    target_density=request.target_density,
                    boundary_mode=request.boundary_mode.value,
                )

                if existing is not None:
                    # Codex fix: Store full response for frontend legacy shape reconstruction
                    update_item_progress(batch_id, size_label, "skipped", existing)
                    continue

                # Create new cell
                name = f"{request.mol_id}_d{request.target_density:.2f}_{xy_size:.0f}x{xy_size:.0f}x{request.lz_angstrom:.0f}"
                create_req = InterfaceMoleculeCellCreateRequest(
                    name=name,
                    mol_id=request.mol_id,
                    lx_angstrom=xy_size,
                    ly_angstrom=xy_size,
                    lz_angstrom=request.lz_angstrom,
                    target_density=request.target_density,
                    boundary_mode=request.boundary_mode,
                )

                resp = await create_interface_molecule_cell(create_req)
                # Codex fix: Store full response for frontend legacy shape reconstruction
                update_item_progress(
                    batch_id,
                    size_label,
                    "completed",
                    resp.model_dump(mode="json"),
                )

            except Exception as e:
                logger.exception("batch_generate_background: Failed for size %s: %s", size_label, e)
                update_item_progress(batch_id, size_label, "failed", {"error": str(e)})

        finalize_batch_progress(batch_id)

    # Codex fix: Wrap in try/except/finally for proper error handling and slot release
    try:
        asyncio.run(_run())
    except Exception as e:
        # Mark batch as failed if unexpected exception occurs
        mark_batch_failed(batch_id, str(e))
    finally:
        # Ensure slot is released even on exception
        # Note: finalize_batch_progress also releases slot, but this is a safety net
        release_batch_slot(batch_id)
