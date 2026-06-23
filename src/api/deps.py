"""
API dependencies for dependency injection.

Provides singleton instances of shared resources like MoleculeDB.
"""

from functools import lru_cache

from common.logging import get_logger

logger = get_logger("api.deps")


@lru_cache(maxsize=1)
def get_molecule_db():
    """Get singleton MoleculeDB instance with aging library loaded.

    Returns:
        MoleculeDB instance with molecules loaded from config

    Raises:
        RuntimeError: If molecule library not found or loading fails
    """
    from builder.molecule_db_loader import create_molecule_db

    return create_molecule_db(allow_mock=False)


@lru_cache(maxsize=1)
def get_aging_config() -> dict | None:
    """
    Get aging library configuration.

    Returns:
        Config dict or None if not available
    """
    from common.library_config import load_combined_molecule_config

    try:
        return load_combined_molecule_config()
    except Exception:
        return None


def _load_mtp():
    """Load the best available MultiTargetPredictor.

    Returns:
        MultiTargetPredictor or None.
    """
    # Champion model from DB-backed registry is the only supported runtime source.
    # Silent filesystem fallback hides lineage drift and must not be used.
    try:
        from database.connection import session_scope
        from ml.model_registry import ModelRegistry

        with session_scope() as session:
            registry = ModelRegistry(session)
            mtp = registry.get_champion_predictor()
            if mtp is None:
                logger.info("No champion MultiTargetPredictor registered")
                return None
            logger.info(f"Loaded champion MultiTargetPredictor: targets={mtp.fitted_targets}")
            return mtp
    except Exception as e:
        logger.error("Champion model load failed", exc_info=e)
        raise RuntimeError("Champion model load failed") from e


def get_runtime_capability_manifest() -> dict | None:
    """Return champion capability manifest when available."""
    try:
        mtp = _load_mtp()
    except Exception:
        return None
    if mtp is None:
        return None
    return dict(getattr(mtp, "_capability_manifest", None) or {})


def get_runtime_ood_detector(feature_set_version: str | None = None):
    """Return champion OOD detector for a requested feature contract."""
    try:
        mtp = _load_mtp()
    except Exception:
        return None
    if mtp is None:
        return None
    if feature_set_version and getattr(mtp, "_ood_detectors", None):
        detector = mtp._ood_detectors.get(feature_set_version)  # noqa: SLF001
        if detector is not None:
            return detector
    return getattr(mtp, "_ood_detector", None)


def _build_feature_vector(composition: dict[str, float]):
    """Build canonical V2 feature payload from composition dict.

    Returns:
        (FeatureBuildResult, normalized_comp, metadata) tuple.
    """
    from contracts.policies.ml_policy import FeatureSetVersion
    from ml.feature_builder import FeatureBuildInput, build_feature_result
    from recommendation.composition_validator import CompositionValidator

    metadata_keys = {"additive_type", "additive_mol_id"}
    metadata = {k: composition[k] for k in metadata_keys if k in composition}
    numeric_comp = {k: v for k, v in composition.items() if k not in metadata_keys}

    validator = CompositionValidator(auto_fix=True)
    result = validator.validate(numeric_comp)
    comp = result.corrected_composition or numeric_comp

    built = build_feature_result(
        FeatureBuildInput.from_prediction_composition(
            comp,
            additive_type=metadata.get("additive_type"),
            additive_mol_id=metadata.get("additive_mol_id"),
        ),
        FeatureSetVersion.V2,
    )

    return built, comp, metadata


def _get_required_feature_sets(mtp, *, include_layered: bool = False) -> set[str]:
    """Return feature-set versions required by the loaded predictor."""
    config = getattr(mtp, "config", None)
    if config is None or not hasattr(config, "get_feature_set_for_target"):
        return {"v2"}
    requested = {
        feature_set
        for target_name in getattr(mtp, "fitted_targets", [])
        for feature_set in [config.get_feature_set_for_target(target_name)]
        if isinstance(feature_set, str)
    }
    if not include_layered:
        requested.discard("v4")
        requested.discard("v6")
    if not requested:
        return {"v2"}
    return requested


