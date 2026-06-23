"""Tests for LAMMPS input generator."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
from protocols.lammps_input import LAMMPSInputGenerator


class TestLAMMPSInputGenerator:
    """Test LAMMPS input generator."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    @pytest.fixture
    def basic_request(self):
        return ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/data.lammps",
        )

    def test_generate_creates_file(self, generator, basic_request, temp_dir):
        """Test that generate creates output file."""
        output_path = temp_dir / "in.lammps"
        result = generator.generate_to_path(basic_request, output_path)

        assert output_path.exists()
        assert result.input_script_path == str(output_path)

    def test_generate_returns_result(self, generator, basic_request, temp_dir):
        """Test that generate returns proper result."""
        output_path = temp_dir / "in.lammps"
        result = generator.generate_to_path(basic_request, output_path)

        assert result.protocol_hash is not None
        assert len(result.protocol_hash) == 8
        assert len(result.stabilization_chain) > 0

    def test_script_has_header(self, generator, basic_request, temp_dir):
        """Test that script has proper header."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "LAMMPS input script" in content
        assert "Tier: screening" in content
        assert "units real" in content

    def test_script_has_force_field(self, generator, basic_request, temp_dir):
        """Test that script has force field setup."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "pair_style" in content

    def test_script_reads_data(self, generator, temp_dir):
        """Test that script reads data file."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/path/to/system.data",
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)

        content = output_path.read_text()
        assert "read_data system.data" in content

    def test_script_has_minimize(self, generator, basic_request, temp_dir):
        """Test that script has minimization."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "minimize" in content

    def test_script_has_equilibration(self, generator, basic_request, temp_dir):
        """Test that script has equilibration."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "fix" in content
        assert "run" in content

    def test_script_writes_restart(self, generator, basic_request, temp_dir):
        """Test that script writes restart files."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "write_restart" in content

    def test_script_writes_final_data(self, generator, basic_request, temp_dir):
        """Test that script writes final data."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(basic_request, output_path)

        content = output_path.read_text()
        assert "write_data final.data" in content


class TestLAMMPSInputGeneratorTiers:
    """Test different tier configurations."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_screening_tier(self, generator, temp_dir):
        """Test screening tier generation."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        result = generator.generate_to_path(request, output_path)

        assert len(result.stabilization_chain) > 0

    def test_confirm_tier(self, generator, temp_dir):
        """Test confirm tier generation."""
        request = ProtocolRequest(
            run_tier=RunTier.CONFIRM,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        result = generator.generate_to_path(request, output_path)

        assert len(result.stabilization_chain) > 0

    def test_viscosity_tier(self, generator, temp_dir):
        """Test viscosity tier generation."""
        request = ProtocolRequest(
            run_tier=RunTier.VISCOSITY,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)

        # Check for viscosity-related content
        content = output_path.read_text()
        assert "viscosity" in content.lower() or "nemd" in content.lower()


class TestLAMMPSInputGeneratorForceFields:
    """Test different force field configurations."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_gaff2_force_field(self, generator, temp_dir):
        """Test GAFF2 force field generation."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)

        content = output_path.read_text()
        assert "lj/cut/coul/long" in content
        assert "pppm" in content

    def test_reaxff_force_field(self, generator, temp_dir):
        """Test ReaxFF force field generation."""
        request = ProtocolRequest(
            run_tier=RunTier.VALIDATION,
            ff_type=FFType.REAXFF,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)

        content = output_path.read_text()
        assert "reax" in content.lower()


class TestLAMMPSInputGeneratorValidation:
    """Test input validation."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_validate_valid_request(self, generator):
        """Test validation of valid request."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="/path/to/data.lammps",
        )

        errors = generator.validate_request(request)
        assert len(errors) == 0

    def test_validate_missing_data_file(self, generator):
        """Test validation catches missing data file."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        errors = generator.validate_request(request)
        assert len(errors) > 0


