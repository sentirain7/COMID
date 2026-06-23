#!/usr/bin/env python3
# ruff: noqa: E402
"""Read-only verification for DB/ML contract integrity."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from database.connection import session_scope
from database.models import (
    ExperimentConditionModel,
    ExperimentModel,
    MetricModel,
    MLModelVersionModel,
)

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

CAPABILITY_KEYS = {
    "supported_targets",
    "supported_temperature_range_k",
    "supported_binder_types",
    "supported_aging_states",
    "supported_additives",
    "ood_enabled",
    "uncertainty_enabled",
}


@dataclass(slots=True)
class VerificationSummary:
    total_experiments: int = 0
    completed_experiments: int = 0
    missing_material_id: int = 0
    missing_force_field_version: int = 0
    missing_mechanical_context: int = 0
    duplicate_core_conditions: int = 0
    invalid_metrics: int = 0
    mismatched_metric_units: int = 0
    mismatched_metric_namespaces: int = 0
    lineage_incomplete_models: int = 0
    capability_manifest_gaps: int = 0
    champion_count: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any contract violation counters are non-zero",
    )
    args = parser.parse_args()

    summary = VerificationSummary()

    with session_scope() as session:
        experiments = session.query(ExperimentModel).all()
        summary.total_experiments = len(experiments)
        summary.completed_experiments = sum(1 for exp in experiments if exp.status == "completed")
        summary.missing_material_id = sum(
            1 for exp in experiments if exp.status == "completed" and not exp.material_id
        )
        summary.missing_force_field_version = sum(
            1
            for exp in experiments
            if exp.status == "completed" and not exp.force_field_version
        )
        summary.missing_mechanical_context = sum(
            1
            for exp in experiments
            if exp.status == "completed"
            and exp.study_type in {"bulk", "layer_bulkff"}
            and exp.tensile_pull_velocity_a_per_fs is None
            and exp.shear_rate_1_per_ps is None
        )

        summary.duplicate_core_conditions = (
            session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.condition_key.in_(CORE_CONDITION_KEYS))
            .count()
        )

        metrics = session.query(MetricModel).all()
        for metric in metrics:
            definition = DEFAULT_METRICS_REGISTRY.get(metric.metric_name)
            if definition is None:
                summary.invalid_metrics += 1
                continue
            if metric.unit != definition.unit:
                summary.mismatched_metric_units += 1
            if metric.namespace != definition.namespace.value:
                summary.mismatched_metric_namespaces += 1

        models = session.query(MLModelVersionModel).all()
        summary.champion_count = sum(1 for row in models if row.status == "champion")
        for row in models:
            if not row.feature_schema_hash or not row.training_manifest_hash:
                summary.lineage_incomplete_models += 1
            manifest = row.capability_manifest_json or {}
            if any(key not in manifest for key in CAPABILITY_KEYS):
                summary.capability_manifest_gaps += 1

    payload = asdict(summary)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")

    if args.strict:
        violations = (
            summary.invalid_metrics
            + summary.mismatched_metric_units
            + summary.mismatched_metric_namespaces
            + summary.lineage_incomplete_models
            + summary.capability_manifest_gaps
        )
        if violations:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
