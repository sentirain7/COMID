"""Recommendation and inverse-design API routes."""

from fastapi import APIRouter

from api.schemas import (
    ActiveLearningSummaryResponse,
    ApproveRecommendationRequest,
    ApproveRejectResponse,
    FeedResultRequest,
    InverseDesignRequest,
    InverseDesignResponse,
    RecommendationBatchResponse,
    RecommendationDetailResponse,
    RecommendationItem,
    RejectRecommendationRequest,
    StopRecommendationRequest,
    UnifiedRecommendation,
)

from . import active_learning as active_learning_service
from . import inverse_design as inverse_design_service
from . import pending_service

router = APIRouter(tags=["Recommendations"])


@router.post("/recommendations/suggest", response_model=RecommendationBatchResponse)
async def suggest_recommendations(n_candidates: int = 20):
    """Generate a batch of composition recommendations."""
    return await active_learning_service.suggest_recommendations(n_candidates=n_candidates)


@router.post("/recommendations/approve", response_model=ApproveRejectResponse)
async def approve_recommendation(request: ApproveRecommendationRequest):
    """Approve a recommendation for MD simulation."""
    return await active_learning_service.approve_recommendation(request)


@router.post("/recommendations/reject", response_model=ApproveRejectResponse)
async def reject_recommendation(request: RejectRecommendationRequest):
    """Reject a recommendation."""
    return await active_learning_service.reject_recommendation(request)


@router.post("/recommendations/stop", response_model=ApproveRejectResponse)
async def stop_recommendation_execution(request: StopRecommendationRequest):
    """Stop an auto-executed recommendation run."""
    return await active_learning_service.stop_recommendation_execution(request)


@router.post("/recommendations/feed-result")
async def feed_recommendation_result(request: FeedResultRequest):
    """Feed MD simulation results back to active learning loop."""
    return await active_learning_service.feed_recommendation_result(request)


@router.get("/recommendations/pending", response_model=list[RecommendationItem])
async def get_pending_recommendations():
    """Get all pending (unapproved) recommendations."""
    return await active_learning_service.get_pending_recommendations()


@router.get("/recommendations/summary", response_model=ActiveLearningSummaryResponse)
async def get_active_learning_summary():
    """Get a summary of the active learning state."""
    return await active_learning_service.get_active_learning_summary()


@router.get("/recommendations/pending/recent", response_model=list[UnifiedRecommendation])
async def list_recent_pending():
    """List recent pending recommendations from DB (all statuses)."""
    return pending_service.list_recent(limit=200)


@router.get(
    "/recommendations/pending/{recommendation_id}", response_model=RecommendationDetailResponse
)
async def get_pending_detail(recommendation_id: str):
    """Get detailed pending recommendation by ID."""
    return pending_service.get_detail(recommendation_id)


@router.post("/recommendations/inverse/run", response_model=InverseDesignResponse)
async def run_inverse_design(request: InverseDesignRequest):
    """Run inverse design optimization for user-specified property targets."""
    return await inverse_design_service.run_inverse_design(request)