class TestLAMMPSInputGeneratorInterface:
    """Test interface compliance."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_implements_interface(self, temp_dir):
        """Test that generator implements IProtocolGenerator."""
        from contracts.interfaces import IProtocolGenerator

        generator = LAMMPSInputGenerator(template_dir=temp_dir / "templates")
        assert isinstance(generator, IProtocolGenerator)

    def test_get_protocol_hash(self, temp_dir):
        """Test get_protocol_hash method."""
        generator = LAMMPSInputGenerator(template_dir=temp_dir / "templates")
        hash_val = generator.get_protocol_hash("screening")

        assert len(hash_val) == 8
        assert isinstance(hash_val, str)

    def test_get_stabilization_chain(self, temp_dir):
        """Test get_stabilization_chain method."""
        generator = LAMMPSInputGenerator(template_dir=temp_dir / "templates")
        chain = generator.get_stabilization_chain("screening")

        assert len(chain) > 0
        assert all(isinstance(s, str) for s in chain)


class TestAnnealingGeneration:
    """Test annealing cycle LAMMPS script generation."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_annealing_script_generation(self, generator, temp_dir):
        """_generate_annealing produces correct cycle structure."""
        from protocols.protocol_chain import ProtocolStep

        step = ProtocolStep(
            name="annealing_cycles",
            step_type="annealing",
            ensemble="nvt",
            temperature_K=298.0,
            duration="1000 ps",
            extra_params={
                "n_cycles": 3,
                "temp_high_K": 500.0,
                "temp_low_K": 298.0,
                "tdamp": 100.0,
                "duration_per_half_cycle_ps": 100.0,
            },
        )
        script = generator._generate_annealing(step, step_index=2)

        # Check cycle count: 3 cycles × 2 half-cycles = 6 fix/unfix pairs
        assert script.count("unfix anneal_heat_2_") == 3
        assert script.count("unfix anneal_cool_2_") == 3
        # Each fix appears twice (fix + unfix), so 6 total per type
        assert script.count("anneal_heat_2_") == 6  # 3 fix + 3 unfix
        assert script.count("anneal_cool_2_") == 6

        # Check temperature ramping
        assert "298.0 500.0" in script  # heating
        assert "500.0 298.0" in script  # cooling

        # Check run steps (100 ps = 100000 steps at dt=1.0)
        assert "run 100000" in script
        # Annealing must NOT reset timestep — step counter continues for progress tracking
        assert "reset_timestep" not in script

    def test_annealing_has_dump_restart_checkpoint(self, generator, temp_dir):
        """_generate_annealing includes dump/undump/write_restart/checkpoint."""
        from protocols.protocol_chain import ProtocolStep

        step = ProtocolStep(
            name="annealing_cycles",
            step_type="annealing",
            ensemble="nvt",
            temperature_K=298.0,
            duration="1000 ps",
            extra_params={
                "n_cycles": 3,
                "temp_high_K": 500.0,
                "temp_low_K": 298.0,
                "tdamp": 100.0,
                "duration_per_half_cycle_ps": 100.0,
            },
        )
        script = generator._generate_annealing(step, step_index=2)

        # dump command before cycle loop
        assert "dump d_2 all custom" in script
        assert "dump_annealing_cycles.lammpstrj" in script

        # undump + write_restart after cycle loop
        assert "undump d_2" in script
        assert "write_restart restart.annealing_cycles" in script

    def test_tensile_layer_full_script(self, generator, temp_dir):
        """tensile_layer generates 7-step script with annealing."""
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        # Create dummy data file
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        result = generator.generate_to_path(request, output_path)

        script = output_path.read_text()
        assert "Step 1: minimize" in script
        assert "Step 2: high_temp_nvt" in script
        assert "Step 3: annealing_cycles" in script
        assert "Step 4: nvt_equilibration" in script
        assert "Step 5: npt_equilibration" in script
        assert "Step 6: pre_tensile_nvt" in script
        assert "Step 7: tensile_pull" in script
        assert len(result.stabilization_chain) == 7

    def test_minimize_ssot_params_in_script(self, generator, temp_dir):
        """minimize step uses SSOT etol/ftol/maxiter/maxeval."""
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # SSOT: etol=1e-5, ftol=1e-7, maxiter=50000, maxeval=500000
        assert "minimize 1e-05 1e-07 50000 500000" in script


class TestMixingRuleByStudyType:
    """GAFF2 uses arithmetic (L-B) mixing for both bulk and layered."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_bulk_uses_arithmetic_mixing(self, generator, temp_dir):
        """Bulk study type uses arithmetic (L-B) mixing for GAFF2."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "pair_modify mix arithmetic" in script

    def test_layer_uses_arithmetic_mixing(self, generator, temp_dir):
        """LAYER_BULKFF uses arithmetic (L-B) mixing for INTERFACE FF compat."""
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "pair_modify mix arithmetic" in script
        assert "pair_modify mix geometric" not in script
        assert "INTERFACE FF" in script  # comment indicates IFF usage

    def test_layer_script_still_has_lj_coulomb(self, generator, temp_dir):
        """Layered script must still use lj/cut/coul/long pair_style."""
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "pair_style lj/cut/coul/long 12.0" in script
        assert "kspace_style pppm" in script


class TestKspaceSlab:
    """kspace_modify slab 3.0 for layered structures only."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_layer_has_kspace_slab_correction(self, generator, temp_dir):
        """LAYER_BULKFF + charged → kspace_modify slab 3.0 must be present."""
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "kspace_modify slab 3.0" in script

    def test_bulk_no_kspace_slab_correction(self, generator, temp_dir):
        """BULK → kspace_modify slab must NOT be present."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "kspace_modify slab" not in script


