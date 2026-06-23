"""역설계 파이프라인 서비스 — 계획 미리보기 (P1, dry-run).

계획 §4.2 ①~③을 stateless로 조립한다 (§4.5 모드 판정, §5 실험 편성,
§4.7 존재확인, §4.6 plan_hash). DB 쓰기/제출은 하지 않는다 — 제출은
P2(approve_and_run)가 plan_hash 재검증 후 수행한다.
"""

from typing import Any

from api.schemas import InverseDesignRequest
from common.hashing import compute_content_hash
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode
from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    InversePipelinePolicy,
    PipelineMode,
    PlannedExperimentKind,
)
from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from features.inverse_design_pipeline import queries

logger = get_logger(__name__)

PLAN_SCHEMA_VERSION = "1"
PLAN_HASH_LENGTH = 16


def compute_plan_hash(plan: dict) -> str:
    """계획 문서의 결정적 해시 (§4.6 — approve 시 재검증에 사용)."""
    return compute_content_hash(plan, length=PLAN_HASH_LENGTH)


def policy_snapshot(policy: InversePipelinePolicy) -> dict:
    """계획서에 동봉되는 정책 스냅샷 (§4.6 — approve 시 정책 변경 감지 SSOT).

    실험 구조를 결정하는 모든 필드를 포함해야 한다 — 누락 필드는 배포 중
    정책이 바뀌어도 approve gate를 통과하는 silent drift가 된다 (R-P1-2).
    """
    return {
        "cold_start": policy.cold_start.model_dump(),
        "similarity": policy.similarity.model_dump(),
        "default_temperature_k": policy.default_temperature_k,
        "tg_temperature_sweep_k": list(policy.tg_temperature_sweep_k),
        "viscosity_stage_metrics": list(policy.viscosity_stage_metrics),
        "multi_temperature_metrics": list(policy.multi_temperature_metrics),
        "moisture": policy.moisture.model_dump(),
        "candidate_binder_types": list(policy.candidate_binder_types),
        "additive_wt_grid": list(policy.additive_wt_grid),
    }


def decide_pipeline_mode(
    target_metrics: list[str],
    *,
    capability_manifest: dict | None,
    label_counts: dict[str, int],
    label_counts_available: bool = True,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
) -> tuple[PipelineMode, dict]:
    """BOOTSTRAP/BO 모드를 결정론적으로 판정한다 (§4.5).

    BOOTSTRAP 진입 조건 (하나라도 해당):
    - champion capability manifest 부재 (모델 미등록)
    - 표적 metric 중 champion 미지원이 존재
    - 표적 metric 중 학습 라벨 수 < n_min_labels

    Args:
        target_metrics: 표적 metric 이름 리스트
        capability_manifest: champion capability manifest (None = 모델 없음)
        label_counts: metric별 completed 라벨 수
        label_counts_available: DB 조회 성공 여부 (실패 시 보수적 BOOTSTRAP)
        policy: 파이프라인 정책 (SSOT)

    Returns:
        (모드, 판정 근거 dict) — 근거는 계획서에 그대로 노출되어 감사가능
    """
    n_min = policy.cold_start.n_min_labels

    supported: set[str] = set()
    if capability_manifest:
        supported = {str(name) for name in capability_manifest.get("supported_targets", []) if name}
    unsupported = [m for m in target_metrics if m not in supported]
    counts = {m: int(label_counts.get(m, 0)) for m in target_metrics}
    label_starved = sorted(m for m, c in counts.items() if c < n_min)

    rationale: dict[str, Any] = {
        "n_min_labels": n_min,
        "champion_available": bool(supported),
        "unsupported_targets": unsupported,
        "label_counts": counts,
        "label_counts_available": label_counts_available,
        "label_starved_targets": label_starved,
    }

    if not supported or unsupported or label_starved or not label_counts_available:
        return PipelineMode.BOOTSTRAP, rationale
    return PipelineMode.BO, rationale


