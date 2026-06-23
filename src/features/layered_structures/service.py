"""Layered structure composer service (single-job)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from api.schemas import (
    LayeredStructureCheckResponse,
    LayeredStructurePreviewRequest,
    LayeredStructurePreviewResponse,
    LayeredStructureSubmitRequest,
    LayeredStructureSubmitResponse,
    LayerSourceListResponse,
    LayerSourceSummaryResponse,
)
from common.constants import ATOMIC_WEIGHTS
from common.library_config import load_crystal_structures_config
from common.pathing import get_experiment_path
from common.seed import generate_seed
from contracts.errors import ContractError, ErrorCode
from contracts.policies.layer import DEFAULT_LAYER_POLICY as _LAYER_POLICY
from contracts.schemas import LayerSourceType, StudyType, SubmissionSource
from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS

# UFF_ELEMENT_FALLBACKS import removed (fail-closed policy v00.99.29)
# ── Re-exports from extracted modules ──
# These are imported here so that existing callers can continue to
# ``from features.layered_structures.service import <name>``.
from .layer_source_resolver import _auto_select_crystal as _auto_select_crystal  # noqa: F401
from .layer_source_resolver import _crystal_row_box_size as _crystal_row_box_size  # noqa: F401
from .layer_source_resolver import _load_layer_sources, _ResolvedLayerSource
from .layered_analysis import _LAYER_TYPE_MAP as _LAYER_TYPE_MAP  # noqa: F401
from .layered_analysis import _has_water_layer as _has_water_layer  # noqa: F401
from .layered_analysis import _infer_layer_type as _infer_layer_type  # noqa: F401
from .layered_analysis import get_layered_analysis_3d as get_layered_analysis_3d  # noqa: F401
from .layered_analysis import list_layered_experiments as list_layered_experiments  # noqa: F401

logger = logging.getLogger(__name__)


@dataclass
class _CombinedAtom:
    element: str
    charge: float
    x: float
    y: float
    z: float
    layer_index: int
    original_atom_type: int = 0
    original_mol_id: int = 0


@dataclass
class _CombinedGeometry:
    atoms: list[_CombinedAtom]
    bonds: list[list[int]]
    box_size: tuple[float, float, float]
    layer_boundaries_z: list[float]
    xyz: str


def _collect_layered_ced_provenance(
    sources: list[_ResolvedLayerSource],
) -> tuple[dict[str, float], bool, dict[str, int], list[dict[str, object]]]:
    """Collect layered CED provenance from binder-cell source experiments."""
    comp = {"asphaltene": 0.0, "resin": 0.0, "aromatic": 0.0, "saturate": 0.0}
    no_binder_source = True
    total_mol_counts: dict[str, int] = {}
    source_records: list[dict[str, object]] = []

    try:
        from database.connection import session_scope
        from database.repositories import ExperimentRepository

        with session_scope() as session:
            repo = ExperimentRepository(session)
            for layer_index, src in enumerate(sources):
                if src.source_type != LayerSourceType.BINDER_CELL or not src.source_id:
                    continue

                binder_exp = repo.get_by_id(src.source_id)
                if binder_exp is None:
                    continue

                if no_binder_source:
                    comp = {
                        "asphaltene": binder_exp.comp_asphaltene_wt or 0.0,
                        "resin": binder_exp.comp_resin_wt or 0.0,
                        "aromatic": binder_exp.comp_aromatic_wt or 0.0,
                        "saturate": binder_exp.comp_saturate_wt or 0.0,
                    }
                    no_binder_source = False

                molecule_instances = 0
                molecule_types = 0
                layer_mol_counts: dict[str, int] = {}
                for exp_mol, molecule in repo.get_experiment_molecules(src.source_id):
                    count = int(getattr(exp_mol, "count", 0) or 0)
                    mol_id = str(getattr(molecule, "mol_id", "") or "").strip()
                    if count <= 0 or not mol_id:
                        continue
                    total_mol_counts[mol_id] = total_mol_counts.get(mol_id, 0) + count
                    layer_mol_counts[mol_id] = layer_mol_counts.get(mol_id, 0) + count
                    molecule_instances += count
                    molecule_types += 1

                source_records.append(
                    {
                        "source_exp_id": src.source_id,
                        "layer_index": layer_index,
                        "molecule_types": molecule_types,
                        "molecule_instances": molecule_instances,
                        "mol_counts": layer_mol_counts,
                    }
                )
    except Exception as exc:
        logger.warning("Layered CED provenance collection failed: %s", exc)

    return comp, no_binder_source, total_mol_counts, source_records


def _build_layered_profile_provenance(
    request: LayeredStructureSubmitRequest,
    preview: LayeredStructurePreviewResponse,
    source_records: list[dict[str, object]],
) -> tuple[list[str], dict[str, float], dict[str, dict[str, int]]]:
    """Build canonical layer labels, volumes, and binder-backed mol-counts.

    The profile is intentionally restricted to layers whose source provenance
    can provide molecule counts (currently binder-cell-backed layers). Crystal
    and water/interface layers remain visible in ``layer_labels`` and
    ``layer_volumes_A3`` but may be omitted from ``mol_counts_by_layer``.
    """
    layer_labels: list[str] = []
    layer_volumes_A3: dict[str, float] = {}
    mol_counts_by_layer: dict[str, dict[str, int]] = {}

    boundaries = list(getattr(preview, "layer_boundaries_z", None) or [])
    lx, ly, _ = preview.box_size
    records_by_index = {
        int(rec.get("layer_index", -1)): rec for rec in source_records if "layer_index" in rec
    }

    for idx, layer in enumerate(request.layers):
        layer_label = str(layer.label or f"layer_{idx}")
        layer_labels.append(layer_label)
        if len(boundaries) >= idx + 2:
            thickness = float(boundaries[idx + 1]) - float(boundaries[idx])
            if thickness > 0.0:
                layer_volumes_A3[layer_label] = float(lx) * float(ly) * thickness
        rec = records_by_index.get(idx)
        raw_counts = rec.get("mol_counts") if isinstance(rec, dict) else None
        if isinstance(raw_counts, dict):
            clean_counts = {
                str(mol_id): int(count)
                for mol_id, count in raw_counts.items()
                if str(mol_id).strip() and int(count) > 0
            }
            if clean_counts:
                mol_counts_by_layer[layer_label] = clean_counts

    return layer_labels, layer_volumes_A3, mol_counts_by_layer


def _crystal_additive_label(
    material: str,
    surface: str | None = None,
    hydroxylated: bool | None = None,
) -> str:
    """Build compact crystal descriptor for exp_id additive slot.

    Format: {material}[-{surface}][-OH]
    Examples: SiO2-001-OH, CaCO3-001, Al2O3-110

    Uses '-' as internal separator (no '_') to remain
    compatible with parse_exp_id which splits on '_'.
    """
    parts = [material]
    if surface:
        parts.append(surface)
    if hydroxylated:
        parts.append("OH")
    return "-".join(parts)


def _compute_crystal_grip_ranges(
    sources: list[_ResolvedLayerSource],
    shifted_boundaries: list[float],
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Compute z-ranges of outermost crystal layers for grip regions.

    Args:
        sources: Resolved layer sources (in stacking order).
        shifted_boundaries: Vacuum-shifted layer boundaries [z0, z1, z2, ...].
            Layer i spans (shifted_boundaries[2*i], shifted_boundaries[2*i+1]).

    Returns:
        (bottom_grip_z_range, top_grip_z_range) — None if that side is not crystal.
    """
    bottom: tuple[float, float] | None = None
    top: tuple[float, float] | None = None
    if sources[0].source_type == LayerSourceType.CRYSTAL_STRUCTURE:
        bottom = (shifted_boundaries[0], shifted_boundaries[1])
    if len(sources) > 1 and sources[-1].source_type == LayerSourceType.CRYSTAL_STRUCTURE:
        last_idx = len(sources) - 1
        top = (shifted_boundaries[2 * last_idx], shifted_boundaries[2 * last_idx + 1])
    return bottom, top


def _resolve_tolerance_pct(
    request: LayeredStructurePreviewRequest | LayeredStructureSubmitRequest,
    sources: list[_ResolvedLayerSource],
) -> float:
    """Resolve final XY tolerance in % from request fields.

    Priority: xy_tolerance_pct > xy_tolerance_angstrom (backward compat) > policy default.
    """
    if request.xy_tolerance_pct is not None:
        return request.xy_tolerance_pct
    if request.xy_tolerance_angstrom is not None:
        base_lx, base_ly, _ = sources[0].box_size
        ref_avg = (base_lx + base_ly) / 2.0
        if ref_avg > 0:
            return request.xy_tolerance_angstrom / ref_avg * 100.0
        return _LAYER_POLICY.xy_tolerance_pct
    return _LAYER_POLICY.xy_tolerance_pct