class TestWave1LayeredCombinedRegression:
    """Wave 1: lock the LAYER_BULKFF runtime contract in one combined check.

    The plan v3 calls out three things that must NEVER drift in a layered
    build because they would silently invalidate the silica/binder
    interface physics:

    1. ``pair_modify mix arithmetic`` (Lorentz-Berthelot) — required by
       INTERFACE FF (Heinz 2013) for organic-mineral cross interactions.
    2. ``kspace_modify slab 3.0`` — required for Yeh-Berkowitz slab Ewald
       correction in p p f boundary layered builds.
    3. ``pair_style lj/cut/coul/long`` — long-range Coulomb is mandatory
       for the silica surface that is dominated by partial charges.

    These are individually checked in older test classes, but Wave 1 adds
    one combined regression so any future template change that touches
    layered protocols has a single failing test that explains *why*.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def _emit_layer_script(self, generator, temp_dir):
        from contracts.schemas import StudyType, TensileSpec

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        return output_path.read_text()

    def test_layered_script_locks_all_three_contracts(self, generator, temp_dir):
        script = self._emit_layer_script(generator, temp_dir)

        # 1. Mixing rule: arithmetic for organic-inorganic interfaces
        assert "pair_modify mix arithmetic" in script, (
            "LAYER_BULKFF must use arithmetic mixing per INTERFACE FF "
            "(Heinz 2013); geometric mixing breaks the silica-binder "
            "cross interaction physics."
        )
        assert "pair_modify mix geometric" not in script

        # 2. Slab Ewald correction for p p f boundary
        assert "kspace_modify slab 3.0" in script, (
            "LAYER_BULKFF must invoke Yeh-Berkowitz slab correction (slab 3.0) "
            "because the box has p p f boundaries; without it the long-range "
            "Coulomb sums are biased by the periodic image stack."
        )

        # 3. Long-range Coulomb pair style required for charged silica
        assert "pair_style lj/cut/coul/long 12.0" in script, (
            "LAYER_BULKFF must use lj/cut/coul/long because the silica "
            "surface charges dominate the interface energy; lj/cut alone "
            "would drop the Coulomb contribution."
        )
        assert "kspace_style pppm" in script

    def test_bulk_script_does_not_pull_in_layered_overrides(self, generator, temp_dir):
        """The opposite contract: a BULK build must keep GAFF2 defaults
        and never pick up the layered slab overrides."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # GAFF2 uses arithmetic mixing for both bulk and layer
        assert "pair_modify mix arithmetic" in script
        assert "kspace_modify slab" not in script


class TestWave1InterfaceFfMineralLockdown:
    """Wave 1: lock the INTERFACE FF mineral element parameters in place.

    These values come from Heinz et al. (Langmuir 2013, 29, 1754) and
    Emami et al. (Chem. Mater. 2014, 26, 2647). They are intentionally
    *not* the UFF defaults — INTERFACE FF Si has ε ≈ 0.0004 kcal/mol,
    roughly 1000× smaller than UFF — because the silica surface is
    dominated by Coulomb interactions, not LJ. If a future refactor
    silently swaps these for UFF/element fallback values, the silica
    interface physics will break and validation papers will not
    reproduce. This is the wall.
    """

    def test_silica_si_epsilon_is_interface_ff_value(self):
        from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS

        si = INTERFACE_FF_MINERAL_PARAMS["Si"]
        assert si["sigma"] == pytest.approx(3.302, abs=1e-4)
        assert si["epsilon"] == pytest.approx(0.00040, abs=1e-6), (
            "INTERFACE FF Si epsilon must remain 0.00040 kcal/mol "
            "(Emami 2014, Heinz 2013); UFF Si is 0.402 — a 1000× error "
            "that would silently break silica/binder interfacial energy."
        )

    def test_silica_o_epsilon_is_interface_ff_value(self):
        from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS

        o = INTERFACE_FF_MINERAL_PARAMS["O"]
        assert o["sigma"] == pytest.approx(3.166, abs=1e-4)
        assert o["epsilon"] == pytest.approx(0.15540, abs=1e-5)

    def test_carbonate_calcite_anchors_present(self):
        """Calcite (Ca, C, O) is the second mineral the codebase
        currently supports for layered builds. Lock its anchors so a
        future refactor cannot accidentally drop calcite coverage."""
        from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS

        for element in ("Ca", "Mg", "C", "O"):
            assert element in INTERFACE_FF_MINERAL_PARAMS, (
                f"INTERFACE FF must keep {element} for calcite/carbonate layered builds"
            )

    def test_unknown_mineral_element_is_not_silently_added(self):
        """Defense in depth: if a developer adds a new mineral element,
        they must update the catalog explicitly. The catalog is the SSOT.
        """
        from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS

        # Lock the *current* set so additions are visible in the diff.
        expected_minimal_set = {
            "Si",
            "O",
            "Al",
            "Ti",
            "Fe",
            "Zn",
            "C",
            "Ca",
            "Mg",
            "Na",
            "K",
            "Cl",
            "Cu",
            "Ni",
            "H",
        }
        missing = expected_minimal_set - set(INTERFACE_FF_MINERAL_PARAMS.keys())
        assert not missing, f"INTERFACE FF dropped expected mineral elements: {sorted(missing)}"


