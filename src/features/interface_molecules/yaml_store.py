"""Interface molecule YAML SSOT file CRUD operations.

Handles reading, writing, upserting, and deleting entries in the
interface_molecules.yaml catalog, plus path resolution for cell artifacts.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from api.schemas.interface_molecules import InterfaceMoleculeCellResponse
from common.logging import get_logger
from common.pathing import get_project_root
from contracts.errors import ContractError, ErrorCode

from .catalog import get_interface_molecule_info

logger = get_logger("features.interface_molecules.yaml_store")


def _get_interface_molecules_config_path() -> Path:
    return get_project_root() / "data" / "interface_molecules.yaml"


def _get_interface_molecule_cell_path(
    cell_id: str, filename: str | None = None, *, create: bool = False
) -> Path:
    base = get_project_root() / "data" / "interface_cells" / cell_id
    if create:
        base.mkdir(parents=True, exist_ok=True)
    if filename:
        return base / filename
    return base


def _load_yaml_catalog_for_write() -> dict:
    path = _get_interface_molecules_config_path()
    if path.exists():
        payload = yaml.safe_load(path.read_text()) or {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("library", {"name": "interface_molecules", "version": "1.0"})
    payload.setdefault("directory", "interface_cells")
    cells = payload.get("cells")
    if not isinstance(cells, list):
        payload["cells"] = []
    return payload


def _iter_yaml_cell_items() -> list[dict]:
    path = _get_interface_molecules_config_path()
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text()) or {}
    return list(payload.get("cells", []) or [])


def _write_yaml_catalog_atomic(payload: dict) -> None:
    import os

    path = _get_interface_molecules_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".interface_molecules.", suffix=".yaml", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=False)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _upsert_yaml_cell_entry(entry: dict) -> None:
    payload = _load_yaml_catalog_for_write()
    cells = list(payload.get("cells", []) or [])
    cell_id = str(entry.get("cell_id", "")).strip()
    if not cell_id:
        raise ContractError(ErrorCode.INVALID_REQUEST, "Missing cell_id for YAML entry")

    updated = False
    for idx, existing in enumerate(cells):
        if str((existing or {}).get("cell_id", "")).strip() == cell_id:
            cells[idx] = entry
            updated = True
            break
    if not updated:
        cells.append(entry)

    payload["cells"] = cells
    _write_yaml_catalog_atomic(payload)


def _remove_yaml_cell_entry(cell_id: str) -> None:
    payload = _load_yaml_catalog_for_write()
    cells = list(payload.get("cells", []) or [])
    filtered = [row for row in cells if str((row or {}).get("cell_id", "")).strip() != cell_id]
    if len(filtered) == len(cells):
        return
    payload["cells"] = filtered
    _write_yaml_catalog_atomic(payload)


def _find_yaml_cell_item(cell_id: str) -> dict | None:
    for item in _iter_yaml_cell_items():
        if str(item.get("cell_id", "")).strip() == cell_id:
            return item
    return None


def _yaml_item_to_response(item: dict) -> InterfaceMoleculeCellResponse:
    metadata = dict(item.get("metadata") or {})
    mol_id = str(item.get("mol_id", ""))
    mol_info = get_interface_molecule_info().get(mol_id, {})
    return InterfaceMoleculeCellResponse(
        cell_id=str(item.get("cell_id", "")),
        name=str(item.get("name", item.get("cell_id", ""))),
        status=str(item.get("status", "ready")),
        mol_id=mol_id,
        mol_name=mol_info.get("name"),
        formula=mol_info.get("formula"),
        atom_count=int(item.get("atom_count", 0) or 0),
        molecule_count=int(item.get("molecule_count", 0) or 0),
        target_density=float(item.get("target_density", 0.0) or 0.0),
        actual_density=item.get("actual_density"),
        boundary_mode=str(item.get("boundary_mode", "ppf")),
        lx_angstrom=float(item.get("lx_angstrom", 0.0) or 0.0),
        ly_angstrom=float(item.get("ly_angstrom", 0.0) or 0.0),
        lz_angstrom=float(item.get("lz_angstrom", 0.0) or 0.0),
        lammps_data_file_path=item.get("lammps_data_file_path"),
        xyz_file_path=item.get("xyz_file_path"),
        metadata=metadata,
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
    )


def _response_to_yaml_item(item: InterfaceMoleculeCellResponse) -> dict:
    return {
        "cell_id": item.cell_id,
        "name": item.name,
        "status": item.status,
        "mol_id": item.mol_id,
        "atom_count": int(item.atom_count or 0),
        "molecule_count": int(item.molecule_count or 0),
        "target_density": float(item.target_density or 0.0),
        "actual_density": item.actual_density,
        "boundary_mode": item.boundary_mode,
        "lx_angstrom": float(item.lx_angstrom or 0.0),
        "ly_angstrom": float(item.ly_angstrom or 0.0),
        "lz_angstrom": float(item.lz_angstrom or 0.0),
        "lammps_data_file_path": item.lammps_data_file_path,
        "xyz_file_path": item.xyz_file_path,
        "metadata": dict(item.metadata or {}),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
