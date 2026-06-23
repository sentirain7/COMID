"""Tests for recommendation.property_targets module."""

import pytest

from recommendation.property_targets import (
    PropertyTarget,
    PropertyTargetSet,
)


class TestPropertyTarget:
    """Tests for PropertyTarget dataclass."""

    def test_is_satisfied_within_range(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.is_satisfied(1.0) is True

    def test_is_satisfied_below_min(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.is_satisfied(0.8) is False

    def test_is_satisfied_above_max(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.is_satisfied(1.2) is False

    def test_is_satisfied_no_bounds(self) -> None:
        t = PropertyTarget(metric_name="density")
        assert t.is_satisfied(999.0) is True

    def test_is_satisfied_only_min(self) -> None:
        t = PropertyTarget(metric_name="viscosity", target_min=5.0)
        assert t.is_satisfied(10.0) is True
        assert t.is_satisfied(3.0) is False

    def test_is_satisfied_only_max(self) -> None:
        t = PropertyTarget(metric_name="viscosity", target_max=3000.0)
        assert t.is_satisfied(2000.0) is True
        assert t.is_satisfied(4000.0) is False

    def test_distance_to_target_inside(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.distance_to_target(1.0) == 0.0

    def test_distance_to_target_below(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.distance_to_target(0.7) == pytest.approx(0.2)

    def test_distance_to_target_above(self) -> None:
        t = PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1)
        assert t.distance_to_target(1.3) == pytest.approx(0.2)

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid direction"):
            PropertyTarget(metric_name="density", direction="invalid")

    def test_valid_directions(self) -> None:
        for d in ("maximize", "minimize", "target"):
            t = PropertyTarget(metric_name="density", direction=d)
            assert t.direction == d


class TestPropertyTargetSet:
    """Tests for PropertyTargetSet."""

    def test_validate_against_registry_valid(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="density", unit="g/cm3"),
                PropertyTarget(metric_name="viscosity", unit="mPa.s"),
            ],
        )
        ok, errors = ts.validate_against_registry()
        assert ok is True
        assert errors == []

    def test_validate_against_registry_unknown_metric(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[PropertyTarget(metric_name="nonexistent_metric")],
        )
        ok, errors = ts.validate_against_registry()
        assert ok is False
        assert any("Unknown metric" in e for e in errors)

    def test_validate_against_registry_unit_mismatch(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[PropertyTarget(metric_name="density", unit="kg/m^3")],
        )
        ok, errors = ts.validate_against_registry()
        assert ok is False
        assert any("Unit mismatch" in e for e in errors)

    def test_are_all_satisfied_true(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1),
                PropertyTarget(metric_name="viscosity", target_max=3000.0),
            ],
        )
        assert ts.are_all_satisfied({"density": 1.0, "viscosity": 2000.0}) is True

    def test_are_all_satisfied_false(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1),
            ],
        )
        assert ts.are_all_satisfied({"density": 0.5}) is False

    def test_are_all_satisfied_missing_metric(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[PropertyTarget(metric_name="density", target_min=0.9)],
        )
        assert ts.are_all_satisfied({}) is False

    def test_get_objectives(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="density", direction="maximize", weight=2.0),
                PropertyTarget(metric_name="viscosity", direction="minimize"),
            ],
        )
        objs = ts.get_objectives()
        assert len(objs) == 2
        assert objs[0]["name"] == "density"
        assert objs[0]["weight"] == 2.0
        assert objs[1]["direction"] == "minimize"

    def test_get_objectives_target_direction(self) -> None:
        """'target' direction should map to 'maximize' for optimizer."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[PropertyTarget(metric_name="density", direction="target")],
        )
        objs = ts.get_objectives()
        assert objs[0]["direction"] == "maximize"

    def test_compute_distances(self) -> None:
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1),
                PropertyTarget(metric_name="viscosity", target_max=3000.0),
            ],
        )
        dists = ts.compute_distances({"density": 0.7, "viscosity": 2000.0})
        assert dists["density"] == pytest.approx(0.2)
        assert dists["viscosity"] == 0.0

