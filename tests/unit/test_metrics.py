"""
Unit tests for metrics module.

Tests density calculation, CED calculation, and metric validation.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestDensityCalculator:
    """Tests for DensityCalculator class."""

    def test_init_default_range(self):
        """Test default density range."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        assert calc.min_density == 0.5
        assert calc.max_density == 2.0

    def test_init_custom_range(self):
        """Test custom density range."""
        from metrics import DensityCalculator

        calc = DensityCalculator(min_density=0.8, max_density=1.3)

        assert calc.min_density == 0.8
        assert calc.max_density == 1.3

    def test_is_valid(self):
        """Test density validation."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        assert calc.is_valid(1.0)  # Valid
        assert calc.is_valid(0.5)  # At min
        assert calc.is_valid(2.0)  # At max
        assert not calc.is_valid(0.4)  # Below min
        assert not calc.is_valid(2.1)  # Above max

    def test_check_asphalt_range(self):
        """Test asphalt-specific range check."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        assert calc.check_asphalt_range(1.0) == "ok"
        assert calc.check_asphalt_range(0.9) == "ok"
        assert calc.check_asphalt_range(1.2) == "ok"
        assert calc.check_asphalt_range(0.7) == "too_low"
        assert calc.check_asphalt_range(1.4) == "too_high"

    def test_calculate_from_thermo_basic(self):
        """Test density calculation from thermo data."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        # Simple case
        densities = [0.95, 0.98, 1.00, 1.01, 1.02]
        avg, std = calc.calculate_from_thermo(densities)

        # Average of [0.98, 1.00, 1.01, 1.02] after skipping first 20%
        assert 0.99 < avg < 1.01
        assert std > 0

    def test_calculate_from_thermo_skip_fraction(self):
        """Test density calculation with skip fraction."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        # Data with equilibration period
        densities = [0.8, 0.85, 0.9, 0.95, 1.0, 1.01, 1.01, 1.02, 1.02, 1.02]

        # Skip first 20%
        avg, std = calc.calculate_from_thermo(densities, skip_fraction=0.2)

        # Should average equilibrated values
        assert avg > 0.95

    def test_calculate_from_thermo_empty(self):
        """Test density calculation with empty data."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        avg, std = calc.calculate_from_thermo([])

        assert avg == 0.0
        assert std == 0.0

    def test_calculate_from_box(self):
        """Test density calculation from box dimensions."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        # Typical MD box: 80A cube, ~10000 atoms
        volume_A3 = 80**3  # 512000 A^3
        total_mass_amu = 200000  # ~20 amu per atom

        density = calc.calculate_from_box(volume_A3, total_mass_amu)

        # Should be a reasonable density
        assert 0.1 < density < 2.0

    def test_calculate_from_box_zero_volume(self):
        """Test density calculation with zero volume."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        density = calc.calculate_from_box(0.0, 1000.0)

        assert density == 0.0

    def test_create_metric(self):
        """Test metric result creation."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        result = calc.create_metric(
            exp_id="exp_001",
            density_gcc=1.02,
            std_dev=0.01,
        )

        assert result.exp_id == "exp_001"
        assert result.metric_name == "density"
        assert result.value == 1.02
        assert result.unit == "g/cm3"
        assert result.namespace == "bulk_ff_gaff2"


