#!/usr/bin/env python3
# ruff: noqa: E402
"""Backfill typed experiment contract fields from legacy sources.

Default mode is dry-run. Use ``--apply`` to persist changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from common.pathing import exp_id_to_material_id
from contracts.policies.forcefield import get_ff_display_label
from database.connection import session_scope
from database.models import ExperimentConditionModel, ExperimentModel
from orchestrator.exp_id_helper import parse_material_id

ALLOWED_CONDITION_KEYS = {
    "boundary_mode",
    "aggregate_material",
    "aggregate_surface",
    "layer_count",
    "interface_gap_angstrom",
    "loading_mode",
    "planner_origin",
    "selection_context",
}

CORE_CONDITION_KEYS = {
    "material_id",
    "binder_type",
    "structure_size",
    "aging_state",
    "force_field_name",
    "force_field_version",
    "failure_category",
    "tensile_strain_rate_1_per_ps",
    "tensile_pull_velocity_a_per_fs",
    "shear_rate_1_per_ps",
}


@dataclass(slots=True)
class BackfillStats:
    scanned: int = 0
    updated_rows: int = 0
    updated_fields: int = 0
    inserted_conditions: int = 0
    untouched: int = 0
    inferred_legacy: int = 0
    unresolved: list[str] = field(default_factory=list)


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _nested(payload: Any, *path: str) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _coerce_number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _build_condition_payload(key: str, value: Any, source: str) -> dict[str, Any] | None:
    if key not in ALLOWED_CONDITION_KEYS:
        return None
    if key in CORE_CONDITION_KEYS:
        return None
    if value in (None, "", [], {}):
        return None

    number = _coerce_number(value)
    if number is not None and not isinstance(value, bool):
        return {
            "condition_key": key,
            "value_type": "number",
            "value_number": number,
            "value_text": None,
            "value_bool": None,
            "value_json": None,
            "unit": "angstrom" if key == "interface_gap_angstrom" else None,
            "source": source,
        }

    boolean = _coerce_bool(value)
    if boolean is not None:
        return {
            "condition_key": key,
            "value_type": "bool",
            "value_number": None,
            "value_text": None,
            "value_bool": boolean,
            "value_json": None,
            "unit": None,
            "source": source,
        }

    if isinstance(value, (dict, list)):
        return {
            "condition_key": key,
            "value_type": "json",
            "value_number": None,
            "value_text": None,
            "value_bool": None,
            "value_json": value,
            "unit": None,
            "source": source,
        }

    return {
        "condition_key": key,
        "value_type": "text",
        "value_number": None,
        "value_text": str(value),
        "value_bool": None,
        "value_json": None,
        "unit": None,
        "source": source,
    }


def _iter_candidate_conditions(exp: ExperimentModel) -> Iterable[dict[str, Any]]:
    metadata = exp.metadata_json or {}
    build = exp.build_result_json or {}
    protocol = exp.protocol_result_json or {}
    lammps = exp.lammps_result_json or {}

    for key in sorted(ALLOWED_CONDITION_KEYS):
        value = _first_nonempty(
            _nested(protocol, key),
            _nested(build, key),
            _nested(lammps, key),
            metadata.get(key),
        )
        payload = _build_condition_payload(key, value, source="legacy_backfill")
        if payload:
            yield payload


def _backfill_core_fields(exp: ExperimentModel) -> tuple[dict[str, Any], bool]:
    metadata = exp.metadata_json or {}
    build = exp.build_result_json or {}
    protocol = exp.protocol_result_json or {}
    lammps = exp.lammps_result_json or {}

    material_id = _first_nonempty(exp.material_id, metadata.get("material_id"))
    if not material_id:
        material_id = exp_id_to_material_id(str(exp.exp_id or "")) or None

    binder_type = _first_nonempty(exp.binder_type, metadata.get("binder_type"))
    structure_size = _first_nonempty(exp.structure_size, metadata.get("structure_size"))
    aging_state = _first_nonempty(exp.aging_state, metadata.get("aging_state"))

    parsed_binder, parsed_size, parsed_aging = (None, None, None)
    if material_id:
        parsed_binder, parsed_size, parsed_aging = parse_material_id(str(material_id))

    tensile_spec = _first_nonempty(
        _nested(lammps, "tensile_spec"),
        _nested(protocol, "tensile_spec"),
        metadata.get("tensile_spec"),
        {},
    )
    shear_spec = _first_nonempty(
        _nested(lammps, "shear_spec"),
        _nested(protocol, "shear_spec"),
        metadata.get("shear_spec"),
        {},
    )

    updates = {
        "material_id": _first_nonempty(material_id),
        "binder_type": _first_nonempty(binder_type, parsed_binder),
        "structure_size": _first_nonempty(structure_size, parsed_size),
        "aging_state": _first_nonempty(aging_state, parsed_aging),
        "force_field_name": _first_nonempty(
            exp.force_field_name,
            metadata.get("force_field_name"),
            get_ff_display_label(str(exp.ff_type or "bulk_ff_gaff2")),
        ),
        "force_field_version": _first_nonempty(
            exp.force_field_version,
            metadata.get("force_field_version"),
            _nested(build, "force_field_version"),
            _nested(protocol, "force_field_version"),
        ),
        "failure_category": _first_nonempty(
            exp.failure_category,
            metadata.get("failure_category"),
            _nested(lammps, "failure_category"),
        ),
        "tensile_strain_rate_1_per_ps": _first_nonempty(
            exp.tensile_strain_rate_1_per_ps,
            metadata.get("tensile_strain_rate_1_per_ps"),
            _nested(tensile_spec, "strain_rate_1_per_ps"),
        ),
        "tensile_pull_velocity_a_per_fs": _first_nonempty(
            exp.tensile_pull_velocity_a_per_fs,
            metadata.get("tensile_pull_velocity_a_per_fs"),
            _nested(tensile_spec, "pull_velocity_A_per_fs"),
        ),
        "shear_rate_1_per_ps": _first_nonempty(
            exp.shear_rate_1_per_ps,
            metadata.get("shear_rate_1_per_ps"),
            _nested(shear_spec, "shear_rate_1_per_ps"),
        ),
    }

    inferred = any(
        updates[name] is not None and getattr(exp, name) in (None, "")
        for name in ("material_id", "binder_type", "structure_size", "aging_state")
    )
    return updates, inferred


def _upsert_conditions(exp: ExperimentModel, payloads: Iterable[dict[str, Any]], apply: bool) -> int:
    existing = {row.condition_key: row for row in exp.conditions}
    inserted = 0
    for payload in payloads:
        row = existing.get(payload["condition_key"])
        if row is None:
            if apply:
                exp.conditions.append(
                    ExperimentConditionModel(
                        condition_key=payload["condition_key"],
                        value_type=payload["value_type"],
                        value_number=payload["value_number"],
                        value_text=payload["value_text"],
                        value_bool=payload["value_bool"],
                        value_json=payload["value_json"],
                        unit=payload["unit"],
                        source=payload["source"],
                    )
                )
            inserted += 1
            continue

        changed = False
        for attr_name in (
            "value_type",
            "value_number",
            "value_text",
            "value_bool",
            "value_json",
            "unit",
            "source",
        ):
            if getattr(row, attr_name) != payload[attr_name]:
                changed = True
                if apply:
                    setattr(row, attr_name, payload[attr_name])
        if changed:
            inserted += 1
    return inserted


def run(*, apply: bool, limit: int | None) -> int:
    stats = BackfillStats()

    with session_scope() as session:
        query = session.query(ExperimentModel).order_by(ExperimentModel.id.asc())
        if limit:
            query = query.limit(limit)
        experiments = query.all()

        for exp in experiments:
            stats.scanned += 1
            updates, inferred = _backfill_core_fields(exp)
            field_changes = 0
            for field, value in updates.items():
                current = getattr(exp, field)
                if current != value and value is not None:
                    field_changes += 1
                    if apply:
                        setattr(exp, field, value)

            inserted_conditions = _upsert_conditions(
                exp,
                _iter_candidate_conditions(exp),
                apply,
            )

            if inferred:
                stats.inferred_legacy += 1
            if field_changes or inserted_conditions:
                stats.updated_rows += 1
                stats.updated_fields += field_changes
                stats.inserted_conditions += inserted_conditions
            else:
                stats.untouched += 1

            if updates["material_id"] is None:
                stats.unresolved.append(str(exp.exp_id))

        if not apply:
            session.rollback()

    print(json.dumps(asdict(stats), indent=2, ensure_ascii=False))
    if stats.unresolved:
        print("# unresolved_exp_ids")
        for exp_id in stats.unresolved[:20]:
            print(exp_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist updates instead of dry-run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of experiments")
    args = parser.parse_args()
    return run(apply=args.apply, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
