"""Tests for Layer interaction v2: GroupSelector, group commands, cross-cut,
and _calculate_layer_interactions runtime path."""

import sys
from unittest.mock import MagicMock

sys.path.insert(0, "src")

from contracts.schemas import ArrayMetricStorage, GroupEnergySpec, GroupPairSpec, GroupSelector
from metrics.group_assignment import LayerGroupAssignmentBuilder
from metrics.layer_metrics import AdhesionEnergyCalculator, compute_cross_cut_interaction
from protocols.lammps_force_field import generate_group_energy_commands

# Single SSOT for the kcal/mol/Å² → mJ/m² conversion (so the test never pins a
# stale literal again).
_K = AdhesionEnergyCalculator.KCAL_MOL_A2_TO_MJ_M2


def _mock_array_storage():
    """Create a mock ArrayStorage whose store_metric returns a valid ArrayMetricStorage."""
    mock_storage = MagicMock()

    def _store(**kwargs):
        return ArrayMetricStorage(
            file_path="/tmp/test.parquet",
            file_hash="abc123",
            shape=(1, 2),
            summary={"test": True},
        )

    mock_storage.store_metric = MagicMock(side_effect=lambda **kw: _store(**kw))
    return mock_storage


class TestLayerGroupAssignmentBuilder:
    """LayerGroupAssignmentBuilder unit tests."""

    def test_build_3_layers(self):
        lineage = [
            {"index": 0, "type": "crystal", "atom_id_start": 1, "atom_id_end": 500},
            {"index": 1, "type": "binder", "atom_id_start": 501, "atom_id_end": 3000},
            {"index": 2, "type": "crystal", "atom_id_start": 3001, "atom_id_end": 3500},
        ]
        spec = LayerGroupAssignmentBuilder().build(lineage)
        assert spec.layer_count == 3
        assert len(spec.pairs) == 3  # C(3,2)
        assert spec.group_selectors is not None
        assert "layer_0" in spec.group_selectors
        assert spec.group_selectors["layer_0"].mode == "atom_id_range"
        assert spec.group_selectors["layer_0"].range_start == 1
        assert spec.group_selectors["layer_0"].range_end == 500

    def test_pair_labels_format(self):
        lineage = [
            {"index": 0, "type": "a", "atom_id_start": 1, "atom_id_end": 10},
            {"index": 1, "type": "b", "atom_id_start": 11, "atom_id_end": 20},
        ]
        spec = LayerGroupAssignmentBuilder().build(lineage)
        labels = {p.label for p in spec.pairs}
        assert labels == {"L0_L1"}

    def test_empty_lineage(self):
        spec = LayerGroupAssignmentBuilder().build([])
        assert spec.layer_count is None
        assert len(spec.pairs) == 0


class TestGenerateGroupEnergyCommandsV2:
    """Protocol generation with v2 GroupSelector."""

    def test_atom_id_range_output(self):
        spec = GroupEnergySpec(
            group_selectors={
                "layer_0": GroupSelector(mode="atom_id_range", range_start=1, range_end=500),
                "layer_1": GroupSelector(mode="atom_id_range", range_start=501, range_end=3000),
            },
            pairs=[GroupPairSpec(label="L0_L1", group_a="layer_0", group_b="layer_1")],
            layer_count=2,
        )
        output = generate_group_energy_commands(spec)
        assert "group layer_0 id 1:500" in output
        assert "group layer_1 id 501:3000" in output

    def test_kspace_omitted_for_kokkos_compatibility(self):
        """Verify kspace option is omitted for KOKKOS pppm/kk compatibility.

        Note: kspace yes is not supported by KOKKOS pppm/kk.
        Short-range interactions (LJ + direct Coulomb within cutoff) are computed.
        For high-precision long-range Coulomb, use CPU rerun mode.
        """
        spec = GroupEnergySpec(
            group_selectors={
                "layer_0": GroupSelector(mode="atom_id_range", range_start=1, range_end=10),
            },
            pairs=[GroupPairSpec(label="L0_L1", group_a="layer_0", group_b="layer_1")],
        )
        output = generate_group_energy_commands(spec)
        assert "group/group" in output
        assert "kspace yes" not in output  # KOKKOS compatibility

    def test_v1_molecule_mode_unchanged(self):
        spec = GroupEnergySpec(
            groups={"saturate": [1, 2, 3], "aromatic": [4, 5]},
            pairs=[GroupPairSpec(label="sat_aro", group_a="saturate", group_b="aromatic")],
        )
        output = generate_group_energy_commands(spec)
        assert "group saturate molecule 1 2 3" in output
        assert "group/group" in output
        assert "kspace yes" not in output  # KOKKOS compatibility


