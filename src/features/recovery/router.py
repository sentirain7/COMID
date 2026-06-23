"""Recovery routes."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas import ExecuteRecoveryRequest, RecoveryCheckResponse
from contracts.schemas import RecoveryCandidate, RecoveryResult

from . import service as recovery_service

router = APIRouter(tags=["Recovery"])


@router.get("/recovery/check", response_model=RecoveryCheckResponse, tags=["Recovery"])
async def check_recovery_status():
    return await recovery_service.check_recovery_status()


@router.get("/recovery/candidates", response_model=list[RecoveryCandidate], tags=["Recovery"])
async def get_recovery_candidates():
    return await recovery_service.get_recovery_candidates()


@router.post("/recovery/execute", response_model=RecoveryResult, tags=["Recovery"])
async def execute_recovery_action(request: ExecuteRecoveryRequest):
    return await recovery_service.execute_recovery_action(request)


@router.post("/recovery/execute-all", response_model=list[RecoveryResult], tags=["Recovery"])
async def execute_all_recommended():
    return await recovery_service.execute_all_recommended()


@router.post("/recovery/cleanup", tags=["Recovery"])
async def cleanup_stale_records():
    return await recovery_service.cleanup_stale_records()
