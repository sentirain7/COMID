"""MLOps API routes."""

from fastapi import APIRouter, Query

from api.schemas import (
    DriftCheckResponse,
    MLModelHistoryResponse,
    MLModelVersionResponse,
    RetrainRequest,
    RetrainResponse,
)
from api.schemas.ml_visualization import (
    DataCoverageResponse,
    DataQualityResponse,
    FeatureImportanceResponse,
    LearningCurveResponse,
    ParityPlotResponse,
    ResidualResponse,
    StructuralEvalRequest,
    StructuralEvalResponse,
    StructuralMLStatusResponse,
    StructuralTrainRequest,
    StructuralTrainResponse,
)

from . import service as mlops_service

router = APIRouter(tags=["MLOps"])


@router.get("/ml/models/champion", response_model=MLModelVersionResponse)
async def get_ml_champion():
    """Get currently promoted champion model metadata."""
    return await mlops_service.get_ml_champion()


@router.get("/ml/models/history", response_model=MLModelHistoryResponse)
async def get_ml_model_history(limit: int = 20, status: str | None = None):
    """Get model version history."""
    return await mlops_service.get_ml_model_history(limit=limit, status=status)


@router.post("/ml/models/retrain", response_model=RetrainResponse)
async def retrain_ml_model(request: RetrainRequest):
    """Manually trigger retraining pipeline."""
    return await mlops_service.retrain_ml_model(request)


@router.post("/ml/models/{version_id}/promote", response_model=MLModelVersionResponse)
async def promote_ml_model(version_id: str):
    """Promote challenger model to champion."""
    return await mlops_service.promote_ml_model(version_id)


@router.post("/ml/models/rollback", response_model=MLModelVersionResponse)
async def rollback_ml_model():
    """Rollback champion to previous promoted model."""
    return await mlops_service.rollback_ml_model()


@router.get("/ml/drift/check", response_model=DriftCheckResponse)
async def check_ml_drift():
    """Run on-demand drift check against current champion and recent data."""
    return await mlops_service.check_ml_drift()


# ---------------------------------------------------------------------------
# Diagnostics endpoints
# ---------------------------------------------------------------------------


@router.get("/ml/diagnostics/parity", response_model=ParityPlotResponse)
async def get_parity_plot(target: str = Query(..., description="Target metric name")):
    """Get parity plot data (predicted vs actual) for champion model."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(lambda s: viz.get_parity_plot(s, target))


@router.get("/ml/diagnostics/feature-importance", response_model=FeatureImportanceResponse)
async def get_feature_importance(
    target: str = Query(..., description="Target metric name"),
    top_k: int = Query(15, ge=1, le=100, description="Number of top features"),
):
    """Get feature importance for champion model."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(lambda s: viz.get_feature_importance(s, target, top_k))


@router.get("/ml/diagnostics/residuals", response_model=ResidualResponse)
async def get_residuals(target: str = Query(..., description="Target metric name")):
    """Get residual distribution for champion model."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(lambda s: viz.get_residuals(s, target))


@router.get("/ml/diagnostics/learning-curve", response_model=LearningCurveResponse)
async def get_learning_curve(
    target: str = Query(..., description="Target metric name"),
):
    """Get learning curve from model version history."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(lambda s: viz.get_learning_curve(s, target))


@router.get("/ml/diagnostics/data-coverage", response_model=DataCoverageResponse)
async def get_data_coverage():
    """Get data coverage diagnostics for ML training."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(viz.get_data_coverage)


@router.get("/ml/diagnostics/data-quality", response_model=DataQualityResponse)
async def get_data_quality():
    """Get data quality diagnostics."""
    from features.common import run_in_session
    from features.mlops import visualization_service as viz

    return run_in_session(viz.get_data_quality)


@router.get("/ml/structural/status", response_model=StructuralMLStatusResponse)
async def get_structural_ml_status():
    """V7 structural ML opt-in 정책 상태 + champion feature_set (화면 표시용)."""
    from features.mlops import visualization_service as viz

    return viz.get_structural_ml_status()


@router.post("/ml/structural/evaluate", response_model=StructuralEvalResponse)
async def evaluate_structural_v7(request: StructuralEvalRequest):
    """V7 XGB-vs-RF 랜덤 반복 평가 (on-demand, 내부 데이터만).

    모델 학습이 포함되는 무거운 경로이므로 threadpool로 오프로드해
    이벤트 루프를 막지 않는다.
    """
    from features.common import run_in_session_async
    from features.mlops import visualization_service as viz

    return await run_in_session_async(
        lambda s: viz.run_structural_eval(
            s,
            target=request.target,
            n_repeats=request.n_repeats,
            holdout_ratio=request.holdout_ratio,
        )
    )


@router.post("/ml/structural/train", response_model=StructuralTrainResponse)
async def train_structural_v7(request: StructuralTrainRequest):
    """V7 challenger 학습 (on-demand). ``register=True``면 등록·승급 판정.

    학습 경로이므로 threadpool 오프로드.
    """
    from features.common import run_in_session_async
    from features.mlops import visualization_service as viz

    return await run_in_session_async(
        lambda s: viz.run_structural_train(
            s, targets=request.targets, register=request.register_challenger
        )
    )
