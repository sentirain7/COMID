"""Parser for LAMMPS stress-strain output from tensile tests (Phase 4.3)."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from contracts.errors import ErrorCode, ParserError


@dataclass
class StressStrainData:
    """Parsed stress-strain data."""

    strain: np.ndarray  # Engineering strain (dimensionless)
    stress_MPa: np.ndarray  # Engineering stress (MPa)
    n_points: int

    @property
    def peak_stress_MPa(self) -> float:
        """Ultimate tensile strength (max stress)."""
        return float(np.max(self.stress_MPa))

    @property
    def peak_strain(self) -> float:
        """Strain at peak stress (ductility)."""
        return float(self.strain[np.argmax(self.stress_MPa)])

    @property
    def elastic_modulus_GPa(self) -> float | None:
        """Young's modulus from initial linear region (0~2% strain).

        Returns None if fewer than 3 data points in the linear region.
        """
        mask = self.strain <= 0.02
        if np.sum(mask) < 3:
            return None
        coeffs = np.polyfit(self.strain[mask], self.stress_MPa[mask], 1)
        return float(coeffs[0] / 1000.0)  # MPa -> GPa

    @property
    def toughness_MJ_m3(self) -> float:
        """Area under stress-strain curve (engineering toughness).

        Unit: MJ/m3 (= MPa, since strain is dimensionless).
        """
        _trapz = getattr(np, "trapezoid", None) or np.trapz
        return float(_trapz(self.stress_MPa, self.strain))


class StressStrainParser:
    """Parser for LAMMPS fix print stress-strain output files.

    Expected format:
        # strain stress_MPa    (header line)
        0.001 12.5
        0.002 25.1
        ...
    """

    def parse(self, file_path: Path) -> StressStrainData:
        """Parse stress_strain_*.dat file.

        Args:
            file_path: Path to stress-strain data file.

        Returns:
            StressStrainData with validated arrays.

        Raises:
            ParserError: If file is empty, has insufficient data, or malformed.
        """
        if not file_path.exists():
            raise ParserError(
                code=ErrorCode.DUMP_PARSE_FAILED,
                message=f"Stress-strain file not found: {file_path}",
            )

        try:
            data = np.loadtxt(file_path, comments="#")
        except ValueError:
            # Robust fallback for files with a non-comment title/header line.
            try:
                data = np.loadtxt(file_path, comments="#", skiprows=1)
            except ValueError as e:
                raise ParserError(
                    code=ErrorCode.DUMP_PARSE_FAILED,
                    message=f"Malformed stress-strain file: {file_path}: {e}",
                ) from e

        if data.size == 0:
            raise ParserError(
                code=ErrorCode.DUMP_PARSE_FAILED,
                message=f"Empty stress-strain file: {file_path}",
            )

        # Handle 0-D scalar (single value): insufficient columns
        if data.ndim == 0:
            raise ParserError(
                code=ErrorCode.DUMP_PARSE_FAILED,
                message="Stress-strain file needs >= 2 columns, got 1",
            )

        # Handle single-row case: np.loadtxt returns 1D array
        if data.ndim == 1:
            if data.shape[0] < 2:
                raise ParserError(
                    code=ErrorCode.DUMP_PARSE_FAILED,
                    message=f"Stress-strain file needs >= 2 columns, got {data.shape[0]}",
                )
            data = data.reshape(1, -1)

        if data.shape[1] < 2:
            raise ParserError(
                code=ErrorCode.DUMP_PARSE_FAILED,
                message=f"Stress-strain file needs >= 2 columns, got {data.shape[1]}",
            )

        return StressStrainData(
            strain=data[:, 0],
            stress_MPa=data[:, 1],
            n_points=len(data),
        )
