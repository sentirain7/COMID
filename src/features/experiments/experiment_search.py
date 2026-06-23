"""Experiment search, pagination, and composition query helpers.

Extracted from query.py — search/query logic for experiments.
"""

from common.logging import get_logger

logger = get_logger("features.experiments.experiment_search")


def _as_percent(value: float) -> float:
    """Normalize composition values to percent scale for comparison."""
    if 0.0 <= value <= 1.0:
        return value * 100.0
    return value


def list_experiments_paginated(
    *,
    status: str | None = None,
    run_tier: str | None = None,
    ff_type: str | None = None,
    min_temperature: float | None = None,
    max_temperature: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List experiments with DB filtering and pagination.

    Returns:
        Dict with keys: models, total_count.
    """
    from database.connection import get_session
    from database.models import ExperimentModel

    session = get_session()
    try:
        query = session.query(ExperimentModel)

        if status:
            query = query.filter(ExperimentModel.status == status)
        if run_tier:
            query = query.filter(ExperimentModel.run_tier == run_tier)
        if ff_type:
            query = query.filter(ExperimentModel.ff_type == ff_type)
        if min_temperature is not None:
            query = query.filter(ExperimentModel.temperature_K >= min_temperature)
        if max_temperature is not None:
            query = query.filter(ExperimentModel.temperature_K <= max_temperature)

        total_count = query.count()
        models = query.order_by(ExperimentModel.created_at.desc()).limit(limit).offset(offset).all()

        return {"models": models, "total_count": total_count}
    finally:
        session.close()


def search_by_composition(
    target: dict[str, float],
    tolerance: float = 5.0,
    limit: int = 20,
) -> list:
    """Find experiments with similar composition using L1 distance.

    Args:
        target: Dict with keys asphaltene, resin, aromatic, saturate (wt%).
        tolerance: Maximum L1 distance to include.
        limit: Maximum number of results.

    Returns:
        List of ExperimentModel objects sorted by L1 distance.
    """
    from database.connection import get_session
    from database.models import ExperimentModel

    normed_target = {k: _as_percent(v) for k, v in target.items()}

    session = get_session()
    try:
        models = session.query(ExperimentModel).all()
        scored: list[tuple[float, object]] = []
        for model in models:
            model_comp = {
                "asphaltene": _as_percent(model.comp_asphaltene_wt),
                "resin": _as_percent(model.comp_resin_wt),
                "aromatic": _as_percent(model.comp_aromatic_wt),
                "saturate": _as_percent(model.comp_saturate_wt),
            }
            l1 = sum(abs(model_comp[k] - normed_target[k]) for k in normed_target)
            if l1 <= tolerance:
                scored.append((l1, model))

        scored.sort(key=lambda item: item[0])
        return [model for _, model in scored[:limit]]
    finally:
        session.close()


def calculate_composition_from_library(
    composition: dict[str, float],
    target_atoms: int,
    db,
    config: dict | None,
) -> dict:
    """Calculate molecule counts for a target SARA composition.

    Args:
        composition: Dict with keys asphaltene, resin, aromatic, saturate (wt%).
        target_atoms: Target total atom count.
        db: MoleculeDB instance.
        config: Aging config dict (may be None).

    Returns:
        Dict with keys: molecule_counts (list of dicts), total_atoms, total_mass,
        actual_composition (dict), target_composition (dict), composition_error_l1.
    """
    from common.molecule_id import parse_molecule_id

    temp_code = db.get_temperature_code(config or {}, 298.0)

    categories = ["asphaltene", "resin", "aromatic", "saturate"]
    target_map = {cat: composition.get(cat, 0.0) for cat in categories}

    molecule_counts: list[dict] = []
    total_atoms = 0
    total_mass = 0.0
    achieved: dict[str, float] = dict.fromkeys(categories, 0.0)

    for category, target_wt in target_map.items():
        candidates = db.list_by_category(category)
        preferred = []
        for spec in candidates:
            try:
                parsed = parse_molecule_id(spec.mol_id)
                if parsed.temp_code == temp_code:
                    preferred.append(spec)
            except ValueError:
                pass
        preferred = preferred or candidates
        if not preferred:
            continue

        spec = preferred[0]
        if spec.molecular_weight <= 0 or spec.atom_count <= 0:
            continue

        target_atoms_for_category = max(1, int(target_atoms * (target_wt / 100.0)))
        count = max(1, int(target_atoms_for_category / spec.atom_count))
        atom_contribution = count * spec.atom_count
        mass_contribution = count * spec.molecular_weight

        total_atoms += atom_contribution
        total_mass += mass_contribution
        achieved[category] = mass_contribution

        molecule_counts.append(
            {
                "mol_id": spec.mol_id,
                "name": spec.paper_name or spec.mol_id,
                "category": category,
                "count": count,
                "atom_contribution": atom_contribution,
                "weight_fraction": 0.0,
            }
        )

    if total_mass > 0:
        for mc in molecule_counts:
            mc["weight_fraction"] = (achieved[mc["category"]] / total_mass) * 100.0

    actual_composition = {
        cat: (achieved[cat] / total_mass * 100.0 if total_mass else 0.0) for cat in categories
    }
    l1 = sum(abs(actual_composition[k] - composition.get(k, 0.0)) for k in categories)

    return {
        "molecule_counts": molecule_counts,
        "total_atoms": total_atoms,
        "total_mass": total_mass,
        "actual_composition": actual_composition,
        "target_composition": {cat: composition.get(cat, 0.0) for cat in categories},
        "composition_error_l1": l1,
    }


def count_experiments_by_status() -> dict[str, int]:
    """Get experiment counts grouped by status.

    Returns:
        Dict with keys: pending, running, completed, failed.
    """
    from database.connection import get_session
    from database.repositories.experiment_repo import ExperimentRepository

    session = get_session()
    try:
        repo = ExperimentRepository(session)
        counts = repo.count_by_status()
        return {
            "pending": counts.get("pending", 0) + counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Similar experiment detection for batch submission
# ---------------------------------------------------------------------------


def find_similar_experiments(
    session,
    binder_type: str,
    aging_state: str,
    additive_mol_id: str | None,
    additive_wt: float,
    temperature_k: float,
    *,
    temperature_tolerance: float = 5.0,
    limit: int = 10,
) -> list:
    """유사한 binder+aging+additive+온도 조합의 completed 실험 검색.

    비교 기준:
    - binder_type: 정확 일치 (metadata_json.binder_type)
    - aging_state: 정확 일치 (metadata_json.aging_state)
    - additive_mol_id: 정확 일치 (None = 무첨가)
    - additive_wt: 정확 일치
    - temperature_k: ±tolerance 범위
    - status: completed만 (failed/cancelled 제외)

    Args:
        session: SQLAlchemy session
        binder_type: 바인더 타입 (예: AAA1)
        aging_state: 노화 상태 (예: non_aging)
        additive_mol_id: 첨가제 mol_id (None = 무첨가)
        additive_wt: 첨가제 wt%
        temperature_k: 목표 온도 (K)
        temperature_tolerance: 온도 허용 오차 (K)
        limit: 반환 최대 개수

    Returns:
        ExperimentModel 리스트
    """
    from database.models import ExperimentModel

    query = session.query(ExperimentModel).filter(
        ExperimentModel.status == "completed",
        ExperimentModel.temperature_K >= temperature_k - temperature_tolerance,
        ExperimentModel.temperature_K <= temperature_k + temperature_tolerance,
    )

    # additive_mol_id 조건
    if additive_mol_id is None:
        query = query.filter(
            (ExperimentModel.additive_mol_id.is_(None)) | (ExperimentModel.additive_mol_id == "")
        )
    else:
        query = query.filter(ExperimentModel.additive_mol_id == additive_mol_id)

    # additive_wt 조건 (부동소수점 허용 오차 0.01)
    query = query.filter(
        ExperimentModel.additive_wt >= additive_wt - 0.01,
        ExperimentModel.additive_wt <= additive_wt + 0.01,
    )

    # metadata_json에서 binder_type, aging_state 필터링
    # JSON 필드 쿼리를 위해 Python 레벨에서 필터링
    candidates = query.order_by(ExperimentModel.created_at.desc()).limit(limit * 5).all()

    results = []
    for exp in candidates:
        meta = exp.metadata_json or {}
        exp_binder = meta.get("binder_type", "")
        exp_aging = meta.get("aging_state", "")
        if exp_binder == binder_type and exp_aging == aging_state:
            results.append(exp)
            if len(results) >= limit:
                break

    return results


def find_similar_experiments_batch(
    session,
    jobs_to_check: list[dict],
    *,
    temperature_tolerance: float = 5.0,
    limit_per_job: int = 10,
) -> dict[str, list]:
    """여러 작업에 대해 유사 실험을 일괄 검색.

    Args:
        session: SQLAlchemy session
        jobs_to_check: 검사할 작업 리스트 (각각 binder_type, aging_state,
                       additive_mol_id, additive_wt, temperature_k 키 포함)
        temperature_tolerance: 온도 허용 오차 (K)
        limit_per_job: 작업당 반환 최대 개수

    Returns:
        {exp_id: [similar_exp_ids]} 딕셔너리
    """
    result_map: dict[str, list] = {}

    for job in jobs_to_check:
        exp_id = job.get("exp_id", "")
        similar = find_similar_experiments(
            session=session,
            binder_type=job.get("binder_type", ""),
            aging_state=job.get("aging_state", ""),
            additive_mol_id=job.get("additive_mol_id"),
            additive_wt=job.get("additive_wt", 0.0),
            temperature_k=job.get("temperature_k", 298.0),
            temperature_tolerance=temperature_tolerance,
            limit=limit_per_job,
        )
        result_map[exp_id] = [s.exp_id for s in similar]

    return result_map
