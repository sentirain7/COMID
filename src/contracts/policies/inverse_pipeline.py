"""Inverse-design pipeline policy (SSOT).

docs/plans/INVERSE_DESIGN_AUTOMATION_PLAN.md의 정책 값:
- §5  목표 metric namespace → 실험 편성 매핑 (tier 승급 미사용)
- §4.5 콜드스타트 부트스트랩 진입 조건 (n_min_labels, 시드 배치)
- §4.7 조성 기반 유사실험 재사용 허용오차 (존재확인)
- §7  닫힌 루프 정지/수정 기준 (P7 소비, 기본 OFF)
- §2  수분손상 건습비(ER) 임계값 (P6 소비)

메트릭 정의 자체의 SSOT는 contracts/policies/metrics.py이며, 이 정책은
"어떤 metric이 어떤 실험/프로토콜 프리셋을 요구하는가"만 정의한다.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from contracts.policies.temperature import (
    DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K,
    DEFAULT_TEMPERATURE_PRIORITY_K,
)


class PipelineMode(StrEnum):
    """preview_plan이 결정론적으로 판정하는 파이프라인 모드 (§4.5)."""

    BOOTSTRAP = "bootstrap"  # DOE 시드 배치 — champion 미지원 또는 라벨 부족
    BO = "bo"  # 기존 run_inverse_design (Bayesian 역설계)


class PlannedExperimentKind(StrEnum):
    """파이프라인이 목표 metric으로부터 편성하는 실험 종류 (§5)."""

    BINDER_CELL = "binder_cell"
    LAYERED_TENSILE = "layered_tensile"
    WATER_INTERFACE_LAYERED = "water_interface_layered"


class ColdStartPolicy(BaseModel):
    """콜드스타트(BOOTSTRAP) 진입 조건과 시드 배치 구성 (§4.5)."""

    n_min_labels: int = Field(
        12,
        ge=1,
        description="BO 모드 진입에 필요한 표적 metric별 최소 학습 라벨 수 "
        "(completed 실험의 스칼라 metric 수). 미만이면 BOOTSTRAP",
    )
    seed_batch_size: int = Field(
        8, ge=1, description="BOOTSTRAP 모드에서 생성하는 공간충전 시드 조성 개수"
    )
    seed_rng_seed: int = Field(
        20260611,
        description="시드 조성 생성의 결정적 RNG seed (i번째 시드는 seed+i) — "
        "재현가능/감사가능한 DOE",
    )


class CompositionSimilarityPolicy(BaseModel):
    """조성 기반 유사실험(재사용 후보) 검색 허용오차 (§4.7 존재확인)."""

    comp_tolerance_wt: float = Field(
        1.0, gt=0, description="SARA 성분별 wt% 허용오차 (±, comp_*_wt 4컬럼 각각)"
    )
    additive_wt_tolerance: float = Field(0.5, ge=0, description="첨가제 wt% 허용오차 (±)")
    temperature_tolerance_k: float = Field(5.0, ge=0, description="온도 허용오차 (±K)")
    limit: int = Field(5, ge=1, description="반환 최대 매칭 실험 수")


class ClosedLoopPolicy(BaseModel):
    """닫힌 루프(결과분석→계획수정) 정지/수정 기준 (§7, P7 소비).

    기본 OFF — NPT 조기종료(v01.05.12)·FeasibilityScout(v01.05.17)와 동일한
    opt-in 정책. 활성화는 배포별 의사결정.
    """

    enabled: bool = Field(False, description="닫힌 루프 자동 라운드 진행 (기본 OFF)")
    max_rounds: int = Field(5, ge=1, description="최대 라운드 수 (예산캡)")
    max_total_experiments: int = Field(
        60, ge=1, description="파이프라인 전체 실험 수 상한 (예산캡)"
    )
    stop_no_improve_rounds: int = Field(
        2, ge=1, description="연속 K라운드 무개선 시 정지 (개선=SE 배수 초과만 인정)"
    )
    improvement_min_se_multiple: float = Field(
        1.0,
        gt=0,
        description="'개선'으로 인정하는 최소 폭 = 관측 SE × 이 배수 "
        "(단일 seed 노이즈를 개선으로 오인하지 않음)",
    )


class MoistureDamagePolicy(BaseModel):
    """수분손상 건습비(ER, wet/dry retained ratio) 판정 임계값 (§2, P6 소비).

    AASHTO T 283 TSR(인장강도비) 0.80 관행을 차용 — 여기서는 계면
    work_of_separation/ITS의 wet/dry 비율에 적용한다.
    """

    er_warn_threshold: float = Field(
        0.80, gt=0, le=1.0, description="ER < warn → 수분민감 경고 (TSR 0.80 관행)"
    )
    er_fail_threshold: float = Field(
        0.70, gt=0, le=1.0, description="ER < fail → 수분손상 부적합 판정"
    )

    # ── water 층 자동 프로비저닝 (wet 계면, P6) ──
    water_mol_id: str = Field(
        "H2O", description="water 층 분자 ID (single_moles 라이브러리, water_model route)"
    )
    water_layer_thickness_angstrom: float = Field(
        10.0, gt=0, description="water 층 두께 (WaterLayerSpec 기본과 정합)"
    )
    water_target_density: float = Field(1.0, gt=0, description="water 층 목표 밀도 (g/cm3)")
    water_default_xy_angstrom: float = Field(
        40.0, gt=0, description="parent binder box를 알 수 없을 때의 water 셀 XY 폴백"
    )

    @model_validator(mode="after")
    def _fail_below_warn(self) -> "MoistureDamagePolicy":
        if self.er_fail_threshold > self.er_warn_threshold:
            raise ValueError("er_fail_threshold must be <= er_warn_threshold")
        return self


class InversePipelinePolicy(BaseModel):
    """역설계 파이프라인 정책 (SSOT)."""

    # ── §5 매핑: metric namespace 값 → 실험 종류 ──
    # 키는 MetricNamespace의 str 값. reaxff/derived는 의도적으로 미포함
    # (파이프라인이 편성하지 않는 namespace → preview에서 fail-fast).
    namespace_experiment_map: dict[str, PlannedExperimentKind] = Field(
        default_factory=lambda: {
            "bulk_ff_gaff2": PlannedExperimentKind.BINDER_CELL,
            "mechanical": PlannedExperimentKind.LAYERED_TENSILE,
            "layer": PlannedExperimentKind.LAYERED_TENSILE,
        },
        description="목표 metric namespace → 편성 실험 종류 (§5 매핑표)",
    )

    # ── §5 metric별 오버라이드 (레지스트리 이름, 프로토콜 프리셋 선택용) ──
    viscosity_stage_metrics: list[str] = Field(
        default_factory=lambda: ["viscosity"],
        description="표적에 포함되면 binder cell에 NEMD(점도) 스테이지를 강제 "
        "(run_tier='viscosity' 체인 라벨, §5.1)",
    )
    multi_temperature_metrics: list[str] = Field(
        default_factory=lambda: ["glass_transition_temperature_k"],
        description="표적에 포함되면 다온도 binder cell 세트를 편성 (Tg bilinear fit)",
    )
    tg_temperature_sweep_k: list[float] = Field(
        default_factory=lambda: list(DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K),
        description="다온도 세트의 온도 sweep — temperature.py SSOT 기본값",
    )
    default_temperature_k: float = Field(
        default_factory=lambda: DEFAULT_TEMPERATURE_PRIORITY_K[0],
        description="요청에 고정 온도가 없을 때의 기본 실험 온도 (K)",
    )

    # ── 후보 조합 공간: 정의 binder × 첨가제 농도 그리드 ──
    # 역설계 결정 변수는 (binder_type, additive_type, additive_wt)이다.
    # binder는 YAML SSOT의 정의 타입(AAA1/AAK1/AAM1) 중 선택, 첨가제 농도는
    # 그리드에서 선택 — 빌드는 batch job binder 경로(YAML 조성+첨가제 주입)를
    # 그대로 사용하므로 SARA wt% 연속 탐색은 하지 않는다.
    candidate_binder_types: list[str] = Field(
        default_factory=lambda: ["AAA1", "AAK1", "AAM1"],
        description="후보 조합의 binder_type 풀 (YAML binder_types 키)",
    )
    additive_wt_grid: list[float] = Field(
        default_factory=lambda: [2.0, 5.0, 8.0],
        description="후보 조합의 첨가제 농도 그리드 (wt%, additive_total bounds 내)",
    )

    cold_start: ColdStartPolicy = Field(default_factory=ColdStartPolicy)
    similarity: CompositionSimilarityPolicy = Field(default_factory=CompositionSimilarityPolicy)
    closed_loop: ClosedLoopPolicy = Field(default_factory=ClosedLoopPolicy)
    moisture: MoistureDamagePolicy = Field(default_factory=MoistureDamagePolicy)

    def experiment_kind_for_namespace(self, namespace: str) -> PlannedExperimentKind | None:
        """namespace 값으로 편성 실험 종류를 조회 (미지원 namespace는 None).

        Args:
            namespace: MetricNamespace의 str 값 (예: "bulk_ff_gaff2")

        Returns:
            편성 실험 종류, 파이프라인이 다루지 않는 namespace면 None
        """
        return self.namespace_experiment_map.get(namespace)


# SSOT: Single source of truth for inverse-design pipeline policy
DEFAULT_INVERSE_PIPELINE_POLICY = InversePipelinePolicy()