def _predict_with_contract_dispatch(mtp, inputs_by_feature_set: dict[str, object]):
    """Dispatch prediction using the best available predictor interface.

    New predictors should use ``predict_multi``. Compatibility wrappers exist so
    tests and older callers that only stub ``predict``/``predict_dual`` still
    exercise the same adapter logic.
    """
    mt_result = None
    predict_multi = getattr(mtp, "predict_multi", None)
    if callable(predict_multi):
        mt_result = predict_multi(inputs_by_feature_set)
        if isinstance(getattr(mt_result, "predictions", None), dict):
            return mt_result

    if "v4" in inputs_by_feature_set:
        predict_dual = getattr(mtp, "predict_dual", None)
        if callable(predict_dual):
            mt_result = predict_dual(
                X_v3=inputs_by_feature_set.get("v3", inputs_by_feature_set["default"]),
                X_v4=inputs_by_feature_set["v4"],
            )
            if isinstance(getattr(mt_result, "predictions", None), dict):
                return mt_result

    predict_single = getattr(mtp, "predict", None)
    if callable(predict_single):
        mt_result = predict_single(
            inputs_by_feature_set.get("v3", inputs_by_feature_set["default"])
        )
        if isinstance(getattr(mt_result, "predictions", None), dict):
            return mt_result

    return mt_result


def get_ml_predictor_fn(
    mol_counts: dict[str, int] | None = None,
    molecule_db=None,
):
    """Get target-aware ML predictor adapter function.

    Args:
        mol_counts: {mol_id: count} for V3 molecule features. None → V2 only.
        molecule_db: MoleculeDB instance for mol_counts resolution.

    Returns:
        Callable[[dict[str, float]], dict[str, float]] if model is loaded,
        None if model directory does not exist (triggers heuristic fallback).
    """
    try:
        mtp = _load_mtp()
        if mtp is None:
            logger.info("ML model directory not found, predictor_fn=None (heuristic fallback)")
            return None
    except Exception as e:
        logger.warning(f"Failed to load MultiTargetPredictor: {e}")
        return None

    has_mol_data = mol_counts is not None and len(mol_counts) > 0

    def _predict(composition: dict[str, float]) -> dict[str, float]:
        """Adapter: composition dict -> predicted properties dict."""
        built_v2, _comp, _meta = _build_feature_vector(composition)
        inputs_by_feature_set = {
            "default": built_v2.values.reshape(1, -1),
            "v2": built_v2.values.reshape(1, -1),
        }
        required_feature_sets = _get_required_feature_sets(mtp)
        if {"v3", "v5"} & required_feature_sets:
            from contracts.policies.ml_policy import FeatureSetVersion
            from ml.feature_builder import FeatureBuildInput, build_feature_results
            from ml.molecule_features import MoleculeFeatureExtractor

            mol_extractor = MoleculeFeatureExtractor()
            mol_feats = (
                mol_extractor.extract_from_composition(mol_counts, molecule_db)
                if has_mol_data
                else {}
            )
            versions = [FeatureSetVersion.V3]
            if "v5" in required_feature_sets:
                versions.append(FeatureSetVersion.V5)
            built_versions = build_feature_results(
                FeatureBuildInput.from_prediction_composition(
                    _comp,
                    additive_type=_meta.get("additive_type"),
                    additive_mol_id=_meta.get("additive_mol_id"),
                    molecule_features=mol_feats,
                ),
                versions,
            )
            for version_key, built in built_versions.items():
                inputs_by_feature_set[version_key] = built.values.reshape(1, -1)

        # V7 (bulk structural / RDKit) — requires per-species mol_counts.
        if "v7" in required_feature_sets and has_mol_data:
            from contracts.policies.ml_policy import FeatureSetVersion
            from ml.feature_builder import FeatureBuildInput, build_feature_result
            from ml.structural_features import (
                RDKIT_AVAILABLE,
                StructuralFeatureExtractor,
            )

            if RDKIT_AVAILABLE:
                struct_feats = StructuralFeatureExtractor(
                    molecule_db
                ).extract_from_counts(
                    mol_counts, float(composition.get("temperature_k", 298.0))
                )
                if struct_feats is not None:
                    built_v7 = build_feature_result(
                        FeatureBuildInput.from_prediction_composition(
                            _comp, structural_features=struct_feats
                        ),
                        FeatureSetVersion.V7,
                    )
                    inputs_by_feature_set["v7"] = built_v7.values.reshape(1, -1)

        mt_result = _predict_with_contract_dispatch(mtp, inputs_by_feature_set)

        if not mt_result.predictions:
            raise RuntimeError("MultiTargetPredictor returned empty predictions")
        return mt_result.predictions

    return _predict


