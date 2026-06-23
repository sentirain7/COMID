"""Central YAML config loader for molecule/crystal SSOT files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common.pathing import get_project_root


def get_molecule_data_dir() -> Path:
    return get_project_root() / "data" / "molecules"


def get_asphalt_binder_config_path() -> Path:
    return get_molecule_data_dir() / "asphalt_binder.yaml"


def get_single_moles_config_path() -> Path:
    return get_molecule_data_dir() / "single_moles.yaml"


def get_crystal_structures_config_path() -> Path:
    return get_molecule_data_dir() / "crystal_structures.yaml"


def get_additives_config_path() -> Path:
    return get_molecule_data_dir() / "additives.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    return dict(data or {})


def load_asphalt_binder_config() -> dict[str, Any]:
    path = get_asphalt_binder_config_path()
    return _load_yaml(path)


def load_single_moles_config() -> dict[str, Any]:
    path = get_single_moles_config_path()
    return _load_yaml(path)


def load_crystal_structures_config() -> dict[str, Any]:
    path = get_crystal_structures_config_path()
    data = _load_yaml(path)
    if data:
        return data
    return {
        "library": {"name": "crystal_structures"},
        "directory": "crystal_structures",
        "structures": [],
    }


def load_additives_config() -> dict[str, Any]:
    path = get_additives_config_path()
    return _load_yaml(path)


def get_ghg_inventory_path() -> Path:
    return get_molecule_data_dir() / "ghg_inventory.yaml"


def load_ghg_inventory() -> dict[str, Any]:
    return _load_yaml(get_ghg_inventory_path())


def load_combined_molecule_config() -> dict[str, Any]:
    """Build legacy-compatible molecule config from split SSOT files."""
    asphalt = load_asphalt_binder_config()
    single = load_single_moles_config()
    additives_cfg = load_additives_config()

    asphalt_molecules = list(asphalt.get("molecules", []))
    single_molecules = list(single.get("molecules", []))

    return {
        "library": {
            **dict(asphalt.get("library") or {}),
            "name": "molecule_library_combined",
        },
        "aging_categories": asphalt.get("aging_categories", {}),
        "sara_mapping": asphalt.get("sara_mapping", {}),
        "temperature_codes": asphalt.get("temperature_codes", {}),
        "file_pattern": asphalt.get("file_pattern"),
        "molecules": [*asphalt_molecules, *single_molecules],
        "binder_types": asphalt.get("binder_types", {}),
        "structure_sizes": asphalt.get("structure_sizes", {}),
        "additives": additives_cfg.get("additives", {}),
    }
