"""Metrics query operations."""

from __future__ import annotations

from api.schemas import (
    ArrayMetricCompareItem,
    ArrayMetricCompareResponse,
    ArrayMetricDataResponse,
    ArrayMetricInfo,
    ArrayMetricsResponse,
    ExperimentArrayMetricEntry,
    MetricStatisticsResponse,
    MetricValueItem,
    MetricValuesResponse,
)
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode, MetricError
from features.common import run_in_session

logger = get_logger("features.metrics.query")


async def get_metrics(exp_id: str) -> dict:
    from database.repositories.metric_repo import MetricRepository

    metrics = []
    try:

        def _load(session):
            nonlocal metrics
            metric_repo = MetricRepository(session)
            db_metrics = metric_repo.get_by_exp_id(exp_id)
            for m in db_metrics:
                metrics.append(
                    {
                        "metric_name": m.metric_name,
                        "value": m.value,
                        "unit": m.unit,
                        "namespace": m.namespace,
                        "uncertainty": m.uncertainty,
                    }
                )

        run_in_session(_load)
    except Exception as exc:
        logger.warning(f"Failed to get metrics for {exp_id}: {exc}")

    return {"exp_id": exp_id, "metrics": metrics}


async def get_metric_values(
    metric_name: str,
    namespace: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> MetricValuesResponse:
    from contracts.policies.metrics import MetricsRegistry, MetricType
    from database.repositories.metric_repo import MetricRepository

    if limit < 1 or limit > 1000:
        raise ContractError(ErrorCode.INVALID_REQUEST, "limit must be between 1 and 1000")
    if offset < 0:
        raise ContractError(ErrorCode.INVALID_REQUEST, "offset must be >= 0")

    registry = MetricsRegistry()
    if registry.is_valid_metric(metric_name) and registry.get_type(metric_name) == MetricType.ARRAY:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"'{metric_name}' is an array metric. Use /experiments/{{exp_id}}/array-metrics.",
        )

    try:

        def _query(session):
            repo = MetricRepository(session)
            values = repo.get_values_by_metric(
                metric_name=metric_name,
                namespace=namespace,
                limit=limit,
                offset=offset,
            )
            stats = repo.get_statistics(metric_name, namespace)
            total = stats["count"]
            return MetricValuesResponse(
                metric_name=metric_name,
                namespace=namespace,
                total=total,
                offset=offset,
                limit=limit,
                values=[MetricValueItem(exp_id=exp_id, value=value) for exp_id, value in values],
            )

        return run_in_session(_query)
    except Exception as exc:
        logger.error(f"Failed to get metric values: {exc}")
        raise MetricError(ErrorCode.METRIC_ERROR, str(exc), metric_name=metric_name) from exc


async def get_metric_statistics(
    metric_name: str,
    namespace: str | None = None,
) -> MetricStatisticsResponse:
    from contracts.policies.metrics import MetricsRegistry, MetricType
    from database.repositories.metric_repo import MetricRepository

    registry = MetricsRegistry()
    if registry.is_valid_metric(metric_name) and registry.get_type(metric_name) == MetricType.ARRAY:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"'{metric_name}' is an array metric and does not support scalar statistics.",
        )

    try:

        def _query(session):
            repo = MetricRepository(session)
            stats = repo.get_statistics(metric_name, namespace)
            return MetricStatisticsResponse(
                metric_name=metric_name,
                namespace=namespace,
                count=stats["count"],
                avg=stats["avg"],
                min=stats["min"],
                max=stats["max"],
                stddev=stats.get("stddev"),
            )

        return run_in_session(_query)
    except Exception as exc:
        logger.error(f"Failed to get metric statistics: {exc}")
        raise MetricError(ErrorCode.METRIC_ERROR, str(exc), metric_name=metric_name) from exc