async def preview_plan(
    request: InverseDesignRequest,
    *,
    moisture_damage: bool = False,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
    session=None,
) -> dict:
    """역설계 파이프라인 계획 미리보기 (dry-run, 제출 없음).

    Args:
        request: 역설계 요청 (custom_targets 필수)
        moisture_damage: 수분손상 트랙 활성 — 계면 실험에 wet 페어 편성 (§2)
        policy: 파이프라인 정책 (SSOT)
        session: SQLAlchemy session (None이면 session_scope 자체 개설)

    Returns:
        {"plan": 계획 문서(JSON-호환 dict), "plan_hash": 결정적 해시}

    Raises:
        ContractError: 표적 무효 / 미지원 namespace / 계면 표적인데
            aggregate_specs 부재
    """
    from features.recommendations.inverse_design import resolve_property_target_set

    target_set = resolve_property_target_set(request)
    ok, errors = target_set.validate_against_registry()
    if not ok:
        raise ContractError(ErrorCode.INVALID_REQUEST, f"Invalid targets: {errors}")

    target_metrics = [t.metric_name for t in target_set.targets]
    metric_kinds = _experiment_kinds_for_targets(target_metrics, policy)

    needs_layered = any(
        kind == PlannedExperimentKind.LAYERED_TENSILE for kind in metric_kinds.values()
    )
    if needs_layered and not request.aggregate_specs:
        layered_metrics = [
            m for m, k in metric_kinds.items() if k == PlannedExperimentKind.LAYERED_TENSILE
        ]
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Targets {layered_metrics} require layered (interface) experiments: "
            "provide aggregate_specs (crystal material/surface).",
        )

    # ── 모드 판정 (§4.5) ──
    capability_manifest = _get_capability_manifest()
    label_counts, label_counts_available = _count_labels(target_metrics, session=session)
    mode, mode_rationale = decide_pipeline_mode(
        target_metrics,
        capability_manifest=capability_manifest,
        label_counts=label_counts,
        label_counts_available=label_counts_available,
        policy=policy,
    )

    # ── 후보 (① 의사결정 또는 DOE 시드) — (binder_type, additive, wt) 조합 ──
    if mode == PipelineMode.BO:
        candidates, design_meta = _bo_candidates(request, target_set=target_set, policy=policy)
    else:
        candidates, design_meta = _bootstrap_candidates(request, policy)

    # ── §5 실험 편성 + §4.7 존재확인 ──
    experiments = _derive_experiments(
        candidates,
        request=request,
        target_metrics=target_metrics,
        metric_kinds=metric_kinds,
        moisture_damage=moisture_damage,
        policy=policy,
        session=session,
    )

    plan = {
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "mode": mode.value,
        "mode_rationale": mode_rationale,
        "targets": [
            {
                "metric_name": t.metric_name,
                "target_min": t.target_min,
                "target_max": t.target_max,
                "direction": t.direction,
                "weight": t.weight,
                "unit": DEFAULT_METRICS_REGISTRY.get_unit(t.metric_name),
                "namespace": DEFAULT_METRICS_REGISTRY.get_namespace(t.metric_name).value,
                "experiment_kind": metric_kinds[t.metric_name].value,
            }
            for t in target_set.targets
        ],
        "candidates": candidates,
        "experiments": experiments,
        "moisture_damage": {
            "enabled": moisture_damage,
            "er_warn_threshold": policy.moisture.er_warn_threshold,
            "er_fail_threshold": policy.moisture.er_fail_threshold,
        },
        "design": design_meta,
        "policy_snapshot": policy_snapshot(policy),
        "request_echo": request.model_dump(mode="json", exclude_none=True),
    }
    return {"plan": plan, "plan_hash": compute_plan_hash(plan)}


# ──────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────────────


def _experiment_kinds_for_targets(
    target_metrics: list[str], policy: InversePipelinePolicy
) -> dict[str, PlannedExperimentKind]:
    """metric → 편성 실험 종류 매핑 (§5). 미지원 namespace는 fail-fast."""
    kinds: dict[str, PlannedExperimentKind] = {}
    unmapped: list[tuple[str, str]] = []
    for metric in target_metrics:
        namespace = DEFAULT_METRICS_REGISTRY.get_namespace(metric).value
        kind = policy.experiment_kind_for_namespace(namespace)
        if kind is None:
            unmapped.append((metric, namespace))
        else:
            kinds[metric] = kind
    if unmapped:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Targets {[m for m, _ in unmapped]} belong to namespaces "
            f"{sorted({ns for _, ns in unmapped})} that the inverse-design "
            "pipeline does not orchestrate.",
        )
    return kinds


