"""Crystal structure, amorphous cell, and layered structure schemas."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.schemas.e_intra_method import validate_submission_e_intra_method
from contracts.policies.e_inter_compute import EInterComputeConfig
from contracts.policies.layer import DEFAULT_LAYER_POLICY as _LAYER_POLICY
from contracts.schemas import (
    AmorphousBoundaryMode,
    CrystalCellMode,
    CrystalLayerSpec,
    CrystalMaterial,
    CrystalSourceType,
    FFType,
    LayerSourceType,
    SurfaceOrientation,
)

from .experiments import (
    EInterRecommendationResponse,
    EquilibrationSettingsRequest,
    StageDurationOverrideRequest,
    StageRequest,
)

# =============================================================================
# Crystal Structure Library Models
# =============================================================================

_CRYSTAL_DEFAULTS = CrystalLayerSpec()


class CrystalStructureCreateRequest(BaseModel):
    """Create crystal structure request."""

    model_config = ConfigDict(title="CrystalStructureCreateRequest")

    name: str = Field(..., min_length=1, max_length=120)
    source_type: CrystalSourceType = Field(default=CrystalSourceType.PRESET)
    material: CrystalMaterial = Field(default=_CRYSTAL_DEFAULTS.material)
    surface: SurfaceOrientation = Field(default=_CRYSTAL_DEFAULTS.surface)
    cell_mode: CrystalCellMode = Field(default=_CRYSTAL_DEFAULTS.cell_mode)
    thickness_angstrom: float = Field(_CRYSTAL_DEFAULTS.thickness_angstrom, gt=0)
    xy_size_angstrom: float = Field(_CRYSTAL_DEFAULTS.xy_size_angstrom, gt=0)
    nx: int = Field(_CRYSTAL_DEFAULTS.nx, gt=0)
    ny: int = Field(_CRYSTAL_DEFAULTS.ny, gt=0)
    nz: int = Field(_CRYSTAL_DEFAULTS.nz, gt=0)
    hydroxylated: bool = _CRYSTAL_DEFAULTS.hydroxylated
    hydroxyl_density: float = Field(_CRYSTAL_DEFAULTS.hydroxyl_density, gt=0)
    use_matrix_search: bool = Field(_CRYSTAL_DEFAULTS.use_matrix_search)
    max_cells_xy: int = Field(_CRYSTAL_DEFAULTS.max_cells_xy, gt=0, le=1000)
    matrix_ortho_tolerance: float = Field(_CRYSTAL_DEFAULTS.matrix_ortho_tolerance, gt=0, le=0.01)
    cif_path: str | None = Field(None, description="Optional CIF path when source_type='cif'")
    cif_content: str | None = Field(
        None,
        description="Optional CIF text content when source_type='cif'",
    )
    metadata: dict[str, Any] | None = Field(None, description="Optional user metadata")

    @field_validator("cif_path")
    @classmethod
    def validate_cif_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        vv = v.strip()
        return vv or None


class CrystalStructureResponse(BaseModel):
    """Crystal structure response payload."""

    model_config = ConfigDict(title="CrystalStructureResponse")

    crystal_id: str
    name: str
    source_type: str
    material: str
    surface: str
    cell_mode: str | None = None
    status: str
    atom_count: int
    nx: int
    ny: int
    nz: int
    thickness_angstrom: float
    xy_size_angstrom: float
    hydroxylated: bool
    hydroxyl_density: float
    xyz_file_path: str | None = None
    lammps_data_file_path: str | None = None
    cif_file_path: str | None = None
    actual_lx_angstrom: float | None = None
    actual_ly_angstrom: float | None = None
    anisotropy_pct: float | None = None
    transformation_matrix: list[list[int]] | None = None
    n_cells_xy: int | None = None
    error_xy_pct: float | None = None
    matrix_search_used: bool = False
    matrix_search_fallback_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class CrystalStructureListResponse(BaseModel):
    """Crystal structure list response."""

    model_config = ConfigDict(title="CrystalStructureListResponse")

    total: int
    items: list[CrystalStructureResponse]


LibraryVisibility = Literal["library", "all"]


class CrystalStructurePreviewResponse(BaseModel):
    """Crystal structure preview payload for 3D viewer."""

    model_config = ConfigDict(title="CrystalStructurePreviewResponse")

    crystal_id: str
    xyz: str
    box_size: tuple[float, float, float]
    n_atoms: int
    n_bonds: int
    bonds: list[list[int]]
    density: float | None = None
    type_map: dict[str, str] | None = None


# =============================================================================
# Layered Experiment Library Models
# =============================================================================


class LayerSourceInfo(BaseModel):
    """Single layer source in a layered experiment."""

    model_config = ConfigDict(title="LayerSourceInfo")

    layer_index: int
    source_type: str
    source_id: str | None = None
    label: str | None = None
    gap_after_angstrom: float | None = None


class LayeredExperimentResponse(BaseModel):
    """Completed layered experiment entry for library."""

    model_config = ConfigDict(title="LayeredExperimentResponse")

    exp_id: str
    name: str
    status: str
    temperature_K: float | None = None
    completed_at: str | None = None
    box_lx: float | None = None
    box_ly: float | None = None
    box_lz: float | None = None
    layer_count: int = 0
    layers: list[LayerSourceInfo] = Field(default_factory=list)
    tensile_strength: float | None = None
    elastic_modulus: float | None = None
    ductility: float | None = None
    toughness: float | None = None
    work_of_separation: float | None = None
    adhesion_energy: float | None = None


class LayeredExperimentListResponse(BaseModel):
    """List of layered experiments."""

    model_config = ConfigDict(title="LayeredExperimentListResponse")

    total: int
    items: list[LayeredExperimentResponse]


class StressStrainResponse(BaseModel):
    """Stress-strain curve data from tensile test."""

    model_config = ConfigDict(title="StressStrainResponse")

    exp_id: str
    strain: list[float]
    stress_MPa: list[float]
    peak_index: int
    peak_strain: float
    peak_stress_MPa: float


class LayeredAnalysis3DPoint(BaseModel):
    """Single data point for 3D layered-structure analysis scatter."""

    model_config = ConfigDict(title="LayeredAnalysis3DPoint")

    exp_id: str
    name: str
    temperature_K: float | None = None
    layer_type: str | None = None
    layer_count: int = 0
    crystal_material: str | None = None
    crystal_surface: str | None = None
    binder_type: str | None = None
    aging_state: str | None = None
    binder_type_secondary: str | None = None
    aging_state_secondary: str | None = None
    additive_type: str | None = None
    additive_wt: float | None = None
    has_water: bool = False
    adhesion_energy: float | None = None
    tensile_strength: float | None = None
    elastic_modulus: float | None = None
    toughness: float | None = None
    work_of_separation: float | None = None
    ductility: float | None = None
    orientation_order: float | None = None
    e_inter_interface_1: float | None = None
    ghg_emission: float | None = None


class LayeredAnalysis3DResponse(BaseModel):
    """Aggregated layered experiment data for 3D analysis."""

    model_config = ConfigDict(title="LayeredAnalysis3DResponse")

    total: int
    matched_total: int | None = None
    returned_total: int | None = None
    available_layer_types: list[str] = Field(default_factory=list)
    available_crystal_materials: list[str] = Field(default_factory=list)
    available_aging_states: list[str] = Field(default_factory=list)
    available_binder_types: list[str] = Field(default_factory=list)
    temp_range: list[float] | None = None
    items: list[LayeredAnalysis3DPoint] = Field(default_factory=list)


# =============================================================================
# Amorphous Cell Library Models
# =============================================================================


class AmorphousCellComponentRequest(BaseModel):
    """Single component in amorphous cell request."""

    model_config = ConfigDict(title="AmorphousCellComponentRequest")

    mol_id: str = Field(..., min_length=1)
    weight_ratio: float = Field(..., gt=0)


class AmorphousCellCreateRequest(BaseModel):
    """Create amorphous cell request."""

    model_config = ConfigDict(title="AmorphousCellCreateRequest")

    name: str = Field(..., min_length=1, max_length=120)
    component_mol_id: str | None = Field(
        None,
        min_length=1,
        description="Single non-binder component mol_id",
    )
    components: list[AmorphousCellComponentRequest] | None = Field(
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
    temperature_K: float = Field(293.0, gt=0)
    seed: int | None = None
    # Non-binder 단순 분자(H2O, Toluene 등)용 기본값:
    # 바인더 screening(300/1000ps)보다 짧게 설정 — 단순 분자는 빠르게 평형 도달.
    minimize_steps: int = Field(1000, gt=0)
    nvt_ps: float = Field(100.0, gt=0)
    npt_ps: float = Field(500.0, gt=0)
    metadata: dict[str, Any] | None = Field(None)
    # High-temperature/high-pressure equilibration settings (optional)
    equilibration_settings: EquilibrationSettingsRequest | None = Field(
        None,
        description="Optional high-temperature/high-pressure equilibration settings "
        "for low-temperature simulations with kinetic trapping issues.",
    )

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


class BoxPresetResponse(BaseModel):
    """Box size preset entry derived from completed binder experiments."""

    model_config = ConfigDict(title="BoxPresetResponse")

    key: str
    label: str
    lx: float
    ly: float
    lz: float
    count: int = 0


class AmorphousCellResponse(BaseModel):
    """Amorphous cell response payload."""

    model_config = ConfigDict(title="AmorphousCellResponse")

    amorphous_id: str
    name: str
    status: str
    boundary_mode: str
    ff_type: str
    temperature_K: float
    atom_count: int
    density: float | None = None
    component_mol_id: str | None = None
    initial_density: float
    component_count: int
    components: list[AmorphousCellComponentRequest] = Field(default_factory=list)
    lx_angstrom: float
    ly_angstrom: float
    lz_angstrom: float
    stabilization_exp_id: str | None = None
    lammps_data_file_path: str | None = None
    log_file_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class AmorphousCellListResponse(BaseModel):
    """Amorphous cell list response."""

    model_config = ConfigDict(title="AmorphousCellListResponse")

    total: int
    items: list[AmorphousCellResponse]


class AmorphousCellPreviewResponse(BaseModel):
    """Amorphous cell preview payload for 3D viewer."""

    model_config = ConfigDict(title="AmorphousCellPreviewResponse")

    amorphous_id: str
    xyz: str
    box_size: tuple[float, float, float]
    n_atoms: int
    n_bonds: int
    bonds: list[list[int]]
    density: float | None = None
    boundary_mode: str
    type_map: dict[str, str] | None = None


# =============================================================================
# Layered Structure Composer Models (Single Job)
# =============================================================================


class CrystalBatchGenerateRequest(BaseModel):
    """Batch-generate all available supercell sizes for a material."""

    model_config = ConfigDict(title="CrystalBatchGenerateRequest")

    material: CrystalMaterial
    surface: SurfaceOrientation | None = Field(
        None,
        description="Surface orientation. None = auto-detect from crystal structure properties.",
    )
    thickness_angstrom: float = Field(25.0, gt=0)
    xy_min: float = Field(35.0, gt=0)
    xy_max: float = Field(60.0, gt=0)
    hydroxylated: bool = True
    hydroxyl_density: float = Field(4.6, gt=0)


class CrystalBatchGenerateResponse(BaseModel):
    """Batch-generate response."""

    model_config = ConfigDict(title="CrystalBatchGenerateResponse")

    material: str
    surface: str
    generated_count: int
    skipped_count: int
    sizes: list[CrystalStructureResponse]


class LayerStackItemRequest(BaseModel):
    """One layer source selected in layered-structure composer."""

    model_config = ConfigDict(title="LayerStackItemRequest")

    source_type: LayerSourceType
    source_id: str | None = Field(None, min_length=1)
    auto_match_material: str | None = Field(
        None,
        description="Material name for automatic crystal size matching. "
        "When set, source_id is resolved automatically from the catalog.",
    )
    label: str | None = Field(None, max_length=80)
    gap_after_angstrom: float | None = Field(
        None,
        ge=_LAYER_POLICY.gap_min_angstrom,
        le=_LAYER_POLICY.gap_max_angstrom,
        description="Per-layer gap override (Angstrom). None = use global default.",
    )

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_legacy_source_type(cls, v: str) -> str:
        """Normalize legacy 'amorphous_cell' to canonical value."""
        if isinstance(v, str) and v == "amorphous_cell":
            return "interface_molecule_cell"
        return v

    @field_validator("source_id", "auto_match_material")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_source_or_auto_match(self):
        if self.source_type == LayerSourceType.CRYSTAL_STRUCTURE:
            if bool(self.source_id) == bool(self.auto_match_material):
                raise ValueError(
                    "Crystal layers require exactly one of source_id or auto_match_material"
                )
            return self

        if self.auto_match_material:
            raise ValueError("auto_match_material is only supported for crystal_structure layers")
        if not self.source_id:
            raise ValueError("source_id is required for non-crystal layers")
        return self


class LayerSourceSummaryResponse(BaseModel):
    """Source summary row for layer composer."""

    model_config = ConfigDict(title="LayerSourceSummaryResponse")

    source_type: LayerSourceType
    source_id: str
    name: str
    status: str
    atom_count: int | None = None
    box_size: tuple[float, float, float] | None = None
    boundary_mode: str | None = None
    material: str | None = None


class LayerSourceListResponse(BaseModel):
    """List response for layer composer source catalog."""

    model_config = ConfigDict(title="LayerSourceListResponse")

    total: int
    items: list[LayerSourceSummaryResponse]


class LayeredStructureCheckResponse(BaseModel):
    """Validation/check result item for layer stack."""

    model_config = ConfigDict(title="LayeredStructureCheckResponse")

    code: str
    status: str  # pass | warn | fail
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class LayeredStructurePreviewRequest(BaseModel):
    """Preview request for user-defined 2-5 layer stack."""

    model_config = ConfigDict(title="LayeredStructurePreviewRequest")

    layers: list[LayerStackItemRequest] = Field(..., min_length=2, max_length=5)
    xy_tolerance_pct: float | None = Field(
        None,
        ge=_LAYER_POLICY.xy_tolerance_pct_min,
        le=_LAYER_POLICY.xy_tolerance_pct_max,
        description="XY mismatch tolerance (%). None = use default from policy.",
    )
    xy_tolerance_angstrom: float | None = Field(
        None,
        gt=0,
        description="Deprecated: use xy_tolerance_pct",
    )
    min_xy_to_z_ratio: float = Field(_LAYER_POLICY.min_xy_to_z_ratio_warn, gt=0)
    inter_layer_gap_angstrom: float = Field(
        _LAYER_POLICY.inter_layer_gap_angstrom,
        ge=_LAYER_POLICY.gap_min_angstrom,
        le=_LAYER_POLICY.gap_max_angstrom,
    )
    # v01.05.28 (P0-1): slab_vacuum_ratio 게이트가 실제 빌드 진공값을 보도록 노출.
    # None → 정책 기본값으로 해석(submit 요청과 동일 의미). 게이트와 빌더가 같은 값을 본다.
    z_vacuum_angstrom: float | None = Field(
        None,
        ge=_LAYER_POLICY.z_vacuum_min_angstrom,
        le=_LAYER_POLICY.z_vacuum_max_angstrom,
        description="Preview-time z vacuum (Angstrom) for the slab_vacuum_ratio gate. "
        "None = policy default. Must match the submit value.",
    )

    @model_validator(mode="after")
    def _resolve_xy_tolerance(self) -> Self:
        """Resolve XY tolerance: pct > angstrom > policy default."""
        if self.xy_tolerance_pct is not None:
            return self  # explicit % value → use as-is
        if self.xy_tolerance_angstrom is not None:
            return self  # backward compat: Å → % conversion deferred to service
        # both None → policy default
        self.xy_tolerance_pct = _LAYER_POLICY.xy_tolerance_pct
        return self


class LayeredStructurePreviewResponse(BaseModel):
    """Preview payload for layer stack 3D viewer."""

    model_config = ConfigDict(title="LayeredStructurePreviewResponse")

    xyz: str
    box_size: tuple[float, float, float]
    n_atoms: int
    n_bonds: int
    bonds: list[list[int]]
    layer_boundaries_z: list[float] = Field(default_factory=list)
    checks: list[LayeredStructureCheckResponse] = Field(default_factory=list)
    # v01.02.17: E_inter precision analysis recommendation
    e_inter_recommendation: EInterRecommendationResponse | None = Field(
        None, description="E_inter precision analysis recommendation for UI"
    )


class LayeredStructureSubmitRequest(BaseModel):
    """Submit request for single-job layered structure simulation."""

    model_config = ConfigDict(title="LayeredStructureSubmitRequest")

    name: str = Field("Layered Structure", min_length=1, max_length=120)
    layers: list[LayerStackItemRequest] = Field(..., min_length=2, max_length=5)
    run_tier: str = "screening"
    ff_type: str = "bulk_ff_gaff2"
    e_intra_method: str | None = Field(
        None,
        description="Optional E_intra method override for new jobs. Defaults to settings.json.",
    )
    boundary_mode: str = Field("ppf", pattern="^(ppp|ppf)$")
    temperature_K: float = Field(298.0, ge=200, le=500)
    pressure_atm: float = Field(1.0, gt=0)
    xy_tolerance_pct: float | None = Field(
        None,
        ge=_LAYER_POLICY.xy_tolerance_pct_min,
        le=_LAYER_POLICY.xy_tolerance_pct_max,
        description="XY mismatch tolerance (%). None = use default from policy.",
    )
    xy_tolerance_angstrom: float | None = Field(
        None,
        gt=0,
        description="Deprecated: use xy_tolerance_pct",
    )
    min_xy_to_z_ratio: float = Field(_LAYER_POLICY.min_xy_to_z_ratio_warn, gt=0)
    inter_layer_gap_angstrom: float = Field(
        _LAYER_POLICY.inter_layer_gap_angstrom,
        ge=_LAYER_POLICY.gap_min_angstrom,
        le=_LAYER_POLICY.gap_max_angstrom,
    )
    z_vacuum_angstrom: float | None = Field(
        None,
        ge=_LAYER_POLICY.z_vacuum_min_angstrom,
        le=_LAYER_POLICY.z_vacuum_max_angstrom,
        description="Submit-only z vacuum padding (Angstrom). None = use policy default.",
    )
    seed: int | None = None
    # 보완 #4 후속: 다중 seed replica 자동 오케스트레이션.
    # 2개 이상 지정 시 같은 계면 설정을 seed별로 N회 제출하고 한 replica group으로
    # 묶는다(완료 시 work_of_separation 등 계면 지표를 mean±SE ensemble로 자동 집계).
    # None/1개 → 단일 실험(기존과 동일, byte-identical).
    replicate_seeds: list[int] | None = Field(
        None,
        description=(
            "Optional seeds for replicate-ensemble runs. >=2 seeds submit the same "
            "interface as a replicate group; interface mechanical metrics are then "
            "auto-aggregated to mean ± SE on completion. None/1 = single experiment."
        ),
    )

    @model_validator(mode="after")
    def _resolve_xy_tolerance(self) -> Self:
        """Resolve XY tolerance: pct > angstrom > policy default."""
        if self.xy_tolerance_pct is not None:
            return self
        if self.xy_tolerance_angstrom is not None:
            return self
        self.xy_tolerance_pct = _LAYER_POLICY.xy_tolerance_pct
        return self

    @model_validator(mode="after")
    def _resolve_z_vacuum(self) -> Self:
        if self.z_vacuum_angstrom is None:
            self.z_vacuum_angstrom = _LAYER_POLICY.z_vacuum_angstrom
        return self

    @field_validator("e_intra_method")
    @classmethod
    def _validate_e_intra_method(cls, value: str | None) -> str | None:
        return validate_submission_e_intra_method(value)

    @model_validator(mode="after")
    def _validate_tensile_qs_params(self) -> Self:
        """Validate QS cross-field constraint at API boundary."""
        if self.tensile_enabled and self.tensile_mode == "quasi_static":
            fa = self.tensile_force_average_steps
            rs = self.tensile_relax_steps
            if fa is not None and rs is not None and fa > rs:
                raise ValueError(
                    f"tensile_force_average_steps ({fa}) must be "
                    f"<= tensile_relax_steps ({rs}) in quasi_static mode"
                )
        return self

    stage_durations: list[StageDurationOverrideRequest] | None = Field(
        None,
        description="Optional stage duration overrides.",
    )
    stage_requests: list[StageRequest] | None = Field(
        None,
        description="Optional stage requests for layer optional stages (high_temp_nvt, annealing_cycles only).",
    )

    @model_validator(mode="after")
    def _validate_stage_requests(self) -> Self:
        """Only allow disabling layered optional stages.

        Contract: stage_requests entries must have enabled=false, no duration/params overrides,
        and no duplicate stage keys. Other overrides go through stage_durations.
        """
        if not self.stage_requests:
            return self
        _LAYER_OPTIONAL = {"high_temp_nvt", "annealing_cycles"}
        seen: set[str] = set()
        for sr in self.stage_requests:
            if sr.stage_key not in _LAYER_OPTIONAL:
                raise ValueError(
                    f"Layered workflow only allows disabling optional stages: {_LAYER_OPTIONAL}, "
                    f"got '{sr.stage_key}'"
                )
            if sr.enabled:
                raise ValueError(
                    f"stage_requests only accepts enabled=false (use stage_durations for overrides), "
                    f"got enabled=true for '{sr.stage_key}'"
                )
            if sr.duration_ps is not None or sr.duration_steps is not None:
                raise ValueError(
                    f"Duration overrides must use stage_durations, not stage_requests, "
                    f"for '{sr.stage_key}'"
                )
            if sr.params_override:
                raise ValueError(
                    f"params_override not supported in layered stage_requests for '{sr.stage_key}'"
                )
            if sr.stage_key in seen:
                raise ValueError(f"Duplicate stage_key in stage_requests: '{sr.stage_key}'")
            seen.add(sr.stage_key)
        return self

    # Tensile test
    tensile_enabled: bool = Field(False, description="Enable direct tensile test")
    tensile_pull_velocity: float | None = Field(None, gt=0, description="Pull velocity (A/fs)")
    tensile_grip_thickness: float | None = Field(None, gt=0, description="Grip thickness (A)")
    tensile_max_strain: float | None = Field(None, gt=0, le=2.0, description="Max strain")
    # Quasi-static tensile parameters
    tensile_mode: str | None = Field(None, pattern="^(continuous|quasi_static)$")
    tensile_displacement_increment: float | None = Field(None, gt=0, le=2.0)
    tensile_relax_steps: int | None = Field(None, gt=0, le=100000)
    tensile_force_average_steps: int | None = Field(None, gt=0, le=50000)
    # E_inter 정밀 분석 설정 (v01.02.17)
    interaction_analysis: EInterComputeConfig | None = Field(
        None,
        description="E_inter 정밀 분석 설정. GPU 완료 후 CPU rerun으로 장거리 Coulomb 포함 E_inter 계산.",
    )


class LayeredStructureSubmitResponse(BaseModel):
    """Submit response for layered structure simulation."""

    model_config = ConfigDict(title="LayeredStructureSubmitResponse")

    exp_id: str
    job_id: str
    status: str
    checks: list[LayeredStructureCheckResponse] = Field(default_factory=list)
    # v01.02.17: E_inter precision analysis recommendation
    e_inter_recommendation: EInterRecommendationResponse | None = Field(
        None, description="E_inter precision analysis recommendation for UI"
    )
    # 보완 #4 후속: replica group (다중 seed ensemble)
    replicate_group_id: str | None = Field(
        None, description="Replicate group id when submitted as a multi-seed ensemble"
    )
    replicate_exp_ids: list[str] | None = Field(
        None, description="All experiment ids in the replicate group (primary first)"
    )
