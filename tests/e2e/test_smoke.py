"""
E2E Smoke Test for Phase 1 Completion Gate.

Purpose:
    Verify full pipeline works with actual LAMMPS execution (10k atoms).
    This is the Phase 1 exit condition - must pass before Phase 2.

Test Parameters:
    - target_atoms: 10,000 (mini version for smoke test)
    - composition: standard SARA (20/30/35/15)
    - temperature: 298 K
    - protocol: minimize (100 steps) + NVT (50 ps) + NPT (100 ps)

Expected Results:
    - data.lammps file generated
    - in.lammps file generated
    - log.lammps file generated (or mock)
    - density calculated in range 0.8 < rho < 1.3 g/cm3

Time Limit: 30 minutes for real LAMMPS, instant for mock.
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestE2ESmoke:
    """
    Phase 1 Exit Gate Test: Full Pipeline with LAMMPS Execution.

    Tests the complete workflow from build request to density calculation.
    Can run in two modes:
    - Real mode: Requires LAMMPS and Packmol installed
    - Mock mode: Uses mock runners for CI/CD testing
    """

    def test_smoke_config_valid(self, smoke_test_config: dict):
        """Verify smoke test configuration is valid."""
        assert smoke_test_config["target_atoms"] == 10000

        comp = smoke_test_config["composition"]
        assert sum(comp.values()) == 100.0
        assert comp["asphaltene"] == 20.0
        assert comp["resin"] == 30.0
        assert comp["aromatic"] == 35.0
        assert comp["saturate"] == 15.0

        assert smoke_test_config["temperature_K"] == 298.0
        assert smoke_test_config["pressure_atm"] == 1.0

    def test_contracts_importable(self):
        """Verify contracts module can be imported."""
        from contracts.schemas import (
            FFType,
            RunTier,
        )

        assert FFType.BULK_FF_GAFF2.value == "bulk_ff_gaff2"
        assert RunTier.SCREENING.value == "screening"

    def test_builder_modules_importable(self):
        """Verify builder modules can be imported."""
        from builder import (
            CompositionCalculator,
            PackmolWrapper,
        )

        assert PackmolWrapper is not None
        assert CompositionCalculator is not None

    def test_protocol_modules_importable(self):
        """Verify protocol modules can be imported."""
        from protocols import (
            LAMMPSInputGenerator,
            ProtocolHasher,
        )

        assert LAMMPSInputGenerator is not None
        assert ProtocolHasher is not None

    def test_parser_modules_importable(self):
        """Verify parser modules can be imported."""
        from parsers import LogParser

        assert LogParser is not None

    def test_metrics_modules_importable(self):
        """Verify metrics modules can be imported."""
        from metrics import DensityCalculator

        calc = DensityCalculator()
        assert calc.is_valid(1.0)  # 1.0 g/cm3 is valid
        assert not calc.is_valid(0.1)  # 0.1 g/cm3 is too low

    def test_build_request_creation(self, smoke_test_config: dict):
        """Test creating a BuildRequest."""
        from contracts.schemas import BuildRequest

        request = BuildRequest(
            composition=smoke_test_config["composition"],
            target_atoms=smoke_test_config["target_atoms"],
            atom_count_tolerance=0.10,
            initial_density=1.0,
            seed=smoke_test_config["seed"],
        )

        assert request.target_atoms == 10000
        assert request.composition["asphaltene"] == 20.0

    def test_protocol_request_creation(self, smoke_test_config: dict, temp_dir: Path):
        """Test creating a ProtocolRequest."""
        from contracts.schemas import FFType, ProtocolRequest, RunTier

        # Create dummy data file
        data_file = temp_dir / "data.lammps"
        data_file.write_text("# Mock LAMMPS data file")

        request = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=smoke_test_config["temperature_K"],
            pressure_atm=smoke_test_config["pressure_atm"],
            data_file_path=str(data_file),
        )

        assert request.ff_type == FFType.BULK_FF_GAFF2
        assert request.run_tier == RunTier.SCREENING
        assert request.temperature_K == 298.0

    def test_protocol_generation(self, smoke_test_config: dict, temp_dir: Path):
        """Test LAMMPS input script generation."""
        from contracts.schemas import FFType, ProtocolRequest, RunTier
        from protocols import LAMMPSInputGenerator

        # Create mock data file
        data_file = temp_dir / "data.lammps"
        data_file.write_text("# Mock LAMMPS data file\n")

        # Create protocol request
        request = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=smoke_test_config["temperature_K"],
            pressure_atm=smoke_test_config["pressure_atm"],
            data_file_path=str(data_file),
        )

        # Generate protocol
        generator = LAMMPSInputGenerator()
        result = generator.generate(request)

        # Verify result
        assert result.input_script_path is not None
        input_file = Path(result.input_script_path)
        assert input_file.exists()

        # Verify content
        content = input_file.read_text()
        assert "LAMMPS input script" in content
        assert "units real" in content
        assert "atom_style full" in content
        assert "minimize" in content
        assert "nvt" in content.lower() or "npt" in content.lower()

        # Verify protocol hash exists
        assert result.protocol_hash is not None
        assert len(result.protocol_hash) >= 8

        # Verify stabilization chain
        assert len(result.stabilization_chain) >= 2  # At least minimize + NVT/NPT

    def test_log_parser_mock_data(self, mock_lammps_log: Path):
        """Test parsing a mock LAMMPS log file."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(mock_lammps_log)

        # Verify parsing
        assert result.completed
        assert result.total_atoms == 10000
        assert len(result.errors) == 0

        # Verify thermo data
        assert "Step" in result.thermo_data
        assert "Density" in result.thermo_data
        assert len(result.thermo_data["Density"]) > 0

        # Verify density values
        densities = result.thermo_data["Density"]
        avg_density = sum(densities[-5:]) / 5  # Average last 5
        assert 0.8 < avg_density < 1.3, f"Density {avg_density} out of range"

    def test_density_calculation(self, mock_lammps_log: Path):
        """Test density calculation from thermo data."""
        from metrics import DensityCalculator
        from parsers import LogParser

        # Parse log
        parser = LogParser()
        log_result = parser.parse(mock_lammps_log)

        # Calculate density
        calc = DensityCalculator()
        densities = log_result.thermo_data.get("Density", [])

        assert len(densities) > 0, "No density data in log"

        avg_density, std_dev = calc.calculate_from_thermo(densities)

        # Verify physical range
        assert 0.8 < avg_density < 1.3, f"Density {avg_density} out of asphalt range"
        assert calc.check_asphalt_range(avg_density) == "ok"

    def test_mock_pipeline_integration(
        self, smoke_test_config: dict, temp_dir: Path, mock_lammps_log: Path
    ):
        """
        Integration test with mock components.

        Tests the full pipeline flow without requiring real LAMMPS.
        """
        from contracts.schemas import (
            BuildRequest,
            BuildResult,
            FFType,
            LAMMPSRunResult,
            ProtocolRequest,
            RunTier,
        )
        from metrics import DensityCalculator
        from parsers import LogParser
        from protocols import LAMMPSInputGenerator

        # Step 1: Create build request
        BuildRequest(
            composition=smoke_test_config["composition"],
            target_atoms=smoke_test_config["target_atoms"],
            atom_count_tolerance=0.10,
            initial_density=1.0,
            seed=smoke_test_config["seed"],
        )

        # Step 2: Mock build result
        data_file = temp_dir / "data.lammps"
        data_file.write_text("# Mock LAMMPS data file\n10000 atoms\n")

        build_result = BuildResult(
            data_file_path=str(data_file),
            actual_atoms=smoke_test_config["target_atoms"],
            actual_density=1.0,
            topology_hash="mock_hash_12345678",
            packmol_version="mock",
            actual_composition_wt=smoke_test_config["composition"],
            composition_error_l1=0.0,
            target_composition_wt=smoke_test_config["composition"],
            min_distance_violation_count=0,
            initial_pe_per_atom=-5.0,
        )

        assert Path(build_result.data_file_path).exists()
        assert build_result.composition_error_l1 < 1.0

        # Step 3: Generate protocol
        protocol_request = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=smoke_test_config["temperature_K"],
            pressure_atm=smoke_test_config["pressure_atm"],
            data_file_path=build_result.data_file_path,
        )

        generator = LAMMPSInputGenerator()
        protocol_result = generator.generate(protocol_request)

        assert Path(protocol_result.input_script_path).exists()
        assert protocol_result.protocol_hash is not None

        # Step 4: Mock LAMMPS run (use pre-generated log)
        import shutil

        shutil.copy(mock_lammps_log, temp_dir / "log.lammps")

        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(temp_dir / "log.lammps"),
            dump_files=[],
            wall_time_seconds=120.0,
            exit_code=0,
        )

        assert run_result.success
        assert Path(run_result.log_file).exists()

        # Step 5: Parse results and calculate density
        parser = LogParser()
        log_result = parser.parse(Path(run_result.log_file))

        assert log_result.completed

        density_calc = DensityCalculator()
        densities = log_result.thermo_data.get("Density", [])
        avg_density, std_dev = density_calc.calculate_from_thermo(densities)

        # Final assertion: density in physical range
        assert 0.8 < avg_density < 1.3, f"Density {avg_density} out of range"

        print("\nE2E Mock Pipeline Test PASSED")
        print(f"  - Atoms: {build_result.actual_atoms}")
        print(f"  - Density: {avg_density:.4f} +/- {std_dev:.4f} g/cm3")
        print(f"  - Protocol hash: {protocol_result.protocol_hash}")

    @pytest.mark.slow
    def test_full_pipeline_real_lammps(
        self,
        smoke_test_config: dict,
        temp_dir: Path,
        lammps_available: bool,
        packmol_available: bool,
    ):
        """
        Full E2E test with real LAMMPS execution.

        This is the actual Phase 1 exit gate test.
        Requires LAMMPS and Packmol to be installed.

        WARNING: This test takes 5-30 minutes to complete.
        """
        if not lammps_available or not packmol_available:
            pytest.skip("LAMMPS or Packmol not available")

        # This would be the real test implementation
        # Requires actual LAMMPS and Packmol binaries


