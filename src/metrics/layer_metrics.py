"""
Layer Metrics for interface studies.

Calculates adhesion energy, density profiles, and orientation order.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common.logging import get_logger

logger = get_logger("metrics.layer_metrics")


@dataclass
class AdhesionEnergyResult:
    """Result of adhesion energy calculation."""

    adhesion_energy: float  # mJ/m²
    work_of_adhesion: float  # mJ/m²
    interface_area: float  # nm²

    # Component energies
    e_total: float  # Total system energy (kcal/mol)
    e_crystal: float  # Crystal energy alone
    e_binder: float  # Binder energy alone
    e_water: float | None = None  # Water energy (if present)

    # Quality metrics
    uncertainty: float | None = None
    n_samples: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "adhesion_energy": self.adhesion_energy,
            "work_of_adhesion": self.work_of_adhesion,
            "interface_area": self.interface_area,
            "e_total": self.e_total,
            "e_crystal": self.e_crystal,
            "e_binder": self.e_binder,
            "e_water": self.e_water,
            "uncertainty": self.uncertainty,
            "n_samples": self.n_samples,
        }


@dataclass
class DensityProfileResult:
    """Result of density profile calculation."""

    z_bins: np.ndarray  # Bin centers (Å)
    density: np.ndarray  # Density values (g/cm³)
    bin_width: float  # Bin width (Å)
    axis: str = "z"

    # Layer boundaries detected
    interface_positions: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "z_bins": self.z_bins.tolist(),
            "density": self.density.tolist(),
            "bin_width": self.bin_width,
            "axis": self.axis,
            "interface_positions": self.interface_positions,
        }

    def to_storage_dict(self) -> tuple[dict[str, list[float]], dict[str, Any]]:
        """Convert to registry-normalized format for ArrayStorage.

        Returns:
            (data, metadata) tuple where data has columns 'z' and 'density'
            matching the registry array_columns, and metadata has the
            auxiliary fields.
        """
        data = {
            "z": self.z_bins.tolist(),
            "density": self.density.tolist(),
        }
        metadata = {
            "bin_width": self.bin_width,
            "axis": self.axis,
            "interface_positions": self.interface_positions,
        }
        return data, metadata

    def get_interface_width(self, threshold: float = 0.1) -> float:
        """
        Estimate interface width from density profile.

        Args:
            threshold: Density gradient threshold

        Returns:
            Interface width in Angstroms
        """
        # Calculate gradient
        gradient = np.abs(np.gradient(self.density, self.bin_width))

        # Find region where gradient is high
        high_gradient = gradient > threshold * np.max(gradient)
        if np.any(high_gradient):
            indices = np.where(high_gradient)[0]
            width = (indices[-1] - indices[0]) * self.bin_width
            return float(width)
        return 0.0


@dataclass
class OrientationOrderResult:
    """Result of orientation order calculation."""

    p2_order: float  # P2 Legendre order parameter (-0.5 to 1.0)
    z_bins: np.ndarray  # Bin centers
    p2_profile: np.ndarray  # P2 values along z

    # By molecule type
    by_type: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "p2_order": self.p2_order,
            "z_bins": self.z_bins.tolist(),
            "p2_profile": self.p2_profile.tolist(),
            "by_type": self.by_type,
        }


class AdhesionEnergyCalculator:
    """
    Calculator for adhesion energy at interfaces.

    Method: W_ad = (E_total - E_crystal - E_binder - E_water) / A
    """

    # Unit conversion: 1 kcal/mol/Å² = 694.77 mJ/m²
    # = 4184 J/kcal / N_A(6.02214e23 mol⁻¹) / 1e-20 (m²/Å²) × 1000 (mJ/J)
    #   = 0.69477 J/m² × 1000 = 694.77 mJ/m²
    # (Prior 6.9477e-2 was 1e4× too small for the mJ/m² unit — fixed v01.05.23.)
    KCAL_MOL_A2_TO_MJ_M2 = 694.77

    def __init__(self) -> None:
        """Initialize calculator."""
        pass

    def calculate(
        self,
        e_total: float,
        e_crystal: float,
        e_binder: float,
        interface_area_nm2: float,
        e_water: float | None = None,
    ) -> AdhesionEnergyResult:
        """
        Calculate adhesion energy.

        Args:
            e_total: Total system energy (kcal/mol)
            e_crystal: Crystal-only energy (kcal/mol)
            e_binder: Binder-only energy (kcal/mol)
            interface_area_nm2: Interface area (nm²)
            e_water: Water-only energy (kcal/mol), optional

        Returns:
            AdhesionEnergyResult
        """
        # Convert area to Å²
        area_A2 = interface_area_nm2 * 100

        # Calculate interaction energy
        e_components = e_crystal + e_binder
        if e_water is not None:
            e_components += e_water

        e_interaction = e_total - e_components

        # Convert to mJ/m²: E in kcal/mol, A in Å².
        # W [mJ/m²] = (E/A) * 694.77  (see KCAL_MOL_A2_TO_MJ_M2 derivation).
        adhesion_energy = e_interaction / area_A2 * self.KCAL_MOL_A2_TO_MJ_M2

        # Work of adhesion (positive for favorable adhesion)
        work_of_adhesion = -adhesion_energy

        return AdhesionEnergyResult(
            adhesion_energy=adhesion_energy,
            work_of_adhesion=work_of_adhesion,
            interface_area=interface_area_nm2,
            e_total=e_total,
            e_crystal=e_crystal,
            e_binder=e_binder,
            e_water=e_water,
        )

    def calculate_from_trajectory(
        self,
        energies: list[tuple[float, float, float, float]],
        interface_area_nm2: float,
        skip_fraction: float = 0.3,
    ) -> AdhesionEnergyResult:
        """
        Calculate adhesion energy from trajectory.

        Args:
            energies: List of (e_total, e_crystal, e_binder, e_water) tuples
            interface_area_nm2: Interface area
            skip_fraction: Fraction of trajectory to skip

        Returns:
            AdhesionEnergyResult with uncertainty
        """
        n_skip = int(len(energies) * skip_fraction)
        energies = energies[n_skip:]

        if len(energies) == 0:
            raise ValueError("No data after skipping equilibration")

        # Calculate for each frame
        adhesion_values = []
        for e_total, e_crystal, e_binder, e_water in energies:
            result = self.calculate(e_total, e_crystal, e_binder, interface_area_nm2, e_water)
            adhesion_values.append(result.adhesion_energy)

        # Statistics
        mean_adhesion = float(np.mean(adhesion_values))
        std_adhesion = float(np.std(adhesion_values))

        # Get average component energies
        avg_e_total = np.mean([e[0] for e in energies])
        avg_e_crystal = np.mean([e[1] for e in energies])
        avg_e_binder = np.mean([e[2] for e in energies])
        avg_e_water = np.mean([e[3] for e in energies]) if energies[0][3] is not None else None

        return AdhesionEnergyResult(
            adhesion_energy=mean_adhesion,
            work_of_adhesion=-mean_adhesion,
            interface_area=interface_area_nm2,
            e_total=float(avg_e_total),
            e_crystal=float(avg_e_crystal),
            e_binder=float(avg_e_binder),
            e_water=float(avg_e_water) if avg_e_water else None,
            uncertainty=std_adhesion,
            n_samples=len(energies),
        )


class DensityProfileCalculator:
    """
    Calculator for density profiles along an axis.
    """

    def __init__(self, bin_width: float = 1.0):
        """
        Initialize calculator.

        Args:
            bin_width: Bin width in Angstroms
        """
        self.bin_width = bin_width

    def calculate(
        self,
        positions: np.ndarray,
        masses: np.ndarray,
        box: tuple[float, float, float],
        axis: str = "z",
    ) -> DensityProfileResult:
        """
        Calculate density profile.

        Args:
            positions: Atom positions (N, 3)
            masses: Atom masses (N,)
            box: Box dimensions (lx, ly, lz)
            axis: Axis for profile ("x", "y", or "z")

        Returns:
            DensityProfileResult
        """
        axis_idx = {"x": 0, "y": 1, "z": 2}[axis]
        box_length = box[axis_idx]

        # Create bins
        n_bins = int(box_length / self.bin_width)
        bins = np.linspace(0, box_length, n_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2

        # Calculate density in each bin
        densities = np.zeros(n_bins)
        axis_coords = positions[:, axis_idx]

        # Cross-sectional area
        if axis == "z":
            area = box[0] * box[1]
        elif axis == "y":
            area = box[0] * box[2]
        else:
            area = box[1] * box[2]

        bin_volume = area * self.bin_width  # Å³

        for i in range(n_bins):
            mask = (axis_coords >= bins[i]) & (axis_coords < bins[i + 1])
            mass_in_bin = np.sum(masses[mask])  # g/mol

            # Convert to g/cm³
            # mass (g/mol) / N_A * 1e24 (Å³/cm³) / volume (Å³)
            densities[i] = mass_in_bin / 6.022e23 * 1e24 / bin_volume

        # Detect interfaces
        interfaces = self._detect_interfaces(bin_centers, densities)

        return DensityProfileResult(
            z_bins=bin_centers,
            density=densities,
            bin_width=self.bin_width,
            axis=axis,
            interface_positions=interfaces,
        )

    def _detect_interfaces(
        self,
        z_bins: np.ndarray,
        density: np.ndarray,
        threshold: float = 0.2,
    ) -> list[float]:
        """Detect interface positions from density profile."""
        interfaces = []

        # Calculate gradient
        gradient = np.gradient(density, self.bin_width)

        # Find peaks in absolute gradient
        abs_gradient = np.abs(gradient)
        max_grad = np.max(abs_gradient)

        if max_grad > 0:
            peaks = abs_gradient > threshold * max_grad

            # Find transitions
            in_peak = False
            peak_start = 0

            for i, is_peak in enumerate(peaks):
                if is_peak and not in_peak:
                    peak_start = i
                    in_peak = True
                elif not is_peak and in_peak:
                    # Peak ended, record center
                    peak_center = (peak_start + i) // 2
                    interfaces.append(float(z_bins[peak_center]))
                    in_peak = False

        return interfaces

    def calculate_from_trajectory(
        self,
        trajectory: list[tuple[np.ndarray, np.ndarray]],
        box: tuple[float, float, float],
        axis: str = "z",
        skip_fraction: float = 0.3,
    ) -> DensityProfileResult:
        """
        Calculate average density profile from trajectory.

        Args:
            trajectory: List of (positions, masses) tuples
            box: Box dimensions
            axis: Profile axis
            skip_fraction: Equilibration skip

        Returns:
            Averaged DensityProfileResult
        """
        n_skip = int(len(trajectory) * skip_fraction)
        trajectory = trajectory[n_skip:]

        profiles = []
        for positions, masses in trajectory:
            result = self.calculate(positions, masses, box, axis)
            profiles.append(result.density)

        # Average
        avg_density = np.mean(profiles, axis=0)

        # Get bin centers from last calculation
        result = self.calculate(trajectory[-1][0], trajectory[-1][1], box, axis)

        return DensityProfileResult(
            z_bins=result.z_bins,
            density=avg_density,
            bin_width=self.bin_width,
            axis=axis,
            interface_positions=self._detect_interfaces(result.z_bins, avg_density),
        )


class OrientationOrderCalculator:
    """
    Calculator for molecular orientation order parameter.

    Uses P2 Legendre polynomial: P2 = (3*cos²θ - 1) / 2
    where θ is angle between molecular axis and reference direction.
    """

    def __init__(self, reference_axis: str = "z"):
        """
        Initialize calculator.

        Args:
            reference_axis: Reference axis for orientation
        """
        self.reference_axis = reference_axis

    def calculate_p2(
        self,
        molecular_axes: np.ndarray,
    ) -> float:
        """
        Calculate P2 order parameter.

        Args:
            molecular_axes: Molecular axis vectors (N, 3), normalized

        Returns:
            P2 order parameter
        """
        axis_idx = {"x": 0, "y": 1, "z": 2}[self.reference_axis]

        # cos(θ) = dot product with reference axis
        cos_theta = molecular_axes[:, axis_idx]

        # P2 = <(3*cos²θ - 1) / 2>
        p2 = np.mean((3 * cos_theta**2 - 1) / 2)

        return float(p2)

    def calculate(
        self,
        positions: np.ndarray,
        molecule_ids: np.ndarray,
        head_atoms: np.ndarray,
        tail_atoms: np.ndarray,
        box: tuple[float, float, float],
        bin_width: float = 5.0,
    ) -> OrientationOrderResult:
        """
        Calculate orientation order profile.

        Args:
            positions: Atom positions (N, 3)
            molecule_ids: Molecule ID for each atom
            head_atoms: Indices of head atoms
            tail_atoms: Indices of tail atoms
            box: Box dimensions
            bin_width: Bin width for profile

        Returns:
            OrientationOrderResult
        """
        # Calculate molecular axes from head to tail
        axes = positions[head_atoms] - positions[tail_atoms]

        # Apply PBC
        for _i, axis in enumerate(axes):
            for j in range(3):
                if axis[j] > box[j] / 2:
                    axis[j] -= box[j]
                elif axis[j] < -box[j] / 2:
                    axis[j] += box[j]

        # Normalize
        norms = np.linalg.norm(axes, axis=1, keepdims=True)
        norms[norms == 0] = 1
        axes = axes / norms

        # Overall P2
        p2_overall = self.calculate_p2(axes)

        # P2 profile along z
        axis_idx = {"x": 0, "y": 1, "z": 2}[self.reference_axis]
        box_length = box[axis_idx]

        # Molecular center positions
        mol_centers = (positions[head_atoms] + positions[tail_atoms]) / 2
        z_coords = mol_centers[:, axis_idx]

        n_bins = int(box_length / bin_width)
        bins = np.linspace(0, box_length, n_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2

        p2_profile = np.zeros(n_bins)
        for i in range(n_bins):
            mask = (z_coords >= bins[i]) & (z_coords < bins[i + 1])
            if np.any(mask):
                p2_profile[i] = self.calculate_p2(axes[mask])

        return OrientationOrderResult(
            p2_order=p2_overall,
            z_bins=bin_centers,
            p2_profile=p2_profile,
        )


@dataclass
class LayerMetrics:
    """Container for all layer metrics."""

    adhesion_energy: AdhesionEnergyResult | None = None
    density_profile: DensityProfileResult | None = None
    orientation_order: OrientationOrderResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "adhesion_energy": self.adhesion_energy.to_dict() if self.adhesion_energy else None,
            "density_profile": self.density_profile.to_dict() if self.density_profile else None,
            "orientation_order": self.orientation_order.to_dict()
            if self.orientation_order
            else None,
        }

    def is_complete(self) -> bool:
        """Check if all metrics are calculated."""
        return all(
            [
                self.adhesion_energy is not None,
                self.density_profile is not None,
            ]
        )


def compute_cross_cut_interaction(
    e_inter_matrix: dict[tuple[int, int], float],
    layer_count: int,
    interface_area_nm2: float,
    cut_between: tuple[int, int],
) -> float:
    """Pairwise enthalpic cross-cut interaction proxy.

    Sums all pairwise inter-layer interactions crossing the specified
    cut plane, normalized by interface area.

    This is NOT thermodynamic work of adhesion (which requires
    separated-state energy difference or free energy methods).
    For rigorous adhesion energy, use tensile work_of_separation.

    Args:
        e_inter_matrix: Dict of (layer_i, layer_j) -> time-averaged
            E_inter (kcal/mol).  Keys must be ordered (min, max).
        layer_count: Total number of layers.
        interface_area_nm2: Interface area in nm².
        cut_between: Tuple (k, k+1) defining the cut plane between
            layer k and layer k+1.

    Returns:
        Cross-cut interaction energy proxy in mJ/m².
    """
    lower = set(range(cut_between[0] + 1))
    upper = set(range(cut_between[1], layer_count))
    cross_sum = sum(e_inter_matrix.get((min(i, j), max(i, j)), 0.0) for i in lower for j in upper)
    area_A2 = interface_area_nm2 * 100  # nm² → Å²
    if area_A2 <= 0:
        return 0.0
    # kcal/mol/Å² → mJ/m²: single SSOT for the conversion factor (694.77).
    return -cross_sum / area_A2 * AdhesionEnergyCalculator.KCAL_MOL_A2_TO_MJ_M2
