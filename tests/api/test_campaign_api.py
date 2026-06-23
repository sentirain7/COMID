"""API contract tests for campaign routes."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

import pytest
from pydantic import TypeAdapter

sys.path.insert(0, "src")

from api.schemas import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignProgressResponse,
    CampaignWaveStatusResponse,
    CampaignWaveSubmitRequest,
)
from contracts.schema_enums import CampaignStatus
from features.campaign.router import (
    create_campaign,
    get_campaign_detail,
    get_campaign_progress,
    list_campaigns,
    submit_campaign_wave,
)


@pytest.mark.asyncio
async def test_submit_campaign_wave_contract(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.submit_wave",
        lambda request: {
            "campaign_id": "camp-1",
            "wave_id": 1,
            "wave_no": request.wave_no,
            "status": "submitted",
            "total_jobs": 15,
            "new_jobs": 15,
            "duplicate_jobs": 0,
            "submitted_jobs": 15,
            "error_jobs": 0,
            "experiment_counts": {"queued": 15},
            "spec": {"binder_types": ["AAA1"]},
            "submitted_at": "2026-03-11T00:00:00+00:00",
        },
    )

    payload = await submit_campaign_wave(CampaignWaveSubmitRequest(wave_no=1))
    validated = CampaignWaveStatusResponse.model_validate(payload)
    assert validated.total_jobs == 15
    assert validated.experiment_counts["queued"] == 15


@pytest.mark.asyncio
async def test_campaign_progress_contract(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.get_progress",
        lambda campaign_id=None: {
            "campaign_id": campaign_id or "camp-1",
            "name": "pilot",
            "status": "running",
            "total_waves": 1,
            "total_experiments": 15,
            "completed_experiments": 3,
            "waves": [
                {
                    "campaign_id": "camp-1",
                    "wave_id": 1,
                    "wave_no": 1,
                    "status": "running",
                    "total_jobs": 15,
                    "new_jobs": 15,
                    "duplicate_jobs": 0,
                    "submitted_jobs": 15,
                    "error_jobs": 0,
                    "experiment_counts": {"completed": 3, "queued": 12},
                    "spec": {"binder_types": ["AAA1"]},
                    "submitted_at": "2026-03-11T00:00:00+00:00",
                }
            ],
        },
    )

    payload = await get_campaign_progress("camp-1")
    validated = TypeAdapter(CampaignProgressResponse).validate_python(payload)
    assert validated.total_experiments == 15
    assert validated.waves[0].experiment_counts["completed"] == 3


@pytest.mark.asyncio
async def test_create_campaign_contract(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.create_campaign",
        lambda request: {
            "campaign_id": request.campaign_id or "camp-new",
            "name": request.name,
            "status": "draft",
            "wave_count": 0,
            "total_experiments": 0,
            "completed_experiments": 0,
            "waves": [],
            "created_at": "2026-03-11T00:00:00+00:00",
        },
    )

    payload = await create_campaign(CampaignCreateRequest(name="pilot"))
    validated = CampaignDetailResponse.model_validate(payload)
    assert validated.campaign_id == "camp-new"
    assert validated.wave_count == 0


@pytest.mark.asyncio
async def test_list_campaigns_contract(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.list_campaigns",
        lambda status=None, limit=50, offset=0: {
            "campaigns": [
                {
                    "campaign_id": "camp-1",
                    "name": "pilot",
                    "status": "running",
                    "wave_count": 2,
                    "total_experiments": 30,
                    "completed_experiments": 10,
                }
            ],
            "total": 1,
            "limit": limit,
            "offset": offset,
            "status_filter": status,
        },
    )

    payload = await list_campaigns()
    validated = CampaignListResponse.model_validate(payload)
    assert validated.campaigns[0].campaign_id == "camp-1"
    assert validated.campaigns[0].status == "running"
    assert validated.total == 1


@pytest.mark.asyncio
async def test_list_campaigns_contract_with_filters(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.list_campaigns",
        lambda status=None, limit=50, offset=0: {
            "campaigns": [],
            "total": 3,
            "limit": limit,
            "offset": offset,
            "status_filter": status,
        },
    )

    payload = await list_campaigns(status=CampaignStatus.ACTIVE, limit=10, offset=5)
    validated = CampaignListResponse.model_validate(payload)
    assert validated.total == 3
    assert validated.limit == 10
    assert validated.offset == 5
    assert validated.status_filter == CampaignStatus.ACTIVE


@pytest.mark.asyncio
async def test_campaign_detail_contract(monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.get_campaign_detail",
        lambda campaign_id: {
            "campaign_id": campaign_id,
            "name": "pilot",
            "status": "active",
            "wave_count": 1,
            "total_experiments": 15,
            "completed_experiments": 3,
            "waves": [
                {
                    "campaign_id": campaign_id,
                    "wave_id": 1,
                    "wave_no": 1,
                    "status": "running",
                    "total_jobs": 15,
                    "new_jobs": 15,
                    "duplicate_jobs": 0,
                    "submitted_jobs": 15,
                    "error_jobs": 0,
                    "experiment_counts": {"completed": 3, "queued": 12},
                    "spec": {"binder_types": ["AAA1"]},
                    "submitted_at": "2026-03-11T00:00:00+00:00",
                }
            ],
            "created_at": "2026-03-11T00:00:00+00:00",
        },
    )

    payload = await get_campaign_detail("camp-1")
    validated = CampaignDetailResponse.model_validate(payload)
    assert validated.campaign_id == "camp-1"
    assert validated.waves[0].status == "running"


TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient


@pytest.fixture()
def client():
    from api.application import app

    @asynccontextmanager
    async def _lifespan(_app):
        yield

    app.router.lifespan_context = _lifespan
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_progress_route_not_shadowed_by_campaign_detail(client, monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.get_progress",
        lambda campaign_id=None: {
            "campaign_id": campaign_id or "camp-1",
            "name": "pilot",
            "status": "running",
            "total_waves": 1,
            "total_experiments": 15,
            "completed_experiments": 3,
            "waves": [],
        },
    )
    monkeypatch.setattr(
        "features.campaign.service.get_campaign_detail",
        lambda campaign_id: {
            "campaign_id": campaign_id,
            "name": "detail-route",
            "status": "draft",
            "wave_count": 0,
            "total_experiments": 0,
            "completed_experiments": 0,
            "waves": [],
            "created_at": "2026-03-11T00:00:00+00:00",
        },
    )

    response = client.get("/campaigns/progress", params={"campaign_id": "camp-1"})
    assert response.status_code == 200
    data = response.json()
    assert data["campaign_id"] == "camp-1"
    assert data["name"] == "pilot"
    assert "total_waves" in data


def test_campaign_list_route_accepts_filter_and_pagination(client, monkeypatch):
    monkeypatch.setattr(
        "features.campaign.service.list_campaigns",
        lambda status=None, limit=50, offset=0: {
            "campaigns": [],
            "total": 7,
            "limit": limit,
            "offset": offset,
            "status_filter": status,
        },
    )

    response = client.get(
        "/campaigns",
        params={"status": CampaignStatus.ACTIVE.value, "limit": 10, "offset": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 7
    assert data["limit"] == 10
    assert data["offset"] == 5
    assert data["status_filter"] == CampaignStatus.ACTIVE.value
