"""ML diagnostics / visualization API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ParityPoint(BaseModel):
    """Single point in parity plot."""

    exp_id: str
    actual: float
    predicted: float
    uncertainty: float | None = None
    residual: float
    # 데이터 분할 라벨 — 'train' | 'validation' | 'test'. 프론트에서 학습/검증
    # 포인트를 서로 다른 색으로 구분 표출하는 데 사용 (None = 레거시 응답).
    split: str | None = None


class ParityPlotResponse(BaseModel):
    """Parity plot data for a target."""

    target: str
    points: list[ParityPoint]
    metrics: dict[str, float]  # holdout(rmse, r2, mae, n_points)
    # 학습(train) split만의 지표 — holdout 지표(metrics)와 분리 보고.
    train_metrics: dict[str, float] | None = None


class StructuralMLStatusResponse(BaseModel):
    """V7 structural ML opt-in policy + champion 상태 (MLOps 화면 표시용)."""

    enabled: bool
    targets: list[str]
    force_fields: list[str]
    min_labels_to_start: int
    retrain_label_increment: int
    champion_feature_set: str | None = None  # champion의 feature_set (v7 여부)
    champion_supported_targets: list[str] = Field(default_factory=list)
    # 물성→승자 모델(xgboost/random_forest) — V7 champion일 때만 채워짐(B2).
    champion_model_types: dict[str, str] = Field(default_factory=dict)


class StructuralModelEval(BaseModel):
    """단일 모델(XGB 또는 RF)의 랜덤 반복 평가 요약 (원 스케일 RMSE)."""

    rmse_mean: float
    rmse_std: float  # 표본 표준편차(ddof=1) — 오차막대
    per_repeat: list[float]


class StructuralEvalRequest(BaseModel):
    """On-demand V7 랜덤 반복 평가 요청 (XGB vs RF 경쟁, 내부 데이터만)."""

    target: str = "density"
    n_repeats: int = Field(default=10, ge=2, le=50)
    holdout_ratio: float = Field(default=0.2, gt=0.0, lt=0.9)


class StructuralEvalResponse(BaseModel):
    """V7 XGB-vs-RF 랜덤 반복 평가 결과 (mean±std + 승자)."""

    target: str
    n_samples: int = 0
    n_repeats: int = 0
    transform: str = "identity"
    models: dict[str, StructuralModelEval] = Field(default_factory=dict)
    winner: str | None = None
    error: str | None = None  # 데이터 부족/미지원 target 시 메시지


class StructuralTrainRequest(BaseModel):
    """On-demand V7 challenger 학습 요청 (물성별 XGB-vs-RF 승자 선택)."""

    # 와이어 키는 ``register``로 유지하되, 필드명은 ABCMeta.register 그림자
    # 경고를 피하기 위해 alias로 분리한다(populate_by_name으로 양쪽 허용).
    model_config = ConfigDict(populate_by_name=True)

    targets: list[str] | None = None  # 기본: V7 적격 전체
    # True면 registry 등록·승급 판정 (production DB 변경)
    register_challenger: bool = Field(default=False, alias="register")


class StructuralTrainResponse(BaseModel):
    """V7 challenger 학습 결과 (ChallengerOutcome 직렬화)."""

    version_id: str | None = None
    targets_trained: list[str] = Field(default_factory=list)
    training_samples: int = 0
    holdout_samples: int = 0
    promoted: bool = False
    comparison: dict | None = None
    per_target_holdout_rmse: dict[str, float] = Field(default_factory=dict)
    model_types: dict[str, str] = Field(default_factory=dict)  # 물성→승자 모델
    notes: list[str] = Field(default_factory=list)


class FeatureImportanceItem(BaseModel):
    """Single feature importance entry."""

    name: str
    importance: float
    rank: int


class FeatureImportanceResponse(BaseModel):
    """Feature importance for a target."""

    target: str
    features: list[FeatureImportanceItem]
    feature_set_version: str


class ResidualResponse(BaseModel):
    """Residual distribution for a target."""

    target: str
    residuals: list[float]
    stats: dict[str, float]  # mean, std, skew, count


class LearningCurvePoint(BaseModel):
    """Single point on learning curve."""

    training_samples: int
    train_rmse: float
    val_rmse: float
    test_rmse: float
    version_id: str


class LearningCurveResponse(BaseModel):
    """Learning curve over model versions."""

    target: str
    points: list[LearningCurvePoint]


class DataCoverageResponse(BaseModel):
    """Data coverage diagnostics.

    PR 2: coverage exposes both deployed-champion lineage and the current
    submission default so backend/UI consumers can detect contract drift
    without inferring from unrelated settings or training metadata.

    ``champion_e_intra_method`` remains the champion-lineage SSOT for
    coverage calculations. ``submission_default_e_intra_method`` is the
    currently resolved default for new submissions. ``e_intra_method`` is
    preserved as a backward-compatible alias of ``champion_e_intra_method``.

    ``method_resolution_status`` exposes how the champion-side contract was
    resolved for this coverage view, so the UI can distinguish:

    - ``champion_lineage`` — derived from the deployed champion's
      ``training_config_json["e_intra_method"]``.
    - ``cold_start_no_champion`` — no champion exists yet; coverage uses
      the legacy Method 1 baseline as a benign default.

    Registry failures no longer fall back silently — they surface as
    HTTP 5xx (see ``get_data_coverage`` strict resolver).
    """

    total_experiments: int
    per_target: dict[str, dict]
    feature_set_eligibility: dict[str, dict]
    composition_coverage: dict
    e_intra_method: str | None = Field(
        default=None,
        description="Deprecated alias of champion_e_intra_method for compatibility.",
    )
    champion_e_intra_method: str | None = Field(
        default=None,
        description="Resolved E_intra method from deployed champion lineage.",
    )
    submission_default_e_intra_method: str | None = Field(
        default=None,
        description="Resolved default E_intra method for new submissions.",
    )
    e_intra_method_mismatch: bool = Field(
        default=False,
        description=(
            "True when the deployed champion lineage method differs from the "
            "current submission default."
        ),
    )
    method_resolution_status: str = Field(
        default="cold_start_no_champion",
        description="Champion method resolution status for this diagnostics response.",
    )


class DataQualityIssue(BaseModel):
    """Single data quality issue."""

    issue_type: str
    exp_id: str
    details: dict


class DataQualityResponse(BaseModel):
    """Data quality diagnostics."""

    total_experiments: int
    issues: list[DataQualityIssue]
    summary: dict[str, int]
