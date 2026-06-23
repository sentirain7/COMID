"""Crystal structure library application service."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml

from api.schemas import (
    CrystalBatchGenerateRequest,
    CrystalBatchGenerateResponse,
    CrystalStructureCreateRequest,
    CrystalStructureListResponse,
    CrystalStructurePreviewResponse,
    CrystalStructureResponse,
)
from api.utils.time_utils import iso_or_none as _iso
from builder.crystal_builder import CrystalBuilder
from builder.crystal_importer import load_cif_unit_cell
from builder.layer_spec import CrystalMaterial, CrystalSpec
from common.hashing import compute_content_hash, compute_file_hash
from common.library_config import get_crystal_structures_config_path, load_crystal_structures_config
from common.pathing import get_crystal_structure_path, get_project_root
from contracts.errors import ContractError, DatabaseError, ErrorCode, SecurityError
from database.repositories.crystal_repo import CrystalStructureRepository
from features.common import run_in_session, run_in_session_commit
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


def generate_crystal_name(
    material: str,
    surface: str,
    lx: float,
    ly: float,
    lz: float,
) -> str:
    """Generate standardized crystal structure name (SSOT).

    Format: ``{Material}_{avgXY}A_{lz}A_{surface}``
    Example: ``SiO2_39A_27A_001``
    """
    avg_xy = (lx + ly) / 2.0
    return f"{material}_{avg_xy:.0f}A_{lz:.0f}A_{surface}"


_SUPERCELL_META_KEYS = (
    "transformation_matrix",
    "n_cells_xy",
    "error_xy_pct",
    "matrix_search_used",
    "matrix_search_fallback_reason",
)


def _supercell_response_fields(metadata: dict) -> dict:
    return {
        "actual_lx_angstrom": metadata.get("actual_lx_angstrom"),
        "actual_ly_angstrom": metadata.get("actual_ly_angstrom"),
        "anisotropy_pct": metadata.get("anisotropy_pct"),
        "transformation_matrix": metadata.get("transformation_matrix"),
        "n_cells_xy": metadata.get("n_cells_xy"),
        "error_xy_pct": metadata.get("error_xy_pct"),
        "matrix_search_used": bool(metadata.get("matrix_search_used", False)),
        "matrix_search_fallback_reason": metadata.get("matrix_search_fallback_reason"),
    }


def _attach_supercell_metadata(metadata: dict, *, slab) -> dict:
    merged = dict(metadata or {})
    merged["transformation_matrix"] = slab.transformation_matrix
    merged["n_cells_xy"] = slab.n_cells_xy
    merged["error_xy_pct"] = slab.error_xy_pct
    merged["matrix_search_used"] = slab.matrix_search_used
    merged["matrix_search_fallback_reason"] = slab.matrix_search_fallback_reason
    # Store individual lx/ly for anisotropic supercells
    merged["actual_lx_angstrom"] = float(slab.box[0])
    merged["actual_ly_angstrom"] = float(slab.box[1])
    avg = (slab.box[0] + slab.box[1]) / 2.0
    merged["anisotropy_pct"] = abs(slab.box[0] - slab.box[1]) / max(avg, 1e-12) * 100.0
    return merged


def _to_response(row) -> CrystalStructureResponse:
    metadata = dict(row.metadata_json or {})
    return CrystalStructureResponse(
        crystal_id=row.crystal_id,
        name=row.name,
        source_type=row.source_type,
        material=row.material,
        surface=row.surface,
        cell_mode=metadata.get("cell_mode"),
        status=row.status,
        atom_count=int(row.atom_count or 0),
        nx=int(row.nx or 1),
        ny=int(row.ny or 1),
        nz=int(row.nz or 1),
        thickness_angstrom=float(row.thickness_angstrom or 0.0),
        xy_size_angstrom=float(row.xy_size_angstrom or 0.0),
        hydroxylated=bool(row.hydroxylated),
        hydroxyl_density=float(row.hydroxyl_density or 0.0),
        xyz_file_path=row.xyz_file_path,
        lammps_data_file_path=row.lammps_data_file_path,
        cif_file_path=row.cif_file_path,
        **_supercell_response_fields(metadata),
        metadata=metadata,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _iter_yaml_crystal_items() -> list[dict]:
    cfg = load_crystal_structures_config()
    return list(cfg.get("structures", []) or [])


def _load_yaml_catalog_for_write() -> dict:
    path = get_crystal_structures_config_path()
    if path.exists():
        payload = yaml.safe_load(path.read_text()) or {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("library", {"name": "crystal_structures", "version": "1.0"})
    payload.setdefault("directory", "crystal_structures")
    structures = payload.get("structures")
    if not isinstance(structures, list):
        payload["structures"] = []
    return payload


def _write_yaml_catalog_atomic(payload: dict) -> None:
    import os

    path = get_crystal_structures_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".crystal_structures.", suffix=".yaml", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=False)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _upsert_yaml_crystal_entry(entry: dict) -> None:
    payload = _load_yaml_catalog_for_write()
    structures = list(payload.get("structures", []) or [])
    crystal_id = str(entry.get("crystal_id", "")).strip()
    if not crystal_id:
        raise ContractError(ErrorCode.INVALID_REQUEST, "Missing crystal_id for YAML entry")

    updated = False
    for idx, existing in enumerate(structures):
        if str((existing or {}).get("crystal_id", "")).strip() == crystal_id:
            structures[idx] = entry
            updated = True
            break
    if not updated:
        structures.append(entry)

    payload["structures"] = structures
    _write_yaml_catalog_atomic(payload)


def _remove_yaml_crystal_entry(crystal_id: str) -> None:
    payload = _load_yaml_catalog_for_write()
    structures = list(payload.get("structures", []) or [])
    filtered = [
        row for row in structures if str((row or {}).get("crystal_id", "")).strip() != crystal_id
    ]
    if len(filtered) == len(structures):
        return
    payload["structures"] = filtered
    _write_yaml_catalog_atomic(payload)


def _yaml_item_to_response(item: dict) -> CrystalStructureResponse:
    metadata = dict(item.get("metadata") or {})
    return CrystalStructureResponse(
        crystal_id=str(item.get("crystal_id", "")),
        name=str(item.get("name", item.get("crystal_id", ""))),
        source_type=str(item.get("source_type", "yaml")),
        material=str(item.get("material", "aggregate")),
        surface=str(item.get("surface", "001")),
        cell_mode=str(item.get("cell_mode", "orthogonalized")),
        status=str(item.get("status", "ready")),
        atom_count=int(item.get("atom_count", 0) or 0),
        nx=int(item.get("nx", 1) or 1),
        ny=int(item.get("ny", 1) or 1),
        nz=int(item.get("nz", 1) or 1),
        thickness_angstrom=float(item.get("thickness_angstrom", 0.0) or 0.0),
        xy_size_angstrom=float(item.get("xy_size_angstrom", 0.0) or 0.0),
        hydroxylated=bool(item.get("hydroxylated", False)),
        hydroxyl_density=float(item.get("hydroxyl_density", 0.0) or 0.0),
        xyz_file_path=item.get("xyz_file_path"),
        lammps_data_file_path=item.get("lammps_data_file_path"),
        cif_file_path=item.get("cif_file_path"),
        **_supercell_response_fields(metadata),
        metadata=metadata,
        created_at=None,
        updated_at=None,
    )


def _response_to_yaml_item(item: CrystalStructureResponse) -> dict:
    metadata = dict(item.metadata or {})
    for key in _SUPERCELL_META_KEYS:
        value = getattr(item, key, None)
        if value is not None:
            metadata[key] = value
        else:
            metadata.pop(key, None)

    return {
        "crystal_id": item.crystal_id,
        "name": item.name,
        "source_type": item.source_type,
        "material": item.material,
        "surface": item.surface,
        "cell_mode": item.cell_mode,
        "status": item.status,
        "atom_count": int(item.atom_count or 0),
        "nx": int(item.nx or 1),
        "ny": int(item.ny or 1),
        "nz": int(item.nz or 1),
        "thickness_angstrom": float(item.thickness_angstrom or 0.0),
        "xy_size_angstrom": float(item.xy_size_angstrom or 0.0),
        "hydroxylated": bool(item.hydroxylated),
        "hydroxyl_density": float(item.hydroxyl_density or 0.0),
        "xyz_file_path": item.xyz_file_path,
        "lammps_data_file_path": item.lammps_data_file_path,
        "cif_file_path": item.cif_file_path,
        "metadata": metadata,
    }


def _find_yaml_crystal_item(crystal_id: str) -> dict | None:
    for item in _iter_yaml_crystal_items():
        if str(item.get("crystal_id", "")).strip() == crystal_id:
            return item
    return None


def _validate_cif_path(raw_path: str) -> Path:
    source_path = Path(raw_path).expanduser()
    resolved = source_path.resolve()
    allowed_root = get_project_root().resolve()

    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise SecurityError(
            ErrorCode.PATH_TRAVERSAL_BLOCKED,
            f"CIF path escapes project root: {raw_path}",
            {"cif_path": raw_path},
        ) from exc

    return resolved


def _build_source_hash(request: CrystalStructureCreateRequest) -> str:
    base_payload = {
        "_hash_version": 2,  # bump to invalidate stale entries from v1
        "source_type": request.source_type.value,
        "material": request.material.value,
        "surface": request.surface.value,
        "cell_mode": request.cell_mode.value,
        "thickness_angstrom": request.thickness_angstrom,
        "xy_size_angstrom": request.xy_size_angstrom,
        "hydroxylated": request.hydroxylated,
        "hydroxyl_density": request.hydroxyl_density,
        "use_matrix_search": request.use_matrix_search,
        "max_cells_xy": request.max_cells_xy,
        "matrix_ortho_tolerance": request.matrix_ortho_tolerance,
    }
    # nz is auto-derived from thickness when use_matrix_search=True;
    # only include nx/ny/nz in hash when they are user-controlled.
    if not request.use_matrix_search:
        base_payload["nx"] = request.nx
        base_payload["ny"] = request.ny
        base_payload["nz"] = request.nz

    if request.source_type.value == "preset":
        unit_cell = CrystalBuilder.UNIT_CELLS.get(request.material)
        if unit_cell is not None:
            base_payload["unit_cell_hash"] = compute_content_hash(
                {
                    "a": unit_cell["a"],
                    "b": unit_cell["b"],
                    "c": unit_cell["c"],
                    "n_atoms": len(unit_cell["atoms"]),
                    "atoms": [
                        (elem, round(fx, 6), round(fy, 6), round(fz, 6))
                        for elem, fx, fy, fz in unit_cell["atoms"]
                    ],
                }
            )
    elif request.source_type.value == "cif":
        if request.cif_content:
            base_payload["cif_hash"] = compute_content_hash(request.cif_content)
        elif request.cif_path:
            cif_path = _validate_cif_path(request.cif_path)
            if not cif_path.exists():
                raise ContractError(
                    ErrorCode.STRUCTURE_NOT_FOUND,
                    f"CIF file not found: {cif_path}",
                    {"cif_path": str(cif_path)},
                )
            base_payload["cif_hash"] = compute_file_hash(cif_path)
        else:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "source_type='cif' requires cif_path or cif_content",
            )

    return compute_content_hash(base_payload)


def _get_existing_crystal_structure(
    request: CrystalStructureCreateRequest,
) -> CrystalStructureResponse | None:
    """Return an existing crystal matching the create request, if present."""

    source_hash = _build_source_hash(request)

    def _load_existing(session):
        repo = CrystalStructureRepository(session)
        row = repo.get_by_source_hash(
            source_type=request.source_type.value,
            source_hash=source_hash,
        )
        if row is None:
            return None
        return _to_response(row)

    return run_in_session(_load_existing)


def _prepare_cif_source(
    request: CrystalStructureCreateRequest,
    work_dir: Path,
) -> Path | None:
    if request.source_type.value != "cif":
        return None

    cif_dest = work_dir / "source.cif"

    if request.cif_content:
        cif_dest.write_text(request.cif_content, encoding="utf-8")
        return cif_dest

    if request.cif_path:
        source_path = _validate_cif_path(request.cif_path)
        if not source_path.exists():
            raise ContractError(
                ErrorCode.STRUCTURE_NOT_FOUND,
                f"CIF file not found: {source_path}",
                {"cif_path": str(source_path)},
            )
        shutil.copy2(source_path, cif_dest)
        return cif_dest

    raise ContractError(
        ErrorCode.INVALID_REQUEST,
        "source_type='cif' requires cif_path or cif_content",
    )


async def create_crystal_structure(
    request: CrystalStructureCreateRequest,
) -> CrystalStructureResponse:
    """Create crystal structure template artifacts only (no stabilization job)."""

    source_hash = _build_source_hash(request)
    existing = _get_existing_crystal_structure(request)
    if existing is not None:
        _upsert_yaml_crystal_entry(_response_to_yaml_item(existing))
        return existing

    crystal_id = f"crys_{uuid4().hex[:12]}"
    work_dir = get_crystal_structure_path(crystal_id, create=True)
    try:
        builder = CrystalBuilder()
        cif_path = _prepare_cif_source(request, work_dir)

        if request.source_type.value == "preset":
            spec = CrystalSpec(
                material=request.material,
                surface=request.surface,
                cell_mode=request.cell_mode,
                thickness_angstrom=request.thickness_angstrom,
                xy_size_angstrom=request.xy_size_angstrom,
                nx=request.nx,
                ny=request.ny,
                nz=request.nz,
                hydroxylated=request.hydroxylated,
                hydroxyl_density=request.hydroxyl_density,
                use_matrix_search=request.use_matrix_search,
                max_cells_xy=request.max_cells_xy,
                matrix_ortho_tolerance=request.matrix_ortho_tolerance,
            )
            slab = builder.build(spec)
            unit_cell = builder.UNIT_CELLS.get(request.material, {})
            material_value = request.material.value
        else:
            if cif_path is None:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    "CIF source was not prepared",
                )
            unit_cell = load_cif_unit_cell(cif_path)
            spec = CrystalSpec(
                material=CrystalMaterial.AGGREGATE,
                surface=request.surface,
                cell_mode=request.cell_mode,
                thickness_angstrom=request.thickness_angstrom,
                xy_size_angstrom=request.xy_size_angstrom,
                nx=request.nx,
                ny=request.ny,
                nz=request.nz,
                hydroxylated=request.hydroxylated,
                hydroxyl_density=request.hydroxyl_density,
                use_matrix_search=request.use_matrix_search,
                max_cells_xy=request.max_cells_xy,
                matrix_ortho_tolerance=request.matrix_ortho_tolerance,
            )
            slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)
            material_value = CrystalMaterial.AGGREGATE.value

        # Generate standardized name from actual build dimensions (SSOT)
        crystal_name = generate_crystal_name(
            material=material_value,
            surface=request.surface.value,
            lx=slab.box[0],
            ly=slab.box[1],
            lz=slab.box[2],
        )

        xyz_path = get_crystal_structure_path(crystal_id, "crystal.xyz", create=True)
        data_path = get_crystal_structure_path(crystal_id, "crystal.data", create=True)
        slab.to_xyz(xyz_path)
        slab.to_lammps_data(data_path, title=f"Crystal template {crystal_name}")
        if not xyz_path.exists() or not data_path.exists():
            raise ContractError(
                ErrorCode.STRUCTURE_NOT_FOUND,
                "Generated crystal artifacts are missing after build.",
                {
                    "xyz_path": str(xyz_path),
                    "lammps_data_path": str(data_path),
                },
            )

        lattice_payload = {
            "a": float(unit_cell.get("a", 0.0)),
            "b": float(unit_cell.get("b", 0.0)),
            "c": float(unit_cell.get("c", 0.0)),
            "alpha": float(unit_cell.get("alpha", 90.0)),
            "beta": float(unit_cell.get("beta", 90.0)),
            "gamma": float(unit_cell.get("gamma", 90.0)),
        }

        base_metadata = _attach_supercell_metadata(
            {
                **(request.metadata or {}),
                "cell_mode": request.cell_mode.value,
                "size_resolution": (
                    "matrix_search" if slab.matrix_search_used else "diagonal_replication"
                ),
                "target_xy_size_angstrom": request.xy_size_angstrom,
                "target_thickness_angstrom": request.thickness_angstrom,
            },
            slab=slab,
        )

        rel_cif = _as_workspace_relative(cif_path)
        rel_xyz = _as_workspace_relative(xyz_path)
        rel_data = _as_workspace_relative(data_path)
        yaml_entry = {
            "crystal_id": crystal_id,
            "name": crystal_name,
            "source_type": request.source_type.value,
            "material": material_value,
            "surface": request.surface.value,
            "cell_mode": request.cell_mode.value,
            "status": "ready",
            "atom_count": int(slab.n_atoms),
            "nx": int(slab.nx),
            "ny": int(slab.ny),
            "nz": int(slab.nz),
            "thickness_angstrom": float(slab.box[2]),
            "xy_size_angstrom": float(max(slab.box[0], slab.box[1])),
            "hydroxylated": bool(request.hydroxylated),
            "hydroxyl_density": float(request.hydroxyl_density),
            "xyz_file_path": rel_xyz,
            "lammps_data_file_path": rel_data,
            "cif_file_path": rel_cif,
            "metadata": dict(base_metadata),
        }

        _upsert_yaml_crystal_entry(yaml_entry)

        def _save(session):
            repo = CrystalStructureRepository(session)
            row = repo.upsert_by_crystal_id(
                crystal_id,
                name=crystal_name,
                source_type=request.source_type.value,
                source_hash=source_hash,
                status="ready",
                material=material_value,
                surface=request.surface.value,
                atom_count=slab.n_atoms,
                nx=slab.nx,
                ny=slab.ny,
                nz=slab.nz,
                thickness_angstrom=float(slab.box[2]),
                xy_size_angstrom=float(max(slab.box[0], slab.box[1])),
                hydroxylated=request.hydroxylated,
                hydroxyl_density=request.hydroxyl_density,
                lattice_json=lattice_payload,
                cif_file_path=rel_cif,
                xyz_file_path=rel_xyz,
                lammps_data_file_path=rel_data,
                metadata_json=base_metadata,
            )
            return _to_response(row)

        try:
            return run_in_session_commit(_save)
        except Exception as exc:
            _remove_yaml_crystal_entry(crystal_id)
            raise ContractError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Database unavailable. Crystal creation was not completed",
                {"reason": str(exc)},
            ) from exc
    except Exception as exc:
        error_message = str(exc)

        def _mark_failed(session):
            repo = CrystalStructureRepository(session)
            row = repo.get_by_id(crystal_id)
            if row is None:
                return
            metadata = dict(row.metadata_json or {})
            metadata["last_error"] = error_message
            repo.update_status(
                crystal_id,
                "failed",
                metadata_json=metadata,
            )

        run_in_session_commit(_mark_failed)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        raise


async def list_crystal_structures(
    *,
    status: str | None = None,
    limit: int = 100,
    visibility: str = "library",
) -> CrystalStructureListResponse:
    """List crystal structure templates from YAML SSOT."""
    bounded_limit = max(1, min(limit, 500))
    allowed_statuses = {"ready"} if visibility == "library" else None

    yaml_rows = _iter_yaml_crystal_items()
    yaml_ids = [
        str((raw or {}).get("crystal_id", "")).strip()
        for raw in yaml_rows
        if str((raw or {}).get("crystal_id", "")).strip()
    ]

    def _load_db_by_ids(session):
        repo = CrystalStructureRepository(session)
        rows = repo.list_by_ids(yaml_ids)
        return {
            row.crystal_id: {
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "metadata_json": dict(row.metadata_json or {}),
            }
            for row in rows
        }

    db_map = run_in_session(_load_db_by_ids) if yaml_ids else {}

    items = []
    for raw in yaml_rows:
        item = _yaml_item_to_response(raw)
        db_info = db_map.get(item.crystal_id)
        if db_info is not None:
            item.status = db_info["status"]
            item.created_at = _iso(db_info["created_at"])
            item.updated_at = _iso(db_info["updated_at"])
            merged = dict(item.metadata or {})
            merged.update(db_info["metadata_json"])
            item.metadata = merged
            for key, value in _supercell_response_fields(merged).items():
                setattr(item, key, value)
        if status and item.status != status:
            continue
        if allowed_statuses is not None and item.status not in allowed_statuses:
            continue
        items.append(item)

    items = items[:bounded_limit]
    return CrystalStructureListResponse(total=len(items), items=items)


async def get_crystal_structure(crystal_id: str) -> CrystalStructureResponse:
    """Get crystal structure detail from YAML SSOT."""
    row = _find_yaml_crystal_item(crystal_id)
    if row is not None:
        return _yaml_item_to_response(row)
    raise DatabaseError(
        ErrorCode.RECORD_NOT_FOUND,
        f"Crystal structure not found: {crystal_id}",
        {"crystal_id": crystal_id},
    )


async def get_crystal_structure_preview(crystal_id: str) -> CrystalStructurePreviewResponse:
    """Get crystal structure preview payload for 3D rendering."""
    row = _find_yaml_crystal_item(crystal_id)
    if row is None:
        raise DatabaseError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Crystal structure not found: {crystal_id}",
            {"crystal_id": crystal_id},
        )
    data_path_value = str(row.get("lammps_data_file_path") or "").strip()
    preview_name = str(row.get("name", crystal_id))

    if not data_path_value:
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"LAMMPS data path missing for crystal: {crystal_id}.",
            {"crystal_id": crystal_id},
        )

    data_path = _resolve_workspace_path(data_path_value)
    if not data_path.exists():
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"Crystal data file not found: {data_path}",
            {"crystal_id": crystal_id, "data_path": str(data_path)},
        )

    parser = DataParser()
    info = parser.parse(data_path)
    type_map = parser.estimate_elements_from_info(info)
    xyz_str, box_size = parser.info_to_xyz(
        info,
        type_map,
        comment=f"Crystal preview {preview_name}",
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

    return CrystalStructurePreviewResponse(
        crystal_id=crystal_id,
        xyz=xyz_str,
        box_size=box_size,
        n_atoms=info.n_atoms,
        n_bonds=len(bonds),
        bonds=bonds,
        density=density,
        type_map=type_map,
    )


async def delete_crystal_structure(crystal_id: str) -> dict:
    """Delete crystal structure from YAML catalog, DB, and filesystem.

    Removal order: YAML (SSOT) → DB → filesystem artifacts.

    Args:
        crystal_id: Unique crystal structure identifier.

    Returns:
        Dict with crystal_id and deleted status.

    Raises:
        DatabaseError: If crystal_id not found in YAML catalog.
    """
    yaml_item = _find_yaml_crystal_item(crystal_id)
    if yaml_item is None:
        raise DatabaseError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Crystal structure not found: {crystal_id}",
            {"crystal_id": crystal_id},
        )

    # 1. YAML 카탈로그에서 제거 (SSOT)
    _remove_yaml_crystal_entry(crystal_id)

    # 2. DB 레코드 삭제
    def _delete_from_db(session):
        repo = CrystalStructureRepository(session)
        repo.delete(crystal_id)

    try:
        run_in_session_commit(_delete_from_db)
    except Exception:
        pass  # DB 레코드가 없어도 YAML 삭제는 유지

    # 3. 파일시스템 아티팩트 삭제
    try:
        work_dir = get_crystal_structure_path(crystal_id, create=False)
        if work_dir.exists() and work_dir.is_dir():
            shutil.rmtree(work_dir)
    except Exception:
        pass  # 디렉토리가 없어도 무시

    return {"crystal_id": crystal_id, "deleted": True}


async def batch_generate_crystal_sizes(
    request: CrystalBatchGenerateRequest,
) -> CrystalBatchGenerateResponse:
    """Batch-generate all available supercell sizes for a material in [xy_min, xy_max].

    Dynamically enumerates available sizes from unit cell parameters, then
    creates each size that doesn't already exist (dedup by source_hash).
    """
    from builder.supercell_search import enumerate_available_sizes

    unit_cell = CrystalBuilder.UNIT_CELLS.get(request.material)
    if unit_cell is None:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown material: {request.material.value}",
            {"material": request.material.value},
        )

    # Resolve surface: None → auto-detect from crystal structure properties
    surface = request.surface or CrystalBuilder.preferred_surface(request.material)

    sizes = enumerate_available_sizes(
        a=unit_cell["a"],
        b=unit_cell["b"],
        gamma_deg=unit_cell["gamma"],
        c=unit_cell["c"],
        xy_min=request.xy_min,
        xy_max=request.xy_max,
        target_z=request.thickness_angstrom,
    )

    sizes_response: list[CrystalStructureResponse] = []
    generated_count = 0
    skipped = 0

    for entry in sizes:
        create_req = CrystalStructureCreateRequest(
            name=f"{request.material.value}-{surface.value}-{entry.avg_xy:.1f}A",
            source_type="preset",
            material=request.material,
            surface=surface,
            cell_mode="orthogonalized",
            thickness_angstrom=request.thickness_angstrom,
            xy_size_angstrom=entry.avg_xy,
            hydroxylated=request.hydroxylated,
            hydroxyl_density=request.hydroxyl_density,
            use_matrix_search=True,
        )
        existing = _get_existing_crystal_structure(create_req)
        if existing is not None:
            _upsert_yaml_crystal_entry(_response_to_yaml_item(existing))
            sizes_response.append(existing)
            skipped += 1
            continue

        resp = await create_crystal_structure(create_req)
        sizes_response.append(resp)
        generated_count += 1

    return CrystalBatchGenerateResponse(
        material=request.material.value,
        surface=surface.value,
        generated_count=generated_count,
        skipped_count=skipped,
        sizes=sizes_response,
    )


# ─────────────────────────────────────────────────────────────────────────────
# P2: Async batch generation (202 Accepted)
#
# Background function for non-blocking batch generation.
# Uses asyncio.run() to run async code in sync context (BackgroundTasks).
# ProcessPoolExecutor NOT used due to session/YAML pickling issues.
# ─────────────────────────────────────────────────────────────────────────────


def batch_generate_crystal_sizes_background(
    batch_id: str,
    request: CrystalBatchGenerateRequest,
) -> None:
    """Background task: sequential batch generation with progress tracking.

    ⚠️ Sync function — called from BackgroundTasks.add_task().
    Uses asyncio.run() to execute async create_crystal_structure().

    Args:
        batch_id: Unique identifier for progress tracking.
        request: Original batch generate request.
    """
    import asyncio

    from builder.supercell_search import enumerate_available_sizes

    from .batch_progress import (
        finalize_batch_progress,
        mark_batch_failed,
        release_batch_slot,
        start_batch_progress,
        update_item_progress,
    )

    async def _run():
        from common.logging import get_logger

        logger = get_logger("features.crystal_structures.batch")

        unit_cell = CrystalBuilder.UNIT_CELLS.get(request.material)
        if unit_cell is None:
            logger.error("batch_generate_background: Unknown material %s", request.material)
            # Codex fix: Fatal precondition failure → mark as failed, not completed
            mark_batch_failed(batch_id, f"Unknown material: {request.material}")
            return

        surface = request.surface or CrystalBuilder.preferred_surface(request.material)

        sizes = enumerate_available_sizes(
            a=unit_cell["a"],
            b=unit_cell["b"],
            gamma_deg=unit_cell["gamma"],
            c=unit_cell["c"],
            xy_min=request.xy_min,
            xy_max=request.xy_max,
            target_z=request.thickness_angstrom,
        )

        # Codex fix: Transition from queued → running with actual items and metadata
        # Items were not known at router time (computed dynamically)
        size_labels = [f"{s.avg_xy:.1f}A" for s in sizes]
        start_batch_progress(
            batch_id,
            size_labels,
            metadata={
                "material": request.material.value,
                "surface": surface.value,
            },
        )

        for entry in sizes:
            size_label = f"{entry.avg_xy:.1f}A"
            try:
                create_req = CrystalStructureCreateRequest(
                    name=f"{request.material.value}-{surface.value}-{entry.avg_xy:.1f}A",
                    source_type="preset",
                    material=request.material,
                    surface=surface,
                    cell_mode="orthogonalized",
                    thickness_angstrom=request.thickness_angstrom,
                    xy_size_angstrom=entry.avg_xy,
                    hydroxylated=request.hydroxylated,
                    hydroxyl_density=request.hydroxyl_density,
                    use_matrix_search=True,
                )

                # Check for existing structure
                existing = _get_existing_crystal_structure(create_req)
                if existing is not None:
                    _upsert_yaml_crystal_entry(_response_to_yaml_item(existing))
                    # Codex fix: Store full response for frontend legacy shape reconstruction
                    update_item_progress(
                        batch_id,
                        size_label,
                        "skipped",
                        existing.model_dump(mode="json"),
                    )
                    continue

                # Create new structure
                resp = await create_crystal_structure(create_req)
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
