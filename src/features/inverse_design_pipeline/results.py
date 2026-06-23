"""파이프라인 결과 집계 — 목표 대비 달성도 + 건습 ER (§4.2 ⑥, execution에서 분리).

targets는 승인 시 멤버 metadata pipeline 블록에 동봉된 것을 복원하고
(stateless §4.6), replica ensemble(mean±SE)을 metric 값으로 우선 노출한다.
"""

from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    InversePipelinePolicy,
    PlannedExperimentKind,
)
from features.common import with_optional_session
from features.inverse_design_pipeline.members import resolved_members


def get_results(
    pipeline_id: str,
    *,
    session=None,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
) -> dict:
    """완료된 멤버 실험의 메트릭을 수집해 목표 대비 달성도를 보고한다 (§4.2 ⑥).

    다온도 정합(R-P1-1): Tg sweep처럼 한 후보가 여러 온도의 binder cell을
    가지면, 온도 의존 스칼라 지표는 **primary 온도의 실험 값**을 우선한다
    (pipeline 블록의 ``primary_temperature_k``·멤버 온도로 판별). primary
    정보가 없는 레거시 멤버는 기존 동작(최신 row 우선)으로 폴백.

    수분손상(P6): wet(water_interface_layered) 멤버의 메트릭은 본 결과표와
    분리 수집하고 — dry와 같은 metric명이라 합치면 덮어씀 — 건습비
    ER=wet/dry로 정책 임계(warn/fail) 판정을 ``moisture_er``에 붙인다.

    Args:
        pipeline_id: approve_and_run이 발급한 파이프라인 ID
        session: SQLAlchemy session (None이면 관리 세션 자체 개설)
        policy: 파이프라인 정책 (ER 임계 SSOT)

    Returns:
        {"pipeline_id", "targets", "candidates", "total_experiments",
         "completed_experiments"}
    """
    from recommendation.property_targets import PropertyTarget

    wet_kind = PlannedExperimentKind.WATER_INTERFACE_LAYERED.value
    binder_kind = PlannedExperimentKind.BINDER_CELL.value

    def _run(s) -> dict:
        resolved = resolved_members(s, pipeline_id)
        targets: list[dict] = []
        for r in resolved:
            if r["pipe"].get("targets"):
                targets = list(r["pipe"]["targets"])
                break

        by_candidate: dict[int, list[dict]] = {}
        for r in resolved:
            ci = r["pipe"].get("candidate_index")
            if ci is None:
                continue
            by_candidate.setdefault(int(ci), []).append(r)

        target_objs = [
            PropertyTarget(
                metric_name=str(t.get("metric_name")),
                target_min=t.get("target_min"),
                target_max=t.get("target_max"),
                direction=str(t.get("direction", "maximize")),
                weight=float(t.get("weight", 1.0)),
            )
            for t in targets
        ]
        target_names = [t.metric_name for t in target_objs]

        candidates: list[dict] = []
        completed_total = 0
        for ci in sorted(by_candidate):
            rows = by_candidate[ci]
            wet_rows = [r for r in rows if r["pipe"].get("kind") == wet_kind]
            dry_rows = [r for r in rows if r["pipe"].get("kind") != wet_kind]
            completed_total += sum(1 for r in rows if r["effective_status"] == "completed")

            dry_completed = [r for r in dry_rows if r["effective_status"] == "completed"]
            primary_exp_id = _primary_binder_exp_id(dry_completed, binder_kind)
            metrics = _collect_candidate_metrics(
                s,
                [r["effective_exp_id"] for r in dry_completed],
                target_names,
                primary_exp_id=primary_exp_id,
            )
            _apply_ensemble(metrics, dry_completed, target_names)

            # 수분손상 wet 페어: 분리 수집 + ER 산출 (P6)
            moisture_er = None
            wet_completed = [r for r in wet_rows if r["effective_status"] == "completed"]
            if wet_completed:
                wet_metrics = _collect_candidate_metrics(
                    s, [r["effective_exp_id"] for r in wet_completed], target_names
                )
                _apply_ensemble(wet_metrics, wet_completed, target_names)
                moisture_er = _compute_moisture_er(metrics, wet_metrics, policy.moisture)

            values = {name: m["value"] for name, m in metrics.items() if m.get("value") is not None}
            per_target = {}
            for t in target_objs:
                value = values.get(t.metric_name)
                per_target[t.metric_name] = {
                    "value": value,
                    "satisfied": (t.is_satisfied(value) if value is not None else None),
                }
            evaluated = [p for p in per_target.values() if p["satisfied"] is not None]
            candidates.append(
                {
                    "candidate_index": ci,
                    "experiments": [
                        {
                            "exp_id": r["effective_exp_id"],
                            "kind": r["pipe"].get("kind"),
                            "status": r["effective_status"],
                        }
                        for r in rows
                    ],
                    "metrics": metrics,
                    "per_target": per_target,
                    "moisture_er": moisture_er,
                    "targets_satisfied": (
                        all(p["satisfied"] for p in evaluated)
                        if evaluated and len(evaluated) == len(target_objs)
                        else None
                    ),
                }
            )

        return {
            "pipeline_id": pipeline_id,
            "targets": targets,
            "candidates": candidates,
            "total_experiments": len(resolved),
            "completed_experiments": completed_total,
        }

    return with_optional_session(session, _run)


