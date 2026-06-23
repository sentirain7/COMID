import pytest

from contracts.errors import ErrorCode, MetricError
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import ArrayMetricStorage, MetricResult
from database.models import ExperimentModel, MetricArrayArtifactModel
from database.repositories.metric_repo import MetricRepository


def _seed_experiment(db_session, exp_id: str = "exp_metric_phase2") -> None:
    db_session.add(
        ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="completed",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            temperature_K=298.0,
            pressure_atm=1.0,
            target_atoms=100000,
        )
    )
    db_session.commit()


def test_metric_repository_rejects_unknown_metric(db_session):
    _seed_experiment(db_session)
    repo = MetricRepository(db_session)

    with pytest.raises(MetricError) as exc_info:
        repo.create(
            exp_id="exp_metric_phase2",
            metric_name="unknown_metric_x",
            value=1.0,
            unit="arb",
            namespace="bulk_ff_gaff2",
        )

    assert exc_info.value.code == ErrorCode.UNKNOWN_METRIC


def test_metric_repository_rejects_unit_mismatch(db_session):
    _seed_experiment(db_session)
    repo = MetricRepository(db_session)

    with pytest.raises(MetricError) as exc_info:
        repo.create(
            exp_id="exp_metric_phase2",
            metric_name="density",
            value=1.0,
            unit="kg/m3",
            namespace="bulk_ff_gaff2",
        )

    assert exc_info.value.code == ErrorCode.UNIT_MISMATCH


def test_metric_repository_escape_hatch_allows_unregistered_metric(db_session):
    _seed_experiment(db_session)
    repo = MetricRepository(db_session)

    metric = repo.create(
        exp_id="exp_metric_phase2",
        metric_name="legacy_import_metric",
        value=2.5,
        unit="arb",
        namespace="bulk_ff_gaff2",
        allow_unregistered=True,
    )

    assert metric.metric_name == "legacy_import_metric"


def test_metric_repository_persists_layer_interface_provenance(db_session):
    _seed_experiment(db_session)
    repo = MetricRepository(db_session)

    metric = repo.create(
        exp_id="exp_metric_phase2",
        metric_name="adhesion_energy",
        value=55.0,
        unit="mJ/m2",
        namespace="layer",
        layer_index=1,
        interface_index=0,
        allow_unregistered=True,
    )
    db_session.commit()

    assert metric.layer_index == 1
    assert metric.interface_index == 0

    loaded = repo.get_by_name("exp_metric_phase2", "adhesion_energy", "layer")
    assert loaded is not None
    assert loaded.layer_index == 1
    assert loaded.interface_index == 0


def test_metrics_registry_marks_shear_modulus_non_trainable():
    registry = MetricsRegistry()
    definition = registry.get_definition("shear_modulus")

    assert definition.produced is False
    assert definition.trainable is False
    assert definition.llm_exposed is False


def test_metric_repository_tracks_array_artifact_ownership(db_session):
    _seed_experiment(db_session)
    repo = MetricRepository(db_session)

    repo.save(
        MetricResult(
            exp_id="exp_metric_phase2",
            metric_name="rdf_curve",
            value=None,
            unit="[angstrom, dimensionless]",
            namespace="bulk_ff_gaff2",
            array_storage=ArrayMetricStorage(
                file_path="/tmp/rdf_curve.parquet",
                file_hash="hash_rdf_001",
                shape=(100, 2),
                summary={"first_peak_r": 3.6},
            ),
        )
    )

    metric = repo.get_by_name("exp_metric_phase2", "rdf_curve", "bulk_ff_gaff2")
    assert metric is not None
    assert metric.array_artifact_id is not None

    artifact = db_session.get(MetricArrayArtifactModel, metric.array_artifact_id)
    assert artifact is not None
    assert artifact.content_hash == "hash_rdf_001"
    assert artifact.ref_count == 1

    deleted = repo.delete_for_experiment("exp_metric_phase2")
    assert deleted == 1
    assert (
        db_session.query(MetricArrayArtifactModel)
        .filter(MetricArrayArtifactModel.content_hash == "hash_rdf_001")
        .first()
        is None
    )
