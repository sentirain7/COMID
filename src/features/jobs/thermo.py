"""Thermo data extraction helpers."""

import re
from collections.abc import Sequence
from pathlib import Path

_STAGE_RE = re.compile(r"@@STAGE\s+(\d+)\s+(\w+)")


def parse_stage_marker(log_file_path: str | None) -> tuple[int, str] | None:
    """Parse last @@STAGE marker from log tail.

    Reads the final 100KB of the log file (same range as parse_thermo_tail)
    and returns the last @@STAGE marker found.

    Args:
        log_file_path: Path to LAMMPS log file, or None.

    Returns:
        (0-based stage index, stage name) or None if not found.
    """
    if not log_file_path:
        return None

    path = Path(log_file_path)
    if not path.exists():
        return None

    try:
        file_size = path.stat().st_size
        read_size = min(file_size, 102400)
        with open(path, "rb") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            tail = f.read(read_size).decode("utf-8", errors="replace")
    except OSError:
        return None

    for line in reversed(tail.splitlines()):
        m = _STAGE_RE.match(line.strip())
        if m:
            return (int(m.group(1)), m.group(2))

    return None


def _safe_get(
    values: Sequence[float] | None, index: int, default: float | None = None
) -> float | None:
    """Safely read sequence value at index with default fallback."""
    if values is None:
        return default
    try:
        return float(values[index])
    except (IndexError, TypeError, ValueError):
        return default


def parse_thermo_tail(
    log_file_path: str | None,
) -> tuple[list[dict], int, float | None, float | None, float | None, float | None]:
    """Parse recent thermo tail from log file path."""
    thermo_data: list[dict] = []
    current_step = 0
    temperature = None
    pressure = None
    density = None
    energy = None

    if not log_file_path:
        return thermo_data, current_step, temperature, pressure, density, energy

    from parsers.log_parser import LogParser

    log_path = Path(log_file_path)
    if not log_path.exists():
        return thermo_data, current_step, temperature, pressure, density, energy

    parser = LogParser()
    result = parser.parse_tail(log_path, bytes_to_read=102400, max_points=50)
    td = result.thermo_data

    if td and "Step" in td and len(td["Step"]) > 0:
        steps = td.get("Step", [])
        n_points = len(steps)
        if n_points <= 0:
            return thermo_data, current_step, temperature, pressure, density, energy

        try:
            current_step = int(steps[-1])
        except (TypeError, ValueError, IndexError):
            current_step = 0
        temperature = _safe_get(td.get("Temp"), -1, None)
        pressure = _safe_get(td.get("Press"), -1, None)
        density = _safe_get(td.get("Density"), -1, None)
        energy = _safe_get(td.get("PotEng"), -1, None)

        for i in range(n_points):
            thermo_data.append(
                {
                    "step": int(_safe_get(steps, i, 0.0)),
                    "temperature": _safe_get(td.get("Temp"), i, None),
                    "pressure": _safe_get(td.get("Press"), i, None),
                    "density": _safe_get(td.get("Density"), i, None),
                    "energy": _safe_get(td.get("PotEng"), i, None),
                }
            )

    return thermo_data, current_step, temperature, pressure, density, energy
