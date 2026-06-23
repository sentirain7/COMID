"""닫힌 루프(결과분석→계획수정) — 결정론적 능동학습 (P7, 계획 §7).

기본 **OFF**(``ClosedLoopPolicy.enabled``) — NPT 조기종료/FeasibilityScout와
동일한 opt-in 정책. 한 pipeline(=라운드 배치)이 종료되면:

② 집계(``get_results``, replica ensemble mean±SE) → ③ 진단(목표충족·최적
후보 거리) → ④ 결정(STOP: 목표달성/라운드·실험 예산캡/연속 무개선 — 정책
SSOT; '개선'은 SE 배수 초과만 인정) → ⑤ 수정(재학습 advisory ingest →
``preview_plan``(BOOTSTRAP→BO 전환은 §4.5 모드 판정이 자동 수행) →
``approve_and_run`` 자동 다음 라운드).

stateless(§4.6): 라운드 상태는 직전 plan 문서(클라이언트 회신, plan_hash
검증)와 멤버 metadata의 ``loop`` 블록에서 복원한다 — 루프 상태 테이블 없음.
"""

from typing import Any

from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode
from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    InversePipelinePolicy,
)
from features.common import with_optional_session
from features.inverse_design_pipeline.execution import approve_and_run, compute_plan_hash
from features.inverse_design_pipeline.members import resolved_members
from features.inverse_design_pipeline.results import get_results

logger = get_logger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}


async def run_loop_round(
    plan: dict,
    plan_hash: str,
    pipeline_id: str,
    *,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
    session=None,
) -> dict:
    """종료된 라운드를 진단하고 정지 또는 다음 라운드를 자동 실행한다 (§7).

    Args:
        plan: 이 pipeline을 승인할 때 사용한 계획 문서 (회신, 변조 불가)
        plan_hash: 해당 계획의 해시
        pipeline_id: 종료된 라운드의 파이프라인 ID
        policy: 파이프라인 정책 (closed_loop SSOT)
        session: SQLAlchemy session (None이면 session_scope 자체 개설)

    Returns:
        {"decision", "diagnostics", "audit", "next"} — next는 계속 시
        다음 라운드의 approve 응답(+plan/plan_hash), 정지 시 None

    Raises:
        ContractError: 정책 비활성 / 검증 실패 / 라운드 미종료
    """
    loop_policy = policy.closed_loop
    if not loop_policy.enabled:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Closed-loop rounds are disabled by policy "
            "(InversePipelinePolicy.closed_loop.enabled=False).",
            {"failure_mode": "closed_loop_disabled"},
        )
    if compute_plan_hash(plan) != plan_hash:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "plan_hash mismatch: the plan document was modified.",
            {"failure_mode": "plan_hash_mismatch"},
        )
    if not pipeline_id.startswith(f"pl-{plan_hash}-"):
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "pipeline_id does not belong to the supplied plan.",
            {"failure_mode": "pipeline_plan_mismatch"},
        )

    def _load(s):
        members = resolved_members(s, pipeline_id)
        results = get_results(pipeline_id, session=s, policy=policy)
        return members, results

    members, results = with_optional_session(session, _load)

    if not members:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown pipeline: {pipeline_id}",
            {"failure_mode": "pipeline_not_found"},
        )

    pending = [
        m["effective_exp_id"] for m in members if m["effective_status"] not in TERMINAL_STATUSES
    ]
    if pending:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Round is not finished: {len(pending)} experiment(s) still active.",
            {"failure_mode": "round_incomplete", "pending_exp_ids": pending[:10]},
        )

    # ── 체인 상태 복원 (멤버 metadata loop 블록, 없으면 라운드 1) ──
    loop_meta: dict[str, Any] = {}
    for m in members:
        if isinstance(m["pipe"].get("loop"), dict):
            loop_meta = dict(m["pipe"]["loop"])
            break
    round_no = int(loop_meta.get("round", 1))
    chain_id = str(loop_meta.get("chain_id", pipeline_id))
    chain_total = int(loop_meta.get("chain_experiments_total", len(members)))
    prev_best = loop_meta.get("prev_best_distance")
    no_improve_count = int(loop_meta.get("no_improve_count", 0))

    # ── ③ 진단 ──
    diagnostics = _diagnose(plan, results)
    best_distance = diagnostics["best_distance"]
    best_se = diagnostics["best_se"]

    improvement = None
    if prev_best is not None and best_distance is not None:
        threshold = loop_policy.improvement_min_se_multiple * (best_se or 0.0)
        improvement = float(prev_best) - float(best_distance)
        if improvement <= threshold:
            no_improve_count += 1
        else:
            no_improve_count = 0

    # ── ④ 결정 (정책 SSOT, 우선순위 고정) ──
    decision = "continue"
    if diagnostics["any_satisfied"]:
        decision = "stop_target_met"
    elif round_no >= loop_policy.max_rounds:
        decision = "stop_max_rounds"
    elif chain_total >= loop_policy.max_total_experiments:
        decision = "stop_budget_experiments"
    elif no_improve_count >= loop_policy.stop_no_improve_rounds:
        decision = "stop_no_improvement"

    audit = {
        "chain_id": chain_id,
        "round": round_no,
        "chain_experiments_total": chain_total,
        "best_distance": best_distance,
        "prev_best_distance": prev_best,
        "improvement": improvement,
        "improvement_threshold_se_multiple": loop_policy.improvement_min_se_multiple,
        "best_se": best_se,
        "no_improve_count": no_improve_count,
        "policy": {
            "max_rounds": loop_policy.max_rounds,
            "max_total_experiments": loop_policy.max_total_experiments,
            "stop_no_improve_rounds": loop_policy.stop_no_improve_rounds,
        },
    }

    if decision != "continue":
        return {"decision": decision, "diagnostics": diagnostics, "audit": audit, "next": None}

    # ── ⑤ 수정: 재학습 advisory → 재미리보기(모드 자동) → 자동 승인 ──
    _ingest_round_results(plan, results)

    next_round = await _launch_next_round(
        plan,
        policy=policy,
        loop_block={
            "chain_id": chain_id,
            "round": round_no + 1,
            "prev_pipeline_id": pipeline_id,
            "chain_experiments_total": None,  # 아래에서 새 배치 크기로 확정
            "prev_best_distance": best_distance,
            "no_improve_count": no_improve_count,
        },
        chain_total=chain_total,
    )
    return {
        "decision": "continue",
        "diagnostics": diagnostics,
        "audit": audit,
        "next": next_round,
    }