class TestCEDCalculator:
    """Tests for CEDCalculator class."""

    def test_ced_basic_calculation(self):
        """Test basic CED calculation."""
        from common.units import KCAL_MOL_A3_TO_MJ_M3
        from metrics import CEDCalculator

        calc = CEDCalculator()

        # Test basic calculation without E_intra
        total_pe = -5000.0  # kcal/mol
        volume = 500000.0  # A^3
        mol_counts = {"mol1": 100}
        e_intra = {}  # No E_intra values

        ced = calc.calculate(total_pe, volume, mol_counts, e_intra)

        # Without E_intra, CED = -(PE/V) * KCAL_MOL_A3_TO_MJ_M3
        expected = -(total_pe / volume) * KCAL_MOL_A3_TO_MJ_M3
        assert ced > 0  # CED must be positive
        assert abs(ced - expected) < 0.1

    def test_ced_with_e_intra(self):
        """Test CED calculation with E_intra values."""
        from common.units import KCAL_MOL_A3_TO_MJ_M3
        from metrics import CEDCalculator

        calc = CEDCalculator()

        total_pe = -5000.0  # kcal/mol
        volume = 500000.0  # A^3
        mol_counts = {"mol1": 100}
        e_intra = {"mol1": -40.0}  # E_intra per molecule

        ced = calc.calculate(total_pe, volume, mol_counts, e_intra)

        # E_cohesive = PE - sum(n*E_intra) = -5000 - (100*-40) = -1000
        # CED = -(E_cohesive / V) * KCAL_MOL_A3_TO_MJ_M3
        e_cohesive = total_pe - (100 * -40.0)
        expected = -(e_cohesive / volume) * KCAL_MOL_A3_TO_MJ_M3
        assert ced > 0
        assert abs(ced - expected) < 0.1

    def test_ced_from_thermo_window_method(self):
        """Test CED calculation from thermo data with window method."""
        from metrics import CEDCalculator

        calc = CEDCalculator()

        # Create mock thermo data (300 samples)
        thermo_data = {
            "PotEng": [-5000.0 + i * 0.1 for i in range(300)],
            "Volume": [500000.0 + i * 10 for i in range(300)],
        }

        result = calc.calculate_from_thermo(
            thermo_data=thermo_data,
            mol_counts={},
            ff_name="GAFF2",
            ff_version="1.0",
            window_ps=200.0,
            use_window_ps=True,
        )

        assert result is not None
        assert result.metric_name == "cohesive_energy_density"
        assert result.unit == "MJ/m3"
        assert result.value > 0  # CED must be positive
        # Calculation info is stored in array_summary
        assert result.array_summary["window_method"] == "window_ps"
        assert result.array_summary["window_ps"] == 200.0
        assert "calc_version" in result.array_summary

    def test_ced_from_thermo_skip_fraction_method(self):
        """Test CED calculation with legacy skip_fraction method."""
        from metrics import CEDCalculator

        calc = CEDCalculator()

        thermo_data = {
            "PotEng": [-5000.0 + i * 0.1 for i in range(100)],
            "Volume": [500000.0 + i * 10 for i in range(100)],
        }

        result = calc.calculate_from_thermo(
            thermo_data=thermo_data,
            mol_counts={},
            ff_name="GAFF2",
            ff_version="1.0",
            use_window_ps=False,
            skip_fraction=0.2,
        )

        assert result is not None
        assert result.value > 0  # CED must be positive
        assert result.array_summary["window_method"] == "skip_fraction"
        assert result.array_summary["skip_fraction"] == 0.2

    def test_ced_validation(self):
        """Test CED validation range."""
        from metrics import CEDCalculator

        calc = CEDCalculator()

        # Valid CED range: 100-1000 MJ/m³
        assert calc.validate_ced(300.0) is True
        assert calc.validate_ced(500.0) is True
        assert calc.validate_ced(50.0) is False
        assert calc.validate_ced(1500.0) is False

    def test_ced_always_positive(self):
        """CED must be positive for attractive intermolecular interactions."""
        from metrics import CEDCalculator

        calc = CEDCalculator()
        # total_pe < total_e_intra (attractive) -> CED > 0
        ced = calc.calculate(-5000.0, 500000.0, {"mol1": 100}, {"mol1": -40.0})
        assert ced > 0

    def test_ced_benchmark_range(self):
        """CED should fall in typical asphalt range ~200-600 MJ/m³ for realistic inputs."""
        from metrics import CEDCalculator

        calc = CEDCalculator()
        # Realistic asphalt: e_coh ~ -15000 kcal/mol, V ~ 300000 A³
        ced = calc.calculate(-50000.0, 300000.0, {"mol1": 100}, {"mol1": -350.0})
        # e_coh = -50000 - (100 * -350) = -50000 + 35000 = -15000
        # CED = 15000/300000 * 6947.7 = 347.4
        assert 200 < ced < 600


