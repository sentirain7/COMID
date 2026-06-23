"""계면 replica group 오케스트레이션 + 완료시 ensemble 자동 persist (보완 #4 후속).

다중 seed로 같은 계면 설정을 N회 제출하면 한 **replica group**으로 묶고
(각 실험 metadata에 group 정보 태깅), group의 모든 replica가 종료되면
계면 mechanical 지표(work_of_separation 등)를 mean ± SE ensemble로 자동
집계하여 primary 실험 metadata에 보존한다.

자동 그룹핑은 "제출 시점 명시적 태깅"으로 한다(조성/온도/프로토콜 역추론
휴리스틱보다 결정적이고 안전). ensemble 계산은 v01.05.26의
``layered_analysis.aggregate_layered_replicate_metrics`` (SSOT)를 재사용한다.
"""

from __future__ import annotations

from common.logging import get_logger

logger = get_logger("features.layered_structures.replicate")

# metadata_json 내 group/ensemble 보존 키.
REPLICATE_GROUP_KEY = "replicate_group"
REPLICATE_ENSEMBLE_KEY = "replicate_ensemble"

# 종료 상태(이 상태들에 모두 도달해야 ensemble 집계를 확정).
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timeout"})


def tag_replicate_group(exp_ids: list[str], group_id: str) -> None:
    """replica group 구성원 각 실험 metadata에 group 정보를 태깅한다.

    첫 번째 exp_id가 primary(ensemble 보존 대상). 각 구성원은 전체 sibling
    목록을 자기 metadata에 보관하므로, 이후 완료 훅이 JSON 쿼리 없이 자신의
    metadata만 읽어 siblings를 알 수 있다.

    Args:
        exp_ids: group 구성원 실험 ID(primary first).
        group_id: replica group ID.
    """
    if not exp_ids:
        return
    from database.models.experiment import ExperimentModel
    from features.common import run_in_session_commit

    primary = exp_ids[0]

    def _op(session):
        rows = session.query(ExperimentModel).filter(ExperimentModel.exp_id.in_(exp_ids)).all()
        for r in rows:
            meta = dict(r.metadata_json or {})
            meta[REPLICATE_GROUP_KEY] = {
                "group_id": group_id,
                "primary_exp_id": primary,
                "sibling_exp_ids": list(exp_ids),
                "role": "primary" if r.exp_id == primary else "replica",
            }
            r.metadata_json = meta  # 전체 dict 재할당(SQLAlchemy JSON 변경감지)

    run_in_session_commit(_op)


def persist_replicate_ensemble(exp_id: str) -> dict | None:
    """grouped 실험이 완료되면 group ensemble을 집계해 primary metadata에 보존.

    멱등적: 모든 replica가 종료될 때마다 재계산/덮어쓰기. 일부 replica가 아직
    실행 중이면 None(대기). 완료된 replica가 하나도 없으면 None.

    Args:
        exp_id: 방금 완료된(또는 종료된) 실험 ID.

    Returns:
        보존한 ensemble dict, 또는 None(group 아님/대기/집계 불가).
    """
    grp = _read_group_context(exp_id)
    if grp is None:
        return None

    siblings: list[str] = list(grp.get("sibling_exp_ids") or [])
    primary: str = grp.get("primary_exp_id") or exp_id
    group_id: str = grp.get("group_id") or ""
    if not siblings:
        return None

    statuses = _read_statuses(siblings)
    # 아직 종료되지 않은 replica가 있으면 대기.
    if not all(statuses.get(s, "") in _TERMINAL_STATUSES for s in siblings):
        return None

    completed = [s for s in siblings if statuses.get(s) == "completed"]
    if not completed:
        return None

    # Sibling co-completion guard (v01.05.56 M5): under co-location, multiple
    # replicas of a group can hit a terminal state near-simultaneously, so two
    # workers can both pass the "all terminal" check and both aggregate + do a
    # full-dict reassign of the primary's metadata_json — racing each other (and
    # any unrelated metadata write). A per-group fcntl lock serializes them, and
    # an in-lock re-check makes exactly one worker do the aggregation for a given
    # completed-set (the rest no-op). Still idempotent: a later terminal event
    # that grows `completed` re-aggregates.
    lock = _acquire_group_lock(group_id or primary)
    try:
        if _ensemble_already_written(primary, completed):
            return None

        # SSOT ensemble 집계(자체 세션) — 중첩 세션 회피 위해 분리 호출.
        from features.layered_structures.layered_analysis import (
            aggregate_layered_replicate_metrics,
        )

        metrics = aggregate_layered_replicate_metrics(completed)
        if not metrics:
            return None

        ensemble = {
            "group_id": group_id,
            "n_replicates": len(siblings),
            "n_completed": len(completed),
            "completed_exp_ids": completed,
            "metrics": metrics,
        }
        _write_primary_ensemble(primary, ensemble)
    finally:
        _release_group_lock(lock)

    logger.info(
        "Replicate ensemble persisted for group %s (primary=%s, n_completed=%d)",
        group_id,
        primary,
        len(completed),
    )
    return ensemble


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _read_group_context(exp_id: str) -> dict | None:
    from database.models.experiment import ExperimentModel
    from features.common import run_in_session

    def _q(session):
        row = (
            session.query(ExperimentModel.metadata_json)
            .filter(ExperimentModel.exp_id == exp_id)
            .first()
        )
        if not row:
            return None
        meta = row[0] or {}
        return meta.get(REPLICATE_GROUP_KEY)

    return run_in_session(_q)


