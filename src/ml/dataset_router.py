"""Unified ML dataset loading — routes targets to bulk or layered loader.

Prevents callers from having to choose between DataLoader (bulk)
and LayeredDataLoader (layered). Target-to-loader mapping follows
DEFAULT_ML_POLICY.target_feature_sets.

Feature set downgrade protection: layered targets (V4/V6) are never
downgraded below V4, even if caller requests V3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion

if TYPE_CHECKING:
    from ml.data_loader import TargetVariable, TrainingDataset

logger = get_logger("ml.dataset_router")

_LAYERED_VERSIONS = frozenset({FeatureSetVersion.V4, FeatureSetVersion.V6})


def load_training_dataset(
    session: object,
    target: TargetVariable,
    *,
    min_samples: int = 20,
    requested_feature_set: FeatureSetVersion | None = None,
    strict_feature_set: bool = False,
    e_intra_method: str | None = None,
) -> TrainingDataset | None:
    """Load training dataset with automatic bulk/layered routing.

    Args:
        session: DB session.
        target: Target variable for ML training.
        min_samples: Minimum samples required.
        requested_feature_set: Override feature set version.
            For layered targets, this is clamped to >= V4 (never downgraded).
        strict_feature_set: If True, no fallback to lower versions.
        e_intra_method: PR 2 (Method 1a SSOT) — when ``target`` is CED, only
            metrics whose ``metadata_json["e_intra_method"]`` matches this
            tag are kept.  ``None`` defaults to Method 1 (legacy
            ``single_molecule_vacuum``) so existing callers retain behaviour.
            Pass e.g. ``"single_molecule_vacuum_adaptive_cutoff"`` to load a
            Method 1a CED training set.

    Returns:
        TrainingDataset or None if insufficient data.
    """
    from ml.data_loader import DataLoader

    base_fsv = DEFAULT_ML_POLICY.target_feature_sets.get_version(target.value)
    is_layered = base_fsv in _LAYERED_VERSIONS

    if is_layered:
        from ml.layered_data_loader import LayeredDataLoader

        # Layered targets: never downgrade below V4
        if requested_feature_set and requested_feature_set in _LAYERED_VERSIONS:
            effective_fsv = requested_feature_set
        else:
            effective_fsv = base_fsv

        loader = LayeredDataLoader()
    else:
        effective_fsv = requested_feature_set or base_fsv
        loader = DataLoader()

    logger.debug(
        "Dataset router: target=%s, base_fsv=%s, effective_fsv=%s, loader=%s",
        target.value,
        base_fsv.value,
        effective_fsv.value,
        type(loader).__name__,
    )

    # Layered loader does not yet accept e_intra_method; bulk loader does.
    kwargs: dict = {
        "session": session,
        "target": target,
        "min_samples": min_samples,
        "feature_set_version": effective_fsv,
        "strict_feature_set": strict_feature_set,
    }
    # Only forward e_intra_method to loaders that accept it (bulk DataLoader).
    import inspect as _inspect

    sig = _inspect.signature(loader.load_from_database)
    if "e_intra_method" in sig.parameters:
        kwargs["e_intra_method"] = e_intra_method

    # Match ``DataLoader.load_from_database`` signature: first positional is db_session.
    return loader.load_from_database(
        **{("db_session" if k == "session" else k): v for k, v in kwargs.items()}
    )