def _validate_checks(
    sources: list[_ResolvedLayerSource],
    *,
    xy_tolerance_pct: float,
    min_xy_to_z_ratio: float,
    z_vacuum_angstrom: float = _LAYER_POLICY.z_vacuum_angstrom,
) -> list[LayeredStructureCheckResponse]:
    checks: list[LayeredStructureCheckResponse] = []

    checks.append(
        LayeredStructureCheckResponse(
            code="layer_count",
            status="pass" if 2 <= len(sources) <= 5 else "fail",
            message=f"Layer count {len(sources)} (allowed: 2-5)",
            details={"count": len(sources)},
        )
    )

    base_lx, base_ly, _ = sources[0].box_size
    ref_avg = (base_lx + base_ly) / 2.0
    max_mismatch_pct = 0.0
    for source in sources[1:]:
        lx, ly, _ = source.box_size
        dx_pct = abs(base_lx - lx) / ref_avg * 100.0 if ref_avg > 0 else 0.0
        dy_pct = abs(base_ly - ly) / ref_avg * 100.0 if ref_avg > 0 else 0.0
        max_mismatch_pct = max(max_mismatch_pct, dx_pct, dy_pct)
    xy_ok = max_mismatch_pct <= xy_tolerance_pct
    checks.append(
        LayeredStructureCheckResponse(
            code="xy_alignment",
            status="pass" if xy_ok else "fail",
            message=(
                "XY sizes aligned"
                if xy_ok
                else "XY size mismatch exceeds tolerance; adjust layer source sizes"
            ),
            details={
                "base_xy": [round(base_lx, 4), round(base_ly, 4)],
                "max_mismatch_pct": round(max_mismatch_pct, 4),
                "tolerance_pct": round(xy_tolerance_pct, 4),
            },
        )
    )

    # Affine-rescale safety: non-crystal layers will be rescaled to match
    # the bottom (first) crystal XY.  Warn/fail if scale factor is too large.
    crystal_srcs = [s for s in sources if s.source_type == LayerSourceType.CRYSTAL_STRUCTURE]
    if crystal_srcs:
        ref_lx = crystal_srcs[0].box_size[0]
        ref_ly = crystal_srcs[0].box_size[1]
    else:
        ref_lx = max(s.box_size[0] for s in sources)
        ref_ly = max(s.box_size[1] for s in sources)

    max_rescale_pct = 0.0
    rescale_details: list[dict] = []
    for idx, source in enumerate(sources):
        if source.source_type == LayerSourceType.CRYSTAL_STRUCTURE:
            continue
        slx, sly, _ = source.box_size
        sx = ref_lx / slx if slx > 1e-6 else 1.0
        sy = ref_ly / sly if sly > 1e-6 else 1.0
        pct_x = abs(1.0 - sx) * 100.0
        pct_y = abs(1.0 - sy) * 100.0
        layer_max = max(pct_x, pct_y)
        max_rescale_pct = max(max_rescale_pct, layer_max)
        if layer_max > 1e-3:
            rescale_details.append(
                {"layer": idx + 1, "scale_x": round(sx, 6), "scale_y": round(sy, 6)}
            )

    warn_pct = _LAYER_POLICY.rescale_warn_pct
    hard_pct = _LAYER_POLICY.rescale_max_pct
    if max_rescale_pct > hard_pct:
        rescale_status = "fail"
        rescale_msg = f"Affine rescale {max_rescale_pct:.2f}% exceeds hard limit {hard_pct}%"
    elif max_rescale_pct > warn_pct:
        rescale_status = "warn"
        rescale_msg = f"Affine rescale {max_rescale_pct:.2f}% exceeds soft limit {warn_pct}%"
    elif max_rescale_pct > 1e-3:
        rescale_status = "pass"
        rescale_msg = f"Affine rescale {max_rescale_pct:.2f}% within safe bounds"
    else:
        rescale_status = "pass"
        rescale_msg = "No affine rescaling needed (XY dimensions match)"
    checks.append(
        LayeredStructureCheckResponse(
            code="affine_rescale",
            status=rescale_status,
            message=rescale_msg,
            details={
                "max_rescale_pct": round(max_rescale_pct, 4),
                "warn_pct": warn_pct,
                "hard_limit_pct": hard_pct,
                "per_layer": rescale_details,
            },
        )
    )

    z_sizes = [source.box_size[2] for source in sources]
    positive_z = all(z > 0 for z in z_sizes)
    checks.append(
        LayeredStructureCheckResponse(
            code="z_thickness",
            status="pass" if positive_z else "fail",
            message="All layer thickness values are positive"
            if positive_z
            else "Invalid zero/negative layer thickness",
            details={"z_sizes": [round(z, 4) for z in z_sizes]},
        )
    )

    boundary_modes = sorted({source.boundary_mode for source in sources})
    boundary_status = "pass" if len(boundary_modes) == 1 else "warn"
    checks.append(
        LayeredStructureCheckResponse(
            code="boundary_mode",
            status=boundary_status,
            message=(
                f"Boundary mode is consistent ({boundary_modes[0]})"
                if boundary_status == "pass"
                else f"Mixed boundary modes detected: {', '.join(boundary_modes)}"
            ),
            details={"boundary_modes": boundary_modes},
        )
    )

    # ── Slab geometry adequacy gate (보완 #5) ──
    # XY/Z 종횡비: hard 하한 미만은 빌드 거부(fail), warn 하한 미만은 경고.
    total_z = sum(z_sizes)
    xy_ratio = min(base_lx, base_ly) / total_z if total_z > 0 else 0.0
    hard_ratio = _LAYER_POLICY.min_xy_to_z_ratio_hard
    if total_z <= 0 or xy_ratio < hard_ratio:
        ratio_status = "fail"
        ratio_msg = (
            f"XY/Z ratio {xy_ratio:.3f} below hard minimum {hard_ratio} — "
            "slab too tall for periodic XY; increase XY size or reduce stacked Z"
        )
    elif xy_ratio < min_xy_to_z_ratio:
        ratio_status = "warn"
        ratio_msg = "XY/Z ratio is low; increase XY size or reduce stacked Z thickness"
    else:
        ratio_status = "pass"
        ratio_msg = "Layer aspect ratio is appropriate"
    checks.append(
        LayeredStructureCheckResponse(
            code="aspect_ratio",
            status=ratio_status,
            message=ratio_msg,
            details={
                "xy_to_z_ratio": round(xy_ratio, 4),
                "required_min_ratio": min_xy_to_z_ratio,
                "hard_min_ratio": hard_ratio,
            },
        )
    )

    # 진공/슬랩두께 비율: kspace_modify slab(EW3DC)이 유효하려면 z 진공이 슬랩
    # 두께 대비 충분해야 한다. total_vacuum = 2×z_vacuum.
    total_vacuum = 2.0 * z_vacuum_angstrom
    vac_ratio = total_vacuum / total_z if total_z > 0 else 0.0
    vac_warn = _LAYER_POLICY.min_vacuum_to_slab_ratio_warn
    vac_hard = _LAYER_POLICY.min_vacuum_to_slab_ratio_hard
    if total_z > 0 and vac_ratio < vac_hard:
        vac_status = "fail"
        vac_msg = (
            f"Vacuum/slab ratio {vac_ratio:.3f} below hard minimum {vac_hard} — "
            "insufficient free-surface/deformation space for the p p f slab; increase z-vacuum"
        )
    elif total_z > 0 and vac_ratio < vac_warn:
        vac_status = "warn"
        vac_msg = (
            f"Vacuum/slab ratio {vac_ratio:.3f} below recommended {vac_warn}; "
            "consider increasing z-vacuum for free-surface relaxation/tensile headroom"
        )
    else:
        vac_status = "pass"
        vac_msg = "Vacuum/slab thickness ratio is adequate for the p p f slab"
    checks.append(
        LayeredStructureCheckResponse(
            code="slab_vacuum_ratio",
            status=vac_status,
            message=vac_msg,
            details={
                "vacuum_to_slab_ratio": round(vac_ratio, 4),
                "total_vacuum_angstrom": round(total_vacuum, 4),
                "slab_thickness_angstrom": round(total_z, 4),
                "recommended_min_ratio": vac_warn,
                "hard_min_ratio": vac_hard,
            },
        )
    )

    flipped_crystal_layers = [
        idx + 1 for idx, source in enumerate(sources) if _should_flip_crystal_layer(sources, idx)
    ]
    checks.append(
        LayeredStructureCheckResponse(
            code="crystal_interface_orientation",
            status="pass",
            message=(
                "Crystal layers follow stack direction; non-bottom crystals are flipped so their"
                " prepared face points toward the lower interface"
                if flipped_crystal_layers
                else "Crystal layer orientation is consistent with bottom-up stacking"
            ),
            details={"flipped_layer_indices": flipped_crystal_layers},
        )
    )

    interior_crystal_layers = [
        idx + 1
        for idx, source in enumerate(sources)
        if source.source_type == LayerSourceType.CRYSTAL_STRUCTURE and 0 < idx < len(sources) - 1
    ]
    checks.append(
        LayeredStructureCheckResponse(
            code="crystal_dual_interface_limit",
            status="warn" if interior_crystal_layers else "pass",
            message=(
                "Interior crystal layers only expose one prepared face after orientation handling;"
                " the upper interface uses the raw backside"
                if interior_crystal_layers
                else "No interior crystal layer requires two opposing prepared interfaces"
            ),
            details={"interior_crystal_layer_indices": interior_crystal_layers},
        )
    )

    # FF compatibility checks for layer sources
    try:
        from forcefield.eligibility import collect_layered_ff_checks

        # Build layer dicts with resolver metadata for FF checks
        # The resolver enriches _ResolvedLayerSource with interface_mol_id and
        # components_json which eligibility needs for interface_molecule_cell FF lookup
        layer_dicts = []
        for s in sources:
            src_type = getattr(s.source_type, "value", str(s.source_type)) if s.source_type else ""
            layer_dict = {
                "source_type": src_type,
                "source_id": getattr(s, "source_id", ""),
            }
            # Pass resolver metadata for interface_molecule_cell FF checks
            if hasattr(s, "interface_mol_id") and s.interface_mol_id:
                layer_dict["interface_mol_id"] = s.interface_mol_id
            if hasattr(s, "components_json") and s.components_json:
                layer_dict["components_json"] = s.components_json
            # Pass is_water_like for water model FF compatibility
            if hasattr(s, "is_water_like") and s.is_water_like:
                layer_dict["is_water_like"] = s.is_water_like
            layer_dicts.append(layer_dict)

        ff_checks = collect_layered_ff_checks(layer_dicts)
        for fc in ff_checks:
            checks.append(
                LayeredStructureCheckResponse(
                    code=fc["code"],
                    status=fc["status"],
                    message=fc["message"],
                    details=fc.get("details"),
                )
            )
    except Exception as exc:
        logger.warning("FF eligibility check failed: %s", exc)

    return checks


