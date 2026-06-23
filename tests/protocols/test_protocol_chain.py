"""Tests for protocol chain builder."""

import sys

import pytest

sys.path.insert(0, "src")

from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
from protocols.protocol_chain import ProtocolChainBuilder, ProtocolStep


class TestProtocolChainBuilder:
    """Test protocol chain builder."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    @pytest.fixture
    def screening_request(self):
        return ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

    @pytest.fixture
    def confirm_request(self):
        return ProtocolRequest(
            run_tier=RunTier.CONFIRM,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=300.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

    def test_build_screening_chain(self, builder, screening_request):
        """Test building screening tier chain."""
        chain = builder.build(screening_request)

        assert chain.tier == RunTier.SCREENING
        assert len(chain.steps) > 0
        assert chain.ff_type == FFType.BULK_FF_GAFF2
        assert chain.temperature_K == 298.0

    def test_build_confirm_chain(self, builder, confirm_request):
        """Test building confirm tier chain."""
        chain = builder.build(confirm_request)

        assert chain.tier == RunTier.CONFIRM
        assert len(chain.steps) > 0

    def test_chain_has_minimization(self, builder, screening_request):
        """Test that chain includes minimization step."""
        chain = builder.build(screening_request)

        step_types = [step.step_type for step in chain.steps]
        assert "minimize" in step_types

    def test_chain_has_equilibration(self, builder, screening_request):
        """Test that chain includes equilibration steps."""
        chain = builder.build(screening_request)

        step_types = [step.step_type for step in chain.steps]
        # Should have at least NVT or NPT
        assert "nvt" in step_types or "npt" in step_types

    def test_total_duration(self, builder, screening_request):
        """Test total duration calculation."""
        chain = builder.build(screening_request)
        total_ps = builder.get_total_duration_ps(chain)

        assert total_ps > 0

    def test_total_steps(self, builder, screening_request):
        """Test total steps calculation."""
        chain = builder.build(screening_request)
        total_steps = builder.get_total_steps(chain)

        assert total_steps > 0

    def test_estimate_runtime(self, builder, screening_request):
        """Test runtime estimation."""
        chain = builder.build(screening_request)
        hours = builder.estimate_runtime_hours(chain, atom_count=100000)

        assert hours > 0


class TestProtocolStep:
    """Test protocol step dataclass."""

    def test_default_values(self):
        """Test default step values."""
        step = ProtocolStep(
            name="test_step",
            step_type="nvt",
        )

        assert step.temperature_K == 298.0
        assert step.pressure_atm == 1.0
        assert step.timestep_fs == 1.0

    def test_custom_values(self):
        """Test custom step values."""
        step = ProtocolStep(
            name="hot_nvt",
            step_type="nvt",
            temperature_K=500.0,
            duration="200 ps",
        )

        assert step.temperature_K == 500.0
        assert step.duration == "200 ps"


class TestViscosityChain:
    """Test viscosity tier chain."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    @pytest.fixture
    def viscosity_request(self):
        return ProtocolRequest(
            run_tier=RunTier.VISCOSITY,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

    def test_viscosity_chain_has_viscosity_step(self, builder, viscosity_request):
        """Test that viscosity tier includes viscosity calculation step."""
        chain = builder.build(viscosity_request)

        step_names = [step.name.lower() for step in chain.steps]
        has_viscosity = any(
            "viscosity" in name or "nemd" in name or "muller" in name for name in step_names
        )

        assert has_viscosity


class TestTensileLayerChain:
    """Test tensile_layer tier chain (literature-based 6-step protocol)."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    @pytest.fixture
    def tensile_request(self):
        from contracts.schemas import StudyType, TensileSpec

        return ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=373.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=TensileSpec(enabled=True),
        )

    def test_tensile_chain_has_seven_steps(self, builder, tensile_request):
        """tensile_layer chain builds 7 ProtocolSteps."""
        chain = builder.build(tensile_request)
        assert len(chain.steps) == 7
        names = [s.name for s in chain.steps]
        assert names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
            "pre_tensile_nvt",
            "tensile_pull",
        ]

    def test_minimize_constraints_normalized(self, builder, tensile_request):
        """minimize step constraints are normalized from SSOT parameters."""
        chain = builder.build(tensile_request)
        min_step = chain.steps[0]
        assert min_step.step_type == "minimize"
        assert min_step.constraints["etol"] == 1e-5
        assert min_step.constraints["ftol"] == 1e-7
        assert min_step.constraints["max_iter"] == 50000
        assert min_step.constraints["max_eval"] == 500000

    def test_annealing_step_type_and_ensemble(self, builder, tensile_request):
        """annealing step has step_type='annealing' and ensemble='nvt'."""
        chain = builder.build(tensile_request)
        anneal_step = chain.steps[2]
        assert anneal_step.step_type == "annealing"
        assert anneal_step.ensemble == "nvt"

    def test_annealing_temp_low_injected(self, builder, tensile_request):
        """annealing step gets temp_low_K from request temperature_K."""
        chain = builder.build(tensile_request)
        anneal_step = chain.steps[2]
        assert anneal_step.extra_params["temp_low_K"] == 373.0

    def test_pre_tensile_nvt_uses_target_temperature(self, builder, tensile_request):
        """pre_tensile_nvt step uses request target temperature."""
        chain = builder.build(tensile_request)
        pt_step = chain.steps[5]
        assert pt_step.name == "pre_tensile_nvt"
        assert pt_step.step_type == "nvt"
        assert pt_step.temperature_K == 373.0

    def test_tensile_spec_injection(self, builder):
        """tensile_spec + layer_spec inject grip z-boundaries."""
        from contracts.schemas import LayerSpec, StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=TensileSpec(enabled=True),
            layer_spec=LayerSpec(layer_boundary_z=[0.0, 50.0, 100.0]),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]
        assert tensile_step.extra_params["z_lo_grip"] == 0.0
        assert tensile_step.extra_params["z_hi_grip"] == 100.0


class TestGetTotalStepsMinimizeDuration:
    """Test get_total_steps uses minimize duration, not max_iter."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    @pytest.fixture
    def screening_request(self):
        return ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

    def test_get_total_steps_minimize_uses_duration_not_maxiter(self, builder, screening_request):
        """get_total_steps uses minimize duration field, not constraints max_iter."""
        chain = builder.build(screening_request)
        total = builder.get_total_steps(chain)
        # screening: minimize "1000 steps" + nvt 300ps=300000 + npt 2000ps=2000000
        assert total == 2301000  # NOT 2310000 (max_iter=10000)


class TestNonTensileLayerChain:
    """LAYER_BULKFF without tensile → 5-step 'layer' chain."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    def test_layer_bulkff_no_tensile_uses_layer_chain(self, builder):
        """LAYER_BULKFF without tensile_spec uses 'layer' chain (5 steps)."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            study_type=StudyType.LAYER_BULKFF,
        )
        chain = builder.build(request)
        step_names = [s.name for s in chain.steps]
        assert step_names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
        ]
        assert len(chain.steps) == 5

    def test_layer_bulkff_with_tensile_uses_tensile_layer_chain(self, builder):
        """LAYER_BULKFF with tensile_spec.enabled uses 'tensile_layer' chain (6 steps)."""
        from contracts.schemas import TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            study_type=StudyType.LAYER_BULKFF,
            tensile_spec=TensileSpec(enabled=True),
        )
        chain = builder.build(request)
        step_names = [s.name for s in chain.steps]
        assert len(chain.steps) == 7
        assert step_names[-1] == "tensile_pull"

    def test_bulk_study_type_ignores_tensile_spec(self, builder):
        """BULK study_type with tensile_spec still uses screening chain (no tensile_layer).

        This guards against ppp+tensile chain mismatch: even if tensile_spec
        is set, BULK study_type routes to the tier-based chain (screening=3 steps).
        """
        from contracts.schemas import TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            study_type=StudyType.BULK,
            tensile_spec=TensileSpec(enabled=True),
        )
        chain = builder.build(request)
        step_names = [s.name for s in chain.steps]
        assert "tensile_pull" not in step_names
        assert len(chain.steps) == 3  # screening chain (minimize, nvt, npt)


