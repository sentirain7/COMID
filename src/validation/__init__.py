"""
Validation Module for ReaxFF Verification.

This module provides ReaxFF-based validation for bulk FF simulation results.
It selects outliers and runs reactive force field simulations for verification.
"""

from .reaxff_selector import (
    OutlierCandidate,
    ReaxFFSelector,
    SelectionCriteria,
    SelectionResult,
)
from .reaxff_validator import (
    ComparisonResult,
    ReaxFFValidator,
    ValidationJob,
    ValidationResult,
    ValidationStatus,
)

__all__ = [
    # Selector
    "ReaxFFSelector",
    "SelectionCriteria",
    "OutlierCandidate",
    "SelectionResult",
    # Validator
    "ReaxFFValidator",
    "ValidationJob",
    "ValidationResult",
    "ValidationStatus",
    "ComparisonResult",
]