def _should_flip_crystal_layer(sources: list[_ResolvedLayerSource], layer_idx: int) -> bool:
    """Flip non-bottom crystal layers so the prepared surface faces the lower interface."""
    return sources[layer_idx].source_type == LayerSourceType.CRYSTAL_STRUCTURE and layer_idx > 0


def _layer_local_z(atom_z: float, zlo: float, zhi: float, *, flip_z: bool) -> float:
    """Return layer-local z coordinate, optionally mirrored across the slab thickness."""
    local_z = (zhi - atom_z) if flip_z else (atom_z - zlo)
    thickness = zhi - zlo
    if local_z < 0.0:
        return 0.0
    if local_z > thickness:
        return thickness
    return local_z


def _combine_sources_to_geometry(
    sources: list[_ResolvedLayerSource],
    inter_layer_gap: float = _LAYER_POLICY.inter_layer_gap_angstrom,
    per_layer_gaps: list[float | None] | None = None,
) -> _CombinedGeometry:
    # Reference XY: the bottom (first) crystal layer defines the periodic box.
    # Lattice constants are inviolable — all non-crystal layers are affine-
    # rescaled to fill the bottom crystal XY exactly, eliminating PBC vacuum
    # strips.  When no crystal exists (e.g. binder-binder), use max of all.
    crystal_sources = [s for s in sources if s.source_type == LayerSourceType.CRYSTAL_STRUCTURE]
    if crystal_sources:
        # Bottom crystal = substrate; defines the simulation periodic box.
        global_lx = crystal_sources[0].box_size[0]
        global_ly = crystal_sources[0].box_size[1]
    else:
        global_lx = max(s.box_size[0] for s in sources)
        global_ly = max(s.box_size[1] for s in sources)

    z_cursor = 0.0
    atoms: list[_CombinedAtom] = []
    bonds: list[list[int]] = []
    boundaries: list[float] = []

    for layer_idx, source in enumerate(sources):
        xlo, xhi, ylo, yhi, zlo, zhi = source.info.box_bounds
        lx = xhi - xlo
        ly = yhi - ylo
        lz = zhi - zlo
        flip_z = _should_flip_crystal_layer(sources, layer_idx)

        boundaries.append(z_cursor)  # layer start

        # Crystal layers: centering only (preserve lattice constants).
        # Non-crystal layers with XY mismatch: affine rescale to fill box.
        is_crystal = source.source_type == LayerSourceType.CRYSTAL_STRUCTURE
        xy_match = abs(lx - global_lx) < 1e-6 and abs(ly - global_ly) < 1e-6

        if is_crystal or xy_match:
            use_rescale = False
            x_shift = (global_lx - lx) * 0.5
            y_shift = (global_ly - ly) * 0.5
            scale_x = 1.0
            scale_y = 1.0
        else:
            use_rescale = True
            scale_x = global_lx / lx if lx > 1e-6 else 1.0
            scale_y = global_ly / ly if ly > 1e-6 else 1.0
            logger.info(
                "Layer %d (%s): affine rescale XY by (%.4f, %.4f)",
                layer_idx,
                source.source_id,
                scale_x,
                scale_y,
            )

        start_index = len(atoms)
        atom_id_to_idx: dict[int, int] = {}

        for local_idx, atom in enumerate(source.info.atoms):
            element = source.type_map.get(str(atom.atom_type), "X")
            if use_rescale:
                ax = (atom.x - xlo) * scale_x
                ay = (atom.y - ylo) * scale_y
            else:
                ax = (atom.x - xlo) + x_shift
                ay = (atom.y - ylo) + y_shift
            combined = _CombinedAtom(
                element=element,
                charge=float(atom.charge),
                x=ax,
                y=ay,
                z=_layer_local_z(atom.z, zlo, zhi, flip_z=flip_z) + z_cursor,
                layer_index=layer_idx + 1,
                original_atom_type=atom.atom_type,
                original_mol_id=atom.mol_id,
            )
            atoms.append(combined)
            atom_id_to_idx[atom.atom_id] = start_index + local_idx

        for bond in source.info.bonds:
            idx1 = atom_id_to_idx.get(bond.atom1_id)
            idx2 = atom_id_to_idx.get(bond.atom2_id)
            if idx1 is not None and idx2 is not None:
                bonds.append([idx1, idx2])

        z_cursor += lz
        boundaries.append(z_cursor)  # layer end

        # Insert inter-layer gap (skip after last layer)
        if layer_idx < len(sources) - 1:
            gap = (
                per_layer_gaps[layer_idx]
                if per_layer_gaps and per_layer_gaps[layer_idx] is not None
                else inter_layer_gap
            )
            if gap > 0:
                z_cursor += gap

    xyz_lines = [str(len(atoms)), "Layered structure preview"]
    for atom in atoms:
        xyz_lines.append(f"{atom.element} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}")

    return _CombinedGeometry(
        atoms=atoms,
        bonds=bonds,
        box_size=(global_lx, global_ly, z_cursor),
        layer_boundaries_z=boundaries,
        xyz="\n".join(xyz_lines),
    )


def _protocol_layer_boundaries_with_vacuum(
    boundaries: list[float],
    *,
    z_vacuum: float = _LAYER_POLICY.z_vacuum_angstrom,
) -> list[float]:
    """Shift layer boundaries into the submit-time z coordinate system.

    Preview geometry uses the physical slab coordinates starting at z=0.
    The submit data file adds symmetric vacuum padding on both sides, so
    tensile grip regions must use the same shifted coordinates.
    """
    return [float(boundary) + z_vacuum for boundary in boundaries]