async def get_experiment_array_metrics(exp_id: str) -> ArrayMetricsResponse:
    from database.repositories.metric_repo import MetricRepository

    try:

        def _query(session):
            repo = MetricRepository(session)
            metrics = repo.list_array_metrics(exp_id)
            return ArrayMetricsResponse(
                exp_id=exp_id,
                array_metrics=[
                    ArrayMetricInfo(
                        metric_name=m.metric_name,
                        namespace=m.namespace,
                        array_file_path=m.array_file_path,
                        array_shape=m.array_shape,
                    )
                    for m in metrics
                ],
            )

        return run_in_session(_query)
    except Exception as exc:
        logger.error(f"Failed to get array metrics for {exp_id}: {exc}")
        raise MetricError(
            ErrorCode.METRIC_ERROR,
            str(exc),
            metric_name="array_metrics",
            details={"exp_id": exp_id},
        ) from exc


async def get_stress_strain_curve(exp_id: str) -> dict:
    """Load stress-strain curve from ArrayStorage."""
    from metrics.array_storage import ArrayStorage

    storage = ArrayStorage()
    data = storage.load("stress_strain_curve", exp_id)
    if data is None:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            f"No stress-strain curve found for {exp_id}",
        )

    strain = data.get("strain", [])
    stress = data.get("stress_MPa", [])
    if not strain or not stress:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Empty stress-strain data for {exp_id}",
        )

    # Guard against length mismatch (corrupted/legacy data)
    n = min(len(strain), len(stress))
    strain = strain[:n]
    stress = stress[:n]

    # Find peak (safe — n >= 1 guaranteed by check above)
    peak_idx = int(max(range(n), key=lambda i: stress[i]))

    return {
        "exp_id": exp_id,
        "strain": strain,
        "stress_MPa": stress,
        "peak_index": peak_idx,
        "peak_strain": strain[peak_idx],
        "peak_stress_MPa": stress[peak_idx],
    }


# ---------------------------------------------------------------------------
# Metric query helpers (originally extracted from the removed GraphQL queries)
# ---------------------------------------------------------------------------


def _build_density_dict(metric_model, exp_id: str) -> dict:
    """Build density metric dict from a MetricModel row.

    Returns:
        Dict with keys: exp_id, average, std_dev, min_value, max_value,
        n_samples, skip_fraction, quality, is_equilibrated.
    """
    meta = metric_model.metadata_json or {}
    avg = metric_model.value
    std = metric_model.uncertainty or meta.get("std_dev", 0.0)
    return {
        "exp_id": exp_id,
        "average": avg or 0.0,
        "std_dev": std,
        "min_value": meta.get("min_value", (avg or 0.0) - 2.0 * std),
        "max_value": meta.get("max_value", (avg or 0.0) + 2.0 * std),
        "n_samples": meta.get("n_samples", 0),
        "skip_fraction": meta.get("skip_fraction", 0.0),
        "quality": "ok" if avg and 0.8 < avg < 1.3 else "warning",
        "is_equilibrated": bool(meta.get("is_equilibrated", std < 0.05 if std else False)),
    }


def _build_ced_dict(metric_model, exp_id: str) -> dict:
    """Build CED metric dict from a MetricModel row."""
    meta = metric_model.metadata_json or {}
    ced_val = metric_model.value or 0.0
    ced_std = metric_model.uncertainty or meta.get("std_dev", 0.0)
    sol_param = meta.get("solubility_parameter", ced_val**0.5 if ced_val > 0 else 0.0)
    return {
        "exp_id": exp_id,
        "ced": ced_val,
        "std_dev": ced_std,
        "solubility_parameter": sol_param,
        "e_coh": meta.get("e_coh", 0.0),
        "molar_volume": meta.get("molar_volume", 0.0),
    }


def _build_viscosity_dict(metric_model, exp_id: str) -> dict:
    """Build viscosity metric dict from a MetricModel row."""
    meta = metric_model.metadata_json or {}
    return {
        "exp_id": exp_id,
        "viscosity": metric_model.value or 0.0,
        "std_dev": metric_model.uncertainty or meta.get("std_dev", 0.0),
        "method": meta.get("method", "GK"),
        "temperature_k": meta.get("temperature_k", 298.0),
        "shear_rate": meta.get("shear_rate"),
    }


