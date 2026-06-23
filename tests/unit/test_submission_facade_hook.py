from unittest.mock import MagicMock

import pytest

from contracts.schemas import BuildRequest, FFType, ProtocolRequest, RunTier, TensileSpec
from database.repositories.experiment_repo import ExperimentRepository
from database.repositories.layered_source_repo import LayeredSourceRepository
from orchestrator.submission_facade import SubmissionFacade


def _build_request():
    return BuildRequest(
        composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
        target_atoms=100000,
        seed=1,
    )


def _protocol_request():
    return ProtocolRequest(
        run_tier=RunTier.SCREENING,
        ff_type=FFType.BULK_FF_GAFF2,
        temperature_K=298.0,
        data_file_path="",
    )


def test_post_stub_hook_persists_related_rows_atomically(db_session):
    job_manager = MagicMock()
    job_manager.submit.return_value = "job-1"
    job_manager.get_task_id.return_value = "task-1"

    def _hook(session, exp_id: str) -> None:
        repo = LayeredSourceRepository(session)
        repo.create_sources(
            exp_id,
            [
                {
                    "layer_index": 0,
                    "source_type": "crystal_structure",
                    "source_id": "SiO2_001",
                }
            ],
        )

    SubmissionFacade.submit_experiment(
        job_manager=job_manager,
        exp_id="exp_hook_ok",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        target_atoms=100000,
        temperature_k=298.0,
        pressure_atm=1.0,
        seed=1,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        build_request=_build_request(),
        protocol_request=_protocol_request(),
        material_id="hook_test",
        post_stub_hook=_hook,
    )

    exp_repo = ExperimentRepository(db_session)
    exp = exp_repo.get_by_id("exp_hook_ok")
    assert exp is not None
    assert exp.celery_task_id == "task-1"

    layered_repo = LayeredSourceRepository(db_session)
    sources = layered_repo.get_sources("exp_hook_ok")
    assert len(sources) == 1
    assert sources[0].source_id == "SiO2_001"


def test_post_stub_hook_failure_rolls_back_stub_and_skips_submit(db_session):
    job_manager = MagicMock()
    job_manager.submit.return_value = "job-2"
    job_manager.get_task_id.return_value = "task-2"

    def _hook(_session, _exp_id: str) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        SubmissionFacade.submit_experiment(
            job_manager=job_manager,
            exp_id="exp_hook_fail",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            target_atoms=100000,
            temperature_k=298.0,
            pressure_atm=1.0,
            seed=1,
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            build_request=_build_request(),
            protocol_request=_protocol_request(),
            material_id="hook_test",
            post_stub_hook=_hook,
        )

    job_manager.submit.assert_not_called()
    exp_repo = ExperimentRepository(db_session)
    assert exp_repo.get_by_id("exp_hook_fail") is None

    layered_repo = LayeredSourceRepository(db_session)
    assert layered_repo.get_sources("exp_hook_fail") == []


def test_submission_facade_persists_material_and_tensile_context(db_session):
    job_manager = MagicMock()
    job_manager.submit.return_value = "job-phase1"
    job_manager.get_task_id.return_value = "task-phase1"

    protocol_request = ProtocolRequest(
        run_tier=RunTier.SCREENING,
        ff_type=FFType.BULK_FF_GAFF2,
        temperature_K=298.0,
        data_file_path="",
        tensile_spec=TensileSpec(enabled=True, pull_velocity_A_per_fs=0.00015),
    )

    SubmissionFacade.submit_experiment(
        job_manager=job_manager,
        exp_id="exp_phase1_context",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        target_atoms=100000,
        temperature_k=298.0,
        pressure_atm=1.0,
        seed=7,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        build_request=_build_request(),
        protocol_request=protocol_request,
        material_id="AAA1_X3_long_aging",
    )

    exp_repo = ExperimentRepository(db_session)
    exp = exp_repo.get_by_id("exp_phase1_context")
    assert exp is not None
    assert exp.material_id == "AAA1_X3_long_aging"
    assert exp.binder_type == "AAA1"
    assert exp.structure_size == "X3"
    assert exp.aging_state == "long_aging"
    assert exp.force_field_name == "GAFF2"
    assert exp.force_field_version == "2.11"  # registry.yaml canonical version
    assert exp.tensile_pull_velocity_a_per_fs == 0.00015
    assert exp.celery_task_id == "task-phase1"


def test_submission_facade_uses_composition_and_additive_for_ff_provenance(db_session, monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_collect(mol_ids, additive_ids):
        captured["mol_ids"] = list(mol_ids)
        captured["additive_ids"] = list(additive_ids)
        return [
            {
                "mol_id": "mol-a",
                "source_id": "mol-a",
                "generator": "antechamber_am1bcc",
                "generation_profile": "baseline",
            },
            {
                "mol_id": "ADD-X",
                "source_id": "ADD-X",
                "generator": "antechamber_am1bcc",
                "generation_profile": "sqm_robust",
            },
        ]

    monkeypatch.setattr("forcefield.eligibility.collect_organic_source_provenance", fake_collect)

    job_manager = MagicMock()
    job_manager.submit.return_value = "job-ff-prov"
    job_manager.get_task_id.return_value = "task-ff-prov"
    build_request = BuildRequest(
        composition={"mol-a": 2, "mol-b": 1},
        composition_mode="mol_count",
        target_atoms=100,
        seed=11,
    )

    SubmissionFacade.submit_experiment(
        job_manager=job_manager,
        exp_id="exp_ff_prov",
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        target_atoms=100,
        temperature_k=298.0,
        pressure_atm=1.0,
        seed=11,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        build_request=build_request,
        protocol_request=_protocol_request(),
        material_id="ff_prov_test",
        additive_type="polymer",
        additive_mol_id="ADD-X",
    )

    assert captured == {"mol_ids": ["mol-a", "mol-b"], "additive_ids": ["ADD-X"]}
    exp = ExperimentRepository(db_session).get_by_id("exp_ff_prov")
    assert exp is not None
    assert (exp.metadata_json or {})["ff_provenance"]["stack_id"] == "gaff2_am1bcc_v1"