class TestComputeCrossCutInteraction:
    """Cross-cut interaction proxy manual verification."""

    def test_3layer_cut_0(self):
        # 3 layers, cut between 0 and 1
        # lower={0}, upper={1,2}
        # cross-cut pairs: (0,1) + (0,2)
        matrix = {(0, 1): -100.0, (0, 2): -50.0, (1, 2): -80.0}
        result = compute_cross_cut_interaction(matrix, 3, 10.0, (0, 1))
        # Expected: -(-100 + -50) / (10*100) * K = 150/1000 * 694.77
        expected = -(-100.0 + -50.0) / (10.0 * 100) * _K
        assert abs(result - expected) < 1e-6

    def test_3layer_cut_1(self):
        # lower={0,1}, upper={2}
        # cross-cut pairs: (0,2) + (1,2)
        matrix = {(0, 1): -100.0, (0, 2): -50.0, (1, 2): -80.0}
        result = compute_cross_cut_interaction(matrix, 3, 10.0, (1, 2))
        expected = -(-50.0 + -80.0) / (10.0 * 100) * _K
        assert abs(result - expected) < 1e-6

    def test_5layer_cut_2(self):
        # 5 layers, cut between 2 and 3
        # lower={0,1,2}, upper={3,4}
        # cross pairs: (0,3),(0,4),(1,3),(1,4),(2,3),(2,4)
        matrix = {
            (0, 3): -10.0,
            (0, 4): -5.0,
            (1, 3): -20.0,
            (1, 4): -8.0,
            (2, 3): -30.0,
            (2, 4): -12.0,
        }
        result = compute_cross_cut_interaction(matrix, 5, 20.0, (2, 3))
        cross_sum = -10 + -5 + -20 + -8 + -30 + -12  # = -85
        expected = -cross_sum / (20.0 * 100) * _K
        assert abs(result - expected) < 1e-6

    def test_zero_area_returns_zero(self):
        matrix = {(0, 1): -100.0}
        result = compute_cross_cut_interaction(matrix, 2, 0.0, (0, 1))
        assert result == 0.0


# ---------------------------------------------------------------------------
# Runtime path: _calculate_layer_interactions with array_storage
# ---------------------------------------------------------------------------


def _make_layer_spec_and_thermo():
    """Create a 3-layer GroupEnergySpec and matching thermo data."""
    spec = GroupEnergySpec(
        group_selectors={
            "layer_0": GroupSelector(mode="atom_id_range", range_start=1, range_end=500),
            "layer_1": GroupSelector(mode="atom_id_range", range_start=501, range_end=3000),
            "layer_2": GroupSelector(mode="atom_id_range", range_start=3001, range_end=3500),
        },
        pairs=[
            GroupPairSpec(label="L0_L1", group_a="layer_0", group_b="layer_1"),
            GroupPairSpec(label="L0_L2", group_a="layer_0", group_b="layer_2"),
            GroupPairSpec(label="L1_L2", group_a="layer_1", group_b="layer_2"),
        ],
        layer_count=3,
    )
    thermo = {
        "c_gg_L0_L1": [-100.0] * 20,
        "c_gg_L0_L2": [-50.0] * 20,
        "c_gg_L1_L2": [-80.0] * 20,
    }
    return spec, thermo


