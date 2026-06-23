"""Enum definitions and helpers for contracts schemas."""

from enum import StrEnum
from typing import Any


class FFType(StrEnum):
    """Force field type."""

    BULK_FF_GAFF2 = "bulk_ff_gaff2"  # GAFF2 (primary organic FF)
    REAXFF = "reaxff"


class RunTier(StrEnum):
    """Run tier for cost control."""

    SCREENING = "screening"
    CONFIRM = "confirm"
    VISCOSITY = "viscosity"
    VALIDATION = "validation"


class MoleculeCategory(StrEnum):
    """Molecule category (SARA + additive)."""

    SATURATE = "saturate"
    AROMATIC = "aromatic"
    RESIN = "resin"
    ASPHALTENE = "asphaltene"
    ADDITIVE = "additive"


class AdditiveSubcategory(StrEnum):
    """Additive subcategory."""

    POLYMER = "polymer"
    SURFACTANT = "surfactant"
    NANOPARTICLE = "nanoparticle"


class FunctionalTag(StrEnum):
    """Functional tag for additives."""

    ANTI_AGING = "anti-aging"
    ANTI_STRIPPING = "anti-stripping"
    MODIFIER = "modifier"


class ExperimentStatus(StrEnum):
    """Experiment status."""

    PENDING = "pending"
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    RUNNING = "running"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"  # GPU wait timeout (distinct from simulation failure)


class FailureCategory(StrEnum):
    """Failure classification."""

    OVERLAP_INSTABILITY = "overlap_instability"
    PRESSURE_BLOWUP = "pressure_blowup"
    ENERGY_DRIFT = "energy_drift"
    QEQ_DIVERGENCE = "qeq_divergence"
    PACKING_OVERLAP_SUSPECTED = "packing_overlap_suspected"


class ValidityDomainTag(StrEnum):
    """Validity domain tags for simulation results."""

    BULK_GAFF2_OK = "bulk_gaff2_ok"
    HIGH_ASPHALTENE_SENSITIVE = "high_asphaltene_sensitive"
    LOW_TEMPERATURE_CAUTION = "low_temperature_caution"
    HIGH_ADDITIVE_UNCERTAIN = "high_additive_uncertain"


class StudyType(StrEnum):
    """Study type for DB separation."""

    BULK = "bulk"
    LAYER_BULKFF = "layer_bulkff"
    REAXFF_VALIDATION = "reaxff_validation"
    SINGLE_MOLECULE_VACUUM = "single_molecule_vacuum"


class SubmissionSource(StrEnum):
    """SSOT for the ``metadata_json["source"]`` submission-origin tag.

    Records which entrypoint produced an experiment so downstream
    analytics/ML can filter by provenance. Member *values* preserve the
    exact pre-existing strings so already-stored rows stay consistent
    (StrEnum members compare/serialise as their string value).
    """

    EXPERIMENT_SUBMIT = "experiment_submit"
    MOLECULE_SUBMIT = "molecule_submit"
    DEPENDENT_MOLECULE_SUBMIT = "dependent_molecule_submit"
    SINGLE_MOLECULE = "single_molecule"
    BATCH_JOB_BINDER_CELL = "batch_job_binder_cell"
    BATCH_JOB_BINDER_CELL_ADDITIVE = "batch_job_binder_cell_additive"
    LAYERED_STRUCTURES = "layered_structures"
    INVERSE_PIPELINE = "inverse_pipeline"


class EIntraMethod(StrEnum):
    """E_intra calculation method tag (CED method redesign v3+).

    Distinct stored methods that differ in the LAMMPS protocol used to derive
    the single-molecule potential energy.  ``EIntraKey.method`` carries this
    tag through the writer/reader paths so that Method 1 (legacy 12 Å cutoff
    vacuum), Method 1a (adaptive-cutoff vacuum), and the future Method 2
    (periodic single-molecule + PPPM) can co-exist without row aliasing.

    See ``docs/architecture/ced-method-redesign-analysis.md`` for the
    catalogue and ``docs/architecture/test-forcefield-stale-failures.md``
    for the related fail-closed policy.
    """

    SINGLE_MOLECULE_VACUUM = "single_molecule_vacuum"
    SINGLE_MOLECULE_VACUUM_ADAPTIVE_CUTOFF = "single_molecule_vacuum_adaptive_cutoff"
    SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF = SINGLE_MOLECULE_VACUUM_ADAPTIVE_CUTOFF
    SINGLE_MOLECULE_PERIODIC = "single_molecule_periodic"