def get_ml_predictor_with_uncertainty_fn(
    mol_counts: dict[str, int] | None = None,
    molecule_db=None,
):
    """Get target-aware ML predictor with uncertainty estimates.

    Args:
        mol_counts: {mol_id: count} for V3 molecule features. None → V2 only.
        molecule_db: MoleculeDB instance for mol_counts resolution.

    Returns:
        Callable that takes composition dict and returns:
        {"predictions": dict[str, float], "uncertainties": dict[str, float]}
    """
    try:
        mtp = _load_mtp()
        if mtp is None:
            logger.info("ML model directory not found, returning None")
            return None
    except Exception as e:
        logger.warning(f"Failed to load MultiTargetPredictor: {e}")
        return None

    has_mol_data = mol_counts is not None and len(mol_counts) > 0

    def _predict_with_uncertainty(
        composition: dict[str, float],
    ) -> dict[str, dict[str, float]]:
        """Adapter: composition dict -> predictions + uncertainties."""
        built_v2, _comp, _meta = _build_feature_vector(composition)
        inputs_by_feature_set = {
            "default": built_v2.values.reshape(1, -1),
            "v2": built_v2.values.reshape(1, -1),
        }
        required_feature_sets = _get_required_feature_sets(mtp)
        if {"v3", "v5"} & required_feature_sets:
            from contracts.policies.ml_policy import FeatureSetVersion
            from ml.feature_builder import FeatureBuildInput, build_feature_results
            from ml.molecule_features import MoleculeFeatureExtractor

            mol_extractor = MoleculeFeatureExtractor()
            mol_feats = (
                mol_extractor.extract_from_composition(mol_counts, molecule_db)
                if has_mol_data
                else {}
            )
            versions = [FeatureSetVersion.V3]
            if "v5" in required_feature_sets:
                versions.append(FeatureSetVersion.V5)
            built_versions = build_feature_results(
                FeatureBuildInput.from_prediction_composition(
                    _comp,
                    additive_type=_meta.get("additive_type"),
                    additive_mol_id=_meta.get("additive_mol_id"),
                    molecule_features=mol_feats,
                ),
                versions,
            )
            for version_key, built in built_versions.items():
                inputs_by_feature_set[version_key] = built.values.reshape(1, -1)

        mt_result = _predict_with_contract_dispatch(mtp, inputs_by_feature_set)

        if not mt_result.predictions:
            raise RuntimeError("MultiTargetPredictor returned empty predictions")

        return {
            "predictions": mt_result.predictions,
            "uncertainties": mt_result.uncertainties or {},
        }

    return _predict_with_uncertainty