def _write_combined_lammps_data(
    path: Path,
    geometry: _CombinedGeometry,
    sources: list[_ResolvedLayerSource] | None = None,
    *,
    z_vacuum: float = _LAYER_POLICY.z_vacuum_angstrom,
) -> list[dict] | None:
    """Write combined LAMMPS data file preserving full topology from sources.

    When *sources* is provided, bonds/angles/dihedrals/impropers and their
    coefficient sections are merged with proper type-ID offsets so LAMMPS
    can read the file as-is.  Crystal atom types are annotated in a trailing
    comment for downstream crystal-freeze detection.
    """
    if sources is None:
        # Legacy path: element-based simple output (preview only)
        _write_combined_lammps_data_simple(path, geometry)
        return None

    # ── Build global type maps with per-layer offsets ──
    # Each layer contributes its own atom/bond/angle/dihedral/improper types.
    # We remap them into a unified numbering.
    global_atom_type_offset: list[int] = []  # per-layer offset
    global_bond_type_offset: list[int] = []
    global_angle_type_offset: list[int] = []
    global_dihedral_type_offset: list[int] = []
    global_improper_type_offset: list[int] = []
    total_atom_types = 0
    total_bond_types = 0
    total_angle_types = 0
    total_dihedral_types = 0
    total_improper_types = 0

    for source in sources:
        info = source.info
        global_atom_type_offset.append(total_atom_types)
        global_bond_type_offset.append(total_bond_types)
        global_angle_type_offset.append(total_angle_types)
        global_dihedral_type_offset.append(total_dihedral_types)
        global_improper_type_offset.append(total_improper_types)
        total_atom_types += info.n_atom_types
        total_bond_types += info.n_bond_types
        total_angle_types += info.n_angle_types
        total_dihedral_types += info.n_dihedral_types
        total_improper_types += info.n_improper_types

    # ── Collect all bonds/angles/dihedrals/impropers with remapped IDs ──
    all_bonds: list[str] = []
    all_angles: list[str] = []
    all_dihedrals: list[str] = []
    all_impropers: list[str] = []

    # Track layer lineage for GroupEnergySpec v2
    layer_lineage: list[dict] = []
    _lineage_cursor = 0
    for _li, src in enumerate(sources):
        _n = len(src.info.atoms)
        layer_lineage.append(
            {
                "index": _li,
                "type": src.source_type.value
                if hasattr(src.source_type, "value")
                else str(src.source_type),
                "atom_id_start": _lineage_cursor + 1,
                "atom_id_end": _lineage_cursor + _n,
            }
        )
        _lineage_cursor += _n

    # We need atom-id mapping: per source, original atom_id → global 1-based atom_id
    # _combine_sources_to_geometry already tracked this, but we need to rebuild from
    # the same traversal order.
    atom_cursor = 0
    for layer_idx, source in enumerate(sources):
        info = source.info
        # Build local atom_id → global atom_id map
        local_to_global: dict[int, int] = {}
        for local_idx, atom in enumerate(info.atoms):
            local_to_global[atom.atom_id] = atom_cursor + local_idx + 1
        atom_cursor += len(info.atoms)

        bt_off = global_bond_type_offset[layer_idx]
        agt_off = global_angle_type_offset[layer_idx]
        dt_off = global_dihedral_type_offset[layer_idx]
        it_off = global_improper_type_offset[layer_idx]

        for bond in info.bonds:
            g1 = local_to_global.get(bond.atom1_id)
            g2 = local_to_global.get(bond.atom2_id)
            if g1 is not None and g2 is not None:
                bid = len(all_bonds) + 1
                all_bonds.append(f"{bid} {bond.bond_type + bt_off} {g1} {g2}")

        if info.angles:
            for angle in info.angles:
                g1 = local_to_global.get(angle.atom1_id)
                g2 = local_to_global.get(angle.atom2_id)
                g3 = local_to_global.get(angle.atom3_id)
                if g1 is not None and g2 is not None and g3 is not None:
                    aid = len(all_angles) + 1
                    all_angles.append(f"{aid} {angle.angle_type + agt_off} {g1} {g2} {g3}")

        if info.dihedrals:
            for dih in info.dihedrals:
                g1 = local_to_global.get(dih.atom1_id)
                g2 = local_to_global.get(dih.atom2_id)
                g3 = local_to_global.get(dih.atom3_id)
                g4 = local_to_global.get(dih.atom4_id)
                if g1 is not None and g2 is not None and g3 is not None and g4 is not None:
                    did = len(all_dihedrals) + 1
                    all_dihedrals.append(f"{did} {dih.dihedral_type + dt_off} {g1} {g2} {g3} {g4}")

        if info.impropers:
            for imp in info.impropers:
                g1 = local_to_global.get(imp.atom1_id)
                g2 = local_to_global.get(imp.atom2_id)
                g3 = local_to_global.get(imp.atom3_id)
                g4 = local_to_global.get(imp.atom4_id)
                if g1 is not None and g2 is not None and g3 is not None and g4 is not None:
                    iid = len(all_impropers) + 1
                    all_impropers.append(f"{iid} {imp.improper_type + it_off} {g1} {g2} {g3} {g4}")

    # ── Merge masses with offsets ──
    # NOTE: Crystal subtype labels (Os, Hoh, Si_s) are mapped to bare elements
    # (O, H, Si) by estimate_elements_from_info() mass matching. This is
    # expected — merged data uses bare elements for INTERFACE FF lookup.
    merged_masses: dict[int, tuple[float, str]] = {}  # global_type → (mass, comment)
    for layer_idx, source in enumerate(sources):
        off = global_atom_type_offset[layer_idx]
        for local_type, mass in source.info.masses.items():
            element = source.type_map.get(str(local_type), "X")
            merged_masses[local_type + off] = (mass, element)

    # ── Merge coeff sections with remapped type IDs ──
    def _merge_coeff_section(section_name: str, offsets: list[int]) -> list[str]:
        merged: list[str] = []
        for layer_idx, source in enumerate(sources):
            raw = (source.info.raw_coeff_sections or {}).get(section_name, "")
            if not raw:
                continue
            off = offsets[layer_idx]
            for raw_line in raw.strip().split("\n"):
                raw_line = raw_line.strip()
                if not raw_line or raw_line.startswith("#"):
                    continue
                parts = raw_line.split(None, 1)
                if len(parts) >= 2:
                    try:
                        old_id = int(parts[0])
                        merged.append(f"{old_id + off} {parts[1]}")
                    except ValueError:
                        merged.append(raw_line)
                else:
                    merged.append(raw_line)
        return merged

    pair_coeffs = _merge_coeff_section("Pair Coeffs", global_atom_type_offset)

    # ── Fill missing Pair Coeffs with INTERFACE FF (fail-closed, no fallback) ──
    # Crystal sources typically lack Pair Coeffs.  Without them LAMMPS will
    # error because binder Pair Coeffs only cover binder types.
    # INTERFACE FF (Heinz et al. 2013) provides mineral-optimized LJ params
    # validated against experimental surface energies.  Unsupported elements
    # raise ValueError (fail-closed policy v00.99.29).
    #
    # NOTE: Profile-aware lookup (source.profile_id tracking) will be added
    # in a follow-up phase. Currently using INTERFACE_FF directly which
    # already contains the same parameters as active profiles.
    covered_types: set[int] = set()
    for line in pair_coeffs:
        parts = line.split(None, 1)
        if parts:
            try:
                covered_types.add(int(parts[0]))
            except ValueError:
                pass

    for gtype in sorted(merged_masses):
        if gtype not in covered_types:
            _mass, elem = merged_masses[gtype]
            # Fail-closed policy (v00.99.29): INTERFACE FF only, no UFF fallback.
            # INTERFACE FF contains CLAYFF-compatible LJ for mineral elements
            # (Si, O, H, Al, Mg, etc.) from Heinz et al. 2013.
            # UFF fallback has been removed to ensure FF consistency.
            if iff := INTERFACE_FF_MINERAL_PARAMS.get(elem):
                eps = iff["epsilon"]
                sig = iff["sigma"]
                pair_coeffs.append(f"{gtype} {eps} {sig} # INTERFACE FF ({elem})")
            else:
                raise ValueError(
                    f"No LJ parameters for element '{elem}' (atom type {gtype}). "
                    f"INTERFACE FF does not cover this element. "
                    f"Add validated parameters to mineral_lj_catalog.yaml. "
                    f"Currently supported: {sorted(INTERFACE_FF_MINERAL_PARAMS.keys())}"
                )

    bond_coeffs = _merge_coeff_section("Bond Coeffs", global_bond_type_offset)
    angle_coeffs = _merge_coeff_section("Angle Coeffs", global_angle_type_offset)
    dihedral_coeffs = _merge_coeff_section("Dihedral Coeffs", global_dihedral_type_offset)
    improper_coeffs = _merge_coeff_section("Improper Coeffs", global_improper_type_offset)

    # ── Identify crystal atom types for freeze annotation ──
    crystal_type_ids: set[int] = set()
    for layer_idx, source in enumerate(sources):
        if source.source_type == LayerSourceType.CRYSTAL_STRUCTURE:
            off = global_atom_type_offset[layer_idx]
            for local_type in source.info.masses:
                crystal_type_ids.add(local_type + off)

    # ── Build per-layer molecule ID offsets ──
    # Preserve original molecule identity across layers by offsetting mol_ids.
    global_mol_id_offset: list[int] = []
    mol_id_cursor = 0
    for source in sources:
        global_mol_id_offset.append(mol_id_cursor)
        max_mol = max((a.mol_id for a in source.info.atoms), default=0)
        mol_id_cursor += max_mol

    # ── Write data file with z-vacuum buffer for kspace slab correction ──
    # The vacuum is submit-only: geometry.box_size preserves physical slab
    # dimensions for preview/UI.  Atom z-coords are offset by z_vacuum so
    # the slab sits centred between vacuum regions.
    lx, ly, lz = geometry.box_size
    z_box = lz + 2 * z_vacuum

    lines = [
        "LAMMPS data file - Layered structure prebuilt",
        "",
        f"{len(geometry.atoms)} atoms",
        f"{len(all_bonds)} bonds",
        f"{len(all_angles)} angles",
        f"{len(all_dihedrals)} dihedrals",
        f"{len(all_impropers)} impropers",
        "",
        f"{total_atom_types} atom types",
        f"{total_bond_types} bond types",
        f"{total_angle_types} angle types",
        f"{total_dihedral_types} dihedral types",
        f"{total_improper_types} improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {z_box:.6f} zlo zhi",
        "",
        "Masses",
        "",
    ]
    for gtype in sorted(merged_masses):
        mass, elem = merged_masses[gtype]
        lines.append(f"{gtype} {mass:.6f} # {elem}")

    # Coeff sections (Pair Coeffs always written — INTERFACE FF for minerals)
    lines.extend(["", "Pair Coeffs", ""])
    lines.extend(pair_coeffs)
    if bond_coeffs:
        lines.extend(["", "Bond Coeffs", ""])
        lines.extend(bond_coeffs)
    if angle_coeffs:
        lines.extend(["", "Angle Coeffs", ""])
        lines.extend(angle_coeffs)
    if dihedral_coeffs:
        lines.extend(["", "Dihedral Coeffs", ""])
        lines.extend(dihedral_coeffs)
    if improper_coeffs:
        lines.extend(["", "Improper Coeffs", ""])
        lines.extend(improper_coeffs)

    # Atoms (z-coords offset by z_vacuum so slab sits between vacuum regions)
    lines.extend(["", "Atoms # full", ""])
    for atom_id, atom in enumerate(geometry.atoms, start=1):
        off = global_atom_type_offset[atom.layer_index - 1]
        gtype = atom.original_atom_type + off
        mol_off = global_mol_id_offset[atom.layer_index - 1]
        gmol = atom.original_mol_id + mol_off
        az = atom.z + z_vacuum
        lines.append(
            f"{atom_id} {gmol} {gtype} {atom.charge:.6f} {atom.x:.6f} {atom.y:.6f} {az:.6f}"
        )

    # Charge neutrality check
    total_charge = sum(a.charge for a in geometry.atoms)
    if abs(total_charge) > 1.0:
        logger.warning(
            "Combined layered system net charge = %.4f e (%d atoms)",
            total_charge,
            len(geometry.atoms),
        )

    # Bonds
    if all_bonds:
        lines.extend(["", "Bonds", ""])
        lines.extend(all_bonds)

    # Angles
    if all_angles:
        lines.extend(["", "Angles", ""])
        lines.extend(all_angles)

    # Dihedrals
    if all_dihedrals:
        lines.extend(["", "Dihedrals", ""])
        lines.extend(all_dihedrals)

    # Impropers
    if all_impropers:
        lines.extend(["", "Impropers", ""])
        lines.extend(all_impropers)

    # Crystal atom types annotation (for downstream crystal-freeze detection)
    if crystal_type_ids:
        sorted_types = " ".join(str(t) for t in sorted(crystal_type_ids))
        lines.append("")
        lines.append(f"# Crystal atom types: {sorted_types}")
        lines.append("# Crystal FF: INTERFACE_FF (Heinz et al. 2013, Lorentz-Berthelot mixing)")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return layer_lineage


