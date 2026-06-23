"""Train and register a V7 (structural) challenger model (P3).

Reuses the existing ML infrastructure end to end:

    DataLoader.load_from_database(V7)   →  TrainingDataset (32 features)
    DataSplitter.split (group-aware)    →  train / holdout
    MultiTargetPredictor.train          →  XGBoost ensemble (models.py)
    ModelRegistry.register_model        →  challenger row + capability_manifest
    ModelRegistry.compare_with_champion →  promote if it beats the V3 champion

No new trainer/registry is introduced — V7 is wired into the per-target
feature routing (TargetFeatureSetMapping / MultiTargetConfig.target_feature_sets)
so the *same* pipeline produces a structural-feature challenger.

Decision A (champion/challenger): the challenger is registered with status
``challenger`` and only promoted when it beats the incumbent on a held-out
split of *our* GAFF2 labels — so a worse V7 model can never degrade serving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common.logging import get_logger
from contracts.policies.ml_policy import FeatureSetVersion

# V7 적격 bulk 표적은 정책 SSOT(contracts) — 코드 중복 정의 금지.
from contracts.policies.structural_ml import V7_ELIGIBLE_TARGETS as DEFAULT_V7_TARGETS

logger = get_logger("ml.structural_challenger")


def evaluate_v7_random_repeats(
    session: Any,
    *,
    target: str = "density",
    n_repeats: int = 10,
    holdout_ratio: float = 0.2,
    base_seed: int = 42,
    model_types: tuple[str, ...] = ("xgboost", "random_forest"),
    ff_type: str = "bulk_ff_gaff2",
) -> dict[str, Any]:
    """V7 모델을 랜덤 셔플 train/test 분할로 ``n_repeats``회 평가 (추정용).

    그룹(첨가제) 분할이 단일 그룹에서 train을 비우는 문제를 회피하기 위해
    **무작위 셔플 분할**을 쓰고, 서로 다른 시드로 반복해 holdout RMSE의
    평균±**표본 표준편차(ddof=1)**를 보고한다. 기본 ``n_repeats=10`` — 3회는
    std 추정 상대오차가 ±50%로 오차막대가 무의미했다(리뷰 v01.05.49+).
    같은 분할에서 **XGBoost vs RandomForest**를 함께
    돌려 모델 경쟁 결과를 제시한다. 내부(GAFF2) 데이터만 사용.

    Args:
        session: SQLAlchemy session.
        target: 평가할 물성.
        n_repeats: 랜덤 분할 반복 횟수 (기본 3).
        holdout_ratio: test 비율.
        base_seed: 반복마다 base_seed+i.
        model_types: 비교할 모델들 (xgboost / random_forest).
        ff_type: 내부 데이터 FF 필터.

    Returns:
        {target, n_samples, n_repeats, models:{type:{rmse_mean,rmse_std,per_repeat}}, winner}.
    """
    import numpy as np

    from ml.data_loader import DataLoader, DataSplitter, TargetVariable

    try:
        tv = TargetVariable(target)
    except ValueError:
        return {"error": f"unknown target '{target}'"}

    loader = DataLoader()
    dataset = loader.load_from_database(
        session,
        target=tv,
        ff_type=ff_type,
        run_tiers=["screening", "confirm"],
        min_samples=10,
        feature_set_version=FeatureSetVersion.V7,
    )
    if dataset is None or dataset.n_samples < 10:
        return {"error": f"insufficient internal V7 data for '{target}'"}

    # 로그 변환(MSD 등)은 train에서 fit, 평가는 원 스케일로 역변환.
    t_dataset, params = _apply_target_transform(dataset, target)

    per_model: dict[str, list[float]] = {mt: [] for mt in model_types}
    for rep in range(n_repeats):
        seed = base_seed + rep
        splitter = DataSplitter(
            train_ratio=1.0 - holdout_ratio,
            val_ratio=0.0,
            test_ratio=holdout_ratio,
            random_seed=seed,
        )
        split = splitter.split(t_dataset)  # 무작위 분할 (groups 미전달)
        if split.train.n_samples < 2 or split.test is None or split.test.n_samples < 1:
            continue
        # holdout 원 스케일 라벨 (역변환).
        y_test_orig = _inverse(split.test.y, params)
        for mt in model_types:
            model = _make_tree_model(mt, seed)
            model.fit(split.train.X, split.train.y)
            pred_orig = _inverse(model.predict(split.test.X), params)
            rmse = float(np.sqrt(np.mean((pred_orig - y_test_orig) ** 2)))
            per_model[mt].append(rmse)

    summary: dict[str, Any] = {}
    for mt, vals in per_model.items():
        if vals:
            # 표본 표준편차(ddof=1) — n_repeats가 작을 때 모집단 std(ddof=0)는
            # 변동성을 과소평가한다. n=1이면 std=0.
            std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
            summary[mt] = {
                "rmse_mean": float(np.mean(vals)),
                "rmse_std": std,
                "per_repeat": [float(v) for v in vals],
            }
    winner = min(summary, key=lambda m: summary[m]["rmse_mean"]) if summary else None
    return {
        "target": target,
        "n_samples": dataset.n_samples,
        "n_repeats": n_repeats,
        "transform": params["type"] if params else "identity",
        "models": summary,
        "winner": winner,
    }


def _make_tree_model(model_type: str, seed: int) -> Any:
    """XGBoost / RandomForest 회귀기 생성 — 하이퍼파라미터는 정책 SSOT에서."""
    from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY

    hp = DEFAULT_STRUCTURAL_ML_POLICY.tree_hyperparams
    if model_type == "random_forest":
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(
            n_estimators=hp.n_estimators, random_state=seed, n_jobs=hp.n_jobs
        )
    from xgboost import XGBRegressor

    return XGBRegressor(
        n_estimators=hp.n_estimators,
        max_depth=hp.max_depth,
        learning_rate=hp.learning_rate,
        random_state=seed,
        n_jobs=hp.n_jobs,
    )


def _inverse(y: Any, params: dict | None) -> Any:
    """변환 파라미터로 역변환 (identity면 그대로)."""
    if not params:
        return y
    from ml.target_transform import TargetTransformer

    return TargetTransformer().inverse_transform("_eval", y, params)


@dataclass
class ChallengerOutcome:
    """Result of a structural challenger training run."""

    version_id: str | None
    targets_trained: list[str]
    training_samples: int
    holdout_samples: int
    promoted: bool
    comparison: dict[str, Any] | None = None
    per_target_holdout_rmse: dict[str, float] = field(default_factory=dict)
    # 물성별 XGB-vs-RF 경쟁 승자(model_type.value) — 화면/메타 노출용(A2/B2).
    model_types: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _apply_target_transform(dataset: Any, target: str) -> tuple[Any, dict | None]:
    """Apply the project's per-target transform (log for MSD/viscosity).

    Mirrors retrainer: fit_transform the training y so the ensemble learns in
    transformed space; the returned params are stored on the predictor so
    predict-time inverse-transform restores original scale. Identity targets
    (density, RDF, …) pass through unchanged.

    Returns:
        (dataset_for_training, transform_params or None).
    """
    from ml.data_loader import TrainingDataset
    from ml.target_transform import TargetTransformer

    transformer = TargetTransformer()
    if transformer.get_transform_type(target) == "identity":
        return dataset, None
    y_t, params = transformer.fit_transform(target, dataset.y)
    transformed = TrainingDataset(
        X=dataset.X,
        y=y_t,
        exp_ids=dataset.exp_ids,
        feature_names=dataset.feature_names,
        target_name=dataset.target_name,
        metadata=dict(dataset.metadata),
    )
    return transformed, params


def _holdout_rmse(predictor: Any, X: np.ndarray, y: np.ndarray, target: str) -> float | None:
    """RMSE of a predictor's ensemble mean on a holdout set, original scale."""
    try:
        from ml.multi_target import MultiTargetResult  # noqa: F401

        inputs = {"v7": X, "default": X}
        result = predictor.predict_multi(inputs)
        preds = result.predictions.get(target)
        if preds is None:
            return None
        yhat = np.asarray(preds, dtype=float).reshape(-1)
        if yhat.shape[0] != y.shape[0]:
            # predict_multi may return a single dict of scalars for 1 row;
            # fall back to per-row prediction.
            yhat = np.array(
                [
                    float(
                        predictor.predict_multi(
                            {"v7": X[i : i + 1], "default": X[i : i + 1]}
                        ).predictions.get(target, np.nan)
                    )
                    for i in range(X.shape[0])
                ]
            )
        return float(np.sqrt(np.mean((yhat - y) ** 2)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("holdout rmse failed for %s: %s", target, exc)
        return None


def _select_winning_model_types(
    train_datasets: dict[str, Any],
    holdout: dict[str, tuple[np.ndarray, np.ndarray]],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """물성별로 XGBoost vs RandomForest를 holdout에서 비교해 승자 ModelType 반환.

    사용자 결정(XGB vs RF 경쟁)을 **실제 등록 모델에 반영** — 이전엔 평가만 하고
    항상 XGBoost를 등록했다. holdout이 없는 표적은 XGBoost 기본.
    """
    from ml.models import ModelType

    winners: dict[str, Any] = {}
    candidates = (("xgboost", ModelType.XGBOOST), ("random_forest", ModelType.RANDOM_FOREST))
    for name, ds in train_datasets.items():
        if name not in holdout:
            winners[name] = ModelType.XGBOOST
            continue
        X_hold, y_hold = holdout[name]  # 원 스케일
        t_ds, params = _apply_target_transform(ds, name)
        best_mt, best_rmse = ModelType.XGBOOST, float("inf")
        for mt_str, mt_enum in candidates:
            try:
                model = _make_tree_model(mt_str, seed)
                model.fit(t_ds.X, t_ds.y)
                pred = _inverse(model.predict(X_hold), params)
                rmse = float(np.sqrt(np.mean((np.asarray(pred) - y_hold) ** 2)))
            except Exception:  # noqa: BLE001
                continue
            if rmse < best_rmse:
                best_rmse, best_mt = rmse, mt_enum
        winners[name] = best_mt
    return winners


def _build_and_train_v7(
    train_datasets: dict[str, Any],
    *,
    training_sources: list[str] | None = None,
    model_types: dict[str, Any] | None = None,
) -> Any:
    """Build a V7 MultiTargetPredictor, apply transforms, fit, set manifest.

    Shared by both training entry points so the predictor assembly (per-target
    feature-set routing, log transform, capability manifest) is identical.
    ``model_types`` (target→ModelType)가 주어지면 표적별 model_type을 설정한다
    (XGB-vs-RF 경쟁 승자 — A1). 미지정 시 기본 XGBoost.
    """
    from ml.data_loader import TargetVariable
    from ml.models import ModelConfig, ModelType
    from ml.multi_target import MultiTargetConfig, MultiTargetPredictor

    target_configs: dict[str, Any] = {}
    if model_types:
        for name in train_datasets:
            target_configs[name] = ModelConfig(
                model_type=model_types.get(name, ModelType.XGBOOST), target_name=name
            )
    config = MultiTargetConfig(
        targets=[TargetVariable(n) for n in train_datasets],
        target_feature_sets=dict.fromkeys(train_datasets, FeatureSetVersion.V7.value),
        target_configs=target_configs,
    )
    predictor = MultiTargetPredictor(config)
    transformed: dict[str, Any] = {}
    transform_params: dict[str, dict] = {}
    for name, ds in train_datasets.items():
        t_ds, params = _apply_target_transform(ds, name)
        transformed[name] = t_ds
        if params:
            transform_params[name] = params
    predictor.train(transformed)
    if transform_params:
        predictor._target_transforms = transform_params  # noqa: SLF001
    manifest: dict[str, Any] = {
        "supported_targets": list(train_datasets.keys()),
        "feature_set": FeatureSetVersion.V7.value,
        "feature_kind": "structural_bulk_rdkit",
    }
    if model_types:
        manifest["model_types"] = {
            n: (mt.value if hasattr(mt, "value") else str(mt))
            for n, mt in model_types.items()
        }
    if training_sources is not None:
        manifest["training_sources"] = training_sources
    predictor._capability_manifest = manifest  # noqa: SLF001
    return predictor


def _champion_predictions_by_exp(
    session: Any, champion: Any, exp_ids: list[str], target: str = "density"
) -> dict[str, float]:
    """Champion을 **자기 feature_set**으로 holdout exp_ids 예측 → {exp_id: pred}.

    교차 피처셋 비교의 핵심(A3): V7 challenger(32 피처)와 V3 champion(40 피처)을
    같은 holdout 실험에서 공정 비교하려면, champion은 V7 피처가 아니라 자기
    피처셋(V3)으로 재구성·예측해야 한다.
    """
    try:
        from contracts.policies.ml_policy import FeatureSetVersion
        from ml.data_loader import TargetVariable
        from ml.dataset_router import load_training_dataset

        fs_str = champion.config.get_feature_set_for_target(target)
        ds = load_training_dataset(
            session,
            TargetVariable(target),
            requested_feature_set=FeatureSetVersion(fs_str),
            min_samples=1,
        )
        if ds is None:
            return {}
        wanted = set(exp_ids)
        idx = [i for i, e in enumerate(ds.exp_ids) if e in wanted]
        if not idx:
            return {}
        X = ds.X[np.array(idx, dtype=int)]
        eids = [ds.exp_ids[i] for i in idx]
        results = champion.predict_batch(X, targets=[target])
        out: dict[str, float] = {}
        for eid, r in zip(eids, results, strict=False):
            v = r.predictions.get(target)
            if v is not None:
                out[eid] = float(v)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("champion reconstruction failed: %s", exc)
        return {}


def _register_and_maybe_promote(
    session: Any,
    predictor: Any,
    *,
    holdout: dict[str, tuple[np.ndarray, np.ndarray]],
    target_keys: list[str],
    training_samples: int,
    random_seed: int,
    triggered_by: str,
    holdout_exp_ids: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, dict | None, list[str]]:
    """Register a V7 challenger and promote it if it beats the champion.

    **Single SSOT for register→compare→promote** — both training entry points
    call this so the champion/challenger decision (Decision A) runs identically.
    Previously ``train_from_store`` omitted this block and could *never* promote
    (latent bug). Champion comparison/promote is exception-isolated (R3): a
    registry/DB failure leaves the challenger registered and returns
    ``promoted=False`` with a note instead of raising.

    Returns:
        (version_id, promoted, comparison_payload, notes).
    """
    from ml.model_registry import ModelRegistry

    notes: list[str] = []
    registry = ModelRegistry(session)
    reg_row = registry.register_model(
        predictor,
        feature_set_version=FeatureSetVersion.V7.value,
        actual_feature_set=FeatureSetVersion.V7.value,
        per_target_feature_sets=dict.fromkeys(target_keys, FeatureSetVersion.V7.value),
        capability_manifest=predictor._capability_manifest,  # noqa: SLF001
        training_samples=training_samples,
        training_seed=random_seed,
        triggered_by=triggered_by,
    )
    version_id = getattr(reg_row, "version_id", None)

    promoted = False
    comparison_payload: dict[str, Any] | None = None
    try:
        champion = registry.get_champion_predictor()
        # 커버리지 가드: V7이 champion이 지원하던 물성을 떨어뜨리면 승급 금지
        # (무저하 원칙). 예: V3 champion은 CED 지원, V7은 미지원 → 승급 시 CED
        # 예측 상실. 이 경우 challenger로만 등록(per-target champion=B3 전까지).
        dropped: set[str] = set()
        if champion is not None:
            champ_targets = set(getattr(champion, "fitted_targets", []) or [])
            dropped = champ_targets - set(target_keys)
        if champion is None:
            notes.append("no incumbent champion — V7 becomes champion via cold-start path")
        elif dropped:
            notes.append(
                f"승급 보류: V7이 champion 물성 {sorted(dropped)}을 미지원 — "
                "challenger로만 등록(커버리지 보호). per-target champion 필요"
            )
        elif "density" in holdout:
            X_hold, y_hold = holdout["density"]
            cp = _predict_density(predictor, X_hold)  # challenger(V7)
            exp_ids = (holdout_exp_ids or {}).get("density")
            if cp is not None and exp_ids and len(exp_ids) == len(y_hold):
                # 교차 피처셋: champion은 자기 feature_set으로 같은 실험 예측 후
                # exp_id로 정렬해 공정 비교 (A3).
                champ_by_exp = _champion_predictions_by_exp(session, champion, exp_ids)
                y_a, cp_a, ch_a = [], [], []
                for i, eid in enumerate(exp_ids):
                    if eid in champ_by_exp:
                        y_a.append(float(y_hold[i]))
                        cp_a.append(float(cp[i]))
                        ch_a.append(champ_by_exp[eid])
                if len(y_a) >= 2:
                    # 시그니처: compare_with_champion(challenger_pred, champion_pred, y).
                    # cp_a=challenger(V7), ch_a=champion(V3).
                    comparison = registry.compare_with_champion(
                        np.array(cp_a), np.array(ch_a), np.array(y_a)
                    )
                    comparison_payload = {
                        "promoted": bool(comparison.promoted),
                        "champion_rmse": float(comparison.champion_rmse),
                        "challenger_rmse": float(comparison.challenger_rmse),
                        "n_compared": len(y_a),
                    }
                    if comparison.promoted and version_id:
                        registry.promote(version_id)
                        promoted = True
                else:
                    notes.append("champion comparison: no overlapping holdout experiments")
            else:
                notes.append("champion comparison skipped: holdout exp_ids unavailable")
    except Exception as exc:  # noqa: BLE001 - 비교/승급 실패는 등록 보존 + 보고
        notes.append(f"champion comparison skipped: {exc}")
    return version_id, promoted, comparison_payload, notes


def train_structural_challenger(
    session: Any,
    *,
    targets: list[str] | None = None,
    ff_type: str = "bulk_ff_gaff2",
    run_tiers: list[str] | None = None,
    min_samples: int | None = None,
    holdout_ratio: float = 0.2,
    random_seed: int = 42,
    register: bool = True,
) -> ChallengerOutcome:
    """Train a V7 structural challenger and (optionally) register it.

    Args:
        session: SQLAlchemy session.
        targets: Bulk targets to train (default: density).
        ff_type: Force-field filter (our GAFF2 corpus).
        run_tiers: Experiment tiers to include.
        min_samples: Minimum V7 samples required per target.
        holdout_ratio: Fraction held out for champion comparison.
        random_seed: Deterministic split/seed.
        register: When True, register the challenger in the model registry.

    Returns:
        ChallengerOutcome with training stats and promotion decision.
    """
    from contracts.policies.ml_policy import DEFAULT_ML_POLICY
    from ml.data_loader import DataLoader, DataSplitter, TargetVariable

    # 최소 표본 수는 정책 SSOT에서 (하드코딩 금지). 호출자 override 우선.
    if min_samples is None:
        min_samples = DEFAULT_ML_POLICY.min_structural_samples_for_v7

    target_names = list(targets or DEFAULT_V7_TARGETS)
    loader = DataLoader()
    splitter = DataSplitter(
        train_ratio=1.0 - holdout_ratio,
        val_ratio=0.0,
        test_ratio=holdout_ratio,
        random_seed=random_seed,
    )

    train_datasets: dict[str, Any] = {}
    holdout: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    holdout_exp_ids: dict[str, list[str]] = {}
    notes: list[str] = []

    for name in target_names:
        try:
            target_var = TargetVariable(name)
        except ValueError:
            notes.append(f"unknown target '{name}' — skipped")
            continue
        dataset = loader.load_from_database(
            session,
            target=target_var,
            ff_type=ff_type,
            run_tiers=run_tiers,
            min_samples=min_samples,
            feature_set_version=FeatureSetVersion.V7,
        )
        if dataset is None:
            notes.append(f"no V7 dataset for '{name}' (RDKit/samples) — skipped")
            continue
        split = splitter.split(dataset)
        train_datasets[name] = split.train
        if split.test is not None and split.test.n_samples > 0:
            holdout[name] = (split.test.X, split.test.y)
            holdout_exp_ids[name] = list(split.test.exp_ids)

    if not train_datasets:
        return ChallengerOutcome(
            version_id=None,
            targets_trained=[],
            training_samples=0,
            holdout_samples=0,
            promoted=False,
            notes=notes or ["no trainable V7 targets"],
        )

    # A1: 물성별 XGB-vs-RF 경쟁 → 승자를 그 물성의 등록 모델로.
    model_types = _select_winning_model_types(train_datasets, holdout, seed=random_seed)
    model_types_str = {n: mt.value for n, mt in model_types.items()}
    predictor = _build_and_train_v7(train_datasets, model_types=model_types)

    per_target_rmse: dict[str, float] = {}
    for name, (X, y) in holdout.items():
        rmse = _holdout_rmse(predictor, X, y, name)
        if rmse is not None:
            per_target_rmse[name] = rmse

    training_samples = sum(ds.n_samples for ds in train_datasets.values())
    holdout_samples = sum(len(y) for (_, y) in holdout.values())

    if not register:
        return ChallengerOutcome(
            version_id=None,
            targets_trained=list(train_datasets.keys()),
            training_samples=training_samples,
            holdout_samples=holdout_samples,
            promoted=False,
            per_target_holdout_rmse=per_target_rmse,
            model_types=model_types_str,
            notes=notes + ["register=False (dry-run)"],
        )

    version_id, promoted, comparison_payload, reg_notes = _register_and_maybe_promote(
        session,
        predictor,
        holdout=holdout,
        holdout_exp_ids=holdout_exp_ids,
        target_keys=list(train_datasets.keys()),
        training_samples=training_samples,
        random_seed=random_seed,
        triggered_by="structural_challenger_v7",
    )

    return ChallengerOutcome(
        version_id=version_id,
        targets_trained=list(train_datasets.keys()),
        training_samples=training_samples,
        holdout_samples=holdout_samples,
        promoted=promoted,
        comparison=comparison_payload,
        per_target_holdout_rmse=per_target_rmse,
        model_types=model_types_str,
        notes=notes + reg_notes,
    )


def train_from_store(
    session: Any,
    *,
    target: str = "density",
    sources: list[str] | None = None,
    force_fields: list[str] | None = None,
    holdout_ratio: float = 0.2,
    random_seed: int = 42,
    register: bool = True,
    store: Any | None = None,
    allow_external: bool | None = None,
) -> ChallengerOutcome:
    """Train a V7 challenger from the structural feature store.

    **내부 데이터 전용이 기본(운영 결정).** ``allow_external`` 미지정 시
    `DEFAULT_STRUCTURAL_ML_POLICY.internal_data_only`(=True)를 따르며, 그때는
    ``sources``/``force_fields``를 명시하지 않아도 our_production/gaff2_am1bcc로
    강제 필터한다. 외부(MDML COMPASS III) 사전학습 혼합은 ``allow_external=True``
    또는 정책 ``internal_data_only=False``로 **명시 전환**해야만 허용된다.

    Args:
        session: SQLAlchemy session (for registry/comparison).
        target: Property to train.
        sources: Store sources. None + internal-only → our_production만.
        force_fields: FF 태그. None + internal-only → gaff2_am1bcc만.
        holdout_ratio: Fraction held out for champion comparison.
        random_seed: Deterministic seed.
        register: Register the challenger when True.
        allow_external: 외부 데이터 혼합 허용. None이면 정책 기본값.

    Returns:
        ChallengerOutcome.
    """
    from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY
    from ml.data_loader import DataSplitter, TargetVariable, TrainingDataset
    from ml.structural_feature_store import StructuralFeatureStore

    pol = DEFAULT_STRUCTURAL_ML_POLICY
    use_external = (not pol.internal_data_only) if allow_external is None else allow_external
    # 내부 전용이면 명시 override가 없는 한 our_production/gaff2_am1bcc로 강제 필터.
    if not use_external:
        if sources is None:
            sources = list(pol.internal_sources)
        if force_fields is None:
            force_fields = list(pol.force_fields)

    if store is None:
        store = StructuralFeatureStore()
    store_ds = store.load_dataset(target, sources=sources, force_fields=force_fields)
    if store_ds is None or store_ds.n_samples < 4:
        return ChallengerOutcome(
            version_id=None,
            targets_trained=[],
            training_samples=0,
            holdout_samples=0,
            promoted=False,
            notes=[f"store has no/insufficient '{target}' rows"],
        )

    dataset = TrainingDataset(
        X=store_ds.X,
        y=store_ds.y,
        exp_ids=[f"store_{i}" for i in range(store_ds.n_samples)],
        feature_names=store_ds.feature_names,
        target_name=target,
        metadata={"sources": sorted(set(store_ds.sources))},
    )
    splitter = DataSplitter(
        train_ratio=1.0 - holdout_ratio,
        val_ratio=0.0,
        test_ratio=holdout_ratio,
        random_seed=random_seed,
    )
    split = splitter.split(dataset, groups=store_ds.groups)

    try:
        TargetVariable(target)  # 표적명 검증 (config는 헬퍼가 구성)
    except ValueError:
        return ChallengerOutcome(
            version_id=None,
            targets_trained=[],
            training_samples=0,
            holdout_samples=0,
            promoted=False,
            notes=[f"unknown target '{target}'"],
        )

    sources_used = sorted(set(store_ds.sources))
    holdout: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    if split.test is not None and split.test.n_samples > 0:
        holdout[target] = (split.test.X, split.test.y)
    # A1: XGB-vs-RF 경쟁 승자로 학습.
    model_types = _select_winning_model_types(
        {target: split.train}, holdout, seed=random_seed
    )
    model_types_str = {n: mt.value for n, mt in model_types.items()}
    predictor = _build_and_train_v7(
        {target: split.train}, training_sources=sources_used, model_types=model_types
    )

    holdout_rmse: dict[str, float] = {}
    if target in holdout:
        rmse = _holdout_rmse(predictor, holdout[target][0], holdout[target][1], target)
        if rmse is not None:
            holdout_rmse[target] = rmse

    notes = [f"store sources: {sources_used}"]
    training_samples = split.train.n_samples
    holdout_samples = split.test.n_samples if split.test else 0
    if not register:
        return ChallengerOutcome(
            version_id=None,
            targets_trained=[target],
            training_samples=training_samples,
            holdout_samples=holdout_samples,
            promoted=False,
            per_target_holdout_rmse=holdout_rmse,
            model_types=model_types_str,
            notes=notes + ["register=False (dry-run)"],
        )

    # 공통 헬퍼로 register→compare→promote (이전엔 store 경로에 비교/승급 누락 버그).
    version_id, promoted, comparison_payload, reg_notes = _register_and_maybe_promote(
        session,
        predictor,
        holdout=holdout,
        target_keys=[target],
        training_samples=training_samples,
        random_seed=random_seed,
        triggered_by="structural_challenger_v7_store",
    )
    return ChallengerOutcome(
        version_id=version_id,
        targets_trained=[target],
        training_samples=training_samples,
        holdout_samples=holdout_samples,
        promoted=promoted,
        comparison=comparison_payload,
        per_target_holdout_rmse=holdout_rmse,
        model_types=model_types_str,
        notes=notes + reg_notes,
    )


def benchmark_transfer_strategies(
    store: Any,
    *,
    target: str = "density",
    holdout_ratio: float = 0.2,
    random_seed: int = 42,
    n_estimators: int = 300,
) -> dict[str, Any]:
    """Compare cross-FF training strategies on a fixed GAFF2 holdout (Track C).

    Strategies (identical features, identical GAFF2 holdout, identical seed):
      (a) gaff2_only — train on our GAFF2 rows only
      (b) mixed      — train on COMPASS pretrain + GAFF2 together
      (c) finetune   — pretrain on COMPASS, then continue boosting on GAFF2
                       (XGBoost warm-start via ``xgb_model``)

    Returns:
        {"holdout_n", "strategies": {name: rmse}, "winner"} — the data decides
        the default strategy (Decision A philosophy: measure, don't assume).
    """
    import numpy as np
    from xgboost import XGBRegressor

    from ml.structural_feature_store import FF_COMPASS, FF_GAFF2

    gaff = store.load_dataset(target, force_fields=[FF_GAFF2])
    compass = store.load_dataset(target, force_fields=[FF_COMPASS])
    if gaff is None or gaff.n_samples < 10:
        return {"error": f"insufficient GAFF2 '{target}' rows"}

    # Fixed group-aware GAFF2 holdout shared by all strategies.
    rng = np.random.default_rng(random_seed)
    groups = sorted(set(gaff.groups))
    rng.shuffle(groups)
    n_hold_groups = max(1, int(len(groups) * holdout_ratio))
    hold_groups = set(groups[:n_hold_groups])
    hold_mask = np.array([g in hold_groups for g in gaff.groups])
    if hold_mask.all() or not hold_mask.any():
        idx = rng.permutation(gaff.n_samples)
        hold_mask = np.zeros(gaff.n_samples, dtype=bool)
        hold_mask[idx[: max(1, int(gaff.n_samples * holdout_ratio))]] = True
    X_tr_g, y_tr_g = gaff.X[~hold_mask], gaff.y[~hold_mask]
    X_hold, y_hold = gaff.X[hold_mask], gaff.y[hold_mask]

    def _rmse(model: Any) -> float:
        pred = model.predict(X_hold)
        return float(np.sqrt(np.mean((pred - y_hold) ** 2)))

    from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY

    hp = DEFAULT_STRUCTURAL_ML_POLICY.tree_hyperparams
    params = {
        "n_estimators": n_estimators,  # 호출자 override(벤치마크 비용 조절)
        "max_depth": hp.max_depth,
        "learning_rate": hp.learning_rate,
        "random_state": random_seed,
        "n_jobs": hp.n_jobs,
    }
    results: dict[str, float] = {}

    model_a = XGBRegressor(**params)
    model_a.fit(X_tr_g, y_tr_g)
    results["gaff2_only"] = _rmse(model_a)

    if compass is not None and compass.n_samples > 0:
        X_mix = np.vstack([compass.X, X_tr_g])
        y_mix = np.concatenate([compass.y, y_tr_g])
        model_b = XGBRegressor(**params)
        model_b.fit(X_mix, y_mix)
        results["mixed"] = _rmse(model_b)

        base = XGBRegressor(**params)
        base.fit(compass.X, compass.y)
        model_c = XGBRegressor(**params)
        model_c.fit(X_tr_g, y_tr_g, xgb_model=base.get_booster())
        results["finetune"] = _rmse(model_c)

    winner = min(results, key=results.get)
    return {
        "target": target,
        "holdout_n": int(hold_mask.sum()),
        "train_gaff2_n": int((~hold_mask).sum()),
        "pretrain_compass_n": int(compass.n_samples) if compass else 0,
        "strategies": results,
        "winner": winner,
    }


def _last_v7_training_count(session: Any) -> int:
    """현재 V7 champion이 학습된 표본 수 (없으면 0). 증분 게이트 기준점."""
    try:
        from database.repositories.model_version_repo import ModelVersionRepository

        champion = ModelVersionRepository(session).get_champion()
        if champion is None:
            return 0
        if str(getattr(champion, "feature_set_version", "")) != "v7":
            return 0
        return int(getattr(champion, "training_samples", 0) or 0)
    except Exception:  # noqa: BLE001 - champion 부재/조회 실패는 0(증분 미적용)
        return 0


def maybe_retrain_structural(session: Any, *, policy: Any | None = None) -> dict[str, Any]:
    """Opt-in V7 retrain trigger for the completion hook (P6).

    Default-OFF: when the policy is disabled this is a no-op and returns
    ``{"triggered": False, "reason": "disabled"}`` — byte-identical behaviour.
    When enabled, it retrains a V7 challenger per eligible target once enough
    *new* GAFF2 labels have accumulated, then lets champion/challenger decide
    promotion (Decision A — a worse model never degrades serving).

    Args:
        session: SQLAlchemy session.
        policy: StructuralMLPolicy (default: DEFAULT_STRUCTURAL_ML_POLICY).

    Returns:
        Diagnostic dict (triggered, per-target outcomes).
    """
    from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY

    pol = policy or DEFAULT_STRUCTURAL_ML_POLICY
    if not pol.enabled:
        return {"triggered": False, "reason": "disabled"}

    from ml.data_loader import TargetVariable  # noqa: F401
    from ml.structural_feature_store import StructuralFeatureStore

    store = StructuralFeatureStore()
    results: dict[str, Any] = {}
    triggered = False
    for target in pol.targets:
        # per-target 예외 격리: 한 표적의 ingest/load/train 실패가 나머지 표적을
        # 중단하지 않도록 본문 전체를 감싼다(R3). 외곽 완료 훅이 전체를 삼키면
        # "한 표적 실패→전부 무음 스킵"이 되던 문제 해소.
        try:
            store.ingest_experiments(session, targets=[target])
            ds = store.load_dataset(target, force_fields=list(pol.force_fields))
            n = ds.n_samples if ds else 0
            if n < pol.min_labels_to_start:
                results[target] = {"labels": n, "action": "below_min_start"}
                continue
            # 증분 게이트: 마지막 V7 학습 이후 새 라벨이 임계 미만이면 건너뜀
            # (retrain_label_increment 활성화 — champion training_samples 기준점).
            last_n = _last_v7_training_count(session)
            if last_n > 0 and (n - last_n) < pol.retrain_label_increment:
                results[target] = {
                    "labels": n,
                    "since_last": n - last_n,
                    "action": "below_increment",
                }
                continue
            outcome = train_from_store(
                session,
                target=target,
                force_fields=list(pol.force_fields),
                holdout_ratio=pol.holdout_ratio,
                random_seed=pol.random_seed,
                register=True,
                store=store,
            )
            triggered = True
            results[target] = {
                "labels": n,
                "version_id": outcome.version_id,
                "holdout_rmse": outcome.per_target_holdout_rmse.get(target),
                "promoted": outcome.promoted,
            }
        except Exception as exc:  # noqa: BLE001 - 표적 격리
            results[target] = {"error": f"retrain failed: {exc}"}
    return {"triggered": triggered, "targets": results}


def _predict_density(predictor: Any, X: np.ndarray) -> np.ndarray | None:
    """Per-row density predictions (original scale) for champion comparison."""
    try:
        preds = []
        for i in range(X.shape[0]):
            row = X[i : i + 1]
            result = predictor.predict_multi({"v7": row, "default": row, "v3": row})
            value = result.predictions.get("density")
            preds.append(float(value) if value is not None else np.nan)
        arr = np.array(preds, dtype=float)
        return arr if np.isfinite(arr).all() else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("density prediction failed: %s", exc)
        return None
