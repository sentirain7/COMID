import sys
from datetime import datetime

import pytest

sys.path.insert(0, "src")

from api.schemas import CampaignCreateRequest, CampaignWaveSubmitRequest
from contracts.schema_enums import CampaignStatus
from database.connection import close_db, init_memory_db
from database.models import AdditiveCatalogModel, ExperimentModel
from features.campaign import service as campaign_service
from orchestrator.batch_job_binder_cell import BatchJobBinderCellJob, BatchJobBinderCellResult


@pytest.fixture
def memory_db():
    session = init_memory_db()
    session.add_all(
        [
            AdditiveCatalogModel(
                mol_id="PPA",
                name="PPA",
                category="polymer",
                default_counts={"X1": 2, "X2": 4, "X3": 6},
            ),
            AdditiveCatalogModel(
                mol_id="SBS",
                name="SBS",
                category="polymer",
                default_counts={"X1": 2, "X2": 4, "X3": 6},
            ),
        ]
    )
    session.commit()
    yield session
    session.close()
    close_db()


def _make_experiment(exp_id: str, status: str) -> ExperimentModel:
    return ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status=status,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        target_atoms=1000,
        temperature_K=298.0,
        pressure_atm=1.0,
        seed=1,
        created_at=datetime.utcnow(),
    )


def test_submit_wave_and_progress(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service,
        "get_aging_config",
        lambda: {"binder_types": {"AAA1": {}, "AAK1": {}}},
    )

    def _fake_submit(session, spec):
        session.add(_make_experiment("exp-wave1-001", "queued"))
        session.add(_make_experiment("exp-wave1-002", "completed"))
        session.flush()
        return BatchJobBinderCellResult(
            batch_job_id="batch-wave1",
            jobs=[
                BatchJobBinderCellJob(
                    exp_id="exp-wave1-001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    seed=1,
                    status="submitted",
                ),
                BatchJobBinderCellJob(
                    exp_id="exp-wave1-002",
                    binder_type="AAK1",
                    structure_size="X1",
                    temperature_k=313.0,
                    aging_state="non_aging",
                    tier="screening",
                    seed=1,
                    status="duplicate",
                ),
            ],
            total=2,
            new=1,
            duplicates=1,
            submitted=1,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_submit)

    wave = campaign_service.submit_wave(CampaignWaveSubmitRequest(campaign_name="pilot", wave_no=1))
    assert wave.total_jobs == 2
    assert wave.submitted_jobs == 1
    assert wave.duplicate_jobs == 1
    assert wave.experiment_counts["queued"] == 1
    assert wave.experiment_counts["completed"] == 1

    progress = campaign_service.get_progress(wave.campaign_id)
    assert progress.name == "pilot"
    assert progress.total_waves == 1
    assert progress.total_experiments == 2
    assert progress.completed_experiments == 1


def test_wave3_requires_additive_types(memory_db):
    with pytest.raises(Exception, match="Wave 3 requires additive_types"):
        campaign_service.submit_wave(CampaignWaveSubmitRequest(campaign_name="pilot", wave_no=3))