def _write_combined_lammps_data_simple(path: Path, geometry: _CombinedGeometry) -> None:
    """Simple element-based data file for preview (no topology preservation)."""
    atom_types: dict[str, int] = {}
    masses: dict[int, float] = {}

    for atom in geometry.atoms:
        if atom.element not in atom_types:
            next_type = len(atom_types) + 1
            atom_types[atom.element] = next_type
            masses[next_type] = float(ATOMIC_WEIGHTS.get(atom.element, 12.0))

    lx, ly, lz = geometry.box_size
    lines = [
        "LAMMPS data file - Layered structure prebuilt",
        "",
        f"{len(geometry.atoms)} atoms",
        "0 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        f"{len(atom_types)} atom types",
        "0 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
    ]

    for element, type_id in atom_types.items():
        lines.append(f"{type_id} {masses[type_id]:.6f} # {element}")

    lines.extend(["", "Atoms # full", ""])
    for atom_id, atom in enumerate(geometry.atoms, start=1):
        type_id = atom_types[atom.element]
        lines.append(
            f"{atom_id} {atom.layer_index} {type_id} {atom.charge:.6f} "
            f"{atom.x:.6f} {atom.y:.6f} {atom.z:.6f}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_has_fail(checks: list[LayeredStructureCheckResponse]) -> bool:
    return any(check.status == "fail" for check in checks)


def _validate_source_readiness_for_submit(sources: list[_ResolvedLayerSource]) -> None:
    """Enforce strict source readiness before layered submit."""
    allowed = {
        LayerSourceType.BINDER_CELL: {"completed"},
        LayerSourceType.INTERFACE_MOLECULE_CELL: {"ready"},
        LayerSourceType.CRYSTAL_STRUCTURE: {"ready"},
    }
    blocked: list[dict[str, str]] = []
    for source in sources:
        status = str(source.status or "").strip().lower()
        if status not in allowed[source.source_type]:
            blocked.append(
                {
                    "source_type": source.source_type.value,
                    "source_id": source.source_id,
                    "status": source.status,
                }
            )
    if blocked:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            "Some layer sources are not ready for submit",
            {"blocked_sources": blocked},
        )


async def list_layer_sources(
    *,
    source_type: LayerSourceType,
    limit: int = 100,
    visibility: str = "library",
) -> LayerSourceListResponse:
    """List selectable sources for layered-structure composer."""
    from features.common import run_in_session

    bounded_limit = max(1, min(limit, 300))

    def _load(session):
        from database.repositories.experiment_repo import ExperimentRepository

        if source_type == LayerSourceType.BINDER_CELL:
            repo = ExperimentRepository(session)
            if visibility == "library":
                allowed = {"completed"}
            else:
                allowed = {"completed", "queued", "ready", "running"}
            rows = [
                r for r in repo.list_all(limit=bounded_limit * 3) if (r.status or "") in allowed
            ]
            rows = rows[:bounded_limit]
            items = [
                LayerSourceSummaryResponse(
                    source_type=source_type,
                    source_id=row.exp_id,
                    name=row.exp_id,
                    status=str(row.status or "unknown"),
                    atom_count=int(row.actual_atoms or row.target_atoms or 0) or None,
                    box_size=(
                        (float(row.box_lx), float(row.box_ly), float(row.box_lz))
                        if row.box_lx and row.box_ly and row.box_lz
                        else None
                    ),
                    boundary_mode="ppf",
                )
                for row in rows
            ]
            return LayerSourceListResponse(total=len(items), items=items)

        if source_type == LayerSourceType.INTERFACE_MOLECULE_CELL:
            from features.common.interface_sources import list_canonical_sources

            cells = list_canonical_sources(
                limit=bounded_limit,
                visibility=visibility,
                session=session,
            )
            items = [
                LayerSourceSummaryResponse(
                    source_type=source_type,
                    source_id=cell["source_id"],
                    name=cell.get("name", cell["source_id"]),
                    status=str(cell.get("status", "unknown")),
                    atom_count=cell.get("atom_count"),
                    box_size=(
                        float(cell.get("lx_angstrom", 0)),
                        float(cell.get("ly_angstrom", 0)),
                        float(cell.get("lz_angstrom", 0)),
                    ),
                    boundary_mode=str(cell.get("boundary_mode", "ppf")),
                )
                for cell in cells
            ]
            return LayerSourceListResponse(total=len(items), items=items)

        rows = list(load_crystal_structures_config().get("structures", []))
        if visibility == "library":
            rows = [row for row in rows if str(row.get("status", "")) == "ready"]
        rows = rows[:bounded_limit]
        items = [
            LayerSourceSummaryResponse(
                source_type=source_type,
                source_id=str(row.get("crystal_id", "")),
                name=str(row.get("name", row.get("crystal_id", ""))),
                status=str(row.get("status", "unknown")),
                atom_count=int(row.get("atom_count", 0) or 0) or None,
                box_size=_crystal_row_box_size(row),
                boundary_mode="ppp",
                material=str(row.get("material", "")) or None,
            )
            for row in rows
            if str(row.get("crystal_id", "")).strip()
        ]
        return LayerSourceListResponse(total=len(items), items=items)

    return run_in_session(_load)