def get_layered_predictor_fn(
    crystal_features: dict[str, float],
    amorphous_features: dict[str, float] | None = None,
    stack_features: dict[str, float] | None = None,
    mol_counts: dict[str, int] | None = None,
    molecule_db=None,
):
    """Get composite predictor for layered structure inverse design.

    Returns a predictor that:
    - Uses V3 features for bulk targets (density, CED, etc.)
    - Uses V4 features (V3 + crystal + amorphous) for layered targets (adhesion, tensile)
    - Crystal/amorphous features are fixed; binder composition is the variable.

    mol_counts가 없으면 V3 분자 feature는 0으로 처리하되,
    MTP.predict_dual()이 target별로 V3/V4를 디스패치하므로
    V4 target(adhesion 등)은 crystal/amorphous feature만으로도 의미있음.

    Args:
        crystal_features: Dict of 10 crystal feature values.
        amorphous_features: Dict of 3 amorphous feature values (or None).
        mol_counts: {mol_id: count} for V3 molecule features. None → zeros.
        molecule_db: MoleculeDB instance for mol_counts resolution.

    Returns:
        Callable[[dict], dict] predictor function, or None if model not loaded.
    """
    try:
        mtp = _load_mtp()
        if mtp is None:
            return None
    except Exception:
        return None

    from contracts.policies.ml_policy import FeatureSetVersion
    from ml.amorphous_features import AmorphousFeatureExtractor
    from ml.feature_builder import FeatureBuildInput, build_feature_results
    from ml.molecule_features import MoleculeFeatureExtractor

    amorphous_feats = amorphous_features or AmorphousFeatureExtractor.zeros()

    def _layered_predict(composition: dict[str, float]) -> dict[str, float]:
        """Predict with dual feature set dispatch."""
        _built_v2, comp, meta = _build_feature_vector(composition)

        mol_extractor = MoleculeFeatureExtractor()
        if mol_counts:
            mol_feats = mol_extractor.extract_from_composition(mol_counts, molecule_db)
        else:
            mol_feats = {}
        versions = [FeatureSetVersion.V3, FeatureSetVersion.V4]
        if "v6" in _get_required_feature_sets(mtp, include_layered=True):
            versions.append(FeatureSetVersion.V6)
        built = build_feature_results(
            FeatureBuildInput.from_prediction_composition(
                comp,
                additive_type=meta.get("additive_type"),
                additive_mol_id=meta.get("additive_mol_id"),
                molecule_features=mol_feats,
                crystal_features=crystal_features,
                amorphous_features=amorphous_feats,
                stack_features=stack_features,
            ),
            versions,
        )

        inputs_by_feature_set = {
            "default": built[FeatureSetVersion.V3.value].values.reshape(1, -1),
            "v3": built[FeatureSetVersion.V3.value].values.reshape(1, -1),
            "v4": built[FeatureSetVersion.V4.value].values.reshape(1, -1),
        }
        if FeatureSetVersion.V6.value in built:
            inputs_by_feature_set["v6"] = built[FeatureSetVersion.V6.value].values.reshape(1, -1)
        if "v5" in _get_required_feature_sets(mtp, include_layered=True):
            built_v5 = build_feature_results(
                FeatureBuildInput.from_prediction_composition(
                    comp,
                    additive_type=meta.get("additive_type"),
                    additive_mol_id=meta.get("additive_mol_id"),
                    molecule_features=mol_feats,
                ),
                [FeatureSetVersion.V5],
            )
            inputs_by_feature_set["v5"] = built_v5[FeatureSetVersion.V5.value].values.reshape(1, -1)

        mt_result = _predict_with_contract_dispatch(mtp, inputs_by_feature_set)
        if not mt_result.predictions:
            raise RuntimeError("MultiTargetPredictor returned empty predictions")
        return mt_result.predictions

    return _layered_predict


def get_model_registry(session):
    """Create a ModelRegistry bound to a DB session."""
    from ml.model_registry import ModelRegistry

    return ModelRegistry(session)


