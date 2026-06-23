"""역설계 파이프라인 API 스키마 (계획 §9-5, P3).

stateless 설계(§4.6): 계획 문서(JSON)는 서버에 저장하지 않고 응답으로
반환하며, 승인 시 클라이언트가 그대로 회신해 plan_hash로 재검증한다.
"""

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.recommendations import InverseDesignRequest


class InversePipelinePlanRequest(InverseDesignRequest):
    """계획 미리보기 요청 — 역설계 입력 + 파이프라인 전용 플래그."""

    model_config = ConfigDict(title="InversePipelinePlanRequest")

    moisture_damage: bool = Field(
        False,
        description="수분손상 트랙 — 계면 실험에 water-interface wet 페어를 편성 (§2)",
    )


class InversePipelinePlanResponse(BaseModel):
    """계획 미리보기 응답 (서버 비저장, plan_hash 동봉)."""

    model_config = ConfigDict(title="InversePipelinePlanResponse")

    plan: dict
    plan_hash: str


class InversePipelineApproveRequest(BaseModel):
    """계획 승인 요청 — preview가 반환한 plan/plan_hash를 그대로 회신."""

    model_config = ConfigDict(title="InversePipelineApproveRequest")

    plan: dict
    plan_hash: str = Field(..., min_length=1)


class PipelineMemberItem(BaseModel):
    """승인 실행 결과의 멤버 항목."""

    model_config = ConfigDict(title="PipelineMemberItem")

    plan_exp_id: str
    kind: str
    action: str
    exp_id: str | None = None
    job_id: str | None = None
    parent_exp_id: str | None = None
    error: str | None = None


class InversePipelineApproveResponse(BaseModel):
    """계획 승인 실행 응답."""

    model_config = ConfigDict(title="InversePipelineApproveResponse")

    pipeline_id: str
    plan_hash: str
    mode: str
    members: list[PipelineMemberItem]
    counts: dict[str, int]


class PipelineProgressMemberItem(BaseModel):
    """진행집계 멤버 항목 (placeholder 간접참조 해석 포함)."""

    model_config = ConfigDict(title="PipelineProgressMemberItem")

    exp_id: str
    effective_exp_id: str
    plan_exp_id: str | None = None
    kind: str | None = None
    candidate_index: int | None = None
    role: str = "member"
    status: str
    effective_status: str
    replicate_group_id: str | None = None
    ensemble_ready: bool = False


class InversePipelineProgressResponse(BaseModel):
    """파이프라인 진행집계 응답."""

    model_config = ConfigDict(title="InversePipelineProgressResponse")

    pipeline_id: str
    total: int
    completed: int
    status_counts: dict[str, int]
    members: list[PipelineProgressMemberItem]


class InversePipelineResultsResponse(BaseModel):
    """파이프라인 결과(목표 대비 달성도) 응답."""

    model_config = ConfigDict(title="InversePipelineResultsResponse")

    pipeline_id: str
    targets: list[dict]
    candidates: list[dict]
    total_experiments: int
    completed_experiments: int


class InversePipelineLoopStepRequest(BaseModel):
    """닫힌 루프 한 스텝 요청 (§7) — 종료된 라운드의 plan/hash/id 회신."""

    model_config = ConfigDict(title="InversePipelineLoopStepRequest")

    pipeline_id: str = Field(..., min_length=1)
    plan: dict
    plan_hash: str = Field(..., min_length=1)


class InversePipelineLoopStepResponse(BaseModel):
    """닫힌 루프 스텝 응답 — 정지 결정 또는 자동 실행된 다음 라운드."""

    model_config = ConfigDict(title="InversePipelineLoopStepResponse")

    decision: str
    diagnostics: dict
    audit: dict
    next: dict | None = None
