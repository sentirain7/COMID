"""
Logging utilities - SSOT for logging configuration.

All sessions must use this logging setup for consistency.
"""

import logging
import sys
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class LogLevel(StrEnum):
    """Log level enumeration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# Default log format
DEFAULT_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Session-specific loggers
_loggers: dict[str, logging.Logger] = {}


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    log_file: str | None = None,
    format_string: str = DEFAULT_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
) -> None:
    """
    Configure global logging settings.

    Args:
        level: Log level
        log_file: Optional log file path
        format_string: Log format string
        date_format: Date format string
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.value))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(format_string, datefmt=date_format)

    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str, level: LogLevel | None = None) -> logging.Logger:
    """
    Get or create a logger for a module/session.

    Args:
        name: Logger name (typically module name)
        level: Optional specific level for this logger

    Returns:
        Configured logger
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)

    if level:
        logger.setLevel(getattr(logging, level.value))

    _loggers[name] = logger
    return logger


class ExperimentLogger:
    """Logger for experiment-specific events."""

    def __init__(self, exp_id: str, log_dir: Path | None = None):
        """
        Initialize experiment logger.

        Args:
            exp_id: Experiment ID
            log_dir: Directory for experiment logs
        """
        self.exp_id = exp_id
        self.logger = get_logger(f"experiment.{exp_id}")
        self.start_time = datetime.now()

        if log_dir:
            self._setup_file_handler(log_dir)

    def _setup_file_handler(self, log_dir: Path) -> None:
        """Set up file handler for experiment logs."""
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{self.exp_id}.log"

        formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
        handler = logging.FileHandler(log_file)
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def log_phase_start(self, phase: str) -> None:
        """Log start of a simulation phase."""
        self.logger.info(f"[{self.exp_id}] Phase started: {phase}")

    def log_phase_end(self, phase: str, success: bool) -> None:
        """Log end of a simulation phase."""
        status = "SUCCESS" if success else "FAILED"
        self.logger.info(f"[{self.exp_id}] Phase ended: {phase} ({status})")

    def log_metric(self, metric_name: str, value: float, unit: str) -> None:
        """Log a calculated metric."""
        self.logger.info(f"[{self.exp_id}] Metric: {metric_name} = {value:.6f} {unit}")

    def log_error(self, error_code: str, message: str) -> None:
        """Log an error."""
        self.logger.error(f"[{self.exp_id}] [{error_code}] {message}")

    def log_warning(self, message: str) -> None:
        """Log a warning."""
        self.logger.warning(f"[{self.exp_id}] {message}")

    def log_retry(self, attempt: int, action: str) -> None:
        """Log a retry attempt."""
        self.logger.info(f"[{self.exp_id}] Retry {attempt}: {action}")

    def get_elapsed_time(self) -> float:
        """Get elapsed time since experiment start."""
        return (datetime.now() - self.start_time).total_seconds()
