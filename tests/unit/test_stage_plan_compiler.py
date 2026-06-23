"""Tests for canonical stage request resolution and compiled execution plans."""

import pytest

from api.schemas import EquilibrationSettingsRequest, StageDurationOverrideRequest, StageRequest
from contracts.errors import ContractError
from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
from features.experiments.validation import resolve_stage_requests
from features.jobs.progress import get_stage_info_with_overrides
from protocols.stage_plan_compiler import StagePlanCompiler, build_stage_plan_metadata


def test_resolve_stage_requests_filters_legacy_equilibration_overrides() -> None:
    resolved = resolve_stage_requests(
        stage_requests=None,
        stage_durations=[
            StageDurationOverrideRequest(stage_name="high_pressure_npt", duration_ps=250),
            StageDurationOverrideRequest(stage_name="npt_production", duration_ps=2400),
        ],
        equilibration_settings=EquilibrationSettingsRequest(
            enabled=True, high_pressure_npt_duration_ps=250
        ),
        run_tier=RunTier.SCREENING,
    )

    assert resolved.has_equilibration is True
    assert resolved.equilibration_settings is not None
    assert resolved.stage_duration_overrides is not None
    assert [o.stage_name for o in resolved.stage_duration_overrides] == ["npt_production"]


def test_resolve_stage_requests_uses_canonical_stage_requests() -> None:
    resolved = resolve_stage_requests(
        stage_requests=[
            StageRequest(
                stage_key="high_temp_nvt",
                enabled=True,
                duration_ps=150,
                params_override={"temperature_K": 650},
            ),
            StageRequest(
                stage_key="high_pressure_npt",
                enabled=True,
                duration_ps=275,
                params_override={"temperature_K": 650, "pressure_atm": 150},
            ),
            StageRequest(stage_key="npt_production", enabled=True, duration_ps=2500),
        ],
        stage_durations=None,
        equilibration_settings=None,
        run_tier=RunTier.SCREENING,
    )

    assert resolved.has_equilibration is True
    assert resolved.equilibration_settings is not None
    assert resolved.equilibration_settings.high_temp_nvt_temperature_K == 650
    assert resolved.equilibration_settings.high_pressure_npt_pressure_atm == 150
    assert [o.stage_name for o in resolved.stage_duration_overrides or []] == ["npt_production"]


def test_resolve_stage_requests_rejects_out_of_bounds_equilibration_params() -> None:
    with pytest.raises(ContractError):
        resolve_stage_requests(
            stage_requests=[
                StageRequest(
                    stage_key="high_temp_nvt",
                    enabled=True,
                    duration_ps=150,
                    params_override={"temperature_K": 2000},
                ),
                StageRequest(
                    stage_key="high_pressure_npt",
                    enabled=True,
                    duration_ps=275,
                    params_override={"temperature_K": 650, "pressure_atm": 150},
                ),
            ],
            stage_durations=None,
            equilibration_settings=None,
            run_tier=RunTier.SCREENING,
        )


def test_compiled_plan_drives_progress_boundaries() -> None:
    request = ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.SCREENING,
        study_type=StudyType.BULK,
        temperature_K=293.0,
        pressure_atm=1.0,
        data_file_path="/tmp/fake.data",
        equilibration_settings={
            "enabled": True,
            "high_temp_nvt_temperature_K": 600,
            "high_temp_nvt_duration_ps": 150,
            "high_pressure_npt_temperature_K": 600,
            "high_pressure_npt_pressure_atm": 120,
            "high_pressure_npt_duration_ps": 250,
        },
    )
    compiler = StagePlanCompiler()
    plan = compiler.compile(request)

    info = get_stage_info_with_overrides(
        "screening",
        150_000,
        overrides=None,
        has_equilibration=True,
        compiled_plan=plan.model_dump(),
    )

    assert plan.total_steps == 2_700_000
    assert info["current_stage"] == "high_pressure_npt"
    assert info["stage_index"] == 3


def test_build_stage_plan_metadata_persists_plan() -> None:
    request = ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.SCREENING,
        study_type=StudyType.BULK,
        temperature_K=293.0,
        pressure_atm=1.0,
        data_file_path="/tmp/fake.data",
    )

    metadata = build_stage_plan_metadata(
        protocol_request=request,
        overrides=None,
        canonical_stage_requests=[{"stage_key": "npt_production", "enabled": True}],
        base_metadata={"source": "test"},
    )

    assert metadata["source"] == "test"
    assert metadata["chain_key"] == "screening"
    assert metadata["compiled_execution_plan"]["plan_hash"]
    assert metadata["stage_requests"] == [{"stage_key": "npt_production", "enabled": True}]