async def list_layer_sources_legacy(
    *,
    limit: int = 100,
    visibility: str = "library",
) -> LayerSourceListResponse:
    """Legacy alias: return DB amorphous cells only."""
    from features.common import run_in_session
    from features.common.interface_sources import list_legacy_only_sources

    bounded_limit = max(1, min(limit, 500))

    def _query(session):
        cells = list_legacy_only_sources(
            limit=bounded_limit,
            visibility=visibility,
            session=session,
        )
        return [
            LayerSourceSummaryResponse(
                source_type=LayerSourceType.INTERFACE_MOLECULE_CELL,
                source_id=cell["source_id"],
                name=cell.get("name", cell["source_id"]),
                status=str(cell.get("status", "unknown")),
                atom_count=cell.get("atom_count"),
                box_size=(
                    float(cell.get("lx_angstrom", 0)),
                    float(cell.get("ly_angstrom", 0)),
                    float(cell.get("lz_angstrom", 0)),
                ),
                boundary_mode=str(cell.get("boundary_mode", "ppf")),
            )
            for cell in cells
        ]

    items = run_in_session(_query)
    return LayerSourceListResponse(total=len(items), items=items)


async def preview_layered_structure(
    request: LayeredStructurePreviewRequest,
) -> LayeredStructurePreviewResponse:
    """Build combined XYZ preview and compatibility checks for layer stack."""
    sources = _load_layer_sources(request.layers)
    tol_pct = _resolve_tolerance_pct(request, sources)
    # P0-1: 게이트는 실제 빌드에 쓰일 진공값으로 평가한다(None → 정책 기본).
    resolved_z_vacuum = float(
        request.z_vacuum_angstrom
        if request.z_vacuum_angstrom is not None
        else _LAYER_POLICY.z_vacuum_angstrom
    )
    checks = _validate_checks(
        sources,
        xy_tolerance_pct=tol_pct,
        min_xy_to_z_ratio=request.min_xy_to_z_ratio,
        z_vacuum_angstrom=resolved_z_vacuum,
    )

    per_layer_gaps = [layer.gap_after_angstrom for layer in request.layers]
    if per_layer_gaps:
        per_layer_gaps[-1] = None  # last layer gap is always 0
    geometry = _combine_sources_to_geometry(
        sources,
        inter_layer_gap=request.inter_layer_gap_angstrom,
        per_layer_gaps=per_layer_gaps,
    )

    # E_inter recommendation for layered structures (Finding #8)
    from api.schemas import EInterRecommendationResponse
    from features.e_inter_compute.service import DEFAULT_E_INTER_COMPUTE_SERVICE

    e_inter_rec = DEFAULT_E_INTER_COMPUTE_SERVICE.get_recommendation(
        workflow="layered_structure",
        tier="screening",  # Preview doesn't have tier info, default to screening
        layer_count=len(sources),
        estimated_atoms=len(geometry.atoms),
    )
    e_inter_response = EInterRecommendationResponse(
        level=e_inter_rec["level"],
        score=e_inter_rec["score"],
        reason_codes=e_inter_rec["reason_codes"],
        affected_metrics=e_inter_rec["affected_metrics"],
        estimated_cpu_cost_minutes=e_inter_rec["estimated_cpu_cost_minutes"],
        default_enabled=e_inter_rec["default_enabled"],
    )

    return LayeredStructurePreviewResponse(
        xyz=geometry.xyz,
        box_size=geometry.box_size,
        n_atoms=len(geometry.atoms),
        n_bonds=len(geometry.bonds),
        bonds=geometry.bonds,
        layer_boundaries_z=geometry.layer_boundaries_z,
        checks=checks,
        e_inter_recommendation=e_inter_response,
    )