def _read_statuses(exp_ids: list[str]) -> dict[str, str]:
    from database.models.experiment import ExperimentModel
    from features.common import run_in_session

    def _q(session):
        rows = (
            session.query(ExperimentModel.exp_id, ExperimentModel.status)
            .filter(ExperimentModel.exp_id.in_(exp_ids))
            .all()
        )
        return {exp: str(status) for exp, status in rows}

    return run_in_session(_q)


def _write_primary_ensemble(primary_exp_id: str, ensemble: dict) -> None:
    from database.models.experiment import ExperimentModel
    from features.common import run_in_session_commit

    def _op(session):
        row = (
            session.query(ExperimentModel).filter(ExperimentModel.exp_id == primary_exp_id).first()
        )
        if row is None:
            return
        meta = dict(row.metadata_json or {})
        meta[REPLICATE_ENSEMBLE_KEY] = ensemble
        row.metadata_json = meta

    run_in_session_commit(_op)


# ---------------------------------------------------------------------------
# Sibling co-completion guard (M5)
# ---------------------------------------------------------------------------


def _acquire_group_lock(key: str):
    """Cross-process exclusive lock for a replica group's ensemble write.

    Returns an opaque handle (or None if POSIX fcntl is unavailable, in which
    case the caller proceeds un-serialized — fail-open, never deadlock).
    """
    import hashlib
    import os
    import tempfile

    try:
        import fcntl
    except Exception:  # pragma: no cover - non-POSIX
        return None

    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(tempfile.gettempdir(), f"asphalt_ensemble_{digest}.lock")
    try:
        handle = open(path, "a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle
    except Exception:  # pragma: no cover - fail-open
        return None


def _release_group_lock(handle) -> None:
    if handle is None:
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


def _ensemble_already_written(primary_exp_id: str, completed: list[str]) -> bool:
    """True if the primary already holds an ensemble for this exact completed set.

    Lets a co-completing sibling no-op instead of redundantly re-aggregating and
    re-writing (and risking a metadata clobber). A later, larger completed set
    differs → re-aggregation still proceeds (idempotent).
    """
    from database.models.experiment import ExperimentModel
    from features.common import run_in_session

    def _q(session):
        row = (
            session.query(ExperimentModel.metadata_json)
            .filter(ExperimentModel.exp_id == primary_exp_id)
            .first()
        )
        if not row or not row[0]:
            return False
        existing = (row[0] or {}).get(REPLICATE_ENSEMBLE_KEY)
        if not existing:
            return False
        return set(existing.get("completed_exp_ids") or []) == set(completed)

    return bool(run_in_session(_q))
