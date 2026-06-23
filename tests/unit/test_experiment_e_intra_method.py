from types import SimpleNamespace

import pytest

from features.experiments.e_intra_method import resolve_experiment_e_intra_method


def _exp(*, metrics=None, metadata=None):
    return SimpleNamespace(metrics=metrics or [], metadata_json=metadata)


def test_resolve_experiment_e_intra_method_prefers_ced_metric_metadata():
    exp = _exp(
        metrics=[
            SimpleNamespace(
                metric_name="cohesive_energy_density",
                metadata_json={"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"},
            )
        ],
        metadata={"e_intra_method": "single_molecule_vacuum"},
    )

    method, origin, resolved_from = resolve_experiment_e_intra_method(exp)

    assert method == "single_molecule_vacuum_adaptive_cutoff"
    assert origin is None
    assert resolved_from == "metric:cohesive_energy_density"


def test_resolve_experiment_e_intra_method_normalizes_legacy_metadata_alias():
    exp = _exp(
        metadata={"ced_provenance": {"e_intra_method": "single_molecule_vacuum_extended_cutoff"}}
    )

    method, origin, resolved_from = resolve_experiment_e_intra_method(exp)

    assert method == "single_molecule_vacuum_adaptive_cutoff"
    assert origin is None
    assert resolved_from == "metadata:ced_provenance"


def test_resolve_experiment_e_intra_method_preserves_origin_separately():
    exp = _exp(
        metadata={
            "e_intra_method": "single_molecule_vacuum_adaptive_cutoff",
            "e_intra_method_origin": "scan_import",
        }
    )

    method, origin, resolved_from = resolve_experiment_e_intra_method(exp)

    assert method == "single_molecule_vacuum_adaptive_cutoff"
    assert origin == "scan_import"
    assert resolved_from == "metadata:experiment"


@pytest.mark.asyncio
async def test_list_experiments_filters_by_resolved_e_intra_method(db_session, sample_experiments):
    from database.models import ExperimentModel
    from features.experiments.query import list_experiments

    exp1 = db_session.query(ExperimentModel).filter_by(exp_id="exp_test_001").first()
    exp2 = db_session.query(ExperimentModel).filter_by(exp_id="exp_test_002").first()
    exp3 = db_session.query(ExperimentModel).filter_by(exp_id="exp_test_003").first()
    exp1.study_type = "single_molecule_vacuum"
    exp2.study_type = "single_molecule_vacuum"
    exp3.study_type = "single_molecule_vacuum"
    exp1.metadata_json = {"e_intra_method": "single_molecule_vacuum"}
    exp2.metadata_json = {"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"}
    exp3.metadata_json = {"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"}
    db_session.commit()

    result = await list_experiments(
        study_type="single_molecule_vacuum",
        status="completed",
        e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        limit=10,
    )

    assert result["filtered_total_count"] == 2
    assert result["total"] == 2
    assert {row["exp_id"] for row in result["experiments"]} == {"exp_test_002", "exp_test_003"}
    assert all(
        row["e_intra_method"] == "single_molecule_vacuum_adaptive_cutoff"
        for row in result["experiments"]
    )
