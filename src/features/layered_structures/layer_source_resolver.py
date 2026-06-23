"""Layer source resolution logic for layered structure composer."""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path

from common.library_config import load_crystal_structures_config
from contracts.errors import ContractError, DatabaseError, ErrorCode
from contracts.schemas import CrystalLayerSpec, LayerSourceType
from features.common.workspace import resolve_workspace_path as _resolve_workspace_path
from parsers.data_parser import DataFileInfo, DataParser

logger = logging.getLogger(__name__)


@dataclass
class _ResolvedLayerSource:
    source_type: LayerSourceType
    source_id: str
    name: str
    status: str
    data_path: Path
    boundary_mode: str
    info: DataFileInfo
    type_map: dict[str, str]
    box_size: tuple[float, float, float]
    origin: str = "db"  # "yaml" | "db"
    interface_mol_id: str | None = None  # e.g. "H2O", "CO2"
    components_json: list | None = None  # legacy amorphous cell components
    is_water_like: bool = False


_DEFAULT_AUTO_MATCH_CRYSTAL = CrystalLayerSpec()
# Default cell_mode and hydroxylated come from CrystalLayerSpec;
# preferred surface is resolved dynamically per material via
# CrystalBuilder.preferred_surface().


def _crystal_row_box_size(
    row: dict,
) -> tuple[float, float, float]:
    """Extract (lx, ly, lz) from a crystal YAML row, preferring actual_lx/ly."""
    metadata = row.get("metadata") or {}
    lx = float(metadata.get("actual_lx_angstrom") or row.get("xy_size_angstrom", 0.0) or 0.0)
    ly = float(metadata.get("actual_ly_angstrom") or row.get("xy_size_angstrom", 0.0) or 0.0)
    lz = float(row.get("thickness_angstrom", 0.0) or 0.0)
    return (lx, ly, lz)


def _auto_select_crystal(
    material: str,
    target_lx: float,
    target_ly: float,
) -> str:
    """Select the crystal_id from YAML catalog that best matches target XY.

    Finds the crystal of the given material whose actual_lx/ly are closest
    to target_lx/ly, minimising ``max(|lx - target_lx|, |ly - target_ly|)``.

    Args:
        material: Crystal material name (e.g. "SiO2").
        target_lx: Target X dimension (Angstrom).
        target_ly: Target Y dimension (Angstrom).

    Returns:
        crystal_id of the best matching crystal.

    Raises:
        ContractError: If no ready crystals found for the material.
    """
    candidates = [
        c
        for c in load_crystal_structures_config().get("structures", [])
        if str(c.get("material", "")).upper() == material.upper()
        and str(c.get("status", "")) == "ready"
    ]
    if not candidates:
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"No ready crystal structures found for material: {material}",
            {"material": material},
        )

    # Resolve preferred surface dynamically from crystal structure properties
    from builder.crystal_builder import CrystalBuilder
    from builder.layer_spec import CrystalMaterial as _CM

    material_enum = None
    material_upper = material.upper()
    for m in _CM:
        if m.value.upper() == material_upper or m.name.upper() == material_upper:
            material_enum = m
            break
    preferred_surface = (
        CrystalBuilder.preferred_surface(material_enum).value
        if material_enum is not None
        else _DEFAULT_AUTO_MATCH_CRYSTAL.surface.value
    )
    preferred_cell_mode = _DEFAULT_AUTO_MATCH_CRYSTAL.cell_mode.value
    preferred_hydroxylated = _DEFAULT_AUTO_MATCH_CRYSTAL.hydroxylated

    preferred_candidates = [
        c
        for c in candidates
        if str(c.get("surface", preferred_surface)) == preferred_surface
        and str(c.get("cell_mode", preferred_cell_mode)) == preferred_cell_mode
        and bool(c.get("hydroxylated", preferred_hydroxylated)) == preferred_hydroxylated
    ]
    if preferred_candidates:
        candidates = preferred_candidates
    else:
        variant_keys = {
            (
                str(c.get("surface", "")),
                str(c.get("cell_mode", "")),
                bool(c.get("hydroxylated", False)),
            )
            for c in candidates
        }
        if len(variant_keys) > 1:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Auto-match is ambiguous for this material; select a crystal manually",
                {
                    "material": material,
                    "available_variants": sorted(variant_keys),
                    "expected_variant": {
                        "surface": preferred_surface,
                        "cell_mode": preferred_cell_mode,
                        "hydroxylated": preferred_hydroxylated,
                    },
                },
            )

    def _mismatch(c: dict) -> float:
        lx, ly, _ = _crystal_row_box_size(c)
        return max(abs(lx - target_lx), abs(ly - target_ly))

    best = min(candidates, key=_mismatch)
    return str(best["crystal_id"])


