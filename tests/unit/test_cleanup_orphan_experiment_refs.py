"""Tests for orphan experiment reference cleanup helpers."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

# scripts/ is not a package — load the script module directly from its path.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_orphan_experiment_refs.py"
_MODULE_SPEC = importlib.util.spec_from_file_location(
    "cleanup_orphan_experiment_refs_test_module", _SCRIPT_PATH
)
assert _MODULE_SPEC and _MODULE_SPEC.loader
cleanup_orphan_experiment_refs = importlib.util.module_from_spec(_MODULE_SPEC)
_MODULE_SPEC.loader.exec_module(cleanup_orphan_experiment_refs)
cleanup_metrics_with_fk_reconciliation = (
    cleanup_orphan_experiment_refs.cleanup_metrics_with_fk_reconciliation
)


def _create_experiment(db_session, exp_id: str):
    from database.models import ExperimentModel

    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
    )
    db_session.add(exp)
    db_session.flush()
    return exp


def test_metrics_cleanup_reports_fk_mismatches_without_auto_attaching(db_session):
    """PK reuse-like metric states should be unresolved, not silently recovered."""
    from database.models import MetricModel

    exp_a = _create_experiment(db_session, "exp-a")
    exp_b = _create_experiment(db_session, "exp-b")
    db_session.commit()

    db_session.execute(text("PRAGMA foreign_keys=OFF"))
    invalid_pk = max(exp_a.id, exp_b.id) + 1000
    db_session.add_all(
        [
            MetricModel(
                exp_id="exp-a",
                experiment_id=None,
                metric_name="missing_pk",
                namespace="test",
                unit="u",
                value=1.0,
            ),
            MetricModel(
                exp_id="exp-a",
                experiment_id=invalid_pk,
                metric_name="valid_exp_invalid_pk",
                namespace="test",
                unit="u",
                value=1.0,
            ),
            MetricModel(
                exp_id="exp-a",
                experiment_id=exp_b.id,
                metric_name="valid_exp_wrong_pk",
                namespace="test",
                unit="u",
                value=1.0,
            ),
            MetricModel(
                exp_id="stale-exp",
                experiment_id=exp_a.id,
                metric_name="stale_exp_valid_pk",
                namespace="test",
                unit="u",
                value=1.0,
            ),
            MetricModel(
                exp_id="orphan-exp",
                experiment_id=None,
                metric_name="true_orphan",
                namespace="test",
                unit="u",
                value=1.0,
            ),
        ]
    )
    db_session.flush()

    result = cleanup_metrics_with_fk_reconciliation(
        db_session,
        {"exp-a", "exp-b"},
        {exp_a.id, exp_b.id},
        apply=False,
        verbose=False,
    )

    assert result["recovered"] == 1
    assert result["deleted"] == 1
    assert result["unresolved"] == 3
