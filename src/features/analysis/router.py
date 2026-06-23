"""Analysis routes."""

from fastapi import APIRouter, HTTPException

from api.schemas import AnalysisEmbeddingPoint, BinderCellXYSummaryResponse, Scatter3DPoint

from . import service as analysis_service

router = APIRouter(tags=["Analysis"])


@router.get("/analysis/embedding", response_model=list[AnalysisEmbeddingPoint], tags=["Analysis"])
async def get_analysis_embedding(ff_type: str = "bulk_ff_gaff2"):
    return await analysis_service.get_analysis_embedding(ff_type=ff_type)


@router.get("/analysis/molecule-impact", tags=["Analysis"])
async def get_molecule_impact(ff_type: str = "bulk_ff_gaff2"):
    return await analysis_service.get_molecule_impact(ff_type=ff_type)


@router.get(
    "/analysis/binder-cells/xy-summary",
    response_model=BinderCellXYSummaryResponse,
    tags=["Analysis"],
)
async def get_binder_cell_xy_summary(group_by: str = "binder", ff_type: str = "bulk_ff_gaff2"):
    try:
        return await analysis_service.get_binder_cell_xy_summary(
            group_by=group_by,
            ff_type=ff_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analysis/scatter3d", response_model=list[Scatter3DPoint], tags=["Analysis"])
async def get_scatter3d(
    axis_x: str = "density",
    axis_y: str = "cohesive_energy_density",
    axis_z: str = "ghg_emission",
    ff_type: str = "bulk_ff_gaff2",
):
    try:
        return await analysis_service.get_scatter3d(
            axis_x=axis_x, axis_y=axis_y, axis_z=axis_z, ff_type=ff_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
