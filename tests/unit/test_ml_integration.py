"""Tests for ML→Recommendation integration (api/deps.get_ml_predictor_fn)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


class TestGetMLPredictorFn:
    """Tests for api.deps.get_ml_predictor_fn adapter."""

    @staticmethod
    @contextmanager
    def _mock_session_scope():
        yield MagicMock()

    def test_no_champion_returns_none(self) -> None:
        """When no champion is registered, return None without filesystem fallback."""
        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=None),
            patch("ml.multi_target.MultiTargetPredictor.load") as load_mock,
        ):
            from api.deps import get_ml_predictor_fn

            result = get_ml_predictor_fn()
            assert result is None
            load_mock.assert_not_called()

    def test_registry_failure_returns_none_without_filesystem_fallback(self) -> None:
        """Registry load failure should not trigger legacy filesystem fallback."""
        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch(
                "ml.model_registry.ModelRegistry.get_champion_predictor",
                side_effect=RuntimeError("registry down"),
            ),
            patch("ml.multi_target.MultiTargetPredictor.load") as load_mock,
        ):
            from api.deps import get_ml_predictor_fn

            result = get_ml_predictor_fn()
            assert result is None
            load_mock.assert_not_called()

    def test_successful_load_returns_callable(self) -> None:
        """When champion loads successfully, return a callable."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density", "viscosity"]

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(
            predictions={"density": 1.0, "viscosity": 500.0},
            uncertainties={"density": 0.01, "viscosity": 10.0},
        )
        mock_mtp.predict_multi.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None
            assert callable(fn)

    def test_adapter_returns_dict_not_none(self) -> None:
        """Adapter must return dict[str, float], never None."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(predictions={"density": 1.05})
        mock_mtp.predict_multi.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None

            result = fn(
                {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                }
            )
            assert isinstance(result, dict)
            assert "density" in result
            assert result["density"] == pytest.approx(1.05)

    def test_adapter_raises_on_empty_predictions(self) -> None:
        """Adapter must raise if MultiTargetPredictor returns empty predictions."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(predictions={})  # Empty!
        mock_mtp.predict_multi.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None

            with pytest.raises(RuntimeError, match="empty predictions"):
                fn(
                    {
                        "asphaltene": 20.0,
                        "resin": 30.0,
                        "aromatic": 35.0,
                        "saturate": 15.0,
                    }
                )

    def test_adapter_raises_on_predict_error(self) -> None:
        """Adapter must let prediction errors propagate (not silently return None)."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]
        mock_mtp.predict_multi.side_effect = ValueError("Feature mismatch")

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None

            with pytest.raises(ValueError, match="Feature mismatch"):
                fn(
                    {
                        "asphaltene": 20.0,
                        "resin": 30.0,
                        "aromatic": 35.0,
                        "saturate": 15.0,
                    }
                )

    def test_adapter_handles_additive_type(self) -> None:
        """Adapter should pass additive_type metadata without validator type errors."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(predictions={"density": 1.01})
        mock_mtp.predict_multi.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None
            result = fn(
                {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 10.0,
                    "additive": 5.0,
                    "additive_type": "SBS",
                }
            )
            assert result["density"] == pytest.approx(1.01)

    def test_adapter_handles_additive_mol_id(self) -> None:
        """Adapter should pass additive_mol_id metadata without validator type errors."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(predictions={"density": 1.02})
        mock_mtp.predict_multi.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None
            result = fn(
                {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 10.0,
                    "additive": 5.0,
                    "additive_type": "SiO2",
                    "additive_mol_id": "ADD_003",
                }
            )
            assert result["density"] == pytest.approx(1.02)

    def test_adapter_falls_back_to_predict_when_predict_multi_not_stubbed(self) -> None:
        """Compatibility path should still use predict() if predict_multi is unavailable."""
        mock_mtp = MagicMock()
        mock_mtp.fitted_targets = ["density"]
        del mock_mtp.predict_multi

        from ml.multi_target import MultiTargetResult

        mock_result = MultiTargetResult(predictions={"density": 1.03})
        mock_mtp.predict.return_value = mock_result

        with (
            patch("database.connection.session_scope", self._mock_session_scope),
            patch("ml.model_registry.ModelRegistry.get_champion_predictor", return_value=mock_mtp),
        ):
            from api.deps import get_ml_predictor_fn

            fn = get_ml_predictor_fn()
            assert fn is not None
            result = fn(
                {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                }
            )
            assert result["density"] == pytest.approx(1.03)