# ──────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────────────


def _primary_binder_exp_id(dry_completed: list[dict], binder_kind: str) -> str | None:
    """primary 온도의 binder cell 실험 ID (다온도 세트의 대표값 기준, R-P1-1).

    pipeline 블록의 ``primary_temperature_k``(승인 시 동봉)와 멤버 실험의
    온도를 대조한다. 정보가 없으면 None — 기존 동작(최신 row 우선) 폴백.
    """
    for r in dry_completed:
        if r["pipe"].get("kind") != binder_kind:
            continue
        primary_t = r["pipe"].get("primary_temperature_k")
        if primary_t is None or r.get("temperature_k") is None:
            continue
        if abs(float(r["temperature_k"]) - float(primary_t)) < 0.5:
            return r["effective_exp_id"]
    return None


def _collect_candidate_metrics(
    session,
    exp_ids: list[str],
    metric_names: list[str],
    *,
    primary_exp_id: str | None = None,
) -> dict[str, dict]:
    """완료 실험들의 표적 스칼라 메트릭을 수집한다.

    기본은 메트릭별 최신 row 우선이지만, ``primary_exp_id``가 주어지면 해당
    실험의 값이 항상 이긴다 — 다온도 세트에서 임의 온도 값이 결과표를
    오염시키는 것을 방지(R-P1-1).
    """
    if not exp_ids or not metric_names:
        return {}
    from database.models import MetricModel

    rows = (
        session.query(MetricModel)
        .filter(
            MetricModel.exp_id.in_(exp_ids),
            MetricModel.metric_name.in_(metric_names),
            MetricModel.value.isnot(None),
        )
        .order_by(MetricModel.id.asc())
        .all()
    )
    metrics: dict[str, dict] = {}
    primary_metrics: dict[str, dict] = {}
    for row in rows:  # 뒤(최신)가 이김 — primary가 있으면 마지막에 덮어씀
        entry = {
            "value": float(row.value),
            "uncertainty": (float(row.uncertainty) if row.uncertainty is not None else None),
            "exp_id": row.exp_id,
            "source": "metric",
        }
        metrics[row.metric_name] = entry
        if primary_exp_id and row.exp_id == primary_exp_id:
            primary_metrics[row.metric_name] = entry
    if primary_metrics:
        metrics.update(primary_metrics)
    return metrics


def _apply_ensemble(metrics: dict, rows: list[dict], target_names: list[str]) -> None:
    """replica ensemble(mean±SE)이 있으면 metric 값으로 우선 노출."""
    for r in rows:
        ensemble = r["meta"].get("replicate_ensemble")
        if isinstance(ensemble, dict):
            for name, stats in ensemble.items():
                if name in target_names and isinstance(stats, dict):
                    metrics[name] = {
                        "value": stats.get("mean"),
                        "uncertainty": stats.get("standard_error"),
                        "source": "replicate_ensemble",
                        "n_replicates": stats.get("n_replicates"),
                    }


def _compute_moisture_er(
    dry_metrics: dict[str, dict], wet_metrics: dict[str, dict], moisture_policy
) -> dict | None:
    """건습비 ER(wet/dry retained ratio)과 정책 임계 판정 (§2, AASHTO T 283 차용)."""
    report: dict[str, dict] = {}
    for name, wet in wet_metrics.items():
        dry = dry_metrics.get(name)
        wet_value = wet.get("value")
        dry_value = (dry or {}).get("value")
        if wet_value is None or not dry_value:
            continue
        er = float(wet_value) / float(dry_value)
        if er < moisture_policy.er_fail_threshold:
            verdict = "fail"
        elif er < moisture_policy.er_warn_threshold:
            verdict = "warn"
        else:
            verdict = "ok"
        report[name] = {
            "dry": float(dry_value),
            "wet": float(wet_value),
            "er": er,
            "verdict": verdict,
            "er_warn_threshold": moisture_policy.er_warn_threshold,
            "er_fail_threshold": moisture_policy.er_fail_threshold,
        }
    return report or None
