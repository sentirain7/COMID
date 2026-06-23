"""Unit tests for ReplicatePolicy."""

import pytest

from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY, ReplicatePolicy


class TestReplicatePolicyDefaults:
    """Tests for default policy values."""

    def test_default_min_seeds(self):
        """Default minimum seeds is 3."""
        assert DEFAULT_REPLICATE_POLICY.min_seeds == 3

    def test_default_ci_level(self):
        """Default CI level is 0.95."""
        assert DEFAULT_REPLICATE_POLICY.ci_level == 0.95

    def test_default_significance_alpha(self):
        """Default significance alpha is 0.05."""
        assert DEFAULT_REPLICATE_POLICY.significance_alpha == 0.05

    def test_default_seeds(self):
        """Default seed list is [1, 2, 3]."""
        assert DEFAULT_REPLICATE_POLICY.default_seeds == [1, 2, 3]

    def test_required_tiers(self):
        """Confirm and viscosity require replicates."""
        assert "confirm" in DEFAULT_REPLICATE_POLICY.required_for_tiers
        assert "viscosity" in DEFAULT_REPLICATE_POLICY.required_for_tiers

    def test_recommended_tiers(self):
        """Screening recommends replicates."""
        assert "screening" in DEFAULT_REPLICATE_POLICY.recommended_for_tiers


class TestIsRequired:
    """Tests for is_required()."""

    def test_confirm_required(self):
        assert DEFAULT_REPLICATE_POLICY.is_required("confirm") is True

    def test_viscosity_required(self):
        assert DEFAULT_REPLICATE_POLICY.is_required("viscosity") is True

    def test_screening_not_required(self):
        assert DEFAULT_REPLICATE_POLICY.is_required("screening") is False

    def test_unknown_tier_not_required(self):
        assert DEFAULT_REPLICATE_POLICY.is_required("unknown_tier") is False


class TestIsRecommended:
    """Tests for is_recommended()."""

    def test_screening_recommended(self):
        assert DEFAULT_REPLICATE_POLICY.is_recommended("screening") is True

    def test_confirm_not_recommended(self):
        """Confirm is required, not just recommended."""
        assert DEFAULT_REPLICATE_POLICY.is_recommended("confirm") is False


class TestGetSeeds:
    """Tests for get_seeds()."""

    def test_returns_user_seeds_when_provided(self):
        seeds = DEFAULT_REPLICATE_POLICY.get_seeds([10, 20, 30])
        assert seeds == [10, 20, 30]

    def test_returns_defaults_when_none(self):
        seeds = DEFAULT_REPLICATE_POLICY.get_seeds(None)
        assert seeds == [1, 2, 3]

    def test_returns_defaults_when_empty(self):
        seeds = DEFAULT_REPLICATE_POLICY.get_seeds([])
        assert seeds == [1, 2, 3]


class TestValidateReplicateCount:
    """Tests for validate_replicate_count()."""

    def test_confirm_with_enough_replicates(self):
        assert DEFAULT_REPLICATE_POLICY.validate_replicate_count(3, "confirm") is True

    def test_confirm_with_insufficient_replicates(self):
        assert DEFAULT_REPLICATE_POLICY.validate_replicate_count(2, "confirm") is False

    def test_screening_always_valid(self):
        """Screening is only recommended, so any count is valid."""
        assert DEFAULT_REPLICATE_POLICY.validate_replicate_count(1, "screening") is True

    def test_custom_min_seeds(self):
        """Custom policy with min_seeds=5."""
        policy = ReplicatePolicy(min_seeds=5)
        assert policy.validate_replicate_count(4, "confirm") is False
        assert policy.validate_replicate_count(5, "confirm") is True


class TestCustomPolicy:
    """Tests for custom policy creation."""

    def test_custom_ci_level(self):
        policy = ReplicatePolicy(ci_level=0.99)
        assert policy.ci_level == 0.99

    def test_custom_required_tiers(self):
        policy = ReplicatePolicy(required_for_tiers=["screening", "confirm", "viscosity"])
        assert policy.is_required("screening") is True

    def test_invalid_ci_level_rejected(self):
        with pytest.raises(ValueError):
            ReplicatePolicy(ci_level=1.5)

    def test_invalid_min_seeds_rejected(self):
        with pytest.raises(ValueError):
            ReplicatePolicy(min_seeds=0)
