"""파이프라인 멤버 조회·해석 공용 모듈 (execution/results/loop 공유).

metadata 태깅 기반 멤버십(§4.6 stateless)의 단일 구현 — LIKE 사전필터
(양 DB 호환) 후 Python 정확 검증, placeholder dedupe, ``real_layered_exp_id``
간접참조 해석을 담당한다.
"""

PIPELINE_META_KEY = "pipeline"
PIPELINE_REFS_META_KEY = "pipeline_refs"


def find_pipeline_members(session, pipeline_id: str) -> list:
    """metadata pipeline 태그로 파이프라인 구성원 실험을 조회한다.

    LIKE 사전필터(양 DB 호환) 후 Python에서 정확 검증 — pipeline_id는
    발급 시 고유 토큰이라 오탐 가능성이 낮고, 검증으로 0이 된다.
    (운영 규모에서 PostgreSQL jsonb 인덱스 분기는 R-P2-4로 보류.)
    """
    from sqlalchemy import String, cast

    from database.models import ExperimentModel

    rows = (
        session.query(ExperimentModel)
        .filter(cast(ExperimentModel.metadata_json, String).like(f"%{pipeline_id}%"))
        .all()
    )
    return [r for r in rows if pipeline_block_for(dict(r.metadata_json or {}), pipeline_id)]


def pipeline_block_for(meta: dict, pipeline_id: str) -> dict | None:
    """metadata에서 해당 pipeline_id의 블록을 찾는다 (직접 태그 또는 참조)."""
    block = meta.get(PIPELINE_META_KEY)
    if isinstance(block, dict) and block.get("id") == pipeline_id:
        return block
    for ref in meta.get(PIPELINE_REFS_META_KEY) or []:
        if isinstance(ref, dict) and ref.get("id") == pipeline_id:
            return ref
    return None


def resolved_members(session, pipeline_id: str) -> list[dict]:
    """멤버 조회 + placeholder dedupe + real_layered 간접참조 해석 (공용).

    Returns:
        [{"exp_id", "effective_exp_id", "status", "effective_status",
          "temperature_k", "meta", "pipe"}] — meta는 실효(간접참조 후) 기준,
        pipe는 placeholder 기준(간접참조 출발점)
    """
    members = find_pipeline_members(session, pipeline_id)
    # 실제 layered 실험이 직접 멤버로 태깅된 경우(메타 전파 이후),
    # 같은 실험을 가리키는 placeholder는 중복 집계하지 않는다.
    member_ids = {m.exp_id for m in members}
    members = [
        m
        for m in members
        if not (
            (m.metadata_json or {}).get("real_layered_exp_id") in member_ids
            and (m.metadata_json or {}).get("real_layered_exp_id") != m.exp_id
        )
    ]
    resolved: list[dict] = []
    for m in members:
        meta = dict(m.metadata_json or {})
        pipe = pipeline_block_for(meta, pipeline_id) or {}
        effective_exp_id = m.exp_id
        effective_status = str(m.status or "")
        effective_meta = meta
        temperature_k = float(m.temperature_K) if m.temperature_K is not None else None
        real_id = meta.get("real_layered_exp_id")
        if real_id:
            real = get_experiment(session, str(real_id))
            if real is not None:
                effective_exp_id = real.exp_id
                effective_status = str(real.status or "")
                effective_meta = dict(real.metadata_json or {})
        resolved.append(
            {
                "exp_id": m.exp_id,
                "effective_exp_id": effective_exp_id,
                "status": str(m.status or ""),
                "effective_status": effective_status,
                "temperature_k": temperature_k,
                "meta": effective_meta,
                "pipe": pipe,
            }
        )
    return resolved


def get_experiment(session, exp_id: str):
    """exp_id로 단건 조회 (간접참조 해석용)."""
    from database.models import ExperimentModel

    return session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
