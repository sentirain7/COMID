"""Health and monitoring routes."""

from fastapi import APIRouter

from api.schemas import DetailedHealthResponse

from . import service as health_service

router = APIRouter()


@router.get("/", tags=["Health"])
async def root():
    return health_service.root()


@router.get("/health", response_model=DetailedHealthResponse, tags=["Health"])
async def health_check():
    return await health_service.health_check()
