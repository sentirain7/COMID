"""NAS backup/load adapter — manifest-based data synchronization."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from common.logging import get_logger

logger = get_logger("features.data_sync.nas_adapter")

# Directories/files to include in NAS backup
_BACKUP_TARGETS = [
    "database/",
    "data/arrays/",
    "data/e_intra/",
    "data/interface_molecules.yaml",
    "data/interface_cells/",
    "data/molecules/crystal_structures.yaml",
    "data/crystal_structures/",
    "data/forcefield_artifacts/",
]


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _validate_path_within(path: Path, allowed_root: Path, label: str = "path") -> None:
    """Raise ValueError if resolved path escapes allowed_root."""
    resolved = path.resolve()
    root_resolved = allowed_root.resolve()
    if not str(resolved).startswith(str(root_resolved) + "/") and resolved != root_resolved:
        raise ValueError(f"{label} escapes allowed root: {path}")


def _validate_target(target: str) -> None:
    """Raise ValueError if target is unsafe or not in _BACKUP_TARGETS allowlist.

    Only targets in the hardcoded _BACKUP_TARGETS are allowed.
    Manifest targets are NOT trusted — they could be tampered with.
    """
    if target.startswith("/"):
        raise ValueError(f"Absolute path not allowed in target: {target}")
    if ".." in target.split("/"):
        raise ValueError(f"Path traversal not allowed in target: {target}")
    if target not in _BACKUP_TARGETS:
        raise ValueError(f"Target not in allowlist: {target}")


def create_backup(nas_root: str, asset_types: list[str]) -> dict:
    """Create a backup to NAS with manifest."""
    project_root = _get_project_root()
    nas_path = Path(nas_root)

    if not nas_path.exists():
        return {
            "success": False,
            "manifest_path": None,
            "items_backed_up": 0,
            "message": f"NAS root does not exist: {nas_root}",
        }

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_dir = nas_path / f"asphalt_backup_{timestamp}"

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        items_copied = 0

        for target in _BACKUP_TARGETS:
            src = project_root / target
            if not src.exists():
                continue

            dst = backup_dir / target
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                items_copied += 1
            elif src.is_dir():
                # Skip empty directories
                if not any(src.iterdir()):
                    continue
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                items_copied += 1

        # Also backup DB file if SQLite
        db_file = project_root / "asphalt_agent.db"
        if db_file.exists():
            shutil.copy2(str(db_file), str(backup_dir / "asphalt_agent.db"))
            items_copied += 1

        # Write manifest
        manifest = {
            "version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "source_host": _get_hostname(),
            "project_root": str(project_root),
            "items": items_copied,
            "targets": _BACKUP_TARGETS,
            "asset_types": asset_types,
            "scope": "full_workspace",
        }
        manifest_path = backup_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        logger.info("NAS backup created: %s (%d items)", backup_dir, items_copied)
        return {
            "success": True,
            "manifest_path": str(manifest_path),
            "items_backed_up": items_copied,
            "message": f"Backup created at {backup_dir}",
        }

    except Exception as exc:
        logger.error("NAS backup failed: %s", exc)
        return {
            "success": False,
            "manifest_path": None,
            "items_backed_up": 0,
            "message": str(exc),
        }


def load_preview(nas_root: str, manifest_path: str | None) -> dict:
    """Preview what would be loaded from NAS (dry-run)."""
    nas_path = Path(nas_root)

    if not nas_path.exists():
        return {
            "success": False,
            "items_found": 0,
            "message": f"NAS root does not exist: {nas_root}",
            "assets": [],
        }

    # Find the most recent backup if no manifest specified
    if not manifest_path:
        backup_dirs = sorted(
            [d for d in nas_path.iterdir() if d.is_dir() and d.name.startswith("asphalt_backup_")],
            reverse=True,
        )
        if not backup_dirs:
            return {
                "success": False,
                "items_found": 0,
                "message": "No backups found in NAS root.",
                "assets": [],
            }
        manifest_path = str(backup_dirs[0] / "manifest.json")

    manifest_file = Path(manifest_path)

    # Path traversal protection: manifest must be within NAS root
    try:
        _validate_path_within(manifest_file, nas_path, "manifest_path")
    except ValueError as exc:
        return {
            "success": False,
            "items_found": 0,
            "message": str(exc),
            "assets": [],
        }

    if not manifest_file.exists():
        return {
            "success": False,
            "items_found": 0,
            "message": f"Manifest not found: {manifest_path}",
            "assets": [],
        }

    try:
        manifest = json.loads(manifest_file.read_text())
        backup_dir = manifest_file.parent

        # Validate all manifest targets against hardcoded allowlist
        manifest_targets = manifest.get("targets", _BACKUP_TARGETS)
        for target in manifest_targets:
            try:
                _validate_target(target)
            except ValueError as exc:
                return {
                    "success": False,
                    "items_found": 0,
                    "manifest_path": None,
                    "message": f"Manifest contains invalid target: {exc}",
                    "assets": [],
                }

        assets: list[dict] = []
        for target in manifest_targets:
            src = backup_dir / target
            if not src.exists():
                continue
            if src.is_file():
                assets.append(
                    {
                        "asset_id": target,
                        "asset_type": "file",
                        "name": target,
                        "status": "available",
                        "already_synced": False,
                        "details": {"size_bytes": src.stat().st_size},
                    }
                )
            elif src.is_dir():
                n_items = sum(1 for _ in src.iterdir())
                assets.append(
                    {
                        "asset_id": target,
                        "asset_type": "directory",
                        "name": target,
                        "status": "available",
                        "already_synced": False,
                        "details": {
                            "item_count": n_items,
                            "source_host": manifest.get("source_host", "unknown"),
                            "backup_date": manifest.get("created_at", "unknown"),
                        },
                    }
                )

        return {
            "success": True,
            "items_found": len(assets),
            "manifest_path": str(manifest_file),
            "message": f"Backup from {manifest.get('created_at', 'unknown')}",
            "assets": assets,
        }

    except Exception as exc:
        return {
            "success": False,
            "items_found": 0,
            "message": str(exc),
            "assets": [],
        }


def apply_load(
    nas_root: str,
    manifest_path: str,
    targets: list[str] | None = None,
) -> dict:
    """Apply NAS load — copy selected backup targets to workspace.

    Args:
        nas_root: NAS root directory.
        manifest_path: Path to manifest.json (required, from preview).
        targets: Subset of targets to restore. If None, restore all.

    Returns:
        Dict with success, items_restored, message.
    """
    if not manifest_path:
        return {
            "success": False,
            "items_restored": 0,
            "message": "manifest_path is required. Run Load Preview first.",
        }
    nas_path = Path(nas_root)
    project_root = _get_project_root()

    manifest_file = Path(manifest_path)

    # Path traversal protection: manifest must be within NAS root
    try:
        _validate_path_within(manifest_file, nas_path, "manifest_path")
    except ValueError as exc:
        return {"success": False, "items_restored": 0, "message": str(exc)}

    if not manifest_file.exists():
        return {
            "success": False,
            "items_restored": 0,
            "message": f"Manifest not found: {manifest_path}",
        }

    try:
        manifest = json.loads(manifest_file.read_text())
        backup_dir = manifest_file.parent
        restore_targets = targets or manifest.get("targets", _BACKUP_TARGETS)
        items_restored = 0

        # Validate all targets against hardcoded _BACKUP_TARGETS allowlist
        for target in restore_targets:
            _validate_target(target)

        # Clean up old snapshots (keep last 5)
        snapshot_dir = project_root / ".data_sync_snapshots"
        _cleanup_old_snapshots(snapshot_dir, keep=5)

        # Create local snapshot before overwriting
        snapshot_name = f"pre_restore_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        snapshot_path = snapshot_dir / snapshot_name
        snapshot_path.mkdir(parents=True, exist_ok=True)

        for target in restore_targets:
            src = backup_dir / target
            if not src.exists():
                continue
            dst = project_root / target

            # Snapshot existing data before overwrite
            if dst.exists():
                snap_dst = snapshot_path / target
                snap_dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.is_file():
                    shutil.copy2(str(dst), str(snap_dst))
                elif dst.is_dir():
                    shutil.copytree(str(dst), str(snap_dst), dirs_exist_ok=True)

            # Restore from backup
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                items_restored += 1
            elif src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                items_restored += 1

        # DB file restore is excluded from apply — requires server restart.
        # Log warning if DB file was in targets.
        db_src = backup_dir / "asphalt_agent.db"
        db_skipped = False
        if db_src.exists() and (not targets or "asphalt_agent.db" in targets):
            db_skipped = True
            logger.warning(
                "DB file restore skipped — requires server stop. Copy manually: %s → %s",
                db_src,
                project_root / "asphalt_agent.db",
            )

        logger.info(
            "NAS load applied from %s (%d items, snapshot=%s)",
            backup_dir,
            items_restored,
            snapshot_path,
        )
        msg = f"Restored {items_restored} item(s) from {backup_dir.name}"
        if db_skipped:
            msg += ". DB file skipped (requires server restart to restore safely)."
        msg += f" Pre-restore snapshot: {snapshot_path}"
        return {
            "success": True,
            "items_restored": items_restored,
            "message": msg,
        }

    except Exception as exc:
        logger.error("NAS load apply failed: %s", exc)
        return {"success": False, "items_restored": 0, "message": str(exc)}


def _cleanup_old_snapshots(snapshot_dir: Path, keep: int = 5) -> None:
    """Remove old snapshot directories, keeping the most recent ``keep``."""
    if not snapshot_dir.exists():
        return
    dirs = sorted(
        [d for d in snapshot_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for old_dir in dirs[keep:]:
        try:
            shutil.rmtree(old_dir)
            logger.info("Cleaned up old snapshot: %s", old_dir.name)
        except Exception as exc:
            logger.warning("Failed to clean snapshot %s: %s", old_dir.name, exc)


def _get_hostname() -> str:
    """Get current hostname."""
    import socket

    try:
        return socket.gethostname()
    except Exception:
        return "unknown"
