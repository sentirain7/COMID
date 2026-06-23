"""Analytics query logic for layered structure experiments."""

from __future__ import annotations

# =============================================================================
# Layer type inference helpers
# =============================================================================

# Mapping from tuple of source_types -> LayerType contract enum values (SSOT).
# Values MUST match contracts.schemas.LayerType exactly (hyphenated).
_LAYER_TYPE_MAP: dict[tuple[str, ...], str] = {
    ("crystal_structure", "binder_cell"): "interface",
    ("crystal_structure", "amorphous_cell", "binder_cell"): "water-interface",
    ("crystal_structure", "binder_cell", "crystal_structure"): "3-layer",
    ("crystal_structure", "binder_cell", "binder_cell"): "aged-fresh",
    ("crystal_structure", "amorphous_cell", "binder_cell", "binder_cell"): "water-aged-fresh",
    ("binder_cell", "binder_cell"): "binder-binder",
}


def _infer_layer_type(sources: list) -> str | None:
    """Infer layer_type label from ordered source_type tuple, using is_water_like metadata."""
    normalized = []
    for s in sources:
        if getattr(s, "is_water_like", False):
            normalized.append("amorphous_cell")  # legacy key for map compat
        else:
            st = s.source_type
            normalized.append(st.value if hasattr(st, "value") else str(st))
    return _LAYER_TYPE_MAP.get(tuple(normalized))


def _has_water_layer(sources: list) -> bool:
    """Check if any layer is a water-like interlayer."""
    return any(getattr(s, "is_water_like", False) for s in sources)


# =============================================================================
# Public query functions
# =============================================================================


def list_layered_experiments(
    *,
    status: str | None = None,
    limit: int = 200,
) -> dict:
    """List layered experiments with layer sources and key metrics.

    Args:
        status: Filter by experiment status. If None, return all statuses.
        limit: Maximum number of experiments to return.
    """
    from api.utils.time_utils import to_utc_iso
    from database.models import MetricModel
    from database.models.experiment import ExperimentModel
    from database.models.structure import LayeredExperimentSourceModel
    from features.common import run_in_session
    from features.common.box_dims import parse_box_from_data_file

    def _query(session):
        # Find exp_ids that have layered lineage rows
        layered_exp_ids = session.query(LayeredExperimentSourceModel.exp_id).distinct().subquery()

        base = session.query(ExperimentModel).filter(
            ExperimentModel.exp_id.in_(session.query(layered_exp_ids)),
        )
        if status is not None:
            base = base.filter(ExperimentModel.status == status)

        experiments = (
            base.order_by(ExperimentModel.created_at.desc()).limit(max(1, min(limit, 500))).all()
        )

        if not experiments:
            return {"total": 0, "items": []}

        exp_ids = [exp.exp_id for exp in experiments]

        # Batch load all sources (1 query instead of N)
        all_sources = (
            session.query(LayeredExperimentSourceModel)
            .filter(LayeredExperimentSourceModel.exp_id.in_(exp_ids))
            .order_by(
                LayeredExperimentSourceModel.exp_id,
                LayeredExperimentSourceModel.layer_index,
            )
            .all()
        )
        sources_by_exp: dict[str, list] = {}
        for s in all_sources:
            sources_by_exp.setdefault(s.exp_id, []).append(s)

        # Batch load all metrics (1 query instead of N)
        metric_names = [
            "density",
            "cohesive_energy_density",
            "e_inter_total",
            "tensile_strength",
            "elastic_modulus",
            "ductility",
            "toughness",
            "work_of_separation",
            "interfacial_tensile_strength",
        ]
        all_metrics = (
            session.query(MetricModel.exp_id, MetricModel.metric_name, MetricModel.value)
            .filter(
                MetricModel.exp_id.in_(exp_ids),
                MetricModel.metric_name.in_(metric_names),
            )
            .all()
        )
        metrics_by_exp: dict[str, dict[str, float]] = {}
        for r in all_metrics:
            metrics_by_exp.setdefault(r.exp_id, {})[r.metric_name] = r.value

        # Assemble response items (no additional DB queries)
        items = []
        for exp in experiments:
            sources = sources_by_exp.get(exp.exp_id, [])
            layers = [
                {
                    "layer_index": s.layer_index,
                    "source_type": s.source_type,
                    "source_id": s.source_id,
                    "label": s.label,
                    "gap_after_angstrom": s.gap_after_angstrom,
                }
                for s in sources
            ]

            # Box dims (read-only — no DB mutation on GET)
            box_lx = getattr(exp, "box_lx", None)
            box_ly = getattr(exp, "box_ly", None)
            box_lz = getattr(exp, "box_lz", None)
            if box_lx is None or box_ly is None or box_lz is None:
                dims = parse_box_from_data_file(getattr(exp, "data_file_path", None))
                if dims:
                    box_lx, box_ly, box_lz = dims

            metrics_dict = metrics_by_exp.get(exp.exp_id, {})
            metadata = dict(exp.metadata_json or {})
            name = metadata.get("name") or exp.exp_id

            items.append(
                {
                    "exp_id": exp.exp_id,
                    "name": name,
                    "status": exp.status,
                    "temperature_K": exp.temperature_K,
                    "completed_at": to_utc_iso(exp.completed_at),
                    "box_lx": box_lx,
                    "box_ly": box_ly,
                    "box_lz": box_lz,
                    "layer_count": len(layers),
                    "layers": layers,
                    **{mn: metrics_dict.get(mn) for mn in metric_names},
                }
            )

        return {"total": len(items), "items": items}

    return run_in_session(_query)


