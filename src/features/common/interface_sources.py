"""Resolve, merge-list, and water-detect interface molecule sources.

Bridges the legacy ``amor_*`` (DB-backed amorphous cells) and the new
``ifc_*`` (YAML-backed interface molecule cells) behind a single adapter
dict so that downstream consumers (layered structures, binder analysis, ML
loader) can work with either origin transparently.

All DB-touching functions accept an optional ``session`` parameter.  When
provided the caller's session is reused; otherwise a fresh one is created
via :func:`features.common.db.run_in_session`.

Heavy imports are performed lazily inside each function to avoid circular
dependencies at module-load time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from features.common.source_compat import (
    CANONICAL_INTERFACE_TYPE,
    is_interface_like_source,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger("features.common.interface_sources")


# ---------------------------------------------------------------------------
# Water-like detection
# ---------------------------------------------------------------------------

_WATER_KEYWORDS: frozenset[str] = frozenset({"h2o", "water", "tip3p"})


def is_water_like_source(
    *,
    source_type: str,
    mol_id: str | None = None,
    components_json: list | None = None,
) -> bool:
    """Determine whether a source represents a water-like molecule.

    The check is conservative: returns ``False`` when neither *mol_id* nor
    *components_json* provides enough evidence, even if *source_type* is
    interface-like.

    Args:
        source_type: The (possibly legacy) source type string.
        mol_id: Molecule identifier from YAML or inferred from DB.
        components_json: Legacy amorphous cell component list.

    Returns:
        ``True`` only when the source is interface-like **and** its metadata
        indicates water.
    """
    if not is_interface_like_source(source_type):
        return False

    # Check mol_id first (YAML sources always have this)
    if mol_id:
        if any(w in mol_id.lower() for w in _WATER_KEYWORDS):
            return True

    # Fall back to legacy components_json inspection
    if components_json is not None:
        return _components_contain_h2o(components_json)

    return False


def _components_contain_h2o(components_json: object) -> bool:
    """Check if *components_json* contains H2O / water reference.

    Mirrors the pattern in ``binder_analysis/lookup.py``.

    Args:
        components_json: Component list (list of dicts or strings).

    Returns:
        ``True`` when at least one component looks water-like.
    """
    if not isinstance(components_json, list):
        return False
    for item in components_json:
        if isinstance(item, dict):
            for field in ("mol_id", "name", "type", "component_mol_id"):
                val = item.get(field, "")
                if isinstance(val, str) and any(w in val.lower() for w in _WATER_KEYWORDS):
                    return True
        elif isinstance(item, str):
            if any(w in item.lower() for w in _WATER_KEYWORDS):
                return True
    return False


# ---------------------------------------------------------------------------
# Adapter dict builder
# ---------------------------------------------------------------------------


def _yaml_item_to_adapter(item: dict) -> dict:
    """Convert a YAML cell item dict to the unified adapter dict.

    Args:
        item: Raw dict from the YAML catalog.

    Returns:
        Adapter dict with the canonical key set.
    """
    mol_id = str(item.get("mol_id", "") or "")
    components_json: list | None = None
    raw_components = item.get("components_json")
    if isinstance(raw_components, list):
        components_json = raw_components

    return {
        "source_id": str(item.get("cell_id", "")),
        "source_type": CANONICAL_INTERFACE_TYPE,
        "origin": "yaml",
        "name": str(item.get("name", item.get("cell_id", ""))),
        "status": str(item.get("status", "ready")),
        "lammps_data_file_path": item.get("lammps_data_file_path"),
        "atom_count": int(item.get("atom_count", 0) or 0),
        "boundary_mode": str(item.get("boundary_mode", "ppf")),
        "lx_angstrom": float(item.get("lx_angstrom", 0.0) or 0.0),
        "ly_angstrom": float(item.get("ly_angstrom", 0.0) or 0.0),
        "lz_angstrom": float(item.get("lz_angstrom", 0.0) or 0.0),
        "actual_density": item.get("actual_density"),
        "target_density": float(item.get("target_density", 0.0) or 0.0),
        "mol_id": mol_id or None,
        "components_json": components_json,
        "is_water_like": is_water_like_source(
            source_type=CANONICAL_INTERFACE_TYPE,
            mol_id=mol_id or None,
            components_json=components_json,
        ),
    }


def _db_row_to_adapter(row: object) -> dict:
    """Convert an :class:`AmorphousCellModel` ORM row to the adapter dict.

    Args:
        row: An ``AmorphousCellModel`` instance.

    Returns:
        Adapter dict with the canonical key set.
    """
    components_json: list | None = None
    raw_components = getattr(row, "components_json", None)
    if isinstance(raw_components, list):
        components_json = raw_components

    # Try to infer mol_id from single-component cells
    mol_id = _infer_mol_id_from_components(components_json)

    return {
        "source_id": str(getattr(row, "amorphous_id", "")),
        "source_type": CANONICAL_INTERFACE_TYPE,
        "origin": "db",
        "name": str(getattr(row, "name", "")),
        "status": str(getattr(row, "status", "draft")),
        "lammps_data_file_path": getattr(row, "lammps_data_file_path", None),
        "atom_count": int(getattr(row, "atom_count", 0) or 0),
        "boundary_mode": str(getattr(row, "boundary_mode", "ppp")),
        "lx_angstrom": float(getattr(row, "lx_angstrom", 0.0) or 0.0),
        "ly_angstrom": float(getattr(row, "ly_angstrom", 0.0) or 0.0),
        "lz_angstrom": float(getattr(row, "lz_angstrom", 0.0) or 0.0),
        "actual_density": getattr(row, "density", None),
        "target_density": float(getattr(row, "target_density", 0.0) or 0.0),
        "mol_id": mol_id,
        "components_json": components_json,
        "is_water_like": is_water_like_source(
            source_type=CANONICAL_INTERFACE_TYPE,
            mol_id=mol_id,
            components_json=components_json,
        ),
    }


def _infer_mol_id_from_components(components_json: list | None) -> str | None:
    """Infer mol_id from a single-component legacy amorphous cell.

    Args:
        components_json: Legacy component list.

    Returns:
        The ``mol_id`` of the sole component, or ``None``.
    """
    if not isinstance(components_json, list) or len(components_json) != 1:
        return None
    comp = components_json[0]
    if isinstance(comp, dict):
        for field in ("mol_id", "component_mol_id"):
            val = comp.get(field)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


# ---------------------------------------------------------------------------
# Public API: dedicated water cell finder
# ---------------------------------------------------------------------------


def find_ready_yaml_water_cell(session: Session | None = None) -> dict | None:
    """Find a ready, PPF, water-like YAML interface molecule cell.

    Unlike :func:`list_canonical_sources`, this skips DB entirely and searches
    all YAML cells without an arbitrary limit.

    Args:
        session: Unused; accepted for API symmetry with other helpers.

    Returns:
        Adapter dict for the first matching water cell, or ``None``.
    """
    from features.interface_molecules.service import list_interface_cells_for_sources

    # Get ALL ready YAML cells (no limit)
    items = list_interface_cells_for_sources(limit=9999, visibility="library")
    for item in items:
        adapter = _yaml_item_to_adapter(item)
        if adapter.get("is_water_like") and adapter.get("boundary_mode") == "ppf":
            return adapter
    return None


# ---------------------------------------------------------------------------
# Public API: resolve
# ---------------------------------------------------------------------------


def resolve_interface_source(source_id: str, session: Session | None = None) -> dict | None:
    """Resolve a source by ID, dispatching on prefix.

    - ``ifc_*`` prefix: read from YAML via interface molecules service.
    - ``amor_*`` prefix: read from legacy DB via
      :class:`AmorphousCellRepository`.

    Args:
        source_id: The source identifier (e.g. ``"ifc_abc123"`` or
            ``"amor_xyz789"``).
        session: Optional SQLAlchemy session.  When ``None`` a fresh session
            is created automatically for DB lookups.

    Returns:
        A unified adapter dict, or ``None`` if the source was not found.
    """
    if source_id.startswith("ifc_"):
        return _resolve_yaml_source(source_id)
    if source_id.startswith("amor_"):
        return _resolve_db_source(source_id, session)

    # Unknown prefix — try YAML first, then DB
    result = _resolve_yaml_source(source_id)
    if result is not None:
        return result
    return _resolve_db_source(source_id, session)


def _resolve_yaml_source(source_id: str) -> dict | None:
    """Resolve a YAML-backed interface molecule cell.

    Args:
        source_id: Cell ID to look up.

    Returns:
        Adapter dict or ``None``.
    """
    from features.interface_molecules.service import get_interface_cell_by_id

    item = get_interface_cell_by_id(source_id)
    if item is None:
        return None
    return _yaml_item_to_adapter(item)


def _resolve_db_source(source_id: str, session: Session | None = None) -> dict | None:
    """Resolve a legacy DB-backed amorphous cell.

    Args:
        source_id: Amorphous cell ID.
        session: Optional pre-existing session.

    Returns:
        Adapter dict or ``None``.
    """
    from database.repositories.amorphous_repo import AmorphousCellRepository

    def _query(sess: Session) -> dict | None:
        repo = AmorphousCellRepository(sess)
        row = repo.get_by_id(source_id)
        if row is None:
            return None
        return _db_row_to_adapter(row)

    if session is not None:
        return _query(session)

    from features.common.db import run_in_session

    return run_in_session(_query)


# ---------------------------------------------------------------------------
# Public API: listing
# ---------------------------------------------------------------------------


def list_canonical_sources(
    limit: int = 100,
    visibility: str = "library",
    session: Session | None = None,
) -> list[dict]:
    """Merge YAML ``ifc_*`` cells and legacy DB ``amor_*`` rows.

    Both origins are unified under the canonical source type.  Duplicate
    ``source_id`` values are deduplicated (YAML wins).

    Args:
        limit: Maximum number of items to return.
        visibility: Filter mode (``"library"`` restricts to ready/stabilized).
        session: Optional pre-existing DB session.

    Returns:
        List of adapter dicts up to *limit* items.
    """
    bounded_limit = max(1, min(limit, 500))
    seen_ids: set[str] = set()
    results: list[dict] = []

    # --- YAML sources first (they take priority for dedup) ---
    yaml_items = _list_yaml_sources(visibility, limit=bounded_limit)
    for item in yaml_items:
        sid = item["source_id"]
        if sid not in seen_ids:
            seen_ids.add(sid)
            results.append(item)

    # --- Legacy DB sources ---
    db_items = _list_db_sources(bounded_limit, visibility, session)
    for item in db_items:
        sid = item["source_id"]
        if sid not in seen_ids:
            seen_ids.add(sid)
            results.append(item)

    return results[:bounded_limit]


def list_legacy_only_sources(
    limit: int = 100,
    visibility: str = "library",
    session: Session | None = None,
) -> list[dict]:
    """List only legacy DB ``amor_*`` rows (for the legacy alias route).

    Args:
        limit: Maximum number of items to return.
        visibility: Filter mode.
        session: Optional pre-existing DB session.

    Returns:
        List of adapter dicts from the legacy DB only.
    """
    bounded_limit = max(1, min(limit, 500))
    return _list_db_sources(bounded_limit, visibility, session)


# ---------------------------------------------------------------------------
# Internal listing helpers
# ---------------------------------------------------------------------------


def _list_yaml_sources(visibility: str, limit: int = 500) -> list[dict]:
    """Fetch YAML-backed interface molecule cells as adapter dicts.

    Args:
        visibility: When ``"library"`` only ``"ready"`` cells are returned.
        limit: Maximum number of YAML items to fetch.

    Returns:
        List of adapter dicts.
    """
    from features.interface_molecules.service import (
        list_interface_cells_for_sources,
    )

    items = list_interface_cells_for_sources(limit=limit, visibility=visibility)
    return [_yaml_item_to_adapter(item) for item in items]


def _list_db_sources(
    limit: int,
    visibility: str,
    session: Session | None = None,
) -> list[dict]:
    """Fetch legacy DB amorphous cells as adapter dicts.

    Args:
        limit: Maximum rows to fetch.
        visibility: When ``"library"`` only ``"stabilized"`` rows are returned.
        session: Optional pre-existing session.

    Returns:
        List of adapter dicts.
    """
    from database.repositories.amorphous_repo import AmorphousCellRepository

    status_filter = "ready" if visibility == "library" else None

    def _query(sess: Session) -> list[dict]:
        repo = AmorphousCellRepository(sess)
        rows = repo.list_recent(status=status_filter, limit=limit)
        return [_db_row_to_adapter(row) for row in rows]

    if session is not None:
        return _query(session)

    from features.common.db import run_in_session

    return run_in_session(_query)