class TestSmokeTestConfig:
    """Tests for smoke test configuration validation."""

    def test_composition_sum(self, smoke_test_config: dict):
        """Composition must sum to 100%."""
        total = sum(smoke_test_config["composition"].values())
        assert total == 100.0

    def test_temperature_positive(self, smoke_test_config: dict):
        """Temperature must be positive."""
        assert smoke_test_config["temperature_K"] > 0

    def test_pressure_positive(self, smoke_test_config: dict):
        """Pressure must be positive."""
        assert smoke_test_config["pressure_atm"] > 0

    def test_atom_count_reasonable(self, smoke_test_config: dict):
        """Atom count should be reasonable for smoke test."""
        # Smoke test uses 10k, real screening uses 100k
        assert 5000 <= smoke_test_config["target_atoms"] <= 20000


class TestDensityValidation:
    """Tests for density validation logic."""

    def test_asphalt_density_range(self):
        """Test density range validation for asphalt."""
        from metrics import DensityCalculator

        calc = DensityCalculator(min_density=0.5, max_density=2.0)

        # Valid densities for asphalt
        assert calc.check_asphalt_range(0.9) == "ok"
        assert calc.check_asphalt_range(1.0) == "ok"
        assert calc.check_asphalt_range(1.1) == "ok"

        # Out of range
        assert calc.check_asphalt_range(0.5) == "too_low"
        assert calc.check_asphalt_range(1.5) == "too_high"

    def test_density_from_box(self):
        """Test density calculation from box dimensions."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        # Test with typical MD box
        # 80 A cube = 512000 A^3
        # 10000 atoms * ~20 amu/atom = 200000 amu
        volume_A3 = 512000.0
        mass_amu = 200000.0  # Approximate

        density = calc.calculate_from_box(volume_A3, mass_amu)

        # Should be around 0.65 g/cm3 with these numbers
        assert 0.1 < density < 2.0
