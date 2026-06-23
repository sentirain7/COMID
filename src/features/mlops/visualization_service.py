"""ML diagnostics visualization service.

Reconstructs diagnostic data from model artifacts and training snapshots.
No additional DB columns/tables required — all data is derived from:
  - MLModelVersionModel.model_artifact_path → MultiTargetPredictor.load()
  - MLModelVersionModel.training_data_snapshot_path → test_exp_ids
  - DataLoader.load_from_database() → TrainingDataset
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from api.schemas.ml_visualization import (
    DataCoverageResponse,
    DataQualityIssue,
    DataQualityResponse,
    FeatureImportanceItem,
    FeatureImportanceResponse,
    LearningCurvePoint,
    LearningCurveResponse,
    ParityPlotResponse,
    ParityPoint,
    ResidualResponse,
    StructuralEvalResponse,
    StructuralMLStatusResponse,
    StructuralModelEval,
    StructuralTrainResponse,
)
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion

_logger = logging.getLogger(__name__)


def _resolve_e_intra_method_diagnostics(
    session: Any,
    *,
    strict_champion: bool,
) -> dict[str, Any]:
    """Resolve champion and submission-default E_intra method diagnostics.

    Champion method must come from deployed model lineage SSOT via
    ``api.deps._resolve_champion_e_intra_method``. Submission default comes
    from the submission resolver SSOT used by new experiment requests.
    """
    from api.deps import _resolve_champion_e_intra_method
    from config.dashboard_settings import resolve_submission_e_intra_method

    champion_method = _resolve_champion_e_intra_method(session, strict=strict_champion)
    submission_default_method = resolve_submission_e_intra_method().value

    return {
        "e_intra_method": champion_method,
        "champion_e_intra_method": champion_method,
        "submission_default_e_intra_method": submission_default_method,
        "e_intra_method_mismatch": bool(
            champion_method and champion_method != submission_default_method
        ),
        "method_resolution_status": (
            "champion_lineage" if champion_method else "cold_start_no_champion"
        ),
    }


def _load_champion_and_snapshot(session: Any) -> tuple[Any, dict, Any]:
    """Load champion model row, snapshot dict, and predictor.

    Returns:
        (db_row, snapshot_dict, MultiTargetPredictor)

    Raises:
        ValueError: if champion or artifact not found.
    """
    from database.repositories.model_version_repo import ModelVersionRepository

    repo = ModelVersionRepository(session)
    champion = repo.get_champion()
    if champion is None:
        raise ValueError("No champion model found")

    artifact_path = champion.model_artifact_path
    snapshot_path = champion.training_data_snapshot_path

    if not artifact_path or not Path(artifact_path).exists():
        raise ValueError(f"Model artifact not found: {artifact_path}")

    from ml.multi_target import MultiTargetPredictor

    predictor = MultiTargetPredictor.load(Path(artifact_path))

    snapshot: dict = {}
    if snapshot_path and Path(snapshot_path).exists():
        snapshot = json.loads(Path(snapshot_path).read_text())

    return champion, snapshot, predictor


def _reconstruct_test_data(
    session: Any,
    predictor: Any,
    snapshot: dict,
    target_name: str,
    champion_row: Any = None,
    include_exp_ids: set[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    """Reconstruct predictions from snapshot for selected experiments.

    Loads data using the same feature-set version that the champion was
    trained on, so feature dimensions match. Loader routing is delegated
    to ml.dataset_router, which preserves the correct bulk/layered SSOT.

    Args:
        include_exp_ids: Experiments to predict. Default None keeps the
            legacy behaviour (snapshot ``test_exp_ids`` only — used by
            residuals etc.); the parity plot passes the union of
            train/validation/test so 학습·검증 포인트가 함께 표출된다.

    Returns:
        (y_actual, y_predicted, exp_ids, uncertainties) for the intersection
        of the requested exp_ids and available DB data.

    Raises:
        ValueError: if reconstruction fails for any reason.
    """
    from ml.data_loader import TargetVariable
    from ml.dataset_router import load_training_dataset

    test_exp_ids = (
        set(include_exp_ids)
        if include_exp_ids is not None
        else set(snapshot.get("test_exp_ids", []))
    )
    if not test_exp_ids:
        raise ValueError("No test_exp_ids in training snapshot")

    try:
        tv = TargetVariable(target_name)
    except ValueError as e:
        raise ValueError(f"Unknown target: {target_name}") from e

    # Determine feature-set version from champion metadata
    fsv = FeatureSetVersion.V1
    if champion_row is not None and champion_row.feature_set_version:
        try:
            fsv = FeatureSetVersion(champion_row.feature_set_version)
        except ValueError:
            pass

    # PR 2 (Codex Round 4): for CED parity/residuals, resolve the champion's
    # training E_intra method from real lineage fields, not a non-existent
    # ``metadata_json`` attribute.  Order:
    #   1) ``training_config_json["e_intra_method"]`` (registry row)
    #   2) ``snapshot["e_intra_method"]`` (snapshot fallback)
    #   3) None → DataLoader defaults to Method 1 baseline
    from contracts.schema_enums import normalize_e_intra_method

    e_intra_method: str | None = None
    if champion_row is not None:
        cfg = getattr(champion_row, "training_config_json", None) or {}
        e_intra_method = normalize_e_intra_method(cfg.get("e_intra_method"))
    if e_intra_method is None and isinstance(snapshot, dict):
        e_intra_method = normalize_e_intra_method(snapshot.get("e_intra_method"))

    dataset = load_training_dataset(
        session,
        target=tv,
        requested_feature_set=fsv,
        min_samples=1,
        e_intra_method=e_intra_method,
    )

    if dataset is None or dataset.n_samples == 0:
        raise ValueError(f"No data available for target {target_name} with feature set {fsv.value}")

    # Intersect with snapshot test_exp_ids
    indices = [i for i, eid in enumerate(dataset.exp_ids) if eid in test_exp_ids]
    if not indices:
        raise ValueError("No overlapping test samples found")

    idx_arr = np.array(indices, dtype=int)
    X_test = dataset.X[idx_arr]
    y_actual = dataset.y[idx_arr]
    exp_ids = [dataset.exp_ids[i] for i in indices]

    # Re-predict — use predict_batch which handles dimension guards internally
    results = predictor.predict_batch(X_test, targets=[target_name])

    # Verify predictions were actually produced (not silently skipped)
    y_predicted = np.array([r.predictions.get(target_name, np.nan) for r in results], dtype=float)
    valid_mask = ~np.isnan(y_predicted)
    if not np.any(valid_mask):
        raise ValueError(
            f"Prediction failed for target '{target_name}': feature dimension mismatch "
            f"(input {X_test.shape[1]} features, model may expect different count)"
        )
    if not np.all(valid_mask):
        _logger.warning(
            "Some predictions for '%s' were skipped (%d/%d valid)",
            target_name,
            int(np.sum(valid_mask)),
            len(valid_mask),
        )
        idx_valid = np.where(valid_mask)[0]
        y_actual = y_actual[idx_valid]
        y_predicted = y_predicted[idx_valid]
        exp_ids = [exp_ids[i] for i in idx_valid]

    uncertainties = np.array([r.uncertainties.get(target_name, 0.0) for r in results], dtype=float)
    if not np.all(valid_mask):
        uncertainties = uncertainties[np.where(valid_mask)[0]]

    return y_actual, y_predicted, exp_ids, uncertainties


def _split_metrics(y_actual: np.ndarray, y_predicted: np.ndarray) -> dict[str, float]:
    """RMSE/R²/MAE for one split (original scale)."""
    residuals = y_actual - y_predicted
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y_actual - np.mean(y_actual)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"rmse": rmse, "r2": r2, "mae": mae, "n_points": float(len(y_actual))}


def get_parity_plot(session: Any, target: str) -> ParityPlotResponse:
    """Build parity plot data for champion model on a target.

    Points carry a ``split`` label (train/validation/test, snapshot 기준)
    so the frontend renders 학습 vs 검증 예측을 서로 다른 색으로 표출한다.
    ``metrics``는 기존과 동일하게 holdout(test, 없으면 validation) 기준이고,
    ``train_metrics``는 train split만의 지표다.
    """
    champion, snapshot, predictor = _load_champion_and_snapshot(session)

    if target not in predictor.fitted_targets:
        raise ValueError(f"Target '{target}' not fitted in champion model")

    split_ids: dict[str, set[str]] = {
        "train": set(snapshot.get("train_exp_ids", [])),
        "validation": set(snapshot.get("val_exp_ids", [])),
        "test": set(snapshot.get("test_exp_ids", [])),
    }

    y_actual, y_predicted, exp_ids, uncertainties = _reconstruct_test_data(
        session,
        predictor,
        snapshot,
        target,
        champion_row=champion,
        include_exp_ids=set().union(*split_ids.values()) or None,
    )

    def _label(eid: str) -> str | None:
        for name, ids in split_ids.items():
            if eid in ids:
                return name
        return None

    residuals = y_actual - y_predicted
    points = [
        ParityPoint(
            exp_id=eid,
            actual=float(ya),
            predicted=float(yp),
            uncertainty=float(u) if u > 0 else None,
            residual=float(r),
            split=_label(eid),
        )
        for eid, ya, yp, u, r in zip(
            exp_ids, y_actual, y_predicted, uncertainties, residuals, strict=True
        )
    ]

    # metrics = holdout 기준 (기존 계약 유지): test 우선, 없으면 validation,
    # 그것도 없으면 전체(레거시 snapshot 호환).
    def _mask(name: str) -> np.ndarray:
        return np.array([p.split == name for p in points], dtype=bool)

    holdout_mask = _mask("test")
    if not holdout_mask.any():
        holdout_mask = _mask("validation")
    if not holdout_mask.any():
        holdout_mask = np.ones(len(points), dtype=bool)
    metrics = _split_metrics(y_actual[holdout_mask], y_predicted[holdout_mask])
    metrics["n_points"] = float(len(points))

    train_mask = _mask("train")
    train_metrics = (
        _split_metrics(y_actual[train_mask], y_predicted[train_mask])
        if train_mask.any()
        else None
    )

    return ParityPlotResponse(
        target=target,
        points=points,
        metrics=metrics,
        train_metrics=train_metrics,
    )


def get_feature_importance(session: Any, target: str, top_k: int = 15) -> FeatureImportanceResponse:
    """Extract feature importances from champion ensemble."""
    champion, _snapshot, predictor = _load_champion_and_snapshot(session)

    if target not in predictor.fitted_targets:
        raise ValueError(f"Target '{target}' not fitted in champion model")

    ensemble = predictor._ensembles.get(target)
    if ensemble is None:
        raise ValueError(f"No ensemble for target '{target}'")

    # Average feature importances across ensemble members
    all_importances: list[np.ndarray] = []
    feature_names: list[str] = []
    for member in ensemble.predictors:
        fi = member.get_feature_importances()
        if fi:
            if not feature_names:
                feature_names = list(fi.keys())
            all_importances.append(np.array(list(fi.values()), dtype=float))

    if not all_importances:
        raise ValueError("No feature importances available")

    avg_imp = np.mean(all_importances, axis=0)
    # Rank by importance (descending)
    ranked_idx = np.argsort(avg_imp)[::-1][:top_k]

    features = [
        FeatureImportanceItem(
            name=feature_names[i],
            importance=float(avg_imp[i]),
            rank=rank + 1,
        )
        for rank, i in enumerate(ranked_idx)
    ]

    fsv = champion.feature_set_version or "v1"

    return FeatureImportanceResponse(
        target=target,
        features=features,
        feature_set_version=fsv,
    )


def get_residuals(session: Any, target: str) -> ResidualResponse:
    """Compute residual distribution for champion model."""
    champion, snapshot, predictor = _load_champion_and_snapshot(session)

    if target not in predictor.fitted_targets:
        raise ValueError(f"Target '{target}' not fitted in champion model")

    y_actual, y_predicted, _exp_ids, _unc = _reconstruct_test_data(
        session, predictor, snapshot, target, champion_row=champion
    )

    residuals = (y_actual - y_predicted).tolist()
    arr = np.array(residuals)
    n = len(arr)
    mean = float(np.mean(arr))
    std = float(np.std(arr)) if n > 1 else 0.0

    # Skewness (Fisher)
    if n > 2 and std > 0:
        skew = float(np.mean(((arr - mean) / std) ** 3))
    else:
        skew = 0.0

    return ResidualResponse(
        target=target,
        residuals=residuals,
        stats={"mean": mean, "std": std, "skew": skew, "count": n},
    )


def get_learning_curve(session: Any, target: str) -> LearningCurveResponse:
    """Extract learning curve from model version history."""
    from database.repositories.model_version_repo import ModelVersionRepository

    repo = ModelVersionRepository(session)
    rows = repo.get_history(limit=100)

    points: list[LearningCurvePoint] = []
    for row in reversed(rows):
        train_metrics = row.train_metrics_json or {}
        val_metrics = row.val_metrics_json or {}
        test_metrics = row.test_metrics_json or {}

        train_rmse = _extract_rmse(train_metrics, target)
        val_rmse = _extract_rmse(val_metrics, target)
        test_rmse = _extract_rmse(test_metrics, target)

        if train_rmse is not None and test_rmse is not None:
            points.append(
                LearningCurvePoint(
                    training_samples=row.training_samples or 0,
                    train_rmse=train_rmse,
                    val_rmse=val_rmse or 0.0,
                    test_rmse=test_rmse,
                    version_id=row.version_id,
                )
            )

    return LearningCurveResponse(target=target, points=points)


def _extract_rmse(metrics_json: dict, target: str) -> float | None:
    """Extract RMSE for a target from metrics JSON."""
    if not isinstance(metrics_json, dict):
        return None
    target_m = metrics_json.get(target)
    if isinstance(target_m, dict):
        return target_m.get("rmse")
    return None


def get_data_coverage(session: Any) -> DataCoverageResponse:
    """Analyze data coverage for ML training.

    PR 2 (Codex Round 8): coverage now uses the same fail-closed contract
    as the retrain/drift critical paths — registry failures surface as
    ``RuntimeError`` instead of silently reverting to Method 1 baseline.
    The response carries ``method_resolution_status`` so the UI can show
    when the champion method came from cold-start (no champion) versus
    explicit lineage versus a degraded fallback path (deprecated).
    """
    from ml.data_loader import TargetVariable
    from ml.dataset_router import load_training_dataset

    policy = DEFAULT_ML_POLICY
    # Strict mode: a broken registry must NOT silently underreport CED
    # coverage.  Cold start (no champion row at all) still returns ``None``
    # without raising — that is a benign state, not a registry failure.
    method_diagnostics = _resolve_e_intra_method_diagnostics(session, strict_champion=True)
    champion_method = method_diagnostics["champion_e_intra_method"]

    # Count total completed experiments
    from database.models import ExperimentModel

    total = session.query(ExperimentModel).filter(ExperimentModel.status == "completed").count()

    # Per-target coverage (uses dataset_router for correct bulk/layered routing)
    per_target: dict[str, dict] = {}
    for tv in TargetVariable.trainable():
        ds = load_training_dataset(
            session, target=tv, min_samples=1, e_intra_method=champion_method
        )
        samples = ds.n_samples if ds is not None else 0
        min_req = policy.min_training_samples
        per_target[tv.value] = {
            "samples": samples,
            "sufficient": samples >= min_req,
            "min_required": min_req,
        }

    # Feature set eligibility — check actual_feature_set from loader metadata
    # to detect when the loader falls back to a lower version.
    feature_set_eligibility: dict[str, dict] = {}
    for fsv in FeatureSetVersion:
        ds = load_training_dataset(
            session,
            target=TargetVariable.DENSITY,
            requested_feature_set=fsv,
            min_samples=1,
            e_intra_method=champion_method,
        )
        samples = ds.n_samples if ds is not None else 0
        actual_fsv = (
            ds.metadata.get("actual_feature_set", fsv.value) if ds is not None else fsv.value
        )
        # Eligible only if the loader actually used the requested version
        # (i.e. did not fall back to a lower one) AND has enough samples.
        truly_eligible = samples >= policy.min_training_samples and actual_fsv == fsv.value
        feature_set_eligibility[fsv.value] = {
            "eligible": truly_eligible,
            "samples": samples,
            "min_required": policy.min_training_samples,
            "requested_feature_set": fsv.value,
            "actual_feature_set": actual_fsv,
        }

    # Composition coverage from the density dataset
    composition_coverage: dict = {}
    ds = load_training_dataset(
        session,
        target=TargetVariable.DENSITY,
        min_samples=1,
        e_intra_method=champion_method,
    )
    if ds is not None and ds.n_samples > 0:
        temp_idx = (
            ds.feature_names.index("temperature_k") if "temperature_k" in ds.feature_names else None
        )
        if temp_idx is not None:
            temps = ds.X[:, temp_idx]
            composition_coverage["temp_range"] = {
                "min": float(np.min(temps)),
                "max": float(np.max(temps)),
            }

        # SARA ranges from first 4 features (asphaltene/resin/aromatic/saturate)
        sara_names = [
            "asphaltene_wt",
            "resin_wt",
            "aromatic_wt",
            "saturate_wt",
        ]
        sara_ranges: dict = {}
        for sname in sara_names:
            if sname in ds.feature_names:
                idx = ds.feature_names.index(sname)
                col = ds.X[:, idx]
                sara_ranges[sname] = {
                    "min": float(np.min(col)),
                    "max": float(np.max(col)),
                }
        composition_coverage["sara_ranges"] = sara_ranges

    return DataCoverageResponse(
        total_experiments=total,
        per_target=per_target,
        feature_set_eligibility=feature_set_eligibility,
        composition_coverage=composition_coverage,
        **method_diagnostics,
    )


def get_data_quality(session: Any) -> DataQualityResponse:
    """Analyze data quality issues."""
    from database.models import ExperimentModel

    experiments = session.query(ExperimentModel).filter(ExperimentModel.status == "completed").all()

    issues: list[DataQualityIssue] = []

    # Track duplicates by topology+protocol hash
    hash_groups: dict[str, list[str]] = {}
    for exp in experiments:
        key = f"{getattr(exp, 'topology_hash', '')}__{getattr(exp, 'protocol_hash', '')}"
        if key != "__":
            hash_groups.setdefault(key, []).append(exp.exp_id)

    for key, eids in hash_groups.items():
        if len(eids) > 1:
            for eid in eids:
                issues.append(
                    DataQualityIssue(
                        issue_type="duplicate_experiment",
                        exp_id=eid,
                        details={"group_key": key, "group_size": len(eids)},
                    )
                )

    # Physical range checks
    for exp in experiments:
        metrics = {m.metric_name: m.value for m in (exp.metrics or [])}
        density = metrics.get("density")
        if density is not None and (density < 0.8 or density > 1.3):
            issues.append(
                DataQualityIssue(
                    issue_type="density_out_of_range",
                    exp_id=exp.exp_id,
                    details={"density": density},
                )
            )

        # Missing complementary metrics
        has_density = "density" in metrics
        has_ced = "cohesive_energy_density" in metrics
        if has_density and not has_ced:
            issues.append(
                DataQualityIssue(
                    issue_type="missing_ced",
                    exp_id=exp.exp_id,
                    details={"has_density": True, "has_ced": False},
                )
            )

    summary: dict[str, int] = {}
    for issue in issues:
        summary[issue.issue_type] = summary.get(issue.issue_type, 0) + 1

    return DataQualityResponse(
        total_experiments=len(experiments),
        issues=issues,
        summary=summary,
    )


def get_structural_ml_status() -> StructuralMLStatusResponse:
    """V7 structural ML opt-in 정책 + champion feature_set 상태.

    정책(SSOT)은 contracts에서, champion 상태는 runtime capability manifest에서
    읽는다 — 화면이 '옵트인 여부'와 'V7 champion 활성 여부'를 함께 표시한다.
    """
    from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY

    manifest: dict = {}
    try:
        from api.deps import get_runtime_capability_manifest

        manifest = get_runtime_capability_manifest() or {}
    except Exception:  # noqa: BLE001 - champion 부재/로드 실패는 상태 표시로 충분
        manifest = {}

    policy = DEFAULT_STRUCTURAL_ML_POLICY
    return StructuralMLStatusResponse(
        enabled=policy.enabled,
        targets=list(policy.targets),
        force_fields=list(policy.force_fields),
        min_labels_to_start=policy.min_labels_to_start,
        retrain_label_increment=policy.retrain_label_increment,
        champion_feature_set=manifest.get("feature_set"),
        champion_supported_targets=[
            str(t) for t in manifest.get("supported_targets", []) if t
        ],
        champion_model_types={
            str(k): str(v) for k, v in (manifest.get("model_types") or {}).items()
        },
    )


def run_structural_eval(
    session: Any,
    *,
    target: str,
    n_repeats: int = 10,
    holdout_ratio: float = 0.2,
) -> StructuralEvalResponse:
    """V7 XGB-vs-RF 랜덤 반복 평가 (on-demand, 내부 GAFF2 데이터만).

    ``structural_challenger.evaluate_v7_random_repeats``를 호출해 모델별
    mean±std(원 스케일 RMSE)와 승자를 응답으로 직렬화한다. 데이터 부족/미지원
    target은 result의 ``error`` 필드로 graceful 보고(예외 아님).
    """
    from ml.structural_challenger import evaluate_v7_random_repeats

    result = evaluate_v7_random_repeats(
        session,
        target=target,
        n_repeats=n_repeats,
        holdout_ratio=holdout_ratio,
    )
    if "error" in result:
        return StructuralEvalResponse(target=target, error=result["error"])

    models = {
        mt: StructuralModelEval(
            rmse_mean=info["rmse_mean"],
            rmse_std=info["rmse_std"],
            per_repeat=info["per_repeat"],
        )
        for mt, info in result.get("models", {}).items()
    }
    return StructuralEvalResponse(
        target=result["target"],
        n_samples=result.get("n_samples", 0),
        n_repeats=result.get("n_repeats", 0),
        transform=result.get("transform", "identity"),
        models=models,
        winner=result.get("winner"),
    )


def run_structural_train(
    session: Any,
    *,
    targets: list[str] | None = None,
    register: bool = False,
) -> StructuralTrainResponse:
    """V7 challenger 학습 (on-demand). ``register=True``면 등록·승급 판정.

    ``register`` 기본값 False는 화면에서 안전한 dry-run(학습·holdout RMSE만)을
    제공한다 — production registry 변경은 명시적 opt-in일 때만.
    """
    from ml.structural_challenger import train_structural_challenger

    outcome = train_structural_challenger(
        session, targets=targets, register=register
    )
    return StructuralTrainResponse(
        version_id=outcome.version_id,
        targets_trained=list(outcome.targets_trained),
        training_samples=outcome.training_samples,
        holdout_samples=outcome.holdout_samples,
        promoted=outcome.promoted,
        comparison=outcome.comparison,
        per_target_holdout_rmse=dict(outcome.per_target_holdout_rmse),
        model_types=dict(outcome.model_types),
        notes=list(outcome.notes),
    )
