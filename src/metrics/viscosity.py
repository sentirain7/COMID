"""
Viscosity calculator for RNEMD (Muller-Plathe) simulations.

Computes dynamic viscosity from:
1. Cumulative momentum transfer (f_viscosity from LAMMPS thermo)
2. Velocity profile (from fix ave/chunk output)
3. Box geometry

Uses the Muller-Plathe reverse NEMD method (J. Chem. Phys. 111, 8252, 1999):
    η = J_p / |dv_x/dz|
where
    J_p = d(f_viscosity)/dt / (2 × Lx × Ly)   (momentum flux per area per time)
    dv_x/dz = streaming velocity gradient       (from velocity profile)

Unit conversion (LAMMPS real → mPa·s):
    1 g/(mol·fs·Å) = 1.661e-2 Pa·s = 16.61 mPa·s
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common.logging import get_logger
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import MetricResult

logger = get_logger("metrics.viscosity")

# Unit conversion factor: LAMMPS real viscosity unit → mPa·s
# g/(mol·fs·Å) → Pa·s:
#   (1e-3 kg / 6.022e23) / (1e-15 s × 1e-10 m) = 1.661e-2 Pa·s
# Pa·s → mPa·s: × 1000
_REAL_TO_MPAS = (1e-3 / 6.022e23) / (1e-15 * 1e-10) * 1e3  # ≈ 16.61


@dataclass
class VelocityProfile:
    """Averaged velocity profile from fix ave/chunk output."""

    z: np.ndarray  # bin centre coordinates (Å)
    vx: np.ndarray  # average streaming velocity (Å/fs)
    n_blocks: int  # number of time blocks averaged


@dataclass
class ViscosityResult:
    """Result from RNEMD viscosity calculation."""

    viscosity_mPas: float | None  # Dynamic viscosity in mPa·s
    momentum_flux_rate: float | None  # d(f_viscosity)/dt [g·Å/(mol·fs²)]
    velocity_gradient: float | None  # |dv_x/dz| [1/fs]
    flux_fit_r_squared: float | None
    gradient_fit_r_squared: float | None
    method: str = "rnemd_muller_plathe"
    n_thermo_samples: int = 0
    n_profile_blocks: int = 0
    box_area_A2: float | None = None  # Lx × Ly
    error: str | None = None


class ViscosityCalculator:
    """Calculator for dynamic viscosity via Muller-Plathe RNEMD.

    The Muller-Plathe method swaps momenta between box slabs to
    create a known momentum flux.  The viscosity is then:

        η = d(f_viscosity)/dt / (2 × A_cross × |dv_x/dz|)

    Args:
        skip_fraction: Fraction of data to skip (initial transient).
        registry: MetricsRegistry for SSOT name/unit validation.
    """

    _METRIC_NAME = "viscosity"

    def __init__(
        self,
        skip_fraction: float = 0.3,
        registry: MetricsRegistry | None = None,
    ) -> None:
        self.skip_fraction = skip_fraction
        self.registry = registry or MetricsRegistry()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute_from_rnemd(
        self,
        f_viscosity_values: list[float],
        time_fs: np.ndarray,
        box_area_A2: float,
        velocity_profile: VelocityProfile | None = None,
    ) -> ViscosityResult:
        """Compute viscosity from RNEMD data.

        Args:
            f_viscosity_values: Cumulative transferred momentum time series
                from LAMMPS ``f_viscosity`` thermo column (g·Å/(mol·fs)).
            time_fs: Corresponding time values in **femtoseconds**.
            box_area_A2: Cross-sectional area Lx × Ly (ų).
            velocity_profile: Averaged velocity profile from ``fix ave/chunk``.
                If ``None``, only the momentum flux rate is computed.

        Returns:
            ViscosityResult with viscosity (if profile available) or partial data.
        """
        n_total = len(f_viscosity_values)
        if n_total < 3:
            return self._error_result(
                "Insufficient thermo samples for viscosity (<3)",
                n_total,
                0,
                box_area_A2,
            )

        # Skip transient regime
        start = int(n_total * self.skip_fraction)
        if start >= n_total - 2:
            start = max(0, n_total - 3)

        f_vals = np.asarray(f_viscosity_values[start:], dtype=np.float64)
        t_vals = np.asarray(time_fs[start:], dtype=np.float64)

        # Remove NaN / Inf
        valid = np.isfinite(f_vals) & np.isfinite(t_vals)
        if valid.sum() < 3:
            return self._error_result(
                "Insufficient valid (non-NaN/Inf) samples",
                int(valid.sum()),
                0,
                box_area_A2,
            )
        f_vals = f_vals[valid]
        t_vals = t_vals[valid]
        n_used = len(f_vals)

        # Linear fit of f_viscosity vs time → momentum flux rate
        flux_slope, flux_r2 = self._linear_fit(t_vals, f_vals)
        if flux_slope is None:
            return self._error_result(
                "Linear fit of f_viscosity vs time failed",
                n_used,
                0,
                box_area_A2,
            )

        # Velocity gradient from profile
        vel_gradient: float | None = None
        grad_r2: float | None = None
        n_profiles = 0
        if velocity_profile is not None:
            vel_gradient, grad_r2 = self._compute_velocity_gradient(
                velocity_profile,
            )
            n_profiles = velocity_profile.n_blocks

        # Compute viscosity
        viscosity_mPas: float | None = None
        error: str | None = None

        if vel_gradient is not None and abs(vel_gradient) > 1e-30:
            # η [g/(mol·fs·Å)] = |slope| / (2 × A × |dv/dz|)
            eta_raw = abs(flux_slope) / (2.0 * box_area_A2 * abs(vel_gradient))
            viscosity_mPas = float(eta_raw * _REAL_TO_MPAS)
            if viscosity_mPas <= 0:
                error = "Computed viscosity ≤ 0"
                viscosity_mPas = None
        elif velocity_profile is None:
            error = "No velocity profile available — cannot compute viscosity"
        else:
            error = "Velocity gradient ≈ 0 — cannot compute viscosity"

        return ViscosityResult(
            viscosity_mPas=viscosity_mPas,
            momentum_flux_rate=float(flux_slope),
            velocity_gradient=vel_gradient,
            flux_fit_r_squared=flux_r2,
            gradient_fit_r_squared=grad_r2,
            method="rnemd_muller_plathe",
            n_thermo_samples=n_used,
            n_profile_blocks=n_profiles,
            box_area_A2=box_area_A2,
            error=error,
        )

    # ------------------------------------------------------------------
    # Velocity profile parsing
    # ------------------------------------------------------------------

    def parse_velocity_profile(self, filepath: Path) -> VelocityProfile | None:
        """Parse ``fix ave/chunk`` velocity profile output.

        Expected file format (one or more blocks)::

            # comment lines
            timestep  n_chunks  total_count
            chunk_id  coord1  ncount  vx
            ...

        Args:
            filepath: Path to the velocity profile file.

        Returns:
            Averaged VelocityProfile over steady-state blocks, or None.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return None

        try:
            text = filepath.read_text()
        except OSError:
            logger.warning(f"Cannot read velocity profile: {filepath}")
            return None

        lines = text.strip().split("\n")
        blocks: list[tuple[list[float], list[float]]] = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            # Skip comments and blank lines
            if not line or line.startswith("#"):
                i += 1
                continue

            # Block header: timestep  n_chunks  total_count
            parts = line.split()
            if len(parts) == 3:
                try:
                    n_chunks = int(parts[1])
                except ValueError:
                    i += 1
                    continue

                z_vals: list[float] = []
                vx_vals: list[float] = []
                for j in range(1, n_chunks + 1):
                    if i + j >= len(lines):
                        break
                    data_parts = lines[i + j].strip().split()
                    if len(data_parts) >= 4:
                        try:
                            z_vals.append(float(data_parts[1]))  # Coord1
                            vx_vals.append(float(data_parts[3]))  # vx
                        except (ValueError, IndexError):
                            pass

                if z_vals:
                    blocks.append((z_vals, vx_vals))
                i += n_chunks + 1
            else:
                i += 1

        if not blocks:
            return None

        # Average over steady-state blocks (skip initial transient)
        n_blocks = len(blocks)
        skip = max(1, int(n_blocks * self.skip_fraction))
        steady = blocks[skip:] if skip < n_blocks else blocks[-1:]

        z_arr = np.array(steady[0][0], dtype=np.float64)
        vx_sum = np.zeros_like(z_arr)
        for _, vx in steady:
            vx_sum += np.array(vx, dtype=np.float64)
        vx_avg = vx_sum / len(steady)

        return VelocityProfile(z=z_arr, vx=vx_avg, n_blocks=n_blocks)

    # ------------------------------------------------------------------
    # Velocity gradient extraction
    # ------------------------------------------------------------------

    def _compute_velocity_gradient(
        self,
        profile: VelocityProfile,
    ) -> tuple[float | None, float | None]:
        """Extract velocity gradient from the first half of the profile.

        The Muller-Plathe method creates a triangular velocity profile:
        linear increase from z=0 to z≈Lz/2, then decrease.
        We fit the first half to get the gradient.

        Returns:
            (|gradient| in 1/fs, R²)
        """
        z = profile.z
        vx = profile.vx

        if len(z) < 4:
            return None, None

        # Use first half (ascending portion of triangular profile)
        z_mid = (z[0] + z[-1]) / 2.0
        half_mask = z <= z_mid
        z_half = z[half_mask]
        vx_half = vx[half_mask]

        if len(z_half) < 3:
            return None, None

        gradient, r2 = self._linear_fit(z_half, vx_half)
        if gradient is None:
            return None, None
        return abs(gradient), r2

    # ------------------------------------------------------------------
    # Box dimensions helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_box_area_from_log(log_content: str) -> float | None:
        """Extract Lx × Ly from LAMMPS log (orthogonal box line).

        Searches for the *last* occurrence of the box specification,
        which corresponds to the state after NPT equilibration
        (i.e. the box used during the viscosity NVT/NEMD run).

        Args:
            log_content: Full text of log.lammps.

        Returns:
            Cross-sectional area Lx × Ly (ų), or None.
        """
        pattern = (
            r"orthogonal box\s*=\s*"
            r"\(\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*\)\s*to\s*"
            r"\(\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*\)"
        )
        matches = list(re.finditer(pattern, log_content))
        if not matches:
            return None

        last = matches[-1]
        xlo, ylo = float(last.group(1)), float(last.group(2))
        xhi, yhi = float(last.group(4)), float(last.group(5))
        lx = xhi - xlo
        ly = yhi - ylo
        if lx <= 0 or ly <= 0:
            return None
        return lx * ly

    @staticmethod
    def estimate_box_area_from_volume(volume_A3: float) -> float:
        """Estimate Lx × Ly assuming a cubic box: A = V^(2/3).

        Args:
            volume_A3: Box volume in ų.

        Returns:
            Estimated cross-sectional area (ų).
        """
        if volume_A3 <= 0:
            return 0.0
        return float(volume_A3 ** (2.0 / 3.0))

    # ------------------------------------------------------------------
    # Thermo column discovery
    # ------------------------------------------------------------------

    @staticmethod
    def find_f_viscosity_column(
        thermo_data: dict[str, list[float]],
    ) -> str | None:
        """Find the f_viscosity column in thermo data.

        LAMMPS names the column ``f_<fix_id>``.  The fix ID may include
        a step index suffix (e.g. ``f_viscosity_3``).

        Args:
            thermo_data: Parsed thermo columns.

        Returns:
            Column name, or None if not found.
        """
        for col in thermo_data:
            if col.startswith("f_viscosity") or col == "f_vis":
                return col
        return None

    # ------------------------------------------------------------------
    # Metric creation (registry-based SSOT)
    # ------------------------------------------------------------------

    def create_scalar_metric(
        self,
        result: ViscosityResult,
        namespace: str = "bulk_ff_gaff2",
    ) -> MetricResult | None:
        """Create scalar MetricResult for viscosity.

        Args:
            result: Viscosity calculation result.
            namespace: Metric namespace.

        Returns:
            MetricResult or None if viscosity not available.
        """
        if result.viscosity_mPas is None:
            return None

        name = self._METRIC_NAME
        is_valid, error = self.registry.validate_metric(
            name=name,
            unit=self.registry.get_unit(name),
            namespace=namespace,
        )
        if not is_valid:
            logger.warning(f"Registry validation failed for {name}: {error}")
            return None

        return MetricResult(
            metric_name=name,
            value=result.viscosity_mPas,
            unit=self.registry.get_unit(name),
            namespace=namespace,
        )

    # ------------------------------------------------------------------
    # Metadata for non-blocking error tracking
    # ------------------------------------------------------------------

    @staticmethod
    def get_metadata(result: ViscosityResult) -> dict[str, str | float | None]:
        """Build metadata dict for viscosity calculation status.

        Always records method and parse status.  On failure, includes
        the error message and any partial results (flux rate, gradient).

        Args:
            result: Viscosity calculation result.

        Returns:
            Metadata dict suitable for experiment record.
        """
        meta: dict[str, str | float | None] = {
            "viscosity_method": result.method,
            "viscosity_parse_status": (
                "success" if result.viscosity_mPas is not None else "failed"
            ),
        }
        if result.error:
            meta["viscosity_error"] = result.error
        if result.momentum_flux_rate is not None:
            meta["viscosity_momentum_flux_rate"] = result.momentum_flux_rate
        if result.flux_fit_r_squared is not None:
            meta["viscosity_flux_r2"] = result.flux_fit_r_squared
        if result.velocity_gradient is not None:
            meta["viscosity_velocity_gradient"] = result.velocity_gradient
        if result.gradient_fit_r_squared is not None:
            meta["viscosity_gradient_r2"] = result.gradient_fit_r_squared
        if result.n_thermo_samples:
            meta["viscosity_n_samples"] = result.n_thermo_samples
        return meta

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _linear_fit(
        x: np.ndarray,
        y: np.ndarray,
    ) -> tuple[float | None, float | None]:
        """Robust linear least-squares fit.

        Returns:
            (slope, R²) or (None, None) on failure.
        """
        if len(x) < 2:
            return None, None
        try:
            coeffs = np.polyfit(x, y, 1)
        except (np.linalg.LinAlgError, ValueError):
            return None, None

        slope = float(coeffs[0])
        y_pred = np.polyval(coeffs, x)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return slope, r2

    @staticmethod
    def _error_result(
        msg: str,
        n_samples: int = 0,
        n_profiles: int = 0,
        area: float | None = None,
    ) -> ViscosityResult:
        return ViscosityResult(
            viscosity_mPas=None,
            momentum_flux_rate=None,
            velocity_gradient=None,
            flux_fit_r_squared=None,
            gradient_fit_r_squared=None,
            n_thermo_samples=n_samples,
            n_profile_blocks=n_profiles,
            box_area_A2=area,
            error=msg,
        )
