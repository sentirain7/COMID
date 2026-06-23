"""
Unit tests for Layer Track.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from builder.crystal_builder import CrystalBuilder
from builder.layer_builder import LayerBuilder, LayerBuildResult, generate_layer_exp_id
from builder.layer_spec import (
    CrystalMaterial,
    CrystalSpec,
    LayerSpec,
    LayerType,
    SurfaceOrientation,
)
from metrics.layer_metrics import (
    AdhesionEnergyCalculator,
    AdhesionEnergyResult,
    DensityProfileCalculator,
    DensityProfileResult,
    LayerMetrics,
    OrientationOrderCalculator,
)


class TestLayerSpec:
    """Tests for LayerSpec."""

    def test_create_interface(self):
        """Test creating simple interface spec."""
        spec = LayerSpec.create_interface(
            crystal_material=CrystalMaterial.SIO2,
            binder_thickness=50.0,
        )

        assert spec.layer_type == LayerType.INTERFACE
        assert spec.crystal.material == CrystalMaterial.SIO2
        assert spec.binder.thickness_angstrom == 50.0
        assert spec.water is None

    def test_create_water_interface(self):
        """Test creating water interface spec."""
        spec = LayerSpec.create_water_interface(
            water_thickness=10.0,
            binder_thickness=50.0,
        )

        assert spec.layer_type == LayerType.WATER_INTERFACE
        assert spec.water is not None
        assert spec.water.thickness_angstrom == 10.0

    def test_create_sandwich(self):
        """Test creating sandwich spec."""
        spec = LayerSpec.create_sandwich(
            crystal_material=CrystalMaterial.SIO2,
            binder_thickness=50.0,
        )

        assert spec.layer_type == LayerType.THREE_LAYER

    def test_get_total_height(self):
        """Test total height calculation."""
        spec = LayerSpec.create_interface(
            crystal_material=CrystalMaterial.SIO2,
            binder_thickness=50.0,
            crystal_thickness=25.0,
        )

        height = spec.get_total_height()
        assert height == pytest.approx(75.0)  # 25 + 50

    def test_get_total_height_with_water(self):
        """Test total height with water layer."""
        spec = LayerSpec.create_water_interface(
            water_thickness=10.0,
            binder_thickness=50.0,
        )
        spec.crystal.thickness_angstrom = 25.0

        height = spec.get_total_height()
        assert height == pytest.approx(85.0)  # 25 + 10 + 50

    def test_get_total_height_binder_binder_no_crystal(self):
        """Binder-binder total height should exclude crystal thickness."""
        spec = LayerSpec.create_binder_binder(
            binder1_thickness=50.0,
            binder2_thickness=40.0,
        )
        # Crystal thickness must not be included for scenario F.
        assert spec.get_total_height() == pytest.approx(90.0)

    def test_get_layer_boundaries(self):
        """Test layer boundary calculation."""
        spec = LayerSpec.create_interface(
            binder_thickness=50.0,
            crystal_thickness=25.0,
        )
        spec.crystal.thickness_angstrom = 25.0

        boundaries = spec.get_layer_boundaries()

        assert "crystal_bottom" in boundaries
        assert "binder" in boundaries

        z_min, z_max = boundaries["crystal_bottom"]
        assert z_min == 0.0
        assert z_max == 25.0

        z_min, z_max = boundaries["binder"]
        assert z_min == 25.0
        assert z_max == 75.0

    def test_to_dict_from_dict(self):
        """Test serialization."""
        spec = LayerSpec.create_water_interface()
        spec.temperature_k = 350.0

        d = spec.to_dict()
        spec2 = LayerSpec.from_dict(d)

        assert spec2.layer_type == spec.layer_type
        assert spec2.temperature_k == 350.0
        assert spec2.water is not None


class TestCrystalSpec:
    """Tests for CrystalSpec."""

    def test_default_values(self):
        """Test default crystal spec."""
        spec = CrystalSpec()

        assert spec.material == CrystalMaterial.SIO2
        assert spec.surface == SurfaceOrientation.ORIENT_001
        assert spec.thickness_angstrom == 25.0
        assert spec.hydroxylated is True

    def test_calcite_spec(self):
        """Test calcite specification."""
        spec = CrystalSpec(
            material=CrystalMaterial.CITE,
            thickness_angstrom=30.0,
            hydroxylated=False,
        )

        assert spec.material == CrystalMaterial.CITE
        assert spec.hydroxylated is False


class TestCrystalBuilder:
    """Tests for CrystalBuilder."""

    def test_build_sio2(self):
        """Test building SiO2 slab."""
        builder = CrystalBuilder()
        spec = CrystalSpec(
            material=CrystalMaterial.SIO2,
            nx=3,
            ny=3,
            nz=2,
            hydroxylated=False,
        )

        slab = builder.build(spec)

        assert slab is not None
        assert slab.n_atoms > 0
        assert slab.material == CrystalMaterial.SIO2
        assert "Si" in slab.atom_types
        assert "O" in slab.atom_types

    def test_build_with_hydroxyl(self):
        """Test building hydroxylated slab."""
        builder = CrystalBuilder()
        spec = CrystalSpec(
            material=CrystalMaterial.SIO2,
            nx=3,
            ny=3,
            nz=2,
            hydroxylated=True,
        )

        slab = builder.build(spec)

        assert "Hoh" in slab.atom_types
        assert "Os" in slab.atom_types
        assert "H" not in slab.atom_types
        # Should have more atoms due to -OH groups
        spec_no_oh = CrystalSpec(
            material=CrystalMaterial.SIO2,
            nx=3,
            ny=3,
            nz=2,
            hydroxylated=False,
        )
        slab_no_oh = builder.build(spec_no_oh)
        assert slab.n_atoms >= slab_no_oh.n_atoms

    def test_slab_translate(self):
        """Test translating slab."""
        builder = CrystalBuilder()
        slab = builder.create_sio2_slab(thickness=10.0, xy_size=20.0, hydroxylated=False)

        z_before = [a.z for a in slab.atoms]
        slab.translate(0, 0, 10.0)
        z_after = [a.z for a in slab.atoms]

        for z_b, z_a in zip(z_before, z_after, strict=False):
            assert z_a == pytest.approx(z_b + 10.0)

    def test_slab_to_xyz(self):
        """Test writing XYZ file."""
        builder = CrystalBuilder()
        slab = builder.create_sio2_slab(hydroxylated=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "slab.xyz"
            slab.to_xyz(filepath)

            assert filepath.exists()
            with open(filepath) as f:
                lines = f.readlines()
                assert int(lines[0].strip()) == slab.n_atoms

    def test_get_surface_atoms(self):
        """Test getting surface atoms."""
        builder = CrystalBuilder()
        slab = builder.create_sio2_slab(hydroxylated=False)

        surface = slab.get_surface_atoms(tolerance=1.0)
        assert len(surface) > 0

        z_max = max(a.z for a in slab.atoms)
        for atom in surface:
            assert abs(atom.z - z_max) < 1.0


class TestLayerBuilder:
    """Tests for LayerBuilder."""

    def test_build_interface(self):
        """Deprecated build path fails fast and points to the canonical route.

        LayerBuilder._create_combined_data_file is intentionally deprecated
        (NotImplementedError). The canonical path is
        features.layered_structures.service.submit_layered_structure().
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = LayerBuilder(work_dir=Path(tmpdir))

            result = builder.build_interface(
                crystal_material=CrystalMaterial.SIO2,
                binder_thickness=50.0,
            )

            assert result.success is False
            assert result.error_message is not None
            assert "submit_layered_structure" in result.error_message

    def test_build_water_interface(self):
        """Deprecated water-interface build path fails fast with guidance.

        Same deprecation as test_build_interface: the build must not succeed
        and the error message must direct callers to the canonical route
        (submit_layered_structure).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = LayerBuilder(work_dir=Path(tmpdir))

            result = builder.build_water_interface(
                water_thickness=10.0,
                binder_thickness=50.0,
            )

            assert result.success is False
            assert result.error_message is not None
            assert "submit_layered_structure" in result.error_message

    def test_layer_build_result_to_dict(self):
        """Test build result serialization."""
        result = LayerBuildResult(
            success=True,
            total_atoms=5000,
            box_dimensions=(50.0, 50.0, 100.0),
            crystal_atoms=1000,
            water_molecules=500,
            binder_atoms=3500,
            interface_area_nm2=25.0,
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["total_atoms"] == 5000
        assert d["interface_area_nm2"] == 25.0


class TestGenerateLayerExpId:
    """Tests for layer experiment ID generation."""

    def test_generate_id(self):
        """Test generating layer exp ID."""
        spec = LayerSpec.create_interface(
            crystal_material=CrystalMaterial.SIO2,
        )
        spec.temperature_k = 298.0

        exp_id = generate_layer_exp_id(spec, seed=12345)

        assert "layer2" in exp_id
        assert "SiO2" in exp_id
        assert "T298K" in exp_id
        assert "__h=" in exp_id

    def test_different_specs_different_ids(self):
        """Test that different specs produce different IDs."""
        spec1 = LayerSpec.create_interface(binder_thickness=50.0)
        spec2 = LayerSpec.create_interface(binder_thickness=60.0)

        id1 = generate_layer_exp_id(spec1, seed=123)
        id2 = generate_layer_exp_id(spec2, seed=123)

        assert id1 != id2


class TestAdhesionEnergyCalculator:
    """Tests for AdhesionEnergyCalculator."""

    def test_calculate_basic(self):
        """Test basic adhesion energy calculation."""
        calc = AdhesionEnergyCalculator()

        result = calc.calculate(
            e_total=-10000.0,  # Total system energy
            e_crystal=-3000.0,  # Crystal alone
            e_binder=-6000.0,  # Binder alone
            interface_area_nm2=25.0,
        )

        # Interaction energy = -10000 - (-3000 - 6000) = -1000 kcal/mol
        assert result.e_total == -10000.0
        assert result.interface_area == 25.0
        assert result.adhesion_energy != 0

    def test_calculate_with_water(self):
        """Test adhesion with water layer."""
        calc = AdhesionEnergyCalculator()

        result = calc.calculate(
            e_total=-15000.0,
            e_crystal=-3000.0,
            e_binder=-6000.0,
            interface_area_nm2=25.0,
            e_water=-4000.0,
        )

        assert result.e_water == -4000.0

    def test_calculate_from_trajectory(self):
        """Test calculation from trajectory."""
        calc = AdhesionEnergyCalculator()

        # Mock trajectory data
        energies = [(-10000 + np.random.randn() * 100, -3000, -6000, None) for _ in range(100)]

        result = calc.calculate_from_trajectory(
            energies=energies,
            interface_area_nm2=25.0,
            skip_fraction=0.3,
        )

        assert result.n_samples == 70  # After skipping 30%
        assert result.uncertainty is not None


class TestDensityProfileCalculator:
    """Tests for DensityProfileCalculator."""

    def test_calculate_basic(self):
        """Test basic density profile calculation."""
        calc = DensityProfileCalculator(bin_width=2.0)

        # Create simple test data
        n_atoms = 1000
        positions = np.random.rand(n_atoms, 3) * 50  # 50 Å box
        masses = np.ones(n_atoms) * 12.0  # Carbon-like

        result = calc.calculate(
            positions=positions,
            masses=masses,
            box=(50.0, 50.0, 50.0),
            axis="z",
        )

        assert len(result.z_bins) > 0
        assert len(result.density) == len(result.z_bins)
        assert result.bin_width == 2.0

    def test_interface_width(self):
        """Test interface width estimation."""
        DensityProfileCalculator(bin_width=1.0)

        # Create layered density profile
        z_bins = np.linspace(0, 100, 100)
        density = np.zeros(100)
        density[:30] = 2.5  # Crystal region
        density[30:40] = np.linspace(2.5, 1.0, 10)  # Interface
        density[40:] = 1.0  # Binder region

        result = DensityProfileResult(
            z_bins=z_bins,
            density=density,
            bin_width=1.0,
        )

        width = result.get_interface_width()
        assert width > 0


class TestOrientationOrderCalculator:
    """Tests for OrientationOrderCalculator."""

    def test_calculate_p2_aligned(self):
        """Test P2 for perfectly aligned molecules."""
        calc = OrientationOrderCalculator(reference_axis="z")

        # All molecules aligned with z-axis
        axes = np.array(
            [
                [0, 0, 1],
                [0, 0, 1],
                [0, 0, 1],
            ],
            dtype=float,
        )

        p2 = calc.calculate_p2(axes)
        assert p2 == pytest.approx(1.0, abs=0.01)

    def test_calculate_p2_perpendicular(self):
        """Test P2 for perpendicular molecules."""
        calc = OrientationOrderCalculator(reference_axis="z")

        # All molecules in xy-plane
        axes = np.array(
            [
                [1, 0, 0],
                [0, 1, 0],
                [1, 0, 0],
                [0, 1, 0],
            ],
            dtype=float,
        )

        p2 = calc.calculate_p2(axes)
        assert p2 == pytest.approx(-0.5, abs=0.01)

    def test_calculate_p2_random(self):
        """Test P2 for random orientations."""
        calc = OrientationOrderCalculator(reference_axis="z")

        np.random.seed(42)
        n_mols = 1000
        # Random unit vectors
        theta = np.arccos(2 * np.random.rand(n_mols) - 1)
        phi = 2 * np.pi * np.random.rand(n_mols)

        axes = np.column_stack(
            [
                np.sin(theta) * np.cos(phi),
                np.sin(theta) * np.sin(phi),
                np.cos(theta),
            ]
        )

        p2 = calc.calculate_p2(axes)
        # Random orientations should give P2 ≈ 0
        assert abs(p2) < 0.1


class TestLayerMetrics:
    """Tests for LayerMetrics container."""

    def test_empty_metrics(self):
        """Test empty metrics container."""
        metrics = LayerMetrics()

        assert not metrics.is_complete()
        d = metrics.to_dict()
        assert d["adhesion_energy"] is None

    def test_complete_metrics(self):
        """Test complete metrics."""
        metrics = LayerMetrics(
            adhesion_energy=AdhesionEnergyResult(
                adhesion_energy=-50.0,
                work_of_adhesion=50.0,
                interface_area=25.0,
                e_total=-10000,
                e_crystal=-3000,
                e_binder=-6000,
            ),
            density_profile=DensityProfileResult(
                z_bins=np.linspace(0, 100, 50),
                density=np.ones(50),
                bin_width=2.0,
            ),
        )

        assert metrics.is_complete()

        d = metrics.to_dict()
        assert d["adhesion_energy"]["work_of_adhesion"] == 50.0
