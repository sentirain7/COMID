"""
Interface definitions (ABC/Protocol) for the Asphalt Binder MD/ML Agent.

All sessions must implement these interfaces to ensure contract compliance.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from .policies.ml_policy import FeatureSetVersion
from .schemas import (
    ArrayMetricStorage,
    BuildRequest,
    BuildResult,
    EIntraKey,
    EIntraValue,
    ExperimentRecord,
    LAMMPSRunResult,
    MetricResult,
    MoleculeSpec,
    ProtocolRequest,
    ProtocolResult,
    ThermoData,
)

# =============================================================================
# Session B: Structure Builder Interface
# =============================================================================


@runtime_checkable
class IStructureBuilder(Protocol):
    """Interface for Session B (Structure Builder)."""

    def build(self, request: BuildRequest) -> BuildResult:
        """
        Build molecular structure from composition specification.

        Args:
            request: Build request containing composition and parameters

        Returns:
            BuildResult with data file path and quality metrics

        Raises:
            BuildError: If structure building fails
        """
        ...


class AbstractStructureBuilder(ABC):
    """Abstract base class for structure builders."""

    @abstractmethod
    def build(self, request: BuildRequest) -> BuildResult:
        """Build molecular structure."""
        pass

    @abstractmethod
    def validate_packing(self, data_file_path: str) -> dict[str, Any]:
        """Validate packing quality of generated structure."""
        pass


# =============================================================================
# Session C: Protocol Generator Interface
# =============================================================================


@runtime_checkable
class IProtocolGenerator(Protocol):
    """Interface for Session C (Protocol Library)."""

    def generate(self, request: ProtocolRequest) -> ProtocolResult:
        """
        Generate LAMMPS input script from protocol request.

        Args:
            request: Protocol request with FF type, tier, and conditions

        Returns:
            ProtocolResult with input script path and protocol hash

        Raises:
            ProtocolError: If protocol generation fails
        """
        ...


class AbstractProtocolGenerator(ABC):
    """Abstract base class for protocol generators."""

    @abstractmethod
    def generate(self, request: ProtocolRequest) -> ProtocolResult:
        """Generate LAMMPS input script."""
        pass

    @abstractmethod
    def get_protocol_hash(self, tier: str) -> str:
        """Get reproducibility hash for protocol."""
        pass

    @abstractmethod
    def get_stabilization_chain(self, tier: str) -> list[str]:
        """Get stabilization step names for tier."""
        pass


# =============================================================================
# Session D: Metric Calculator Interface
# =============================================================================


@runtime_checkable
class IMetricCalculator(Protocol):
    """Interface for Session D (Parser & Metrics)."""

    def calculate(self, run_result: LAMMPSRunResult) -> list[MetricResult]:
        """
        Calculate metrics from LAMMPS output.

        Args:
            run_result: LAMMPS run result with output files

        Returns:
            List of metric results

        Raises:
            MetricError: If calculation fails
        """
        ...


class AbstractMetricCalculator(ABC):
    """Abstract base class for metric calculators."""

    @abstractmethod
    def calculate(self, run_result: LAMMPSRunResult) -> list[MetricResult]:
        """Calculate all metrics from LAMMPS output."""
        pass

    @abstractmethod
    def calculate_density(self, thermo_data: ThermoData) -> MetricResult:
        """Calculate density metric."""
        pass

    @abstractmethod
    def calculate_ced(
        self,
        thermo_data: ThermoData,
        mol_counts: dict[str, int],
        ff_name: str,
        ff_version: str,
        use_window_ps: bool = True,
        temperature_K: float = 298.0,
    ) -> MetricResult:
        """Calculate cohesive energy density with exact-temperature E_intra lookup."""
        pass


# =============================================================================
# E_intra Store Interface
# =============================================================================


@runtime_checkable
class IEIntraStore(Protocol):
    """Interface for E_intra cache storage."""

    def get(self, key: EIntraKey) -> EIntraValue | None:
        """Get E_intra value from cache."""
        ...

    def put(self, key: EIntraKey, value: EIntraValue) -> None:
        """Store E_intra value in cache."""
        ...

    def has(self, key: EIntraKey) -> bool:
        """Check if E_intra value exists in cache."""
        ...


class AbstractEIntraStore(ABC):
    """Abstract base class for E_intra storage."""

    @abstractmethod
    def get(self, key: EIntraKey) -> EIntraValue | None:
        """Get E_intra value from cache."""
        pass

    @abstractmethod
    def put(self, key: EIntraKey, value: EIntraValue) -> None:
        """Store E_intra value in cache."""
        pass

    @abstractmethod
    def has(self, key: EIntraKey) -> bool:
        """Check if E_intra value exists in cache."""
        pass

    @abstractmethod
    def list_keys(self) -> list[EIntraKey]:
        """List all cached keys."""
        pass


# =============================================================================
# Session E: Repository Interfaces
# =============================================================================


@runtime_checkable
class IExperimentRepository(Protocol):
    """Interface for experiment data repository."""

    def save(self, record: ExperimentRecord) -> str:
        """Save experiment record to database."""
        ...

    def get(self, exp_id: str) -> ExperimentRecord | None:
        """Get experiment record by ID."""
        ...

    def update_status(self, exp_id: str, status: str) -> None:
        """Update experiment status."""
        ...


class AbstractExperimentRepository(ABC):
    """Abstract base class for experiment repository."""

    @abstractmethod
    def save(self, record: ExperimentRecord) -> str:
        """Save experiment record."""
        pass

    @abstractmethod
    def get(self, exp_id: str) -> ExperimentRecord | None:
        """Get experiment by ID."""
        pass

    @abstractmethod
    def update_status(self, exp_id: str, status: str) -> None:
        """Update experiment status."""
        pass

    @abstractmethod
    def find_by_status(self, status: str) -> list[ExperimentRecord]:
        """Find experiments by status."""
        pass

    @abstractmethod
    def find_by_tier(self, tier: str) -> list[ExperimentRecord]:
        """Find experiments by run tier."""
        pass


@runtime_checkable
class IJobDependencyRepository(Protocol):
    """Interface for job dependency graph repository."""

    def create_dependency(self, parent_exp_id: str, child_exp_id: str) -> str:
        """Create dependency edge parent -> child and return edge identifier."""
        ...

    def list_dependents(self, parent_exp_id: str) -> list[dict[str, Any]]:
        """List downstream jobs waiting on parent."""
        ...

    def validate_no_cycles(self, parent_exp_id: str, child_exp_id: str) -> bool:
        """Return False when a new edge would create a cycle."""
        ...

    def list_by_status(self, status: str, limit: int = 200) -> list[Any]:
        """List dependency edges filtered by status."""
        ...

    def list_parents_with_active_edges(self, limit: int = 500) -> list[str]:
        """List distinct parent exp_ids that still have active edges."""
        ...

    def update_status(
        self,
        parent_exp_id: str,
        child_exp_id: str,
        *,
        status: str,
        reason: str | None = None,
    ) -> bool:
        """Update dependency edge status and optional reason."""
        ...


class AbstractJobDependencyRepository(ABC):
    """Abstract base class for dependency graph repository."""

    @abstractmethod
    def create_dependency(self, parent_exp_id: str, child_exp_id: str) -> str:
        """Create dependency edge."""
        pass

    @abstractmethod
    def list_dependents(self, parent_exp_id: str) -> list[dict[str, Any]]:
        """List downstream jobs."""
        pass

    @abstractmethod
    def validate_no_cycles(self, parent_exp_id: str, child_exp_id: str) -> bool:
        """Validate acyclic graph constraint."""
        pass

    @abstractmethod
    def list_by_status(self, status: str, limit: int = 200) -> list[Any]:
        """List dependency edges by status."""
        pass

    @abstractmethod
    def list_parents_with_active_edges(self, limit: int = 500) -> list[str]:
        """List parents that have blocked/ready edges."""
        pass

    @abstractmethod
    def update_status(
        self,
        parent_exp_id: str,
        child_exp_id: str,
        *,
        status: str,
        reason: str | None = None,
    ) -> bool:
        """Update one dependency edge state."""
        pass


@runtime_checkable
class IMoleculeRepository(Protocol):
    """Interface for molecule repository."""

    def save(self, molecule: MoleculeSpec) -> str:
        """Save molecule to database."""
        ...

    def get(self, mol_id: str) -> MoleculeSpec | None:
        """Get molecule by ID."""
        ...

    def get_by_category(self, category: str) -> list[MoleculeSpec]:
        """Get molecules by category."""
        ...


class AbstractMoleculeRepository(ABC):
    """Abstract base class for molecule repository."""

    @abstractmethod
    def save(self, molecule: MoleculeSpec) -> str:
        """Save molecule."""
        pass

    @abstractmethod
    def get(self, mol_id: str) -> MoleculeSpec | None:
        """Get molecule by ID."""
        pass

    @abstractmethod
    def get_by_category(self, category: str) -> list[MoleculeSpec]:
        """Get molecules by category."""
        pass

    @abstractmethod
    def list_all(self) -> list[MoleculeSpec]:
        """List all molecules."""
        pass


@runtime_checkable
class IMetricRepository(Protocol):
    """Interface for metric repository."""

    def save(self, metric: MetricResult) -> None:
        """Save single metric to database."""
        ...

    def save_batch(self, metrics: list[MetricResult]) -> int:
        """
        Save multiple metrics in single transaction.

        Args:
            metrics: List of MetricResult to save

        Returns:
            Number of metrics saved
        """
        ...

    def get_by_exp(self, exp_id: str) -> list[MetricResult]:
        """Get all metrics for experiment."""
        ...


class AbstractMetricRepository(ABC):
    """Abstract base class for metric repository."""

    @abstractmethod
    def save(self, metric: MetricResult) -> None:
        """Save single metric."""
        pass

    @abstractmethod
    def save_batch(self, metrics: list[MetricResult]) -> int:
        """Save multiple metrics in single transaction."""
        pass

    @abstractmethod
    def get_by_exp(self, exp_id: str) -> list[MetricResult]:
        """Get metrics by experiment ID."""
        pass


# =============================================================================
# Array Storage Interface
# =============================================================================


@runtime_checkable
class IArrayStorage(Protocol):
    """Interface for array metric file storage."""

    def save(
        self,
        exp_id: str,
        metric_name: str,
        data: Any,  # numpy array
        columns: list[str] | None = None,
    ) -> ArrayMetricStorage:
        """Save array to file and return storage info."""
        ...

    def load(self, file_path: str) -> Any:
        """Load array from file."""
        ...


class AbstractArrayStorage(ABC):
    """Abstract base class for array storage."""

    @abstractmethod
    def save(
        self, exp_id: str, metric_name: str, data: Any, columns: list[str] | None = None
    ) -> ArrayMetricStorage:
        """Save array to Parquet file."""
        pass

    @abstractmethod
    def load(self, file_path: str) -> Any:
        """Load array from file."""
        pass

    @abstractmethod
    def delete(self, file_path: str) -> None:
        """Delete array file."""
        pass


# =============================================================================
# Log Parser Interface
# =============================================================================


@runtime_checkable
class ILogParser(Protocol):
    """Interface for LAMMPS log parser."""

    def parse(self, log_file: str) -> ThermoData:
        """Parse LAMMPS log file to extract thermo data."""
        ...


class AbstractLogParser(ABC):
    """Abstract base class for log parser."""

    @abstractmethod
    def parse(self, log_file: str) -> ThermoData:
        """Parse log file."""
        pass

    @abstractmethod
    def extract_final_values(self, log_file: str) -> dict[str, float]:
        """Extract final thermo values."""
        pass


# =============================================================================
# LAMMPS Runner Interface
# =============================================================================


@runtime_checkable
class ILAMMPSRunner(Protocol):
    """Interface for LAMMPS execution."""

    def run(self, protocol_result: ProtocolResult, timeout: int | None = None) -> LAMMPSRunResult:
        """
        Run LAMMPS simulation.

        Args:
            protocol_result: Protocol with input script
            timeout: Optional timeout in seconds

        Returns:
            LAMMPSRunResult with output files and status
        """
        ...


class AbstractLAMMPSRunner(ABC):
    """Abstract base class for LAMMPS runner."""

    @abstractmethod
    def run(self, protocol_result: ProtocolResult, timeout: int | None = None) -> LAMMPSRunResult:
        """Run LAMMPS simulation."""
        pass

    @abstractmethod
    def check_lammps_available(self) -> bool:
        """Check if LAMMPS is available."""
        pass

    @abstractmethod
    def get_lammps_version(self) -> str:
        """Get LAMMPS version string."""
        pass


# =============================================================================
# ML Feature Extractor Interface
# =============================================================================


@runtime_checkable
class IFeatureExtractor(Protocol):
    """Interface for ML feature extraction."""

    def extract_features(self, record: ExperimentRecord) -> dict[str, float]:
        """Extract features from an experiment record.

        Args:
            record: Experiment record with composition and additive metadata.

        Returns:
            Dict mapping feature name to float value.
        """
        ...

    def get_feature_set_version(self) -> FeatureSetVersion:
        """Return the feature set version this extractor produces.

        Returns:
            FeatureSetVersion enum value.
        """
        ...
