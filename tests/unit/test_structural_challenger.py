"""V7 structural challenger 학습 경로 테스트 (P3).

Pins:
  - 합성 V7 데이터셋 → MultiTargetPredictor 학습 → holdout RMSE 산출
  - register=False dry-run (DB 불필요)
  - V7 미가용(데이터셋 None) 시 graceful (targets_trained 비어있음)
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("xgboost")

from contracts.policies.ml_policy import FeatureSetVersion  # noqa: E402
from ml import structural_challenger as sc  # noqa: E402
from ml.data_loader import TrainingDataset  # noqa: E402
from ml.feature_registry import FeatureRegistry  # noqa: E402


def _synthetic_v7_dataset(n: int = 80, seed: int = 0) -> TrainingDataset:
    rng = np.random.default_rng(seed)
    feature_names = FeatureRegistry.get_features(FeatureSetVersion.V7)
    X = rng.normal(size=(n, len(feature_names)))
    # density = linear fn of node_MolWt_mean (col 0) + noise → 학습 가능
    y = 0.9 + 0.05 * (X[:, 0] - X[:, 0].mean()) / (X[:, 0].std() + 1e-9)
    y += rng.normal(scale=0.005, size=n)
    return TrainingDataset(
        X=X,
        y=y,
        exp_ids=[f"exp_{i}" for i in range(n)],
        feature_names=feature_names,
        target_name="density",
        metadata={},
    )


class TestCoverageGuardAndCrossFS:
    def test_coverage_guard_blocks_promotion_when_dropping_target(self, monkeypatch):
        # V3 champion이 CED 지원, V7은 미지원 → 승급 보류(커버리지 보호)
        import numpy as np

        from ml import structural_challenger as scc

        class FakeChampion:
            fitted_targets = ["density", "cohesive_energy_density"]

        class FakeRegistry:
            def __init__(self, session):
                pass

            def register_model(self, predictor, **kw):
                return type("Row", (), {"version_id": "v7-x"})()

            def get_champion_predictor(self):
                return FakeChampion()

        monkeypatch.setattr("ml.model_registry.ModelRegistry", FakeRegistry)
        vid, promoted, payload, notes = scc._register_and_maybe_promote(
            session=object(),
            predictor=type("P", (), {"_capability_manifest": {}})(),
            holdout={"density": (np.zeros((5, 32)), np.ones(5))},
            holdout_exp_ids={"density": [f"e{i}" for i in range(5)]},
            target_keys=["density"],  # CED 미포함 → 가드 발동
            training_samples=100,
            random_seed=42,
            triggered_by="t",
        )
        assert promoted is False
        assert any("승급 보류" in n and "cohesive_energy_density" in n for n in notes)

    def test_champion_predictions_by_exp_graceful(self, monkeypatch):
        from ml import structural_challenger as scc

        # load 실패 시 빈 dict (예외 격리)
        monkeypatch.setattr(
            "ml.dataset_router.load_training_dataset",
            lambda *a, **k: None,
        )

        class FakeChampion:
            class config:
                @staticmethod
                def get_feature_set_for_target(t):
                    return "v3"

        out = scc._champion_predictions_by_exp(object(), FakeChampion(), ["e1"])
        assert out == {}


class TestModelCompetition:
    def test_winner_selected_per_target(self):
        # A1: 물성별 XGB-vs-RF 승자 선택이 ModelType을 반환
        pytest.importorskip("xgboost")
        from ml.models import ModelType

        rng = np.random.default_rng(0)
        names = FeatureRegistry.get_features(FeatureSetVersion.V7)
        # RF가 유리한 비선형 + XGB가 유리한 선형, 두 표적
        Xtr = rng.normal(size=(60, 32))
        ds_lin = TrainingDataset(
            X=Xtr, y=1.0 + 0.1 * Xtr[:, 0], exp_ids=[f"e{i}" for i in range(60)],
            feature_names=names, target_name="density", metadata={},
        )
        Xho = rng.normal(size=(20, 32))
        holdout = {"density": (Xho, 1.0 + 0.1 * Xho[:, 0])}
        winners = sc._select_winning_model_types({"density": ds_lin}, holdout)
        assert winners["density"] in (ModelType.XGBOOST, ModelType.RANDOM_FOREST)

    def test_no_holdout_defaults_xgboost(self):
        from ml.models import ModelType

        ds = TrainingDataset(
            X=np.zeros((5, 32)), y=np.ones(5), exp_ids=list("abcde"),
            feature_names=["f"] * 32, target_name="density", metadata={},
        )
        winners = sc._select_winning_model_types({"density": ds}, holdout={})
        assert winners["density"] == ModelType.XGBOOST

    def test_manifest_records_model_types(self):
        pytest.importorskip("xgboost")
        from ml.models import ModelType

        ds = _synthetic_v7_dataset(n=40)
        pred = sc._build_and_train_v7(
            {"density": ds}, model_types={"density": ModelType.RANDOM_FOREST}
        )
        manifest = pred._capability_manifest  # noqa: SLF001
        assert manifest["model_types"]["density"] == "random_forest"


class TestTargetTransform:
    def test_msd_gets_log_transform(self):
        ds = TrainingDataset(
            X=np.zeros((5, 32)),
            y=np.array([1e-6, 2e-6, 3e-6, 4e-6, 5e-6]),
            exp_ids=list("abcde"),
            feature_names=["f"] * 32,
            target_name="msd_diffusion_coefficient",
            metadata={},
        )
        _t, params = sc._apply_target_transform(ds, "msd_diffusion_coefficient")
        assert params is not None and params["type"] == "log"

    def test_density_is_identity(self):
        ds = TrainingDataset(
            X=np.zeros((5, 32)),
            y=np.array([0.9, 0.95, 1.0, 1.05, 1.1]),
            exp_ids=list("abcde"),
            feature_names=["f"] * 32,
            target_name="density",
            metadata={},
        )
        _t, params = sc._apply_target_transform(ds, "density")
        assert params is None  # identity → 변환 없음

    def test_default_v7_targets_are_bulk(self):
        # density + MSD + RDF (전부 bulk), 계면(work_of_separation 등) 미포함
        assert "density" in sc.DEFAULT_V7_TARGETS
        assert "msd_diffusion_coefficient" in sc.DEFAULT_V7_TARGETS
        assert "work_of_separation" not in sc.DEFAULT_V7_TARGETS


class TestRandomRepeatEval:
    def test_xgb_vs_rf_random_repeats(self, monkeypatch):
        pytest.importorskip("xgboost")
        ds = _synthetic_v7_dataset(n=120)

        def loader(self, session, *, target, **kwargs):  # noqa: ANN001, ARG001
            return ds

        monkeypatch.setattr("ml.data_loader.DataLoader.load_from_database", loader)
        out = sc.evaluate_v7_random_repeats(
            session=object(), target="density", n_repeats=3
        )
        # 두 모델 모두 3회 평가, mean±std 산출
        assert set(out["models"]) == {"xgboost", "random_forest"}
        for mt in ("xgboost", "random_forest"):
            assert len(out["models"][mt]["per_repeat"]) == 3
            assert out["models"][mt]["rmse_mean"] >= 0
        assert out["winner"] in ("xgboost", "random_forest")
        assert out["n_repeats"] == 3

    def test_single_group_data_does_not_empty_train(self, monkeypatch):
        # 무첨가(단일 그룹) 데이터여도 랜덤 분할이라 train이 비지 않음
        pytest.importorskip("xgboost")
        ds = _synthetic_v7_dataset(n=80)

        def loader(self, session, *, target, **kwargs):  # noqa: ANN001, ARG001
            return ds

        monkeypatch.setattr("ml.data_loader.DataLoader.load_from_database", loader)
        out = sc.evaluate_v7_random_repeats(
            session=object(), target="density", n_repeats=2
        )
        # 학습이 실제로 일어남(빈 train 아님)
        assert out["models"]["xgboost"]["per_repeat"]

    def test_insufficient_data_graceful(self, monkeypatch):
        monkeypatch.setattr(
            "ml.data_loader.DataLoader.load_from_database",
            lambda self, session, **kw: None,  # noqa: ARG005
        )
        out = sc.evaluate_v7_random_repeats(session=object(), target="density")
        assert "error" in out


class TestMultiTargetTrain:
    def test_trains_density_and_msd_with_transform(self, monkeypatch):
        rng = np.random.default_rng(1)
        names = FeatureRegistry.get_features(FeatureSetVersion.V7)

        def make_ds(target, scale):
            X = rng.normal(size=(60, len(names)))
            base = 0.05 * (X[:, 0] - X[:, 0].mean())
            y = (1.0 + base) if target == "density" else np.exp(-13 + base) * scale
            return TrainingDataset(
                X=X, y=np.abs(y), exp_ids=[f"e{i}" for i in range(60)],
                feature_names=names, target_name=target, metadata={},
            )

        datasets = {
            "density": make_ds("density", 1.0),
            "msd_diffusion_coefficient": make_ds("msd_diffusion_coefficient", 1.0),
        }

        # load_from_database가 target별 dataset 반환
        def loader(self, session, *, target, **kwargs):  # noqa: ANN001, ARG001
            return datasets.get(target.value)

        monkeypatch.setattr("ml.data_loader.DataLoader.load_from_database", loader)
        out = sc.train_structural_challenger(
            session=object(),
            targets=["density", "msd_diffusion_coefficient"],
            min_samples=10,
            register=False,
        )
        assert set(out.targets_trained) == {"density", "msd_diffusion_coefficient"}
        assert "msd_diffusion_coefficient" in out.per_target_holdout_rmse


class TestTrainStructuralChallenger:
    def test_trains_and_reports_holdout_rmse(self, monkeypatch):
        ds = _synthetic_v7_dataset()

        def fake_load(self, session, **kwargs):  # noqa: ANN001, ARG001
            assert kwargs.get("feature_set_version") == FeatureSetVersion.V7
            return ds

        monkeypatch.setattr(
            "ml.data_loader.DataLoader.load_from_database", fake_load
        )
        outcome = sc.train_structural_challenger(
            session=object(),
            targets=["density"],
            min_samples=10,
            register=False,
        )
        assert outcome.targets_trained == ["density"]
        assert outcome.training_samples > 0
        assert outcome.holdout_samples > 0
        # 합성 데이터는 선형 관계라 RMSE가 작아야 함
        assert outcome.per_target_holdout_rmse["density"] < 0.05
        assert not outcome.promoted  # dry-run

    def test_no_dataset_graceful(self, monkeypatch):
        def fake_load(self, session, **kwargs):  # noqa: ANN001, ARG001
            return None

        monkeypatch.setattr(
            "ml.data_loader.DataLoader.load_from_database", fake_load
        )
        outcome = sc.train_structural_challenger(
            session=object(), targets=["density"], register=False
        )
        assert outcome.targets_trained == []
        assert outcome.version_id is None
        assert any("no V7 dataset" in n or "no trainable" in n for n in outcome.notes)

    def test_unknown_target_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "ml.data_loader.DataLoader.load_from_database",
            lambda self, session, **kw: None,  # noqa: ARG005
        )
        outcome = sc.train_structural_challenger(
            session=object(), targets=["not_a_metric"], register=False
        )
        assert outcome.targets_trained == []
