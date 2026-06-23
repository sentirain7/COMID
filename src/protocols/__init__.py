"""
Protocol Library for LAMMPS input generation.

This module provides tools for generating LAMMPS input scripts
based on tier policies and stabilization chains.
"""

# Lazy imports to avoid circular dependencies
__all__ = [
    "TemplateEngine",
    "ProtocolChainBuilder",
    "LAMMPSInputGenerator",
    "ProtocolHasher",
]


def __getattr__(name: str) -> type:
    if name == "TemplateEngine":
        from protocols.template_engine import TemplateEngine

        return TemplateEngine
    elif name == "ProtocolChainBuilder":
        from protocols.protocol_chain import ProtocolChainBuilder

        return ProtocolChainBuilder
    elif name == "LAMMPSInputGenerator":
        from protocols.lammps_input import LAMMPSInputGenerator

        return LAMMPSInputGenerator
    elif name == "ProtocolHasher":
        from protocols.protocol_hash import ProtocolHasher

        return ProtocolHasher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
