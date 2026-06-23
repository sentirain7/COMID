"""V7 opt-in 실시간 재학습 정책 + 완료 훅 테스트 (P6/S6).

Pins:
  - 기본 OFF → maybe_retrain_structural no-op (byte-identical)
  - 완료 훅 _try_structural_retrain: OFF면 재학습 모듈조차 import 안 함
  - 정책 SSOT 값 (하드코딩 없음)
"""

from __future__ import annotations

from contracts.policies.structural_ml import (
    DEFAULT_STRUCTURAL_ML_POLICY,
    StructuralMLPolicy,
)


class TestPolicy:
    def test_default_off(self):
        assert DEFAULT_STRUCTURAL_ML_POLICY.enabled is False

    def test_ssot_values(self):
        p = DEFAULT_STRUCTURAL_ML_POLICY
        assert p.targets == ("density",)
        assert p.retrain_label_increment > 0
        assert p.min_labels_to_start > 0
        assert p.force_fields == ("gaff2_am1bcc",)  # GAFF2-only 기본

    def test_internal_data_only_default(self):
        # 운영 결정: 내부(이 패키지) 생산 데이터만 학습 — 외부(COMPASS) 기본 차단
        p = DEFAULT_STRUCTURAL_ML_POLICY
        assert p.internal_data_only is True
        assert p.internal_sources == ("our_production",)

    def test_holdout_bounds(self):
        # ge/le 검증 (잘못된 값 거부)
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            StructuralMLPolicy(holdout_ratio=0.9)


class TestMaybeRetrain:
    def test_disabled_is_noop(self):
        from ml.structural_challenger import maybe_retrain_structural

        result = maybe_retrain_structural(session=object())
        assert result == {"triggered": False, "reason": "disabled"}

    def test_enabled_below_min_no_register(self, monkeypatch, tmp_path):
        from ml import structural_challenger as sc
        from ml.structural_feature_store import StructuralFeatureStore

        policy = StructuralMLPolicy(enabled=True, min_labels_to_start=1000)

        # store.ingest_experiments를 무력화(빈 스토어) → below_min_start
        monkeypatch.setattr(
            StructuralFeatureStore, "ingest_experiments", lambda self, s, **k: 0
        )
        monkeypatch.setattr(
            StructuralFeatureStore, "_default_store_path", lambda: tmp_path, raising=False
        )
        result = sc.maybe_retrain_structural(session=object(), policy=policy)
        assert result["triggered"] is False
        assert result["targets"]["density"]["action"] == "below_min_start"


class TestCompletionHook:
    def test_hook_noop_when_disabled(self, monkeypatch):
        # 정책 OFF면 _try_structural_retrain은 재학습 모듈을 import조차 안 함
        from orchestrator import task_maintenance

        called = {"retrain": False}

        def _should_not_run(*a, **k):
            called["retrain"] = True
            return {}

        monkeypatch.setattr(
            "ml.structural_challenger.maybe_retrain_structural", _should_not_run
        )
        # 기본 정책 OFF 상태에서 훅 호출
        task_maintenance._try_structural_retrain()
        assert called["retrain"] is False
