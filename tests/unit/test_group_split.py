"""Tests for group-aware data splitting."""

import numpy as np

from ml.data_loader import DataSplitter, TrainingDataset


def _make_dataset(n: int = 100, n_features: int = 5) -> TrainingDataset:
    return TrainingDataset(
        X=np.random.randn(n, n_features),
        y=np.random.randn(n),
        exp_ids=[f"exp_{i}" for i in range(n)],
        feature_names=[f"f{j}" for j in range(n_features)],
        target_name="density",
    )


class TestGroupSplit:
    def test_group_split_no_leakage(self) -> None:
        """Same group must not appear in multiple splits."""
        ds = _make_dataset(100)
        # 5 groups: 20 samples each
        groups = np.array([f"g{i // 20}" for i in range(100)])

        splitter = DataSplitter(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=42)
        split = splitter.split(ds, groups=groups)

        train_groups = set(groups[np.isin(ds.exp_ids, split.train.exp_ids)])
        val_groups = set(groups[np.isin(ds.exp_ids, split.val.exp_ids)])
        test_groups = set(groups[np.isin(ds.exp_ids, split.test.exp_ids)])

        # No overlap between any two splits
        assert train_groups & val_groups == set()
        assert train_groups & test_groups == set()
        assert val_groups & test_groups == set()

    def test_group_split_all_samples_assigned(self) -> None:
        """All samples must be assigned to exactly one split."""
        ds = _make_dataset(50)
        groups = np.array([f"g{i // 10}" for i in range(50)])

        splitter = DataSplitter(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=123)
        split = splitter.split(ds, groups=groups)

        total = split.train.n_samples + split.val.n_samples + split.test.n_samples
        assert total == 50

    def test_group_split_split_info(self) -> None:
        """Split info should contain group information."""
        ds = _make_dataset(30)
        groups = np.array([f"g{i // 10}" for i in range(30)])

        splitter = DataSplitter(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=42)
        split = splitter.split(ds, groups=groups)

        assert split.split_info["method"] == "group"
        assert "train_groups" in split.split_info
        assert "val_groups" in split.split_info
        assert "test_groups" in split.split_info

    def test_random_split_when_no_groups(self) -> None:
        """Without groups, random split should be used."""
        ds = _make_dataset(50)

        splitter = DataSplitter(train_ratio=0.7, val_ratio=0.15, test_ratio=0.15, random_seed=42)
        split = splitter.split(ds, groups=None)

        assert split.split_info["method"] == "random"
        total = split.train.n_samples + split.val.n_samples + split.test.n_samples
        assert total == 50

    def test_group_split_deterministic(self) -> None:
        """Same seed should produce same split."""
        ds = _make_dataset(60)
        groups = np.array([f"g{i // 15}" for i in range(60)])

        splitter1 = DataSplitter(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=99)
        split1 = splitter1.split(ds, groups=groups)

        splitter2 = DataSplitter(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=99)
        split2 = splitter2.split(ds, groups=groups)

        assert split1.train.exp_ids == split2.train.exp_ids
        assert split1.val.exp_ids == split2.val.exp_ids
        assert split1.test.exp_ids == split2.test.exp_ids