def get_metrics_summary(exp_id: str) -> dict | None:
    """Get all key metrics for an experiment as plain dicts.

    Returns:
        Dict with keys: exp_id, density, ced, viscosity,
        composition_error_l1, wall_time_seconds.
        Returns None if no metrics exist.
    """
    from database.connection import get_session
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    session = get_session()
    try:
        metric_repo = MetricRepository(session)
        exp_repo = ExperimentRepository(session)

        experiment = exp_repo.get_by_id(exp_id)
        composition_error = experiment.composition_error_l1 if experiment else 0.0
        wall_time = experiment.wall_time_seconds if experiment else None

        metrics = metric_repo.get_by_exp_id(exp_id)
        if not metrics:
            return None

        density_dict = None
        ced_dict = None
        viscosity_dict = None
        rdf_coordination_number_val: float | None = None
        e_inter_total_val: float | None = None
        glass_transition_temperature_k_val: float | None = None
        bulk_modulus_val: float | None = None

        for m in metrics:
            if m.metric_name == "density" and density_dict is None:
                density_dict = _build_density_dict(m, exp_id)
            elif m.metric_name in ("cohesive_energy_density", "ced") and ced_dict is None:
                ced_dict = _build_ced_dict(m, exp_id)
            elif m.metric_name == "viscosity" and viscosity_dict is None:
                viscosity_dict = _build_viscosity_dict(m, exp_id)
            elif m.metric_name == "rdf_coordination_number" and rdf_coordination_number_val is None:
                rdf_coordination_number_val = m.value
            elif m.metric_name == "e_inter_total" and e_inter_total_val is None:
                e_inter_total_val = m.value
            elif (
                m.metric_name == "glass_transition_temperature_k"
                and glass_transition_temperature_k_val is None
            ):
                glass_transition_temperature_k_val = m.value
            elif m.metric_name == "bulk_modulus" and bulk_modulus_val is None:
                bulk_modulus_val = m.value

        return {
            "exp_id": exp_id,
            "density": density_dict,
            "ced": ced_dict,
            "viscosity": viscosity_dict,
            "rdf_coordination_number": rdf_coordination_number_val,
            "e_inter_total": e_inter_total_val,
            "glass_transition_temperature_k": glass_transition_temperature_k_val,
            "bulk_modulus": bulk_modulus_val,
            "composition_error_l1": composition_error,
            "wall_time_seconds": wall_time,
        }
    finally:
        session.close()


def get_density_metric(exp_id: str) -> dict | None:
    """Get density metric details for an experiment.

    Returns:
        Density metric dict or None if not found.
    """
    from database.connection import get_session
    from database.repositories.metric_repo import MetricRepository

    session = get_session()
    try:
        repo = MetricRepository(session)
        metrics = repo.get_by_exp_id(exp_id)
        for m in metrics:
            if m.metric_name == "density":
                return _build_density_dict(m, exp_id)
        return None
    finally:
        session.close()


def get_thermo_data(
    exp_id: str,
    start_step: int | None = None,
    end_step: int | None = None,
) -> dict | None:
    """Parse thermo data from experiment log file.

    Returns:
        Dict with keys: exp_id, steps, temperature, pressure, density,
        potential_energy, kinetic_energy, total_energy, volume.
        Returns None if no data available.
    """
    from database.connection import get_session
    from database.repositories.experiment_repo import ExperimentRepository
    from parsers.log_parser import LogParser

    session = get_session()
    try:
        repo = ExperimentRepository(session)
        exp = repo.get_by_id(exp_id)
        if not exp or not exp.log_file_path:
            return None

        parser = LogParser()
        result = parser.parse(exp.log_file_path)
        if not result or not result.thermo_data:
            return None

        td = result.thermo_data
        steps = [int(v) for v in td.get("Step", [])]
        temperature = list(td.get("Temp", []))
        pressure = list(td.get("Press", []))
        density = list(td.get("Density", []))
        pe = list(td.get("PotEng", []))
        ke = list(td.get("KinEng", []))
        te = list(td.get("TotEng", []))
        vol = list(td.get("Volume", []))

        if not steps:
            return None

        # Apply step range filter
        if start_step is not None or end_step is not None:
            lo = start_step or 0
            hi = end_step or float("inf")
            indices = [i for i, s in enumerate(steps) if lo <= s <= hi]
            steps = [steps[i] for i in indices]
            temperature = [temperature[i] for i in indices] if temperature else []
            pressure = [pressure[i] for i in indices] if pressure else []
            density = [density[i] for i in indices] if density else []
            pe = [pe[i] for i in indices] if pe else []
            ke = [ke[i] for i in indices] if ke else []
            te = [te[i] for i in indices] if te else []
            vol = [vol[i] for i in indices] if vol else []

        return {
            "exp_id": exp_id,
            "steps": steps,
            "temperature": temperature,
            "pressure": pressure,
            "density": density,
            "potential_energy": pe or [0.0] * len(steps),
            "kinetic_energy": ke or [0.0] * len(steps),
            "total_energy": te or [0.0] * len(steps),
            "volume": vol or [0.0] * len(steps),
        }
    finally:
        session.close()