class TestAnnealingOrganicGroup:
    """Annealing uses organic group when crystal atoms are frozen."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_annealing_uses_organic_group_with_crystal(self, generator):
        """When crystal_type_ids set + LAYER_BULKFF, annealing fix uses 'organic' group."""
        from contracts.schemas import StudyType
        from protocols.protocol_chain import ProtocolStep

        generator._crystal_type_ids = {1, 2}

        step = ProtocolStep(
            name="annealing_cycles",
            step_type="annealing",
            ensemble="nvt",
            temperature_K=298.0,
            duration="1000 ps",
            extra_params={
                "n_cycles": 2,
                "temp_high_K": 500.0,
                "temp_low_K": 298.0,
                "tdamp": 100.0,
                "duration_per_half_cycle_ps": 100.0,
            },
        )
        script = generator._generate_annealing(
            step, step_index=2, study_type=StudyType.LAYER_BULKFF
        )

        assert "organic nvt" in script
        assert "all nvt" not in script

    def test_annealing_uses_all_group_without_crystal(self, generator):
        """Without crystal_type_ids, annealing fix uses 'all' group."""
        from protocols.protocol_chain import ProtocolStep

        generator._crystal_type_ids = set()

        step = ProtocolStep(
            name="annealing_cycles",
            step_type="annealing",
            ensemble="nvt",
            temperature_K=298.0,
            duration="1000 ps",
            extra_params={
                "n_cycles": 2,
                "temp_high_K": 500.0,
                "temp_low_K": 298.0,
                "tdamp": 100.0,
                "duration_per_half_cycle_ps": 100.0,
            },
        )
        script = generator._generate_annealing(step, step_index=2)

        assert "all nvt" in script


class TestTensileCrystalGripRegions:
    """Test explicit crystal grip z-range in LAMMPS region definitions."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_tensile_crystal_grip_regions(self, generator):
        """Explicit grip z-range → LAMMPS region uses those coordinates."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={
                "pull_velocity_A_per_fs": 0.0001,
                "grip_thickness_angstrom": 20.0,
                "output_interval_steps": 100,
                "z_lo_grip": 0.0,
                "z_hi_grip": 100.0,
                "bottom_grip_z": (0.0, 12.0),
                "top_grip_z": (88.0, 100.0),
            },
        )
        from contracts.schemas import StudyType

        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        script = generator._generate_tensile(step, step_index=6, chain=chain)

        assert "0.0000 12.0000" in script  # bottom grip
        assert "88.0000 100.0000" in script  # top grip
        # original_gap = 88 - 12 = 76
        assert "76.0000" in script

    def test_tensile_thickness_grip_fallback(self, generator):
        """No explicit range → falls back to grip_thickness."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={
                "pull_velocity_A_per_fs": 0.0001,
                "grip_thickness_angstrom": 20.0,
                "output_interval_steps": 100,
                "z_lo_grip": 0.0,
                "z_hi_grip": 100.0,
            },
        )
        from contracts.schemas import StudyType

        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        script = generator._generate_tensile(step, step_index=6, chain=chain)

        # bottom: 0.0000 → 20.0000, top: 80.0000 → 100.0000
        assert "0.0000 20.0000" in script
        assert "80.0000 100.0000" in script
        # gap = 80 - 20 = 60
        assert "60.0000" in script

    def test_tensile_mixed_grip_mode(self, generator):
        """One explicit + one thickness → mixed regions and gap."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={
                "pull_velocity_A_per_fs": 0.0001,
                "grip_thickness_angstrom": 20.0,
                "output_interval_steps": 100,
                "z_lo_grip": 0.0,
                "z_hi_grip": 100.0,
                "bottom_grip_z": (0.0, 10.0),
                # top: fallback → 80..100
            },
        )
        from contracts.schemas import StudyType

        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        script = generator._generate_tensile(step, step_index=6, chain=chain)

        assert "0.0000 10.0000" in script  # explicit bottom
        assert "80.0000 100.0000" in script  # fallback top
        # gap = 80 - 10 = 70
        assert "70.0000" in script


class TestTensileResetTimestep:
    """Tensile block starts with reset_timestep 0."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_tensile_starts_with_reset_timestep(self, generator):
        """Tensile output must contain reset_timestep 0 before timestep command."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={
                "pull_velocity_A_per_fs": 0.0001,
                "grip_thickness_angstrom": 20.0,
                "output_interval_steps": 100,
                "z_lo_grip": 0.0,
                "z_hi_grip": 100.0,
            },
        )
        from contracts.schemas import StudyType

        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        script = generator._generate_tensile(step, step_index=5, chain=chain)

        lines = script.split("\n")
        # Find reset_timestep and timestep lines
        reset_idx = next(i for i, ln in enumerate(lines) if "reset_timestep 0" in ln)
        ts_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("timestep "))
        assert reset_idx < ts_idx


class TestCrystalFreezeRedesign:
    """Crystal freeze 2-phase redesign: spring/self → rigid freeze → grip handoff."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def _make_layered_data_file(self, path: Path) -> None:
        """Create minimal data file with crystal atom type annotation."""
        path.write_text("# Crystal atom types: 1 2 3\n0 atoms\n0 bonds\n")

    def test_header_has_spring_self_not_freeze(self, generator, temp_dir):
        """Layered + crystal types → header has spring/self, no setforce freeze."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        self._make_layered_data_file(data_path)

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Phase 1: spring/self in header
        assert "fix restrain_crystal crystal spring/self 50.0" in script
        # No immediate setforce freeze in header area
        header_end = script.index("# Step 1:")
        header = script[:header_end]
        assert "setforce 0.0 0.0 0.0" not in header
        assert "velocity crystal set 0.0 0.0 0.0" not in header

    def test_pre_tensile_transition(self, generator, temp_dir):
        """pre_tensile_nvt step has unfix restrain + fix freeze transition."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        self._make_layered_data_file(data_path)

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Phase 2: transition before pre_tensile_nvt
        pre_tensile_idx = script.index("pre_tensile_nvt")
        transition_section = script[pre_tensile_idx:]

        assert "unfix restrain_crystal" in transition_section
        assert "fix freeze_crystal crystal setforce 0.0 0.0 0.0" in transition_section
        assert "velocity crystal set 0.0 0.0 0.0" in transition_section

        # unfix restrain comes before fix freeze
        unfix_pos = transition_section.index("unfix restrain_crystal")
        fix_pos = transition_section.index("fix freeze_crystal")
        assert unfix_pos < fix_pos

    def test_tensile_unfix_freeze(self, generator, temp_dir):
        """tensile step has unfix freeze_crystal before grip setup."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        self._make_layered_data_file(data_path)

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Phase 3: unfix in tensile step
        tensile_idx = script.index("Tensile pull test")
        tensile_section = script[tensile_idx:]

        assert "unfix freeze_crystal" in tensile_section

        # unfix freeze_crystal comes before grip definitions
        unfix_pos = tensile_section.index("unfix freeze_crystal")
        grip_pos = tensile_section.index("fix freeze_bottom")
        assert unfix_pos < grip_pos

    def test_no_crystal_no_restraint(self, generator, temp_dir):
        """No crystal annotation → no spring/self or freeze commands."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("0 atoms\n0 bonds\n")  # No crystal annotation

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "spring/self" not in script
        assert "restrain_crystal" not in script
        assert "freeze_crystal" not in script

    def test_bulk_study_type_all_group(self, generator, temp_dir):
        """BULK study type + crystal_type_ids → thermo_group still 'all'."""
        from contracts.schemas import StudyType
        from protocols.protocol_chain import ProtocolChain

        generator._crystal_type_ids = {1, 2}
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.BULK,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[],
        )
        assert generator._thermo_group(StudyType.BULK) == "all"
        assert not generator._has_crystal_freeze(chain)