def _get_capability_manifest() -> dict | None:
    """champion capability manifest 조회 (없으면 None — BOOTSTRAP 신호)."""
    try:
        from api.deps import get_runtime_capability_manifest

        return get_runtime_capability_manifest()
    except Exception:
        return None


def _count_labels(target_metrics: list[str], *, session) -> tuple[dict[str, int], bool]:
    """metric별 라벨 수 집계. DB 실패 시 (0, available=False) — 보수적 BOOTSTRAP."""

    def _run(s) -> dict[str, int]:
        return {m: queries.count_training_labels(s, m) for m in target_metrics}

    try:
        from features.common import with_optional_session

        return with_optional_session(session, _run), True
    except Exception:
        logger.warning("Label-count query failed; treating targets as label-starved")
        return dict.fromkeys(target_metrics, 0), False


def _candidate_combinations(
    request: InverseDesignRequest, policy: InversePipelinePolicy
) -> list[dict]:
    """(binder_type × additive_type × 농도 그리드) 후보 조합 풀 (결정적 정렬).

    역설계 결정 변수는 정의 binder 선택 + 첨가제 종류/양 뿐이다 — SARA wt%는
    binder YAML SSOT가 결정하며 탐색하지 않는다. 무첨가 control(None, 0.0)은
    batch DOE 관행(`_generate_additive_combos`)과 동일하게 항상 포함한다.
    """
    from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS

    allowed = list(policy.candidate_binder_types)
    binders = list(request.binder_types) if request.binder_types else allowed
    invalid = [b for b in binders if b not in allowed]
    if invalid:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown binder types: {invalid}. Allowed: {allowed}",
        )

    if request.explore_all_additives:
        additives = _active_additive_ids()
    elif request.additive_type:
        additives = [request.additive_type]
    else:
        additives = []

    max_wt = float(DEFAULT_COMPOSITION_CONSTRAINTS.bounds.get("additive_total", (0.0, 10.0))[1])
    wt_grid = [float(w) for w in policy.additive_wt_grid if 0.0 < float(w) <= max_wt]

    combos: list[dict] = []
    for binder in binders:
        combos.append({"binder_type": binder, "additive_type": None, "additive_wt": 0.0})
        for additive in sorted(additives):
            for wt in wt_grid:
                combos.append({"binder_type": binder, "additive_type": additive, "additive_wt": wt})
    return combos


def _active_additive_ids() -> list[str]:
    """활성 첨가제 카탈로그의 mol_id 목록 (실패 시 빈 리스트 — 무첨가만 편성)."""
    try:
        from features.experiments.validation import load_active_additive_catalog

        return sorted(load_active_additive_catalog().keys())
    except Exception:
        logger.warning("Active additive catalog unavailable; planning binder-only candidates")
        return []


def _binder_sara_wt(binder_type: str) -> dict[str, float]:
    """binder YAML SSOT의 SARA fractions를 wt%로 반환 (표시·재사용 검색용).

    batch 경로가 comp_*_wt에 기록하는 값과 동일해야 재사용 검색이 매칭된다
    (`BatchJobBinderCellRunner._resolve_sara_wt` 재사용). plan 미리보기는 yaml
    config만 필요하므로 분자 라이브러리 전체 로드(get_molecule_db) 없이 빈
    MoleculeDB로 호출한다 (get_sara_fractions는 config-전용 위임).
    """
    from api.deps import get_aging_config
    from builder.molecule_db import MoleculeDB
    from orchestrator.batch_job_binder_cell import BatchJobBinderCellRunner

    config = get_aging_config()
    if not config:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Molecule library config unavailable; cannot resolve binder SARA fractions.",
        )
    return BatchJobBinderCellRunner._resolve_sara_wt(config, MoleculeDB(), binder_type)


def _combo_candidate(combo: dict, *, source: str, index: int) -> dict:
    """조합 → plan candidate dict (composition은 binder fractions 표시용)."""
    composition = {k: float(v) for k, v in _binder_sara_wt(combo["binder_type"]).items()}
    if combo["additive_type"] and combo["additive_wt"] > 0.0:
        composition["additive"] = float(combo["additive_wt"])
    return {
        "source": source,
        "seed_index": index,
        "binder_type": combo["binder_type"],
        "additive_type": combo["additive_type"],
        "additive_wt": float(combo["additive_wt"]),
        "composition": composition,
        "predicted_properties": None,
        "targets_satisfied": None,
        # V7 champion BO 경로에서만 채워짐(V7 피처공간 OOD soft flag). 그 외 None.
        "is_ood": None,
    }


