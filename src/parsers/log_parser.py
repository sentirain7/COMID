"""
LAMMPS log file parser.

Parses LAMMPS log.lammps files to extract run information,
errors, and thermo data.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from common.logging import get_logger
from contracts.interfaces import AbstractLogParser

logger = get_logger("parsers.log_parser")


@dataclass
class RunInfo:
    """Information about a single LAMMPS run."""

    step_start: int
    step_end: int
    duration_seconds: float
    performance_ns_day: float
    total_atoms: int
    completed: bool
    error_message: str | None = None


@dataclass
class LogParseResult:
    """Result of parsing a LAMMPS log file."""

    lammps_version: str
    total_atoms: int
    runs: list[RunInfo]
    thermo_data: dict[str, list[float]]
    errors: list[str]
    warnings: list[str]
    completed: bool
    final_step: int
    total_time_seconds: float


class LogParser(AbstractLogParser):  # type: ignore[override]
    """
    Parser for LAMMPS log files.

    Extracts run information, thermodynamic data, and error messages.

    Note: AbstractLogParser.parse() declares return type ThermoData, but this
    implementation returns LogParseResult (richer structure used by all production
    callers). The type: ignore[override] annotation documents this intentional
    deviation; contracts/ cannot be modified (SSOT), and changing the return type
    would break all downstream consumers.
    """

    def __init__(self) -> None:
        """Initialize log parser."""
        self._thermo_columns: list[str] = []
        self._in_thermo_block = False

    def parse(self, log_file: Path) -> LogParseResult:
        """
        Parse a LAMMPS log file.

        Args:
            log_file: Path to log.lammps file

        Returns:
            LogParseResult with extracted data
        """
        log_file = Path(log_file)

        if not log_file.exists():
            return self._empty_result("Log file not found")

        content = log_file.read_text()
        lines = content.split("\n")

        return self._parse_lines(lines)

    def parse_tail(
        self,
        log_file: Path,
        bytes_to_read: int = 102400,
        max_points: int = 50,
    ) -> LogParseResult:
        """
        Parse only the tail of a LAMMPS log file.

        Optimized for real-time monitoring - reads only the last portion
        of the file instead of loading everything into memory.

        Args:
            log_file: Path to log.lammps file
            bytes_to_read: Number of bytes to read from end (default 100KB)
            max_points: Maximum thermo data points to keep (default 50)

        Returns:
            LogParseResult with extracted data from file tail
        """
        log_file = Path(log_file)

        if not log_file.exists():
            return self._empty_result("Log file not found")

        try:
            file_size = log_file.stat().st_size
            read_size = min(bytes_to_read, file_size)

            with open(log_file, "rb") as f:
                if file_size > read_size:
                    f.seek(-read_size, 2)  # Seek from end
                content = f.read().decode("utf-8", errors="replace")

            lines = content.split("\n")

            # If we started mid-line, skip the first partial line
            if file_size > read_size:
                lines = lines[1:]

            result = self._parse_lines(lines)

            # Limit thermo data to max_points
            for col in result.thermo_data:
                if len(result.thermo_data[col]) > max_points:
                    result.thermo_data[col] = result.thermo_data[col][-max_points:]

            return result

        except Exception as e:
            logger.warning(f"Failed to parse tail of {log_file}: {e}")
            return self._empty_result(f"Error: {e}")

    def _parse_lines(self, lines: list[str]) -> LogParseResult:
        """Parse log lines."""
        version = ""
        total_atoms = 0
        runs: list[RunInfo] = []
        thermo_data: dict[str, list[float]] = {}
        errors: list[str] = []
        warnings: list[str] = []
        completed = False
        final_step = 0
        total_time = 0.0

        for _i, line in enumerate(lines):
            line = line.strip()

            # Extract version
            if "LAMMPS" in line and "version" in line.lower():
                version = line

            # Extract atom count - look for lines like "100000 atoms"
            if "atoms" in line.lower():
                match = re.search(r"(\d+)\s+atoms", line, re.IGNORECASE)
                if match and total_atoms == 0:  # Only set if not already found
                    total_atoms = int(match.group(1))

            # Detect thermo header
            if self._is_thermo_header(line):
                self._thermo_columns = line.split()
                self._in_thermo_block = True
                for col in self._thermo_columns:
                    if col not in thermo_data:
                        thermo_data[col] = []
                continue

            # Parse thermo data
            if self._in_thermo_block and self._is_thermo_data(line):
                values = line.split()
                if len(values) == len(self._thermo_columns):
                    for col, val in zip(self._thermo_columns, values, strict=False):
                        try:
                            thermo_data[col].append(float(val))
                            if col.lower() == "step":
                                final_step = int(float(val))
                        except ValueError:
                            pass
            else:
                if self._in_thermo_block and line and not line.startswith("Loop"):
                    self._in_thermo_block = False

            # Detect run start
            if line.startswith("run") and "Running" not in line:
                try:
                    steps_match = re.search(r"run\s+(\d+)", line)
                    if steps_match:
                        pass
                except ValueError:
                    pass

            # Detect errors
            if "ERROR" in line or "error" in line.lower():
                if "ERROR:" in line:
                    errors.append(line)

            # Detect warnings
            if "WARNING" in line:
                warnings.append(line)

            # Detect performance
            if "Performance:" in line:
                match = re.search(r"(\d+\.?\d*)\s*ns/day", line)
                if match:
                    float(match.group(1))

            # Detect loop time
            if "Loop time" in line:
                match = re.search(r"Loop time of\s+(\d+\.?\d*)", line)
                if match:
                    loop_time = float(match.group(1))
                    total_time += loop_time

            # Detect completion
            if "Total wall time" in line:
                completed = True
                match = re.search(r"(\d+):(\d+):(\d+)", line)
                if match:
                    h, m, s = map(int, match.groups())
                    total_time = h * 3600 + m * 60 + s

        return LogParseResult(
            lammps_version=version,
            total_atoms=total_atoms,
            runs=runs,
            thermo_data=thermo_data,
            errors=errors,
            warnings=warnings,
            completed=completed,
            final_step=final_step,
            total_time_seconds=total_time,
        )

    def _is_thermo_header(self, line: str) -> bool:
        """Check if line is a thermo header.

        Recognizes standard LAMMPS thermo columns plus custom compute
        (c_*) and fix (f_*) column names, which appear in group/group
        energy decomposition and RNEMD viscosity outputs.
        """
        words = line.split()
        if len(words) < 2:
            return False

        # Common thermo columns (including energy decomposition variants)
        thermo_cols = {
            "Step",
            "Temp",
            "Press",
            "Volume",
            "Vol",
            "PotEng",
            "KinEng",
            "TotEng",
            "Density",
            "E_pair",
            "Epair",
            "E_mol",
            "Emol",
            "E_coul",
            "Ecoul",
            "E_vdwl",
            "Evdwl",
            "E_bond",
            "Ebond",
            "E_angle",
            "Eangle",
            "E_dihed",
            "Edihed",
            "E_imp",
            "Eimp",
            "E_improp",
            "Eimprop",
            "E_long",
            "Elong",
            "Enthalpy",
        }

        # Count matches: known columns + custom compute/fix columns (c_*, f_*)
        matches = 0
        for w in words:
            if w in thermo_cols or w.startswith("c_") or w.startswith("f_"):
                matches += 1

        return matches >= 2 and "Step" in words

    def _is_thermo_data(self, line: str) -> bool:
        """Check if line is thermo data."""
        if not line:
            return False

        words = line.split()
        if len(words) != len(self._thermo_columns):
            return False

        # First column should be step (integer)
        try:
            int(float(words[0]))
            return True
        except ValueError:
            return False

    def _empty_result(self, error: str) -> LogParseResult:
        """Return empty result with error."""
        return LogParseResult(
            lammps_version="",
            total_atoms=0,
            runs=[],
            thermo_data={},
            errors=[error],
            warnings=[],
            completed=False,
            final_step=0,
            total_time_seconds=0.0,
        )

    def get_final_values(self, result: LogParseResult) -> dict[str, float]:
        """Get final thermodynamic values."""
        final = {}
        for col, values in result.thermo_data.items():
            if values:
                final[col] = values[-1]
        return final

    def extract_final_values(self, log_file: str) -> dict[str, float]:
        """Extract final thermo values from log file (AbstractLogParser interface).

        Args:
            log_file: Path to LAMMPS log file

        Returns:
            Dictionary of final thermodynamic values
        """
        result = self.parse(Path(log_file))
        return self.get_final_values(result)

    def get_average_values(
        self,
        result: LogParseResult,
        last_n: int | None = None,
    ) -> dict[str, float]:
        """
        Get average thermodynamic values.

        Args:
            result: Parse result
            last_n: Only average last n values (for equilibrated data)

        Returns:
            Dictionary of averaged values
        """
        avg = {}
        for col, values in result.thermo_data.items():
            if values:
                if last_n:
                    values = values[-last_n:]
                avg[col] = sum(values) / len(values)
        return avg
