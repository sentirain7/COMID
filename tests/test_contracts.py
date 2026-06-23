"""
Tests for contract schemas and interfaces.

This test file validates that all contracts are correctly defined
and can be instantiated with valid data.
"""

import sys

import pytest

sys.path.insert(0, "src")

from contracts.errors import (
    CompositionError,
    ContractError,
    ErrorCode,
    ValidationError,
)
from contracts.interfaces import (
    IEIntraStore,
    IStructureBuilder,
)
from contracts.schemas import (
    ArrayMetricStorage,
    BuildRequest,
    BuildResult,
    CompositionSpec,
    EIntraKey,
    EIntraValue,
    ExperimentRecord,
    ExperimentStatus,
    FFType,
    LAMMPSRunResult,
    MetricResult,
    MoleculeCategory,
    MoleculeInfo,
    MoleculeSpec,
    ProtocolRequest,
    ProtocolResult,
    RunTier,
    ThermoData,
    ValidityDomainTag,
)


class TestEnums:
    """Test enum definitions."""

    def test_ff_type_values(self):
        assert FFType.BULK_FF_GAFF2.value == "bulk_ff_gaff2"
        assert FFType.REAXFF.value == "reaxff"

    def test_run_tier_values(self):
        assert RunTier.SCREENING.value == "screening"
        assert RunTier.CONFIRM.value == "confirm"
        assert RunTier.VISCOSITY.value == "viscosity"
        assert RunTier.VALIDATION.value == "validation"

    def test_molecule_category_values(self):
        assert MoleculeCategory.ASPHALTENE.value == "asphaltene"
        assert MoleculeCategory.RESIN.value == "resin"
        assert MoleculeCategory.AROMATIC.value == "aromatic"
        assert MoleculeCategory.SATURATE.value == "saturate"
        assert MoleculeCategory.ADDITIVE.value == "additive"

    def test_validity_domain_tags(self):
        assert ValidityDomainTag.BULK_GAFF2_OK.value == "bulk_gaff2_ok"
        assert ValidityDomainTag.HIGH_ASPHALTENE_SENSITIVE.value == "high_asphaltene_sensitive"


class TestMoleculeSchemas:
    """Test molecule-related schemas."""

    def test_molecule_spec_creation(self):
        mol = MoleculeSpec(
            mol_id="asphaltene_01",
            smiles="c1ccc2c(c1)ccc3c2ccc4c3cccc4",
            molecular_weight=278.35,
            atom_count=42,
            category=MoleculeCategory.ASPHALTENE,
            structure_file="molecules/asphaltene_01.mol2",
            topology_hash="sha256:abc123",
        )
        assert mol.mol_id == "asphaltene_01"
        assert mol.category == MoleculeCategory.ASPHALTENE
        assert mol.molecular_weight == 278.35

    def test_molecule_info_lightweight(self):
        info = MoleculeInfo(
            mol_id="resin_01",
            molecular_weight=350.0,
            atom_count=50,
            category=MoleculeCategory.RESIN,
        )
        assert info.mol_id == "resin_01"
        assert info.atom_count == 50


class TestBuildSchemas:
    """Test build-related schemas."""

    def test_build_request_defaults(self):
        req = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=12345,
        )
        assert req.target_atoms == 100000
        assert req.atom_count_tolerance == 0.10
        assert req.initial_density == 0.6

    def test_build_request_custom(self):
        req = BuildRequest(
            composition={"asphaltene": 25, "resin": 25, "aromatic": 30, "saturate": 20},
            target_atoms=200000,
            atom_count_tolerance=0.05,
            initial_density=1.05,
            seed=99999,
        )
        assert req.target_atoms == 200000
        assert req.seed == 99999

    def test_build_result_full(self):
        result = BuildResult(
            data_file_path="/path/to/data.lammps",
            actual_atoms=99500,
            actual_density=1.02,
            topology_hash="abc12345",
            packmol_version="20.14.0",
            actual_composition_wt={"asphaltene": 20.1, "resin": 29.9},
            composition_error_l1=0.2,
            target_composition_wt={"asphaltene": 20.0, "resin": 30.0},
            min_distance_violation_count=0,
            initial_pe_per_atom=-5.5,
        )
        assert result.composition_error_l1 == 0.2
        assert result.stability_flag is None

    def test_composition_spec_validation(self):
        # Valid composition
        comp = CompositionSpec(
            components={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15}
        )
        assert sum(comp.components.values()) == 100

        # Negative values should fail
        with pytest.raises(ValueError):
            CompositionSpec(components={"asphaltene": -10, "resin": 110})


class TestProtocolSchemas:
    """Test protocol-related schemas."""

    def test_protocol_request(self):
        req = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )
        assert req.ff_type == FFType.BULK_FF_GAFF2
        assert req.temperature_K == 298.0

    def test_protocol_result(self):
        result = ProtocolResult(
            input_script_path="/path/to/in.lammps",
            expected_outputs=["log.lammps", "dump.lammpstrj"],
            estimated_steps=1000000,
            protocol_hash="a1b2c3d4",
            stabilization_chain=["minimize", "nvt_equilibration", "npt_production"],
        )
        assert result.protocol_hash == "a1b2c3d4"
        assert len(result.stabilization_chain) == 3


class TestEIntraSchemas:
    """Test E_intra cache schemas."""

    def test_e_intra_key(self):
        key = EIntraKey(
            mol_id="asphaltene_01",
            ff_name="GAFF2",
            ff_version="1.0",
        )
        assert key.method == "single_molecule_vacuum"

    def test_e_intra_value(self):
        value = EIntraValue(
            e_intra=-150.5,
        )
        assert value.e_intra == -150.5
        assert value.lj_cutoff == 100.0
        assert value.coulomb_cutoff == 100.0


