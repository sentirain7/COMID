"""Structural (V7) ML real-time retraining policy — opt-in, default OFF.

Follows the established opt-in convention (NPT early-stop, FeasibilityScout,
closed loop): when ``enabled`` is False the completion hook does nothing and
behaviour is byte-identical. Activation triggers a V7 challenger retrain when
enough *new* GAFF2 labels for a target have accumulated since the last run.

All values are SSOT here — no hardcoding at call sites.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── FF provenance tags (SSOT) ───────────────────────────────────────────────
# V7 structural store의 force_field 태그. governance stack_id ``gaff2_am1bcc_v1``
# (stack_governance.py)의 FF-name 부분 = our 내부 GAFF2 lineage. compass_iii는
# 외부(MDML/Materials Studio) — governance 밖 research-only 참고 데이터.
FF_GAFF2_TAG = "gaff2_am1bcc"
FF_COMPASS_TAG = "compass_iii"
SOURCE_OUR = "our_production"
SOURCE_MDML = "mdml_pretrain"

# ── V7 적격 bulk 표적 (SSOT) ─────────────────────────────────────────────────
# 라벨이 있는 bulk 화학 물성. challenger의 DEFAULT_V7_TARGETS가 이를 참조한다.
# 계면(work_of_separation 등)은 V4 layered라 비포함.
V7_ELIGIBLE_TARGETS: tuple[str, ...] = (
    "density",
    "msd_diffusion_coefficient",
    "rdf_first_peak_r",
    "rdf_first_peak_g",
    "rdf_coordination_number",
)


class TreeHyperparams(BaseModel):
    """V7 평가/벤치마크용 트리 하이퍼파라미터 (SSOT — 코드 매직넘버 금지)."""

    n_estimators: int = 300
    max_depth: int = 6
    learning_rate: float = 0.05
    n_jobs: int = 4


class StructuralMLPolicy(BaseModel):
    """Real-time V7 retraining policy (opt-in)."""

    # Master switch — OFF means the completion hook is a no-op (byte-identical).
    enabled: bool = False

    # Targets eligible for V7 structural *auto-retraining* (재학습 대상 — 적격
    # 표적의 부분집합). 학습 가능 표적 전체는 V7_ELIGIBLE_TARGETS(SSOT).
    targets: tuple[str, ...] = ("density",)

    # Retrain when this many new completed labels have accumulated for a target.
    retrain_label_increment: int = 25

    # Minimum total labels before the first structural challenger is trained.
    min_labels_to_start: int = 30

    # Hold-out fraction for champion comparison during retrain.
    holdout_ratio: float = Field(default=0.2, ge=0.05, le=0.5)

    # Deterministic seed for split/training (reproducible challengers).
    random_seed: int = 42

    # Force fields to train on (GAFF2-only by default — our production lineage).
    force_fields: tuple[str, ...] = (FF_GAFF2_TAG,)

    # 내부(이 패키지)에서 생산한 데이터만 학습에 사용한다 (운영 결정, 기본 True).
    # False로 명시 전환해야만 외부(MDML/COMPASS III) 사전학습 혼합이 허용된다.
    # 기본 True면 train_from_store가 our_production/gaff2_am1bcc로 강제 필터된다.
    internal_data_only: bool = True

    # 내부 데이터의 정식 출처·FF 태그 (internal_data_only=True일 때 허용 집합).
    internal_sources: tuple[str, ...] = (SOURCE_OUR,)

    # 평가/벤치마크 트리 하이퍼파라미터 (SSOT).
    tree_hyperparams: TreeHyperparams = Field(default_factory=TreeHyperparams)


DEFAULT_STRUCTURAL_ML_POLICY = StructuralMLPolicy()
