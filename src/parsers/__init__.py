"""
LAMMPS output parsers.

This module provides tools for parsing LAMMPS log files,
dump files, and extracting thermodynamic data.
"""

# Lazy imports to avoid circular dependencies
__all__ = [
    "LogParser",
    "ThermoExtractor",
    "DumpParser",
    "DataParser",
    # stats_utils exports
    "apply_time_window",
    "compute_mean_std",
    "get_default_window_ps",
    "get_default_dt_fs",
    "get_default_thermo_interval",
]


def __getattr__(name):
    if name == "LogParser":
        from parsers.log_parser import LogParser

        return LogParser
    elif name == "ThermoExtractor":
        from parsers.thermo_extractor import ThermoExtractor

        return ThermoExtractor
    elif name == "DumpParser":
        from parsers.dump_parser import DumpParser

        return DumpParser
    elif name == "DataParser":
        from parsers.data_parser import DataParser

        return DataParser
    elif name == "apply_time_window":
        from parsers.stats_utils import apply_time_window

        return apply_time_window
    elif name == "compute_mean_std":
        from parsers.stats_utils import compute_mean_std

        return compute_mean_std
    elif name == "get_default_window_ps":
        from parsers.stats_utils import get_default_window_ps

        return get_default_window_ps
    elif name == "get_default_dt_fs":
        from parsers.stats_utils import get_default_dt_fs

        return get_default_dt_fs
    elif name == "get_default_thermo_interval":
        from parsers.stats_utils import get_default_thermo_interval

        return get_default_thermo_interval
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