class TestLayeredExpIdRoundtrip:
    """Layered exp_id produces standard 6-part format that roundtrips."""

    def test_exp_id_six_parts(self):
        """Layered exp_id is standard 6-part format."""
        from common.pathing import generate_exp_id

        exp_id = generate_exp_id(
            binder_type="custom",
            structure_size="X1",
            temperature_k=298.0,
            additive="SiO2",
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
        )
        assert len(exp_id.split("_")) == 6

    def test_exp_id_roundtrip(self):
        """parse_exp_id roundtrip for layered exp_id."""
        from common.pathing import generate_exp_id, parse_exp_id

        exp_id = generate_exp_id(
            binder_type="AAA1",
            structure_size="X1",
            temperature_k=433.0,
            additive="SiO2",
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
        )
        parsed = parse_exp_id(exp_id)
        assert parsed["additive"] == "SiO2"
        assert parsed["binder_type"] == "A1"
        assert parsed["temperature_k"] == 433.0


class TestQuasiStaticTensileScript:
    """Test quasi-static decohesion LAMMPS script generation."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    @pytest.fixture
    def qs_request(self):
        from contracts.schemas import (
            LayerSpec,
            StudyType,
            TensileMode,
            TensileSpec,
        )

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
                max_strain=0.5,
                grip_thickness_angstrom=20.0,
            ),
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 20.0, 80.0, 100.0],
                bottom_grip_z_range=(0.0, 20.0),
                top_grip_z_range=(80.0, 100.0),
            ),
        )

    def test_qs_script_has_loop(self, generator, qs_request, temp_dir):
        """QS script contains variable loop structure."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "variable i loop" in content
        assert "label qs_loop" in content
        assert "next i" in content
        assert "jump SELF qs_loop" in content

    def test_qs_script_has_displace(self, generator, qs_request, temp_dir):
        """QS script displaces top grip atoms."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "displace_atoms grip_top move 0.0 0.0 0.5" in content

    def test_qs_script_has_ave_time(self, generator, qs_request, temp_dir):
        """QS script uses fix ave/time for force averaging."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "ave/time" in content

    def test_qs_script_has_hold_top(self, generator, qs_request, temp_dir):
        """QS script uses fix move linear to hold top grip."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "fix hold_top grip_top move linear 0.0 0.0 0.0" in content

    def test_qs_script_has_print_stress_strain(self, generator, qs_request, temp_dir):
        """QS script prints stress-strain data."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "stress_strain_" in content
        assert "qs_strain" in content
        assert "qs_stress" in content

    def test_qs_n_disp_steps_correct(self, generator, qs_request, temp_dir):
        """Number of displacement steps computed correctly."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        # gap=80-20=60, max_disp=60*0.5=30, n_steps=ceil(30/0.5)=60
        assert "variable i loop 60" in content

    def test_qs_small_gap_minimum_one_step(self, generator, temp_dir):
        """Small gap ensures at least 1 displacement step."""
        from contracts.schemas import LayerSpec, StudyType, TensileMode, TensileSpec

        request = ProtocolRequest(
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
                max_strain=0.1,
                grip_thickness_angstrom=20.0,
            ),
            layer_spec=LayerSpec(
                layer_boundary_z=[0.0, 20.0, 22.0, 42.0],
                bottom_grip_z_range=(0.0, 20.0),
                top_grip_z_range=(22.0, 42.0),
            ),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        content = output_path.read_text()
        # gap=2, max_disp=0.2 < disp_inc=0.5 → ceil(0.2/0.5)=1
        assert "variable i loop 1" in content
        assert "variable i loop 0" not in content
        # effective_disp_inc = 0.2/1 = 0.2 → max_strain reached exactly
        assert "displace_atoms grip_top move 0.0 0.0 0.2" in content

    def test_qs_thermo_uses_step_interval(self, generator, qs_request, temp_dir):
        """QS thermo matches step.thermo_interval, not output_every."""
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(qs_request, output_path)
        content = output_path.read_text()
        assert "thermo 1000" in content


class TestVelocityCreate:
    """Test velocity create after minimize step."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_bulk_velocity_create_after_minimize(self, generator, temp_dir):
        """Bulk: velocity all create at target temperature, after minimize."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Bulk uses target temperature (298.0), not 10K
        assert "velocity all create 298.0" in script
        assert "velocity all create 10.0" not in script
        # velocity create must come after minimize and before first dynamics
        min_idx = script.index("minimize")
        vel_idx = script.index("velocity all create")
        assert vel_idx > min_idx

    def test_layered_velocity_create_organic_group(self, generator, temp_dir):
        """Layered: velocity organic create is used."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "velocity organic create 10.0" in script
        assert "velocity all create" not in script

    def test_layered_velocity_create_at_10K(self, generator, temp_dir):
        """Layered velocity create is 10K regardless of target temperature."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "create 10.0" in script

    def test_bulk_velocity_create_at_target_temp(self, generator, temp_dir):
        """Bulk velocity create uses target temperature, not 10K."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=500.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "velocity all create 500.0" in script
        assert "create 10.0" not in script

    def test_velocity_seed_deterministic(self, generator, temp_dir):
        """Same inputs produce same seed across invocations."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        out1 = temp_dir / "in1.lammps"
        out2 = temp_dir / "in2.lammps"
        generator.generate_to_path(request, out1)
        generator.generate_to_path(request, out2)

        import re

        seeds1 = re.findall(r"velocity all create 298\.0 (\d+)", out1.read_text())
        seeds2 = re.findall(r"velocity all create 298\.0 (\d+)", out2.read_text())
        assert seeds1 == seeds2
        assert len(seeds1) == 1

    def test_velocity_seed_differs_for_different_inputs(self, generator, temp_dir):
        """Different data files produce different seeds."""
        (temp_dir / "a.lammps").write_text("0 atoms\n0 bonds\n")
        (temp_dir / "b.lammps").write_text("0 atoms\n0 bonds\n")

        req_a = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "a.lammps"),
        )
        req_b = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "b.lammps"),
        )

        out_a = temp_dir / "in_a.lammps"
        out_b = temp_dir / "in_b.lammps"
        generator.generate_to_path(req_a, out_a)
        generator.generate_to_path(req_b, out_b)

        import re

        seed_a = re.findall(r"velocity all create 298\.0 (\d+)", out_a.read_text())
        seed_b = re.findall(r"velocity all create 298\.0 (\d+)", out_b.read_text())
        assert seed_a != seed_b

    def test_no_velocity_create_without_dynamics(self, generator):
        """Minimize-only chain produces no velocity create."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="minimize",
            step_type="minimize",
            ensemble="none",
            temperature_K=298.0,
            duration="1000 steps",
            extra_params={"etol": 1e-4, "ftol": 1e-6},
        )
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.BULK,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        content = generator._generate_step(step, chain, 0)
        assert "velocity" not in content


