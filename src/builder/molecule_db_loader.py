"""Unified MoleculeDB initialization loader.

Provides a single entry point for creating properly initialized MoleculeDB
instances with combined config (binder + single + additives).
"""

from __future__ import annotations

import logging
from typing import Any

from builder.molecule_db import MoleculeDB
from common.library_config import (
    get_asphalt_binder_config_path,
    load_combined_molecule_config,
)
from common.pathing import get_project_root

logger = logging.getLogger(__name__)


def create_molecule_db(*, allow_mock: bool = False) -> MoleculeDB:
    """Create MoleculeDB with combined config (binder + single + additives).

    Args:
        allow_mock: If True, fall back to mock molecules on any load failure
                    (missing files, empty config, YAML parse errors, .mol parse errors).
                    If False, raise RuntimeError on failure.

    Returns:
        Initialized MoleculeDB instance with additives loaded.

    Raises:
        RuntimeError: If loading fails and allow_mock is False.
    """
    db = MoleculeDB()
    config_path = get_asphalt_binder_config_path()
    base_dir = get_project_root() / "data" / "molecules"

    if not config_path.exists():
        if allow_mock:
            logger.warning(
                "asphalt_binder.yaml not found at %s, using mock molecules",
                config_path,
            )
            db.create_mock_molecules()
            return db
        raise RuntimeError(f"Molecule config not found: {config_path}")

    # Try loading combined config (may fail on YAML parse errors)
    try:
        combined = load_combined_molecule_config()
    except Exception as e:
        if allow_mock:
            logger.warning("Failed to load combined molecule config: %s, using mock molecules", e)
            db.create_mock_molecules()
            return db
        raise RuntimeError(f"Failed to load molecule config: {e}") from e

    if not combined.get("molecules") and not combined.get("additives"):
        if allow_mock:
            logger.warning("Empty molecule config, using mock molecules")
            db.create_mock_molecules()
            return db
        raise RuntimeError("Molecule config is empty (no molecules or additives)")

    # Try loading aging library (may fail on .mol parse errors, missing files, etc.)
    try:
        count = db.load_aging_library_from_config(config=combined, base_dir=base_dir)
    except Exception as e:
        if allow_mock:
            logger.warning("Failed to load aging library from config: %s, using mock molecules", e)
            db.create_mock_molecules()
            return db
        raise RuntimeError(f"Failed to load aging library: {e}") from e

    db._aging_config_path = config_path

    logger.info("Loaded %d molecules from aging library", count)
    return db


def load_combined_molecule_config_strict() -> dict[str, Any]:
    """Load combined molecule config with strict validation.

    Returns:
        Combined config dict with molecules and additives.

    Raises:
        RuntimeError: If config is missing or empty.
    """
    config_path = get_asphalt_binder_config_path()
    if not config_path.exists():
        raise RuntimeError(f"Molecule config not found: {config_path}")

    combined = load_combined_molecule_config()
    if not combined.get("molecules") and not combined.get("additives"):
        raise RuntimeError("Combined molecule config is empty")

    return combined