class TestMetricValidation:
    """Tests for metric value validation."""

    def test_density_physical_range(self):
        """Test density values in physical range."""
        from metrics import DensityCalculator

        calc = DensityCalculator()

        # Typical asphalt binder densities
        test_densities = [0.95, 1.00, 1.05, 1.10]

        for d in test_densities:
            assert calc.is_valid(d), f"Density {d} should be valid"
            assert calc.check_asphalt_range(d) == "ok", f"Density {d} should be in asphalt range"

    def test_density_outliers(self):
        """Test detection of density outliers."""
        from metrics import DensityCalculator

        calc = DensityCalculator(min_density=0.5, max_density=2.0)

        # Clear outliers
        assert not calc.is_valid(-1.0)
        assert not calc.is_valid(5.0)
        assert not calc.is_valid(0.0)


class TestPolicyIntegration:
    """Tests for policy-based density boundary checks."""

    def test_check_asphalt_range_uses_policy(self):
        """Verify boundary judgments match FailurePolicy values."""
        from metrics import DensityCalculator

        calc = DensityCalculator()
        assert calc.check_asphalt_range(0.79) == "too_low"
        assert calc.check_asphalt_range(0.80) == "ok"
        assert calc.check_asphalt_range(1.30) == "ok"
        assert calc.check_asphalt_range(1.31) == "too_high"

    def test_validate_density_uses_policy(self):
        """MetricCalculator.validate_density should use FailurePolicy physical range."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator.__new__(MetricCalculator)
        assert calc.validate_density(0.5) is False  # boundary exclusive
        assert calc.validate_density(0.51) is True
        assert calc.validate_density(1.99) is True
        assert calc.validate_density(2.0) is False  # boundary exclusive


class TestEInterGroupEnergyIntegration:
    """Tests for E_inter with group_energy_spec (Phase 4.2)."""

    def test_e_inter_with_atom_counts(self):
        """E_inter calculation passes atom_counts for normalization."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator()

        # Thermo data with c_gg_* columns
        thermo_data = {
            "Step": list(range(300)),
            "c_gg_saturate_aromatic": [-100.0 + i * 0.01 for i in range(300)],
        }
        metrics = calc._calculate_e_inter(
            thermo_data=thermo_data,
            atom_counts={"saturate": 150, "aromatic": 36},
        )
        # Should find at least e_inter_total metric
        metric_names = [m.metric_name for m in metrics]
        assert "e_inter_total" in metric_names

    def test_e_inter_without_gg_columns(self):
        """No c_gg_* columns → empty metrics list."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator()

        thermo_data = {"Step": list(range(100)), "Temp": [298.0] * 100}
        metrics = calc._calculate_e_inter(thermo_data=thermo_data)
        assert metrics == []

    def test_e_inter_with_additive_pair_label(self):
        """Additive pair label produces e_inter_additive_binder metric."""
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator()

        thermo_data = {
            "Step": list(range(300)),
            "c_gg_additive_saturate": [-50.0 + i * 0.01 for i in range(300)],
        }
        metrics = calc._calculate_e_inter(
            thermo_data=thermo_data,
            additive_pair_label="additive_saturate",
        )
        metric_names = [m.metric_name for m in metrics]
        assert "e_inter_total" in metric_names
        assert "e_inter_additive_binder" in metric_names

    def test_build_group_assignments_from_dump_uses_mol_key(self):
        """Group assignment builder should read 'mol' from atom dict keys."""
        from contracts.schemas import GroupEnergySpec, GroupPairSpec
        from metrics.calculator import MetricCalculator

        dump_text = """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0 10
