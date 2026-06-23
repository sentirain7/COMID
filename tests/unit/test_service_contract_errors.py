"""ContractError behavior tests for service-layer error mapping."""

from types import SimpleNamespace

import pytest

from contracts.errors import ContractError, ErrorCode, OrchestrationError
from features.jobs.management import delete_or_cancel_job, get_job
from features.recovery.service import execute_recovery_action, get_recovery_candidates


@pytest.mark.asyncio
async def test_get_job_raises_service_unavailable(monkeypatch):
    def _raise_runtime_error():
        raise RuntimeError("manager down")

    monkeypatch.setattr("api.deps.get_job_manager", _raise_runtime_error)

    with pytest.raises(OrchestrationError) as exc:
        await get_job("job-1")

    assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_delete_or_cancel_job_invalid_state(monkeypatch):
    mock_manager = SimpleNamespace(
        get_job=lambda _job_id: SimpleNamespace(status=SimpleNamespace(value="running")),
        cancel_job=lambda _job_id: False,
        delete_job=lambda _job_id: False,
    )
    monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)

    with pytest.raises(ContractError) as exc:
        await delete_or_cancel_job("job-1", action="cancel")

    assert exc.value.code == ErrorCode.INVALID_REQUEST


@pytest.mark.asyncio
async def test_get_recovery_candidates_requires_service(monkeypatch):
    monkeypatch.setattr("features.recovery.service.get_recovery_service", lambda: None)

    with pytest.raises(OrchestrationError) as exc:
        await get_recovery_candidates()

    assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_execute_recovery_action_invalid_action(monkeypatch):
    mock_recovery_service = SimpleNamespace(
        execute_recovery=lambda _exp_id, _action: None,
    )
    monkeypatch.setattr(
        "features.recovery.service.get_recovery_service",
        lambda: mock_recovery_service,
    )
    request = SimpleNamespace(exp_id="exp-1", action="not-a-valid-action")

    with pytest.raises(ContractError) as exc:
        await execute_recovery_action(request)

    assert exc.value.code == ErrorCode.INVALID_REQUEST
