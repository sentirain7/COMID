"""Tests for the scatter3d analysis service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from contracts.policies.ghg import GHGPolicy


@pytest.fixture()
def ghg_policy() -> GHGPolicy:
    return GHGPolicy(
        binder_molecules={"SA-Squalane": 0.40, "AS-Thio": 0.56},
        sara_fallback={
            "saturate": 0.42,
            "aromatic": 0.48,
            "resin": 0.51,
            "asphaltene": 0.55,
        },
        additives={"SBS": 3.40},
        default_binder_ef=0.50,
        default_additive_ef=0.0,
    )


class TestComputeGhgForExperiment:
    """Test _compute_ghg_for_experiment helper (batch-cache signature)."""

    def test_weight_fraction_path(self, ghg_policy: GHGPolicy) -> None:
        from features.analysis.service import _compute_ghg_for_experiment

        exp = MagicMock()
        exp.id = 1

        mol_cache = {
            1: [("SA-Squalane", 0.6), ("AS-Thio", 0.4)],
        }

        result = _compute_ghg_for_experiment(exp, ghg_policy, mol_cache)
        expected = 0.6 * 0.40 + 0.4 * 0.56
        assert result is not None
        assert abs(result - expected) < 1e-6

    def test_aging_wrapped_additive_in_weight_fractions(self, ghg_policy: GHGPolicy) -> None:
        """U-SBS-0293 in experiment_molecules must resolve to SBS EF=3.40."""
        from features.analysis.service import _compute_ghg_for_experiment

        exp = MagicMock()
        exp.id = 1

        mol_cache = {
            1: [("U-SA-Squalane-0293", 0.90), ("U-SBS-0293", 0.10)],
        }

        result = _compute_ghg_for_experiment(exp, ghg_policy, mol_cache)
        # SA-Squalane → 0.40, SBS → 3.40
        expected = 0.90 * 0.40 + 0.10 * 3.40
        assert result is not None
        assert abs(result - expected) < 1e-6

    def test_sara_fallback_path(self, ghg_policy: GHGPolicy) -> None:
        from features.analysis.service import _compute_ghg_for_experiment

        exp = MagicMock()
        exp.id = 1
        exp.comp_saturate_wt = 20.0
        exp.comp_aromatic_wt = 35.0
        exp.comp_resin_wt = 30.0
        exp.comp_asphaltene_wt = 15.0
        exp.additive_wt = 5.0
        exp.additive_mol_id = "SBS"

        # Empty cache → fallback to SARA
        mol_cache: dict = {}

        result = _compute_ghg_for_experiment(exp, ghg_policy, mol_cache)
        assert result is not None
        total = 20 + 35 + 30 + 15
        binder = 0.95 * (
            (20 / total) * 0.42 + (35 / total) * 0.48 + (30 / total) * 0.51 + (15 / total) * 0.55
        )
        additive = 0.05 * 3.40
        expected = binder + additive
        assert abs(result - expected) < 1e-6

    def test_no_sara_returns_none(self, ghg_policy: GHGPolicy) -> None:
        from features.analysis.service import _compute_ghg_for_experiment

        exp = MagicMock()
        exp.id = 1
        exp.comp_saturate_wt = 0
        exp.comp_aromatic_wt = 0
        exp.comp_resin_wt = 0
        exp.comp_asphaltene_wt = 0
        exp.additive_wt = 0
        exp.additive_mol_id = None

        result = _compute_ghg_for_experiment(exp, ghg_policy, {})
        assert result is None


class TestGetScatter3d:
    """Integration-level tests with mocked DB."""

    @pytest.mark.asyncio
    async def test_empty_data(self) -> None:
        from features.analysis.service import get_scatter3d

        with patch("features.analysis.service.run_in_session") as mock_run:

            def side_effect(fn):
                session = MagicMock()
                session.execute.return_value.all.return_value = []
                fn(session)

            mock_run.side_effect = side_effect

            result = await get_scatter3d()
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        from features.analysis.service import get_scatter3d

        with patch("features.analysis.service.run_in_session") as mock_run:
            mock_run.side_effect = lambda fn: None
            result = await get_scatter3d()
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_axis_raises(self) -> None:
        """Unsupported axis must raise ValueError, not silently return []."""
        from features.analysis.service import get_scatter3d

        with pytest.raises(ValueError, match="Unsupported"):
            await get_scatter3d(axis_x="bogus_metric")

    @pytest.mark.asyncio
    async def test_invalid_axis_z_raises(self) -> None:
        from features.analysis.service import get_scatter3d

        with pytest.raises(ValueError, match="Unsupported"):
            await get_scatter3d(axis_z="not_a_thing")
