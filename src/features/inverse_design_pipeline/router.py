"""역설계 파이프라인 REST 라우터 (계획 §9-5, P3).

POST /inverse-design/plan          — 계획 미리보기 (stateless dry-run)
POST /inverse-design/plan/approve  — 계획 승인·실행 (plan_hash 재검증)
GET  /inverse-design/{id}/progress — 진행집계
GET  /inverse-design/{id}/results  — 목표 대비 결과
"""

from fastapi import APIRouter

from api.schemas import (
    InversePipelineApproveRequest,
    InversePipelineApproveResponse,
    InversePipelineLoopStepRequest,
    InversePipelineLoopStepResponse,
    InversePipelinePlanRequest,
    InversePipelinePlanResponse,
    InversePipelineProgressResponse,
    InversePipelineResultsResponse,
)
from features.inverse_design_pipeline import execution, loop, results, service

router = APIRouter(prefix="/inverse-design", tags=["InverseDesignPipeline"])


@router.post("/plan", response_model=InversePipelinePlanResponse)
async def preview_inverse_pipeline_plan(
    request: InversePipelinePlanRequest,
) -> InversePipelinePlanResponse:
    """목표 물성 → DOE 계획 미리보기 (제출 없음, §4.2 ①~③)."""
    result = await service.preview_plan(request, moisture_damage=request.moisture_damage)
    return InversePipelinePlanResponse(**result)


@router.post("/plan/approve", response_model=InversePipelineApproveResponse)
def approve_inverse_pipeline_plan(
    request: InversePipelineApproveRequest,
) -> InversePipelineApproveResponse:
    """승인된 계획을 검증 후 실행 (§4.2 ④ — plan_hash/정책 재검증)."""
    result = execution.approve_and_run(request.plan, request.plan_hash)
    return InversePipelineApproveResponse(**result)


@router.get("/{pipeline_id}/progress", response_model=InversePipelineProgressResponse)
def get_inverse_pipeline_progress(pipeline_id: str) -> InversePipelineProgressResponse:
    """파이프라인 진행집계 (§4.2 ⑤)."""
    return InversePipelineProgressResponse(**execution.get_progress(pipeline_id))


@router.get("/{pipeline_id}/results", response_model=InversePipelineResultsResponse)
def get_inverse_pipeline_results(pipeline_id: str) -> InversePipelineResultsResponse:
    """파이프라인 결과 — 목표 대비 달성도 (§4.2 ⑥)."""
    return InversePipelineResultsResponse(**results.get_results(pipeline_id))


@router.post("/loop/step", response_model=InversePipelineLoopStepResponse)
async def run_inverse_pipeline_loop_step(
    request: InversePipelineLoopStepRequest,
) -> InversePipelineLoopStepResponse:
    """닫힌 루프 한 스텝 (§7, 정책 기본 OFF) — 진단·정지/다음 라운드."""
    result = await loop.run_loop_round(request.plan, request.plan_hash, request.pipeline_id)
    return InversePipelineLoopStepResponse(**result)