def _build_layered_rows(  # noqa: C901
    session,
    *,
    temp_min: float | None = None,
    temp_max: float | None = None,
) -> list[dict]:
    """Build enriched layered experiment rows from *session*.

    Returns ALL candidates (temperature-filtered only, no categorical filter,
    no limit).  Callers apply their own categorical filters and limits.
    """
    from common.pathing import BINDER_ABBREV_REVERSE, parse_exp_id
    from contracts.policies.ghg import GHGPolicy  # noqa: F811
    from database.models import MetricModel
    from database.models.experiment import ExperimentModel
    from database.models.structure import CrystalStructureModel, LayeredExperimentSourceModel
    from features.analysis.service import (
        _batch_load_mol_fractions,
        _compute_ghg_for_experiment,
        _get_ghg_policy,
    )

    # 1. Find all layered exp_ids
    layered_exp_ids = session.query(LayeredExperimentSourceModel.exp_id).distinct().subquery()

    q = session.query(ExperimentModel).filter(
        ExperimentModel.exp_id.in_(session.query(layered_exp_ids)),
        ExperimentModel.status == "completed",
    )
    if temp_min is not None:
        q = q.filter(ExperimentModel.temperature_K >= temp_min)
    if temp_max is not None:
        q = q.filter(ExperimentModel.temperature_K <= temp_max)
    experiments = q.order_by(ExperimentModel.completed_at.desc().nullslast()).all()

    if not experiments:
        return []

    exp_ids = [exp.exp_id for exp in experiments]

    # 2. Batch load all layer sources
    all_sources = (
        session.query(LayeredExperimentSourceModel)
        .filter(LayeredExperimentSourceModel.exp_id.in_(exp_ids))
        .order_by(
            LayeredExperimentSourceModel.exp_id,
            LayeredExperimentSourceModel.layer_index,
        )
        .all()
    )
    sources_by_exp: dict[str, list] = {}
    for s in all_sources:
        sources_by_exp.setdefault(s.exp_id, []).append(s)

    # 3. Batch load metrics
    metric_names = [
        "density",
        "cohesive_energy_density",
        "e_inter_total",
        "tensile_strength",
        "elastic_modulus",
        "ductility",
        "toughness",
        "work_of_separation",
        "interfacial_tensile_strength",
    ]
    all_metrics = (
        session.query(MetricModel.exp_id, MetricModel.metric_name, MetricModel.value)
        .filter(
            MetricModel.exp_id.in_(exp_ids),
            MetricModel.metric_name.in_(metric_names),
        )
        .all()
    )
    metrics_by_exp: dict[str, dict[str, float]] = {}
    for r in all_metrics:
        metrics_by_exp.setdefault(r.exp_id, {})[r.metric_name] = r.value

    # 4. Batch load crystal structure info
    crystal_source_ids: set[str] = set()
    for sources in sources_by_exp.values():
        for s in sources:
            if s.source_type == "crystal_structure" and s.source_id:
                crystal_source_ids.add(s.source_id)

    crystal_info: dict[str, dict] = {}
    if crystal_source_ids:
        crystals = (
            session.query(
                CrystalStructureModel.crystal_id,
                CrystalStructureModel.material,
                CrystalStructureModel.surface,
            )
            .filter(CrystalStructureModel.crystal_id.in_(list(crystal_source_ids)))
            .all()
        )
        for c in crystals:
            crystal_info[c.crystal_id] = {"material": c.material, "surface": c.surface}

    # 5. Batch load binder source experiments for GHG
    binder_source_ids: set[str] = set()
    for sources in sources_by_exp.values():
        for s in sources:
            if s.source_type == "binder_cell" and s.source_id:
                binder_source_ids.add(s.source_id)

    binder_exps: dict[str, ExperimentModel] = {}
    if binder_source_ids:
        binder_rows = (
            session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id.in_(list(binder_source_ids)))
            .all()
        )
        for be in binder_rows:
            binder_exps[be.exp_id] = be

    ghg_policy: GHGPolicy | None = None
    mol_fractions_cache: dict[int, list[tuple[str, float]]] = {}
    try:
        ghg_policy = _get_ghg_policy()
        binder_int_ids = [be.id for be in binder_exps.values()]
        if binder_int_ids:
            mol_fractions_cache = _batch_load_mol_fractions(session, binder_int_ids)
    except Exception:
        ghg_policy = None

    # 6. Assemble rows
    rows: list[dict] = []
    for exp in experiments:
        sources = sources_by_exp.get(exp.exp_id, [])
        if not sources:
            continue

        layer_type = _infer_layer_type(sources)
        has_water = _has_water_layer(sources)

        crystal_material: str | None = None
        crystal_surface: str | None = None
        for s in sources:
            if s.source_type == "crystal_structure" and s.source_id:
                ci = crystal_info.get(s.source_id)
                if ci:
                    crystal_material = ci["material"]
                    crystal_surface = ci["surface"]
                break

        metadata = dict(exp.metadata_json or {})
        binder_type: str | None = metadata.get("binder_type")
        aging_state: str | None = metadata.get("aging_state")
        binder_type_secondary: str | None = None
        aging_state_secondary: str | None = None
        name = metadata.get("name") or exp.exp_id

        binder_sources = [s for s in sources if s.source_type == "binder_cell" and s.source_id]
        for idx, bs in enumerate(binder_sources):
            try:
                parsed = parse_exp_id(bs.source_id)
                raw_bt = parsed.get("binder_type")
                norm_bt = BINDER_ABBREV_REVERSE.get(raw_bt, raw_bt) if raw_bt else None
                norm_ag = parsed.get("aging_state")
                if idx == 0:
                    if not binder_type:
                        binder_type = norm_bt
                    if not aging_state:
                        aging_state = norm_ag
                elif idx == 1:
                    binder_type_secondary = norm_bt
                    aging_state_secondary = norm_ag
            except Exception:
                pass

        if binder_type:
            binder_type = BINDER_ABBREV_REVERSE.get(binder_type, binder_type)

        additive_type = exp.additive_type
        additive_wt = float(exp.additive_wt or 0.0)

        ghg_emission: float | None = None
        if ghg_policy and binder_sources:
            ghg_values = []
            for bs in binder_sources:
                be = binder_exps.get(bs.source_id)
                if be:
                    v = _compute_ghg_for_experiment(be, ghg_policy, mol_fractions_cache)
                    if v is not None:
                        ghg_values.append(v)
            if ghg_values:
                ghg_emission = sum(ghg_values) / len(ghg_values)

        metrics_dict = metrics_by_exp.get(exp.exp_id, {})

        rows.append(
            {
                "exp_id": exp.exp_id,
                "name": name,
                "temperature_K": exp.temperature_K,
                "layer_type": layer_type,
                "layer_count": len(sources),
                "crystal_material": crystal_material,
                "crystal_surface": crystal_surface,
                "binder_type": binder_type,
                "aging_state": aging_state,
                "binder_type_secondary": binder_type_secondary,
                "aging_state_secondary": aging_state_secondary,
                "additive_type": additive_type,
                "additive_wt": additive_wt if additive_wt > 0 else None,
                "has_water": has_water,
                "density": metrics_dict.get("density"),
                "cohesive_energy_density": metrics_dict.get("cohesive_energy_density"),
                "e_inter_total": metrics_dict.get("e_inter_total"),
                "tensile_strength": metrics_dict.get("tensile_strength"),
                "elastic_modulus": metrics_dict.get("elastic_modulus"),
                "ductility": metrics_dict.get("ductility"),
                "toughness": metrics_dict.get("toughness"),
                "work_of_separation": metrics_dict.get("work_of_separation"),
                "interfacial_tensile_strength": metrics_dict.get("interfacial_tensile_strength"),
                "tensile_strain_rate_1_per_ps": getattr(exp, "tensile_strain_rate_1_per_ps", None),
                "tensile_pull_velocity_a_per_fs": getattr(
                    exp, "tensile_pull_velocity_a_per_fs", None
                ),
                "shear_rate_1_per_ps": getattr(exp, "shear_rate_1_per_ps", None),
                "ghg_emission": ghg_emission,
            }
        )

    return rows


