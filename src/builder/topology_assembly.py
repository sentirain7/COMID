"""Full-topology assembly for multi-component LAMMPS .data generation.

Extracted from ``StructureBuilder._generate_full_topology`` to keep the
builder class a thin orchestration facade while the heavy topology logic
lives in a standalone, unit-testable function.

The public entry point :func:`generate_full_topology` receives all
dependencies as explicit arguments so it can be called without an
instantiated ``StructureBuilder``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common.hashing import compute_topology_hash
from common.logging import get_logger
from contracts.errors import BuildError, ErrorCode
from contracts.schemas import MoleculeCategory, MoleculeInfo
from forcefield.organic_typing_executor import TypingChargeAssignmentError
from forcefield.topology import MolTopologyBuilder
from forcefield.topology import TopologyBuilder as FFTopologyBuilder

from .mol_types import MolTopology
from .topology_helpers import find_mol_file, parse_xyz_coordinates, validate_molecule_topologies

if TYPE_CHECKING:
    from collections.abc import Callable

    from config.settings import TypingChargeSettings

    from .molecule_db import MoleculeDB
    from .packmol_wrapper import PackmolMolecule

logger = get_logger("builder.topology_assembly")


def _make_mol_progress_wrapper(
    prefix: str,
    emit_progress: Callable[[str, str | None], None] | None,
) -> Callable[[str, str], None] | None:
    """Return a ``(code, label)`` callback that prepends ``prefix`` to the
    label before delegating to ``emit_progress``. Returns ``None`` when
    ``emit_progress`` is ``None`` so callers can short-circuit cheaply.
    """
    if emit_progress is None:
        return None

    def _wrapped(code: str, label: str) -> None:
        try:
            emit_progress(code, prefix + label)
        except Exception:
            # Progress callbacks are best-effort; never block the build.
            pass

    return _wrapped


def generate_full_topology(
    *,
    packmol_molecules: list[PackmolMolecule],
    packed_xyz: Path,
    mol_counts: dict[str, int],
    molecules: dict[str, MoleculeInfo],
    output_file: Path,
    box_dimensions: tuple[float, float, float] | None = None,
    molecule_db: MoleculeDB,
    ff_name: str,
    ff_version: str,
    ff_registry_name: str,
    typing_charge_settings: TypingChargeSettings,
    emit_progress: Callable[[str, str | None], None] | None = None,
) -> tuple[Path, str]:
    """Generate LAMMPS data file with full topology (bonds, angles, dihedrals).

    This is a standalone version of the former
    ``StructureBuilder._generate_full_topology`` method.  All instance
    state that was previously accessed via ``self`` is now passed as
    explicit keyword arguments.

    Args:
        packmol_molecules: List of PackmolMolecule with structure files.
        packed_xyz: Path to Packmol output XYZ file.
        mol_counts: Molecule counts by category / mol_id.
        molecules: Molecule info dictionary.
        output_file: Output LAMMPS data file path.
        box_dimensions: Optional explicit box dimensions ``(lx, ly, lz)``.
        molecule_db: :class:`MoleculeDB` instance for topology lookups.
        ff_name: Human-readable force field name (e.g. ``"GAFF2"``).
        ff_version: Force field version string.
        ff_registry_name: Normalised FF name for the registry.
        typing_charge_settings: Typing/charge configuration from app
            settings.
        emit_progress: Optional callback for coarse-grained status updates.

    Returns:
        Tuple of ``(output_file_path, topology_hash)``.

    Raises:
        BuildError: On topology generation or validation failure.
    """

    def _emit(status: str, label: str | None = None) -> None:
        if emit_progress is not None:
            try:
                emit_progress(status, label)
            except Exception:
                pass

    # Parse packed XYZ coordinates
    packed_coords = parse_xyz_coordinates(packed_xyz)

    # Validate expected atom count (defensive coding)
    expected_atoms = 0
    for pm_mol in packmol_molecules:
        info = molecule_db.get_info(pm_mol.mol_id)
        if info is not None:
            expected_atoms += pm_mol.count * info.atom_count
    if packed_coords and len(packed_coords) != expected_atoms:
        logger.warning(
            f"Atom count mismatch: Packmol output has {len(packed_coords)} atoms, "
            f"expected {expected_atoms}. This may cause incorrect mapping."
        )

    # Load MOL topologies for each molecule type
    _emit("loading_molecule_topologies")
    # Wave 1: 3-tuple form (MolTopology, count, mol_strict). The
    # legacy 2-tuple is still accepted by MolTopologyBuilder for
    # backward compatibility, but every append below uses the
    # 3-tuple form so the route-aware strict policy reaches the
    # builder consistently.
    mol_topologies: list[tuple[MolTopology, int, bool]] = []
    topology_issues: list[dict[str, object]] = []
    # Collect inorganic override coefficients for MolTopologyBuilder
    inorganic_overrides: dict[str, Any] = {
        "atom_types": {},
        "bond_types": {},
        "angle_types": {},
        "dihedral_policy": "strict",  # Default: use strict_param_coverage
        "inorganic_ff_types": set(),  # Collect ff_types for scoped dihedral fallback
    }
    # Collect organic artifact bonded overrides for MolTopologyBuilder
    organic_overrides: dict[str, dict[str, dict[str, Any]]] = {
        "bond_types": {},
        "angle_types": {},
        "dihedral_types": {},
        "improper_types": {},
        "atom_types": {},
    }

    total_molecules = len(packmol_molecules)
    for mol_index, pm_mol in enumerate(packmol_molecules):
        mol_id = pm_mol.mol_id
        count = pm_mol.count
        # Per-molecule prefix for fine-grained build phase labels:
        # e.g. "[3/12 SA-Squalane] 부분전하 계산 (antechamber AM1-BCC)"
        mol_label_prefix = f"[{mol_index + 1}/{total_molecules} {mol_id}] "
        mol_progress = _make_mol_progress_wrapper(mol_label_prefix, emit_progress)

        # Use original MOL file if available, otherwise search for it
        mol_file = pm_mol.original_mol_file
        if mol_file is None or not mol_file.exists():
            mol_file = find_mol_file(pm_mol.structure_file, mol_id, molecule_db)

        if not mol_file or not mol_file.exists():
            topology_issues.append(
                {
                    "mol_id": mol_id,
                    "count": count,
                    "issue": "MOL topology file not found",
                }
            )
            continue

        topology = molecule_db.parse_mol_topology(mol_file, mol_id)
        if topology is None:
            topology_issues.append(
                {
                    "mol_id": mol_id,
                    "count": count,
                    "issue": f"Failed to parse MOL topology: {mol_file}",
                }
            )
            continue

        # Check if this is an additive with parameterization config
        mol_info = molecule_db.get_info(mol_id)
        is_additive_category = mol_info and mol_info.category == MoleculeCategory.ADDITIVE
        additive_def = molecule_db.get_additive_definition(mol_id)

        # Fail-closed: check for YAML load errors when processing additives
        if is_additive_category:
            yaml_error = molecule_db.get_additives_load_error()
            if yaml_error is not None:
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Additive '{mol_id}' requires additives.yaml but "
                        f"loading failed: {yaml_error}",
                    }
                )
                continue

            # Fail-closed: additive definition must exist in YAML
            if additive_def is None:
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Additive '{mol_id}' not found in additives.yaml",
                    }
                )
                continue

        # Resolve typing strategy via shared SSOT router.
        # Wave 0: the ff_assignment SSOT is authoritative; additive_def is
        # still passed as a legacy fallback (e.g., profile_id resolution).
        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        ff_assignment = molecule_db.get_ff_assignment(mol_id)
        decision = resolve_typing_strategy(mol_id, additive_def, ff_assignment)

        # Wave 1: per-mol strict policy. Routes that come with curated
        # parameter coverage (artifact / inorganic profile) must
        # fail-closed on missing bonded params.
        mol_strict = decision.strategy in (
            TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            TypingStrategy.INORGANIC_PROFILE,
            TypingStrategy.WATER_MODEL,
        )

        if decision.strategy == TypingStrategy.BLOCKED:
            topology_issues.append(
                {
                    "mol_id": mol_id,
                    "count": count,
                    "issue": decision.blocked_reason
                    or f"Additive '{mol_id}' blocked by typing router.",
                }
            )
            continue

        # Ionic profile path: activation-ready (gate check inside executor)
        if decision.strategy == TypingStrategy.IONIC_PROFILE:
            from forcefield.ionic_executor import IonicNotActivatedError, assign_ionic

            try:
                ionic_result = assign_ionic(
                    topology=topology,
                    profile_id=decision.profile_id or decision.source_id or "",
                    artifact_id=decision.source_id or mol_id,
                    # Single-molecule ionic uses vacuum context.
                    # Bulk/layered builds must pass study_type-derived context
                    # once those workflows support ionic species.
                    usage_context="vacuum",
                )
            except IonicNotActivatedError as exc:
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Ionic assignment blocked: {exc}",
                    }
                )
                continue
            if ionic_result.bonded_overrides:
                bo = ionic_result.bonded_overrides
                for key, val in (bo.get("atom_types") or {}).items():
                    organic_overrides["atom_types"].setdefault(key, val)
            mol_topologies.append((topology, count, True))
            logger.info(f"Loaded ionic topology for {mol_id}: {topology.n_atoms} atoms")
            continue

        # Inorganic profile path: use cache-aware executor
        if decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            from forcefield.inorganic_executor import assign_inorganic_with_cache
            from forcefield.inorganic_parameter_service import (
                InorganicParameterizationError,
            )

            try:
                bundle = assign_inorganic_with_cache(
                    topology=topology,
                    mol_file=mol_file,
                    additive_def=additive_def or {},
                )
            except InorganicParameterizationError as exc:
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Inorganic parameterization failed: {exc}",
                    }
                )
                continue

            # Merge inorganic coefficients into override dict
            for site_type, params in bundle.atom_type_coeffs.items():
                if site_type not in inorganic_overrides["atom_types"]:
                    inorganic_overrides["atom_types"][site_type] = params
                # Collect inorganic ff_types for scoped dihedral fallback
                inorganic_overrides["inorganic_ff_types"].add(site_type)
            for bond_key, params in bundle.bond_type_coeffs.items():
                if bond_key not in inorganic_overrides["bond_types"]:
                    inorganic_overrides["bond_types"][bond_key] = params
            for angle_key, params in bundle.angle_type_coeffs.items():
                if angle_key not in inorganic_overrides["angle_types"]:
                    inorganic_overrides["angle_types"][angle_key] = params

            # Use dihedral_policy from inorganic profile if more permissive
            if bundle.dihedral_policy == "allow_default_fallback":
                inorganic_overrides["dihedral_policy"] = bundle.dihedral_policy

            logger.info(
                "Applied inorganic profile %s to %s: charge=%.4fe (cache_hit=%s)",
                bundle.profile_id,
                mol_id,
                bundle.total_charge,
                bundle.cache_hit,
            )

            # Wave 1: inorganic_profile route is strict — pass
            # mol_strict=True so any missing bonded lookup fails-closed.
            mol_topologies.append((topology, count, mol_strict))
            logger.info(
                f"Loaded topology for {mol_id}: {topology.n_atoms} atoms, {topology.n_bonds} bonds"
            )
            continue

        # Organic typing path: dispatched through organic_typing_executor
        # which routes to the curated artifact path.
        if typing_charge_settings.enabled:
            from forcefield.organic_typing_executor import (
                OrganicAssignmentError,
                assign_organic,
            )

            # Validate artifact exists and is complete (fail-closed policy)
            if decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
                from features.molecules.artifact_runtime import ensure_organic_artifact
                from forcefield.organic_curated_artifact import (
                    ArtifactIncompleteError,
                    ArtifactMissingError,
                )

                try:
                    source_id = ensure_organic_artifact(
                        mol_id=mol_id,
                        mol_path=mol_file,
                        ff_assignment=ff_assignment or {},
                        ff_family="organic_gaff2",
                        progress_callback=mol_progress,
                    )
                except ArtifactMissingError as e:
                    topology_issues.append(
                        {
                            "mol_id": mol_id,
                            "count": count,
                            "issue": f"Build blocked: {e}. Generate artifact first via admin procedure.",
                            "error_code": "ARTIFACT_MISSING",
                        }
                    )
                    continue
                except ArtifactIncompleteError as e:
                    topology_issues.append(
                        {
                            "mol_id": mol_id,
                            "count": count,
                            "issue": f"Build blocked: {e}. Regenerate artifact with LJ parameters.",
                            "error_code": "ARTIFACT_INCOMPLETE",
                        }
                    )
                    continue

                # Update decision source_id if it was _variant_ sentinel
                if decision.source_id != source_id:
                    from forcefield.typing_router import TypingRouterDecision

                    decision = TypingRouterDecision(
                        strategy=decision.strategy,
                        source_id=source_id,
                        status=decision.status,
                    )

            # Water model dispatch — separate from organic
            if decision.strategy == TypingStrategy.WATER_MODEL:
                _emit("assigning_types_charges")
                from forcefield.water_executor import WaterAssignmentError, assign_water

                try:
                    water_result = assign_water(
                        topology=topology,
                        source_id=decision.source_id or mol_id,
                    )
                except WaterAssignmentError as exc:
                    topology_issues.append(
                        {
                            "mol_id": mol_id,
                            "count": count,
                            "issue": f"Water model assignment failed: {exc.message}",
                            "details": exc.details or {},
                        }
                    )
                    continue
                if water_result.bonded_overrides:
                    bo = water_result.bonded_overrides
                    for key, val in (bo.get("bond_types") or {}).items():
                        organic_overrides["bond_types"].setdefault(key, {"k": val.k, "r0": val.r0})
                    for key, val in (bo.get("angle_types") or {}).items():
                        organic_overrides["angle_types"].setdefault(
                            key, {"k": val.k, "theta0": val.theta0}
                        )
                    for key, val in (bo.get("atom_types") or {}).items():
                        organic_overrides["atom_types"].setdefault(key, val)
                mol_topologies.append((topology, count, mol_strict))
                logger.info(f"Loaded water topology for {mol_id}: {topology.n_atoms} atoms")
                continue

            _emit("assigning_types_charges")
            organic_result = None
            try:
                organic_result = assign_organic(
                    topology=topology,
                    mol_file=mol_file,
                    strategy=decision.strategy,
                    source_id=decision.source_id,
                    ff_name=ff_registry_name,
                    charge_model_primary=typing_charge_settings.charge_model_primary,
                    charge_model_fallback=typing_charge_settings.charge_model_fallback,
                    total_charge_tolerance=typing_charge_settings.total_charge_tolerance,
                )
            except OrganicAssignmentError as exc:
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Organic typing/charge assignment failed: {exc.message}",
                        "details": exc.details or {},
                    }
                )
                continue
            except TypingChargeAssignmentError as exc:
                # Defensive: catch TypingChargeAssignmentError in case
                # it surfaces from a subclass test path or an unexpected
                # code path.
                topology_issues.append(
                    {
                        "mol_id": mol_id,
                        "count": count,
                        "issue": f"Typing/charge assignment failed: {exc.message}",
                        "details": exc.details or {},
                    }
                )
                continue

            # Accumulate artifact bonded overrides for MolTopologyBuilder
            if organic_result is not None and organic_result.bonded_overrides:
                bo = organic_result.bonded_overrides
                for key, val in (bo.get("bond_types") or {}).items():
                    organic_overrides["bond_types"].setdefault(key, {"k": val.k, "r0": val.r0})
                for key, val in (bo.get("angle_types") or {}).items():
                    organic_overrides["angle_types"].setdefault(
                        key, {"k": val.k, "theta0": val.theta0}
                    )
                for key, val in (bo.get("dihedral_types") or {}).items():
                    organic_overrides["dihedral_types"].setdefault(
                        key, {"style": val.style, "coeffs": val.coeffs}
                    )
                for key, val in (bo.get("improper_types") or {}).items():
                    organic_overrides["improper_types"].setdefault(
                        key, {"style": val.style, "coeffs": val.coeffs}
                    )
                for key, val in (bo.get("atom_types") or {}).items():
                    organic_overrides["atom_types"].setdefault(key, val)

        # Tag with mol_strict so MolTopologyBuilder applies the
        # appropriate strict policy. The curated artifact route uses
        # strict=True.
        mol_topologies.append((topology, count, mol_strict))
        logger.info(
            f"Loaded topology for {mol_id}: {topology.n_atoms} atoms, {topology.n_bonds} bonds"
        )

    if topology_issues:
        raise BuildError(
            code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
            message="Topology completeness check failed before system build",
            details={"issues": topology_issues},
        )

    validate_molecule_topologies([(topo, cnt) for topo, cnt, _strict in mol_topologies])

    # Merge organic artifact overrides with inorganic overrides
    # (inorganic takes priority via right-side overwrite)
    merged_bond = {**organic_overrides["bond_types"], **(inorganic_overrides["bond_types"] or {})}
    merged_angle = {
        **organic_overrides["angle_types"],
        **(inorganic_overrides["angle_types"] or {}),
    }
    merged_dihedral = {**organic_overrides["dihedral_types"]}
    merged_improper = {**organic_overrides["improper_types"]}
    # Atom LJ: organic → inorganic (inorganic takes priority)
    merged_atom = {**organic_overrides["atom_types"], **(inorganic_overrides["atom_types"] or {})}

    # Build system topology with GAFF2 parameters + merged overrides
    builder = MolTopologyBuilder(
        ff_name=ff_registry_name,
        strict_param_coverage=typing_charge_settings.strict_param_coverage,
        atom_param_overrides=merged_atom or None,
        bond_param_overrides=merged_bond or None,
        angle_param_overrides=merged_angle or None,
        dihedral_param_overrides=merged_dihedral or None,
        improper_param_overrides=merged_improper or None,
        dihedral_fallback_policy=str(inorganic_overrides.get("dihedral_policy", "strict")),
        inorganic_ff_types=inorganic_overrides["inorganic_ff_types"] or None,
    )

    # Calculate box bounds: prioritize Packmol box for correct density
    if box_dimensions is not None:
        lx, ly, lz = box_dimensions
        box_bounds = (0.0, lx, 0.0, ly, 0.0, lz)
        logger.info(f"Using Packmol box: {lx:.1f} x {ly:.1f} x {lz:.1f} Å")
    elif packed_coords:
        margin = 5.0
        xs = [c[0] for c in packed_coords]
        ys = [c[1] for c in packed_coords]
        zs = [c[2] for c in packed_coords]
        box_bounds = (
            min(xs) - margin,
            max(xs) + margin,
            min(ys) - margin,
            max(ys) + margin,
            min(zs) - margin,
            max(zs) + margin,
        )
        logger.warning("box_dimensions not provided, auto-detecting from atoms")
    else:
        box_bounds = (0, 100, 0, 100, 0, 100)

    try:
        system = builder.create_from_mol_topology(
            mol_topologies,
            packed_coords=packed_coords,
            box_bounds=box_bounds,
            title=f"Asphalt System ({ff_name} {ff_version})",
        )
    except ValueError as exc:
        raise BuildError(
            code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
            message=f"Topology validation failed: {exc}",
        ) from exc

    # Write LAMMPS data file
    ff_builder = FFTopologyBuilder()
    ff_builder.write_lammps_data(system, output_file)

    # Save type_map.json for 3D visualization (type_id -> element)
    _save_type_map(output_file.parent, system.atom_types)

    # Calculate topology hash
    mol_ids = list(mol_counts.keys())
    topo_hash = compute_topology_hash(mol_ids, mol_counts, ff_name, ff_version)

    logger.info(f"Generated LAMMPS data file with full topology: {system.get_counts()}")

    return output_file, topo_hash


def _save_type_map(work_dir: Path, atom_types: list) -> None:
    """Save type ID to element mapping for 3D visualization.

    Creates ``type_map.json`` for dump file XYZ conversion.

    Args:
        work_dir: Working directory to save the file.
        atom_types: List of AtomType objects from topology.
    """
    type_map = {}
    for atom_type in atom_types:
        type_map[str(atom_type.type_id)] = atom_type.element

    type_map_path = work_dir / "type_map.json"
    type_map_path.write_text(json.dumps(type_map, indent=2))
    logger.debug(f"Saved type_map.json with {len(type_map)} types")