class TestMetricSchemas:
    """Test metric-related schemas."""

    def test_metric_result_scalar(self):
        result = MetricResult(
            exp_id="test_exp_001",
            metric_name="density",
            value=1.05,
            unit="g/cm3",
            namespace="bulk_ff_gaff2",
        )
        assert result.value == 1.05
        assert result.array_storage is None

    def test_metric_result_array(self):
        storage = ArrayMetricStorage(
            file_path="/data/arrays/exp001/rdf_curve.parquet",
            file_hash="abc123def456",
            shape=(1000, 2),
            summary={"min": 0.0, "max": 3.5, "mean": 1.2},
        )
        result = MetricResult(
            exp_id="test_exp_001",
            metric_name="rdf_curve",
            unit="[angstrom, dimensionless]",
            namespace="bulk_ff_gaff2",
            array_storage=storage,
            array_summary={"first_peak_r": 3.5, "first_peak_g": 2.1},
        )
        assert result.value is None
        assert result.array_storage.shape == (1000, 2)


class TestExperimentSchemas:
    """Test experiment record schemas."""

    def test_experiment_record_minimal(self):
        record = ExperimentRecord(
            exp_id="binderA_bulk_ff_screening_T298K",
            material_id="binderA",
        )
        assert record.force_field_type == FFType.BULK_FF_GAFF2
        assert record.status == ExperimentStatus.PENDING
        assert record.run_tier == RunTier.SCREENING

    def test_experiment_record_full(self):
        record = ExperimentRecord(
            exp_id="binderA_bulk_ff_screening_T298K_SBS_5wt",
            material_id="binderA",
            force_field_type=FFType.BULK_FF_GAFF2,
            force_field_name="GAFF2",
            force_field_version="1.0",
            study_type="bulk",
            run_tier=RunTier.SCREENING,
            temperature_k=298.0,
            pressure_atm=1.0,
            target_atoms=100000,
            validity_domain_tag=[ValidityDomainTag.BULK_GAFF2_OK],
            status=ExperimentStatus.COMPLETED,
        )
        assert record.status == ExperimentStatus.COMPLETED


class TestLAMMPSSchemas:
    """Test LAMMPS execution schemas."""

    def test_lammps_run_result_success(self):
        result = LAMMPSRunResult(
            success=True,
            log_file="/path/to/log.lammps",
            dump_files=["/path/to/dump.1.lammpstrj"],
            wall_time_seconds=3600.0,
            exit_code=0,
        )
        assert result.success is True
        assert result.error_message is None

    def test_lammps_run_result_failure(self):
        result = LAMMPSRunResult(
            success=False,
            log_file="/path/to/log.lammps",
            wall_time_seconds=100.0,
            exit_code=1,
            error_message="LAMMPS crashed: lost atoms",
        )
        assert result.success is False
        assert "lost atoms" in result.error_message


class TestThermoData:
    """Test thermo data schema."""

    def test_thermo_data(self):
        data = ThermoData(
            step=[0, 1000, 2000],
            time_ps=[0.0, 1.0, 2.0],
            temperature=[300.0, 298.5, 298.2],
            pressure=[1.0, 1.1, 0.9],
            total_energy=[-1000.0, -1001.0, -1002.0],
            kinetic_energy=[500.0, 498.0, 497.0],
            potential_energy=[-1500.0, -1499.0, -1499.0],
            volume=[100000.0, 99990.0, 99985.0],
            density=[1.0, 1.001, 1.002],
        )
        assert len(data.step) == 3
        assert data.temperature[0] == 300.0


class TestErrors:
    """Test error classes."""

    def test_contract_error(self):
        error = ContractError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid input",
            details={"field": "composition"},
        )
        assert error.code == ErrorCode.VALIDATION_ERROR
        assert "E1000" in str(error)

    def test_composition_error(self):
        error = CompositionError(
            code=ErrorCode.COMPOSITION_SUM_ERROR,
            message="Sum != 100",
            composition={"a": 50, "b": 60},
        )
        assert error.details["composition"]["a"] == 50

    def test_error_to_dict(self):
        error = ValidationError("Test error")
        error_dict = error.to_dict()
        assert error_dict["code"] == "E1000"
        assert error_dict["message"] == "Test error"


class TestInterfaces:
    """Test that interfaces can be used for type checking."""

    def test_builder_interface_protocol(self):
        # This class should satisfy IStructureBuilder
        class MockBuilder:
            def build(self, request: BuildRequest) -> BuildResult:
                return BuildResult(
                    data_file_path="/mock/data.lammps",
                    actual_atoms=100000,
                    actual_density=1.0,
                    topology_hash="mock123",
                    packmol_version="mock",
                    actual_composition_wt={},
                    composition_error_l1=0.0,
                    target_composition_wt={},
                    min_distance_violation_count=0,
                    initial_pe_per_atom=-5.0,
                )

        builder = MockBuilder()
        assert isinstance(builder, IStructureBuilder)

    def test_e_intra_store_interface(self):
        class MockEIntraStore:
            def get(self, key: EIntraKey):
                return None

            def put(self, key: EIntraKey, value: EIntraValue):
                pass

            def has(self, key: EIntraKey):
                return False

        store = MockEIntraStore()
        assert isinstance(store, IEIntraStore)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
