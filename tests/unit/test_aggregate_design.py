"""
Unit tests for aggregate-aware inverse design (Step 4-3).

Inverse design is property-target driven; requests specify ``custom_targets``.
"""

import pytest

from api.schemas import AggregateSpecRequest, InverseDesignRequest, PropertyTargetItem

# Reusable target sets expressed as custom_targets payloads.
_BULK_TARGETS = [
    PropertyTargetItem(metric_name="density", target_min=0.9, target_max=1.1, direction="target"),
    PropertyTargetItem(metric_name="viscosity", target_max=3000.0, direction="minimize"),
]
# Mixed V3 (density) + V4 (interface) targets — formerly the HIGH_ADHESION preset.
_INTERFACE_TARGETS = [
    PropertyTargetItem(metric_name="density", target_min=0.95, target_max=1.15, direction="target"),
    PropertyTargetItem(metric_name="work_of_separation", target_min=100.0, direction="maximize"),
    PropertyTargetItem(metric_name="interfacial_tensile_strength", direction="maximize"),
]


class TestAggregateSpecRequest:
    """Test AggregateSpecRequest schema."""

    def test_create_basic(self):
        spec = AggregateSpecRequest(material="SiO2", surface="001")
        assert spec.material == "SiO2"
        assert spec.surface == "001"

    def test_default_surface(self):
        spec = AggregateSpecRequest(material="CaCO3")
        assert spec.surface == "001"


class TestInverseDesignRequestExtended:
    """Test InverseDesignRequest with aggregate_specs."""

    def test_backward_compatible(self):
        """Requests without aggregate_specs should still work."""
        req = InverseDesignRequest(custom_targets=_BULK_TARGETS)
        assert req.aggregate_specs is None
        assert req.explore_all_additives is False

    def test_with_aggregate_specs(self):
        req = InverseDesignRequest(
            custom_targets=_INTERFACE_TARGETS,
            aggregate_specs=[
                AggregateSpecRequest(material="SiO2", surface="001"),
                AggregateSpecRequest(material="CaCO3", surface="010"),
            ],
        )
        assert len(req.aggregate_specs) == 2
        assert req.aggregate_specs[0].material == "SiO2"

    def test_explore_all_additives(self):
        req = InverseDesignRequest(
            custom_targets=[
                PropertyTargetItem(
                    metric_name="adhesion_energy",
                    direction="maximize",
                ),
            ],
            aggregate_specs=[
                AggregateSpecRequest(material="SiO2"),
            ],
            explore_all_additives=True,
        )
        assert req.explore_all_additives is True


class TestResolveTargetSet:
    """Test resolve_property_target_set with custom_targets."""

    def test_resolve_custom_targets(self):
        from features.recommendations.inverse_design import resolve_property_target_set

        req = InverseDesignRequest(custom_targets=_INTERFACE_TARGETS)
        target_set = resolve_property_target_set(req)
        assert target_set.name == "custom"
        names = [t.metric_name for t in target_set.targets]
        assert "work_of_separation" in names
        assert "interfacial_tensile_strength" in names

    def test_resolve_requires_custom_targets(self):
        """A request that bypasses schema validation (no targets) must raise."""
        from contracts.errors import ContractError
        from features.recommendations.inverse_design import resolve_property_target_set

        req = InverseDesignRequest.model_construct(custom_targets=None)
        with pytest.raises(ContractError):
            resolve_property_target_set(req)


class TestInverseDesignBinderSource:
    """Test binder_source_exp_id field on InverseDesignRequest."""

    def test_default_none(self):
        req = InverseDesignRequest(custom_targets=_BULK_TARGETS)
        assert req.binder_source_exp_id is None

    def test_with_binder_source(self):
        req = InverseDesignRequest(
            custom_targets=_INTERFACE_TARGETS,
            aggregate_specs=[AggregateSpecRequest(material="SiO2")],
            binder_source_exp_id="test_exp_001",
        )
        assert req.binder_source_exp_id == "test_exp_001"


