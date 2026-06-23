"""
Unit tests for contracts module.

Tests schema validation, enum types, and data model integrity.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestEnums:
    """Test enum types."""

    def test_ff_type_values(self):
        """Test FFType enum values."""
        from contracts.schemas import FFType

        assert FFType.BULK_FF_GAFF2.value == "bulk_ff_gaff2"
        assert FFType.REAXFF.value == "reaxff"

    def test_run_tier_values(self):
        """Test RunTier enum values."""
        from contracts.schemas import RunTier

        assert RunTier.SCREENING.value == "screening"
        assert RunTier.CONFIRM.value == "confirm"
        assert RunTier.VISCOSITY.value == "viscosity"
        assert RunTier.VALIDATION.value == "validation"

    def test_molecule_category_values(self):
        """Test MoleculeCategory enum values."""
        from contracts.schemas import MoleculeCategory

        assert MoleculeCategory.SATURATE.value == "saturate"
        assert MoleculeCategory.AROMATIC.value == "aromatic"
        assert MoleculeCategory.RESIN.value == "resin"
        assert MoleculeCategory.ASPHALTENE.value == "asphaltene"
        assert MoleculeCategory.ADDITIVE.value == "additive"

    def test_experiment_status_values(self):
        """Test ExperimentStatus enum values."""
        from contracts.schemas import ExperimentStatus

        assert ExperimentStatus.PENDING.value == "pending"
        assert ExperimentStatus.RUNNING.value == "running"
        assert ExperimentStatus.COMPLETED.value == "completed"
        assert ExperimentStatus.FAILED.value == "failed"

    def test_failure_category_values(self):
        """Test FailureCategory enum values."""
        from contracts.schemas import FailureCategory

        assert FailureCategory.OVERLAP_INSTABILITY.value == "overlap_instability"
        assert FailureCategory.PRESSURE_BLOWUP.value == "pressure_blowup"
        assert FailureCategory.ENERGY_DRIFT.value == "energy_drift"


class TestBuildSchemas:
    """Test build-related schemas."""

    def test_build_request_valid(self):
        """Test valid BuildRequest creation."""
        from contracts.schemas import BuildRequest

        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 80},
            target_atoms=10000,
            atom_count_tolerance=0.10,
            initial_density=1.0,
            seed=42,
        )

        assert request.target_atoms == 10000
        assert request.seed == 42

    def test_build_request_defaults(self):
        """Test BuildRequest default values."""
        from contracts.schemas import BuildRequest

        request = BuildRequest(
            composition={"asphaltene": 100},
            seed=42,
        )

        assert request.target_atoms == 100000
        assert request.atom_count_tolerance == 0.10
        assert request.initial_density == 0.5

    def test_build_result_valid(self):
        """Test valid BuildResult creation."""
        from contracts.schemas import BuildResult

        result = BuildResult(
            data_file_path="/path/to/data.lammps",
            actual_atoms=9500,
            actual_density=0.98,
            topology_hash="abc123",
            packmol_version="20.14.0",
            actual_composition_wt={"asphaltene": 20.5},
            composition_error_l1=0.5,
            target_composition_wt={"asphaltene": 20.0},
            min_distance_violation_count=0,
            initial_pe_per_atom=-5.0,
        )

        assert result.actual_atoms == 9500
        assert result.composition_error_l1 == 0.5

    def test_composition_spec_validation(self):
        """Test CompositionSpec validation."""
        from contracts.schemas import CompositionSpec

        # Valid composition
        spec = CompositionSpec(
            basis="wt%",
            components={"a": 50, "b": 50},
        )
        assert sum(spec.components.values()) == 100

        # Invalid: negative values
        with pytest.raises(ValueError):
            CompositionSpec(
                basis="wt%",
                components={"a": -10, "b": 110},
            )


class TestProtocolSchemas:
    """Test protocol-related schemas."""

    def test_protocol_request_valid(self):
        """Test valid ProtocolRequest creation."""
        from contracts.schemas import FFType, ProtocolRequest, RunTier

        request = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

        assert request.temperature_K == 298.0
        assert request.ff_type == FFType.BULK_FF_GAFF2

    def test_protocol_result_valid(self):
        """Test valid ProtocolResult creation."""
        from contracts.schemas import ProtocolResult

        result = ProtocolResult(
            input_script_path="/path/to/in.lammps",
            expected_outputs=["log.lammps", "final.data"],
            estimated_steps=100000,
            protocol_hash="hash123",
            stabilization_chain=["minimize", "nvt", "npt"],
        )

        assert len(result.stabilization_chain) == 3
        assert result.protocol_hash == "hash123"

    def test_run_spec_defaults(self):
        """Test RunSpec default values."""
        from contracts.schemas import RunSpec

        spec = RunSpec()

        assert spec.temperature_K == 298.0
        assert spec.pressure_atm == 1.0
        assert spec.dt_fs == 1.0
        assert spec.lj_cutoff_angstrom == 12.0


class TestMetricSchemas:
    """Test metric-related schemas."""

    def test_metric_result_scalar(self):
        """Test MetricResult for scalar metrics."""
        from contracts.schemas import MetricResult

        result = MetricResult(
            exp_id="exp_001",
            metric_name="density",
            value=1.02,
            unit="g/cm3",
            namespace="bulk_ff_gaff2",
        )

        assert result.value == 1.02
        assert result.array_storage is None

    def test_metric_result_array(self):
        """Test MetricResult for array metrics."""
        from contracts.schemas import ArrayMetricStorage, MetricResult

        storage = ArrayMetricStorage(
            file_path="/path/to/rdf.parquet",
            file_hash="abc123",
            shape=(100, 2),
            summary={"min": 0.0, "max": 5.0},
        )

        result = MetricResult(
            exp_id="exp_001",
            metric_name="rdf_curve",
            value=None,
            unit="angstrom,dimensionless",
            namespace="bulk_ff_gaff2",
            array_storage=storage,
        )

        assert result.array_storage is not None
        assert result.array_storage.shape == (100, 2)

    def test_e_intra_key(self):
        """Test EIntraKey creation."""
        from contracts.schemas import EIntraKey

        key = EIntraKey(
            mol_id="asphaltene_01",
            ff_name="GAFF2",
            ff_version="1.0",
        )

        assert key.method == "single_molecule_vacuum"

    def test_e_intra_value(self):
        """Test EIntraValue creation."""
        from contracts.schemas import EIntraValue

        value = EIntraValue(
            e_intra=-150.5,
            lj_cutoff=100.0,
            coulomb_cutoff=100.0,
        )

        assert value.e_intra == -150.5
        assert value.computed_at is not None


class TestExperimentSchemas:
    """Test experiment-related schemas."""

    def test_experiment_record_minimal(self):
        """Test minimal ExperimentRecord creation."""
        from contracts.schemas import ExperimentRecord, FFType, RunTier

        record = ExperimentRecord(
            exp_id="exp_001",
            material_id="mat_001",
        )

        assert record.force_field_type == FFType.BULK_FF_GAFF2  # default
        assert record.run_tier == RunTier.SCREENING
        assert record.status.value == "pending"

    def test_lammps_run_result_success(self):
        """Test successful LAMMPSRunResult."""
        from contracts.schemas import LAMMPSRunResult

        result = LAMMPSRunResult(
            success=True,
            log_file="/path/to/log.lammps",
            dump_files=["dump.0.lammpstrj"],
            wall_time_seconds=3600.0,
            exit_code=0,
        )

        assert result.success
        assert result.error_message is None

    def test_lammps_run_result_failure(self):
        """Test failed LAMMPSRunResult."""
        from contracts.schemas import LAMMPSRunResult

        result = LAMMPSRunResult(
            success=False,
            log_file="/path/to/log.lammps",
            dump_files=[],
            wall_time_seconds=100.0,
            exit_code=1,
            error_message="Energy explosion",
        )

        assert not result.success
        assert result.error_message == "Energy explosion"

    def test_experiment_record_with_additive(self):
        """Test ExperimentRecord with additive fields."""
        from contracts.schemas import ExperimentRecord

        record = ExperimentRecord(
            exp_id="exp_add",
            material_id="mat_001",
            additive_type="polymer",
            additive_wt=5.0,
            additive_mol_id="ppa_monomer",
        )
        assert record.additive_type == "polymer"
        assert record.additive_wt == 5.0
        assert record.additive_mol_id == "ppa_monomer"

    def test_experiment_record_additive_common_name(self):
        """str type allows common names like PPA/SBS."""
        from contracts.schemas import ExperimentRecord

        record = ExperimentRecord(
            exp_id="exp_ppa",
            material_id="mat_001",
            additive_type="PPA",
            additive_wt=3.0,
        )
        assert record.additive_type == "PPA"

    def test_experiment_record_additive_defaults(self):
        """Test additive field defaults."""
        from contracts.schemas import ExperimentRecord

        record = ExperimentRecord(exp_id="exp_no_add", material_id="mat_001")
        assert record.additive_type is None
        assert record.additive_wt == 0.0
        assert record.additive_mol_id is None


class TestStageCondition:
    """Test StageCondition serialization."""

    def test_stage_condition_ramp_serialization(self):
        from api.schemas import StageCondition

        cond = StageCondition(
            temperature_mode="ramp",
            fixed_temperature_K=500.0,
            n_cycles=5,
            uses_target_temperature=True,
        )
        data = cond.model_dump()
        assert data["temperature_mode"] == "ramp"
        reconstructed = StageCondition(**data)
        assert reconstructed == cond


class TestLayerSpec:
    """Test LayerSpec reproducibility fields."""

    def test_layer_spec_reproducibility_fields(self):
        """Test LayerSpec with reproducibility tracking fields."""
        from contracts.schemas import AgingState, LayerSpec

        spec = LayerSpec(
            binder_composition_ref="AAA1",
            interface_stack_id="D",
            grip_mode="cantilever",
            layer_boundary_z=[0.0, 25.0, 75.0],
            aging_state=AgingState.SHORT_AGING,
        )
        assert spec.interface_stack_id == "D"
        assert len(spec.layer_boundary_z) == 3
        assert spec.aging_state == AgingState.SHORT_AGING

    def test_layer_spec_defaults(self):
        """Test LayerSpec new fields default to None."""
        from contracts.schemas import LayerSpec

        spec = LayerSpec(binder_composition_ref="AAA1")
        assert spec.interface_stack_id is None
        assert spec.grip_mode is None
        assert spec.layer_boundary_z is None
        assert spec.aging_state is None

    def test_layer_spec_grip_z_range_defaults_none(self):
        """Grip z-range fields default to None."""
        from contracts.schemas import LayerSpec

        spec = LayerSpec()
        assert spec.bottom_grip_z_range is None
        assert spec.top_grip_z_range is None

    def test_layer_spec_grip_z_range_roundtrip(self):
        """Grip z-range tuple roundtrips through model_dump/reconstruct."""
        from contracts.schemas import LayerSpec

        spec = LayerSpec(
            bottom_grip_z_range=(25.0, 35.0),
            top_grip_z_range=(85.0, 95.0),
        )
        assert spec.bottom_grip_z_range == (25.0, 35.0)
        assert spec.top_grip_z_range == (85.0, 95.0)

        data = spec.model_dump()
        reconstructed = LayerSpec(**data)
        assert tuple(reconstructed.bottom_grip_z_range) == (25.0, 35.0)
        assert tuple(reconstructed.top_grip_z_range) == (85.0, 95.0)


class TestGroupEnergySpec:
    """Test GroupEnergySpec and related schemas (Phase 4.2)."""

    def test_group_energy_spec_creation(self):
        """Test GroupEnergySpec + GroupPairSpec creation."""
        from contracts.schemas import GroupEnergySpec, GroupPairSpec

        pair = GroupPairSpec(label="saturate_aromatic", group_a="saturate", group_b="aromatic")
        spec = GroupEnergySpec(
            groups={"saturate": [1, 2, 3], "aromatic": [4, 5]},
            pairs=[pair],
            atom_counts={"saturate": 150, "aromatic": 36},
            additive_pair_label=None,
        )
        assert len(spec.groups) == 2
        assert spec.pairs[0].label == "saturate_aromatic"
        assert spec.atom_counts["saturate"] == 150
        assert spec.additive_pair_label is None

    def test_group_energy_spec_defaults(self):
        """Test GroupEnergySpec with all defaults."""
        from contracts.schemas import GroupEnergySpec

        spec = GroupEnergySpec()
        assert spec.groups == {}
        assert spec.pairs == []
        assert spec.atom_counts == {}
        assert spec.additive_pair_label is None

    def test_build_result_with_molecule_ordering(self):
        """Test BuildResult with molecule_ordering field."""
        from contracts.schemas import BuildResult

        ordering = [
            {"mol_id": "SAT_001", "count": 3, "category": "saturate", "atom_count": 50},
        ]
        result = BuildResult(
            data_file_path="/path/to/data.lammps",
            actual_atoms=9500,
            actual_density=0.98,
            topology_hash="abc123",
            packmol_version="20.14.0",
            actual_composition_wt={"saturate": 100.0},
            composition_error_l1=0.0,
            target_composition_wt={"saturate": 100.0},
            initial_pe_per_atom=-5.0,
            molecule_ordering=ordering,
        )
        assert result.molecule_ordering is not None
        assert len(result.molecule_ordering) == 1
        assert result.molecule_ordering[0]["mol_id"] == "SAT_001"

    def test_build_result_molecule_ordering_default_none(self):
        """Test BuildResult.molecule_ordering defaults to None."""
        from contracts.schemas import BuildResult

        result = BuildResult(
            data_file_path="/path/to/data.lammps",
            actual_atoms=9500,
            actual_density=0.98,
            topology_hash="abc123",
            packmol_version="20.14.0",
            actual_composition_wt={},
            composition_error_l1=0.0,
            target_composition_wt={},
            initial_pe_per_atom=-5.0,
        )
        assert result.molecule_ordering is None

    def test_protocol_request_with_group_energy_spec(self):
        """Test ProtocolRequest with group_energy_spec field."""
        from contracts.schemas import FFType, GroupEnergySpec, ProtocolRequest, RunTier

        spec = GroupEnergySpec(groups={"saturate": [1, 2]})
        request = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            data_file_path="/path/to/data.lammps",
            group_energy_spec=spec,
        )
        assert request.group_energy_spec is not None
        assert request.group_energy_spec.groups["saturate"] == [1, 2]

    def test_protocol_request_group_energy_spec_default_none(self):
        """Test ProtocolRequest.group_energy_spec defaults to None."""
        from contracts.schemas import ProtocolRequest

        request = ProtocolRequest(data_file_path="/path/to/data.lammps")
        assert request.group_energy_spec is None

    def test_lammps_run_result_with_group_energy_spec(self):
        """Test LAMMPSRunResult with group_energy_spec field."""
        from contracts.schemas import GroupEnergySpec, LAMMPSRunResult

        spec = GroupEnergySpec(
            groups={"saturate": [1], "aromatic": [2]},
            atom_counts={"saturate": 50, "aromatic": 18},
        )
        result = LAMMPSRunResult(
            success=True,
            log_file="/path/to/log.lammps",
            wall_time_seconds=100.0,
            exit_code=0,
            group_energy_spec=spec,
        )
        assert result.group_energy_spec is not None
        assert result.group_energy_spec.atom_counts["saturate"] == 50

    def test_lammps_run_result_group_energy_spec_default_none(self):
        """Test LAMMPSRunResult.group_energy_spec defaults to None."""
        from contracts.schemas import LAMMPSRunResult

        result = LAMMPSRunResult(
            success=True,
            log_file="/path/to/log.lammps",
            wall_time_seconds=100.0,
            exit_code=0,
        )
        assert result.group_energy_spec is None


class TestTensileSpec:
    """Test TensileSpec parameter fields."""

    def test_tensile_spec_parameters(self):
        """Test TensileSpec with tensile test parameters."""
        from contracts.schemas import TensileSpec

        spec = TensileSpec(
            enabled=True,
            pull_velocity_A_per_fs=0.0002,
            max_strain=0.3,
            layer_scenario="A",
        )
        assert spec.pull_velocity_A_per_fs == 0.0002
        assert spec.max_strain == 0.3
        assert spec.layer_scenario == "A"

    def test_tensile_spec_defaults(self):
        """Test TensileSpec default values."""
        from contracts.schemas import TensileSpec

        spec = TensileSpec()
        assert spec.enabled is False
        assert spec.pull_velocity_A_per_fs == 0.00005
        assert spec.grip_thickness_angstrom == 20.0
        assert spec.max_strain == 0.5
        assert spec.pull_axis == "z"
        assert spec.layer_scenario is None

    def test_tensile_spec_output_interval(self):
        """Test TensileSpec output_interval_steps field (Phase 4.3)."""
        from contracts.schemas import TensileSpec

        spec = TensileSpec(enabled=True, output_interval_steps=200)
        assert spec.output_interval_steps == 200

        # Default
        spec2 = TensileSpec()
        assert spec2.output_interval_steps == 100


class TestLayerSpecPhase43:
    """Test LayerSpec SSOT integration (Phase 4.3)."""

    def test_layer_type_enum_values(self):
        """Test LayerType enum includes all scenarios."""
        from contracts.schemas import LayerType

        assert LayerType.INTERFACE == "interface"
        assert LayerType.WATER_INTERFACE == "water-interface"
        assert LayerType.THREE_LAYER == "3-layer"
        assert LayerType.AGED_FRESH == "aged-fresh"
        assert LayerType.WATER_AGED_FRESH == "water-aged-fresh"
        assert LayerType.BINDER_BINDER == "binder-binder"

    def test_crystal_material_cite_alias(self):
        """Test CrystalMaterial.CITE and CACO3 both map to CaCO3."""
        from contracts.schemas import CrystalMaterial

        assert CrystalMaterial.CITE == "CaCO3"
        assert CrystalMaterial.CACO3 == "CaCO3"
        assert CrystalMaterial.CITE is CrystalMaterial.CACO3

    def test_layer_spec_structured_creation(self):
        """Test LayerSpec with structured sub-models."""
        from contracts.schemas import (
            CrystalLayerSpec,
            CrystalMaterial,
            LayerSpec,
            LayerType,
        )

        spec = LayerSpec(
            layer_type=LayerType.INTERFACE,
            crystal=CrystalLayerSpec(
                material=CrystalMaterial.SIO2,
                thickness_angstrom=30.0,
            ),
        )
        assert spec.crystal.material == CrystalMaterial.SIO2
        assert spec.crystal.thickness_angstrom == 30.0
        assert spec.water is None

    def test_layer_spec_flat_migration_crystal(self):
        """Test flat dict backward compat: crystal_material key."""
        from contracts.schemas import LayerSpec

        flat = {
            "crystal_material": "SiO2",
            "crystal_thickness_angstrom": 30.0,
            "binder_composition_ref": "AAA1",
        }
        spec = LayerSpec.model_validate(flat)
        assert spec.crystal.material == "SiO2"
        assert spec.crystal.thickness_angstrom == 30.0
        assert spec.binder.composition_ref == "AAA1"

    def test_layer_spec_flat_migration_binder_only(self):
        """Test flat dict backward compat: binder_composition_ref only."""
        from contracts.schemas import LayerSpec

        flat = {
            "binder_composition_ref": "AAA1",
            "interface_stack_id": "D",
            "grip_mode": "cantilever",
            "layer_boundary_z": [0.0, 25.0, 75.0],
        }
        spec = LayerSpec.model_validate(flat)
        assert spec.binder.composition_ref == "AAA1"
        assert spec.interface_stack_id == "D"

    def test_layer_spec_serialization_roundtrip(self):
        """Test LayerSpec serialization and deserialization."""
        from contracts.schemas import CrystalMaterial, LayerSpec, LayerType

        spec = LayerSpec(
            layer_type=LayerType.WATER_INTERFACE,
            crystal={"material": CrystalMaterial.SIO2, "thickness_angstrom": 25.0},
            water={"thickness_angstrom": 10.0},
        )
        data = spec.model_dump()
        spec2 = LayerSpec.model_validate(data)
        assert spec2.layer_type == LayerType.WATER_INTERFACE
        assert spec2.water is not None
        assert spec2.water.thickness_angstrom == 10.0

    def test_protocol_request_with_tensile_spec(self):
        """Test ProtocolRequest with tensile_spec forward reference."""
        from contracts.schemas import ProtocolRequest, TensileSpec

        req = ProtocolRequest(
            data_file_path="/tmp/test.data",
            tensile_spec=TensileSpec(enabled=True),
        )
        assert req.tensile_spec is not None
        assert req.tensile_spec.enabled is True

    def test_protocol_request_with_layer_spec(self):
        """Test ProtocolRequest with layer_spec forward reference."""
        from contracts.schemas import LayerSpec, ProtocolRequest

        req = ProtocolRequest(
            data_file_path="/tmp/test.data",
            layer_spec=LayerSpec(),
        )
        assert req.layer_spec is not None

    def test_lammps_run_result_tensile_fields(self):
        """Test LAMMPSRunResult tensile metadata fields."""
        from contracts.schemas import LAMMPSRunResult, TensileSpec

        result = LAMMPSRunResult(
            success=True,
            log_file="/tmp/log.lammps",
            wall_time_seconds=100.0,
            exit_code=0,
            tensile_spec=TensileSpec(enabled=True),
            interface_area_nm2=25.0,
            original_gap_angstrom=50.0,
        )
        assert result.tensile_spec.enabled is True
        assert result.interface_area_nm2 == 25.0
        assert result.original_gap_angstrom == 50.0

    def test_lammps_run_result_tensile_defaults(self):
        """Test LAMMPSRunResult tensile fields default to None."""
        from contracts.schemas import LAMMPSRunResult

        result = LAMMPSRunResult(
            success=True,
            log_file="/tmp/log.lammps",
            wall_time_seconds=100.0,
            exit_code=0,
        )
        assert result.tensile_spec is None
        assert result.interface_area_nm2 is None
        assert result.original_gap_angstrom is None