def test_wave2_uses_additive_doe_defaults(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    seen = {}

    def _fake_submit(session, spec):
        seen["spec"] = spec
        return BatchJobBinderCellResult(
            batch_job_id="batch-wave2",
            jobs=[],
            total=0,
            new=0,
            duplicates=0,
            submitted=0,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_submit)

    wave = campaign_service.submit_wave(CampaignWaveSubmitRequest(campaign_name="pilot", wave_no=2))

    assert wave.wave_no == 2
    assert seen["spec"].binder_types == ["AAA1"]
    assert seen["spec"].temperatures_k == [293.0, 313.0]
    assert seen["spec"].additive_types
    assert seen["spec"].additive_concentrations == [2.0, 5.0, 8.0]


def test_wave4_uses_requested_additive_types(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    seen = {}

    def _fake_submit(session, spec):
        seen["spec"] = spec
        return BatchJobBinderCellResult(
            batch_job_id="batch-wave4",
            jobs=[],
            total=0,
            new=0,
            duplicates=0,
            submitted=0,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_submit)

    wave = campaign_service.submit_wave(
        CampaignWaveSubmitRequest(
            campaign_name="pilot",
            wave_no=4,
            additive_types=["PPA", "SBS"],
        )
    )

    assert wave.wave_no == 4
    assert seen["spec"].binder_types == ["AAA1"]
    assert seen["spec"].aging_states == ["non_aging", "short_aging"]
    assert seen["spec"].additive_types == ["PPA", "SBS"]


def test_create_list_and_detail_campaign(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    created = campaign_service.create_campaign(
        CampaignCreateRequest(name="pilot", description="seed run")
    )
    assert created.name == "pilot"
    assert created.wave_count == 0
    assert created.status == "draft"

    def _fake_submit(session, spec):
        session.add(_make_experiment("exp-wave-summary-001", "completed"))
        session.flush()
        return BatchJobBinderCellResult(
            batch_job_id="batch-summary",
            jobs=[
                BatchJobBinderCellJob(
                    exp_id="exp-wave-summary-001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    seed=1,
                    status="submitted",
                )
            ],
            total=1,
            new=1,
            duplicates=0,
            submitted=1,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_submit)

    wave = campaign_service.submit_wave(
        CampaignWaveSubmitRequest(
            campaign_id=created.campaign_id,
            campaign_name=created.name,
            wave_no=1,
        )
    )
    assert wave.campaign_id == created.campaign_id

    listing = campaign_service.list_campaigns()
    assert any(item.campaign_id == created.campaign_id for item in listing.campaigns)
    assert listing.total >= 1

    detail = campaign_service.get_campaign_detail(created.campaign_id)
    assert detail.campaign_id == created.campaign_id
    assert detail.wave_count == 1
    assert detail.total_experiments == 1

    filtered = campaign_service.list_campaigns(
        status=CampaignStatus.COMPLETED,
        limit=10,
        offset=0,
    )
    assert filtered.total == 1
    assert [item.campaign_id for item in filtered.campaigns] == [created.campaign_id]


def test_list_campaigns_supports_offset_and_limit(memory_db):
    first = campaign_service.create_campaign(CampaignCreateRequest(campaign_id="camp-a", name="A"))
    second = campaign_service.create_campaign(CampaignCreateRequest(campaign_id="camp-b", name="B"))

    paged = campaign_service.list_campaigns(limit=1, offset=1)

    assert paged.total == 2
    assert paged.limit == 1
    assert paged.offset == 1
    assert len(paged.campaigns) == 1
    assert paged.campaigns[0].campaign_id in {first.campaign_id, second.campaign_id}


def test_list_campaigns_filters_by_derived_completed_status(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    def _fake_submit(session, spec):
        session.add(_make_experiment("exp-wave-complete-001", "completed"))
        session.flush()
        return BatchJobBinderCellResult(
            batch_job_id="batch-complete",
            jobs=[
                BatchJobBinderCellJob(
                    exp_id="exp-wave-complete-001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    seed=1,
                    status="submitted",
                )
            ],
            total=1,
            new=1,
            duplicates=0,
            submitted=1,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_submit)

    created = campaign_service.create_campaign(CampaignCreateRequest(name="completed-campaign"))
    campaign_service.submit_wave(
        CampaignWaveSubmitRequest(
            campaign_id=created.campaign_id,
            campaign_name=created.name,
            wave_no=1,
        )
    )

    completed = campaign_service.list_campaigns(status=CampaignStatus.COMPLETED, limit=10, offset=0)

    assert completed.total == 1
    assert [item.campaign_id for item in completed.campaigns] == [created.campaign_id]


def test_submit_wave_rejects_unknown_binder(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    with pytest.raises(Exception, match="Invalid binder_type"):
        campaign_service.submit_wave(
            CampaignWaveSubmitRequest(
                campaign_name="pilot",
                wave_no=1,
                binder_types=["ZZZ9"],
            )
        )


def test_submit_wave_rejects_unknown_additive(memory_db, monkeypatch):
    monkeypatch.setattr(
        campaign_service, "get_aging_config", lambda: {"binder_types": {"AAA1": {}}}
    )

    with pytest.raises(Exception, match="Invalid additive mol_id"):
        campaign_service.submit_wave(
            CampaignWaveSubmitRequest(
                campaign_name="pilot",
                wave_no=4,
                additive_types=["UNKNOWN_ADD"],
            )
        )
