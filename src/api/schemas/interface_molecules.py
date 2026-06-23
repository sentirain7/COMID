"""Interface molecule cell schemas for layered structure interface layers."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.schemas import AmorphousBoundaryMode

# =============================================================================
# Interface Molecule Cell Library Models
# =============================================================================


class InterfaceMoleculeCellCreateRequest(BaseModel):
    """Create interface molecule cell request (no MD simulation)."""

    model_config = ConfigDict(title="InterfaceMoleculeCellCreateRequest")

    name: str = Field(..., min_length=1, max_length=120)
    mol_id: str = Field(..., min_length=1, description="Single molecule mol_id (e.g., CO2, NaCl)")
    lx_angstrom: float = Field(40.0, gt=0)
    ly_angstrom: float = Field(40.0, gt=0)
    lz_angstrom: float = Field(10.0, gt=0)
    target_density: float = Field(0.5, gt=0, description="Target density (g/cm3)")
    boundary_mode: AmorphousBoundaryMode = Field(default=AmorphousBoundaryMode.PPF)
    seed: int | None = None
    metadata: dict[str, Any] | None = Field(None)


class InterfaceMoleculeCellResponse(BaseModel):
    """Interface molecule cell response payload."""

    model_config = ConfigDict(title="InterfaceMoleculeCellResponse")

    cell_id: str
    name: str
    status: str
    mol_id: str
    mol_name: str | None = None
    formula: str | None = None
    atom_count: int
    molecule_count: int
    target_density: float
    actual_density: float | None = None
    boundary_mode: str
    lx_angstrom: float
    ly_angstrom: float
    lz_angstrom: float
    lammps_data_file_path: str | None = None
    xyz_file_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class InterfaceMoleculeCellListResponse(BaseModel):
    """Interface molecule cell list response."""

    model_config = ConfigDict(title="InterfaceMoleculeCellListResponse")

    total: int
    items: list[InterfaceMoleculeCellResponse]


class InterfaceMoleculeCellPreviewResponse(BaseModel):
    """Interface molecule cell preview payload for 3D viewer."""

    model_config = ConfigDict(title="InterfaceMoleculeCellPreviewResponse")

    cell_id: str
    xyz: str
    box_size: tuple[float, float, float]
    n_atoms: int
    n_bonds: int
    bonds: list[list[int]]
    density: float | None = None
    boundary_mode: str
    type_map: dict[str, str] | None = None


class InterfaceMoleculeInfo(BaseModel):
    """Single interface molecule information."""

    model_config = ConfigDict(title="InterfaceMoleculeInfo")

    mol_id: str
    name: str
    category: str
    formula: str
    atom_count: int
    molecular_weight: float
    elements: list[str]
    recommended_density: float | None = None
    mol_size_angstrom: tuple[float, float, float] | None = None
    max_extent_angstrom: float | None = None
    generation_supported: bool = True
    generation_reason: str | None = None


class InterfaceMoleculeListResponse(BaseModel):
    """Available interface molecules list."""

    model_config = ConfigDict(title="InterfaceMoleculeListResponse")

    total: int
    categories: list[str]
    items: list[InterfaceMoleculeInfo]


class InterfaceMoleculePreviewResponse(BaseModel):
    """Single molecule preview for 3D viewer."""

    model_config = ConfigDict(title="InterfaceMoleculePreviewResponse")

    mol_id: str
    name: str
    xyz: str
    atom_count: int
    n_bonds: int
    bonds: list[list[int]]
    molecular_weight: float
    elements: list[str]
    mol_size_angstrom: tuple[float, float, float] | None = None
    max_extent_angstrom: float | None = None


# =============================================================================
# Batch Generation Models
# =============================================================================


class InterfaceMoleculeBatchGenerateRequest(BaseModel):
    """Batch-generate interface molecule cells in [xy_min, xy_max] range."""

    model_config = ConfigDict(title="InterfaceMoleculeBatchGenerateRequest")

    mol_id: str = Field(..., min_length=1)
    xy_min: float = Field(35.0, gt=0, description="Minimum XY size (Angstrom)")
    xy_max: float = Field(60.0, gt=0, description="Maximum XY size (Angstrom)")
    lz_angstrom: float = Field(10.0, gt=0)
    target_density: float = Field(..., gt=0, description="Required: target density (g/cm3)")
    boundary_mode: AmorphousBoundaryMode = Field(default=AmorphousBoundaryMode.PPF)

    @model_validator(mode="after")
    def validate_xy_range(self) -> Self:
        """Ensure xy_max >= xy_min."""
        if self.xy_max < self.xy_min:
            raise ValueError(f"xy_max ({self.xy_max}) must be >= xy_min ({self.xy_min})")
        return self


class BatchFailureItem(BaseModel):
    """Single batch generation failure."""

    model_config = ConfigDict(title="BatchFailureItem")

    lx_angstrom: float
    ly_angstrom: float
    lz_angstrom: float
    error_code: str
    message: str


class InterfaceMoleculeBatchGenerateResponse(BaseModel):
    """Batch-generate response."""

    model_config = ConfigDict(title="InterfaceMoleculeBatchGenerateResponse")

    mol_id: str
    mol_name: str
    generated_count: int
    skipped_count: int
    failed_count: int = 0
    failures: list[BatchFailureItem] = Field(default_factory=list)
    cells: list[InterfaceMoleculeCellResponse]
