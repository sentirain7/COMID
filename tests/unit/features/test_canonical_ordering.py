"""Tests for canonical ordering helpers."""

from features.common.canonical_ordering import (
    canonical_value_key,
    group_sort_key,
    stable_sort_records,
)


class TestCanonicalValueKey:
    """canonical_value_key() returns consistent sort tuples."""

    def test_aging_order(self):
        keys = [
            canonical_value_key("aging_state", v)
            for v in ["long_aging", "non_aging", "short_aging"]
        ]
        sorted_keys = sorted(keys)
        assert sorted_keys[0][1] == "non_aging"
        assert sorted_keys[1][1] == "short_aging"
        assert sorted_keys[2][1] == "long_aging"

    def test_additive_none_first(self):
        k_none = canonical_value_key("additive", "none")
        k_sbs = canonical_value_key("additive", "SBS")
        assert k_none < k_sbs

    def test_additive_None_sentinel(self):
        k_none = canonical_value_key("additive", None)
        k_sbs = canonical_value_key("additive", "SBS")
        assert k_none < k_sbs

    def test_additive_empty_string(self):
        k_empty = canonical_value_key("additive", "")
        k_sbs = canonical_value_key("additive", "SBS")
        assert k_empty < k_sbs

    def test_layer_type_order(self):
        keys = [
            canonical_value_key("layer_type", v) for v in ["binder-binder", "interface", "3-layer"]
        ]
        sorted_keys = sorted(keys)
        assert sorted_keys[0][1] == "interface"
        assert sorted_keys[1][1] == "3-layer"
        assert sorted_keys[2][1] == "binder-binder"

    def test_binder_order(self):
        keys = [canonical_value_key("binder_type", v) for v in ["M1", "A1", "K1"]]
        sorted_keys = sorted(keys)
        assert sorted_keys[0][1] == "A1"
        assert sorted_keys[1][1] == "K1"
        assert sorted_keys[2][1] == "M1"

    def test_temperature_numeric_ordering(self):
        k273 = canonical_value_key("temperature_K", 273)
        k298 = canonical_value_key("temperature_K", 298)
        k373 = canonical_value_key("temperature_K", 373)
        assert k273 < k298 < k373

    def test_unknown_dimension_fallback(self):
        k = canonical_value_key("unknown_dim", "foo")
        assert k == (99, "foo")


class TestStableSortRecords:
    """stable_sort_records() produces deterministic output."""

    def test_basic_sort(self):
        records = [
            {"exp_id": "exp3", "aging_state": "long_aging"},
            {"exp_id": "exp1", "aging_state": "non_aging"},
            {"exp_id": "exp2", "aging_state": "short_aging"},
        ]
        result = stable_sort_records(records, ["aging_state"])
        assert [r["exp_id"] for r in result] == ["exp1", "exp2", "exp3"]

    def test_tiebreaker_exp_id(self):
        records = [
            {"exp_id": "exp_c", "aging_state": "non_aging"},
            {"exp_id": "exp_a", "aging_state": "non_aging"},
            {"exp_id": "exp_b", "aging_state": "non_aging"},
        ]
        result = stable_sort_records(records, ["aging_state"])
        assert [r["exp_id"] for r in result] == ["exp_a", "exp_b", "exp_c"]

    def test_multi_key_sort(self):
        records = [
            {"exp_id": "e1", "additive": "SBS", "temperature_K": 373},
            {"exp_id": "e2", "additive": "none", "temperature_K": 298},
            {"exp_id": "e3", "additive": "none", "temperature_K": 273},
        ]
        result = stable_sort_records(records, ["additive", "temperature_K"])
        assert [r["exp_id"] for r in result] == ["e3", "e2", "e1"]

    def test_deterministic(self):
        """Same input always produces same output."""
        records = [
            {"exp_id": f"e{i}", "aging_state": "non_aging", "temperature_K": 298}
            for i in range(10, 0, -1)
        ]
        r1 = stable_sort_records(records, ["aging_state", "temperature_K"])
        r2 = stable_sort_records(records, ["aging_state", "temperature_K"])
        assert r1 == r2

    def test_empty_input(self):
        assert stable_sort_records([], ["aging_state"]) == []


class TestGroupSortKey:
    """group_sort_key() is a drop-in for the old _group_sort_key."""

    def test_binder_order(self):
        assert group_sort_key("binder", "A1") < group_sort_key("binder", "K1")
        assert group_sort_key("binder", "K1") < group_sort_key("binder", "M1")

    def test_aging_order(self):
        assert group_sort_key("aging", "non_aging") < group_sort_key("aging", "short_aging")

    def test_additive_none_first(self):
        assert group_sort_key("additive", None) < group_sort_key("additive", "SBS")