def get_layered_analysis_3d(
    *,
    layer_types: list[str] | None = None,
    crystal_materials: list[str] | None = None,
    aging_states: list[str] | None = None,
    temp_min: float | None = None,
    temp_max: float | None = None,
    limit: int = 500,
) -> dict:
    """Aggregated layered experiment data for 3D multi-variable analysis.

    Returns points with mechanical metrics, GHG, and categorical metadata
    for interactive 3D scatter visualization.
    """
    from features.common import run_in_session

    def _query(session):  # noqa: C901
        from features.common.canonical_ordering import (
            canonical_value_key,
            stable_sort_records,
        )

        # Use shared helper to build all enriched rows
        candidates = _build_layered_rows(session, temp_min=temp_min, temp_max=temp_max)

        if not candidates:
            return {
                "total": 0,
                "matched_total": 0,
                "returned_total": 0,
                "available_layer_types": [],
                "available_crystal_materials": [],
                "available_aging_states": [],
                "available_binder_types": [],
                "temp_range": None,
                "items": [],
            }

        # Pass 1: Collect available_* from FULL candidate universe
        all_layer_types: set[str] = set()
        all_crystal_materials: set[str] = set()
        all_aging_states: set[str] = set()
        all_binder_types: set[str] = set()
        all_temps: list[float] = []

        for rec in candidates:
            if rec.get("layer_type"):
                all_layer_types.add(rec["layer_type"])
            if rec.get("crystal_material"):
                all_crystal_materials.add(rec["crystal_material"])
            if rec.get("aging_state"):
                all_aging_states.add(rec["aging_state"])
            if rec.get("aging_state_secondary"):
                all_aging_states.add(rec["aging_state_secondary"])
            if rec.get("binder_type"):
                all_binder_types.add(rec["binder_type"])
            if rec.get("temperature_K") is not None:
                all_temps.append(rec["temperature_K"])

        # Pass 2: Apply categorical filters → display items
        items: list[dict] = []
        for rec in candidates:
            if layer_types and (rec["layer_type"] not in layer_types):
                continue
            if crystal_materials and (rec["crystal_material"] not in crystal_materials):
                continue
            if aging_states:
                matched = (rec["aging_state"] in aging_states) or (
                    rec["aging_state_secondary"] is not None
                    and rec["aging_state_secondary"] in aging_states
                )
                if not matched:
                    continue
            items.append(rec)

        matched_total = len(items)

        # Stable sort before limit
        items = stable_sort_records(
            items,
            ["layer_type", "crystal_material", "temperature_K"],
            exp_id_key="exp_id",
        )

        # Apply limit AFTER all filters
        effective_limit = max(1, min(limit, 1000))
        items = items[:effective_limit]

        temp_range: list[float] | None = None
        if all_temps:
            temp_range = [min(all_temps), max(all_temps)]

        return {
            "total": len(items),
            "matched_total": matched_total,
            "returned_total": len(items),
            "available_layer_types": sorted(
                all_layer_types, key=lambda v: canonical_value_key("layer_type", v)
            ),
            "available_crystal_materials": sorted(all_crystal_materials),
            "available_aging_states": sorted(
                all_aging_states, key=lambda v: canonical_value_key("aging_state", v)
            ),
            "available_binder_types": sorted(all_binder_types),
            "temp_range": temp_range,
            "items": items,
        }

    return run_in_session(_query)