def get_all_metrics_statistics() -> dict:
    """Get global statistics for density and CED metrics.

    Returns:
        Dict with keys: density (dict), ced (dict).
        Each sub-dict has: count, avg, min, max.
    """
    from database.connection import get_session
    from database.repositories.metric_repo import MetricRepository

    def _stat_dict(raw: dict) -> dict:
        return {
            "count": raw["count"],
            "avg": raw["avg"],
            "min": raw["min"],
            "max": raw["max"],
        }

    session = get_session()
    try:
        repo = MetricRepository(session)
        density_stats = repo.get_statistics("density", "bulk_ff_gaff2")
        ced_stats = repo.get_statistics("cohesive_energy_density", "bulk_ff_gaff2")
        rdf_cn_stats = repo.get_statistics("rdf_coordination_number", "bulk_ff_gaff2")
        e_inter_stats = repo.get_statistics("e_inter_total", "bulk_ff_gaff2")
        tg_stats = repo.get_statistics("glass_transition_temperature_k", "bulk_ff_gaff2")
        return {
            "density": _stat_dict(density_stats),
            "ced": _stat_dict(ced_stats),
            "rdf_coordination_number": _stat_dict(rdf_cn_stats),
            "e_inter_total": _stat_dict(e_inter_stats),
            "glass_transition_temperature_k": _stat_dict(tg_stats),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Array Metric Data (Curve Analysis)
# ---------------------------------------------------------------------------


async def get_array_metric_data(exp_id: str, metric_name: str) -> dict:
    """Load array metric data for a single experiment.

    Args:
        exp_id: Experiment ID.
        metric_name: Registry array metric name (e.g. 'rdf_curve').

    Returns:
        Dict matching ArrayMetricDataResponse schema.
    """
    from contracts.policies.metrics import MetricsRegistry, MetricType
    from database.repositories.metric_repo import MetricRepository
    from metrics.array_storage import ArrayStorage

    registry = MetricsRegistry()
    if not registry.is_valid_metric(metric_name):
        raise ContractError(ErrorCode.INVALID_REQUEST, f"Unknown metric: {metric_name}")
    if registry.get_type(metric_name) != MetricType.ARRAY:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"'{metric_name}' is not an array metric",
        )

    expected_columns = registry.get_array_columns(metric_name) or []
    namespace = str(registry.get_namespace(metric_name))

    def _load(session):
        repo = MetricRepository(session)
        metric = repo.get_by_name(exp_id, metric_name)
        db_metadata = (metric.metadata_json if metric else None) or {}

        storage = ArrayStorage()
        data, file_metadata = storage.load_with_metadata(metric_name, exp_id)
        if data is None and metric and metric.array_file_path:
            data = storage.load(metric.array_file_path)
            file_metadata = None
        if data is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"No {metric_name} data found for {exp_id}",
            )

        ordered = {col: data.get(col, []) for col in expected_columns if col in data}
        merged_meta = {**(file_metadata or {}), **db_metadata}

        return ArrayMetricDataResponse(
            exp_id=exp_id,
            metric_name=metric_name,
            namespace=namespace,
            columns=ordered,
            metadata=merged_meta or None,
        ).model_dump()

    return run_in_session(_load)


