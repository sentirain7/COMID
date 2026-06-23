"""Metrics routes."""

from fastapi import APIRouter

from api.schemas import ArrayMetricCompareRequest, StressStrainResponse

from . import service as metrics_service

router = APIRouter(tags=["Metrics"])


@router.get("/metrics/ced-by-additive", tags=["Metrics"])
async def get_ced_by_additive_route(ff_type: str = "bulk_ff_gaff2"):
    return await metrics_service.get_ced_by_additive(ff_type=ff_type)


@router.get("/metrics/density-temperature", tags=["Metrics"])
async def get_density_temperature_route(ff_type: str = "bulk_ff_gaff2"):
    return await metrics_service.get_density_temperature(ff_type=ff_type)


@router.get("/metrics/temperature-scan/{exp_id}", tags=["Metrics"])
async def get_temperature_scan_route(exp_id: str):
    return await metrics_service.get_temperature_scan(exp_id)


@router.get("/metrics/{exp_id}", tags=["Metrics"])
async def get_metrics(exp_id: str):
    return await metrics_service.get_metrics(exp_id)


@router.get("/metrics/values/{metric_name}", tags=["Metrics"])
async def get_metric_values(
    metric_name: str, namespace: str | None = None, limit: int = 100, offset: int = 0
):
    return await metrics_service.get_metric_values(
        metric_name=metric_name,
        namespace=namespace,
        limit=limit,
        offset=offset,
    )


@router.get("/metrics/statistics/{metric_name}", tags=["Metrics"])
async def get_metric_statistics(metric_name: str, namespace: str | None = None):
    return await metrics_service.get_metric_statistics(metric_name=metric_name, namespace=namespace)


@router.get("/experiments/{exp_id}/array-metrics", tags=["Metrics"])
async def get_experiment_array_metrics(exp_id: str):
    return await metrics_service.get_experiment_array_metrics(exp_id)


@router.get(
    "/experiments/{exp_id}/stress-strain",
    tags=["Metrics"],
    response_model=StressStrainResponse,
)
async def get_stress_strain_curve(exp_id: str):
    """Return stress-strain curve data from stored Parquet."""
    return await metrics_service.get_stress_strain_curve(exp_id)


@router.get("/experiments/with-array-metric/{metric_name}", tags=["Metrics"])
async def list_experiments_with_metric_route(metric_name: str):
    """List experiments that have a given array metric stored."""
    return await metrics_service.get_experiments_with_array_metric(metric_name)


@router.get("/experiments/{exp_id}/array-metric/{metric_name}", tags=["Metrics"])
async def get_array_metric_route(exp_id: str, metric_name: str):
    """Return array metric data (e.g. RDF curve) for one experiment."""
    return await metrics_service.get_array_metric_data(exp_id, metric_name)


@router.post("/experiments/array-metric-compare", tags=["Metrics"])
async def compare_array_metrics_route(body: ArrayMetricCompareRequest):
    """Compare an array metric across multiple experiments (max 8)."""
    return await metrics_service.get_array_metric_compare(body.exp_ids, body.metric_name)


@router.get("/metrics/property-temperature/{metric_name}", tags=["Metrics"])
async def get_property_temperature_route(
    metric_name: str,
    ff_type: str = "bulk_ff_gaff2",
    additive_mol_id: str | None = None,
):
    """Get property values grouped by temperature.

    Args:
        metric_name: Name of the metric (e.g., 'density', 'cohesive_energy_density')
        ff_type: Force field type filter
        additive_mol_id: Optional additive mol_id filter ('none' for no additive)

    Returns:
        Dict with temperatures and corresponding metric values
    """
    return await metrics_service.get_property_by_temperature(
        metric_name, ff_type=ff_type, additive_mol_id=additive_mol_id
    )


@router.get("/metrics/property-by-additive/{metric_name}", tags=["Metrics"])
async def get_property_by_additive_route(
    metric_name: str,
    ff_type: str = "bulk_ff_gaff2",
    temperature_k: float | None = None,
):
    """Get property values grouped by additive type.

    Args:
        metric_name: Name of the metric (e.g., 'density', 'cohesive_energy_density')
        ff_type: Force field type filter
        temperature_k: Optional temperature filter

    Returns:
        Dict with additives and corresponding metric values
    """
    return await metrics_service.get_property_by_additive(
        metric_name, ff_type=ff_type, temperature_k=temperature_k
    )
