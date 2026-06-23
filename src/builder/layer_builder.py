"""
Layer Builder for creating layered molecular systems.

Builds crystal/water/binder systems for interface studies.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.logging import get_logger

from .composition_calculator import CompositionCalculator
from .crystal_builder import CrystalBuilder, CrystalSlab
from .layer_spec import (
    BinderLayerSpec,
    CrystalMaterial,
    CrystalSpec,
    LayerSpec,
    LayerType,
    WaterSpec,
)

# CrystalSpec is now CrystalLayerSpec, BinderLayerSpec is now BinderLayerConfig,
# WaterSpec is now WaterLayerSpec — all aliased in layer_spec.py for compat.
from .molecule_db import MoleculeDB
from .packmol_wrapper import PackmolWrapper

logger = get_logger("builder.layer_builder")


@dataclass
class LayerBuildResult:
    """Result of layer system build."""

    success: bool
    data_file_path: Path | None = None
    total_atoms: int = 0
    box_dimensions: tuple[float, float, float] = (0, 0, 0)
    layer_info: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    # Quality metrics
    crystal_atoms: int = 0
    water_molecules: int = 0
    binder_atoms: int = 0
    interface_area_nm2: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "data_file_path": str(self.data_file_path) if self.data_file_path else None,
            "total_atoms": self.total_atoms,
            "box_dimensions": self.box_dimensions,
            "layer_info": self.layer_info,
            "error_message": self.error_message,
            "crystal_atoms": self.crystal_atoms,
            "water_molecules": self.water_molecules,
            "binder_atoms": self.binder_atoms,
            "interface_area_nm2": self.interface_area_nm2,
        }


class LayerBuilder:
    """
    Builder for layered molecular systems.

    Creates crystal/water/binder systems for adhesion studies.
    """

    def __init__(
        self,
        molecule_db: MoleculeDB | None = None,
        packmol_path: str = "packmol",
        work_dir: Path | None = None,
    ):
        """
        Initialize layer builder.

        Args:
            molecule_db: Molecule database
            packmol_path: Path to Packmol executable
            work_dir: Working directory
        """
        self.molecule_db = molecule_db or MoleculeDB()
        self.crystal_builder = CrystalBuilder()
        self.packmol = PackmolWrapper(packmol_path=packmol_path)
        self.calculator = CompositionCalculator()
        self.work_dir = work_dir or Path("./layer_builds")

    def build(self, spec: LayerSpec) -> LayerBuildResult:
        """
        Build a layered system from specification.

        Args:
            spec: Layer specification

        Returns:
            LayerBuildResult with build info
        """
        logger.info(f"Building layer system: {spec.layer_type.value}")

        # Route to scenario-specific builders (Phase 4.3)
        if spec.layer_type in (LayerType.AGED_FRESH, LayerType.WATER_AGED_FRESH):
            return self._build_aged_fresh(spec)
        elif spec.layer_type == LayerType.BINDER_BINDER:
            return self._build_binder_binder(spec)

        return self._build_standard(spec)

    def _build_standard(self, spec: LayerSpec) -> LayerBuildResult:
        """Build standard layer systems (Scenarios A/B/C).

        Args:
            spec: Layer specification

        Returns:
            LayerBuildResult with build info
        """
        try:
            # Create work directory
            work_dir = self.work_dir / f"layer_{spec.seed}"
            work_dir.mkdir(parents=True, exist_ok=True)

            # Build crystal slab
            crystal_slab = self._build_crystal(spec.crystal)
            logger.info(f"Crystal slab: {crystal_slab.n_atoms} atoms")

            # Get box dimensions from crystal
            lx, ly, _ = crystal_slab.box
            total_height = spec.get_total_height()

            # Build each layer
            layer_info = spec.get_layer_boundaries()

            # Build water layer if present
            water_molecules = 0
            if spec.water:
                water_molecules = self._calculate_water_molecules(spec.water, lx, ly)
                logger.info(f"Water layer: {water_molecules} molecules")

            # Calculate binder molecules
            binder_info = self._calculate_binder_composition(spec.binder, lx, ly)
            logger.info(f"Binder layer: {binder_info['total_atoms']} atoms")

            # Create combined LAMMPS data file
            output_path = work_dir / "layer_system.data"
            self._create_combined_data_file(
                output_path=output_path,
                spec=spec,
                crystal_slab=crystal_slab,
                water_molecules=water_molecules,
                binder_info=binder_info,
                binder_secondary_info=None,
                lx=lx,
                ly=ly,
                lz=total_height,
            )

            # Calculate interface area
            interface_area = (lx * ly) / 100  # Å² to nm²

            return LayerBuildResult(
                success=True,
                data_file_path=output_path,
                total_atoms=crystal_slab.n_atoms + water_molecules * 3 + binder_info["total_atoms"],
                box_dimensions=(lx, ly, total_height),
                layer_info=layer_info,
                crystal_atoms=crystal_slab.n_atoms,
                water_molecules=water_molecules,
                binder_atoms=binder_info["total_atoms"],
                interface_area_nm2=interface_area,
            )

        except Exception as e:
            logger.error(f"Layer build failed: {e}")
            return LayerBuildResult(
                success=False,
                error_message=str(e),
            )

    def _build_crystal(self, spec: CrystalSpec) -> CrystalSlab:
        """Build crystal slab."""
        return self.crystal_builder.build(spec)

    def _calculate_water_molecules(
        self,
        spec: WaterSpec,
        lx: float,
        ly: float,
    ) -> int:
        """Calculate number of water molecules for layer."""
        # Volume in Å³
        volume = lx * ly * spec.thickness_angstrom

        # Water density: 1 g/cm³ = 0.033 molecules/Å³
        # Molar mass of water: 18.015 g/mol
        # Avogadro: 6.022e23
        # 1 g/cm³ water = 3.34e-2 molecules/Å³
        density_mol_per_A3 = spec.density * 0.0334

        return int(volume * density_mol_per_A3)

    def _calculate_binder_composition(
        self,
        spec: BinderLayerSpec,
        lx: float,
        ly: float,
    ) -> dict[str, Any]:
        """Calculate binder molecule counts for layer."""
        # Volume in Å³
        volume = lx * ly * spec.thickness_angstrom

        # Estimate total atoms based on target density and typical asphalt
        # Typical asphalt: ~1 g/cm³, avg molecular weight ~400 g/mol
        # 1 g/cm³ = 1e-24 g/Å³
        # Number of molecules = volume * density / MW * Avogadro
        # Simplified: assume ~50 atoms per molecule average
        density_g_per_A3 = spec.target_density * 1e-24
        avg_mw = 400  # g/mol
        avg_atoms_per_mol = 50

        n_molecules = int(volume * density_g_per_A3 * 6.022e23 / avg_mw)
        total_atoms = n_molecules * avg_atoms_per_mol

        # Distribute by weight fraction
        composition = {
            "asphaltene": {"wt": spec.asphaltene_wt, "count": 0, "atoms": 0},
            "resin": {"wt": spec.resin_wt, "count": 0, "atoms": 0},
            "aromatic": {"wt": spec.aromatic_wt, "count": 0, "atoms": 0},
            "saturate": {"wt": spec.saturate_wt, "count": 0, "atoms": 0},
        }

        total_wt = sum(c["wt"] for c in composition.values())
        for _key, val in composition.items():
            frac = val["wt"] / total_wt if total_wt > 0 else 0.25
            val["count"] = int(n_molecules * frac)
            val["atoms"] = val["count"] * avg_atoms_per_mol

        return {
            "total_atoms": total_atoms,
            "total_molecules": n_molecules,
            "composition": composition,
            "volume_A3": volume,
        }

    def _create_combined_data_file(
        self,
        output_path: Path,
        spec: LayerSpec,
        crystal_slab: CrystalSlab,
        water_molecules: int,
        binder_info: dict[str, Any],
        binder_secondary_info: dict[str, Any] | None,
        lx: float,
        ly: float,
        lz: float,
    ) -> None:
        """Fail-fast: legacy placeholder removed.

        This method does not produce valid LAMMPS data files.
        Use the canonical layered path:
        features.layered_structures.service.submit_layered_structure()
        """
        import importlib.util

        logger.warning(
            "LayerBuilder._create_combined_data_file is deprecated. "
            "Use features.layered_structures.service.submit_layered_structure() "
            "for production layered structure submission."
        )
        _has_canonical = importlib.util.find_spec("features.layered_structures.service")
        if _has_canonical:
            raise NotImplementedError(
                "LayerBuilder cannot produce valid LAMMPS data. "
                "Use the canonical layered path: "
                "features.layered_structures.service.submit_layered_structure()"
            )
        raise NotImplementedError(
            "LayerBuilder placeholder removed. Use the canonical path: "
            "features.layered_structures.service.submit_layered_structure()"
        )

    def _build_aged_fresh(self, spec: LayerSpec) -> LayerBuildResult:
        """Build aged-fresh dual binder system (Scenarios D/E).

        Crystal + [Water] + aged_binder + fresh_binder.

        Args:
            spec: LayerSpec with binder_secondary set.

        Returns:
            LayerBuildResult.
        """
        if spec.binder_secondary is None:
            return LayerBuildResult(
                success=False,
                error_message="Scenarios D/E require binder_secondary",
            )

        try:
            work_dir = self.work_dir / f"layer_{spec.seed}"
            work_dir.mkdir(parents=True, exist_ok=True)

            crystal_slab = self._build_crystal(spec.crystal)
            lx, ly, _ = crystal_slab.box
            total_height = spec.get_total_height()
            layer_info = spec.get_layer_boundaries()

            water_molecules = 0
            if spec.water:
                water_molecules = self._calculate_water_molecules(spec.water, lx, ly)

            aged_info = self._calculate_binder_composition(spec.binder, lx, ly)
            fresh_info = self._calculate_binder_composition(spec.binder_secondary, lx, ly)

            output_path = work_dir / "layer_system.data"
            self._create_combined_data_file(
                output_path=output_path,
                spec=spec,
                crystal_slab=crystal_slab,
                water_molecules=water_molecules,
                binder_info=aged_info,
                binder_secondary_info=fresh_info,
                lx=lx,
                ly=ly,
                lz=total_height,
            )

            interface_area = (lx * ly) / 100
            total_binder_atoms = aged_info["total_atoms"] + fresh_info["total_atoms"]

            return LayerBuildResult(
                success=True,
                data_file_path=output_path,
                total_atoms=(crystal_slab.n_atoms + water_molecules * 3 + total_binder_atoms),
                box_dimensions=(lx, ly, total_height),
                layer_info=layer_info,
                crystal_atoms=crystal_slab.n_atoms,
                water_molecules=water_molecules,
                binder_atoms=total_binder_atoms,
                interface_area_nm2=interface_area,
            )
        except Exception as e:
            logger.error(f"Aged-fresh build failed: {e}")
            return LayerBuildResult(success=False, error_message=str(e))

    def _build_binder_binder(self, spec: LayerSpec) -> LayerBuildResult:
        """Build binder-binder system (Scenario F, internal cohesion).

        No crystal. Two binder layers for cohesive failure study.

        Args:
            spec: LayerSpec with binder_secondary set.

        Returns:
            LayerBuildResult.
        """
        if spec.binder_secondary is None:
            return LayerBuildResult(
                success=False,
                error_message="Scenario F requires binder_secondary",
            )

        try:
            work_dir = self.work_dir / f"layer_{spec.seed}"
            work_dir.mkdir(parents=True, exist_ok=True)

            lx = ly = spec.crystal.xy_size_angstrom  # Use crystal xy as reference
            total_height = spec.get_total_height()
            layer_info = spec.get_layer_boundaries()

            binder1_info = self._calculate_binder_composition(spec.binder, lx, ly)
            binder2_info = self._calculate_binder_composition(spec.binder_secondary, lx, ly)

            output_path = work_dir / "layer_system.data"
            total_binder_atoms = binder1_info["total_atoms"] + binder2_info["total_atoms"]

            # Write placeholder data file
            with open(output_path, "w") as f:
                f.write("LAMMPS Binder-Binder Layer System\n\n")
                f.write(f"# Layer type: {spec.layer_type.value}\n")
                f.write(f"# Temperature: {spec.temperature_k} K\n\n")
                f.write(f"{total_binder_atoms} atoms\n")
                f.write("0 bonds\n0 angles\n\n")
                f.write(f"0.0 {lx:.6f} xlo xhi\n")
                f.write(f"0.0 {ly:.6f} ylo yhi\n")
                f.write(f"0.0 {total_height:.6f} zlo zhi\n\n")
                f.write(f"# Binder 1 atoms: {binder1_info['total_atoms']}\n")
                f.write(f"# Binder 2 atoms: {binder2_info['total_atoms']}\n")
                for name, (z_min, z_max) in layer_info.items():
                    f.write(f"# {name}: z = {z_min:.2f} - {z_max:.2f}\n")

            interface_area = (lx * ly) / 100

            return LayerBuildResult(
                success=True,
                data_file_path=output_path,
                total_atoms=total_binder_atoms,
                box_dimensions=(lx, ly, total_height),
                layer_info=layer_info,
                crystal_atoms=0,
                water_molecules=0,
                binder_atoms=total_binder_atoms,
                interface_area_nm2=interface_area,
            )
        except Exception as e:
            logger.error(f"Binder-binder build failed: {e}")
            return LayerBuildResult(success=False, error_message=str(e))

    def build_interface(
        self,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        binder_thickness: float = 50.0,
        temperature_k: float = 298.0,
    ) -> LayerBuildResult:
        """
        Convenience method to build simple interface.

        Args:
            crystal_material: Crystal material
            binder_thickness: Binder layer thickness
            temperature_k: Temperature

        Returns:
            LayerBuildResult
        """
        spec = LayerSpec.create_interface(
            crystal_material=crystal_material,
            binder_thickness=binder_thickness,
        )
        spec.temperature_k = temperature_k
        return self.build(spec)

    def build_water_interface(
        self,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        water_thickness: float = 10.0,
        binder_thickness: float = 50.0,
        temperature_k: float = 298.0,
    ) -> LayerBuildResult:
        """
        Build interface with water layer.

        Args:
            crystal_material: Crystal material
            water_thickness: Water layer thickness
            binder_thickness: Binder thickness
            temperature_k: Temperature

        Returns:
            LayerBuildResult
        """
        spec = LayerSpec.create_water_interface(
            crystal_material=crystal_material,
            water_thickness=water_thickness,
            binder_thickness=binder_thickness,
        )
        spec.temperature_k = temperature_k
        return self.build(spec)


def generate_layer_exp_id(
    spec: LayerSpec,
    seed: int,
) -> str:
    """
    Generate experiment ID for layer study.

    Format: layer{n}_{material}_{ff_type}_{T}K_{binder}__h={hash8}

    Args:
        spec: Layer specification
        seed: Random seed

    Returns:
        Experiment ID string
    """
    from common.hashing import compute_content_hash

    n_layers = 3 if spec.layer_type == LayerType.THREE_LAYER else 2
    material = spec.crystal.material.value

    # Create hash from spec
    spec_str = f"{spec.to_dict()}{seed}"
    hash_val = compute_content_hash(spec_str, algorithm="md5", length=8)

    return (
        f"layer{n_layers}_{material}_bulk_ff_gaff2_T{int(spec.temperature_k)}K_binder__h={hash_val}"
    )
