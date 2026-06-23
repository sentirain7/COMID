"""Metrics analytics operations."""

from common.logging import get_logger
from features.common import run_in_session

logger = get_logger("features.metrics.analytics")


def _build_additive_name_map(session) -> dict[str, str]:
    """Build mol_id → display name map from AdditiveCatalog.

    Resolution order: short_name → name → mol_id (fallback).
    """
    from database.models.molecule import AdditiveCatalogModel

    name_map: dict[str, str] = {}
    try:
        rows = session.query(
            AdditiveCatalogModel.mol_id,
            AdditiveCatalogModel.short_name,
            AdditiveCatalogModel.name,
        ).all()
        for mol_id, short_name, name in rows:
            display = (short_name or "").strip() or (name or "").strip() or mol_id
            name_map[mol_id] = display
    except Exception:
        pass  # table may not exist yet
    return name_map


def _resolve_additive_display(exp, name_map: dict[str, str]) -> tuple[str, float]:
    """Resolve experiment additive to (display_name, wt%).

    Returns:
        (display_name, additive_wt) where display_name is the human-readable
        additive name from the catalog, or 'none' if no additive.
    """
    if exp.additive_mol_id:
        display = name_map.get(exp.additive_mol_id, exp.additive_mol_id)
        return display, float(exp.additive_wt or 0.0)
    if exp.additive_type:
        return exp.additive_type.upper(), float(exp.additive_wt or 0.0)
    return "none", 0.0


async def get_ced_by_additive(ff_type: str = "bulk_ff_gaff2") -> dict:
    from datetime import datetime, timedelta

    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    additives_set: set[str] = set()
    points = []

    try:

        def _collect(session):
            nonlocal points, additives_set
            metric_repo = MetricRepository(session)
            exp_repo = ExperimentRepository(session)
            name_map = _build_additive_name_map(session)

            ced_values = metric_repo.get_values_by_metric(
                metric_name="cohesive_energy_density",
                namespace=ff_type,
            )

            now = datetime.utcnow()
            session_start = now - timedelta(hours=1)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            for exp_id, ced_value in ced_values:
                if ced_value is None:
                    continue

                exp = exp_repo.get_by_id(exp_id)
                if not exp or exp.ff_type != ff_type:
                    continue

                additive, additive_wt = _resolve_additive_display(exp, name_map)
                if additive == "none":
                    additive = "None"  # CED endpoint uses uppercase

                data_age = "historical"
                if exp.created_at:
                    if exp.created_at > session_start:
                        data_age = "current_session"
                    elif exp.created_at > today_start:
                        data_age = "today"

                additives_set.add(additive)
                points.append(
                    {
                        "exp_id": exp_id,
                        "additive": additive,
                        "additive_wt": additive_wt,
                        "ced": ced_value,
                        "data_age": data_age,
                        "temperature_k": exp.temperature_K if exp else 298.0,
                    }
                )

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to get CED by additive data: {exc}")

    from features.common.canonical_ordering import stable_sort_records

    points = stable_sort_records(
        points,
        ["additive", "additive_wt", "temperature_k"],
        exp_id_key="exp_id",
    )

    additives = sorted(additives_set)
    if "None" in additives:
        additives.remove("None")
        additives.insert(0, "None")

    return {"additives": additives, "points": points, "ff_type": ff_type}


async def get_density_temperature(ff_type: str = "bulk_ff_gaff2") -> dict:
    from datetime import datetime, timedelta

    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    points = []

    try:

        def _collect(session):
            nonlocal points
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)
            name_map = _build_additive_name_map(session)

            now = datetime.utcnow()
            session_start = now - timedelta(hours=1)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            all_exps = exp_repo.list_all(limit=1000)
            completed_exps = [
                e for e in all_exps if e.status == "completed" and e.ff_type == ff_type
            ]

            for exp in completed_exps:
                density_metric = metric_repo.get_by_name(exp.exp_id, "density")
                if not density_metric:
                    continue

                data_age = "historical"
                if exp.created_at:
                    if exp.created_at > session_start:
                        data_age = "current_session"
                    elif exp.created_at > today_start:
                        data_age = "today"

                additive, additive_wt = _resolve_additive_display(exp, name_map)

                points.append(
                    {
                        "exp_id": exp.exp_id,
                        "temperature_k": exp.temperature_K or 298.0,
                        "density": density_metric.value,
                        "uncertainty": density_metric.uncertainty,
                        "additive": additive,
                        "additive_wt": additive_wt,
                        "data_age": data_age,
                        "run_tier": exp.run_tier,
                    }
                )

        run_in_session(_collect)
    except Exception as exc:
        logger.error(f"Error fetching density-temperature data: {exc}", exc_info=True)

    from features.common.canonical_ordering import stable_sort_records

    points = stable_sort_records(
        points,
        ["temperature_k", "additive", "additive_wt"],
        exp_id_key="exp_id",
    )

    return {"points": points, "ff_type": ff_type}


