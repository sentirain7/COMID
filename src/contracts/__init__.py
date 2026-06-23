"""
Contracts module - Single Source of Truth (SSOT)

This module contains all schemas, interfaces, and policies that define
the contracts between different sessions/components of the Asphalt Binder
MD/ML Agent system.

Usage:
    from contracts.schemas import BuildRequest, BuildResult
    from contracts.interfaces import IStructureBuilder
    from contracts.policies.composition import CompositionConstraints
    from contracts.errors import ContractError
"""

from pathlib import Path

# Read version from VERSION file
_version_file = Path(__file__).parent / "VERSION"
__version__ = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"

__all__ = [
    "__version__",
]