class TestResolveCrystalProperties:
    """Test _resolve_crystal_properties fallback chain."""

    def test_returns_correct_structure(self):
        """Should return a dict with required keys and valid values."""
        from features.recommendations.inverse_design import _resolve_crystal_properties

        props = _resolve_crystal_properties("SiO2", "001")
        assert props["material"] == "SiO2"
        assert props["surface"] == "001"
        # Values come from DB if available, otherwise schema defaults
        assert props["hydroxyl_density"] > 0
        assert props["thickness_angstrom"] > 0
        assert props["xy_size_angstrom"] > 0
        assert "atom_count" in props

    def test_unknown_material_uses_defaults(self):
        """Unknown material without DB entry should use schema defaults."""
        from features.recommendations.inverse_design import _resolve_crystal_properties

        props = _resolve_crystal_properties("ZrO2_Unknown", "110")
        assert props["material"] == "ZrO2_Unknown"
        assert props["surface"] == "110"
        assert props["hydroxyl_density"] == 4.6  # CrystalLayerSpec default
        assert props["thickness_angstrom"] == 25.0
        assert props["xy_size_angstrom"] == 50.0

    def test_zero_hydroxyl_density_preserved(self):
        """DB 0.0 values must NOT be replaced by defaults (Issue 3 regression).

        Verifies 'is not None' logic: 0.0 is a valid value for NaCl (no hydroxyls).
        """
        from contextlib import contextmanager
        from unittest.mock import MagicMock, patch

        from features.recommendations.inverse_design import _resolve_crystal_properties

        # Mock a DB crystal with hydroxyl_density=0.0 (valid for NaCl)
        mock_crystal = MagicMock()
        mock_crystal.hydroxyl_density = 0.0
        mock_crystal.thickness_angstrom = 30.0
        mock_crystal.xy_size_angstrom = 60.0
        mock_crystal.atom_count = 3000

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_crystal

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        @contextmanager
        def fake_session_scope():
            yield mock_session

        with patch("database.connection.session_scope", fake_session_scope):
            props = _resolve_crystal_properties("NaCl", "001")
            assert props["hydroxyl_density"] == 0.0, (
                "0.0 should be preserved, not replaced by default 4.6"
            )


class TestV4TargetGuard:
    """Test that V4-only targets are handled correctly in standard design path."""

    def test_all_v4_custom_targets_raises(self):
        """All-V4 custom targets → must raise without aggregate_specs."""
        from contracts.errors import ContractError
        from features.recommendations.inverse_design import _run_standard_design

        # Create request with ONLY V4 targets (no V3 targets like density)
        req = InverseDesignRequest(
            custom_targets=[
                PropertyTargetItem(metric_name="adhesion_energy", direction="maximize"),
                PropertyTargetItem(
                    metric_name="interfacial_tensile_strength", direction="maximize"
                ),
            ]
        )
        with pytest.raises(ContractError, match="aggregate_specs"):
            import asyncio

            asyncio.run(_run_standard_design(req))

    def test_mixed_v3_v4_targets_raise_too(self):
        """Mixed V3/V4 interface targets still must raise without aggregate_specs."""
        from contracts.errors import ContractError
        from features.recommendations.inverse_design import _run_standard_design

        req = InverseDesignRequest(custom_targets=_INTERFACE_TARGETS)
        with pytest.raises(ContractError, match="aggregate_specs"):
            import asyncio

            asyncio.run(_run_standard_design(req))

    def test_bulk_targets_without_aggregate_specs_works(self):
        """Bulk-only targets are V3 — should NOT raise about aggregate_specs."""
        from features.recommendations.inverse_design import _run_standard_design

        req = InverseDesignRequest(custom_targets=_BULK_TARGETS)
        # Should raise about ML model not loaded, NOT about aggregate_specs
        with pytest.raises(Exception) as exc_info:
            import asyncio

            asyncio.run(_run_standard_design(req))
        assert "aggregate_specs" not in str(exc_info.value)
