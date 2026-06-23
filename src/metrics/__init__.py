"""
Metrics calculation and storage module.

This module provides tools for calculating various molecular
dynamics metrics including density, CED, RDF, MSD, and E_intra.
"""

# Lazy imports to avoid circular dependencies
__all__ = [
    "MetricCalculator",
    "DensityCalculator",
    "CEDCalculator",
    "RDFCalculator",
    "MSDCalculator",
    "ViscosityCalculator",
    "TgCalculator",
    "EIntraStore",
    "ArrayStorage",
]


def __getattr__(name: str) -> type:
    if name == "MetricCalculator":
        from metrics.calculator import MetricCalculator

        return MetricCalculator
    elif name == "DensityCalculator":
        from metrics.density import DensityCalculator

        return DensityCalculator
    elif name == "CEDCalculator":
        from metrics.ced import CEDCalculator

        return CEDCalculator
    elif name == "RDFCalculator":
        from metrics.rdf import RDFCalculator

        return RDFCalculator
    elif name == "MSDCalculator":
        from metrics.msd import MSDCalculator

        return MSDCalculator
    elif name == "ViscosityCalculator":
        from metrics.viscosity import ViscosityCalculator

        return ViscosityCalculator
    elif name == "TgCalculator":
        from metrics.tg import TgCalculator

        return TgCalculator
    elif name == "EIntraStore":
        from metrics.e_intra_store import EIntraStore

        return EIntraStore
    elif name == "ArrayStorage":
        from metrics.array_storage import ArrayStorage

        return ArrayStorage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
