"""Parity plot split 분리 로직 테스트 (ML 결과 화면 — 학습/검증 색 구분).

Pins:
  - _split_metrics: 단일 split RMSE/R²/MAE 산출
  - StructuralMLStatusResponse 스키마
  - get_structural_ml_status: 정책 OFF 기본값 반영
"""

from __future__ import annotations

import numpy as np

from api.schemas.ml_visualization import ParityPoint, StructuralMLStatusResponse
from features.mlops.visualization_service import _split_metrics


class TestSplitMetrics:
    def test_perfect_fit(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        m = _split_metrics(y, y)
        assert m["rmse"] == 0.0
        assert m["r2"] == 1.0
        assert m["n_points"] == 4.0

    def test_known_error(self):
        y = np.array([1.0, 2.0, 3.0])
        yhat = np.array([1.1, 2.1, 2.9])
        m = _split_metrics(y, yhat)
        assert m["rmse"] > 0
        assert m["mae"] > 0
        assert 0.0 <= m["r2"] <= 1.0


class TestParityPointSplit:
    def test_split_field_optional(self):
        # split 없이도 생성 (레거시 호환)
        p = ParityPoint(exp_id="a", actual=1.0, predicted=0.99, residual=0.01)
        assert p.split is None

    def test_split_labels(self):
        for s in ("train", "validation", "test"):
            p = ParityPoint(exp_id="a", actual=1.0, predicted=1.0, residual=0.0, split=s)
            assert p.split == s


class TestStructuralStatus:
    def test_schema_defaults(self):
        r = StructuralMLStatusResponse(
            enabled=False,
            targets=["density"],
            force_fields=["gaff2_am1bcc"],
            min_labels_to_start=30,
            retrain_label_increment=25,
        )
        assert r.enabled is False
        assert r.champion_supported_targets == []

    def test_get_status_reflects_policy_off(self):
        from features.mlops.visualization_service import get_structural_ml_status

        status = get_structural_ml_status()
        # 기본 정책 OFF (opt-in)
        assert status.enabled is False
        assert "density" in status.targets
        assert "gaff2_am1bcc" in status.force_fields

    def test_status_exposes_champion_model_types(self, monkeypatch):
        # B2: V7 champion manifest의 model_types를 status로 노출
        import api.deps as deps

        monkeypatch.setattr(
            deps,
            "get_runtime_capability_manifest",
            lambda: {
                "feature_set": "v7",
                "supported_targets": ["density", "msd_diffusion_coefficient"],
                "model_types": {
                    "density": "xgboost",
                    "msd_diffusion_coefficient": "random_forest",
                },
            },
        )
        from features.mlops.visualization_service import get_structural_ml_status

        status = get_structural_ml_status()
        assert status.champion_feature_set == "v7"
        assert status.champion_model_types == {
            "density": "xgboost",
            "msd_diffusion_coefficient": "random_forest",
        }