class TestLayeredNVTRamp:
    """Test NVT temperature ramp for layered structures."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_layered_high_temp_nvt_ramps_from_10K(self, generator, temp_dir):
        """Layered high_temp_nvt: NVT ramps from 10K to 500K."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "nvt temp 10.0 500.0" in script

    def test_bulk_nvt_no_ramp(self, generator, temp_dir):
        """Bulk NVT: constant temperature (no ramp)."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "nvt temp 298.0 298.0" in script
        assert "nvt temp 10.0" not in script

    def test_layered_nvt_equilibration_no_ramp(self, generator, temp_dir):
        """Layered nvt_equilibration: constant temperature (no ramp)."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Find nvt_equilibration section — should have temp 298.0 298.0
        nvt_eq_idx = script.index("Step 4: nvt_equilibration")
        nvt_eq_section = script[nvt_eq_idx:]
        # Next step boundary
        next_step_match = nvt_eq_section.find("# Step 5:")
        if next_step_match > 0:
            nvt_eq_section = nvt_eq_section[:next_step_match]

        assert "nvt temp 298.0 298.0" in nvt_eq_section


class TestLayeredNPTCoupleXY:
    """Test NPT couple xy for layered structures."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_layered_npt_has_couple_xy(self, generator, temp_dir):
        """Layered NPT must use 'couple xy' to synchronize in-plane scaling."""
        from contracts.schemas import TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        npt_lines = [
            ln for ln in script.splitlines() if ln.strip().startswith("fix") and "npt" in ln
        ]
        assert npt_lines, "No NPT fix found in layered script"
        for line in npt_lines:
            assert "couple xy" in line, f"Layered NPT missing 'couple xy': {line}"

    def test_bulk_npt_uses_iso(self, generator, temp_dir):
        """Bulk NPT must use 'iso' (no couple xy)."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.BULK,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/data.lammps",
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        npt_lines = [
            ln for ln in script.splitlines() if ln.strip().startswith("fix") and "npt" in ln
        ]
        assert npt_lines, "No NPT fix found in bulk script"
        for line in npt_lines:
            assert "iso" in line, f"Bulk NPT missing 'iso': {line}"
            assert "couple xy" not in line, f"Bulk NPT should not have 'couple xy': {line}"

    def test_layered_npt_pdamp_default(self, generator, temp_dir):
        """Layered NPT must use default pdamp (1000.0) from SSOT."""
        from contracts.schemas import TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        npt_lines = [
            ln for ln in script.splitlines() if ln.strip().startswith("fix") and "npt" in ln
        ]
        for line in npt_lines:
            assert "1000.0" in line, f"Layered NPT pdamp not 1000.0: {line}"


