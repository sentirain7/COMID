"""
Standard error codes and exceptions for the Asphalt Binder MD/ML Agent.

All sessions must use these error types for consistency.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Standard error codes."""

    # Validation errors (1xxx)
    VALIDATION_ERROR = "E1000"
    COMPOSITION_INVALID = "E1001"
    COMPOSITION_SUM_ERROR = "E1002"
    COMPOSITION_BOUNDS_ERROR = "E1003"
    ATOM_COUNT_ERROR = "E1004"
    TEMPERATURE_RANGE_ERROR = "E1005"
    PRESSURE_RANGE_ERROR = "E1006"
    INVALID_REQUEST = "E1007"
    INVALID_STATE_TRANSITION = "E1700"

    # Build errors (2xxx)
    BUILD_ERROR = "E2000"
    PACKMOL_FAILED = "E2001"
    MOLECULE_NOT_FOUND = "E2002"
    TOPOLOGY_GENERATION_FAILED = "E2003"
    PACKING_OVERLAP = "E2004"
    COMPOSITION_ERROR_EXCEEDED = "E2005"

    # Artifact errors (25xx)
    ARTIFACT_MISSING = "E2501"
    ARTIFACT_INCOMPLETE = "E2502"

    # Protocol errors (3xxx)
    PROTOCOL_ERROR = "E3000"
    TEMPLATE_NOT_FOUND = "E3001"
    INVALID_TIER = "E3002"
    INVALID_FF_TYPE = "E3003"

    # Execution errors (4xxx)
    EXECUTION_ERROR = "E4000"
    LAMMPS_FAILED = "E4001"
    TIMEOUT_ERROR = "E4002"
    ENERGY_DRIFT = "E4003"
    PRESSURE_BLOWUP = "E4004"
    QEQ_DIVERGENCE = "E4005"

    # Parser errors (5xxx)
    PARSER_ERROR = "E5000"
    LOG_PARSE_FAILED = "E5001"
    DUMP_PARSE_FAILED = "E5002"
    THERMO_EXTRACT_FAILED = "E5003"

    # Metric errors (6xxx)
    METRIC_ERROR = "E6000"
    UNKNOWN_METRIC = "E6001"
    UNIT_MISMATCH = "E6002"
    CONVERGENCE_FAILED = "E6003"
    DENSITY_OUT_OF_RANGE = "E6004"
    E_INTRA_NOT_CACHED = "E6005"

    # Database errors (7xxx)
    DATABASE_ERROR = "E7000"
    RECORD_NOT_FOUND = "E7001"
    DUPLICATE_RECORD = "E7002"
    MIGRATION_FAILED = "E7003"

    # Orchestration errors (8xxx)
    ORCHESTRATION_ERROR = "E8000"
    JOB_LIMIT_EXCEEDED = "E8001"
    GPU_NOT_AVAILABLE = "E8002"
    QUEUE_FULL = "E8003"
    SERVICE_UNAVAILABLE = "E8004"
    DEPENDENCY_CYCLE = "E8100"
    DEPENDENCY_BROKEN = "E8101"
    DUPLICATE_EXECUTION_BLOCKED = "E8701"

    # LLM errors (9xxx)
    LLM_ERROR = "E9000"
    REDACTION_VIOLATION = "E9001"
    DEBATE_TIMEOUT = "E9002"
    CONSENSUS_FAILED = "E9003"
    LITERATURE_FETCH_FAILED = "E9004"
    LITERATURE_VALIDATION_FAILED = "E9005"
    REASONING_CHAIN_INVALID = "E9006"
    TRAINING_QUALITY_FAILED = "E9007"
    SCENARIO_PLANNING_ERROR = "E9008"
    LLM_CLIENT_ERROR = "E9009"

    # ML/MLOps errors (10xxx)
    DRIFT_DETECTED = "E10001"
    RETRAINING_FAILED = "E10002"
    MODEL_REGISTRATION_FAILED = "E10003"
    MODEL_NOT_FOUND = "E10004"
    PROMOTION_FAILED = "E10005"
    ROLLBACK_FAILED = "E10006"
    INSUFFICIENT_TRAINING_DATA = "E10007"
    CALIBRATION_FAILED = "E10008"

    # Security errors (95xx)
    PATH_TRAVERSAL_BLOCKED = "E9501"
    SYMLINK_ESCAPE_BLOCKED = "E9502"
    FILE_TOO_LARGE = "E9503"
    ATOM_LIMIT_EXCEEDED = "E9504"
    STRUCTURE_NOT_FOUND = "E9505"


class ContractError(Exception):
    """Base exception for all contract-related errors."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.value}] {message}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(ContractError):
    """Raised when validation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details)


class CompositionError(ContractError):
    """Raised when composition validation fails."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        composition: dict[str, float] | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if composition:
            details["composition"] = composition
        super().__init__(code, message, details)


class BuildError(ContractError):
    """Raised when structure building fails."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class ProtocolError(ContractError):
    """Raised when protocol generation fails."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class ExecutionError(ContractError):
    """Raised when LAMMPS execution fails."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        log_file: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if log_file:
            details["log_file"] = log_file
        super().__init__(code, message, details)


class ParserError(ContractError):
    """Raised when parsing fails."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        file_path: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if file_path:
            details["file_path"] = file_path
        super().__init__(code, message, details)


class MetricError(ContractError):
    """Raised when metric calculation fails."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        metric_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if metric_name:
            details["metric_name"] = metric_name
        super().__init__(code, message, details)


class DatabaseError(ContractError):
    """Raised when database operations fail."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class OrchestrationError(ContractError):
    """Raised when orchestration fails."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class LLMError(ContractError):
    """Raised when LLM operations fail."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class MLOpsError(ContractError):
    """Raised when MLOps operations fail."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)


class SecurityError(ContractError):
    """Raised when security validation fails."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, details)
