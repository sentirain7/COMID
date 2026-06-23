"""
E_inter 계산 모드 정책 (SSOT).

GPU/KOKKOS 기본 실행은 short-range 상호작용만 group 간 분리.
정밀 E_inter (장거리 Coulomb 분리 포함) 필요 시 CPU rerun 사용.

All sessions must use this policy for E_inter mode decisions.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from contracts.schema_enums import EInterComputeMode, EInterRecommendationLevel


@dataclass(frozen=True)
class EInterPolicyInput:
    """정책 평가 입력.

    Attributes:
        workflow: 워크플로우 유형 (bulk, layer, etc.)
        tier: 실행 티어 (screening, confirm, etc.)
        ff_type: Force field 유형
        layer_count: 레이어 수 (layered structure)
        has_additive: 첨가제 포함 여부
        has_polar_molecules: 극성 분자 포함 여부
        has_water_ion: 물/이온 포함 여부
        selected_metrics: 선택된 메트릭 목록
        estimated_atoms: 예상 원자 수
    """

    workflow: str
    tier: str
    ff_type: str = "bulk_ff_gaff2"
    layer_count: int = 1
    has_additive: bool = False
    has_polar_molecules: bool = False
    has_water_ion: bool = False
    selected_metrics: tuple[str, ...] = ()
    estimated_atoms: int = 0


@dataclass(frozen=True)
class EInterPolicyOutput:
    """정책 평가 출력.

    Attributes:
        level: 추천 수준 (none, optional, recommended, required)
        score: 추천 점수 (0.0-1.0)
        reason_codes: 추천 사유 코드 목록
        affected_metrics: 영향받는 메트릭 목록
        estimated_cpu_cost_minutes: 예상 CPU 비용 (분)
        default_enabled: 기본 활성화 여부
    """

    level: EInterRecommendationLevel
    score: float
    reason_codes: tuple[str, ...] = ()
    affected_metrics: tuple[str, ...] = ()
    estimated_cpu_cost_minutes: float = 0.0
    default_enabled: bool = False


# Long-range Coulomb 분리가 필요한 메트릭 집합
# GPU/KOKKOS 기본 실행에서는 정밀도가 떨어질 수 있음
LONG_RANGE_DEPENDENT_METRICS: frozenset[str] = frozenset(
    {
        "e_inter_total",
        "e_inter_layer_matrix",
        "e_inter_additive_binder",
        "adhesion_energy",
    }
)


# 계면(layered) 실험의 정밀 E_inter(장거리 Coulomb 포함) CPU rerun 자동 활성화 (SSOT).
#
# 광물 계면에서는 양이온(Si, Al, Ti)의 LJ ε이 극히 작아(~1e-4 kcal/mol) 계면
# 상호작용이 정전기(Coulomb) 지배적이다. KOKKOS ``compute group/group``은
# ``kspace yes``를 지원하지 않으므로 GPU 실행만으로 측정한 계면 e_inter는
# 장거리 Coulomb 기여가 빠져 물리적으로 불완전하다.
#
# 동역학(NVT/NPT 적분)은 GPU/KOKKOS로 그대로 유지되고, 빠진 장거리 Coulomb은
# trajectory를 1회 CPU ``rerun``(저비용 후처리)으로 복원한다. 따라서 정책 평가가
# 정밀 e_inter를 RECOMMENDED/REQUIRED로 판정한 layered 실험은 명시 설정이 없을 때
# 이 기본값에 따라 자동 활성화된다.
#
# - 명시적 ``interaction_analysis`` 요청은 항상 이 기본값을 덮어쓴다(opt-out 가능).
# - bulk/일반 binder 경로는 정책상 RECOMMENDED가 아니므로 영향 없음 → byte-identical.
AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED: bool = True


# CPU rerun E_inter v1이 지원하는 ff_type (SSOT). EInterComputeService 검증 게이트와
# 자동 활성화 판정(resolve_default_einter_config)이 동일 집합을 참조한다.
SUPPORTED_CPU_RERUN_FF_TYPES: frozenset[str] = frozenset({"bulk_ff_gaff2"})


class EInterComputeConfig(BaseModel):
    """Submit request용 E_inter 계산 설정.

    사용자가 실험 제출 시 E_inter 계산 모드를 지정하는 데 사용.
    """

    enabled: bool = Field(default=False, description="CPU rerun 활성화")
    mode: EInterComputeMode = Field(default=EInterComputeMode.GPU_FAST)
    metrics: list[str] = Field(default_factory=lambda: ["e_inter_total"])
    auto_trigger_rerun: bool = Field(default=True, description="GPU 완료 후 자동 트리거")
    recommendation_ack: bool = Field(default=False, description="추천 확인 여부")


__all__ = [
    "EInterPolicyInput",
    "EInterPolicyOutput",
    "LONG_RANGE_DEPENDENT_METRICS",
    "AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED",
    "SUPPORTED_CPU_RERUN_FF_TYPES",
    "EInterComputeConfig",
]