class TestLayeredNeighModify:
    """Test conservative neigh_modify for early layered dynamics steps."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_layered_early_steps_conservative_neigh(self, generator, temp_dir):
        """Steps 2-5 have neigh_modify delay 0 every 1 check yes."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Check that conservative neigh_modify appears in early steps
        for step_name in [
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
        ]:
            step_header = "# Step"
            # Find the section for this step
            step_idx = script.index(step_name)
            section_start = script.rfind(step_header, 0, step_idx)
            # Find next step or end
            next_step_idx = script.find(step_header, step_idx + 1)
            section = (
                script[section_start:next_step_idx] if next_step_idx > 0 else script[section_start:]
            )

            assert "neigh_modify delay 0 every 1 check yes" in section, (
                f"Conservative neigh_modify missing in {step_name}"
            )

    def test_pre_tensile_nvt_restores_default_neigh(self, generator, temp_dir):
        """Step 6 (pre_tensile_nvt) restores default neigh_modify."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Find pre_tensile_nvt section
        pre_tensile_idx = script.index("pre_tensile_nvt")
        pre_tensile_section = script[pre_tensile_idx:]

        # Should have default neigh_modify (delay 5)
        assert "neigh_modify delay 5 every 1 check yes" in pre_tensile_section

    def test_bulk_no_conservative_neigh_override(self, generator, temp_dir):
        """Bulk study type has no conservative neigh_modify override."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")

        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Count occurrences: should only be in header neighbor settings, not per-step
        count = script.count("neigh_modify delay 0 every 1 check yes")
        assert count == 0

    def test_pre_tensile_restores_opt_profile_neigh(self, temp_dir):
        """With opt_profile (KOKKOS), pre_tensile_nvt restores profile settings."""
        from contracts.schemas import AccelMode, KokkosBackend, LammpsCaps, StudyType, TensileSpec

        # Create a caps object that produces an opt_profile with delay=10, every=5
        caps = LammpsCaps(
            executable_path="/usr/bin/lmp",
            kokkos_backend=KokkosBackend.CUDA,
            gpu_detected=True,
            gpu_count=1,
            accel_mode=AccelMode.KOKKOS_GPU,
        )
        generator = LAMMPSInputGenerator(template_dir=temp_dir / "templates", caps=caps)

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        # Early steps should still have conservative override
        high_temp_idx = script.index("high_temp_nvt")
        annealing_idx = script.index("annealing_cycles")
        early_section = script[high_temp_idx:annealing_idx]
        assert "neigh_modify delay 0 every 1 check yes" in early_section

        # pre_tensile_nvt should restore opt_profile values (delay 10, every 5)
        pre_tensile_idx = script.index("pre_tensile_nvt")
        pre_section = script[pre_tensile_idx:]
        assert "neigh_modify delay 10 every 5 check yes" in pre_section


class TestCrystalNoIntegrator:
    """Crystal atoms should not receive NVE or NVT integrators."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_layered_no_crystal_nve_or_nvt(self, generator, temp_dir):
        """Layered script has no fix ... crystal nve or fix ... crystal nvt."""
        from contracts.schemas import StudyType, TensileSpec

        data_path = temp_dir / "data.lammps"
        data_path.write_text("# Crystal atom types: 1 2 3\n0 atoms\n0 bonds\n")

        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(data_path),
            tensile_spec=TensileSpec(enabled=True),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        import re

        assert not re.search(r"fix\s+\S+\s+crystal\s+nve", script)
        assert not re.search(r"fix\s+\S+\s+crystal\s+nvt", script)


class TestStageMarker:
    """All generated scripts must include @@STAGE markers for progress tracking."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_bulk_script_has_stage_markers(self, generator, temp_dir):
        """Bulk screening script includes @@STAGE markers for all steps."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "@@STAGE 0 minimize" in script
        assert "@@STAGE 1 nvt_equilibration" in script
        assert "@@STAGE 2 npt_production" in script

    def test_layer_script_has_stage_markers(self, generator, temp_dir):
        """Layer chain script includes @@STAGE markers for all 5 steps."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        assert "@@STAGE 0 minimize" in script
        assert "@@STAGE 1 high_temp_nvt" in script
        assert "@@STAGE 2 annealing_cycles" in script
        assert "@@STAGE 3 nvt_equilibration" in script
        assert "@@STAGE 4 npt_equilibration" in script

    def test_marker_format(self, generator, temp_dir):
        """Markers use print command with @@STAGE prefix."""
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
        )
        output_path = temp_dir / "in.lammps"
        generator.generate_to_path(request, output_path)
        script = output_path.read_text()

        import re

        markers = re.findall(r'print "@@STAGE \d+ \w+"', script)
        assert len(markers) >= 3  # at least minimize + nvt + npt