def _bo_candidates(
    request: InverseDesignRequest,
    *,
    target_set,
    policy: InversePipelinePolicy,
) -> tuple[list[dict], dict]:
    """BO 모드: 조합 풀 전수를 champion으로 예측해 목표거리 순으로 랭킹 (§4.2 ①).

    조합 수가 작으므로(binder 3 × additive K × 그리드) 연속 BO 대신 전수
    예측·랭킹으로 충분하다. 예측 실패 조합은 거리 무한대로 뒤로 밀린다.
    """
    combos = _candidate_combinations(request, policy)
    feature_set, predictor_fn = _load_predictor()
    structure_size = getattr(request, "structure_size", None) or "X1"

    temperature_k = request.temperature_k_fixed or policy.default_temperature_k
    scored: list[tuple[float, dict, dict | None, bool | None, bool | None]] = []
    n_predicted = 0
    n_ood_flagged = 0
    for combo in combos:
        diag: dict = {}
        predictions = _predict_combo(
            predictor_fn,
            combo,
            temperature_k=temperature_k,
            feature_set=feature_set,
            structure_size=structure_size,
            diagnostics=diag,
        )
        is_ood = diag.get("is_ood")  # V7 champion만 산출, 그 외엔 None(미상)
        if predictions is not None:
            n_predicted += 1
            distance = float(sum(target_set.compute_distances(predictions).values()))
            satisfied = bool(target_set.are_all_satisfied(predictions))
            if is_ood:
                n_ood_flagged += 1
        else:
            distance, satisfied = float("inf"), None
        scored.append((distance, combo, predictions, satisfied, is_ood))

    # OOD는 soft flag — 랭킹은 거리 기준 그대로(후보 주석/감사 신호로만 노출).
    scored.sort(key=lambda item: item[0])
    top = scored[: request.n_results]

    candidates = []
    for i, (distance, combo, predictions, satisfied, is_ood) in enumerate(top):
        candidate = _combo_candidate(combo, source="bo", index=i)
        candidate["predicted_properties"] = predictions
        candidate["targets_satisfied"] = satisfied
        candidate["target_distance"] = None if distance == float("inf") else distance
        candidate["is_ood"] = is_ood
        candidates.append(candidate)

    design_meta = {
        "prediction_contract": feature_set,
        "feasibility": None,
        "pareto_front": None,
        "audit_log": {
            "strategy": "binder_additive_grid_ranking",
            "combination_pool": len(combos),
            "n_predicted": n_predicted,
            # V7 champion일 때만 의미있는 V7 피처공간 OOD soft-flag 수.
            "n_ood_flagged": n_ood_flagged,
            "ood_feature_space": feature_set if feature_set == "v7" else None,
            "n_results": request.n_results,
            "temperature_k": float(temperature_k),
        },
    }
    return candidates, design_meta


def _champion_feature_set() -> str | None:
    """champion capability manifest의 feature_set (없으면 None)."""
    manifest = _get_capability_manifest()
    if not manifest:
        return None
    value = manifest.get("feature_set")
    return str(value) if value else None


def _load_predictor():
    """champion predictor 로드 (BO 모드 전용 — 없으면 None, 후보는 무예측 랭킹).

    Returns:
        (feature_set, predictor_fn) — feature_set이 'v7'이면 _predict_combo가
        species_counts 기반 구조 피처 경로로 예측한다(structural champion).
    """
    try:
        from api.deps import get_ml_predictor_fn, get_ml_predictor_with_uncertainty_fn

        feature_set = _champion_feature_set()
        if feature_set == "v7":
            # V7 champion + MoleculeDB를 **BO 1회당 한 번만** 로드해 컨텍스트로
            # 반환 — _predict_combo_v7이 조합마다 재로딩하던 병목(조합당 ~60ms)
            # 제거. 조합은 같은 mtp/extractor를 재사용한다.
            from api.deps import _load_mtp, get_molecule_db
            from ml.structural_features import RDKIT_AVAILABLE, StructuralFeatureExtractor

            if not RDKIT_AVAILABLE:
                return "v7", None
            mtp = _load_mtp()
            if mtp is None:
                return "v7", None
            return "v7", {
                "mtp": mtp,
                "extractor": StructuralFeatureExtractor(get_molecule_db()),
            }
        predictor = get_ml_predictor_with_uncertainty_fn()
        return feature_set, (predictor or get_ml_predictor_fn())
    except Exception:
        logger.warning("Champion predictor unavailable; BO candidates ranked without predictions")
        return None, None


