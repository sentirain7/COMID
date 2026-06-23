"""역설계 BO _predict_combo의 V7 분기 테스트 (P4/S5 + R2 효율).

Pins:
  - champion feature_set='v7' → 구조 피처(species_counts) 경로로 라우팅
  - composition champion(None) → 기존 SARA-wt% 경로 (byte-identical)
  - _load_predictor가 (feature_set, predictor_fn) 튜플 반환
  - R2: V7 컨텍스트({mtp, extractor})를 BO 1회당 한 번 로드 — _predict_combo_v7이
    조합마다 재로딩하지 않음
"""

from __future__ import annotations

from features.inverse_design_pipeline import service

_COMBO = {"binder_type": "AAA1", "additive_type": None, "additive_wt": 0.0}


class TestPredictComboRouting:
    def test_composition_path_when_not_v7(self, monkeypatch):
        captured = {}

        def fake_predictor(pred_input: dict):
            captured["input"] = pred_input
            return {"density": 1.0}

        out = service._predict_combo(
            fake_predictor, _COMBO, temperature_k=293.0, feature_set=None
        )
        assert out == {"density": 1.0}
        assert "asphaltene" in captured["input"]
        assert "temperature_k" in captured["input"]

    def test_v7_path_routed(self, monkeypatch):
        called = {}

        def fake_v7(v7_ctx, combo, *, temperature_k, structure_size, diagnostics=None):
            called["ctx"] = v7_ctx
            called["combo"] = combo
            called["structure_size"] = structure_size
            return {"density": 0.95}

        monkeypatch.setattr(service, "_predict_combo_v7", fake_v7)
        # predictor_fn은 _load_predictor가 만든 컨텍스트(여기선 가짜 dict)
        ctx = {"mtp": object(), "extractor": object()}
        out = service._predict_combo(
            ctx, _COMBO, temperature_k=293.0, feature_set="v7", structure_size="X2"
        )
        assert out == {"density": 0.95}
        assert called["ctx"] is ctx
        assert called["combo"] is _COMBO
        assert called["structure_size"] == "X2"

    def test_v7_returns_none_when_ctx_missing(self):
        # 컨텍스트 None(예: RDKit 부재/champion 부재) → graceful None
        assert (
            service._predict_combo_v7(
                None, _COMBO, temperature_k=293.0, structure_size="X1"
            )
            is None
        )


class TestLoadPredictorContext:
    def test_no_manifest_returns_composition(self, monkeypatch):
        monkeypatch.setattr(service, "_get_capability_manifest", lambda: None)
        monkeypatch.setattr(
            "api.deps.get_ml_predictor_with_uncertainty_fn", lambda: None
        )
        monkeypatch.setattr("api.deps.get_ml_predictor_fn", lambda: None)
        feature_set, predictor_fn = service._load_predictor()
        assert feature_set is None
        assert predictor_fn is None

    def test_v7_predict_combo_integration(self, monkeypatch):
        """V7 경로 통합: 컨텍스트의 mtp/extractor 재사용 → 32 피처 예측."""

        class FakeMTP:
            def predict_multi(self, inputs):
                assert "v7" in inputs
                assert inputs["v7"].shape == (1, 32)

                class _R:
                    predictions = {"density": 0.97}

                return _R()

        class FakeExtractor:
            def extract_from_counts(self, mol_counts, temperature_k):
                # 32개 구조 피처 dict 반환
                from ml.structural_features import STRUCTURAL_FEATURE_NAMES

                return dict.fromkeys(STRUCTURAL_FEATURE_NAMES, 0.5)

        monkeypatch.setattr(
            service,
            "_combo_species_counts",
            lambda combo, *, temperature_k, structure_size: {"U-SA-Squalane-0293": 4},
        )
        ctx = {"mtp": FakeMTP(), "extractor": FakeExtractor()}
        out = service._predict_combo_v7(
            ctx, _COMBO, temperature_k=293.0, structure_size="X1"
        )
        assert out == {"density": 0.97}

    def test_v7_context_loaded_once(self, monkeypatch):
        """R2: _load_predictor가 V7 컨텍스트(mtp/extractor)를 1회 구성."""
        load_count = {"n": 0}

        def fake_load_mtp():
            load_count["n"] += 1
            return object()

        monkeypatch.setattr(service, "_get_capability_manifest", lambda: {"feature_set": "v7"})
        monkeypatch.setattr("api.deps._load_mtp", fake_load_mtp)
        monkeypatch.setattr("api.deps.get_molecule_db", lambda: object())
        monkeypatch.setattr("ml.structural_features.RDKIT_AVAILABLE", True, raising=False)
        feature_set, ctx = service._load_predictor()
        assert feature_set == "v7"
        assert isinstance(ctx, dict) and "mtp" in ctx and "extractor" in ctx
        assert load_count["n"] == 1  # champion 1회만 로드


class TestV7OodGuard:
    """B1: V7 피처공간 OOD(soft flag)를 버리지 않고 후보 주석으로 끌어올림."""

    def _ctx(self, *, ood_flag):
        from ml.structural_features import STRUCTURAL_FEATURE_NAMES

        class _OOD:
            is_ood = ood_flag

        class FakeMTP:
            def predict_multi(self, inputs):
                class _R:
                    predictions = {"density": 0.96}
                    ood_results = {"density": _OOD()}

                return _R()

        class FakeExtractor:
            def extract_from_counts(self, mol_counts, temperature_k):
                return dict.fromkeys(STRUCTURAL_FEATURE_NAMES, 0.5)

        return {"mtp": FakeMTP(), "extractor": FakeExtractor()}

    def test_diagnostics_captures_v7_ood_true(self, monkeypatch):
        monkeypatch.setattr(
            service,
            "_combo_species_counts",
            lambda combo, *, temperature_k, structure_size: {"U-SA-Squalane-0293": 4},
        )
        diag: dict = {}
        out = service._predict_combo_v7(
            self._ctx(ood_flag=True),
            _COMBO,
            temperature_k=293.0,
            structure_size="X1",
            diagnostics=diag,
        )
        assert out == {"density": 0.96}  # 예측 반환 계약 불변
        assert diag["is_ood"] is True  # V7 detector 산출을 버리지 않음

    def test_diagnostics_captures_v7_ood_false(self, monkeypatch):
        monkeypatch.setattr(
            service,
            "_combo_species_counts",
            lambda combo, *, temperature_k, structure_size: {"U-SA-Squalane-0293": 4},
        )
        diag: dict = {}
        service._predict_combo_v7(
            self._ctx(ood_flag=False),
            _COMBO,
            temperature_k=293.0,
            structure_size="X1",
            diagnostics=diag,
        )
        assert diag["is_ood"] is False

    def test_is_ood_none_when_no_ood_results(self):
        # ood_results 미산출(detector 부재) → None(미상), soft flag 비활성
        class _R:
            predictions = {"density": 1.0}
            ood_results = None

        assert service._v7_is_ood(_R()) is None
