from contracts.schema_enums import AgingState, ExperimentStatus, FailureCategory, ValidityDomainTag
from contracts.schemas import (
    BuildResult,
    ExperimentConditionRecord,
    ExperimentRecord,
    FFType,
    LAMMPSRunResult,
    ProtocolResult,
    RunTier,
)
from database.repositories.experiment_repo import ExperimentRepository


def _build_result() -> BuildResult:
    return BuildResult(
        data_file_path="/tmp/data.lammps",
        actual_atoms=12345,
        actual_density=1.01,
        topology_hash="topo_hash_001",
        packmol_version="20.14.0",
        actual_composition_wt={
            "asphaltene": 21.0,
            "resin": 29.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        },
        composition_error_l1=0.2,
        target_composition_wt={
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        },
        initial_pe_per_atom=-5.4,
    )


def _protocol_result() -> ProtocolResult:
    return ProtocolResult(
        input_script_path="/tmp/in.lammps",
        expected_outputs=["log.lammps", "dump.lammpstrj"],
        estimated_steps=500000,
        protocol_hash="protocol_hash_001",
        stabilization_chain=["minimize", "nvt", "npt"],
    )


def _lammps_result() -> LAMMPSRunResult:
    return LAMMPSRunResult(
        success=True,
        log_file="/tmp/log.lammps",
        dump_files=["/tmp/dump.lammpstrj"],
        wall_time_seconds=123.4,
        exit_code=0,
        gpu_id_used=1,
        last_successful_step=500000,
    )


def test_experiment_record_roundtrip_persists_structured_fields(db_session):
    repo = ExperimentRepository(db_session)
    record = ExperimentRecord(
        exp_id="exp_roundtrip_phase1",
        material_id="AAA1_X2_short_aging",
        force_field_type=FFType.BULK_FF_GAFF2,
        force_field_name="GAFF2",
        force_field_version="2.11",
        study_type="bulk",
        run_tier=RunTier.SCREENING,
        temperature_k=313.0,
        pressure_atm=1.2,
        target_atoms=120000,
        tensile_strain_rate_1_per_ps=0.001,
        tensile_pull_velocity_a_per_fs=0.00025,
        shear_rate_1_per_ps=0.002,
        validity_domain_tag=[ValidityDomainTag.BULK_GAFF2_OK],
        selection_reason={"policy": "manual", "note": "phase1-roundtrip"},
        status=ExperimentStatus.COMPLETED,
        failure_category=FailureCategory.ENERGY_DRIFT,
        build_result=_build_result(),
        protocol_result=_protocol_result(),
        lammps_result=_lammps_result(),
        metadata={"source": "unit_test"},
        additive_type="SBS",
        additive_wt=4.5,
        additive_mol_id="SBS_unit",
        conditions=[
            ExperimentConditionRecord(
                condition_key="boundary_mode",
                value_text="periodic",
                source="unit_test",
            ),
            ExperimentConditionRecord(
                condition_key="interface_gap_angstrom",
                value_number=12.5,
                unit="angstrom",
                source="unit_test",
            ),
        ],
    )

    saved_exp_id = repo.save(record)
    assert saved_exp_id == record.exp_id

    loaded = repo.get(record.exp_id)
    assert loaded is not None
    assert loaded.material_id == "AAA1_X2_short_aging"
    assert loaded.binder_type == "AAA1"
    assert loaded.structure_size == "X2"
    assert loaded.aging_state == AgingState.SHORT_AGING
    assert loaded.force_field_version == "2.11"
    assert loaded.tensile_strain_rate_1_per_ps == 0.001
    assert loaded.tensile_pull_velocity_a_per_fs == 0.00025
    assert loaded.shear_rate_1_per_ps == 0.002
    assert loaded.failure_category == FailureCategory.ENERGY_DRIFT
    assert loaded.selection_reason == {"policy": "manual", "note": "phase1-roundtrip"}
    assert loaded.validity_domain_tag == [ValidityDomainTag.BULK_GAFF2_OK]
    assert loaded.build_result is not None
    assert loaded.build_result.topology_hash == "topo_hash_001"
    assert loaded.protocol_result is not None
    assert loaded.protocol_result.protocol_hash == "protocol_hash_001"
    assert loaded.lammps_result is not None
    assert loaded.lammps_result.log_file == "/tmp/log.lammps"
    assert len(loaded.conditions) == 2
    assert {row.condition_key for row in loaded.conditions} == {
        "boundary_mode",
        "interface_gap_angstrom",
    }

    raw = repo.get_by_id(record.exp_id)
    assert raw is not None
    assert raw.material_id == "AAA1_X2_short_aging"
    assert raw.binder_type == "AAA1"
    assert raw.structure_size == "X2"
    assert raw.aging_state == "short_aging"
    assert raw.force_field_name == "GAFF2"
    assert raw.build_result_json is not None
    assert raw.protocol_result_json is not None
    assert raw.lammps_result_json is not None
    assert raw.validity_domain_tags_json == ["bulk_gaff2_ok"]
    assert raw.selection_reason_json == {"policy": "manual", "note": "phase1-roundtrip"}
    assert len(raw.conditions) == 2


def test_experiment_record_derives_material_context_from_material_id(db_session):
    repo = ExperimentRepository(db_session)
    record = ExperimentRecord(
        exp_id="exp_material_context",
        material_id="AAK1_X3_long_aging",
        status=ExperimentStatus.QUEUED,
    )

    assert repo.save(record) == record.exp_id
    loaded = repo.get(record.exp_id)
    assert loaded is not None
    assert loaded.binder_type == "AAK1"
    assert loaded.structure_size == "X3"
    assert loaded.aging_state == AgingState.LONG_AGING
