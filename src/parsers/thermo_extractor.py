"""
Thermodynamic data extractor.

Extracts specific thermodynamic quantities from parsed log data.
"""

from dataclasses import dataclass

from common.logging import get_logger
from parsers.stats_utils import (
    apply_time_window,
    compute_mean_std,
    get_default_dt_fs,
    get_default_thermo_interval,
    get_default_window_ps,
)

logger = get_logger("parsers.thermo_extractor")


@dataclass
class ThermoSummary:
    """Summary of thermodynamic data."""

    temperature_K: float
    temperature_std: float
    pressure_atm: float
    pressure_std: float
    density_gcc: float
    density_std: float
    total_energy: float
    potential_energy: float
    kinetic_energy: float
    volume_A3: float
    n_samples: int


class ThermoExtractor:
    """
    Extractor for thermodynamic quantities from LAMMPS data.

    Provides methods for extracting and analyzing thermo data
    from parsed log files.
    """

    def __init__(
        self,
        skip_fraction: float = 0.2,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ):
        """
        Initialize extractor.

        Args:
            skip_fraction: Fraction of data to skip for equilibration (deprecated)
            window_ps: Time window from end for averaging (ps). Default from SSOT.
            dt_fs: Timestep in femtoseconds. Default from SSOT.
            thermo_interval: Steps between thermo outputs. Default: 1000.
        """
        self.skip_fraction = skip_fraction
        self.window_ps = window_ps if window_ps is not None else get_default_window_ps()
        self.dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        self.thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )

    def extract_summary(
        self,
        thermo_data: dict[str, list[float]],
        skip_fraction: float | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> ThermoSummary:
        """
        Extract summary statistics from thermo data.

        Uses the last window_ps of data for stable averaging, avoiding
        contamination from NVT/equilibration phases.

        Args:
            thermo_data: Dictionary of thermo columns to values
            skip_fraction: Deprecated. Fraction of data to skip from start.
                          If provided, uses old behavior for backward compatibility.
            window_ps: Time window from end of simulation (ps).
                       Default: 200 ps (from tier policy density_window_ps).
            dt_fs: Timestep in femtoseconds. Default: 1.0 fs.
            thermo_interval: Steps between thermo outputs. Default: 1000.

        Returns:
            ThermoSummary with averaged values
        """
        # Process data with windowing
        processed = {}
        n_samples = 0

        for col, values in thermo_data.items():
            if values:
                processed[col] = self._apply_window(
                    values, skip_fraction, window_ps, dt_fs, thermo_interval
                )
                n_samples = max(n_samples, len(processed[col]))

        # Extract values with defaults
        temp = self._get_values(processed, ["Temp", "T", "temperature"])
        press = self._get_values(processed, ["Press", "P", "pressure"])
        density = self._get_values(processed, ["Density", "density", "Rho"])
        total_e = self._get_values(processed, ["TotEng", "Etotal", "E_total"])
        pot_e = self._get_values(processed, ["PotEng", "PE", "E_pot"])
        kin_e = self._get_values(processed, ["KinEng", "KE", "E_kin"])
        volume = self._get_values(processed, ["Volume", "Vol", "V"])

        return ThermoSummary(
            temperature_K=self._mean(temp),
            temperature_std=self._std(temp),
            pressure_atm=self._mean(press),
            pressure_std=self._std(press),
            density_gcc=self._mean(density),
            density_std=self._std(density),
            total_energy=self._mean(total_e),
            potential_energy=self._mean(pot_e),
            kinetic_energy=self._mean(kin_e),
            volume_A3=self._mean(volume),
            n_samples=n_samples,
        )

    def extract_column(
        self,
        thermo_data: dict[str, list[float]],
        column_names: list[str],
        skip_fraction: float | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> list[float]:
        """
        Extract a specific column from thermo data.

        Args:
            thermo_data: Thermo data dictionary
            column_names: List of possible column names (tries in order)
            skip_fraction: Deprecated. Fraction to skip from start.
            window_ps: Time window from end (ps).
            dt_fs: Timestep in femtoseconds.
            thermo_interval: Steps between thermo outputs.

        Returns:
            List of values for the column
        """
        values = self._get_values(thermo_data, column_names)
        return self._apply_window(values, skip_fraction, window_ps, dt_fs, thermo_interval)

    def extract_energy_components(
        self,
        thermo_data: dict[str, list[float]],
        skip_fraction: float | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> dict[str, float]:
        """
        Extract energy components.

        Args:
            thermo_data: Thermo data dictionary
            skip_fraction: Deprecated. Fraction to skip from start.
            window_ps: Time window from end (ps).
            dt_fs: Timestep in femtoseconds.
            thermo_interval: Steps between thermo outputs.

        Returns:
            Dictionary of energy components
        """
        components = {}

        energy_cols = [
            ("E_bond", ["E_bond", "Ebond"]),
            ("E_angle", ["E_angle", "Eangle"]),
            ("E_dihed", ["E_dihed", "Edihed", "E_dihedral"]),
            ("E_imp", ["E_imp", "Eimp", "E_improp", "Eimprop", "E_improper"]),
            ("E_vdwl", ["E_vdwl", "Evdwl", "E_vdW"]),
            ("E_coul", ["E_coul", "Ecoul", "E_coulomb"]),
            ("E_pair", ["E_pair", "Epair"]),
            ("E_mol", ["E_mol", "Emol"]),
            ("E_long", ["E_long", "Elong"]),
            ("PotEng", ["PotEng", "PE"]),
            ("KinEng", ["KinEng", "KE"]),
            ("TotEng", ["TotEng", "Etotal"]),
        ]

        for name, aliases in energy_cols:
            values = self._get_values(thermo_data, aliases)
            if values:
                windowed = self._apply_window(
                    values, skip_fraction, window_ps, dt_fs, thermo_interval
                )
                components[name] = self._mean(windowed)

        return components

    def extract_full_trajectory(
        self,
        thermo_data: dict[str, list[float]],
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> dict[str, list[float]]:
        """
        Extract full trajectory data without windowing.

        Returns all time series data with calculated time values.
        Useful for plotting density vs time graphs.

        Args:
            thermo_data: Thermo data dictionary
            dt_fs: Timestep in femtoseconds
            thermo_interval: Steps between thermo outputs

        Returns:
            Dictionary with 'time_ps' and all thermo columns
        """
        eff_dt_fs = dt_fs if dt_fs is not None else self.dt_fs
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else self.thermo_interval
        )

        result = {}

        # Get step values if available, otherwise use index
        steps = self._get_values(thermo_data, ["Step", "step"])
        if steps:
            # Calculate time from steps
            ps_per_step = eff_dt_fs / 1000.0  # fs to ps
            result["time_ps"] = [s * ps_per_step for s in steps]
        else:
            # Estimate time from sample index
            ps_per_sample = (eff_dt_fs * eff_thermo_interval) / 1000.0
            first_col = next((v for v in thermo_data.values() if v), [])
            result["time_ps"] = [i * ps_per_sample for i in range(len(first_col))]

        # Copy all thermo columns
        column_mapping = {
            "density_gcc": ["Density", "density", "Rho"],
            "temperature_K": ["Temp", "T", "temperature"],
            "pressure_atm": ["Press", "P", "pressure"],
            "volume_A3": ["Volume", "Vol", "V"],
            "total_energy": ["TotEng", "Etotal", "E_total"],
            "potential_energy": ["PotEng", "PE", "E_pot"],
            "kinetic_energy": ["KinEng", "KE", "E_kin"],
            # Energy decomposition (present when thermo_style includes components)
            "ebond": ["E_bond", "Ebond"],
            "eangle": ["E_angle", "Eangle"],
            "edihed": ["E_dihed", "Edihed"],
            "eimp": ["E_imp", "Eimp", "E_improp"],
            "evdwl": ["E_vdwl", "Evdwl"],
            "ecoul": ["E_coul", "Ecoul"],
            "epair": ["E_pair", "Epair"],
            "emol": ["E_mol", "Emol"],
            "elong": ["E_long", "Elong"],
        }

        for output_name, aliases in column_mapping.items():
            values = self._get_values(thermo_data, aliases)
            if values:
                result[output_name] = list(values)

        return result

    def is_equilibrated(
        self,
        thermo_data: dict[str, list[float]],
        property_name: str = "TotEng",
        window_size: int = 100,
        tolerance: float = 0.01,
    ) -> bool:
        """
        Check if simulation has equilibrated.

        Uses drift analysis on the specified property.

        Args:
            thermo_data: Thermo data dictionary
            property_name: Property to check
            window_size: Size of averaging window
            tolerance: Relative drift tolerance

        Returns:
            True if equilibrated
        """
        values = self._get_values(thermo_data, [property_name])

        if len(values) < 2 * window_size:
            return False

        # Compare first and last window averages
        first_window = values[:window_size]
        last_window = values[-window_size:]

        first_mean = sum(first_window) / len(first_window)
        last_mean = sum(last_window) / len(last_window)

        if first_mean == 0:
            return abs(last_mean) < tolerance

        relative_drift = abs(last_mean - first_mean) / abs(first_mean)
        return relative_drift < tolerance

    def _apply_window(
        self,
        values: list[float],
        skip_fraction: float | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> list[float]:
        """
        Apply time windowing to a list of values.

        Delegates to stats_utils.apply_time_window for consistency.

        Args:
            values: Input data values
            skip_fraction: Deprecated. Fraction to skip from start.
            window_ps: Time window from end (ps).
            dt_fs: Timestep in femtoseconds.
            thermo_interval: Steps between thermo outputs.

        Returns:
            Windowed subset of values
        """
        eff_window_ps = window_ps if window_ps is not None else self.window_ps
        eff_dt_fs = dt_fs if dt_fs is not None else self.dt_fs
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else self.thermo_interval
        )

        return apply_time_window(
            values,
            window_ps=eff_window_ps,
            dt_fs=eff_dt_fs,
            thermo_interval=eff_thermo_interval,
            skip_fraction=skip_fraction,
        )

    def _get_values(
        self,
        data: dict[str, list[float]],
        aliases: list[str],
    ) -> list[float]:
        """Get values from data using multiple possible column names."""
        for alias in aliases:
            if alias in data:
                return data[alias]
        return []

    def _mean(self, values: list[float]) -> float:
        """Calculate mean of values."""
        mean, _ = compute_mean_std(values)
        return mean

    def _std(self, values: list[float]) -> float:
        """Calculate standard deviation of values (Bessel's correction)."""
        _, std = compute_mean_std(values)
        return std
