"""Data sync service — dispatches scan/import/backup/load by asset type."""

from __future__ import annotations

import os

from common.logging import get_logger

logger = get_logger("features.data_sync.service")

_VALID_ASSET_TYPES = {
    "interface_molecule_cells",
    "crystal_structures",
    "all",
}


def _get_nas_root() -> str | None:
    """Return NAS root path from environment, or None if not configured."""
    return os.environ.get("DATA_SYNC_NAS_ROOT") or None


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def _validate_asset_type(asset_type: str) -> None:
    """Raise ValueError if asset_type is not supported."""
    if asset_type not in _VALID_ASSET_TYPES:
        raise ValueError(
            f"Unknown asset_type '{asset_type}'. "
            f"Valid types: {', '.join(sorted(_VALID_ASSET_TYPES))}"
        )


def scan_assets(asset_type: str) -> dict:
    """Scan filesystem for data assets of the given type."""
    _validate_asset_type(asset_type)
    if asset_type == "all":
        return _scan_all()
    if asset_type == "interface_molecule_cells":
        from .interface_adapter import scan_interface_cells

        return scan_interface_cells()
    if asset_type == "crystal_structures":
        from .crystal_adapter import scan_crystal_structures

        return scan_crystal_structures()
    return {
        "asset_type": asset_type,
        "total_discovered": 0,
        "already_synced": 0,
        "new_items": 0,
        "assets": [],
    }


def _scan_all() -> dict:
    """Scan all asset types and merge results."""
    from .crystal_adapter import scan_crystal_structures
    from .interface_adapter import scan_interface_cells

    ifc = scan_interface_cells()
    crys = scan_crystal_structures()
    all_assets = ifc.get("assets", []) + crys.get("assets", [])
    already = sum(1 for a in all_assets if a.get("already_synced"))
    return {
        "asset_type": "all",
        "total_discovered": len(all_assets),
        "already_synced": already,
        "new_items": len(all_assets) - already,
        "assets": all_assets,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_assets(
    asset_type: str,
    asset_ids: list[str],
    force_import: bool = False,
) -> dict:
    """Import selected assets into the system."""
    _validate_asset_type(asset_type)
    if asset_type == "all":
        return _import_all(asset_ids, force_import)
    if asset_type == "interface_molecule_cells":
        from .interface_adapter import import_interface_cells

        return import_interface_cells(asset_ids, force_import)
    if asset_type == "crystal_structures":
        from .crystal_adapter import import_crystal_structures

        return import_crystal_structures(asset_ids, force_import)
    return {"imported": 0, "failed": 0, "results": []}


def _import_all(asset_ids: list[str], force_import: bool) -> dict:
    """Dispatch import by scan results — each asset goes to the correct adapter."""
    from .crystal_adapter import import_crystal_structures, scan_crystal_structures
    from .interface_adapter import import_interface_cells, scan_interface_cells

    # Scan to determine which adapter owns each asset_id
    ifc_scan = scan_interface_cells()
    crys_scan = scan_crystal_structures()
    ifc_known = {a["asset_id"] for a in ifc_scan.get("assets", [])}
    crys_known = {a["asset_id"] for a in crys_scan.get("assets", [])}

    ifc_ids = [a for a in asset_ids if a in ifc_known]
    crys_ids = [a for a in asset_ids if a in crys_known]
    unknown_ids = [a for a in asset_ids if a not in ifc_known and a not in crys_known]

    total_imported = 0
    total_failed = 0
    all_results: list[dict] = []

    if ifc_ids:
        r = import_interface_cells(ifc_ids, force_import)
        total_imported += r["imported"]
        total_failed += r["failed"]
        all_results.extend(r["results"])

    if crys_ids:
        r = import_crystal_structures(crys_ids, force_import)
        total_imported += r["imported"]
        total_failed += r["failed"]
        all_results.extend(r["results"])

    for uid in unknown_ids:
        total_failed += 1
        all_results.append(
            {
                "asset_id": uid,
                "status": "error",
                "reason": "Asset not found in any data-sync source",
            }
        )

    return {"imported": total_imported, "failed": total_failed, "results": all_results}


# ---------------------------------------------------------------------------
# NAS Backup / Load
# ---------------------------------------------------------------------------


def get_nas_status() -> dict:
    """Check NAS configuration status."""
    nas_root = _get_nas_root()
    if not nas_root:
        return {
            "configured": False,
            "nas_root": None,
            "message": "DATA_SYNC_NAS_ROOT not set. Add to .env to enable NAS backup/load.",
        }
    from pathlib import Path

    if not Path(nas_root).exists():
        return {
            "configured": False,
            "nas_root": nas_root,
            "message": f"NAS root path does not exist: {nas_root}",
        }
    return {
        "configured": True,
        "nas_root": nas_root,
        "message": "NAS is configured and accessible.",
    }


def backup_to_nas(asset_types: list[str]) -> dict:
    """Backup data assets to NAS."""
    nas_root = _get_nas_root()
    if not nas_root:
        return {
            "success": False,
            "manifest_path": None,
            "items_backed_up": 0,
            "message": "DATA_SYNC_NAS_ROOT not configured.",
        }
    from .nas_adapter import create_backup

    return create_backup(nas_root, asset_types)


def load_from_nas(manifest_path: str | None) -> dict:
    """Load and preview data assets from NAS (dry-run)."""
    nas_root = _get_nas_root()
    if not nas_root:
        return {
            "success": False,
            "items_found": 0,
            "message": "DATA_SYNC_NAS_ROOT not configured.",
            "assets": [],
        }
    from .nas_adapter import load_preview

    return load_preview(nas_root, manifest_path)


def apply_nas_load(manifest_path: str, targets: list[str] | None = None) -> dict:
    """Apply NAS load — copy selected backup targets to workspace."""
    nas_root = _get_nas_root()
    if not nas_root:
        return {
            "success": False,
            "items_restored": 0,
            "message": "DATA_SYNC_NAS_ROOT not configured.",
        }
    from .nas_adapter import apply_load

    return apply_load(nas_root, manifest_path, targets)