async def get_array_metric_compare(
    exp_ids: list[str],
    metric_name: str,
) -> dict:
    """Load and compare array metric data across multiple experiments.

    Args:
        exp_ids: List of experiment IDs (max 8).
        metric_name: Registry array metric name.

    Returns:
        Dict matching ArrayMetricCompareResponse schema.
    """
    from contracts.policies.metrics import MetricsRegistry, MetricType
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository
    from features.common.labels import build_experiment_short_label
    from metrics.array_storage import ArrayStorage

    if len(exp_ids) > 8:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Maximum 8 experiments for comparison",
        )

    registry = MetricsRegistry()
    if not registry.is_valid_metric(metric_name):
        raise ContractError(ErrorCode.INVALID_REQUEST, f"Unknown metric: {metric_name}")
    if registry.get_type(metric_name) != MetricType.ARRAY:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"'{metric_name}' is not an array metric",
        )

    expected_columns = registry.get_array_columns(metric_name) or []

    def _load(session):
        exp_repo = ExperimentRepository(session)
        metric_repo = MetricRepository(session)
        storage = ArrayStorage()
        items: list[ArrayMetricCompareItem] = []

        for eid in exp_ids:
            exp = exp_repo.get_by_id(eid)
            label = build_experiment_short_label(exp) if exp else eid

            metric = metric_repo.get_by_name(eid, metric_name)
            db_metadata = (metric.metadata_json if metric else None) or {}

            data, file_metadata = storage.load_with_metadata(metric_name, eid)
            if data is None and metric and metric.array_file_path:
                data = storage.load(metric.array_file_path)
                file_metadata = None
            if data is None:
                continue

            ordered = {col: data.get(col, []) for col in expected_columns if col in data}
            merged_meta = {**(file_metadata or {}), **db_metadata}

            items.append(
                ArrayMetricCompareItem(
                    exp_id=eid,
                    label=label,
                    columns=ordered,
                    metadata=merged_meta or None,
                )
            )

        return ArrayMetricCompareResponse(
            metric_name=metric_name,
            experiments=items,
        ).model_dump()

    return run_in_session(_load)


async def get_experiments_with_array_metric(metric_name: str) -> list[dict]:
    """List experiments that have a specific array metric stored.

    Args:
        metric_name: Registry array metric name.

    Returns:
        List of dicts matching ExperimentArrayMetricEntry schema.
    """
    from contracts.policies.metrics import MetricsRegistry, MetricType
    from database.models import ExperimentModel, MetricModel
    from features.common.labels import (
        build_experiment_short_label,
        resolve_experiment_catalog_labels,
    )

    registry = MetricsRegistry()
    if not registry.is_valid_metric(metric_name):
        raise ContractError(ErrorCode.INVALID_REQUEST, f"Unknown metric: {metric_name}")
    if registry.get_type(metric_name) != MetricType.ARRAY:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"'{metric_name}' is not an array metric",
        )

    def _query(session):
        rows = (
            session.query(ExperimentModel)
            .join(
                MetricModel,
                MetricModel.exp_id == ExperimentModel.exp_id,
            )
            .filter(
                MetricModel.metric_name == metric_name,
                MetricModel.array_file_path.isnot(None),
            )
            .all()
        )

        results = []
        for exp in rows:
            labels = resolve_experiment_catalog_labels(exp)
            results.append(
                ExperimentArrayMetricEntry(
                    exp_id=exp.exp_id,
                    label=build_experiment_short_label(exp),
                    binder_type=labels.get("binder_type"),
                    temperature_k=getattr(exp, "temperature_K", None)
                    or getattr(exp, "temperature_k", None),
                    additive=labels.get("additive_label"),
                ).model_dump()
            )

        from features.common.canonical_ordering import stable_sort_records

        return stable_sort_records(
            results,
            ["temperature_k", "additive"],
            exp_id_key="exp_id",
        )

    return run_in_session(_query)