class TestCrystalGripMode:
    """Test crystal grip range passthrough and mixed-mode duration."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    def test_crystal_grip_ranges_passed_to_extra_params(self, builder):
        """LayerSpec with grip ranges → extra_params has bottom_grip_z/top_grip_z."""
        from contracts.schemas import LayerSpec, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=TensileSpec(enabled=True),
            layer_spec=LayerSpec(
                layer_boundary_z=[25.0, 35.0, 85.0, 95.0],
                bottom_grip_z_range=(25.0, 35.0),
                top_grip_z_range=(85.0, 95.0),
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]
        assert tensile_step.extra_params["bottom_grip_z"] == (25.0, 35.0)
        assert tensile_step.extra_params["top_grip_z"] == (85.0, 95.0)

    def test_crystal_grip_fallback_to_thickness(self, builder):
        """Without grip ranges, extra_params has no bottom_grip_z."""
        from contracts.schemas import LayerSpec, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=TensileSpec(enabled=True),
            layer_spec=LayerSpec(layer_boundary_z=[0.0, 50.0, 100.0]),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]
        assert "bottom_grip_z" not in tensile_step.extra_params
        assert "top_grip_z" not in tensile_step.extra_params

    def test_crystal_grip_mixed_mode_duration(self, builder):
        """One explicit + one fallback: gap computed correctly."""
        from contracts.schemas import LayerSpec, TensileSpec

        ts = TensileSpec(
            enabled=True,
            pull_velocity_A_per_fs=0.00005,
            grip_thickness_angstrom=20.0,
            max_strain=0.5,
        )
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=ts,
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 10.0, 90.0],
                bottom_grip_z_range=(0.0, 10.0),
                # top_grip_z_range=None → fallback to thickness
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]

        # bottom_end = 10.0 (explicit), top_start = 90 - 20 = 70.0 (fallback)
        # gap = 70 - 10 = 60, max_disp = 60 * 0.5 = 30
        # time_fs = 30 / 0.00005 = 600000 → 600.0 ps
        assert tensile_step.duration == "600.0 ps"

    def test_crystal_grip_both_explicit_duration(self, builder):
        """Both explicit: gap = top[0] - bottom[1]."""
        from contracts.schemas import LayerSpec, TensileSpec

        ts = TensileSpec(
            enabled=True,
            pull_velocity_A_per_fs=0.00005,
            grip_thickness_angstrom=20.0,
            max_strain=0.5,
        )
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=ts,
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 15.0, 85.0, 100.0],
                bottom_grip_z_range=(0.0, 15.0),
                top_grip_z_range=(85.0, 100.0),
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]

        # bottom_end = 15.0, top_start = 85.0, gap = 70
        # max_disp = 70 * 0.5 = 35, time_fs = 35/0.00005 = 700000 → 700.0 ps
        assert tensile_step.duration == "700.0 ps"


class TestQuasiStaticChain:
    """Quasi-static decohesion chain tests."""

    @pytest.fixture
    def builder(self):
        return ProtocolChainBuilder()

    @pytest.fixture
    def qs_request(self):
        from contracts.schemas import TensileMode, TensileSpec

        return ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=TensileSpec(
                enabled=True,
                mode=TensileMode.QUASI_STATIC,
                displacement_increment_angstrom=0.5,
                relax_steps=10000,
                force_average_steps=1000,
            ),
        )

    def test_qs_chain_has_seven_steps(self, builder, qs_request):
        """tensile_layer_qs chain has 7 steps (same structure as tensile_layer)."""
        chain = builder.build(qs_request)
        assert len(chain.steps) == 7
        assert chain.steps[-1].name == "tensile_pull"

    def test_qs_extra_params_injected(self, builder, qs_request):
        """QS parameters injected into tensile step extra_params."""
        chain = builder.build(qs_request)
        tensile_step = chain.steps[-1]
        assert tensile_step.extra_params["tensile_mode"] == "quasi_static"
        assert tensile_step.extra_params["displacement_increment_angstrom"] == 0.5
        assert tensile_step.extra_params["relax_steps"] == 10000
        assert tensile_step.extra_params["force_average_steps"] == 1000

    def test_qs_duration_calculation(self, builder):
        """QS duration = n_disp_steps * relax_steps * dt."""
        from contracts.schemas import LayerSpec, TensileMode, TensileSpec

        ts = TensileSpec(
            enabled=True,
            mode=TensileMode.QUASI_STATIC,
            displacement_increment_angstrom=0.5,
            relax_steps=10000,
            max_strain=0.5,
            grip_thickness_angstrom=20.0,
        )
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=ts,
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 15.0, 85.0, 100.0],
                bottom_grip_z_range=(0.0, 15.0),
                top_grip_z_range=(85.0, 100.0),
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]

        # gap = 85 - 15 = 70, max_disp = 70*0.5 = 35
        # n_disp_steps = ceil(35/0.5) = 70
        # total_fs = 70 * 10000 * 1.0 = 700000 → 700.0 ps
        assert tensile_step.duration == "700.0 ps"

    def test_qs_small_gap_minimum_one_step(self, builder):
        """Small gap → n_disp_steps clamped to 1, duration > 0."""
        from contracts.schemas import LayerSpec, TensileMode, TensileSpec

        ts = TensileSpec(
            enabled=True,
            mode=TensileMode.QUASI_STATIC,
            displacement_increment_angstrom=0.5,
            relax_steps=10000,
            max_strain=0.1,
            grip_thickness_angstrom=20.0,
        )
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=ts,
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 20.0, 22.0, 42.0],
                bottom_grip_z_range=(0.0, 20.0),
                top_grip_z_range=(22.0, 42.0),
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]
        # gap=2, max_disp=0.2, ceil(0.2/0.5)=1
        # total_fs = 1 * 10000 * 1.0 = 10000 → 10.0 ps
        assert tensile_step.duration == "10.0 ps"

    def test_continuous_mode_unaffected(self, builder):
        """Continuous mode still uses velocity-based duration."""
        from contracts.schemas import LayerSpec, TensileMode, TensileSpec

        ts = TensileSpec(
            enabled=True,
            mode=TensileMode.CONTINUOUS,
            pull_velocity_A_per_fs=0.00005,
            grip_thickness_angstrom=20.0,
            max_strain=0.5,
        )
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
            tensile_spec=ts,
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 15.0, 85.0, 100.0],
                bottom_grip_z_range=(0.0, 15.0),
                top_grip_z_range=(85.0, 100.0),
            ),
        )
        chain = builder.build(request)
        tensile_step = chain.steps[-1]
        # gap=70, max_disp=35, time_fs=35/0.00005=700000 → 700.0 ps
        assert tensile_step.duration == "700.0 ps"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