def _combo_species_counts(combo: dict, *, temperature_k: float, structure_size: str):
    """조합 → batch SSOT 분자 시스템(mol_id→count). 빌드 경로와 동일."""
    from .execution import _batch_binder_composition

    additive_mol_id = combo.get("additive_type")
    additive_wt = float(combo.get("additive_wt") or 0.0)
    if not (additive_mol_id and additive_wt > 0.0):
        additive_mol_id, additive_wt = None, 0.0
    mol_counts, _sara_wt = _batch_binder_composition(
        binder_type=combo["binder_type"],
        additive_mol_id=str(additive_mol_id) if additive_mol_id else None,
        additive_wt=additive_wt,
        temperature_k=temperature_k,
        structure_size=structure_size,
    )
    return mol_counts


def _v7_is_ood(result) -> bool | None:
    """predict_multi 결과의 V7 피처공간 OOD(soft flag) — 미산출 시 None(미상).

    ``predict_multi``는 ``actual_feature_set``('v7')에 맞는 detector로
    ``ood_results``를 이미 산출한다(multi_target). 여기서는 그 신호를 버리지
    않고 후보 주석으로 끌어올린다 — 어떤 표적이든 OOD면 후보를 OOD로 표시.
    """
    ood = getattr(result, "ood_results", None)
    if not ood:  # None 또는 빈 dict → detector 부재/미산출
        return None
    try:
        return any(bool(getattr(r, "is_ood", False)) for r in ood.values())
    except Exception:  # noqa: BLE001 - 진단 신호는 best-effort
        return None


def _predict_combo_v7(
    v7_ctx,
    combo: dict,
    *,
    temperature_k: float,
    structure_size: str,
    diagnostics: dict | None = None,
) -> dict | None:
    """V7 champion 예측 — 조합을 구조 피처(32)로 변환해 champion에 투입.

    ``v7_ctx``는 ``_load_predictor``가 BO 1회당 한 번 만든 {mtp, extractor}
    컨텍스트로, 조합마다 champion/MoleculeDB를 재로딩하지 않는다.

    ``diagnostics``가 주어지면 V7 피처공간 OOD 플래그를 ``is_ood`` 키로 기록한다
    (반환 계약은 불변 — 예측 dict). soft flag이므로 랭킹/예측에는 영향 없음.
    """
    if not v7_ctx:
        return None
    try:
        from contracts.policies.ml_policy import FeatureSetVersion
        from ml.feature_builder import FeatureBuildInput, build_feature_result

        mtp = v7_ctx["mtp"]
        extractor = v7_ctx["extractor"]
        mol_counts = _combo_species_counts(
            combo, temperature_k=temperature_k, structure_size=structure_size
        )
        feats = extractor.extract_from_counts(mol_counts, float(temperature_k))
        if feats is None:
            return None
        built = build_feature_result(
            FeatureBuildInput(structural_features=feats), FeatureSetVersion.V7
        )
        result = mtp.predict_multi({"v7": built.values.reshape(1, -1)})
        if diagnostics is not None:
            diagnostics["is_ood"] = _v7_is_ood(result)
        return dict(getattr(result, "predictions", {}) or {})
    except Exception:
        logger.warning("V7 combo prediction failed", exc_info=True)
        return None