def _resolve_champion_e_intra_method(session, *, strict: bool = False) -> str | None:
    """Resolve the active CED label method from the current champion's lineage.

    PR 2 (Codex Round 5+7): the champion's
    ``training_config_json["e_intra_method"]`` is the operational SSOT for
    automated retraining — every challenger should be trained on the same
    label contract as the deployed champion unless the caller explicitly
    overrides.

    Args:
        strict: When True, propagate registry/query failures instead of
            silently returning ``None``.  Critical paths (CED retrain /
            drift) should pass ``strict=True`` so a broken registry does
            not silently revert to Method 1 baseline.  Cold start (no
            champion yet) still returns ``None`` even in strict mode —
            that is a benign state, not a registry failure.
    """
    from common.logging import get_logger

    logger = get_logger("api.deps")

    try:
        from database.models import MLModelVersionModel

        row = (
            session.query(MLModelVersionModel)
            .filter(MLModelVersionModel.status == "champion")
            .order_by(MLModelVersionModel.id.desc())
            .first()
        )
        if row is None:
            return None  # Cold start — benign.
        from contracts.schema_enums import normalize_e_intra_method

        cfg = getattr(row, "training_config_json", None) or {}
        return normalize_e_intra_method(cfg.get("e_intra_method"))
    except Exception as exc:
        logger.error(
            "champion e_intra_method resolution failed: %s (strict=%s) — falling back to %s",
            exc,
            strict,
            "RuntimeError" if strict else "None (baseline default)",
        )
        if strict:
            raise RuntimeError(
                f"Failed to resolve champion e_intra_method: {exc}. "
                "Refusing to silently fall back to baseline on a critical "
                "path (CED retrain/drift)."
            ) from exc
        return None


def get_model_retrainer(session, *, e_intra_method: str | None = None):
    """Create a ModelRetrainer bound to a DB session.

    PR 2 (Codex Round 4+5): ``e_intra_method`` propagates the active CED
    label SSOT to the retrainer.  When the caller does not provide a value,
    the helper auto-inherits from the current champion's
    ``training_config_json["e_intra_method"]`` so automated retraining stays
    on the same label contract as the deployed champion.  Falls back to
    Method 1 baseline only when no champion exists.
    """
    from ml.retrainer import ModelRetrainer

    resolved = e_intra_method
    if resolved is None:
        # Critical path: retraining contract must not silently drift to
        # baseline if the registry query fails (Codex Round 7).
        resolved = _resolve_champion_e_intra_method(session, strict=True)

    return ModelRetrainer(session, get_model_registry(session), e_intra_method=resolved)


def clear_molecule_db_cache():
    """Clear the MoleculeDB cache (useful for testing).

    Also clears the V7 structural descriptor cache, which is keyed by .mol path
    (not content): an in-place .mol regeneration would otherwise serve stale
    descriptors. (R3)
    """
    get_molecule_db.cache_clear()
    get_aging_config.cache_clear()
    try:
        from ml.structural_features import compute_molecule_descriptors

        compute_molecule_descriptors.cache_clear()
    except Exception:  # noqa: BLE001 - RDKit 부재 시 무시
        pass


@lru_cache(maxsize=1)
def get_job_manager():
    """Get singleton JobManager instance.

    Returns:
        CeleryJobManager instance

    Raises:
        RuntimeError: If Celery/Redis infrastructure is not available
    """
    from orchestrator.health_checker import HealthChecker, HealthStatus

    checker = HealthChecker(timeout_seconds=2.0)
    redis_health = checker.check_redis()

    if redis_health.status == HealthStatus.DOWN:
        logger.error(f"Redis not available: {redis_health.message}")
        raise RuntimeError(f"Job submission requires Redis. {redis_health.message}")

    try:
        from orchestrator.celery_job_manager import CeleryJobManager

        gpu_tracker = get_gpu_resource_tracker()
        manager = CeleryJobManager(gpu_tracker=gpu_tracker)
        logger.info("CeleryJobManager initialized successfully")
        return manager
    except ImportError as e:
        logger.error(f"CeleryJobManager import failed: {e}")
        raise RuntimeError(f"CeleryJobManager not available: {e}") from e