def _pick_data_file(path_value: str | None) -> Path:
    if not path_value:
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            "Layer source does not have a data file path",
        )

    resolved = _resolve_workspace_path(path_value)
    candidates: list[Path] = []
    if resolved.is_dir():
        candidates.extend(
            [
                resolved / "final.data",
                resolved / "data.lammps",
                resolved / "layer_system.data",
            ]
        )
    else:
        candidates.append(resolved)
        candidates.append(resolved.parent / "final.data")
        candidates.append(resolved.parent / "data.lammps")

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise ContractError(
        ErrorCode.STRUCTURE_NOT_FOUND,
        f"Layer source data file not found: {resolved}",
        {"path": str(resolved)},
    )


def _load_layer_sources(
    layer_items: list,
) -> list[_ResolvedLayerSource]:
    from features.common import run_in_session

    parser = DataParser()
    crystal_by_id = {
        str(item.get("crystal_id", "")).strip(): item
        for item in load_crystal_structures_config().get("structures", [])
    }

    def _load(session):
        from database.repositories.experiment_repo import ExperimentRepository

        experiment_repo = ExperimentRepository(session)
        raw_sources: list[tuple] = []
        for item in layer_items:
            if (
                item.source_type != LayerSourceType.CRYSTAL_STRUCTURE
                and item.auto_match_material is not None
            ):
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    "auto_match_material is only supported for crystal_structure layers",
                    {"source_type": item.source_type.value},
                )
            if item.source_type == LayerSourceType.BINDER_CELL:
                exp = experiment_repo.get_by_id(item.source_id)
                if exp is None:
                    raise DatabaseError(
                        ErrorCode.RECORD_NOT_FOUND,
                        f"Binder cell not found: {item.source_id}",
                        {"source_type": item.source_type.value, "source_id": item.source_id},
                    )
                raw_sources.append(
                    (
                        item,
                        exp.exp_id,
                        exp.exp_id,
                        str(exp.status or "unknown"),
                        str(exp.data_file_path or ""),
                    )
                )
            elif item.source_type == LayerSourceType.INTERFACE_MOLECULE_CELL:
                from features.common.interface_sources import resolve_interface_source

                cell = resolve_interface_source(item.source_id, session=session)
                if cell is None:
                    raise DatabaseError(
                        ErrorCode.RECORD_NOT_FOUND,
                        f"Interface molecule cell not found: {item.source_id}",
                        {"source_type": item.source_type.value, "source_id": item.source_id},
                    )
                raw_sources.append(
                    (
                        item,
                        cell["source_id"],
                        cell.get("name", cell["source_id"]),
                        str(cell.get("status", "unknown")),
                        str(cell.get("lammps_data_file_path", "")),
                    )
                )
            else:
                # Auto-match: resolve crystal_id from material + adjacent XY
                resolved_source_id = item.source_id
                if not resolved_source_id and item.auto_match_material:
                    # Defer resolution — store placeholder to resolve after DB pass
                    raw_sources.append((item, "__auto_match__", "", "pending", ""))
                    continue

                row = crystal_by_id.get(resolved_source_id)
                if row is None:
                    raise DatabaseError(
                        ErrorCode.RECORD_NOT_FOUND,
                        f"Crystal structure not found in crystal_structures.yaml: {resolved_source_id}",
                        {"source_type": item.source_type.value, "source_id": resolved_source_id},
                    )
                raw_sources.append(
                    (
                        item,
                        str(row.get("crystal_id", "")),
                        str(row.get("name", row.get("crystal_id", ""))),
                        str(row.get("status", "unknown")),
                        str(row.get("lammps_data_file_path", "") or ""),
                    )
                )
        return raw_sources

    raw_sources = run_in_session(_load)

    # First pass: resolve non-auto-match sources to get their box sizes
    resolved: list[_ResolvedLayerSource] = []
    deferred_auto: list[tuple[int, object]] = []
    for _idx, (item, source_id, name, status, data_file_path) in enumerate(raw_sources):
        if source_id == "__auto_match__":
            deferred_auto.append((len(resolved), item))
            resolved.append(None)  # type: ignore[arg-type]  # placeholder
            continue
        data_path = _pick_data_file(data_file_path)
        info = parser.parse(data_path)
        type_map = parser.estimate_elements_from_info(info)
        xlo, xhi, ylo, yhi, zlo, zhi = info.box_bounds
        box_size = (xhi - xlo, yhi - ylo, zhi - zlo)
        boundary_mode = "ppf"
        resolved.append(
            _ResolvedLayerSource(
                source_type=item.source_type,
                source_id=source_id,
                name=name,
                status=status,
                data_path=data_path,
                boundary_mode=boundary_mode,
                info=info,
                type_map=type_map,
                box_size=box_size,
            )
        )
        # Enrich interface molecule cell metadata
        if item.source_type == LayerSourceType.INTERFACE_MOLECULE_CELL:
            from features.common.interface_sources import resolve_interface_source

            cell_info = resolve_interface_source(source_id)
            if cell_info:
                resolved[-1] = dataclasses.replace(
                    resolved[-1],
                    origin=cell_info.get("origin", "db"),
                    interface_mol_id=cell_info.get("mol_id"),
                    components_json=cell_info.get("components_json"),
                    is_water_like=cell_info.get("is_water_like", False),
                )

    # Second pass: resolve auto-match crystal layers using adjacent layer XY
    for slot_idx, item in deferred_auto:
        # Find reference XY from nearest resolved neighbor
        ref_lx, ref_ly = 40.0, 40.0
        for offset in (1, -1, 2, -2):
            neighbor_idx = slot_idx + offset
            if 0 <= neighbor_idx < len(resolved) and resolved[neighbor_idx] is not None:
                ref_lx, ref_ly = (
                    resolved[neighbor_idx].box_size[0],
                    resolved[neighbor_idx].box_size[1],
                )
                break

        crystal_id = _auto_select_crystal(
            item.auto_match_material,
            ref_lx,
            ref_ly,  # type: ignore[arg-type]
        )
        row = crystal_by_id.get(crystal_id)
        if row is None:
            raise DatabaseError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Auto-matched crystal not found: {crystal_id}",
                {"crystal_id": crystal_id, "material": item.auto_match_material},
            )
        data_path = _pick_data_file(str(row.get("lammps_data_file_path", "") or ""))
        info = parser.parse(data_path)
        type_map = parser.estimate_elements_from_info(info)
        xlo, xhi, ylo, yhi, zlo, zhi = info.box_bounds
        box_size = (xhi - xlo, yhi - ylo, zhi - zlo)
        resolved[slot_idx] = _ResolvedLayerSource(
            source_type=item.source_type,
            source_id=crystal_id,
            name=str(row.get("name", crystal_id)),
            status=str(row.get("status", "ready")),
            data_path=data_path,
            boundary_mode="ppf",
            info=info,
            type_map=type_map,
            box_size=box_size,
        )

    return resolved
