"""Result sidecar round-trip: write-through -> import recreates DB results.

The autouse ``_isolate_sidecars`` fixture (conftest) redirects the sidecar dir
to a per-test tmp path, so these never touch the real git-tracked sidecars.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import (
    Base,
    ExperimentModel,
    MetricModel,
    MoleculeModel,
)
from features.common.result_sidecar import (
    import_sidecars_to_db,
    read_sidecar,
    write_experiment_sidecar,
)


def _fresh_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def _seed_experiment(session: Session) -> str:
    exp = ExperimentModel(
        exp_id="A1_X1_NA_none_293K_test01",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        study_type="bulk",
        material_id="AAA1",
        binder_type="AAA1",
        temperature_K=293.0,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
    )
    session.add(exp)
    mol = MoleculeModel(
        mol_id="U-AS-Thio-0293", smiles="c1ccsc1", name="Thio", sara_type="asphaltene"
    )
    session.add(mol)
    session.flush()
    # one scalar metric + one array-curve metric (registered names)
    session.add(
        MetricModel(
            experiment_id=exp.id,
            exp_id=exp.exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=0.95,
            unit="g/cm3",
        )
    )
    session.add(
        MetricModel(
            experiment_id=exp.id,
            exp_id=exp.exp_id,
            metric_name="cohesive_energy_density",
            namespace="bulk_ff_gaff2",
            value=350.0,
            unit="MJ/m3",
        )
    )
    session.commit()
    return exp.exp_id


def test_write_through_then_import_recreates_results():
    src = _fresh_session()
    exp_id = _seed_experiment(src)

    assert write_experiment_sidecar(src, exp_id) is True

    # The sidecar carries metadata + metrics, no machine-specific fields.
    doc = read_sidecar(exp_id)
    assert doc is not None
    assert doc["exp_id"] == exp_id
    assert doc["experiment"]["binder_type"] == "AAA1"
    assert doc["experiment"]["temperature_K"] == 293.0
    assert "id" not in doc["experiment"]  # no int PK leaked
    names = {m["metric_name"] for m in doc["metrics"]}
    assert {"density", "cohesive_energy_density"} <= names

    # A different machine (fresh DB) imports the sidecar and gets the results back.
    dst = _fresh_session()
    counts = import_sidecars_to_db(dst)
    dst.commit()
    assert counts["experiments"] == 1
    assert counts["metrics"] >= 2

    exp = dst.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
    assert exp is not None and exp.binder_type == "AAA1"
    ced = (
        dst.query(MetricModel)
        .filter(
            MetricModel.exp_id == exp_id,
            MetricModel.metric_name == "cohesive_energy_density",
        )
        .first()
    )
    assert ced is not None and ced.value == 350.0


def test_write_through_disabled_is_noop(monkeypatch):
    from contracts.policies.result_export import ResultExportPolicy

    monkeypatch.setattr(
        "features.common.result_sidecar.DEFAULT_RESULT_EXPORT_POLICY",
        ResultExportPolicy(enabled=False),
    )
    src = _fresh_session()
    exp_id = _seed_experiment(src)
    # enabled=False -> no sidecar written (byte-identical to pre-feature behaviour)
    assert write_experiment_sidecar(src, exp_id) is False
    assert read_sidecar(exp_id) is None
