"""계면 mechanical 지표 replica 앙상블 집계 (보완 #4, 원칙 9 연계).

``work_of_separation``·``interfacial_tensile_strength`` 같은 **확률적 계면
mechanical 지표**는 단일 seed/변형률 한 번의 결과가 아니라 다중 replica(독립
seed 또는 변형률)로 묶어 **mean ± standard error(SE)** 로 보고해야 한다(원칙 9).

이 모듈은 기존 SSOT 인프라를 계면 경로에 **연결**만 한다:
  - 통계: ``metrics.statistics.aggregate_replicates`` (mean/std/SE/CI) — 재사용
  - 정책: ``contracts.policies.replicate.ReplicatePolicy`` (min_seeds, ci_level,
    report_standard_error) — 재사용
  - 메트릭 SSOT: ``contracts.policies.metrics`` 의 ``requires_replicates`` /
    ``min_replicate_count`` 플래그로 어떤 지표가 ensemble 보고 대상인지 강제

새 통계 로직을 만들지 않는다. per-seed ``MetricResult`` 들을
(metric_name, interface_index, layer_index) 별로 그룹핑하여 replica-필수
지표에 한해 ensemble 결과를 산출한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY, MetricsRegistry
from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY, ReplicatePolicy
from contracts.schemas import MetricResult
from metrics.statistics import AggregateResult, aggregate_replicates

# 그룹핑 키: 동일 계면/레이어 위치의 동일 지표를 replica로 묶는다.
_GroupKey = tuple[str, int | None, int | None]


@dataclass(frozen=True)
class ReplicateMetricResult:
    """계면 지표 replica ensemble 결과.

    Attributes:
        metric_name: 지표 이름.
        namespace: 지표 namespace (레지스트리 기준).
        interface_index: 계면 provenance 인덱스(없으면 None).
        layer_index: 레이어 provenance 인덱스(없으면 None).
        aggregate: mean/std/standard_error/CI 를 담은 ``AggregateResult``.
        n_replicates: 집계에 사용된 replica 수.
        min_replicate_count: 정책상 적정 replica 최소 수.
        meets_min_replicates: ``n_replicates >= min_replicate_count`` 여부.
    """

    metric_name: str
    namespace: str
    interface_index: int | None
    layer_index: int | None
    aggregate: AggregateResult
    n_replicates: int
    min_replicate_count: int
    meets_min_replicates: bool

    def stats_metadata(self) -> dict:
        """``MetricModel.metadata_json`` 에 persist 할 ensemble 통계 dict."""
        agg = self.aggregate
        return {
            "ensemble": True,
            "mean": agg.mean,
            "std": agg.std,
            "standard_error": agg.standard_error,
            "n_replicates": self.n_replicates,
            "min_replicate_count": self.min_replicate_count,
            "meets_min_replicates": self.meets_min_replicates,
            "ci_level": agg.ci_level,
            "ci_lower": agg.ci_lower,
            "ci_upper": agg.ci_upper,
            "values": list(agg.values),
        }

    def to_metric_result(
        self,
        exp_id: str | None,
        *,
        unit: str,
        report_standard_error: bool = True,
    ) -> MetricResult:
        """Ensemble 을 persist 가능한 ``MetricResult`` 로 변환.

        canonical value 는 **mean**, uncertainty 는 **SE**(권장) 또는 std.
        전체 통계는 ``array_summary`` 에 실어 DB ``metadata_json`` 으로 보존한다.
        """
        unc = self.aggregate.standard_error if report_standard_error else self.aggregate.std
        return MetricResult(
            exp_id=exp_id,
            metric_name=self.metric_name,
            value=self.aggregate.mean,
            unit=unit,
            namespace=self.namespace,
            uncertainty=unc,
            layer_index=self.layer_index,
            interface_index=self.interface_index,
            array_summary=self.stats_metadata(),
        )


def aggregate_interface_metric(
    metric_name: str,
    values: Sequence[float],
    *,
    interface_index: int | None = None,
    layer_index: int | None = None,
    registry: MetricsRegistry = DEFAULT_METRICS_REGISTRY,
    policy: ReplicatePolicy = DEFAULT_REPLICATE_POLICY,
) -> ReplicateMetricResult:
    """원시 replica 값 리스트(다중 seed/변형률)를 mean ± SE ensemble 로 집계.

    ``aggregate_replicates`` 를 그대로 호출하고 레지스트리의
    ``min_replicate_count`` 로 적정성(``meets_min_replicates``)을 태깅한다.

    Args:
        metric_name: 레지스트리에 등록된 지표 이름.
        values: replica 측정값(seed/변형률당 1개). 빈 리스트는 허용 안 함.
        interface_index: 계면 provenance(선택).
        layer_index: 레이어 provenance(선택).
        registry: 메트릭 레지스트리 SSOT(기본 전역).
        policy: replica 정책(기본 전역).

    Returns:
        ``ReplicateMetricResult``.

    Raises:
        ValueError: ``values`` 가 비어 있을 때.
    """
    vals = [float(v) for v in values if v is not None]
    if not vals:
        raise ValueError(f"No replicate values for metric '{metric_name}'")

    agg = aggregate_replicates(metric_name, vals, policy=policy)
    min_count = (
        registry.min_replicate_count(metric_name) if registry.is_valid_metric(metric_name) else 1
    )
    namespace = (
        registry.get_namespace(metric_name).value
        if registry.is_valid_metric(metric_name)
        else "mechanical"
    )
    return ReplicateMetricResult(
        metric_name=metric_name,
        namespace=namespace,
        interface_index=interface_index,
        layer_index=layer_index,
        aggregate=agg,
        n_replicates=len(vals),
        min_replicate_count=min_count,
        meets_min_replicates=len(vals) >= min_count,
    )


def aggregate_interface_replicates(
    per_seed_metrics: Sequence[Sequence[MetricResult]] | Sequence[MetricResult],
    *,
    registry: MetricsRegistry = DEFAULT_METRICS_REGISTRY,
    policy: ReplicatePolicy = DEFAULT_REPLICATE_POLICY,
    metric_names: Iterable[str] | None = None,
) -> list[ReplicateMetricResult]:
    """다중 replica 의 per-seed ``MetricResult`` 들을 ensemble 로 집계.

    같은 계면 설정의 N개 replica(seed/변형률) 각각이 산출한 ``MetricResult``
    리스트를 받아 (metric_name, interface_index, layer_index) 별로 묶고,
    **replica-필수 지표**(레지스트리 ``requires_replicates=True``)에 한해
    mean ± SE ensemble 을 만든다.

    Args:
        per_seed_metrics: replica 별 ``MetricResult`` 리스트의 시퀀스
            (예: ``[[m...], [m...], ...]``) 또는 평탄화된 ``MetricResult`` 시퀀스.
        registry: 메트릭 레지스트리 SSOT.
        policy: replica 정책.
        metric_names: 집계 대상 지표를 명시적으로 한정(기본: 레지스트리의
            replica-필수 지표 전체).

    Returns:
        ``ReplicateMetricResult`` 리스트((metric, interface_index, layer_index)당 1개).
        그룹핑은 결정적으로 정렬되어 반환된다.
    """
    flat = _flatten(per_seed_metrics)
    targets = (
        set(metric_names) if metric_names is not None else set(registry.replica_required_metrics())
    )

    grouped: dict[_GroupKey, list[float]] = {}
    for m in flat:
        if m.metric_name not in targets:
            continue
        if m.value is None:
            continue
        key: _GroupKey = (m.metric_name, m.interface_index, m.layer_index)
        grouped.setdefault(key, []).append(float(m.value))

    results: list[ReplicateMetricResult] = []
    for name, iface_idx, layer_idx in sorted(
        grouped,
        key=lambda k: (k[0], k[1] if k[1] is not None else -1, k[2] if k[2] is not None else -1),
    ):
        results.append(
            aggregate_interface_metric(
                name,
                grouped[(name, iface_idx, layer_idx)],
                interface_index=iface_idx,
                layer_index=layer_idx,
                registry=registry,
                policy=policy,
            )
        )
    return results


def _flatten(
    per_seed_metrics: Sequence[Sequence[MetricResult]] | Sequence[MetricResult],
) -> list[MetricResult]:
    """replica 별 리스트의 시퀀스 또는 평탄 시퀀스를 평탄 리스트로 정규화."""
    flat: list[MetricResult] = []
    for item in per_seed_metrics:
        if isinstance(item, MetricResult):
            flat.append(item)
        else:
            flat.extend(item)
    return flat