# ──────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────────────


def _diagnose(plan: dict, results: dict) -> dict:
    """후보별 목표 거리/달성 여부 진단 (③)."""
    from recommendation.property_targets import PropertyTarget, PropertyTargetSet

    target_set = PropertyTargetSet(
        name="loop",
        description="closed-loop diagnostics",
        targets=[
            PropertyTarget(
                metric_name=str(t.get("metric_name")),
                target_min=t.get("target_min"),
                target_max=t.get("target_max"),
                direction=str(t.get("direction", "maximize")),
                weight=float(t.get("weight", 1.0)),
            )
            for t in plan.get("targets", [])
        ],
    )
    target_names = [t.metric_name for t in target_set.targets]

    any_satisfied = False
    best_distance = None
    best_candidate = None
    best_se = None
    evaluated = 0
    for candidate in results.get("candidates", []):
        values = {
            name: p.get("value")
            for name, p in (candidate.get("per_target") or {}).items()
            if p.get("value") is not None
        }
        if candidate.get("targets_satisfied"):
            any_satisfied = True
        if len(values) != len(target_names) or not target_names:
            continue
        evaluated += 1
        distance = sum(target_set.compute_distances(values).values())
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_candidate = candidate.get("candidate_index")
            ses = [
                m.get("uncertainty")
                for m in (candidate.get("metrics") or {}).values()
                if m.get("source") == "replicate_ensemble" and m.get("uncertainty") is not None
            ]
            best_se = (sum(ses) / len(ses)) if ses else None

    return {
        "any_satisfied": any_satisfied,
        "evaluated_candidates": evaluated,
        "best_candidate_index": best_candidate,
        "best_distance": best_distance,
        "best_se": best_se,
        "completed_experiments": results.get("completed_experiments", 0),
        "total_experiments": results.get("total_experiments", 0),
    }


def _ingest_round_results(plan: dict, results: dict) -> None:
    """완료 라벨을 능동학습 워크플로우에 advisory로 공급 (실패 무해)."""
    try:
        from features.recommendations.active_learning import ingest_completed_experiment

        candidates_by_index = dict(enumerate(plan.get("candidates", [])))
        temperature_k = float(
            (plan.get("request_echo") or {}).get("temperature_k_fixed")
            or plan.get("policy_snapshot", {}).get("default_temperature_k", 298.0)
        )
        for candidate in results.get("candidates", []):
            values = {
                name: p["value"]
                for name, p in (candidate.get("per_target") or {}).items()
                if p.get("value") is not None
            }
            if not values:
                continue
            plan_candidate = candidates_by_index.get(int(candidate.get("candidate_index", -1)))
            if plan_candidate is None:
                continue
            exp_ids = [
                e["exp_id"]
                for e in candidate.get("experiments", [])
                if e.get("status") == "completed"
            ]
            if not exp_ids:
                continue
            ingest_completed_experiment(
                exp_id=exp_ids[0],
                composition=dict(plan_candidate.get("composition") or {}),
                observed_properties=values,
                temperature_k=temperature_k,
            )
    except Exception as exc:
        logger.warning("Active-learning ingest skipped: %s", exc)


async def _launch_next_round(
    plan: dict,
    *,
    policy: InversePipelinePolicy,
    loop_block: dict,
    chain_total: int,
) -> dict:
    """재미리보기(§4.5 모드 자동 판정) → 자동 승인으로 다음 라운드 실행."""
    from api.schemas import InversePipelinePlanRequest
    from features.inverse_design_pipeline import service as service_module

    request_echo = dict(plan.get("request_echo") or {})
    request = InversePipelinePlanRequest(**request_echo)

    # R-P1-6: moisture 플래그는 plan 문서가 SSOT — request_echo는 호출 경로에
    # 따라 이 필드가 없을 수 있어(서비스 레벨 InverseDesignRequest) 라운드 2+
    # 에서 수분 트랙이 무음 소실되는 문제를 막는다.
    moisture_damage = bool((plan.get("moisture_damage") or {}).get("enabled", False))

    preview = await service_module.preview_plan(
        request,
        moisture_damage=moisture_damage,
        policy=policy,
    )
    next_plan = preview["plan"]
    next_hash = preview["plan_hash"]

    loop_block = {
        **loop_block,
        "chain_experiments_total": chain_total + len(next_plan.get("experiments", [])),
    }
    approval = approve_and_run(next_plan, next_hash, policy=policy, loop_block=loop_block)
    return {**approval, "plan": next_plan, "plan_hash": next_hash, "loop": loop_block}
