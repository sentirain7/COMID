"""Central stage metadata used by API responses and compiled execution plans."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as EQ_POLICY

_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "protocolStageCatalog.json"
)


def _load_catalog_payload() -> dict[str, Any]:
    with _CATALOG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _apply_equilibration_policy(
    stage_catalog: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog = deepcopy(stage_catalog)
    eq_bounds = {
        "temperature_K": {
            "min": EQ_POLICY.temperature_min_K,
            "max": EQ_POLICY.temperature_max_K,
        },
        "pressure_atm": {
            "min": EQ_POLICY.pressure_min_atm,
            "max": EQ_POLICY.pressure_max_atm,
        },
        "duration_ps": {
            "min": EQ_POLICY.duration_min_ps,
            "max": EQ_POLICY.duration_max_ps,
        },
    }

    high_temp = catalog["high_temp_nvt"]
    high_temp["bounds"] = deepcopy(eq_bounds)
    high_temp["default_duration_ps"] = EQ_POLICY.high_temp_nvt_duration_ps
    high_temp.setdefault("ui_metadata", {})["default_temperature_K"] = (
        EQ_POLICY.high_temp_nvt_temperature_K
    )

    high_pressure = catalog["high_pressure_npt"]
    high_pressure["bounds"] = deepcopy(eq_bounds)
    high_pressure["default_duration_ps"] = EQ_POLICY.high_pressure_npt_duration_ps
    high_pressure.setdefault("ui_metadata", {})["default_temperature_K"] = (
        EQ_POLICY.high_pressure_npt_temperature_K
    )
    high_pressure.setdefault("ui_metadata", {})["default_pressure_atm"] = (
        EQ_POLICY.high_pressure_npt_pressure_atm
    )

    return catalog


_CATALOG_PAYLOAD = _load_catalog_payload()
STAGE_CATALOG: dict[str, dict[str, Any]] = _apply_equilibration_policy(_CATALOG_PAYLOAD["stages"])
CHAIN_OPTIONAL_STAGE_KEYS: dict[str, list[str]] = deepcopy(
    _CATALOG_PAYLOAD["chains"]["optional_stage_keys_by_chain"]
)
BASE_STAGE_KEYS_BY_CHAIN: dict[str, list[str]] = deepcopy(
    _CATALOG_PAYLOAD["chains"]["base_stage_keys_by_chain"]
)
RUN_TIER_PRIORITY: dict[str, int] = deepcopy(_CATALOG_PAYLOAD["run_tier_priority"])


def get_stage_metadata(stage_name: str, *, synthetic_optional: bool = False) -> dict:
    """Return a defensive copy of per-stage UI/presentation metadata.

    Args:
        stage_name: Canonical stage key.
        synthetic_optional: Whether the stage is being surfaced as an optional
            selector rather than emitted from the resolved execution chain.

    Returns:
        Metadata dictionary safe for caller-side mutation.
    """
    metadata = deepcopy(STAGE_CATALOG.get(stage_name, {}))
    metadata.pop("type", None)
    metadata.pop("default_duration_ps", None)
    metadata.pop("default_duration_steps", None)
    if synthetic_optional:
        ui_metadata = dict(metadata.get("ui_metadata", {}))
        if ui_metadata.get("virtual_selector"):
            ui_metadata["virtual_selector"] = True
        metadata["ui_metadata"] = ui_metadata
    return metadata


def get_stage_defaults(stage_name: str) -> dict[str, Any]:
    """Return default duration/type data for a stage.

    Args:
        stage_name: Canonical stage key.

    Returns:
        Dictionary containing default duration/type fields safe for mutation.
    """
    metadata = STAGE_CATALOG.get(stage_name, {})
    return {
        "type": metadata.get("type"),
        "duration_ps": metadata.get("default_duration_ps"),
        "duration_steps": metadata.get("default_duration_steps"),
    }


def get_optional_stage_keys(chain_key: str) -> list[str]:
    """Return optional UI stage keys relevant to a chain key."""
    return list(CHAIN_OPTIONAL_STAGE_KEYS.get(chain_key, []))


def get_base_stage_keys(chain_key: str) -> list[str]:
    """Return base execution stage keys for a chain key."""
    return list(BASE_STAGE_KEYS_BY_CHAIN.get(chain_key, []))
