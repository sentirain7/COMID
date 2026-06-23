"""
Pydantic schemas for the Asphalt Binder MD/ML Agent.

This module defines all data models used across the system.
All sessions must use these schemas for data exchange.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from common.seed import generate_seed
from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as _EQ_POLICY
from contracts.schema_enums import (
    AccelMode,
    AdditiveSubcategory,
    AgingState,
    EIntraMethod,
    ExperimentStatus,
    FailureCategory,
    FFType,
    FunctionalTag,
    KokkosBackend,
    MoleculeCategory,
    RunTier,
    StudyType,
    SubmissionSource,  # noqa: F401 — re-exported for `from contracts.schemas import SubmissionSource`
    ValidityDomainTag,
    coerce_e_intra_method,
)

# =============================================================================
# LAMMPS Capability Schema
# =============================================================================


class LammpsCaps(BaseModel):
    """LAMMPS binary capabilities detected at runtime.

    Probed once per worker process (lazy singleton with file cache).
    Used to determine optimal input script settings (newton, neighbor list,
    KOKKOS package commands) without sacrificing accuracy.
    """

    executable_path: str = Field(..., description="Resolved absolute path to LAMMPS binary")
    version_string: str = Field(default="unknown", description="LAMMPS version line")
    installed_packages: list[str] = Field(
        default_factory=list, description="Installed packages from lmp -h"
    )
    kokkos_backend: KokkosBackend = Field(default=KokkosBackend.NONE)
    kokkos_precision: str = Field(default="unknown", description="double/single/mixed")
    kokkos_fft: str = Field(default="unknown", description="KISS/FFTW3/cuFFT")
    gpu_detected: bool = Field(default=False, description="nvidia-smi returned >=1 GPU")
    gpu_count: int = Field(default=0)
    gpu_model: str | None = Field(default=None)
    cpu_cores: int = Field(default=1)
    accel_mode: AccelMode = Field(default=AccelMode.SERIAL)
    probed_at: datetime | None = Field(default=None)


# =============================================================================
# Molecule Schemas
# =============================================================================


class MoleculeSpec(BaseModel):
    """Molecule specification from molecule database."""

    mol_id: str = Field(..., description="Unique molecule identifier")
    smiles: str = Field(..., description="SMILES string")
    molecular_weight: float = Field(..., gt=0, description="Molecular weight (g/mol)")
    atom_count: int = Field(..., gt=0, description="Number of atoms")
    category: MoleculeCategory = Field(..., description="SARA category or additive")
    subcategory: AdditiveSubcategory | None = Field(None, description="Additive subcategory")
    functional_tag: FunctionalTag | None = Field(None, description="Functional tag for additives")
    structure_file: str = Field(..., description="Path to structure file (mol2)")
    topology_hash: str = Field(..., description="SHA256 hash of topology")
    density_ref: float | None = Field(None, description="Reference density (g/cm3)")
    created_at: datetime = Field(default_factory=datetime.now)

    # Aging library fields (optional for backward compatibility)
    aging_state: AgingState | None = Field(
        None, description="Aging state (non_aging, short_aging, long_aging)"
    )
    temperature_code: str | None = Field(None, description="Temperature code (e.g., 0293 for 293K)")
    base_id: str | None = Field(None, description="Base molecule ID without prefix/suffix")
    paper_name: str | None = Field(None, description="Original paper reference name")


class MoleculeInfo(BaseModel):
    """Lightweight molecule info for calculations."""

    mol_id: str
    molecular_weight: float
    atom_count: int
    category: MoleculeCategory


# =============================================================================
# Force Field Schemas
# =============================================================================


class ForceFieldSpec(BaseModel):
    """Force field specification."""

    type: FFType = Field(FFType.BULK_FF_GAFF2, description="Force field type")
    name: str = Field("GAFF2", description="Force field name")
    version: str = Field("1.0", description="Force field version")
    parameter_source: str = Field("antechamber", description="Parameter source")


class SimulationConfig(BaseModel):
    """Optional simulation configuration.

    When absent, defaults are derived from ff_type:
    - BULK_FF_GAFF2 -> organic_ff="gaff2" (sole organic FF)

    Note:
        This config is declared in Phase 1 but consumption by builder/protocol
        layers is implemented in Phase 3-4. Until then, ff_type alone drives
        the FF selection.
    """

    organic_ff: Literal["opls-aa", "gaff2"] | None = Field(None, description="Organic FF override")


# =============================================================================
# Material and Build Schemas
# =============================================================================


class MaterialSpec(BaseModel):
    """Material specification."""

    material_id: str = Field(..., description="Unique material identifier")
    force_field: ForceFieldSpec = Field(default_factory=ForceFieldSpec)
    molecules: list[MoleculeInfo] = Field(..., description="List of molecules in material")


class CompositionSpec(BaseModel):
    """Composition specification (wt% based)."""

    basis: str = Field("wt%", description="Composition basis")
    components: dict[str, float] = Field(..., description="Component wt% values")

    @field_validator("components")
    @classmethod
    def validate_positive(cls, v: dict[str, float]) -> dict[str, float]:
        for key, val in v.items():
            if val < 0:
                raise ValueError(f"Component {key} has negative value: {val}")
        return v


class BuildSpec(BaseModel):
    """Build specification for structure generation."""

    composition: CompositionSpec
    target_atoms: int = Field(100000, gt=0, description="Target atom count")
    atom_count_tolerance: float = Field(0.10, ge=0, le=1.0, description="Atom count tolerance")
    initial_density: float = Field(0.5, gt=0, description="Initial density (g/cm3)")
    seed: int = Field(..., description="Random seed for reproducibility")
    builder_tool: str = Field("packmol", description="Builder tool name")
    builder_version: str = Field("20.14.0", description="Builder version")


class BuildRequest(BaseModel):
    """Request for Session B (Structure Builder)."""

    composition: dict[str, float] = Field(
        ..., description="Target composition (wt% or molecule counts)"
    )
    composition_mode: str = Field(
        "mol_count",
        description="Composition mode: 'wt_percent' for weight percent or 'mol_count' for molecule counts",
    )
    target_atoms: int = Field(100000, gt=0)
    atom_count_tolerance: float = Field(0.10, ge=0, le=1.0)
    initial_density: float = Field(0.5, gt=0)
    box_dimensions: tuple[float, float, float] | None = Field(
        None,
        description="Optional explicit orthorhombic box dimensions (lx, ly, lz) in Angstrom",
    )
    prebuilt_data_file_path: str | None = Field(
        None,
        description="Optional prebuilt LAMMPS data file path. If provided, structure build is skipped.",
    )
    seed: int = Field(...)
    seed_list: list[int] | None = Field(
        None,
        description="Optional seed list for replicate runs. "
        "When provided, overrides single seed for batch execution.",
    )
    simulation_config: SimulationConfig | None = Field(
        None, description="Optional FF configuration override"
    )

    @field_validator("box_dimensions")
    @classmethod
    def validate_box_dimensions(
        cls, value: tuple[float, float, float] | None
    ) -> tuple[float, float, float] | None:
        if value is None:
            return None
        lx, ly, lz = value
        if lx <= 0 or ly <= 0 or lz <= 0:
            raise ValueError("box_dimensions values must be positive")
        return value


class BuildResult(BaseModel):
    """Result from Session B (Structure Builder)."""

    data_file_path: str = Field(..., description="Path to LAMMPS data file")
    actual_atoms: int = Field(..., gt=0, description="Actual atom count")
    actual_density: float = Field(..., gt=0, description="Actual density")
    topology_hash: str = Field(..., description="Topology hash for reproducibility")
    packmol_version: str = Field(..., description="Packmol version used")

    # Composition tracking
    actual_composition_wt: dict[str, float] = Field(..., description="Actual wt% after building")
    composition_error_l1: float = Field(..., ge=0, description="L1 error in wt%")
    target_composition_wt: dict[str, float] = Field(..., description="Target wt%")

    # Packing quality
    min_distance_violation_count: int = Field(0, ge=0, description="Min distance violations")
    initial_pe_per_atom: float = Field(..., description="Initial PE/atom for stability check")
    stability_flag: str | None = Field(None, description="Stability flag if issues detected")

    # Molecule ordering metadata for group assignment (Phase 4.2)
    molecule_ordering: list[dict[str, str | int]] | None = Field(
        None,
        description="Packing order: [{mol_id, count, category, atom_count}]",
    )


# =============================================================================
# Group Energy Schemas (Phase 4.2)
# =============================================================================


class GroupPairSpec(BaseModel):
    """Group pair specification for compute group/group."""

    label: str = Field(..., description="Pair label (e.g., saturate_aromatic)")
    group_a: str = Field(..., description="First group name")
    group_b: str = Field(..., description="Second group name")


class GroupSelector(BaseModel):
    """Selector for atom group membership in LAMMPS.

    Supports three modes for defining atom groups:
    - molecule: Group by LAMMPS molecule IDs (default).
    - atom_id_list: Group by explicit atom ID list.
    - atom_id_range: Group by contiguous atom ID range.
    """

    mode: Literal["molecule", "atom_id_list", "atom_id_range"] = Field(
        "molecule", description="Group definition mode"
    )
    ids: list[int] | None = Field(None, description="IDs for molecule or atom_id_list mode")
    range_start: int | None = Field(None, description="Start atom ID for atom_id_range mode")
    range_end: int | None = Field(None, description="End atom ID for atom_id_range mode")


class GroupEnergySpec(BaseModel):
    """Group energy decomposition specification.

    Encapsulates all info needed for LAMMPS group/group energy decomposition
    and downstream pair-RDF/E_inter metric calculation.

    Supports two patterns:
    - v1: ``groups`` dict mapping group names to LAMMPS molecule IDs.
    - v2: ``group_selectors`` dict mapping group names to GroupSelector
      instances (takes precedence over ``groups`` when set).
    """

    # v1 fields (backward compatible)
    groups: dict[str, list[int]] = Field(
        default_factory=dict,
        description="Group name → LAMMPS molecule IDs",
    )
    pairs: list[GroupPairSpec] = Field(
        default_factory=list,
        description="Group pairs for compute group/group",
    )
    atom_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Group name → total atom count for normalization",
    )
    additive_pair_label: str | None = Field(
        None, description="Pair label for additive-binder metric"
    )

    # v2 fields
    group_selectors: dict[str, GroupSelector] | None = Field(
        None,
        description="v2 group selectors (takes precedence over groups when set)",
    )
    layer_count: int | None = Field(None, description="Number of layers for layered systems")


# =============================================================================
# Protocol Schemas
# =============================================================================


class RunSpec(BaseModel):
    """Run specification for LAMMPS simulation."""

    temperature_K: float = Field(298.0, gt=0, description="Temperature (K)")
    pressure_atm: float = Field(1.0, gt=0, description="Pressure (atm)")
    dt_fs: float = Field(1.0, gt=0, description="Timestep (fs)")
    lj_cutoff_angstrom: float = Field(12.0, gt=0, description="LJ cutoff (Angstrom)")
    nvt_ps: float = Field(300.0, gt=0, description="NVT duration (ps)")
    npt_ps: float = Field(1000.0, gt=0, description="NPT duration (ps)")
    minimize_steps: int = Field(1000, gt=0, description="Minimization steps")
    thermo_every_steps: int = Field(1000, gt=0, description="Thermo output frequency")
    trajectory_dump_ps: float = Field(20.0, gt=0, description="Trajectory dump frequency (ps)")
    checkpoint_ps: float = Field(250.0, gt=0, description="Checkpoint frequency (ps)")


class EquilibrationSettings(BaseModel):
    """High-temperature/high-pressure equilibration settings for kinetic trapping mitigation.

    When enabled, inserts additional equilibration stages before the standard NVT:
    minimize -> [high_temp_nvt @ high_T] -> [high_pressure_npt @ high_T, high_P] -> nvt @ target_T -> npt @ target_T

    Literature references:
    - Scientific Reports 2021: NPT @ 100 atm (200 ps) -> NPT @ 1 atm (1000 ps)
    - ACS Omega 2022: NVT @ 800K (100 ps) -> NPT @ 200 atm, 800K (500 ps) -> gradual cooling

    Note: Default values and bounds are sourced from contracts.policies.equilibration (SSOT).
    """

    enabled: bool = Field(False, description="Enable enhanced equilibration")
    high_temp_nvt_temperature_K: float = Field(
        _EQ_POLICY.high_temp_nvt_temperature_K,
        ge=_EQ_POLICY.temperature_min_K,
        le=_EQ_POLICY.temperature_max_K,
        description="High-temperature NVT stage temperature (K)",
    )
    high_temp_nvt_duration_ps: float = Field(
        _EQ_POLICY.high_temp_nvt_duration_ps,
        ge=_EQ_POLICY.duration_min_ps,
        le=_EQ_POLICY.duration_max_ps,
        description="High-temperature NVT stage duration (ps)",
    )
    high_pressure_npt_temperature_K: float = Field(
        _EQ_POLICY.high_pressure_npt_temperature_K,
        ge=_EQ_POLICY.temperature_min_K,
        le=_EQ_POLICY.temperature_max_K,
        description="High-pressure NPT stage temperature (K)",
    )
    high_pressure_npt_pressure_atm: float = Field(
        _EQ_POLICY.high_pressure_npt_pressure_atm,
        ge=_EQ_POLICY.pressure_min_atm,
        le=_EQ_POLICY.pressure_max_atm,
        description="High-pressure NPT stage pressure (atm)",
    )
    high_pressure_npt_duration_ps: float = Field(
        _EQ_POLICY.high_pressure_npt_duration_ps,
        ge=_EQ_POLICY.duration_min_ps,
        le=_EQ_POLICY.duration_max_ps,
        description="High-pressure NPT stage duration (ps)",
    )


class ProtocolRequest(BaseModel):
    """Request for Session C (Protocol Library)."""

    ff_type: FFType = Field(FFType.BULK_FF_GAFF2)
    run_tier: RunTier = Field(RunTier.SCREENING)
    study_type: StudyType = Field(StudyType.BULK, description="Study type (bulk or layer)")
    temperature_K: float = Field(298.0, gt=0)
    pressure_atm: float = Field(1.0, gt=0)
    data_file_path: str = Field(..., description="Path to LAMMPS data file")
    e_intra_method: str | None = Field(
        None,
        description="Resolved E_intra method for new job generation.",
    )
    ced_provenance_mol_counts: dict[str, int] | None = Field(
        None,
        description="Optional explicit mol_counts provenance for CED lookup on wt_percent jobs.",
    )
    ced_provenance_mol_counts_by_layer: dict[str, dict[str, int]] | None = Field(
        None,
        description="Optional explicit per-layer mol_counts provenance for layered CED profiles.",
    )
    ced_provenance_layer_volumes_A3: dict[str, float] | None = Field(
        None,
        description="Optional per-layer physical volumes (A^3) for layered CED profiles.",
    )
    ced_provenance_layer_labels: list[str] | None = Field(
        None,
        description="Optional canonical layer labels aligned with layered provenance.",
    )

    @field_validator("e_intra_method")
    @classmethod
    def validate_e_intra_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return coerce_e_intra_method(value).value

    # Group energy specification (Phase 4.2, optional)
    group_energy_spec: GroupEnergySpec | None = Field(
        None, description="Group energy decomposition config"
    )

    # Phase 4.3: Tensile test configuration (optional)
    tensile_spec: Optional["TensileSpec"] = Field(None, description="Tensile test config")
    layer_spec: Optional["LayerSpec"] = Field(
        None, description="Layer geometry for grip z-boundary reference"
    )

    # High-temperature/high-pressure equilibration settings (optional)
    equilibration_settings: EquilibrationSettings | None = Field(
        None, description="Enhanced equilibration settings for low-temperature simulations"
    )

    # Internal execution field: stages to skip from protocol chain
    skip_stage_keys: list[str] | None = Field(
        None, description="Stage keys to skip from protocol chain (internal execution field)"
    )

    simulation_config: SimulationConfig | None = Field(
        None, description="Optional FF configuration override"
    )


class ProtocolResult(BaseModel):
    """Result from Session C (Protocol Library)."""

    input_script_path: str = Field(..., description="Path to LAMMPS input script")
    expected_outputs: list[str] = Field(..., description="Expected output files")
    estimated_steps: int = Field(..., gt=0, description="Estimated total steps")

    # Reproducibility
    protocol_hash: str = Field(..., description="Protocol hash for reproducibility")
    stabilization_chain: list[str] = Field(..., description="Stabilization step names")

    # Sampling provenance (v00.97.00)
    sampling_metadata: dict[str, Any] | None = Field(
        None, description="Adaptive dump interval sampling metadata for provenance tracking"
    )

    # PR 2 (Codex Round 7): generation-time SSOT for SINGLE_MOLECULE_VACUUM
    # E_intra method/cutoff.  Pipeline reads these directly so it does not
    # have to re-parse the LAMMPS input file or re-evaluate env vars.
    e_intra_method: str | None = Field(
        None,
        description=(
            "E_intra method tag decided at LAMMPS input generation "
            "(populated for SINGLE_MOLECULE_VACUUM jobs only)."
        ),
    )
    vacuum_cutoff_a: float | None = Field(
        None,
        description="LJ/Coulomb cutoff (Å) used for SINGLE_MOLECULE_VACUUM jobs.",
    )


# =============================================================================
# E_intra Schemas
# =============================================================================


class EIntraKey(BaseModel):
    """Key for E_intra cache lookup (temperature-aware, method-aware).

    The ``method`` field is the SSOT method tag for distinguishing Method 1
    (legacy 12 Å vacuum), Method 1a (adaptive-cutoff vacuum), and the future
    Method 2 (periodic single-molecule + PPPM).  Accepts ``EIntraMethod`` or
    its string value for backward compatibility with existing call sites.
    """

    mol_id: str = Field(..., description="Molecule ID")
    ff_name: str = Field(..., description="Force field name")
    ff_version: str = Field(..., description="Force field version")
    temperature_K: float = Field(298.0, description="Temperature in Kelvin")
    method: EIntraMethod = Field(
        EIntraMethod.SINGLE_MOLECULE_VACUUM,
        description="Calculation method tag (see EIntraMethod enum)",
    )

    @field_validator("method", mode="before")
    @classmethod
    def _coerce_method(cls, v: Any) -> EIntraMethod:
        """Accept EIntraMethod, its string value, or legacy string aliases."""
        if isinstance(v, EIntraMethod):
            return v
        if isinstance(v, str):
            return coerce_e_intra_method(v)
        raise TypeError(f"EIntraKey.method must be EIntraMethod or str, got {type(v).__name__}")


class EIntraValue(BaseModel):
    """Value for E_intra cache."""

    e_intra: float = Field(..., description="E_intra value (kcal/mol)")
    temperature_K: float = Field(298.0, description="Temperature in Kelvin")
    computed_at: datetime = Field(default_factory=datetime.now)
    source_exp_id: str | None = Field(None, description="Experiment that produced this value")
    averaging_window_ps: float | None = Field(None, description="Thermo averaging window (ps)")
    n_samples: int | None = Field(None, description="Number of thermo samples averaged")
    lj_cutoff: float = Field(100.0, description="LJ cutoff used")
    coulomb_cutoff: float = Field(100.0, description="Coulomb cutoff used")


# =============================================================================
# E_inter Schemas (Phase 4.2)
# =============================================================================


class EInterResult(BaseModel):
    """Result from intermolecular energy decomposition via group/group compute.

    Attributes:
        total_e_inter: Total intermolecular energy (kcal/mol)
        pair_energies: Pairwise group energies {pair_label: energy}
        normalized_per_atom: Pairwise energies normalized per atom {pair_label: energy/atom}
    """

    total_e_inter: float = Field(..., description="Total E_inter (kcal/mol)")
    pair_energies: dict[str, float] = Field(
        ..., description="Pairwise group energies {pair_label: kcal/mol}"
    )
    normalized_per_atom: dict[str, float] = Field(
        default_factory=dict,
        description="Per-atom normalized pairwise energies {pair_label: kcal/mol/atom}",
    )


# =============================================================================
# Metric Schemas
# =============================================================================


class ArrayMetricStorage(BaseModel):
    """Storage info for array metrics (saved as files)."""

    file_path: str = Field(..., description="Path to Parquet/npy file")
    file_hash: str = Field(..., description="File content hash")
    shape: tuple[int, ...] = Field(..., description="Array shape")
    summary: dict[str, float] = Field(..., description="Summary statistics")


class MetricResult(BaseModel):
    """Result from Session D (Parser & Metrics)."""

    exp_id: str | None = Field(None, description="Experiment ID")
    metric_name: str = Field(..., description="Metric name from registry")
    value: float | None = Field(None, description="Scalar metric value")
    unit: str = Field(..., description="Unit from registry")
    namespace: str = Field(..., description="Namespace (bulk_ff, layer, etc.)")
    uncertainty: float | None = Field(None, description="Measurement uncertainty")
    layer_index: int | None = Field(None, description="Optional layer provenance index")
    interface_index: int | None = Field(None, description="Optional interface provenance index")

    # Array metrics (stored as files)
    array_storage: ArrayMetricStorage | None = Field(None, description="Array file storage")
    array_summary: dict[str, Any] | None = Field(None, description="Array summary for DB")


# =============================================================================
# Layer Enums (Phase 4.3 — SSOT migration from builder/layer_spec.py)
# =============================================================================


class LayerType(StrEnum):
    """Type of layered system."""

    INTERFACE = "interface"  # A: crystal + binder
    WATER_INTERFACE = "water-interface"  # B: crystal + water + binder
    THREE_LAYER = "3-layer"  # C: crystal + binder + crystal
    AGED_FRESH = "aged-fresh"  # D: crystal + aged_binder + fresh_binder
    WATER_AGED_FRESH = "water-aged-fresh"  # E: crystal + water + aged + fresh
    BINDER_BINDER = "binder-binder"  # F: binder + binder (internal cohesion)


class CrystalMaterial(StrEnum):
    """Crystal material types."""

    SIO2 = "SiO2"
    CITE = "CaCO3"  # Existing name (crystal_builder.py L126,161,354 + test_layer.py)
    CACO3 = "CaCO3"  # Alias for new code (StrEnum: same value → alias of CITE)
    AL2O3 = "Al2O3"
    MGO = "MgO"
    FE2O3 = "Fe2O3"
    MGCO3 = "MgCO3"
    CAO = "CaO"
    TIO2 = "TiO2"
    ZNO = "ZnO"
    NACL = "NaCl"
    KCL = "KCl"
    AL = "Al"
    FE = "Fe"
    CU = "Cu"
    NI = "Ni"
    AGGREGATE = "aggregate"


class CrystalSourceType(StrEnum):
    """Crystal source type."""

    PRESET = "preset"
    CIF = "cif"


class CrystalCellMode(StrEnum):
    """Crystal in-plane cell representation mode."""

    NATIVE_SKEW = "native_skew"
    ORTHOGONALIZED = "orthogonalized"


class SurfaceOrientation(StrEnum):
    """Crystal surface orientation."""

    ORIENT_001 = "001"
    ORIENT_010 = "010"
    ORIENT_100 = "100"
    ORIENT_110 = "110"
    ORIENT_111 = "111"


class WaterModel(StrEnum):
    """Water model types."""

    TIP3P = "TIP3P"
    TIP4P = "TIP4P"
    SPC = "SPC"
    SPCE = "SPC/E"


class LayerScenario(StrEnum):
    """Multi-layer interface scenario identifiers."""

    A = "A"  # Crystal-Binder
    B = "B"  # Crystal-Water-Binder
    C = "C"  # Crystal-Binder-Crystal (sandwich)
    D = "D"  # Crystal-Aged-Fresh
    E = "E"  # Crystal-Water-Aged-Fresh
    F = "F"  # Binder-Binder (internal cohesion)


class LayerSourceType(StrEnum):
    """Source type used by single-job layered structure composer."""

    BINDER_CELL = "binder_cell"
    INTERFACE_MOLECULE_CELL = "interface_molecule_cell"
    CRYSTAL_STRUCTURE = "crystal_structure"


# =============================================================================
# Layer Sub-models (Phase 4.3)
# =============================================================================


class LayerStackItem(BaseModel):
    """One layer source entry in user-defined stack composition."""

    source_type: LayerSourceType
    source_id: str = Field(..., min_length=1)
    label: str | None = Field(None, max_length=80)


class LayerStackSpec(BaseModel):
    """User-defined stack composition for 2-5 layer systems."""

    layers: list[LayerStackItem] = Field(..., min_length=2, max_length=5)
    xy_tolerance_pct: float | None = Field(
        None, gt=0, le=50, description="XY tolerance (%). None = policy default."
    )
    xy_tolerance_angstrom: float | None = Field(
        None, gt=0, description="Deprecated: use xy_tolerance_pct"
    )
    min_xy_to_z_ratio: float = Field(1.2, gt=0)


class CrystalLayerSpec(BaseModel):
    """Crystal slab specification."""

    material: CrystalMaterial = Field(default=CrystalMaterial.SIO2)
    surface: SurfaceOrientation = Field(default=SurfaceOrientation.ORIENT_001)
    cell_mode: CrystalCellMode = Field(default=CrystalCellMode.ORTHOGONALIZED)
    thickness_angstrom: float = Field(25.0, gt=0)
    xy_size_angstrom: float = Field(50.0, gt=0)
    nx: int = Field(5, gt=0)
    ny: int = Field(5, gt=0)
    nz: int = Field(3, gt=0)
    hydroxylated: bool = Field(True)
    hydroxyl_density: float = Field(4.6, gt=0)
    use_matrix_search: bool = Field(True)
    max_cells_xy: int = Field(200, gt=0, le=1000)
    matrix_ortho_tolerance: float = Field(1e-8, gt=0, le=0.01)


class CrystalTemplateSpec(BaseModel):
    """Reusable crystal template specification for crystal library."""

    name: str = Field(..., min_length=1, max_length=120)
    source_type: CrystalSourceType = Field(default=CrystalSourceType.PRESET)
    crystal: CrystalLayerSpec = Field(default_factory=CrystalLayerSpec)
    cif_path: str | None = Field(None, description="Optional CIF source path")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AmorphousBoundaryMode(StrEnum):
    """Boundary mode for amorphous cell stabilization."""

    PPP = "ppp"
    PPF = "ppf"


class AmorphousComponentSpec(BaseModel):
    """Single amorphous component definition (base molecule + weight ratio)."""

    mol_id: str = Field(..., min_length=1)
    weight_ratio: float = Field(..., gt=0)


class AmorphousCellSpec(BaseModel):
    """Amorphous cell generation/stabilization specification."""

    name: str = Field(..., min_length=1, max_length=120)
    component_mol_id: str | None = Field(
        None,
        min_length=1,
        description="Single non-binder component mol_id",
    )
    components: list[AmorphousComponentSpec] | None = Field(
        None,
        min_length=1,
        max_length=1,
        description="Deprecated: single-component list for backward compatibility",
    )
    lx_angstrom: float = Field(40.0, gt=0)
    ly_angstrom: float = Field(40.0, gt=0)
    lz_angstrom: float = Field(20.0, gt=0)
    initial_density: float = Field(1.0, gt=0)
    target_density: float | None = Field(
        None,
        gt=0,
        description="Deprecated alias for initial_density",
    )
    boundary_mode: AmorphousBoundaryMode = Field(default=AmorphousBoundaryMode.PPP)
    ff_type: FFType = Field(default=FFType.BULK_FF_GAFF2)
    temperature_K: float = Field(298.0, gt=0)
    seed: int | None = Field(None)
    minimize_steps: int = Field(1000, gt=0)
    nvt_ps: float = Field(300.0, gt=0)
    npt_ps: float = Field(1000.0, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_single_component(self):
        if self.target_density is not None:
            self.initial_density = float(self.target_density)

        if self.components:
            if len(self.components) != 1:
                raise ValueError("Exactly one component is required")
            legacy_mol_id = self.components[0].mol_id.strip()
            if not self.component_mol_id:
                self.component_mol_id = legacy_mol_id
            elif self.component_mol_id.strip() != legacy_mol_id:
                raise ValueError("component_mol_id must match components[0].mol_id")

        if self.component_mol_id:
            self.component_mol_id = self.component_mol_id.strip()

        if not self.component_mol_id:
            raise ValueError("component_mol_id is required")

        return self


class WaterLayerSpec(BaseModel):
    """Water layer specification."""

    thickness_angstrom: float = Field(10.0, gt=0)
    model: WaterModel = Field(default=WaterModel.TIP3P)
    density: float = Field(1.0, gt=0)


class BinderLayerConfig(BaseModel):
    """Binder layer specification."""

    composition_ref: str = Field("default")
    thickness_angstrom: float = Field(50.0, gt=0)
    target_density: float = Field(1.0, gt=0)
    asphaltene_wt: float = Field(20.0, ge=0)
    resin_wt: float = Field(30.0, ge=0)
    aromatic_wt: float = Field(35.0, ge=0)
    saturate_wt: float = Field(15.0, ge=0)
    additive_wt: float = Field(0.0, ge=0)
    aging_state: AgingState | None = Field(None, description="Aging state of binder")


# =============================================================================
# Layer Schemas (Phase 4.3 — structured SSOT replacing flat LayerSpec)
# =============================================================================


class LayerSpec(BaseModel):
    """Complete layer system specification (SSOT).

    Phase 4.3: Replaces the flat LayerSpec with structured sub-models.
    Backward compatible via model_validator for flat dict inputs.
    """

    layer_type: LayerType = Field(default=LayerType.INTERFACE)
    scenario: LayerScenario | None = Field(None, description="Scenario A~F")
    stacking_axis: str = Field("z")

    # Layer components
    stack_spec: LayerStackSpec | None = Field(
        None,
        description="Optional user-defined layer stack (single-job layered structure composer)",
    )
    crystal: CrystalLayerSpec = Field(default_factory=CrystalLayerSpec)
    crystal_template_id: str | None = Field(
        None,
        description="Optional reference ID of a persisted crystal template",
    )
    amorphous_cell_id: str | None = Field(
        None,
        description="Optional reference ID of a persisted amorphous cell",
    )
    water: WaterLayerSpec | None = Field(None)
    binder: BinderLayerConfig = Field(default_factory=BinderLayerConfig)
    binder_secondary: BinderLayerConfig | None = Field(
        None, description="Secondary binder (aged-fresh D/E scenarios)"
    )

    # System parameters
    temperature_k: float = Field(298.0, gt=0)
    pressure_atm: float = Field(1.0, gt=0)
    seed: int = Field(default_factory=generate_seed)
    min_distance: float = Field(2.0, gt=0)
    vacuum_above: float = Field(0.0, ge=0)
    vacuum_below: float = Field(0.0, ge=0)

    # Reproducibility (Phase 4.1)
    interface_stack_id: str | None = Field(None)
    grip_mode: str | None = Field(
        None,
        description=(
            "Metadata-only: records how grip regions were determined "
            "(e.g. 'crystal_full'). Not used for execution branching; "
            "actual grip regions are driven by bottom/top_grip_z_range."
        ),
    )
    layer_boundary_z: list[float] | None = Field(None)
    bottom_grip_z_range: tuple[float, float] | None = Field(
        None,
        description="Explicit [z_lo, z_hi] for bottom grip (overrides grip_thickness)",
    )
    top_grip_z_range: tuple[float, float] | None = Field(
        None,
        description="Explicit [z_lo, z_hi] for top grip (overrides grip_thickness)",
    )
    aging_state: AgingState | None = Field(None)

    # --- Flat dict keys for backward compatibility detection ---
    _FLAT_KEYS: frozenset[str] = frozenset(
        {
            "crystal_material",
            "crystal_thickness_angstrom",
            "crystal_surface",
            "water_thickness_angstrom",
            "water_model",
            "binder_thickness_angstrom",
            "binder_composition_ref",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_spec(cls, data: Any) -> Any:
        """Convert flat LayerSpec dict to structured format.

        Flat key detection: if any key in _FLAT_KEYS is present, migrate.
        Protects existing test patterns like LayerSpec(binder_composition_ref="AAA1").
        """
        if not isinstance(data, dict):
            return data

        flat_keys = frozenset(
            {
                "crystal_material",
                "crystal_thickness_angstrom",
                "crystal_surface",
                "water_thickness_angstrom",
                "water_model",
                "binder_thickness_angstrom",
                "binder_composition_ref",
            }
        )

        if not (flat_keys & data.keys()):
            return data

        # Crystal migration
        crystal = {}
        if "crystal_material" in data:
            crystal["material"] = data.pop("crystal_material")
        if "crystal_thickness_angstrom" in data:
            crystal["thickness_angstrom"] = data.pop("crystal_thickness_angstrom")
        if "crystal_surface" in data:
            crystal["surface"] = data.pop("crystal_surface")
        if crystal:
            data.setdefault("crystal", crystal)

        # Water migration
        water = {}
        if "water_thickness_angstrom" in data:
            water["thickness_angstrom"] = data.pop("water_thickness_angstrom")
        if "water_model" in data:
            water["model"] = data.pop("water_model")
        if water:
            data.setdefault("water", water)

        # Binder migration
        binder = {}
        if "binder_composition_ref" in data:
            binder["composition_ref"] = data.pop("binder_composition_ref")
        if "binder_thickness_angstrom" in data:
            binder["thickness_angstrom"] = data.pop("binder_thickness_angstrom")
        if binder:
            data.setdefault("binder", binder)

        return data

    # --- Factory classmethods ---

    @classmethod
    def create_interface(
        cls,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        binder_thickness: float = 50.0,
        crystal_thickness: float = 25.0,
    ) -> "LayerSpec":
        """Create a simple crystal-binder interface (Scenario A)."""
        return cls(
            layer_type=LayerType.INTERFACE,
            scenario=LayerScenario.A,
            crystal=CrystalLayerSpec(
                material=crystal_material,
                thickness_angstrom=crystal_thickness,
            ),
            binder=BinderLayerConfig(thickness_angstrom=binder_thickness),
        )

    @classmethod
    def create_water_interface(
        cls,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        water_thickness: float = 10.0,
        binder_thickness: float = 50.0,
    ) -> "LayerSpec":
        """Create a crystal-water-binder interface (Scenario B)."""
        return cls(
            layer_type=LayerType.WATER_INTERFACE,
            scenario=LayerScenario.B,
            crystal=CrystalLayerSpec(material=crystal_material),
            water=WaterLayerSpec(thickness_angstrom=water_thickness),
            binder=BinderLayerConfig(thickness_angstrom=binder_thickness),
        )

    @classmethod
    def create_sandwich(
        cls,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        binder_thickness: float = 50.0,
    ) -> "LayerSpec":
        """Create a crystal-binder-crystal sandwich (Scenario C)."""
        return cls(
            layer_type=LayerType.THREE_LAYER,
            scenario=LayerScenario.C,
            crystal=CrystalLayerSpec(material=crystal_material),
            binder=BinderLayerConfig(thickness_angstrom=binder_thickness),
        )

    @classmethod
    def create_aged_fresh(
        cls,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        aged_binder_thickness: float = 40.0,
        fresh_binder_thickness: float = 40.0,
        crystal_thickness: float = 25.0,
    ) -> "LayerSpec":
        """Create crystal + aged_binder + fresh_binder (Scenario D)."""
        return cls(
            layer_type=LayerType.AGED_FRESH,
            scenario=LayerScenario.D,
            crystal=CrystalLayerSpec(
                material=crystal_material,
                thickness_angstrom=crystal_thickness,
            ),
            binder=BinderLayerConfig(
                thickness_angstrom=aged_binder_thickness,
                aging_state=AgingState.LONG_AGING,
            ),
            binder_secondary=BinderLayerConfig(
                thickness_angstrom=fresh_binder_thickness,
                aging_state=AgingState.NON_AGING,
            ),
        )

    @classmethod
    def create_water_aged_fresh(
        cls,
        crystal_material: CrystalMaterial = CrystalMaterial.SIO2,
        water_thickness: float = 10.0,
        aged_binder_thickness: float = 40.0,
        fresh_binder_thickness: float = 40.0,
    ) -> "LayerSpec":
        """Create crystal + water + aged + fresh (Scenario E)."""
        return cls(
            layer_type=LayerType.WATER_AGED_FRESH,
            scenario=LayerScenario.E,
            crystal=CrystalLayerSpec(material=crystal_material),
            water=WaterLayerSpec(thickness_angstrom=water_thickness),
            binder=BinderLayerConfig(
                thickness_angstrom=aged_binder_thickness,
                aging_state=AgingState.LONG_AGING,
            ),
            binder_secondary=BinderLayerConfig(
                thickness_angstrom=fresh_binder_thickness,
                aging_state=AgingState.NON_AGING,
            ),
        )

    @classmethod
    def create_binder_binder(
        cls,
        binder1_thickness: float = 50.0,
        binder2_thickness: float = 50.0,
    ) -> "LayerSpec":
        """Create binder + binder (Scenario F, internal cohesion)."""
        return cls(
            layer_type=LayerType.BINDER_BINDER,
            scenario=LayerScenario.F,
            binder=BinderLayerConfig(thickness_angstrom=binder1_thickness),
            binder_secondary=BinderLayerConfig(thickness_angstrom=binder2_thickness),
        )

    # --- Helper methods ---

    def get_total_height(self) -> float:
        """Calculate total system height in Angstroms."""
        # Binder-binder scenario has no crystal layer.
        if self.layer_type == LayerType.BINDER_BINDER:
            height = self.binder.thickness_angstrom
        else:
            height = self.crystal.thickness_angstrom + self.binder.thickness_angstrom

        if self.water:
            height += self.water.thickness_angstrom

        if self.layer_type == LayerType.THREE_LAYER:
            height += self.crystal.thickness_angstrom  # Top crystal

        if self.binder_secondary:
            height += self.binder_secondary.thickness_angstrom

        height += self.vacuum_above + self.vacuum_below

        return height

    def get_layer_boundaries(self) -> dict[str, tuple[float, float]]:
        """Get z-boundaries for each layer.

        Returns:
            Dict mapping layer name to (z_min, z_max)
        """
        boundaries: dict[str, tuple[float, float]] = {}
        z = self.vacuum_below

        # Binder-binder: no crystal
        if self.layer_type == LayerType.BINDER_BINDER:
            boundaries["binder"] = (z, z + self.binder.thickness_angstrom)
            z += self.binder.thickness_angstrom
            if self.binder_secondary:
                boundaries["binder_secondary"] = (
                    z,
                    z + self.binder_secondary.thickness_angstrom,
                )
            return boundaries

        # Bottom crystal
        boundaries["crystal_bottom"] = (z, z + self.crystal.thickness_angstrom)
        z += self.crystal.thickness_angstrom

        # Water (if present)
        if self.water:
            boundaries["water"] = (z, z + self.water.thickness_angstrom)
            z += self.water.thickness_angstrom

        # Binder (primary / aged)
        boundaries["binder"] = (z, z + self.binder.thickness_angstrom)
        z += self.binder.thickness_angstrom

        # Secondary binder (fresh, for D/E scenarios)
        if self.binder_secondary:
            boundaries["binder_secondary"] = (
                z,
                z + self.binder_secondary.thickness_angstrom,
            )
            z += self.binder_secondary.thickness_angstrom

        # Top crystal (for sandwich C)
        if self.layer_type == LayerType.THREE_LAYER:
            boundaries["crystal_top"] = (z, z + self.crystal.thickness_angstrom)

        return boundaries

    # --- Backward compat ---

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "LayerSpec":
        """Create from dictionary."""
        return cls.model_validate(data)


# =============================================================================
# Experiment Schemas
# =============================================================================


class ExperimentRecord(BaseModel):
    """Complete experiment record for database storage."""

    exp_id: str = Field(..., description="Experiment ID")
    material_id: str = Field(..., description="Material ID")
    binder_type: str | None = Field(None, description="Binder type (e.g. AAA1)")
    structure_size: str | None = Field(None, description="Structure size (e.g. X1)")
    aging_state: AgingState | None = Field(None, description="Aging state of binder")

    # Force field info
    force_field_type: FFType = Field(FFType.BULK_FF_GAFF2)
    force_field_name: str = Field("GAFF2")
    force_field_version: str = Field("1.0")

    # Classification
    study_type: StudyType = Field(StudyType.BULK)
    run_tier: RunTier = Field(RunTier.SCREENING)

    # Conditions
    temperature_k: float = Field(298.0)
    pressure_atm: float = Field(1.0)
    target_atoms: int = Field(100000)
    tensile_strain_rate_1_per_ps: float | None = Field(
        None, description="Engineering strain rate for tensile loading (1/ps)"
    )
    tensile_pull_velocity_a_per_fs: float | None = Field(
        None, description="Tensile pull velocity (Angstrom/fs)"
    )
    shear_rate_1_per_ps: float | None = Field(None, description="Shear rate (1/ps)")

    # Validity domain
    validity_domain_tag: list[ValidityDomainTag] = Field(default_factory=list)

    # ReaxFF selection reason (if applicable)
    selection_reason: dict[str, Any] | None = Field(None)

    # Status
    status: ExperimentStatus = Field(ExperimentStatus.PENDING)
    failure_category: FailureCategory | None = Field(None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(None)

    # Results
    build_result: BuildResult | None = Field(None)
    protocol_result: ProtocolResult | None = Field(None)
    lammps_result: Optional["LAMMPSRunResult"] = Field(None, description="LAMMPS run result")
    metrics: list[MetricResult] = Field(default_factory=list)
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")

    # Additive tracking (synced with DB migration 008)
    additive_type: str | None = Field(
        None, description="Additive type (polymer/surfactant/nanoparticle or common name)"
    )
    additive_wt: float = Field(0.0, ge=0.0, description="Additive weight fraction (%)")
    additive_mol_id: str | None = Field(None, description="Additive molecule ID")
    conditions: list["ExperimentConditionRecord"] = Field(
        default_factory=list,
        description="Non-core extensible condition rows persisted in experiment_conditions",
    )


class ExperimentConditionRecord(BaseModel):
    """Structured extensible condition row for experiment_conditions."""

    condition_key: str = Field(..., description="Canonical condition key")
    value_number: float | None = Field(None, description="Numeric condition value")
    value_text: str | None = Field(None, description="Text condition value")
    value_bool: bool | None = Field(None, description="Boolean condition value")
    value_json: dict[str, Any] | list[Any] | None = Field(None, description="JSON condition value")
    unit: str | None = Field(None, description="Optional unit for numeric values")
    source: str | None = Field(None, description="Origin of the condition")

    @model_validator(mode="after")
    def _validate_single_value_slot(self) -> "ExperimentConditionRecord":
        populated = sum(
            value is not None
            for value in (
                self.value_number,
                self.value_text,
                self.value_bool,
                self.value_json,
            )
        )
        if populated != 1:
            raise ValueError(
                "Exactly one of value_number, value_text, value_bool, value_json must be set"
            )
        return self


# =============================================================================
# Execution Schemas
# =============================================================================


class LAMMPSRunResult(BaseModel):
    """Result from LAMMPS execution."""

    success: bool = Field(..., description="Whether run succeeded")
    log_file: str = Field(..., description="Path to log file")
    dump_files: list[str] = Field(default_factory=list, description="Dump file paths")
    restart_file: str | None = Field(None, description="Restart file path (for recovery)")
    wall_time_seconds: float = Field(..., ge=0, description="Wall clock time")
    exit_code: int = Field(..., description="LAMMPS exit code")
    error_message: str | None = Field(None, description="Error message if failed")
    exp_id: str | None = Field(
        None, description="Experiment ID (set by pipeline/runner for metric storage)"
    )
    # New fields for v00.69.06
    gpu_id_used: int | None = Field(
        None, description="Actual GPU ID used during execution (may differ from gpu_id_allocated)"
    )
    last_successful_step: int | None = Field(
        None, description="Last successful timestep (for recovery from restart)"
    )

    # Group energy spec for E_inter/pair-RDF (Phase 4.2)
    group_energy_spec: GroupEnergySpec | None = Field(
        None, description="Group energy config for metric calculation"
    )

    # CED E_intra lookup metadata (Phase v00.97.06)
    mol_counts: dict[str, int] = Field(
        default_factory=dict, description="Molecule ID -> count for CED E_intra lookup"
    )
    mol_counts_by_layer: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Layer label -> {mol_id: count} for layered CED profile lookup",
    )
    layer_volumes_A3: dict[str, float] = Field(
        default_factory=dict,
        description="Layer label -> physical volume (A^3) for layered CED profile calculation",
    )
    layer_labels: list[str] = Field(
        default_factory=list,
        description="Canonical ordered layer labels for layered CED profile output",
    )
    force_field: str = Field("GAFF2", description="Force field name for E_intra lookup")
    ff_version: str = Field("1.0", description="Force field version for E_intra lookup")
    temperature_K: float = Field(298.0, description="Simulation temperature for E_intra lookup")
    study_type: str = Field(
        "bulk",
        description="Study type for metric filtering (bulk | single_molecule_vacuum | layer_bulkff)",
    )

    # Persisted Method 1a / 2 provenance (PR 2 v4) — populated at LAMMPS input
    # generation time so the storage path does not need to re-read env/data_file.
    e_intra_method: str | None = Field(
        None,
        description=(
            "E_intra method tag decided at input-generation time "
            "('single_molecule_vacuum' | 'single_molecule_vacuum_adaptive_cutoff' | "
            "'single_molecule_periodic').  None for non-single-molecule study types."
        ),
    )
    vacuum_cutoff_a: float | None = Field(
        None,
        description=(
            "LJ/Coulomb cutoff (Å) actually used for SINGLE_MOLECULE_VACUUM jobs. "
            "12.0 for Method 1, max(50, 2×extent) for Method 1a, None otherwise."
        ),
    )

    # Phase 4.3: Tensile metadata
    tensile_spec: Optional["TensileSpec"] = Field(None, description="Tensile test config")
    interface_area_nm2: float | None = Field(None, description="Interface area (nm^2)")
    original_gap_angstrom: float | None = Field(
        None, description="Original gap between grips (Angstrom)"
    )


# NOTE: model_rebuild() calls moved to after TensileSpec definition (Phase 4.3)


# =============================================================================
# Thermo Data Schemas
# =============================================================================


class ThermoData(BaseModel):
    """Parsed thermo data from LAMMPS log."""

    step: list[int] = Field(..., description="Timestep")
    time_ps: list[float] = Field(..., description="Time (ps)")
    temperature: list[float] = Field(..., description="Temperature (K)")
    pressure: list[float] = Field(..., description="Pressure (atm)")
    total_energy: list[float] = Field(..., description="Total energy")
    kinetic_energy: list[float] = Field(..., description="Kinetic energy")
    potential_energy: list[float] = Field(..., description="Potential energy")
    volume: list[float] = Field(..., description="Volume (Angstrom^3)")
    density: list[float] = Field(..., description="Density (g/cm3)")


# =============================================================================
# Composition Result Schema
# =============================================================================


class CompositionResult(BaseModel):
    """Result from composition calculation."""

    mol_counts: dict[str, int] = Field(..., description="Molecule counts")
    actual_wt: dict[str, float] = Field(..., description="Actual wt%")
    target_wt: dict[str, float] = Field(..., description="Target wt%")
    error_l1: float = Field(..., ge=0, description="L1 error in wt%")
    total_atoms: int = Field(..., gt=0, description="Total atom count")
    total_mass: float = Field(..., gt=0, description="Total mass (g/mol)")


# =============================================================================
# Molecule-Based Build Schemas (New UI)
# =============================================================================


class MoleculeCountSpec(BaseModel):
    """Single molecule count specification."""

    mol_id: str = Field(..., description="Molecule ID (e.g., SA-Squalane, AR-PHPN)")
    count: int = Field(..., ge=0, description="Number of molecules")


class ViscositySpec(BaseModel):
    """Viscosity calculation settings."""

    enabled: bool = Field(False, description="Enable viscosity calculation")
    temperatures_K: list[float] = Field(
        default_factory=lambda: [298.0], description="Temperatures for viscosity calculation (K)"
    )


class TensileMode(StrEnum):
    """Tensile test mode."""

    CONTINUOUS = "continuous"
    QUASI_STATIC = "quasi_static"


class TensileSpec(BaseModel):
    """Tensile strength calculation settings."""

    enabled: bool = Field(False, description="Enable tensile calculation")
    temperatures_K: list[float] = Field(
        default_factory=lambda: [298.0], description="Temperatures for tensile calculation (K)"
    )

    # Tensile test parameters (Phase 4.1)
    pull_velocity_A_per_fs: float = Field(0.00005, gt=0, description="Pull velocity (Angstrom/fs)")
    grip_thickness_angstrom: float = Field(
        20.0, gt=0, description="Grip region thickness (Angstrom)"
    )
    max_strain: float = Field(0.5, gt=0, le=2.0, description="Maximum engineering strain")
    pull_axis: str = Field("z", description="Pull direction axis")
    layer_scenario: str | None = Field(None, description="Multi-layer scenario reference (A~F)")

    # Phase 4.3: output frequency
    output_interval_steps: int = Field(
        100, gt=0, description="Stress/strain output frequency (steps)"
    )

    # Quasi-static decohesion parameters
    mode: TensileMode = Field(TensileMode.CONTINUOUS, description="Tensile test mode")
    displacement_increment_angstrom: float = Field(
        0.5, gt=0, description="QS displacement per step (Angstrom)"
    )
    relax_steps: int = Field(10000, gt=0, description="QS NVT relaxation steps per displacement")
    force_average_steps: int = Field(1000, gt=0, description="QS force time-averaging steps")

    @model_validator(mode="after")
    def _validate_qs_params(self) -> "TensileSpec":
        if self.mode == TensileMode.QUASI_STATIC:
            if self.force_average_steps > self.relax_steps:
                raise ValueError(
                    f"force_average_steps ({self.force_average_steps}) must be "
                    f"<= relax_steps ({self.relax_steps}) in quasi_static mode"
                )
        return self


# Resolve forward references (after TensileSpec + LayerSpec are defined)
ExperimentRecord.model_rebuild()
ProtocolRequest.model_rebuild()
LAMMPSRunResult.model_rebuild()


class PropertyCalculationSpec(BaseModel):
    """Optional property calculation settings."""

    viscosity: ViscositySpec | None = Field(None, description="Viscosity calculation settings")
    tensile: TensileSpec | None = Field(None, description="Tensile strength settings (future)")


class MoleculeBasedBuildRequest(BaseModel):
    """Molecule-based experiment request (new UI format)."""

    # Binder selection
    binder_type: str = Field("AAA1", description="Binder type: AAA1, AAK1, AAM1, or 'custom'")
    structure_size: str = Field("X1", description="Structure size: X1, X2, X3")
    aging_state: AgingState = Field(AgingState.NON_AGING, description="Aging state")

    # Molecule composition
    molecule_counts: list[MoleculeCountSpec] = Field(..., description="Molecule counts list")
    additives: list[MoleculeCountSpec] | None = Field(None, description="Optional additives")

    # Simulation parameters
    temperature_K: float = Field(298.0, gt=0, description="Simulation temperature (K)")
    run_tier: RunTier = Field(RunTier.SCREENING, description="Run tier")
    ff_type: FFType = Field(FFType.BULK_FF_GAFF2, description="Force field type")

    # Optional property calculations
    property_calculations: PropertyCalculationSpec | None = Field(
        None, description="Optional property calculations (viscosity, tensile)"
    )

    # Random seed (auto-generated if None)
    seed: int | None = Field(None, description="Random seed")

    @field_validator("binder_type")
    @classmethod
    def validate_binder_type(cls, v: str) -> str:
        valid_types = ["AAA1", "AAK1", "AAM1", "custom"]
        if v not in valid_types:
            raise ValueError(f"binder_type must be one of {valid_types}")
        return v

    @field_validator("structure_size")
    @classmethod
    def validate_structure_size(cls, v: str) -> str:
        valid_sizes = ["X1", "X2", "X3"]
        if v not in valid_sizes:
            raise ValueError(f"structure_size must be one of {valid_sizes}")
        return v


class BinderCompositionResponse(BaseModel):
    """Response for binder composition query."""

    binder_type: str = Field(..., description="Binder type name")
    description: str = Field(..., description="Binder description")
    structure_size: str = Field(..., description="Selected structure size")
    molecules: list[MoleculeCountSpec] = Field(..., description="Molecule counts")
    total_molecules: int = Field(..., description="Total molecule count")
    sara_fractions: dict[str, float] = Field(..., description="SARA weight fractions")


# =============================================================================
# Process Tracking Schemas
# =============================================================================


class ProcessState(StrEnum):
    """LAMMPS process state for recovery tracking."""

    RUNNING = "running"  # Process is actively running
    STALE = "stale"  # No heartbeat but process exists
    ORPHANED = "orphaned"  # Process exists but not in DB
    TERMINATED = "terminated"  # Process has ended
    UNKNOWN = "unknown"  # Cannot determine state (remote host)


class RecoveryAction(StrEnum):
    """Actions that can be taken to recover a process."""

    RESUME = "resume"  # Resume monitoring the process
    RECOVER_RESULTS = "recover"  # Parse partial results and mark complete
    RESTART = "restart"  # Terminate and restart the simulation
    ABANDON = "abandon"  # Mark as failed and clean up
    IGNORE = "ignore"  # Leave for manual handling


class ProcessInfo(BaseModel):
    """Information about a tracked LAMMPS process."""

    exp_id: str = Field(..., description="Experiment ID")
    pid: int = Field(..., description="OS process ID")
    hostname: str = Field(..., description="Host running the process")
    working_dir: str = Field(..., description="Working directory path")
    gpu_id: int | None = Field(None, description="Allocated GPU ID")
    started_at: datetime | None = Field(None, description="Process start time")
    last_heartbeat: datetime | None = Field(None, description="Last heartbeat time")
    current_step: int | None = Field(None, description="Current simulation step")
    total_steps: int | None = Field(None, description="Total expected steps")
    temperature: float | None = Field(None, description="Latest temperature (K)")
    pressure: float | None = Field(None, description="Latest pressure (atm)")
    density: float | None = Field(None, description="Latest density (g/cm3)")
    energy: float | None = Field(None, description="Latest potential energy")

    @property
    def progress_percent(self) -> float | None:
        """Calculate progress percentage."""
        if self.current_step is not None and self.total_steps and self.total_steps > 0:
            return (self.current_step / self.total_steps) * 100.0
        return None


class RecoveryCandidate(BaseModel):
    """A process/experiment that may need recovery."""

    exp_id: str = Field(..., description="Experiment ID")
    pid: int = Field(..., description="Process ID")
    hostname: str = Field(..., description="Hostname")
    state: ProcessState = Field(..., description="Detected process state")
    db_status: str = Field(..., description="Status in database")
    last_seen: datetime | None = Field(None, description="Last known activity")
    progress_percent: float | None = Field(None, description="Simulation progress")
    gpu_id: int | None = Field(None, description="Allocated GPU")
    working_dir: str = Field(..., description="Working directory")
    available_actions: list[RecoveryAction] = Field(
        default_factory=list, description="Valid recovery actions"
    )
    recommended_action: RecoveryAction = Field(..., description="Recommended action")
    reason: str = Field(..., description="Reason for recommendation")


class RecoveryResult(BaseModel):
    """Result of a recovery action."""

    success: bool = Field(..., description="Whether action succeeded")
    action: RecoveryAction = Field(..., description="Action that was taken")
    exp_id: str = Field(..., description="Experiment ID")
    message: str = Field(..., description="Result message")
    error: str | None = Field(None, description="Error details if failed")


# =============================================================================
# 3D Structure Visualization Schemas
# =============================================================================


class StructureStage(StrEnum):
    """Simulation stage for structure visualization.

    Maps to stabilization.py step names (SSOT).
    """

    INITIAL = "initial"  # data.lammps (t=0)
    NVT_EQUILIBRATION = "nvt_equilibration"  # dump_nvt_equilibration.lammpstrj
    NPT_PRODUCTION = "npt_production"  # dump_npt_production.lammpstrj
    VISCOSITY_NEMD = "viscosity_nemd"  # dump_viscosity_nemd.lammpstrj (viscosity tier only)
    FINAL = "final"  # Last available stage (chain order)


class StructureResponse(BaseModel):
    """3D structure response for visualization."""

    xyz: str = Field(..., description="XYZ format string for 3Dmol.js")
    box_size: tuple[float, float, float] = Field(
        ..., description="Box dimensions [lx, ly, lz] in Angstrom"
    )
    n_atoms: int = Field(..., gt=0, description="Number of atoms")
    density: float | None = Field(None, description="Density in g/cm3 (if calculable)")
    stage: str = Field(..., description="Actual stage name (resolved for 'final')")
    timestep: int = Field(..., ge=0, description="Timestep from dump file")


class AvailableStagesResponse(BaseModel):
    """Available structure stages for an experiment."""

    stages: list[str] = Field(..., description="List of available stage names")
    tier: str = Field(..., description="Experiment tier (screening, confirm, viscosity)")