def _predict_combo(
    predictor_fn,
    combo: dict,
    *,
    temperature_k: float,
    feature_set: str | None = None,
    structure_size: str = "X1",
    diagnostics: dict | None = None,
) -> dict | None:
    """조합 1건 예측 — champion feature_set에 따라 입력 경로 분기.

    - feature_set == 'v7': 구조 피처(species_counts→RDKit 32) 경로 + V7
      피처공간 OOD를 ``diagnostics``로 전달(soft flag).
    - 그 외(V1~V5 조성 champion): 기존 SARA-wt% 경로 (byte-identical 보존).
      V7 OOD 배선 범위 밖이라 ``diagnostics``는 건드리지 않음(is_ood 미상).
    """
    from collections.abc import Mapping

    if feature_set == "v7":
        # predictor_fn은 _load_predictor가 만든 {mtp, extractor} 컨텍스트(또는 None).
        return _predict_combo_v7(
            predictor_fn,
            combo,
            temperature_k=temperature_k,
            structure_size=structure_size,
            diagnostics=diagnostics,
        )

    if predictor_fn is None:
        return None
    pred_input = {k: float(v) for k, v in _binder_sara_wt(combo["binder_type"]).items()}
    if combo["additive_type"] and combo["additive_wt"] > 0.0:
        pred_input["additive"] = float(combo["additive_wt"])
        pred_input["additive_type"] = combo["additive_type"]
    pred_input["temperature_k"] = float(temperature_k)
    try:
        result = predictor_fn(pred_input)
    except Exception:
        return None
    if isinstance(result, Mapping) and "predictions" in result:
        return dict(result.get("predictions", {}))
    if isinstance(result, Mapping):
        return dict(result)
    return None


def _bootstrap_candidates(
    request: InverseDesignRequest, policy: InversePipelinePolicy
) -> tuple[list[dict], dict]:
    """BOOTSTRAP 모드: 조합 풀에서 결정적 셔플로 시드 배치 선택 (§4.5)."""
    import numpy as np

    combos = _candidate_combinations(request, policy)
    base_seed = policy.cold_start.seed_rng_seed
    order = np.random.default_rng(base_seed).permutation(len(combos))
    selected = [combos[int(i)] for i in order[: policy.cold_start.seed_batch_size]]

    candidates = [
        {**_combo_candidate(combo, source="bootstrap_seed", index=i), "rng_seed": base_seed + i}
        for i, combo in enumerate(selected)
    ]

    design_meta = {
        "prediction_contract": None,
        "feasibility": {
            "status": "unknown",
            "message": "Bootstrap mode: no champion predictions available; "
            "feasibility is unknown until seed labels are collected.",
        },
        "pareto_front": None,
        "audit_log": {
            "strategy": "binder_additive_grid_doe",
            "combination_pool": len(combos),
            "seed_batch_size": policy.cold_start.seed_batch_size,
            "seed_rng_seed": base_seed,
        },
    }
    return candidates, design_meta


