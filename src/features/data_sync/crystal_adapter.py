"""Crystal structures adapter — scan/import via YAML + DB dual sync."""

from __future__ import annotations

from pathlib import Path

from common.logging import get_logger

logger = get_logger("features.data_sync.crystal_adapter")


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_crystal_dir() -> Path:
    return _get_project_root() / "data" / "crystal_structures"


def scan_crystal_structures() -> dict:
    """Scan data/crystal_structures/ for structure directories.

    Compares on-disk directories against the YAML catalog and DB
    to identify new or unsynced structures.
    """
    crystal_dir = _get_crystal_dir()
    if not crystal_dir.exists():
        return {
            "asset_type": "crystal_structures",
            "total_discovered": 0,
            "already_synced": 0,
            "new_items": 0,
            "assets": [],
        }

    # Known crystal_ids from YAML
    known_yaml_ids: set[str] = set()
    try:
        from features.crystal_structures.service import _iter_yaml_crystal_items

        for item in _iter_yaml_crystal_items():
            cid = item.get("crystal_id")
            if cid:
                known_yaml_ids.add(cid)
    except Exception:
        pass

    # Known crystal_ids from DB
    known_db_ids: set[str] = set()
    try:
        from database.connection import session_scope

        with session_scope() as session:
            from database.models.structure import CrystalStructureModel

            rows = session.query(CrystalStructureModel.crystal_id).all()
            known_db_ids = {r[0] for r in rows}
    except Exception:
        pass

    known_ids = known_yaml_ids | known_db_ids
    assets: list[dict] = []

    for entry in sorted(crystal_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Skip non-crystal directories (e.g. .xsd preset files are files, not dirs)
        crystal_id = entry.name
        already = crystal_id in known_ids
        # Check key artifacts
        has_data = (entry / "crystal.data").exists()
        has_xyz = (entry / "crystal.xyz").exists()

        assets.append(
            {
                "asset_id": crystal_id,
                "asset_type": "crystal_structures",
                "name": crystal_id,
                "status": "ready" if has_data else "incomplete",
                "already_synced": already,
                "details": {
                    "has_data_file": has_data,
                    "has_xyz_file": has_xyz,
                    "in_yaml": crystal_id in known_yaml_ids,
                    "in_db": crystal_id in known_db_ids,
                    "directory": str(entry),
                },
            }
        )

    already_count = sum(1 for a in assets if a["already_synced"])
    return {
        "asset_type": "crystal_structures",
        "total_discovered": len(assets),
        "already_synced": already_count,
        "new_items": len(assets) - already_count,
        "assets": assets,
    }


def import_crystal_structures(
    asset_ids: list[str],
    force_import: bool = False,
) -> dict:
    """Import crystal structure directories into YAML catalog and DB."""
    from database.connection import session_scope
    from database.repositories.crystal_repo import CrystalStructureRepository
    from features.crystal_structures.service import (
        _iter_yaml_crystal_items,
        _upsert_yaml_crystal_entry,
    )

    crystal_dir = _get_crystal_dir()
    project_root = _get_project_root()

    # Build known set
    known_yaml = {item.get("crystal_id"): item for item in _iter_yaml_crystal_items()}

    imported = 0
    failed = 0
    results: list[dict] = []

    for crystal_id in asset_ids:
        struct_dir = crystal_dir / crystal_id
        if not struct_dir.is_dir():
            failed += 1
            results.append(
                {"asset_id": crystal_id, "status": "error", "reason": "Directory not found"}
            )
            continue

        if crystal_id in known_yaml and not force_import:
            results.append(
                {"asset_id": crystal_id, "status": "skipped", "reason": "Already in catalog"}
            )
            continue

        data_file = struct_dir / "crystal.data"
        xyz_file = struct_dir / "crystal.xyz"

        if not data_file.exists():
            failed += 1
            results.append(
                {
                    "asset_id": crystal_id,
                    "status": "error",
                    "reason": "Missing crystal.data",
                }
            )
            continue

        try:
            # Merge with existing YAML metadata (SSOT preservation)
            existing = known_yaml.get(crystal_id, {})
            material = existing.get("material") or "unknown"
            surface = existing.get("surface") or "001"
            yaml_entry = {
                **existing,
                "crystal_id": crystal_id,
                "name": existing.get("name") or crystal_id,
                "source_type": existing.get("source_type") or "imported",
                "material": material,
                "surface": surface,
                "status": "ready",
                "lammps_data_file_path": str(data_file.relative_to(project_root)),
                "xyz_file_path": (
                    str(xyz_file.relative_to(project_root)) if xyz_file.exists() else ""
                ),
                "metadata": {
                    **existing.get("metadata", {}),
                    "imported_by": "data_sync",
                },
            }

            # DB-first: upsert DB with all required NOT NULL fields,
            # then YAML. If DB fails, YAML is not written.
            with session_scope() as session:
                repo = CrystalStructureRepository(session)
                repo.upsert_by_crystal_id(
                    crystal_id,
                    name=yaml_entry["name"],
                    source_type=yaml_entry["source_type"],
                    material=material,
                    surface=surface,
                    atom_count=existing.get("atom_count") or 0,
                    nx=existing.get("nx") or 1,
                    ny=existing.get("ny") or 1,
                    nz=existing.get("nz") or 1,
                    status="ready",
                    lammps_data_file_path=str(data_file.relative_to(project_root)),
                    xyz_file_path=(
                        str(xyz_file.relative_to(project_root)) if xyz_file.exists() else None
                    ),
                    metadata_json=yaml_entry.get("metadata"),
                )

            # DB succeeded → write YAML
            _upsert_yaml_crystal_entry(yaml_entry)

            imported += 1
            results.append(
                {"asset_id": crystal_id, "status": "imported", "reason": "Added to catalog"}
            )
        except Exception as exc:
            failed += 1
            results.append({"asset_id": crystal_id, "status": "error", "reason": str(exc)})
            logger.warning("Failed to import crystal structure %s: %s", crystal_id, exc)

    return {"imported": imported, "failed": failed, "results": results}
