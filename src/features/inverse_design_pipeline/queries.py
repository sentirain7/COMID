"""역설계 파이프라인 전용 얇은 DB 쿼리 (계획 §4.5/§4.7).

- count_training_labels: 콜드스타트 모드 판정용 표적 metric별 라벨 수
- find_experiments_by_composition: 임의 SARA 조성의 유사실험(재사용 후보) 검색.
  기존 find_similar_experiments는 binder_type 정확일치 키라서 named binder
  전용 — 역설계가 산출하는 임의 조성에는 이 쿼리를 사용한다.
"""

from sqlalchemy.orm import Session

from contracts.policies.inverse_pipeline import CompositionSimilarityPolicy
from database.models import ExperimentModel, MetricModel

_COMPLETED = "completed"


def count_training_labels(session: Session, metric_name: str) -> int:
    """completed 실험에서 해당 metric의 스칼라 라벨 수를 센다.

    Args:
        session: SQLAlchemy session
        metric_name: 레지스트리 metric 이름

    Returns:
        값이 존재하는 스칼라 metric row 수 (배열 metric의 value=None 제외)
    """
    return (
        session.query(MetricModel.id)
        .join(ExperimentModel, MetricModel.experiment_id == ExperimentModel.id)
        .filter(
            MetricModel.metric_name == metric_name,
            MetricModel.value.isnot(None),
            ExperimentModel.status == _COMPLETED,
        )
        .count()
    )


def find_experiments_by_composition(
    session: Session,
    composition: dict[str, float],
    *,
    additive_mol_id: str | None,
    additive_wt: float,
    temperature_k: float,
    policy: CompositionSimilarityPolicy,
) -> list[ExperimentModel]:
    """조성(comp_*_wt ±tol) + 첨가제 + 온도로 completed 유사실험을 검색한다.

    Args:
        session: SQLAlchemy session
        composition: SARA 성분 wt% dict (asphaltene/resin/aromatic/saturate)
        additive_mol_id: 첨가제 mol_id (None = 무첨가)
        additive_wt: 첨가제 wt%
        temperature_k: 목표 온도 (K)
        policy: 허용오차 정책 (SSOT)

    Returns:
        매칭 ExperimentModel 리스트 (최신순, policy.limit 이내)
    """
    sara_columns = {
        "asphaltene": ExperimentModel.comp_asphaltene_wt,
        "resin": ExperimentModel.comp_resin_wt,
        "aromatic": ExperimentModel.comp_aromatic_wt,
        "saturate": ExperimentModel.comp_saturate_wt,
    }

    query = session.query(ExperimentModel).filter(ExperimentModel.status == _COMPLETED)

    tol = policy.comp_tolerance_wt
    for name, column in sara_columns.items():
        value = float(composition.get(name, 0.0))
        query = query.filter(column >= value - tol, column <= value + tol)

    if additive_mol_id is None:
        query = query.filter(
            (ExperimentModel.additive_mol_id.is_(None)) | (ExperimentModel.additive_mol_id == "")
        )
    else:
        add_tol = policy.additive_wt_tolerance
        query = query.filter(
            ExperimentModel.additive_mol_id == additive_mol_id,
            ExperimentModel.additive_wt >= additive_wt - add_tol,
            ExperimentModel.additive_wt <= additive_wt + add_tol,
        )

    temp_tol = policy.temperature_tolerance_k
    query = query.filter(
        ExperimentModel.temperature_K >= temperature_k - temp_tol,
        ExperimentModel.temperature_K <= temperature_k + temp_tol,
    )

    return query.order_by(ExperimentModel.id.desc()).limit(policy.limit).all()
