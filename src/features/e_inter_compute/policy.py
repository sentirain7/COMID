"""E_inter 정밀 분석 추천 정책 평가기."""

from contracts.policies.e_inter_compute import (
    AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED,
    LONG_RANGE_DEPENDENT_METRICS,
    SUPPORTED_CPU_RERUN_FF_TYPES,
    EInterComputeConfig,
    EInterPolicyInput,
    EInterPolicyOutput,
)
from contracts.schema_enums import EInterComputeMode, EInterRecommendationLevel

# Codex #4: v1 only supports e_inter_total; others planned for v2
V1_SUPPORTED_METRICS = ("e_inter_total",)

# 정밀 e_inter를 "자동 활성화"할 추천 수준(정책 평가 결과 기준).
_AUTO_ENABLE_LEVELS = frozenset(
    {EInterRecommendationLevel.RECOMMENDED, EInterRecommendationLevel.REQUIRED}
)


class EInterComputePolicyEvaluator:
    """Stateless 정책 평가기."""

    def evaluate(self, input: EInterPolicyInput) -> EInterPolicyOutput:
        """Evaluate recommendation level for E_inter precision analysis.

        Note: v1 only supports e_inter_total. affected_metrics always returns
        v1-supported metrics. Future versions will add e_inter_layer_matrix,
        e_inter_additive_binder support.
        """
        reason_codes: list[str] = []
        score = 0.0

        # Rule 1: long-range metric 명시 선택 -> REQUIRED
        if set(input.selected_metrics) & LONG_RANGE_DEPENDENT_METRICS:
            return EInterPolicyOutput(
                level=EInterRecommendationLevel.REQUIRED,
                score=1.0,
                reason_codes=("long_range_metric_selected",),
                # Codex #4: v1 returns e_inter_total only
                affected_metrics=V1_SUPPORTED_METRICS,
                default_enabled=True,
            )

        # Rule 2: water/ion/polar layered -> REQUIRED
        if input.workflow == "layered_structure" and input.has_water_ion:
            return EInterPolicyOutput(
                level=EInterRecommendationLevel.REQUIRED,
                score=1.0,
                reason_codes=("layered_water_ion_polar",),
                # Codex #4: v1 returns e_inter_total (layer_matrix in v2)
                affected_metrics=V1_SUPPORTED_METRICS,
                default_enabled=True,
            )

        # Rule 3: 구조 생성 전용 -> NONE
        if input.workflow in (
            "interface_molecule",
            "crystal_structure",
            "single_molecule_vacuum",
        ):
            return EInterPolicyOutput(
                level=EInterRecommendationLevel.NONE,
                score=0.0,
                reason_codes=("structure_generation_only",),
            )

        # Rule 4: layered 2+ layers -> RECOMMENDED
        if input.workflow == "layered_structure" and input.layer_count >= 2:
            reason_codes.append("layered_2plus_layers")
            score = max(score, 0.7)

        # Rule 5: binder + additive -> RECOMMENDED
        if input.workflow in ("binder_cell", "batch_binder_cell") and input.has_additive:
            reason_codes.append("binder_with_additive")
            score = max(score, 0.6)

        # Rule 6: 일반 SARA binder -> OPTIONAL
        if input.workflow in ("binder_cell", "batch_binder_cell") and not reason_codes:
            reason_codes.append("binder_without_additive")
            score = max(score, 0.3)

        # Score-based level
        if score >= 0.6:
            level = EInterRecommendationLevel.RECOMMENDED
            default_enabled = False
        elif score >= 0.3:
            level = EInterRecommendationLevel.OPTIONAL
            default_enabled = False
        else:
            level = EInterRecommendationLevel.NONE
            default_enabled = False

        return EInterPolicyOutput(
            level=level,
            score=score,
            reason_codes=tuple(reason_codes),
            # Codex #4: v1 always returns e_inter_total
            affected_metrics=V1_SUPPORTED_METRICS if reason_codes else (),
            estimated_cpu_cost_minutes=self._estimate_cost(input),
            default_enabled=default_enabled,
        )

    def _estimate_cost(self, input: EInterPolicyInput) -> float:
        """Estimate CPU rerun cost in minutes."""
        TIER_MULTIPLIER = {
            "screening": 1.0,
            "confirm": 2.5,
            "viscosity": 6.0,
            "validation": 1.0,
        }
        return 5.0 + (input.estimated_atoms * 0.001 * TIER_MULTIPLIER.get(input.tier, 1.0))


DEFAULT_E_INTER_POLICY_EVALUATOR = EInterComputePolicyEvaluator()


def resolve_default_einter_config(
    policy_input: EInterPolicyInput,
    *,
    evaluator: EInterComputePolicyEvaluator | None = None,
) -> EInterComputeConfig | None:
    """명시 설정이 없는 실험에 적용할 기본 정밀 E_inter 설정을 해석한다.

    계면(layered) 실험은 정전기 지배적이라 장거리 Coulomb 복원이 필요하다(원칙 #2).
    정책 평가가 정밀 e_inter를 RECOMMENDED/REQUIRED로 판정하고 SSOT 플래그
    ``AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED``가 True일 때만, GPU 완료 후 자동
    CPU rerun을 트리거하는 활성 config를 반환한다. 그 외에는 None(자동 활성화 안 함).

    동역학은 GPU/KOKKOS로 유지되고 rerun만 CPU 후처리이므로 dynamics는 불변이다.
    호출부는 사용자가 명시한 ``interaction_analysis``가 있으면 이 함수를 호출하지
    않아야 한다(명시 설정이 항상 우선).

    Args:
        policy_input: 정책 평가 입력(workflow/tier/layer_count 등).
        evaluator: 테스트용 평가기 주입(기본 SSOT 평가기 사용).

    Returns:
        자동 활성화할 ``EInterComputeConfig`` 또는 ``None``.
    """
    if not AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED:
        return None
    # P1-3: CPU rerun 검증은 bulk_ff_gaff2만 허용(EInterComputeService).
    # 다른 ff_type(reaxff 등)에 자동 활성화하면 완료마다 검증 거부+경고 반복 →
    # 애초에 활성화하지 않는다(검증 게이트와 정합).
    if policy_input.ff_type not in SUPPORTED_CPU_RERUN_FF_TYPES:
        return None
    ev = evaluator or DEFAULT_E_INTER_POLICY_EVALUATOR
    result = ev.evaluate(policy_input)
    if result.level not in _AUTO_ENABLE_LEVELS:
        return None
    metrics = list(result.affected_metrics) or list(V1_SUPPORTED_METRICS)
    return EInterComputeConfig(
        enabled=True,
        mode=EInterComputeMode.GPU_THEN_CPU,
        metrics=metrics,
        auto_trigger_rerun=True,
    )