async def submit_layered_structure(
    request: LayeredStructureSubmitRequest,
) -> LayeredStructureSubmitResponse:
    """Submit layered structure as single-job simulation using prebuilt data."""
    from orchestrator.exp_id_helper import generate_exp_id_from_material
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade
    from protocols.e_intra_method_resolver import resolve_submission_e_intra_method
    from protocols.stage_plan_compiler import build_stage_plan_metadata

    preview = await preview_layered_structure(
        LayeredStructurePreviewRequest(
            layers=request.layers,
            xy_tolerance_pct=request.xy_tolerance_pct,
            xy_tolerance_angstrom=request.xy_tolerance_angstrom,
            min_xy_to_z_ratio=request.min_xy_to_z_ratio,
            inter_layer_gap_angstrom=request.inter_layer_gap_angstrom,
            # P0-1: 게이트가 submit의 실제 진공값을 보도록 전달.
            z_vacuum_angstrom=request.z_vacuum_angstrom,
        )
    )
    if _check_has_fail(preview.checks):
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            "Layer stack has failed checks. Resolve mismatches before submit.",
            {"checks": [check.model_dump() for check in preview.checks]},
        )

    sources = _load_layer_sources(request.layers)
    _validate_source_readiness_for_submit(sources)
    per_layer_gaps = [layer.gap_after_angstrom for layer in request.layers]
    if per_layer_gaps:
        per_layer_gaps[-1] = None  # last layer gap is always 0
    geometry = _combine_sources_to_geometry(
        sources,
        inter_layer_gap=request.inter_layer_gap_angstrom,
        per_layer_gaps=per_layer_gaps,
    )

    from features.experiments.validation import parse_tier_and_ff, resolve_stage_requests

    run_tier, ff_type = parse_tier_and_ff(request.run_tier, request.ff_type)
    resolved_e_intra_method = resolve_submission_e_intra_method(request.e_intra_method).value
    # Layered structures always use ppf: x,y periodic, z fixed.
    # p p p is physically inappropriate (z-periodic images overlap).
    boundary_mode = "ppf"
    study_type = StudyType.LAYER_BULKFF
    tensile_enabled = getattr(request, "tensile_enabled", False)
    if tensile_enabled:
        tensile_mode = getattr(request, "tensile_mode", None) or "continuous"
        chain_key = "tensile_layer_qs" if tensile_mode == "quasi_static" else "tensile_layer"
    else:
        chain_key = "layer"
    # Extract skip_stage_keys from stage_requests (layered-specific, no coupling)
    skip_stage_keys: list[str] | None = None
    layered_canonical_requests: list[dict] = []
    if getattr(request, "stage_requests", None):
        skip_stage_keys = [sr.stage_key for sr in request.stage_requests if not sr.enabled]
        layered_canonical_requests = [
            {
                "stage_key": sr.stage_key,
                "enabled": sr.enabled,
                "duration_ps": sr.duration_ps,
                "duration_steps": sr.duration_steps,
                "params_override": sr.params_override,
            }
            for sr in request.stage_requests
        ]
        if not skip_stage_keys:
            skip_stage_keys = None

    stage_config = resolve_stage_requests(
        stage_requests=None,
        stage_durations=request.stage_durations,
        equilibration_settings=None,
        run_tier=run_tier,
        chain_key_override=chain_key,
    )

    # Merge layered canonical requests for metadata
    if layered_canonical_requests:
        stage_config.canonical_stage_requests.extend(layered_canonical_requests)
    seed = generate_seed(request.seed)

    # ── Extract binder material_id from first BINDER_CELL source ──
    _binder_material_id = "custom_X1_non_aging"  # fallback
    for _src in sources:
        if _src.source_type == LayerSourceType.BINDER_CELL and _src.source_id:
            from common.pathing import exp_id_to_material_id

            try:
                _binder_material_id = exp_id_to_material_id(_src.source_id)
            except Exception:
                pass
            break

    # ── Extract crystal info from YAML catalog ──
    _crystal_material: str | None = None
    _crystal_surface: str | None = None
    _crystal_hydroxylated: bool | None = None
    _crystal_catalog = {
        str(c.get("crystal_id", "")): c
        for c in load_crystal_structures_config().get("structures", [])
    }
    for _src in sources:
        if _src.source_type == LayerSourceType.CRYSTAL_STRUCTURE and _src.source_id:
            _row = _crystal_catalog.get(_src.source_id)
            if _row:
                _crystal_material = _row.get("material")
                _crystal_surface = _row.get("surface")
                _crystal_hydroxylated = _row.get("hydroxylated")
            break

    _additive_label: str
    if _crystal_material:
        _additive_label = _crystal_additive_label(
            material=_crystal_material,
            surface=_crystal_surface,
            hydroxylated=_crystal_hydroxylated,
        )
    else:
        _additive_label = "layered"

    exp_id = generate_exp_id_from_material(
        material_id=_binder_material_id,
        temperature_k=request.temperature_K,
        ff_type=ff_type.value,
        atom_count=max(1, len(geometry.atoms)),
        seed=seed,
        additive=_additive_label,
    )

    input_dir = get_experiment_path(exp_id, "input", create=True)
    data_path = input_dir / "data.lammps"
    xyz_path = input_dir / "layer_preview.xyz"
    # P2-4: 명시적 0이 정책 기본으로 조용히 치환되지 않도록 None만 폴백.
    z_vacuum = float(
        request.z_vacuum_angstrom
        if request.z_vacuum_angstrom is not None
        else _LAYER_POLICY.z_vacuum_angstrom
    )
    layer_lineage = _write_combined_lammps_data(
        data_path, geometry, sources=sources, z_vacuum=z_vacuum
    )
    xyz_path.write_text(geometry.xyz + "\n", encoding="utf-8")

    # ── Resolve real composition + aggregate binder-source mol_counts for CED ──
    comp, no_binder_source, total_mol_counts, ced_source_records = _collect_layered_ced_provenance(
        sources
    )
    layer_labels, layer_volumes_A3, mol_counts_by_layer = _build_layered_profile_provenance(
        request,
        preview,
        ced_source_records,
    )

    build_request = create_build_request(
        composition=comp,
        seed=seed,
        target_atoms=max(1, len(geometry.atoms)),
        tier=run_tier,
        composition_mode="wt_percent",
        prebuilt_data_file_path=str(data_path),
        box_dimensions=tuple(float(v) for v in geometry.box_size),
    )
    # Build tensile_spec from request if enabled
    tensile_spec = None
    if getattr(request, "tensile_enabled", False):
        from contracts.schemas import TensileMode, TensileSpec

        tensile_spec = TensileSpec(
            enabled=True,
            mode=TensileMode(getattr(request, "tensile_mode", None) or "continuous"),
            pull_velocity_A_per_fs=request.tensile_pull_velocity or 0.00005,
            grip_thickness_angstrom=request.tensile_grip_thickness or 20.0,
            max_strain=request.tensile_max_strain or 0.5,
            displacement_increment_angstrom=(
                getattr(request, "tensile_displacement_increment", None) or 0.5
            ),
            relax_steps=getattr(request, "tensile_relax_steps", None) or 10000,
            force_average_steps=getattr(request, "tensile_force_average_steps", None) or 1000,
        )

    # Build layer_spec for grip z-boundary calculation
    layer_spec_for_protocol = None
    if tensile_spec is not None and preview.layer_boundaries_z:
        from contracts.schemas import LayerSpec

        shifted = _protocol_layer_boundaries_with_vacuum(
            preview.layer_boundaries_z,
            z_vacuum=z_vacuum,
        )
        bottom_grip, top_grip = _compute_crystal_grip_ranges(sources, shifted)
        layer_spec_for_protocol = LayerSpec(
            layer_boundary_z=shifted,
            bottom_grip_z_range=bottom_grip,
            top_grip_z_range=top_grip,
            grip_mode="crystal_full" if (bottom_grip or top_grip) else None,
        )

    protocol_request = create_protocol_request(
        tier=run_tier,
        ff_type=ff_type,
        study_type=study_type,
        temperature_K=request.temperature_K,
        pressure_atm=request.pressure_atm,
        data_file_path=str(data_path),
        e_intra_method=resolved_e_intra_method,
        ced_provenance_mol_counts=total_mol_counts or None,
        ced_provenance_mol_counts_by_layer=mol_counts_by_layer or None,
        ced_provenance_layer_volumes_A3=layer_volumes_A3 or None,
        ced_provenance_layer_labels=layer_labels or None,
        tensile_spec=tensile_spec,
        layer_spec=layer_spec_for_protocol,
        skip_stage_keys=skip_stage_keys,
    )

    # Layer v2: inject layer-based group energy spec
    if layer_lineage and len(layer_lineage) >= 2:
        from metrics.group_assignment import LayerGroupAssignmentBuilder

        protocol_request.group_energy_spec = LayerGroupAssignmentBuilder().build(layer_lineage)

    from api.deps import get_job_manager
    from config.dashboard_settings import load_dashboard_settings

    metadata = {
        "source": SubmissionSource.LAYERED_STRUCTURES.value,
        "chain_key": chain_key,
        "name": request.name,
        "e_intra_method": resolved_e_intra_method,
        "layers": [layer.model_dump() for layer in request.layers],
        "checks": [check.model_dump() for check in preview.checks],
        "layer_boundaries_z": preview.layer_boundaries_z,
        "box_size": list(preview.box_size),
        "boundary_mode": boundary_mode,
    }
    metadata["binder_material_id"] = _binder_material_id
    metadata["crystal_material"] = _crystal_material
    metadata["layer_lineage"] = layer_lineage
    metadata["ced_provenance"] = {
        "e_intra_method": resolved_e_intra_method,
        "e_intra_method_source": "request" if request.e_intra_method else "settings_default",
        "mol_counts": total_mol_counts,
        "mol_counts_by_layer": mol_counts_by_layer or None,
        "layer_volumes_A3": layer_volumes_A3 or None,
        "layer_labels": layer_labels or None,
        "mol_count_source": "binder_source_experiments" if total_mol_counts else None,
        "source_layers": ced_source_records,
    }
    if no_binder_source:
        metadata["no_binder_source"] = True
    if not total_mol_counts:
        metadata["ced_skip_reason"] = "missing_mol_counts"
    # v01.02.17: E_inter 정밀 분석 설정 (CPU rerun)
    # 명시적 요청이 항상 우선. 없으면 정책 기반 자동 활성화(원칙 #2: 계면
    # 장거리 Coulomb 복원). 계면은 정전기 지배적이라 GPU-only e_inter는
    # 불완전 — 정책이 RECOMMENDED/REQUIRED인 layered는 GPU 완료 후 CPU rerun을
    # 자동 트리거. 동역학은 GPU/KOKKOS로 불변, rerun만 저비용 후처리.
    if request.interaction_analysis:
        metadata["interaction_analysis"] = request.interaction_analysis.model_dump()
    else:
        from contracts.policies.e_inter_compute import EInterPolicyInput
        from features.e_inter_compute.policy import resolve_default_einter_config

        _auto_einter = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier=run_tier.value,
                ff_type=ff_type.value,
                layer_count=len(layer_lineage) if layer_lineage else len(sources),
            )
        )
        if _auto_einter is not None:
            metadata["interaction_analysis"] = _auto_einter.model_dump()
    metadata = build_stage_plan_metadata(
        protocol_request=protocol_request,
        overrides=stage_config.stage_duration_overrides,
        canonical_stage_requests=stage_config.canonical_stage_requests,
        chain_key_override=chain_key,
        base_metadata=metadata,
    )

    # Record primary source info for transparency (V4 uses single interface model)
    binder_sources = [
        layer
        for layer in request.layers
        if (
            layer.source_type.value
            if hasattr(layer.source_type, "value")
            else str(layer.source_type)
        )
        == "binder_cell"
        and layer.source_id
    ]
    crystal_sources = [
        layer
        for layer in request.layers
        if (
            layer.source_type.value
            if hasattr(layer.source_type, "value")
            else str(layer.source_type)
        )
        == "crystal_structure"
    ]
    from features.common.source_compat import is_interface_like_source

    interface_sources = [
        layer
        for layer in request.layers
        if is_interface_like_source(
            layer.source_type.value
            if hasattr(layer.source_type, "value")
            else str(layer.source_type)
        )
    ]
    metadata["primary_sources"] = {
        "binder": binder_sources[0].source_id if binder_sources else None,
        "crystal": crystal_sources[0].source_id if crystal_sources else None,
        "n_binder_layers": len(binder_sources),
        "n_crystal_layers": len(crystal_sources),
        "n_interface_layers": len(interface_sources),
        "n_amorphous_layers": len(interface_sources),  # legacy compat
    }
    lineage_rows = [
        {
            "layer_index": idx,
            "source_type": layer.source_type.value
            if hasattr(layer.source_type, "value")
            else str(layer.source_type),
            "source_id": layer.source_id,
            "label": getattr(layer, "label", None),
            "gap_after_angstrom": getattr(layer, "gap_after_angstrom", None),
        }
        for idx, layer in enumerate(request.layers)
    ]

    # Stack governance gate — layered submit uses the same policy as molecule submit.
    try:
        from contracts.policies.forcefield import build_ff_provenance
        from contracts.policies.stack_governance import assert_submit_allowed

        # Layered submit: organic sources are inside binder cells, not directly
        # accessible as molecule IDs. Use default layered stack governance
        # (gaff2_org__inorganic_profile__arith_v1, research_only) without
        # generator-aware override. Fragment fallback governance applies to
        # bulk organic submits where molecule IDs are directly available.
        _prov = build_ff_provenance(
            study_type="layer_bulkff",
            ff_type=ff_type.value if hasattr(ff_type, "value") else str(ff_type),
        )
        assert_submit_allowed(_prov["metadata"].get("stack_id", ""))
    except Exception as _gov_exc:
        if isinstance(_gov_exc, ContractError):
            raise
        import logging as _logging

        _logging.getLogger("layered_structures.service").warning(
            "Stack governance gate degraded (layered submit): %s",
            _gov_exc,
        )

    job_manager = get_job_manager()
    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", []) or None

    def _record_lineage(session, created_exp_id: str) -> None:
        from database.repositories.experiment_repo import ExperimentRepository
        from database.repositories.layered_source_repo import LayeredSourceRepository

        repo = LayeredSourceRepository(session)
        repo.create_sources(created_exp_id, lineage_rows)
        if total_mol_counts:
            ExperimentRepository(session).upsert_experiment_molecules(
                created_exp_id, total_mol_counts
            )

    job_id, _ = SubmissionFacade.submit_experiment(
        job_manager=job_manager,
        exp_id=exp_id,
        run_tier=run_tier.value,
        ff_type=ff_type.value,
        target_atoms=max(1, len(geometry.atoms)),
        temperature_k=request.temperature_K,
        pressure_atm=request.pressure_atm,
        seed=seed,
        comp_asphaltene_wt=comp["asphaltene"],
        comp_resin_wt=comp["resin"],
        comp_aromatic_wt=comp["aromatic"],
        comp_saturate_wt=comp["saturate"],
        build_request=build_request,
        protocol_request=protocol_request,
        material_id=_binder_material_id,
        selected_gpus=selected_gpus,
        stage_duration_overrides=stage_config.stage_duration_overrides,
        metadata_json=metadata,
        data_file_path=str(data_path),
        post_stub_hook=_record_lineage,
    )

    # 보완 #2 잔여: 정밀 e_inter(장거리 Coulomb)가 비활성이면 과소 경고를 표기.
    submit_checks = list(preview.checks)
    _uw = _e_inter_underestimate_check(metadata.get("interaction_analysis"))
    if _uw is not None:
        submit_checks.append(_uw)

    return LayeredStructureSubmitResponse(
        exp_id=exp_id,
        job_id=job_id,
        status="queued",
        checks=submit_checks,
        e_inter_recommendation=preview.e_inter_recommendation,
    )