class TestCalculateLayerInteractionsRuntime:
    """Runtime tests for _calculate_layer_interactions with array_storage."""

    def test_array_storage_filled_for_both_metrics(self):
        """Both array metrics should have array_storage set."""
        from metrics.calculator import MetricCalculator

        mock_storage = _mock_array_storage()

        calc = MetricCalculator(
            array_storage=mock_storage,
            ced_coverage_mode="allow_missing_pe_over_v",
        )
        spec, thermo = _make_layer_spec_and_thermo()
        mock_run_result = MagicMock()
        mock_run_result.exp_id = "test_exp_001"

        metrics = calc._calculate_layer_interactions(
            thermo_data=thermo,
            group_spec=spec,
            interface_area_nm2=10.0,
            run_result=mock_run_result,
        )

        # Should produce 2 metrics: e_inter_layer_matrix + cross_cut_interaction_profile
        assert len(metrics) == 2
        names = {m.metric_name for m in metrics}
        assert "e_inter_layer_matrix" in names
        assert "cross_cut_interaction_profile" in names

        # Both should have array_storage set (not None)
        for m in metrics:
            assert m.array_storage is not None, f"{m.metric_name} missing array_storage"

        # store_metric should have been called twice
        assert mock_storage.store_metric.call_count == 2

    def test_no_array_storage_skips_all(self):
        """Without array_storage, no metrics should be produced."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator(
            array_storage=None,
            ced_coverage_mode="allow_missing_pe_over_v",
        )
        spec, thermo = _make_layer_spec_and_thermo()

        metrics = calc._calculate_layer_interactions(
            thermo_data=thermo,
            group_spec=spec,
            interface_area_nm2=10.0,
            run_result=MagicMock(exp_id="test"),
        )
        assert metrics == []

    def test_no_interface_area_skips_cross_cut_only(self):
        """Without interface_area, only e_inter_layer_matrix is produced."""
        from metrics.calculator import MetricCalculator

        mock_storage = _mock_array_storage()

        calc = MetricCalculator(
            array_storage=mock_storage,
            ced_coverage_mode="allow_missing_pe_over_v",
        )
        spec, thermo = _make_layer_spec_and_thermo()

        metrics = calc._calculate_layer_interactions(
            thermo_data=thermo,
            group_spec=spec,
            interface_area_nm2=None,
            run_result=MagicMock(exp_id="test"),
        )

        names = {m.metric_name for m in metrics}
        assert "e_inter_layer_matrix" in names
        assert "cross_cut_interaction_profile" not in names

    def test_no_exp_id_skips_all(self):
        """Without exp_id, no metrics should be produced."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator(
            array_storage=MagicMock(),
            ced_coverage_mode="allow_missing_pe_over_v",
        )
        spec, thermo = _make_layer_spec_and_thermo()

        metrics = calc._calculate_layer_interactions(
            thermo_data=thermo,
            group_spec=spec,
            interface_area_nm2=10.0,
            run_result=MagicMock(exp_id=None),
        )
        assert metrics == []


class TestAdhesionUnitConversion:
    """Lock the kcal/mol/Å² → mJ/m² conversion (v01.05.23 fix)."""

    def test_conversion_constant_is_physical(self):
        # 1 kcal/mol/Å² = 694.77 mJ/m² (4184/N_A/1e-20 ×1000).
        assert abs(AdhesionEnergyCalculator.KCAL_MOL_A2_TO_MJ_M2 - 694.77) < 0.5

    def test_adhesion_magnitude_is_reasonable(self):
        """Bitumen-aggregate work of adhesion is O(10-100) mJ/m², not O(1e-3)."""
        calc = AdhesionEnergyCalculator()
        # E_interaction = -100 kcal/mol over 25 nm² (2500 Å²).
        res = calc.calculate(
            e_total=-100.0, e_crystal=0.0, e_binder=0.0, interface_area_nm2=25.0
        )
        # W_ad = -(-100)/2500 * 694.77 = 27.79 mJ/m²
        assert 20.0 < res.work_of_adhesion < 40.0
