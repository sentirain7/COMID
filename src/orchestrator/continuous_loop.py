"""Continuous learning loop driven by periodic Celery task."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np

from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from database.models import ExperimentModel, SystemSettingModel
from ml.data_loader import DataLoader, TargetVariable
from ml.drift_detector import DriftDetector
from ml.model_registry import ModelRegistry
from ml.retrainer import ModelRetrainer

_LAST_CHECK_KEY = "continuous_loop_last_check"


class ContinuousLearningLoop:
    """Periodic check for drift and retraining triggers.

    PR 2 (Codex Round 4): ``e_intra_method`` flows from the loop into every
    automatic ``ModelRetrainer`` so continuous retraining stays consistent
    with the active CED label SSOT.  ``None`` defaults to Method 1 baseline.
    """

    def __init__(self, db_session: Any, *, e_intra_method: str | None = None):
        self._session = db_session
        self._policy = DEFAULT_ML_POLICY.continuous_learning
        self._drift = DriftDetector()
        self._loader = DataLoader()
        self._last_check: datetime | None = self._load_last_check()
        self._e_intra_method = e_intra_method

    def _load_last_check(self) -> datetime | None:
        """Load the last check timestamp from DB."""
        row = self._session.query(SystemSettingModel).filter_by(key=_LAST_CHECK_KEY).first()
        if row and row.value:
            try:
                return datetime.fromisoformat(row.value)
            except (ValueError, TypeError):
                return None
        return None

    def _save_last_check(self, ts: datetime) -> None:
        """Persist the last check timestamp to DB."""
        row = self._session.query(SystemSettingModel).filter_by(key=_LAST_CHECK_KEY).first()
        if row:
            row.value = ts.isoformat()
        else:
            self._session.add(SystemSettingModel(key=_LAST_CHECK_KEY, value=ts.isoformat()))
        self._session.flush()

    def _count_new_completed_samples(self) -> int:
        query = self._session.query(ExperimentModel).filter(ExperimentModel.status == "completed")
        if self._last_check is not None:
            query = query.filter(ExperimentModel.completed_at >= self._last_check)
        return int(query.count())

    def _load_density_dataset(self):
        # Density target is independent of CED label method, but we forward
        # ``e_intra_method`` for symmetry — DataLoader ignores it for non-CED
        # targets.
        return self._loader.load_from_database(
            self._session,
            target=TargetVariable.DENSITY,
            feature_set_version=DEFAULT_ML_POLICY.default_feature_set,
            min_samples=2,
            e_intra_method=self._e_intra_method,
        )

    def _load_target_dataset(self, target: TargetVariable):
        # PR 2 (Codex Round 6): drift datasets must follow the same CED
        # label contract as the deployed champion.  Without this the drift
        # detector compares Method 1a champion predictions against Method 1
        # CED labels and silently mis-classifies drift.
        return self._loader.load_from_database(
            self._session,
            target=target,
            feature_set_version=DEFAULT_ML_POLICY.default_feature_set,
            min_samples=2,
            e_intra_method=self._e_intra_method,
        )

    def _check_multi_target_drift(self, champion: Any) -> tuple[dict[str, Any] | None, list[str]]:
        """Check drift across all available targets.

        Returns:
            Tuple of (primary drift dict for density, list of drifted target names).
        """
        drifted_targets: list[str] = []
        primary_drift: dict[str, Any] | None = None

        for target in TargetVariable:
            ds = self._load_target_dataset(target)
            if ds is None or ds.n_samples < 4:
                continue

            tname = target.value
            if tname not in champion.fitted_targets:
                continue

            window = min(
                max(self._policy.min_new_samples_for_check, 20),
                ds.n_samples // 2,
            )
            x_train = ds.X[:-window]
            x_new = ds.X[-window:]
            y_true = ds.y[-window:]

            pred = champion.predict_batch(x_new, targets=[tname])
            y_pred = np.array([p.predictions.get(tname, 0.0) for p in pred], dtype=float)

            detector = DriftDetector()
            report = detector.full_check(x_train=x_train, x_new=x_new, y_true=y_true, y_pred=y_pred)

            if report.should_retrain:
                drifted_targets.append(tname)

            if tname == "density":
                primary_drift = {
                    "drift_type": report.drift_type.value,
                    "feature_drift_fraction": report.feature_drift_fraction,
                    "rmse_drift_pct": report.rmse_drift_pct,
                    "page_hinkley_detected": report.page_hinkley_detected,
                    "should_retrain": report.should_retrain,
                }

        if primary_drift is not None:
            primary_drift["drifted_targets"] = drifted_targets

        return primary_drift, drifted_targets

    def drift_check_only(self) -> dict[str, Any]:
        """Run drift diagnostics without triggering retraining (safe for GET)."""
        now = datetime.now(UTC)
        new_samples = self._count_new_completed_samples()

        result: dict[str, Any] = {
            "checked_at": now.isoformat(),
            "new_samples": new_samples,
            "drift": None,
        }

        if new_samples < self._policy.min_new_samples_for_check:
            return result

        registry = ModelRegistry(self._session)
        champion = registry.get_champion_predictor()
        if champion is None:
            return result

        drift_dict, _ = self._check_multi_target_drift(champion)
        if drift_dict is not None:
            result["drift"] = drift_dict
        return result

    def run_check(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        new_samples = self._count_new_completed_samples()

        result: dict[str, Any] = {
            "checked_at": now.isoformat(),
            "new_samples": new_samples,
            "drift": None,
            "retrained": False,
            "version_id": None,
            "trigger_reason": "skip",
        }

        if new_samples < self._policy.min_new_samples_for_check:
            self._last_check = now
            self._save_last_check(now)
            result["trigger_reason"] = "insufficient_new_samples"
            return result

        registry = ModelRegistry(self._session)
        champion = registry.get_champion_predictor()
        if champion is None:
            retrainer = ModelRetrainer(self._session, registry, e_intra_method=self._e_intra_method)
            train_result = retrainer.run(
                force=True,
                triggered_by="continuous_loop_no_champion",
                new_samples=new_samples,
            )
            self._last_check = now
            self._save_last_check(now)
            result.update(
                {
                    "retrained": train_result.success,
                    "version_id": train_result.version_id,
                    "trigger_reason": train_result.trigger_reason,
                }
            )
            return result

        drift_dict, drifted_targets = self._check_multi_target_drift(champion)
        if drift_dict is None:
            self._last_check = now
            self._save_last_check(now)
            result["trigger_reason"] = "insufficient_target_samples"
            return result

        result["drift"] = drift_dict

        # Build a DriftReport for the retrainer; use any-target-drifted as trigger.
        from ml.drift_detector import DriftReport, DriftType

        any_drifted = len(drifted_targets) > 0
        drift_report = DriftReport(
            drift_type=DriftType.REAL if any_drifted else DriftType.NONE,
            feature_drift_fraction=drift_dict.get("feature_drift_fraction", 0.0),
            rmse_baseline=0.0,
            rmse_current=0.0,
            rmse_drift_pct=drift_dict.get("rmse_drift_pct", 0.0),
            page_hinkley_detected=drift_dict.get("page_hinkley_detected", False),
            should_retrain=any_drifted,
            drifted_targets=drifted_targets,
        )

        retrainer = ModelRetrainer(self._session, registry, e_intra_method=self._e_intra_method)
        train_result = retrainer.run(
            force=False,
            triggered_by="continuous_loop",
            drift_report=drift_report,
            new_samples=new_samples,
        )

        auto_followup: dict[str, Any] | None = None
        if train_result.promoted:
            try:
                from features.recommendations.active_learning import run_post_retrain_auto_batch

                auto_followup = run_post_retrain_auto_batch(source="continuous_loop_auto")
            except Exception:
                auto_followup = {"ok": False, "generated": 0, "persisted": 0, "queued": 0}

        self._last_check = now
        self._save_last_check(now)
        result.update(
            {
                "retrained": train_result.success and train_result.version_id is not None,
                "version_id": train_result.version_id,
                "trigger_reason": train_result.trigger_reason,
                "auto_recommendations": auto_followup,
            }
        )
        return result