0 10
0 10
ITEM: ATOMS id type mol x y z
1 1 1 0 0 0
2 1 2 1 1 1
"""
        with tempfile.TemporaryDirectory() as td:
            dump_file = Path(td) / "dump_test.lammpstrj"
            dump_file.write_text(dump_text)

            spec = GroupEnergySpec(
                groups={"saturate": [1], "aromatic": [2]},
                pairs=[
                    GroupPairSpec(
                        label="saturate_aromatic",
                        group_a="saturate",
                        group_b="aromatic",
                    )
                ],
            )
            calc = MetricCalculator()
            assignments = calc._build_group_assignments_from_dump([str(dump_file)], spec)

        assert assignments is not None
        assert assignments["saturate"] == [0]
        assert assignments["aromatic"] == [1]


class TestArrayStorage:
    """Tests for array metric storage."""

    def test_array_metric_storage_creation(self):
        """Test ArrayMetricStorage creation."""
        from contracts.schemas import ArrayMetricStorage

        storage = ArrayMetricStorage(
            file_path="/path/to/rdf.parquet",
            file_hash="abc123def456",
            shape=(100, 2),
            summary={
                "min": 0.0,
                "max": 10.0,
                "mean": 3.5,
            },
        )

        assert storage.shape == (100, 2)
        assert storage.summary["mean"] == 3.5

    def test_metric_result_with_array(self):
        """Test MetricResult with array storage."""
        from contracts.schemas import ArrayMetricStorage, MetricResult

        storage = ArrayMetricStorage(
            file_path="/data/rdf.parquet",
            file_hash="hash123",
            shape=(200, 2),
            summary={"first_peak_r": 3.5, "first_peak_g": 2.1},
        )

        result = MetricResult(
            exp_id="exp_001",
            metric_name="rdf_curve",
            value=None,  # Array metric, no scalar value
            unit="angstrom,dimensionless",
            namespace="bulk_ff_gaff2",
            array_storage=storage,
            array_summary={"first_peak_r": 3.5, "first_peak_g": 2.1},
        )

        assert result.value is None
        assert result.array_storage.shape == (200, 2)
        assert result.array_summary["first_peak_r"] == 3.5

    def test_default_storage_uses_ssot_nested_layout(self, monkeypatch, tmp_path):
        """Default ArrayStorage should store under data/arrays/{exp_id}/."""
        from metrics.array_storage import ArrayStorage

        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        storage = ArrayStorage()
        storage.store(
            "rdf_curve",
            "exp_nested_001",
            {"r": [0.1, 0.2], "g_r": [1.0, 1.1]},
        )

        exp_metrics = storage.list_metrics("exp_nested_001")
        assert "rdf_curve" in exp_metrics
        assert storage.exists("rdf_curve", "exp_nested_001")

    def test_default_storage_can_read_legacy_flat_layout(self, monkeypatch, tmp_path):
        """Default ArrayStorage should load legacy flat files for compatibility."""
        from metrics.array_storage import ArrayStorage

        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))

        # Simulate legacy flat layout writer.
        legacy = ArrayStorage(storage_dir=tmp_path / "data" / "arrays")
        legacy.store(
            "msd_curve",
            "exp_legacy_001",
            {"time_ps": [1.0, 2.0], "msd": [10.0, 20.0]},
        )

        # New default loader should still find legacy file.
        current = ArrayStorage()
        loaded = current.load("msd_curve", "exp_legacy_001")
        assert loaded is not None
        assert loaded["msd"][1] == 20.0


class TestStudyTypeCEDGate:
    """CED is meaningful only for systems with intermolecular interactions.

    Single-molecule vacuum runs are the source of E_intra; CED would be
    circular and physically undefined. Verify the calculator skips CED
    for study_type='single_molecule_vacuum' but keeps it for 'bulk'.
    """

    def _make_run_result(self, study_type: str):
        """Build a minimal LAMMPSRunResult that triggers metric calculation."""
        from contracts.schemas import LAMMPSRunResult

        return LAMMPSRunResult(
            success=True,
            log_file="dummy.log",
            dump_files=[],
            wall_time_seconds=1.0,
            exit_code=0,
            exp_id="exp_test",
            mol_counts={"U-AS-Thio-0293": 1},
            force_field="GAFF2",
            ff_version="1.0",
            temperature_K=293.0,
            study_type=study_type,
        )

    def test_lammps_run_result_has_study_type_field(self):
        """Schema regression: LAMMPSRunResult must accept study_type."""
        rr = self._make_run_result("single_molecule_vacuum")
        assert rr.study_type == "single_molecule_vacuum"

        rr_bulk = self._make_run_result("bulk")
        assert rr_bulk.study_type == "bulk"

    def test_study_type_default_is_bulk(self):
        """LAMMPSRunResult.study_type defaults to 'bulk' for backward compat."""
        from contracts.schemas import LAMMPSRunResult

        rr = LAMMPSRunResult(
            success=True,
            log_file="x",
            dump_files=[],
            wall_time_seconds=0.0,
            exit_code=0,
        )
        assert rr.study_type == "bulk"

    def _make_calculator_with_spy(self):
        """Build a MetricCalculator and replace ced_calc with a spy."""
        from unittest.mock import MagicMock

        from metrics import MetricCalculator

        calc = MetricCalculator()
        spy = MagicMock()
        spy.calculate_from_thermo = MagicMock(return_value=None)
        calc.ced_calc = spy
        return calc, spy

    def _make_run_result_with_log(self, study_type: str, tmp_path):
        """Create a fake LAMMPS log file + run_result that calculate() can parse."""
        from contracts.schemas import LAMMPSRunResult

        log_path = tmp_path / "log.lammps"
        log_path.write_text(
            "LAMMPS (1 Jan 2025)\n"
            "Step Temp Press PotEng KinEng TotEng Volume Density\n"
            "0 293.0 1.0 -100.0 50.0 -50.0 1000.0 0.001\n"
            "1000 293.0 1.0 -100.0 50.0 -50.0 1000.0 0.001\n"
            "Loop time of 1.0 on 1 procs\n"
            "Total wall time: 0:00:01\n"
        )
        return LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=1.0,
            exit_code=0,
            exp_id="exp_test",
            mol_counts={"U-AS-Thio-0293": 1},
            force_field="GAFF2",
            ff_version="1.0",
            temperature_K=293.0,
            study_type=study_type,
        )

    def test_calculate_skips_ced_for_single_molecule_vacuum(self, tmp_path):
        """Behavior gate: single_molecule_vacuum must NOT trigger ced_calc."""
        calc, spy = self._make_calculator_with_spy()
        rr = self._make_run_result_with_log("single_molecule_vacuum", tmp_path)
        try:
            metrics = calc.calculate(rr)
        except Exception:
            metrics = []  # other calculators may fail on minimal log; we only care about CED gate
        # ced_calc.calculate_from_thermo must NOT be called for vacuum
        spy.calculate_from_thermo.assert_not_called()
        # And no cohesive_energy_density metric in the result list
        names = [m.metric_name for m in metrics]
        assert "cohesive_energy_density" not in names

    def test_calculate_invokes_ced_for_bulk(self, tmp_path):
        """Behavior gate: bulk study must invoke ced_calc.calculate_from_thermo."""
        calc, spy = self._make_calculator_with_spy()
        rr = self._make_run_result_with_log("bulk", tmp_path)
        try:
            calc.calculate(rr)
        except Exception:
            pass
        spy.calculate_from_thermo.assert_called_once()

    def test_calculate_skips_ced_for_layered_without_mol_counts(self, tmp_path):
        """Layered runs without mol-count provenance must not fall back to PE/V."""
        calc, spy = self._make_calculator_with_spy()
        rr = self._make_run_result_with_log("layer_bulkff", tmp_path)
        rr.mol_counts = {}
        try:
            metrics = calc.calculate(rr)
        except Exception:
            metrics = []
        spy.calculate_from_thermo.assert_not_called()
        names = [m.metric_name for m in metrics]
        assert "cohesive_energy_density" not in names

    def test_restore_run_result_metadata_loads_study_type(self):
        """Reanalysis path: restore_run_result_metadata must populate study_type
        from ExperimentModel so the CED gate works for bare run_results."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from contracts.schemas import LAMMPSRunResult
        from orchestrator.task_runners import restore_run_result_metadata

        # Bare LAMMPSRunResult with default study_type (bulk)
        rr = LAMMPSRunResult(
            success=True,
            log_file="x",
            dump_files=[],
            wall_time_seconds=0.0,
            exit_code=0,
        )
        assert rr.study_type == "bulk"  # default

        # Mock session that returns an ExperimentModel-like row with single_molecule_vacuum
        fake_exp = SimpleNamespace(
            id=1,
            temperature_K=293.0,
            ff_type="bulk_ff_gaff2",
            study_type="single_molecule_vacuum",
        )
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = fake_exp
        mock_session.query.return_value.filter.return_value.all.return_value = []  # no mol rows

        restore_run_result_metadata(rr, "exp_test", session=mock_session)

        assert rr.study_type == "single_molecule_vacuum"
        assert rr.temperature_K == 293.0
        assert rr.force_field == "GAFF2"

    def test_restore_run_result_metadata_handles_null_study_type(self):
        """If ExperimentModel.study_type is None, default to 'bulk'."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from contracts.schemas import LAMMPSRunResult
        from orchestrator.task_runners import restore_run_result_metadata

        rr = LAMMPSRunResult(
            success=True, log_file="x", dump_files=[], wall_time_seconds=0.0, exit_code=0
        )
        fake_exp = SimpleNamespace(
            id=1, temperature_K=298.0, ff_type="bulk_ff_gaff2", study_type=None
        )
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = fake_exp
        mock_session.query.return_value.filter.return_value.all.return_value = []

        restore_run_result_metadata(rr, "exp_test", session=mock_session)
        assert rr.study_type == "bulk"


class TestEnergyComponentMetricCreation:
    """Verify MetricCalculator.calculate() produces energy component metrics
    when thermo data includes decomposition columns."""

    def _make_run_result_with_energy_log(self, tmp_path):
        from contracts.schemas import LAMMPSRunResult

        # Thermo header includes energy decomposition columns
        header = (
            "Step Temp Press PotEng KinEng TotEng Volume Density "
            "E_bond E_angle E_dihed E_imp E_vdwl E_coul E_pair E_mol E_long"
        )
        row1 = "0 298.0 1.0 -50000.0 25000.0 -25000.0 300000.0 1.02 1500.0 800.0 200.0 5.0 -30000.0 -20000.0 -49000.0 2505.0 -1000.0"
        row2 = "1000 298.0 1.0 -50100.0 25050.0 -25050.0 300100.0 1.02 1510.0 810.0 205.0 5.5 -30100.0 -20050.0 -49100.0 2530.5 -1050.0"
        row3 = "2000 298.0 1.0 -50050.0 25025.0 -25025.0 300050.0 1.02 1505.0 805.0 202.0 5.2 -30050.0 -20025.0 -49050.0 2517.2 -1025.0"

        log_path = tmp_path / "log_energy.lammps"
        log_path.write_text(
            f"LAMMPS (1 Jan 2025)\n{header}\n{row1}\n{row2}\n{row3}\n"
            f"Loop time of 1.0 on 1 procs\nTotal wall time: 0:00:01\n"
        )
        return LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=1.0,
            exit_code=0,
            exp_id="exp_energy_test",
            mol_counts={"U-SA-Squalane-0293": 1},
            force_field="GAFF2",
            ff_version="1.0",
            temperature_K=298.0,
            study_type="bulk",
        )

    def test_energy_component_metrics_created(self, tmp_path):
        """calculate() must produce MetricResults for all 9 energy components."""
        from metrics import MetricCalculator
        from metrics.calculator import ENERGY_COMPONENT_MAP

        calc = MetricCalculator()
        rr = self._make_run_result_with_energy_log(tmp_path)
        try:
            metrics = calc.calculate(rr)
        except Exception:
            metrics = []

        metric_names = {m.metric_name for m in metrics}

        for metric_name in ENERGY_COMPONENT_MAP.values():
            assert metric_name in metric_names, f"{metric_name} not in calculate() output"

    def test_energy_component_values_reasonable(self, tmp_path):
        """Energy component values must be non-zero and have correct units."""
        from metrics import MetricCalculator

        calc = MetricCalculator()
        rr = self._make_run_result_with_energy_log(tmp_path)
        try:
            metrics = calc.calculate(rr)
        except Exception:
            metrics = []

        by_name = {m.metric_name: m for m in metrics}

        if "e_bond" in by_name:
            assert by_name["e_bond"].unit == "kcal/mol"
            assert by_name["e_bond"].value > 0  # bond energy is positive
        if "e_vdwl" in by_name:
            assert by_name["e_vdwl"].value < 0  # vdW energy is negative (attractive)
        if "e_coul" in by_name:
            assert by_name["e_coul"].value < 0  # Coulomb energy is negative
        if "e_improper" in by_name:
            assert by_name["e_improper"].unit == "kcal/mol"
            assert by_name["e_improper"].namespace == "bulk_ff_gaff2"