def _derive_experiments(
    candidates: list[dict],
    *,
    request: InverseDesignRequest,
    target_metrics: list[str],
    metric_kinds: dict[str, PlannedExperimentKind],
    moisture_damage: bool,
    policy: InversePipelinePolicy,
    session,
) -> list[dict]:
    """후보 조성별 실험 편성 (§5) + binder cell 존재확인 (§4.7/§4.4-3).

    계면(layered) 실험은 항상 신규(§4.4-3), binder cell만 재사용 검사.
    """
    bulk_metrics = [m for m, k in metric_kinds.items() if k == PlannedExperimentKind.BINDER_CELL]
    layered_metrics = [
        m for m, k in metric_kinds.items() if k == PlannedExperimentKind.LAYERED_TENSILE
    ]
    mechanical_metrics = [
        m
        for m in layered_metrics
        if DEFAULT_METRICS_REGISTRY.get_namespace(m).value == "mechanical"
    ]
    layer_aux_metrics = [
        m for m in layered_metrics if DEFAULT_METRICS_REGISTRY.get_namespace(m).value == "layer"
    ]

    # 프로토콜 프리셋: 목표 물성에 따른 '선택'(승급 사다리 아님). 점도 표적이면
    # NEMD 스테이지를 포함한 viscosity 체인, 아니면 bulk 체인을 고른다.
    protocol_preset = (
        "viscosity" if any(m in policy.viscosity_stage_metrics for m in target_metrics) else "bulk"
    )
    structure_size = request.structure_size

    primary_t = float(request.temperature_k_fixed or policy.default_temperature_k)
    multi_temp = any(m in policy.multi_temperature_metrics for m in target_metrics)
    binder_temps = set(policy.tg_temperature_sweep_k) if multi_temp else {primary_t}
    if layered_metrics:
        # layered 의존성의 부모 binder cell이 반드시 편성되도록 보장
        binder_temps.add(primary_t)

    replicate_metrics = [
        m for m in mechanical_metrics if DEFAULT_METRICS_REGISTRY.requires_replicates(m)
    ]
    replicate_seeds = (
        max(DEFAULT_METRICS_REGISTRY.min_replicate_count(m) for m in replicate_metrics)
        if replicate_metrics
        else None
    )

    experiments: list[dict] = []
    seq = 0
    for ci, candidate in enumerate(candidates):
        composition = candidate["composition"]
        additive_type = candidate.get("additive_type")
        additive_wt = float(candidate.get("additive_wt", composition.get("additive", 0.0)))

        binder_ids_by_temp: dict[float, str] = {}
        for temp in sorted(binder_temps):
            seq += 1
            exp_plan_id = f"exp-{seq:03d}"
            binder_ids_by_temp[temp] = exp_plan_id
            existing = _find_existing_binder_cells(
                composition,
                additive_mol_id=additive_type,
                additive_wt=additive_wt,
                temperature_k=temp,
                policy=policy,
                session=session,
            )
            experiments.append(
                {
                    "plan_exp_id": exp_plan_id,
                    "kind": PlannedExperimentKind.BINDER_CELL.value,
                    "candidate_index": ci,
                    "temperature_k": temp,
                    "protocol_preset": protocol_preset,
                    "structure_size": structure_size,
                    "produces": bulk_metrics,
                    "depends_on": None,
                    "action": "reuse" if existing else "build",
                    "matched_exp_ids": existing,
                }
            )

        if not layered_metrics:
            continue

        # aggregate-aware BO 후보는 특정 골재(material/surface)에 대한 후보 —
        # 해당 골재만 편성. 골재 미지정 후보(BOOTSTRAP/표준 BO)는 요청의 모든
        # 골재에 대해 편성.
        candidate_material = candidate.get("aggregate_material")
        candidate_surface = candidate.get("aggregate_surface")
        aggregate_specs = [
            agg
            for agg in (request.aggregate_specs or [])
            if (candidate_material is None or getattr(agg, "material", None) == candidate_material)
            and (candidate_surface is None or getattr(agg, "surface", None) == candidate_surface)
        ]
        for agg in aggregate_specs:
            material = getattr(agg, "material", None)
            surface = getattr(agg, "surface", None)
            seq += 1
            dry_id = f"exp-{seq:03d}"
            experiments.append(
                {
                    "plan_exp_id": dry_id,
                    "kind": PlannedExperimentKind.LAYERED_TENSILE.value,
                    "candidate_index": ci,
                    "aggregate": {"material": material, "surface": surface},
                    "temperature_k": primary_t,
                    "tensile_enabled": bool(mechanical_metrics),
                    "interaction_analysis": bool(layer_aux_metrics),
                    "replicate_seeds": replicate_seeds,
                    "produces": layered_metrics,
                    "depends_on": binder_ids_by_temp[primary_t],
                    "action": "build",  # 계면 실험은 항상 신규 (§4.4-3)
                    "matched_exp_ids": [],
                }
            )
            if moisture_damage:
                seq += 1
                experiments.append(
                    {
                        "plan_exp_id": f"exp-{seq:03d}",
                        "kind": PlannedExperimentKind.WATER_INTERFACE_LAYERED.value,
                        "candidate_index": ci,
                        "aggregate": {"material": material, "surface": surface},
                        "temperature_k": primary_t,
                        "tensile_enabled": bool(mechanical_metrics),
                        "interaction_analysis": bool(layer_aux_metrics),
                        "replicate_seeds": replicate_seeds,
                        "produces": layered_metrics,
                        "depends_on": binder_ids_by_temp[primary_t],
                        "dry_pair_id": dry_id,  # 건습 ER 후처리가 페어를 찾는 키
                        "action": "build",
                        "matched_exp_ids": [],
                    }
                )

    return experiments


def _find_existing_binder_cells(
    composition: dict[str, float],
    *,
    additive_mol_id: str | None,
    additive_wt: float,
    temperature_k: float,
    policy: InversePipelinePolicy,
    session,
) -> list[str]:
    """조성 유사 completed binder cell 검색 (§4.7). DB 실패 시 빈 리스트(=build)."""

    def _run(s) -> list[str]:
        matches = queries.find_experiments_by_composition(
            s,
            composition,
            additive_mol_id=additive_mol_id,
            additive_wt=additive_wt,
            temperature_k=temperature_k,
            policy=policy.similarity,
        )
        return [m.exp_id for m in matches]

    try:
        from features.common import with_optional_session

        return with_optional_session(session, _run)
    except Exception:
        logger.warning("Composition-similarity query failed; planning fresh build")
        return []