# =============================================================================
# 계면 지표 replica 앙상블 (보완 #4, 원칙 9)
# =============================================================================


def aggregate_layered_replicate_metrics(
    exp_ids: list[str],
    *,
    metric_names: list[str] | None = None,
) -> list[dict]:
    """동일 계면 설정의 replica(seed/변형률) 실험 묶음을 mean ± SE ensemble 로 집계.

    확률적 계면 mechanical 지표(``work_of_separation``·
    ``interfacial_tensile_strength`` 등)는 단일 실행이 아니라 다중 replica 의
    mean ± standard error 로 보고해야 한다(원칙 9). 본 함수는 호출자가 명시한
    replica exp_id 묶음에 대해 레지스트리의 replica-필수 지표를
    ``metrics.interface_replicate`` SSOT 로 집계한다.

    (어떤 실험들이 서로 replica 인지 자동 그룹핑하는 로직은 별도 — 현재는
    호출자가 동일 설정/온도/프로토콜·다른 seed 묶음을 제공한다.)

    Args:
        exp_ids: 같은 설정의 replica 실험 ID 묶음.
        metric_names: 집계 대상 한정(기본: 레지스트리 replica-필수 지표 전체).

    Returns:
        지표·계면별 ensemble dict 리스트(mean/standard_error/n_replicates/
        meets_min_replicates/CI 등). 입력이 비면 빈 리스트.
    """
    from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
    from contracts.schemas import MetricResult
    from database.models import MetricModel
    from features.common import run_in_session
    from metrics.interface_replicate import aggregate_interface_replicates

    targets = (
        list(metric_names) if metric_names else DEFAULT_METRICS_REGISTRY.replica_required_metrics()
    )
    if not exp_ids or not targets:
        return []

    def _query(session):
        rows = (
            session.query(
                MetricModel.exp_id,
                MetricModel.metric_name,
                MetricModel.value,
                MetricModel.interface_index,
                MetricModel.layer_index,
            )
            .filter(
                MetricModel.exp_id.in_(exp_ids),
                MetricModel.metric_name.in_(targets),
            )
            .all()
        )
        return [
            MetricResult(
                exp_id=r.exp_id,
                metric_name=r.metric_name,
                value=r.value,
                unit=DEFAULT_METRICS_REGISTRY.get_unit(r.metric_name),
                namespace=DEFAULT_METRICS_REGISTRY.get_namespace(r.metric_name).value,
                interface_index=r.interface_index,
                layer_index=r.layer_index,
            )
            for r in rows
        ]

    per_seed = run_in_session(_query)
    results = aggregate_interface_replicates(per_seed, metric_names=targets)
    # C-1: 통계 dict는 ReplicateMetricResult.stats_metadata() SSOT를 재사용하고
    # provenance(metric/namespace/interface/layer)만 덧붙인다(인라인 중복 제거).
    return [
        {
            "metric_name": r.metric_name,
            "namespace": r.namespace,
            "interface_index": r.interface_index,
            "layer_index": r.layer_index,
            **r.stats_metadata(),
        }
        for r in results
    ]