def clear_job_manager_cache():
    """Clear the JobManager cache (useful for testing)."""
    get_job_manager.cache_clear()


@lru_cache(maxsize=1)
def get_gpu_resource_tracker():
    """
    Get singleton GPU tracker (GPUService-based, drop-in replacement for GPUResourceTracker).

    GPUService provides the same interface as GPUResourceTracker but uses DB as
    the single source of truth for GPU allocations. This ensures consistency
    between API and Celery workers.

    Non-selected GPUs are registered as OFFLINE for correct API responses
    (total GPU count matches system GPUs, not just selected GPUs).

    Returns:
        GPUService instance (GPUResourceTracker-compatible interface)
    """
    from monitoring.gpu_collector import enumerate_compute_devices
    from orchestrator.gpu_service import get_gpu_service

    # 1. Get and initialize GPUService
    service = get_gpu_service()
    service.initialize()  # Idempotent, loads selected_gpus from settings.json

    # 2. Enumerate ALL system devices (raw nvidia-smi ids + uuid + eligible tag).
    # Using the SSOT registry (not detect_system_gpus) keeps registration on the
    # SAME id space as collect_once()/the UUID map, so a sub-threshold GPU (RTX
    # 3050) is shown with its real name instead of being overwritten by a
    # renumbered H200's stats, and every device routes by UUID.
    detected = enumerate_compute_devices()
    detected_ids = [g["gpu_id"] for g in detected] if detected else []

    # 3. Handle GPU detection results
    # Policy: Trust settings.json selected_gpus even if detect fails
    # (nvidia-smi may be temporarily unavailable)
    if detected_ids:
        # Validate selected_gpus against detected IDs (prevent ghost GPUs)
        service.validate_selected_gpus(detected_ids)
        # Register detected GPUs and mark non-selected as OFFLINE
        service.register_detected_gpus(detected)
        service.apply_offline_for_unselected()
    elif service.selected_gpus:
        # Detect failed but selected_gpus is configured - trust settings.json
        # Don't clear selected_gpus, just log a warning
        logger.warning(
            f"GPU detection returned empty but selected_gpus={service.selected_gpus} configured. "
            "Trusting settings.json (nvidia-smi may be temporarily unavailable)."
        )
        # Register selected GPUs as available (without detailed info from detect)
        for gpu_id in service.selected_gpus:
            if service.get_gpu(gpu_id) is None:
                # GPU not in cache, it was created during initialize()
                pass  # Already in cache from initialize()

    # 3. Update GPU info from nvidia-smi if available (for real-time stats)
    try:
        from monitoring.gpu_collector import GPUCollector

        collector = GPUCollector()
        if collector.is_available():
            for gpu_stat in collector.collect_once():
                gpu = service.get_gpu(int(gpu_stat.gpu_id))
                if gpu:
                    gpu.name = gpu_stat.name
                    gpu.memory_total_gb = gpu_stat.memory_total_bytes / (1024**3)
    except Exception:
        pass

    # 4. Fallback: re-enumerate (includes lspci fallback) for GPU names
    all_gpus = service.get_all_gpus()
    if all_gpus and all(gpu.name.startswith("GPU-") for gpu in all_gpus):
        fallback_gpus = enumerate_compute_devices()
        for gpu_info in fallback_gpus:
            gpu = service.get_gpu(gpu_info["gpu_id"])
            if gpu:
                gpu.name = gpu_info["name"]

    return service


def clear_gpu_tracker_cache():
    """Clear the GPUResourceTracker cache (useful for testing)."""
    get_gpu_resource_tracker.cache_clear()
    # Also reset the GPUService singleton to ensure clean state
    from orchestrator.gpu_service import reset_gpu_service

    reset_gpu_service()