E_INTRA_METHOD_LEGACY_ALIASES: dict[str, str] = {
    "single_molecule_vacuum_extended_cutoff": EIntraMethod.SINGLE_MOLECULE_VACUUM_ADAPTIVE_CUTOFF.value,
}


def coerce_e_intra_method(value: Any) -> EIntraMethod:
    """Return the canonical ``EIntraMethod`` enum for new and legacy inputs."""
    if isinstance(value, EIntraMethod):
        return value
    if isinstance(value, str):
        return EIntraMethod(E_INTRA_METHOD_LEGACY_ALIASES.get(value, value))
    raise TypeError(f"EIntraMethod must be a string or EIntraMethod, got {type(value).__name__}")


def normalize_e_intra_method(value: Any) -> str | None:
    """Return the canonical string tag for an E_intra method or ``None``."""
    if value is None:
        return None
    return coerce_e_intra_method(value).value


class AgingState(StrEnum):
    """Aging state for molecule variants."""

    NON_AGING = "non_aging"
    SHORT_AGING = "short_aging"
    LONG_AGING = "long_aging"


class RecommendationMode(StrEnum):
    """Recommendation operating mode."""

    KNOWN = "known"
    NOVEL = "novel"


class RecommendationStatus(StrEnum):
    """Recommendation lifecycle status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FED_BACK = "fed_back"
    FAILED = "failed"


class SimulationPriority(StrEnum):
    """Simulation priority used by recommendation workflows."""

    SCREEN = "screen"
    CONFIRM = "confirm"
    EXPAND = "expand"


class CampaignStatus(StrEnum):
    """Campaign lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"


class WaveStatus(StrEnum):
    """Campaign wave lifecycle status."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class KokkosBackend(StrEnum):
    """KOKKOS backend type detected from LAMMPS build."""

    CUDA = "cuda"
    HIP = "hip"
    OPENMP = "openmp"
    SERIAL = "serial"
    NONE = "none"


class AccelMode(StrEnum):
    """Acceleration mode determined from LAMMPS build + hardware."""

    KOKKOS_GPU = "kokkos_gpu"
    KOKKOS_CPU = "kokkos_cpu"
    MPI_ONLY = "mpi_only"
    SERIAL = "serial"


class EInterComputeMode(StrEnum):
    """E_inter calculation mode."""

    GPU_FAST = "gpu_fast"  # GPU/KOKKOS, short-range only (default)
    GPU_THEN_CPU = "gpu_then_cpu"  # GPU main + CPU rerun for precise E_inter
    CPU_RERUN_ONLY = "cpu_rerun_only"  # Manual post-processing for completed experiments


class EInterRecommendationLevel(StrEnum):
    """E_inter precision analysis recommendation level."""

    NONE = "none"  # Not applicable (structure generation, vacuum)
    OPTIONAL = "optional"  # Available but not recommended
    RECOMMENDED = "recommended"  # Recommended for accuracy
    REQUIRED = "required"  # Required for selected metrics


__all__ = [
    "AccelMode",
    "AdditiveSubcategory",
    "AgingState",
    "CampaignStatus",
    "EInterComputeMode",
    "EInterRecommendationLevel",
    "ExperimentStatus",
    "FFType",
    "FailureCategory",
    "FunctionalTag",
    "KokkosBackend",
    "MoleculeCategory",
    "RecommendationMode",
    "RecommendationStatus",
    "RunTier",
    "SimulationPriority",
    "StudyType",
    "ValidityDomainTag",
    "WaveStatus",
    "coerce_e_intra_method",
    "normalize_e_intra_method",
]
