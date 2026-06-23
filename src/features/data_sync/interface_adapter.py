"""Interface molecule cells adapter — scan/import via YAML store."""

from __future__ import annotations

from pathlib import Path

from common.logging import get_logger

logger = get_logger("features.data_sync.interface_adapter")


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_cells_dir() -> Path:
    return _get_project_root() / "data" / "interface_cells"


def scan_interface_cells() -> dict:
    """Scan data/interface_cells/ for cell directories not yet in YAML catalog."""
    from features.interface_molecules.yaml_store import _iter_yaml_cell_items

    cells_dir = _get_cells_dir()
    if not cells_dir.exists():
        return {
            "asset_type": "interface_molecule_cells",
            "total_discovered": 0,
            "already_synced": 0,
            "new_items": 0,
            "assets": [],
        }

    # Known cell_ids from YAML
    known_ids = {item["cell_id"] for item in _iter_yaml_cell_items()}

    assets: list[dict] = []
    for entry in sorted(cells_dir.iterdir()):
        if not entry.is_dir():
            continue
        cell_id = entry.name
        already = cell_id in known_ids
        # Check for key artifact files
        has_data = (entry / "structure.data").exists() or any(
            f.suffix == ".data" for f in entry.iterdir() if f.is_file()
        )
        has_xyz = (entry / "structure.xyz").exists() or any(
            f.suffix == ".xyz" for f in entry.iterdir() if f.is_file()
        )
        assets.append(
            {
                "asset_id": cell_id,
                "asset_type": "interface_molecule_cells",
                "name": cell_id,
                "status": "ready" if has_data else "incomplete",
                "already_synced": already,
                "details": {
                    "has_data_file": has_data,
                    "has_xyz_file": has_xyz,
                    "directory": str(entry),
                },
            }
        )

    already_count = sum(1 for a in assets if a["already_synced"])
    return {
        "asset_type": "interface_molecule_cells",
        "total_discovered": len(assets),
        "already_synced": already_count,
        "new_items": len(assets) - already_count,
        "assets": assets,
    }


def import_interface_cells(
    asset_ids: list[str],
    force_import: bool = False,
) -> dict:
    """Import interface cell directories into YAML catalog."""
    from features.interface_molecules.yaml_store import (
        _find_yaml_cell_item,
        _upsert_yaml_cell_entry,
    )

    cells_dir = _get_cells_dir()
    imported = 0
    failed = 0
    results: list[dict] = []

    for cell_id in asset_ids:
        cell_dir = cells_dir / cell_id
        if not cell_dir.is_dir():
            failed += 1
            results.append(
                {"asset_id": cell_id, "status": "error", "reason": "Directory not found"}
            )
            continue

        existing = _find_yaml_cell_item(cell_id)
        if existing and not force_import:
            results.append(
                {"asset_id": cell_id, "status": "skipped", "reason": "Already in catalog"}
            )
            continue

        # Find artifact files
        data_file = _find_file(cell_dir, [".data"])
        xyz_file = _find_file(cell_dir, [".xyz"])

        if not data_file:
            failed += 1
            results.append(
                {"asset_id": cell_id, "status": "error", "reason": "No .data file found"}
            )
            continue

        try:
            # Preserve existing YAML metadata if present
            existing_meta = existing.copy() if existing else {}
            project_root = _get_project_root()
            mol_id = existing_meta.get("mol_id") or _infer_mol_id(cell_id)
            reason = "Added to catalog"
            if not existing_meta.get("mol_id"):
                reason += " (mol_id inferred from directory name)"
            entry = {
                **existing_meta,  # preserve atom_count, density, boundary, etc.
                "cell_id": cell_id,
                "name": existing_meta.get("name") or cell_id,
                "status": "ready",
                "mol_id": mol_id,
                "lammps_data_file_path": str(data_file.relative_to(project_root)),
                "xyz_file_path": (str(xyz_file.relative_to(project_root)) if xyz_file else ""),
                "metadata": {
                    **existing_meta.get("metadata", {}),
                    "imported_by": "data_sync",
                },
            }
            _upsert_yaml_cell_entry(entry)
            imported += 1
            results.append({"asset_id": cell_id, "status": "imported", "reason": reason})
        except Exception as exc:
            failed += 1
            results.append({"asset_id": cell_id, "status": "error", "reason": str(exc)})
            logger.warning("Failed to import interface cell %s: %s", cell_id, exc)

    return {"imported": imported, "failed": failed, "results": results}


def _find_file(directory: Path, suffixes: list[str]) -> Path | None:
    """Find first file with given suffix in directory."""
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix in suffixes:
            return f
    return None


def _infer_mol_id(cell_id: str) -> str:
    """Best-effort mol_id inference from cell_id."""
    # cell_id might be like "ifc_MolName_hash" or just the directory name
    parts = cell_id.split("_", 1)
    if len(parts) > 1 and parts[0] in ("ifc", "ifcell"):
        return parts[1]
    return cell_id