async def get_temperature_scan(exp_id: str) -> dict:
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    temperatures = []
    densities = []
    ceds = []

    try:

        def _collect(session):
            nonlocal temperatures, densities, ceds
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)

            base_exp = exp_repo.get_by_id(exp_id)
            if base_exp:
                all_exps = exp_repo.list_all(limit=1000)
                related_exps = [
                    e
                    for e in all_exps
                    if (
                        e.topology_hash == base_exp.topology_hash
                        or (
                            e.comp_asphaltene_wt == base_exp.comp_asphaltene_wt
                            and e.comp_resin_wt == base_exp.comp_resin_wt
                            and e.comp_aromatic_wt == base_exp.comp_aromatic_wt
                            and e.comp_saturate_wt == base_exp.comp_saturate_wt
                        )
                    )
                    and e.status == "completed"
                ]

                for exp in sorted(related_exps, key=lambda x: x.temperature_K or 298.0):
                    temp = exp.temperature_K or 298.0
                    density_metric = metric_repo.get_by_name(exp.exp_id, "density")
                    density = density_metric.value if density_metric else None
                    ced_metric = metric_repo.get_by_name(exp.exp_id, "cohesive_energy_density")
                    ced = ced_metric.value if ced_metric else None

                    temperatures.append(temp)
                    densities.append(density)
                    ceds.append(ced)

        run_in_session(_collect)
    except Exception as exc:
        logger.warning(f"Failed to get temperature scan data for {exp_id}: {exc}")

    return {"exp_id": exp_id, "temperatures": temperatures, "densities": densities, "ceds": ceds}


async def get_property_by_temperature(
    metric_name: str,
    *,
    ff_type: str = "bulk_ff_gaff2",
    additive_mol_id: str | None = None,
) -> dict:
    """Get property values grouped by temperature.

    Args:
        metric_name: Name of the metric (e.g., 'density', 'cohesive_energy_density')
        ff_type: Force field type filter
        additive_mol_id: Optional additive mol_id filter (None = all)

    Returns:
        Dict with temperatures and corresponding metric values
    """
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    points = []

    try:

        def _collect(session):
            nonlocal points
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)
            name_map = _build_additive_name_map(session)

            all_exps = exp_repo.list_all(limit=2000)
            completed_exps = [
                e for e in all_exps if e.status == "completed" and e.ff_type == ff_type
            ]

            # Apply additive filter if specified
            if additive_mol_id is not None:
                if additive_mol_id == "none" or additive_mol_id == "":
                    completed_exps = [
                        e
                        for e in completed_exps
                        if not e.additive_mol_id or e.additive_mol_id == ""
                    ]
                else:
                    completed_exps = [
                        e for e in completed_exps if e.additive_mol_id == additive_mol_id
                    ]

            for exp in completed_exps:
                metric = metric_repo.get_by_name(exp.exp_id, metric_name)
                if not metric or metric.value is None:
                    continue

                additive, additive_wt = _resolve_additive_display(exp, name_map)

                points.append(
                    {
                        "exp_id": exp.exp_id,
                        "temperature_k": exp.temperature_K or 298.0,
                        "value": metric.value,
                        "uncertainty": metric.uncertainty,
                        "additive": additive,
                        "additive_wt": additive_wt,
                        "run_tier": exp.run_tier,
                    }
                )

        run_in_session(_collect)
    except Exception as exc:
        logger.error(f"Error fetching {metric_name} by temperature: {exc}", exc_info=True)

    from features.common.canonical_ordering import stable_sort_records

    points = stable_sort_records(
        points,
        ["temperature_k", "additive", "additive_wt"],
        exp_id_key="exp_id",
    )

    # Get unique temperatures
    temperatures = sorted({p["temperature_k"] for p in points})

    return {
        "metric_name": metric_name,
        "ff_type": ff_type,
        "additive_filter": additive_mol_id,
        "temperatures": temperatures,
        "points": points,
    }


async def get_property_by_additive(
    metric_name: str,
    *,
    ff_type: str = "bulk_ff_gaff2",
    temperature_k: float | None = None,
) -> dict:
    """Get property values grouped by additive type.

    Args:
        metric_name: Name of the metric (e.g., 'density', 'cohesive_energy_density')
        ff_type: Force field type filter
        temperature_k: Optional temperature filter (None = all)

    Returns:
        Dict with additives and corresponding metric values
    """
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

    additives_set: set[str] = set()
    points = []

    try:

        def _collect(session):
            nonlocal points, additives_set
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)
            name_map = _build_additive_name_map(session)

            all_exps = exp_repo.list_all(limit=2000)
            completed_exps = [
                e for e in all_exps if e.status == "completed" and e.ff_type == ff_type
            ]

            # Apply temperature filter if specified
            if temperature_k is not None:
                temp_tolerance = 5.0
                completed_exps = [
                    e
                    for e in completed_exps
                    if abs((e.temperature_K or 298.0) - temperature_k) <= temp_tolerance
                ]

            for exp in completed_exps:
                metric = metric_repo.get_by_name(exp.exp_id, metric_name)
                if not metric or metric.value is None:
                    continue

                additive, additive_wt = _resolve_additive_display(exp, name_map)

                additives_set.add(additive)
                points.append(
                    {
                        "exp_id": exp.exp_id,
                        "additive": additive,
                        "additive_wt": additive_wt,
                        "value": metric.value,
                        "uncertainty": metric.uncertainty,
                        "temperature_k": exp.temperature_K or 298.0,
                        "run_tier": exp.run_tier,
                    }
                )

        run_in_session(_collect)
    except Exception as exc:
        logger.error(f"Error fetching {metric_name} by additive: {exc}", exc_info=True)

    from features.common.canonical_ordering import canonical_value_key, stable_sort_records

    points = stable_sort_records(
        points,
        ["additive", "additive_wt", "temperature_k"],
        exp_id_key="exp_id",
    )

    # Sort additives with 'none' first using canonical ordering
    additives = sorted(additives_set, key=lambda a: canonical_value_key("additive", a))

    return {
        "metric_name": metric_name,
        "ff_type": ff_type,
        "temperature_filter": temperature_k,
        "additives": additives,
        "points": points,
    }