class TestQSTensileResetTimestep:
    """Quasi-static tensile block starts with reset_timestep 0."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def test_qs_tensile_starts_with_reset_timestep(self, generator):
        """QS tensile output must contain reset_timestep 0."""
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={
                "pull_velocity_A_per_fs": 0.0001,
                "grip_thickness_angstrom": 20.0,
                "output_interval_steps": 100,
                "z_lo_grip": 0.0,
                "z_hi_grip": 100.0,
                "mode": "quasi_static",
                "displacement_increment_angstrom": 0.5,
                "relax_steps": 10000,
                "force_average_steps": 1000,
            },
        )
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[step],
        )
        script = generator._generate_tensile_quasi_static(step, step_index=6, chain=chain)
        assert "reset_timestep 0" in script


class TestEnergyComponentFields:
    """Verify energy decomposition fields are available."""

    def test_energy_component_constant_exists(self):
        """ENERGY_COMPONENT_FIELDS constant must contain all required keywords."""
        from protocols.lammps_steps import ENERGY_COMPONENT_FIELDS

        for kw in ["ebond", "eangle", "edihed", "eimp", "evdwl", "ecoul", "epair", "emol", "elong"]:
            assert kw in ENERGY_COMPONENT_FIELDS, f"{kw} missing from ENERGY_COMPONENT_FIELDS"

    def test_eimp_not_eimprop(self):
        """LAMMPS keyword must be eimp, not eimprop."""
        from protocols.lammps_steps import ENERGY_COMPONENT_FIELDS

        assert "eimp" in ENERGY_COMPONENT_FIELDS
        assert "eimprop" not in ENERGY_COMPONENT_FIELDS


class TestGeneratorOutputContainsEnergyFields:
    """Verify each step generator output includes energy decomposition."""

    _REQUIRED_FIELDS = [
        "ebond",
        "eangle",
        "edihed",
        "eimp",
        "evdwl",
        "ecoul",
        "epair",
        "emol",
        "elong",
    ]

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self, temp_dir):
        return LAMMPSInputGenerator(template_dir=temp_dir / "templates")

    def _make_step(self, name="nvt_eq", step_type="nvt", ensemble="nvt", **extra):
        from protocols.protocol_chain import ProtocolStep

        return ProtocolStep(
            name=name,
            step_type=step_type,
            ensemble=ensemble,
            temperature_K=298.0,
            duration="300 ps",
            extra_params=extra,
        )

    def _assert_energy_fields(self, script: str, label: str):
        thermo_lines = [
            line.strip()
            for line in script.split("\n")
            if "thermo_style" in line and "custom" in line
        ]
        assert thermo_lines, f"{label}: no thermo_style line found"
        for line in thermo_lines:
            for field in self._REQUIRED_FIELDS:
                assert field in line, f"{label}: {field} missing in '{line}'"

    def test_minimize_contains_energy_fields(self, generator):
        step = self._make_step(name="minimize", step_type="minimize")
        script = generator._generate_minimize(step)
        self._assert_energy_fields(script, "minimize")

    def test_nvt_contains_energy_fields(self, generator):
        step = self._make_step()
        script = generator._generate_nvt(step, step_index=1)
        self._assert_energy_fields(script, "nvt")

    def test_npt_contains_energy_fields(self, generator):
        step = self._make_step(name="npt_prod", step_type="npt", ensemble="npt")
        script = generator._generate_npt(step, step_index=2)
        self._assert_energy_fields(script, "npt")

    def test_nve_contains_energy_fields(self, generator):
        step = self._make_step(name="nve_run", step_type="nve", ensemble="nve")
        script = generator._generate_nve(step, step_index=3)
        self._assert_energy_fields(script, "nve")

    def test_viscosity_contains_energy_fields(self, generator):
        step = self._make_step(name="viscosity_nemd", step_type="viscosity")
        script = generator._generate_viscosity(step, step_index=3)
        self._assert_energy_fields(script, "viscosity")

    def test_annealing_contains_energy_fields(self, generator):
        step = self._make_step(
            name="annealing_cycles",
            step_type="annealing",
            n_cycles=2,
            temp_high_K=500.0,
            temp_low_K=298.0,
            duration_per_half_cycle_ps=50.0,
        )
        script = generator._generate_annealing(step, step_index=4)
        self._assert_energy_fields(script, "annealing")

    def test_tensile_contains_energy_fields(self, generator):
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="tensile_pull",
            step_type="tensile",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={"pull_velocity_A_per_fs": 0.0001, "z_lo_grip": 0.0, "z_hi_grip": 100.0},
        )
        chain = ProtocolChain(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.BULK,
            steps=[step],
        )
        script = generator._generate_tensile(step, step_index=5, chain=chain)
        self._assert_energy_fields(script, "tensile")

    def test_tensile_quasi_static_contains_energy_fields(self, generator):
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        step = ProtocolStep(
            name="qs_tensile",
            step_type="tensile_quasi_static",
            ensemble="nvt",
            temperature_K=298.0,
            duration="500 ps",
            extra_params={"z_lo_grip": 0.0, "z_hi_grip": 100.0},
        )
        chain = ProtocolChain(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.BULK,
            steps=[step],
        )
        script = generator._generate_tensile_quasi_static(step, step_index=6, chain=chain)
        self._assert_energy_fields(script, "tensile_quasi_static")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
