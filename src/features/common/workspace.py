"""Workspace-relative path resolution utilities."""

from __future__ import annotations

from pathlib import Path

from common.pathing import get_project_root
from contracts.errors import ErrorCode, SecurityError


def resolve_workspace_path(path_value: str) -> Path:
    """Resolve a path relative to the project root, blocking escapes.

    Args:
        path_value: Raw path string (absolute or relative).

    Returns:
        Resolved absolute path within the project root.

    Raises:
        SecurityError: If the resolved path escapes the project root.
    """
    raw_path = Path(path_value).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    else:
        resolved = (get_project_root() / raw_path).resolve()

    allowed_root = get_project_root().resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise SecurityError(
            ErrorCode.PATH_TRAVERSAL_BLOCKED,
            f"Path escapes project root: {path_value}",
            {"path": path_value},
        ) from exc
    return resolved


def as_workspace_relative(path: Path | None) -> str | None:
    """Convert an absolute path to a project-root-relative string.

    Args:
        path: Absolute path to convert, or None.

    Returns:
        Relative path string, or str(path) on failure, or None if input is None.
    """
    if path is None:
        return None
    try:
        root = get_project_root().resolve()
        return str(path.resolve().relative_to(root))
    except Exception:
        return str(path)