def _e_inter_underestimate_check(
    interaction_analysis: dict | None,
) -> LayeredStructureCheckResponse | None:
    """정밀 e_inter(장거리 Coulomb) 비활성 시 계면 에너지 과소 경고 (보완 #2 잔여).

    KOKKOS ``compute group/group``은 ``kspace yes``를 지원하지 않아 GPU-only로
    측정한 계면 e_inter는 장거리 Coulomb이 빠진다. 광물 계면은 정전기 지배적
    이므로 이 경우 계면 에너지(e_inter/adhesion)가 **과소평가**된다. 정밀
    e_inter(CPU rerun)가 활성이 아니면 warn 체크를 반환한다(활성이면 None).

    Args:
        interaction_analysis: 해석된 interaction_analysis metadata(없으면 None).

    Returns:
        과소 경고 ``LayeredStructureCheckResponse`` 또는 None.
    """
    enabled = bool(interaction_analysis and interaction_analysis.get("enabled"))
    if enabled:
        return None
    return LayeredStructureCheckResponse(
        code="e_inter_long_range_omitted",
        status="warn",
        message=(
            "Precise long-range Coulomb e_inter (CPU rerun) is disabled; interface "
            "energy (e_inter/adhesion) will be UNDERESTIMATED — mineral interfaces "
            "are electrostatics-dominated. Enable interaction_analysis to restore it."
        ),
        details={"precise_einter_enabled": False},
    )


def _dedupe_seeds(seeds: list[int] | None) -> list[int]:
    """Preserve order, drop duplicates/None."""
    out: list[int] = []
    for s in seeds or []:
        if s is not None and s not in out:
            out.append(int(s))
    return out


async def submit_layered_replicates(
    request: LayeredStructureSubmitRequest,
) -> LayeredStructureSubmitResponse:
    """다중 seed replica를 자동 오케스트레이션하는 layered submit 진입점 (보완 #4 후속).

    ``request.replicate_seeds`` 가 2개 이상이면 같은 계면 설정을 seed별로 N회
    제출하고 한 replica group으로 묶는다(완료 시 계면 mechanical 지표를
    mean ± SE ensemble로 자동 집계). None/1개면 단일 실험(기존과 동일).

    Args:
        request: layered submit 요청.

    Returns:
        primary(첫 seed) 실험의 응답. group인 경우 ``replicate_group_id`` /
        ``replicate_exp_ids`` 가 채워진다.
    """
    seeds = _dedupe_seeds(request.replicate_seeds)

    # 단일 실험 경로(byte-identical). replicate_seeds 미지정 → 그대로 위임.
    if not request.replicate_seeds:
        return await submit_layered_structure(request)
    if len(seeds) <= 1:
        only = seeds[0] if seeds else request.seed
        return await submit_layered_structure(
            request.model_copy(update={"seed": only, "replicate_seeds": None})
        )

    import uuid

    group_id = f"rgrp_{uuid.uuid4().hex[:12]}"
    responses: list[LayeredStructureSubmitResponse] = []
    # P1-2: 부분 실패 시 이미 제출된 replica를 고아로 남기지 않는다 —
    # 이전에 큐잉된 실험들을 보상 취소하고, 실패 detail에 exp_id를 담아 재현/정리를 돕는다.
    for s in seeds:
        per = request.model_copy(update={"seed": s, "replicate_seeds": None})
        try:
            responses.append(await submit_layered_structure(per))
        except Exception as exc:
            submitted = [r.exp_id for r in responses]
            await _cancel_submitted_replicas(submitted)
            if isinstance(exc, ContractError):
                detail = dict(getattr(exc, "details", {}) or {})
                detail["replicate_seed_failed"] = s
                detail["replicate_cancelled_exp_ids"] = submitted
                raise ContractError(exc.code, str(exc), detail) from exc
            raise ContractError(
                ErrorCode.ORCHESTRATION_ERROR,
                f"Replicate submission failed at seed {s}: {exc}",
                {"replicate_seed_failed": s, "replicate_cancelled_exp_ids": submitted},
            ) from exc

    exp_ids = [r.exp_id for r in responses]

    from features.layered_structures.replicate_orchestration import tag_replicate_group

    # 태깅 실패는 응답을 죽이지 않는다(실험들은 이미 정상 제출됨). group 없이 성공
    # 응답을 반환하되 ensemble 자동집계만 비활성 — 운영자가 수동 재태깅 가능.
    try:
        tag_replicate_group(exp_ids, group_id)
    except Exception as exc:
        logger.warning("Replicate group tagging failed for %s: %s", group_id, exc)
        return responses[0]

    primary = responses[0]
    return primary.model_copy(update={"replicate_group_id": group_id, "replicate_exp_ids": exp_ids})


async def _cancel_submitted_replicas(exp_ids: list[str]) -> None:
    """부분 실패 보상: 이미 큐잉된 replica 실험들을 best-effort 취소한다."""
    if not exp_ids:
        return
    from features.experiments.experiment_lifecycle import cancel_experiment

    for exp_id in exp_ids:
        try:
            await cancel_experiment(exp_id)
        except Exception as exc:  # noqa: BLE001 — best-effort 보상
            logger.warning("Compensating cancel failed for %s: %s", exp_id, exc)
