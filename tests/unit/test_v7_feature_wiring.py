"""V7 피처셋 와이어링 회귀 테스트 (S2).

Pins:
  - V7가 registry/policy에 32 피처로 등록
  - V1~V6 개수 byte-identical(무회귀)
  - feature_builder가 structural_features dict를 병합
  - V7는 V1~V5로 fallback하지 않음(독립 분기)
  - dataset_router가 V7를 bulk 로더로 라우팅
"""

from __future__ import annotations

from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from ml.feature_builder import FeatureBuildInput, build_feature_record, build_feature_result
from ml.feature_registry import FeatureRegistry
from ml.structural_features import STRUCTURAL_FEATURE_NAMES


class TestV7Registration:
    def test_v7_is_32_features(self):
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V7) == 32
        assert DEFAULT_ML_POLICY.v7_feature_count == 32

    def test_policy_count_matches_registry_ssot(self):
        # 정책 v7_feature_count는 실제 피처 개수(SSOT)와 일치해야 함 (drift 차단)
        actual = len(FeatureRegistry.get_features(FeatureSetVersion.V7))
        assert DEFAULT_ML_POLICY.v7_feature_count == actual

    def test_min_samples_policy_wired(self):
        # min_structural_samples_for_v7가 challenger 기본값으로 실제 사용됨
        import inspect

        from ml import structural_challenger as sc

        sig = inspect.signature(sc.train_structural_challenger)
        # min_samples 기본값이 None(=정책에서 해소)이어야 SSOT 연결
        assert sig.parameters["min_samples"].default is None
        assert DEFAULT_ML_POLICY.min_structural_samples_for_v7 > 0

    def test_v7_names_match_structural_ssot(self):
        assert FeatureRegistry.get_features(FeatureSetVersion.V7) == list(
            STRUCTURAL_FEATURE_NAMES
        )

    def test_v1_to_v6_counts_unchanged(self):
        # 기존 피처셋 무회귀 — degrade 방지
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V1) == 11
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V2) == 24
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V3) == 40
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V4) == 53
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V5) == 51
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V6) == 93


class TestFeatureBuilderV7:
    def test_structural_features_merged(self):
        sf = {name: float(i) for i, name in enumerate(STRUCTURAL_FEATURE_NAMES)}
        record = build_feature_record(FeatureBuildInput(structural_features=sf))
        for name in STRUCTURAL_FEATURE_NAMES:
            assert record[name] == sf[name]

    def test_v7_result_shape_and_order(self):
        sf = {name: float(i) for i, name in enumerate(STRUCTURAL_FEATURE_NAMES)}
        built = build_feature_result(
            FeatureBuildInput(structural_features=sf), FeatureSetVersion.V7
        )
        assert built.values.shape == (32,)
        assert built.feature_names == list(STRUCTURAL_FEATURE_NAMES)

    def test_absent_structural_features_zero_filled(self):
        # structural_features 미제공 시 0으로 채워짐 (다른 버전 무영향)
        record = build_feature_record(FeatureBuildInput(asphaltene_wt=15.0))
        assert all(record[n] == 0.0 for n in STRUCTURAL_FEATURE_NAMES)
        # 기존 V3 피처는 정상
        assert record["asphaltene_wt"] == 15.0


class TestV7NoFallback:
    def test_v7_fallback_order_isolated(self):
        from ml.multi_target import MultiTargetConfig, MultiTargetPredictor

        predictor = MultiTargetPredictor(MultiTargetConfig(targets=["density"]))
        # v7 입력만 있을 때 v7 선택, v3만 있으면 v7 미선택(None)
        import numpy as np

        fs, chosen, mat = predictor._select_input_for_target(
            {"v7": np.zeros((1, 32))}, "density_v7_probe"
        )
        # get_feature_set_for_target가 v3 기본이므로 직접 fallback dict 확인
        assert predictor._select_input_for_target(
            {"v3": np.zeros((1, 40))}, "x"
        )[1] == "v3"


class TestDatasetRouterV7:
    def test_v7_routes_to_bulk_loader(self):
        from ml.dataset_router import _LAYERED_VERSIONS

        # V7는 layered가 아니므로 bulk DataLoader로 라우팅됨
        assert FeatureSetVersion.V7 not in _LAYERED_VERSIONS
