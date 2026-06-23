"""Standalone helpers for single-component full-topology LAMMPS .data generation.

Extracted from StructureBuilder private methods to support lightweight
callers (e.g. interface-molecule cell generation) that operate on a single
MOL file without the full builder orchestration.

SSOT integration
================

These helpers route through the same typing_router + organic_typing_executor
SSOT as StructureBuilder so that:

* organic_curated_artifact promotions affect every code path that consumes
  a single MOL file, not just the main builder.
* ionic species (NaCl, CaCl2, KCl, ...) fail-closed before any assignment.
* blocked_placeholder / inorganic_profile / ionic_profile decisions
  here mirror the build path, with the same human-readable reason
  text the user already sees in submit responses.

Callers pass ``ff_assignment`` and ``additive_def`` so the helper does
not need its own MoleculeDB handle.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from builder.mol_parser import parse_mol_topology
from builder.mol_types import MolTopology

if TYPE_CHECKING:
    from collections.abc import Callable

    from contracts.schemas import MoleculeInfo
from common.logging import get_logger
from config.settings import get_settings
from contracts.errors import BuildError, ErrorCode
from forcefield.organic_typing_executor import (
    OrganicAssignmentError,
    TypingChargeAssignmentError,
    assign_organic,
    normalize_ff_name,
)
from forcefield.topology import MolTopologyBuilder
from forcefield.topology import TopologyBuilder as FFTopologyBuilder
from forcefield.typing_router import (
    TypingRouterDecision,
    TypingStrategy,
    resolve_typing_strategy,
)

logger = get_logger("builder.topology_helpers")


def _decide_strategy(
    mol_id: str,
    additive_def: dict[str, Any] | None,
    ff_assignment: dict[str, Any] | None,
) -> TypingRouterDecision:
    """Wave 2: shared router invocation for the helper functions.

    Returns the :class:`TypingRouterDecision`. Callers branch on
    ``decision.strategy`` to honor BLOCKED / INORGANIC / IONIC routes.
    """
    return resolve_typing_strategy(mol_id, additive_def, ff_assignment)


# ---------------------------------------------------------------------------
# A1 — XYZ coordinate parser
# ---------------------------------------------------------------------------


def parse_xyz_coordinates(xyz_path: Path) -> list[tuple[float, float, float]]:
    """Parse atomic coordinates from an XYZ file.

    Follows the standard XYZ format:
        line 0: atom count
        line 1: comment
        line 2+: element  x  y  z

    Args:
        xyz_path: Path to the XYZ file.

    Returns:
        List of (x, y, z) coordinate tuples.  Returns an empty list when the
        file is missing or the format is unrecognisable.
    """
    coords: list[tuple[float, float, float]] = []

    if not xyz_path.exists():
        return coords

    lines = xyz_path.read_text().strip().split("\n")
    if len(lines) < 3:
        return coords

    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        return coords

    for line in lines[2 : 2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
                coords.append((x, y, z))
            except (ValueError, IndexError):
                continue

    return coords


# ---------------------------------------------------------------------------
# A2 — Topology validation
# ---------------------------------------------------------------------------


def validate_molecule_topologies(mol_topologies: list[tuple[MolTopology, int]]) -> None:
    """Validate bond connectivity, explicit charges, and system neutrality.

    Args:
        mol_topologies: List of (topology, molecule_count) pairs.

    Raises:
        BuildError: When any validation check fails
            (``ErrorCode.TOPOLOGY_GENERATION_FAILED``).
    """
    issues: list[dict[str, str | int | float]] = []
    total_system_charge = 0.0

    for topology, count in mol_topologies:
        if topology.n_atoms > 1 and topology.n_bonds <= 0:
            issues.append(
                {
                    "mol_id": topology.mol_id,
                    "count": count,
                    "issue": "No bond connectivity defined for multi-atom molecule",
                }
            )

        missing_charge_atoms = [
            atom.index for atom in topology.atoms if not getattr(atom, "charge_defined", False)
        ]
        if missing_charge_atoms:
            preview = ",".join(str(idx) for idx in missing_charge_atoms[:10])
            if len(missing_charge_atoms) > 10:
                preview += ",..."
            issues.append(
                {
                    "mol_id": topology.mol_id,
                    "count": count,
                    "issue": f"Missing explicit per-atom charges (atom idx: {preview})",
                }
            )

        mol_charge = sum(atom.charge for atom in topology.atoms)
        total_system_charge += mol_charge * count

    if abs(total_system_charge) > 1e-4:
        issues.append(
            {
                "mol_id": "SYSTEM",
                "count": sum(count for _, count in mol_topologies),
                "issue": f"Non-neutral system charge from molecule set: {total_system_charge:.6f}e",
            }
        )

    if issues:
        raise BuildError(
            code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
            message="Molecule completeness check failed (connectivity/charge)",
            details={"issues": issues},
        )


# ---------------------------------------------------------------------------
# A3 — MOL → XYZ converter
# ---------------------------------------------------------------------------


def convert_mol_to_xyz(
    mol_topology: MolTopology,
    mol_id: str,
    output_path: Path,
) -> Path:
    """Convert a parsed MOL topology to XYZ format for Packmol.

    Packmol only supports XYZ, PDB, and TINKER formats, not MDL Molfile
    (.mol).  This function writes a standard XYZ file from an already-parsed
    ``MolTopology``.

    Args:
        mol_topology: Pre-parsed molecule topology.
        mol_id: Molecule identifier (used in the comment line).
        output_path: Destination XYZ file path.

    Returns:
        The *output_path* for convenience.

    Raises:
        BuildError: If the topology contains no atoms.
    """
    if mol_topology is None or not mol_topology.atoms:
        raise BuildError(
            code=ErrorCode.PACKMOL_FAILED,
            message=f"Failed to convert topology for {mol_id}: no atoms",
            details={"mol_id": mol_id},
        )

    # Write XYZ format (sort by atom index for consistent ordering)
    lines = [str(len(mol_topology.atoms)), f"{mol_id} converted from MOL"]
    for atom in sorted(mol_topology.atoms, key=lambda a: a.index):
        lines.append(f"{atom.element}  {atom.x:.6f}  {atom.y:.6f}  {atom.z:.6f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    logger.debug(f"Converted MOL topology to {output_path.name} ({len(mol_topology.atoms)} atoms)")

    return output_path


# ---------------------------------------------------------------------------
# A3.5 — Generation support probe
# ---------------------------------------------------------------------------


def probe_single_component_generation_support(
    mol_path: Path,
    mol_id: str,
    ff_name: str = "GAFF2",
    *,
    ff_assignment: dict[str, Any] | None = None,
    additive_def: dict[str, Any] | None = None,
    observe_only: bool = False,
) -> tuple[bool, str | None]:
    """Check if a molecule can be processed by the full-topology pipeline.

    Wave 2: routes the decision through the shared typing router so that
    blocked / ionic / inorganic species are reported as unsupported with
    the same user-facing reason the build path emits. Organic molecules
    go through :func:`forcefield.organic_typing_executor.assign_organic`
    so the artifact route is also exercised here.

    Args:
        mol_path: Path to the source ``.mol`` file.
        mol_id: Molecule identifier string.
        ff_name: Force field name (default ``"GAFF2"``).
        ff_assignment: Optional ff_assignment SSOT record from
            :meth:`builder.molecule_db.MoleculeDB.get_ff_assignment`.
            If provided, the router uses it to decide routing.
        additive_def: Optional additive definition (legacy fallback used
            by the router for inorganic profile_id resolution).
        observe_only: When ``True`` (v00.99.72), preview-class callers skip
            every action that may trigger synchronous AM1-BCC generation or
            long-running typing/charge assignment. For the organic curated
            artifact route this probe only verifies that a complete artifact
            already exists on disk; a missing artifact short-circuits to
            ``(False, "artifact not generated …")`` instead of invoking
            ``ensure_organic_artifact``. Build/submit callers keep the
            default ``False`` so the generation contract is unchanged.

    Returns:
        ``(True, None)`` when the molecule is supported, or
        ``(False, reason)`` with a human-readable explanation otherwise.
    """
    topology = parse_mol_topology(mol_path, mol_id)
    if topology is None:
        return (False, f"Failed to parse MOL file for {mol_id}")

    settings = get_settings().typing_charge
    normalized_name = normalize_ff_name(ff_name)

    if settings.enabled:
        decision = _decide_strategy(mol_id, additive_def, ff_assignment)

        if decision.strategy == TypingStrategy.BLOCKED:
            reason = decision.blocked_reason or "Molecule blocked by router"
            if "blocked_placeholder" in reason and "curated artifact" in reason:
                reason = (
                    f"GAFF2 artifact not yet generated for '{mol_id}' "
                    "— run scripts/generate_gaff2_artifact.py"
                )
            return (False, reason)

        if decision.strategy == TypingStrategy.IONIC_PROFILE:
            from forcefield.ionic_executor import IonicNotActivatedError, assign_ionic

            try:
                assign_ionic(
                    topology=topology,
                    profile_id=decision.profile_id or decision.source_id or "",
                    artifact_id=decision.source_id or mol_id,
                    usage_context="vacuum",
                )
            except IonicNotActivatedError as exc:
                return (False, f"Ionic blocked: {str(exc)[:150]}")
            return (True, None)

        if decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            return (
                False,
                f"Inorganic profile route is not supported by the "
                "single-component helper. Use the main StructureBuilder "
                f"path for '{mol_id}'.",
            )

        # Water model route — separate dispatch
        if decision.strategy == TypingStrategy.WATER_MODEL:
            from forcefield.water_executor import WaterAssignmentError, assign_water

            try:
                assign_water(
                    topology=topology,
                    source_id=decision.source_id or mol_id,
                )
            except WaterAssignmentError as exc:
                return (False, f"Water model failed: {exc.message[:150]}")
            return (True, None)

        # Validate artifact exists and is complete (fail-closed policy)
        if decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
            if observe_only:
                # v00.99.72: preview class — never trigger AM1-BCC. Report
                # artifact readiness based on on-disk state only. A missing
                # or incomplete artifact is reported as "not generated";
                # the operator generates it explicitly via the FF
                # Parameters page, not via an incidental preview click.
                from features.molecules.artifact_runtime import is_artifact_ready

                ready, _source_id = is_artifact_ready(
                    mol_id=mol_id,
                    ff_assignment=ff_assignment or {},
                    ff_family="organic_gaff2",
                )
                if not ready:
                    return (
                        False,
                        f"Artifact not generated for '{mol_id}'. "
                        "Generate via the Molecules catalog (/molecules) — "
                        "legacy endpoint POST /artifacts/generate/{mol_id} "
                        "also available for operator clients.",
                    )
                # Ready on disk — observe_only callers treat this as
                # supported without running assign_organic (which would
                # re-exercise typing/charge and may be expensive for
                # large molecules). Build/submit callers keep the full
                # validation by using observe_only=False.
                return (True, None)

            from features.molecules.artifact_runtime import ensure_organic_artifact
            from forcefield.organic_curated_artifact import (
                ArtifactIncompleteError,
                ArtifactMissingError,
            )

            try:
                source_id = ensure_organic_artifact(
                    mol_id=mol_id,
                    mol_path=mol_path,
                    ff_assignment=ff_assignment or {},
                    ff_family="organic_gaff2",
                )
            except ArtifactMissingError as exc:
                return (
                    False,
                    f"Artifact not found for '{mol_id}': {str(exc)[:150]}. "
                    "Generate via the Molecules catalog (/molecules) — "
                    "legacy endpoint POST /artifacts/generate/{mol_id} also available.",
                )
            except ArtifactIncompleteError as exc:
                return (
                    False,
                    f"Artifact incomplete for '{mol_id}': {str(exc)[:150]}. "
                    "Regenerate artifact with LJ parameters.",
                )
            except Exception as exc:
                return (False, f"Artifact validation failed for '{mol_id}': {str(exc)[:150]}")
            if decision.source_id != source_id:
                decision = TypingRouterDecision(
                    strategy=decision.strategy,
                    source_id=source_id,
                    status=decision.status,
                )

        # Organic routes (curated artifact) → executor
        try:
            assign_organic(
                topology=topology,
                mol_file=mol_path,
                strategy=decision.strategy,
                source_id=decision.source_id,
                ff_family="organic_gaff2",
                ff_name=normalized_name,
                charge_model_primary=settings.charge_model_primary,
                charge_model_fallback=settings.charge_model_fallback,
                total_charge_tolerance=settings.total_charge_tolerance,
            )
        except OrganicAssignmentError as exc:
            return (False, f"Organic typing/charge failed: {exc.message[:150]}")
        except TypingChargeAssignmentError as exc:
            return (False, f"Typing/charge failed: {exc.message[:150]}")
        except Exception as exc:
            return (False, f"Typing/charge error: {str(exc)[:150]}")

    try:
        validate_molecule_topologies([(topology, 1)])
    except BuildError as exc:
        return (False, f"Topology validation failed: {exc.message[:150]}")

    return (True, None)


# ---------------------------------------------------------------------------
# A4 — Single-component full-topology pipeline
# ---------------------------------------------------------------------------


def generate_single_component_topology(
    mol_path: Path,
    mol_id: str,
    molecule_count: int,
    packed_xyz_path: Path,
    output_data_path: Path,
    box_dimensions: tuple[float, float, float],
    ff_name: str = "GAFF2",
    *,
    ff_assignment: dict[str, Any] | None = None,
    additive_def: dict[str, Any] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
) -> Path:
    """Generate a full-topology LAMMPS .data file for a single molecule type.

    Pipeline:
        1. Parse MOL file → ``MolTopology``
        2. Resolve typing strategy via the shared SSOT router
        3. Apply curated GAFF2 artifact via the organic_typing_executor
        4. Validate connectivity, charges, neutrality
        5. Parse packed XYZ coordinates
        6. Build system topology with FF parameters
           (Wave 1 strict policy is applied for curated artifact route)
        7. Write LAMMPS data file

    Wave 2: blocked / ionic / inorganic species fail-closed at step 2.
    Organic routes (legacy + curated artifact) flow through
    :func:`forcefield.organic_typing_executor.assign_organic`.

    Args:
        mol_path: Path to the source ``.mol`` file.
        mol_id: Molecule identifier string.
        molecule_count: Number of molecules packed by Packmol.
        packed_xyz_path: Path to Packmol output XYZ file.
        output_data_path: Destination path for the LAMMPS ``.data`` file.
        box_dimensions: ``(lx, ly, lz)`` box edge lengths in angstroms.
        ff_name: Force field name (default ``"GAFF2"``).
        ff_assignment: Optional ff_assignment SSOT record. When provided,
            the router uses it to decide routing.
        additive_def: Optional additive definition (legacy fallback for
            the router's profile_id resolution).

    Returns:
        The *output_data_path* on success.

    Raises:
        BuildError: On any topology generation failure
            (``ErrorCode.TOPOLOGY_GENERATION_FAILED``).
    """
    # --- 1. Parse MOL topology ---
    topology = parse_mol_topology(mol_path, mol_id)
    if topology is None:
        raise BuildError(
            code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
            message=f"Failed to parse MOL topology for {mol_id}",
            details={"mol_path": str(mol_path)},
        )

    # --- 2. Typing / charge assignment via SSOT router + executor ---
    settings = get_settings().typing_charge
    normalized_name = normalize_ff_name(ff_name)

    mol_strict = False
    if settings.enabled:
        decision = _decide_strategy(mol_id, additive_def, ff_assignment)

        if decision.strategy == TypingStrategy.BLOCKED:
            raise BuildError(
                code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                message=(
                    decision.blocked_reason
                    or f"Molecule '{mol_id}' is blocked by the typing router."
                ),
                details={"mol_id": mol_id, "stage": "typing_router"},
            )

        if decision.strategy == TypingStrategy.IONIC_PROFILE:
            from forcefield.ionic_executor import IonicNotActivatedError, assign_ionic

            try:
                ionic_result = assign_ionic(
                    topology=topology,
                    profile_id=decision.profile_id or decision.source_id or "",
                    artifact_id=decision.source_id or mol_id,
                    usage_context="vacuum",
                )
            except IonicNotActivatedError as exc:
                raise BuildError(
                    code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                    message=f"Ionic assignment blocked for {mol_id}: {exc}",
                    details={"mol_id": mol_id, "stage": "ionic_executor"},
                ) from exc
            # Ionic result uses same override structure as organic
            organic_result = type(
                "_IonicShim",
                (),
                {"bonded_overrides": ionic_result.bonded_overrides},
            )()

        elif decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            raise BuildError(
                code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                message=(
                    f"Inorganic profile route is not supported by the "
                    "single-component topology helper; use the main "
                    f"StructureBuilder path for '{mol_id}'."
                ),
                details={"mol_id": mol_id, "stage": "typing_router"},
            )

        # Water model dispatch — separate from organic
        if decision.strategy == TypingStrategy.WATER_MODEL:
            from forcefield.water_executor import WaterAssignmentError, assign_water

            try:
                water_result = assign_water(
                    topology=topology,
                    source_id=decision.source_id or mol_id,
                )
            except WaterAssignmentError as exc:
                raise BuildError(
                    code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                    message=f"Water model assignment failed for {mol_id}: {exc.message}",
                    details={"mol_id": mol_id, **(exc.details or {})},
                ) from exc
            # Water result uses same override structure as organic
            organic_result = type(
                "_WaterShim",
                (),
                {
                    "bonded_overrides": water_result.bonded_overrides,
                },
            )()
        else:
            # Validate artifact exists and is complete (fail-closed policy)
            if decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
                from features.molecules.artifact_runtime import ensure_organic_artifact
                from forcefield.organic_curated_artifact import (
                    ArtifactIncompleteError,
                    ArtifactMissingError,
                )

                try:
                    _source_id = ensure_organic_artifact(
                        mol_id=mol_id,
                        mol_path=mol_path,
                        ff_assignment=ff_assignment or {},
                        ff_family="organic_gaff2",
                        progress_callback=progress_callback,
                    )
                except ArtifactMissingError as exc:
                    raise BuildError(
                        code=ErrorCode.ARTIFACT_MISSING,
                        message=f"Build blocked: artifact not found for '{mol_id}'. "
                        "Generate via the Molecules catalog (/molecules) — "
                        "legacy endpoint POST /artifacts/generate/{mol_id} also available.",
                        details={"mol_id": mol_id, "original_error": str(exc)[:200]},
                    ) from exc
                except ArtifactIncompleteError as exc:
                    raise BuildError(
                        code=ErrorCode.ARTIFACT_INCOMPLETE,
                        message=f"Build blocked: artifact incomplete for '{mol_id}'. "
                        "Regenerate artifact with LJ parameters.",
                        details={"mol_id": mol_id, "original_error": str(exc)[:200]},
                    ) from exc

                if decision.source_id != _source_id:
                    decision = TypingRouterDecision(
                        strategy=decision.strategy,
                        source_id=_source_id,
                        status=decision.status,
                    )

            # Organic dispatch
            organic_result = None
            try:
                organic_result = assign_organic(
                    topology=topology,
                    mol_file=mol_path,
                    strategy=decision.strategy,
                    source_id=decision.source_id,
                    ff_family="organic_gaff2",
                    ff_name=normalized_name,
                    charge_model_primary=settings.charge_model_primary,
                    charge_model_fallback=settings.charge_model_fallback,
                    total_charge_tolerance=settings.total_charge_tolerance,
                )
            except OrganicAssignmentError as exc:
                raise BuildError(
                    code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                    message=f"Organic typing/charge assignment failed for {mol_id}: {exc.message}",
                    details={"mol_id": mol_id, **(exc.details or {})},
                ) from exc
            except TypingChargeAssignmentError as exc:
                # Defensive: legacy assigner can still raise its own type if a
                # subclass test path bypasses the executor.
                raise BuildError(
                    code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                    message=f"Typing/charge assignment failed for {mol_id}: {exc.message}",
                    details={"mol_id": mol_id, **(exc.details or {})},
                ) from exc

        # Wave 1/2 strict policy: curated artifact / water model route is strict.
        mol_strict = decision.strategy in (
            TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            TypingStrategy.WATER_MODEL,
        )

    # --- 3. Validate topology ---
    validate_molecule_topologies([(topology, molecule_count)])

    # --- 4. Parse packed XYZ coordinates ---
    coords = parse_xyz_coordinates(packed_xyz_path)

    expected_atoms = molecule_count * len(topology.atoms)
    if coords and len(coords) != expected_atoms:
        logger.warning(
            f"Atom count mismatch: packed XYZ has {len(coords)} atoms, "
            f"expected {expected_atoms} ({molecule_count} × {len(topology.atoms)})"
        )

    # --- 5. Build system topology ---
    # Extract artifact bonded overrides for MolTopologyBuilder
    artifact_bond_overrides: dict[str, dict[str, Any]] = {}
    artifact_angle_overrides: dict[str, dict[str, Any]] = {}
    artifact_dihedral_overrides: dict[str, dict[str, Any]] = {}
    artifact_atom_overrides: dict[str, dict[str, Any]] = {}
    if organic_result is not None and organic_result.bonded_overrides:
        bo = organic_result.bonded_overrides
        for key, val in (bo.get("bond_types") or {}).items():
            artifact_bond_overrides[key] = {"k": val.k, "r0": val.r0}
        for key, val in (bo.get("angle_types") or {}).items():
            artifact_angle_overrides[key] = {"k": val.k, "theta0": val.theta0}
        for key, val in (bo.get("dihedral_types") or {}).items():
            artifact_dihedral_overrides[key] = {"style": val.style, "coeffs": val.coeffs}
        for key, val in (bo.get("atom_types") or {}).items():
            artifact_atom_overrides[key] = val

    lx, ly, lz = box_dimensions
    builder = MolTopologyBuilder(
        ff_name=normalized_name,
        strict_param_coverage=settings.strict_param_coverage,
        atom_param_overrides=artifact_atom_overrides or None,
        bond_param_overrides=artifact_bond_overrides or None,
        angle_param_overrides=artifact_angle_overrides or None,
        dihedral_param_overrides=artifact_dihedral_overrides or None,
    )

    try:
        # Wave 1: pass mol_strict via the 3-tuple form so the curated
        # artifact route's strict bonded coverage flows through here too.
        system = builder.create_from_mol_topology(
            [(topology, molecule_count, mol_strict)],
            packed_coords=coords,
            box_bounds=(0.0, lx, 0.0, ly, 0.0, lz),
        )
    except ValueError as exc:
        raise BuildError(
            code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
            message=f"Topology build failed for {mol_id}: {exc}",
            details={"mol_id": mol_id},
        ) from exc

    # --- 6. Write LAMMPS data file ---
    output_data_path.parent.mkdir(parents=True, exist_ok=True)
    ff_builder = FFTopologyBuilder()
    ff_builder.write_lammps_data(system, output_data_path)

    logger.info(
        f"Generated single-component LAMMPS data: {mol_id} x{molecule_count} → {output_data_path.name}"
    )

    return output_data_path


# ---------------------------------------------------------------------------
# A5 — MOL file finder
# ---------------------------------------------------------------------------


def find_mol_file(
    structure_file: Path,
    mol_id: str = "",
    molecule_db: Any = None,
) -> Path | None:
    """Find corresponding MOL file for a structure file.

    This is a standalone version of the former
    ``StructureBuilder._find_mol_file`` method.

    Args:
        structure_file: Path to structure file (XYZ, PDB, etc.).
        mol_id: Molecule ID for aging library lookup.
        molecule_db: Optional :class:`MoleculeDB` instance for aging
            library lookup.

    Returns:
        Path to MOL file or ``None`` if not found.
    """
    # If structure file is already MOL
    if structure_file.suffix.lower() == ".mol":
        return structure_file

    # Try same directory with .mol extension
    mol_file = structure_file.with_suffix(".mol")
    if mol_file.exists():
        return mol_file

    # Try aging library lookup
    if mol_id and molecule_db is not None and hasattr(molecule_db, "_aging_config_path"):
        config_path = molecule_db._aging_config_path
        if config_path:
            aging_mol: Path | None = molecule_db.get_structure_file_aging(mol_id, config_path)
            if aging_mol and aging_mol.exists():
                return aging_mol

    # Try common patterns in same directory
    parent = structure_file.parent
    stem = structure_file.stem

    for pattern in [f"{stem}.mol", f"{stem}_Mol.mol", f"*{stem}*.mol"]:
        matches = list(parent.glob(pattern))
        if matches:
            return matches[0]

    return None


# ---------------------------------------------------------------------------
# A6 — XYZ topology creator
# ---------------------------------------------------------------------------


def create_xyz_topology(
    structure_file: Path,
    mol_id: str,
) -> MolTopology:
    """Create basic topology from XYZ file (no bonds).

    This is a standalone version of the former
    ``StructureBuilder._create_xyz_topology`` method.

    Args:
        structure_file: Path to an XYZ structure file.
        mol_id: Molecule identifier.

    Returns:
        A :class:`MolTopology` with atoms but no bonds.
    """
    from common.constants import ATOMIC_WEIGHTS

    from .mol_types import MolAtom

    atoms: list[MolAtom] = []
    if structure_file.exists():
        lines = structure_file.read_text().strip().split("\n")
        if len(lines) >= 3:
            try:
                n_atoms = int(lines[0].strip())
                for i, line in enumerate(lines[2 : 2 + n_atoms]):
                    parts = line.split()
                    if len(parts) >= 4:
                        atoms.append(
                            MolAtom(
                                index=i + 1,
                                x=float(parts[1]),
                                y=float(parts[2]),
                                z=float(parts[3]),
                                element=parts[0],
                            )
                        )
            except (ValueError, IndexError):
                pass

    return MolTopology(
        mol_id=mol_id,
        atoms=atoms,
        bonds=[],  # No bond information from XYZ
        molecular_weight=sum(ATOMIC_WEIGHTS.get(a.element, 12.0) for a in atoms),
    )


# ---------------------------------------------------------------------------
# A7 — Mock structure / molecule creation
# ---------------------------------------------------------------------------


def create_mock_structure(
    mol_id: str,
    atom_count: int,
    output_file: Path,
) -> Path:
    """Create a mock XYZ structure file for testing.

    This is a standalone version of the former
    ``StructureBuilder._create_mock_structure`` method.

    Args:
        mol_id: Molecule identifier (used in the comment line).
        atom_count: Number of atoms to generate.
        output_file: Destination XYZ file path.

    Returns:
        The *output_file* path.
    """
    import random

    lines = [str(atom_count), f"{mol_id} mock structure"]

    for _i in range(atom_count):
        x = random.uniform(-5, 5)
        y = random.uniform(-5, 5)
        z = random.uniform(-5, 5)
        lines.append(f"C {x:.6f} {y:.6f} {z:.6f}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines))

    return output_file


def create_mock_molecule(category_name: str) -> MoleculeInfo:
    """Create a mock :class:`MoleculeInfo` for testing.

    This is a standalone version of the former
    ``StructureBuilder._create_mock_molecule`` method.

    Args:
        category_name: SARA category name.

    Returns:
        A :class:`MoleculeInfo` with default values for the category.
    """
    from contracts.schemas import MoleculeCategory, MoleculeInfo

    defaults = {
        "asphaltene": (280.0, 42, MoleculeCategory.ASPHALTENE),
        "resin": (180.0, 28, MoleculeCategory.RESIN),
        "aromatic": (130.0, 18, MoleculeCategory.AROMATIC),
        "saturate": (230.0, 50, MoleculeCategory.SATURATE),
        "additive": (200.0, 30, MoleculeCategory.ADDITIVE),
    }

    mw, atoms, cat = defaults.get(category_name, (200.0, 30, MoleculeCategory.ADDITIVE))

    return MoleculeInfo(
        mol_id=f"mock_{category_name}",
        molecular_weight=mw,
        atom_count=atoms,
        category=cat,
    )
