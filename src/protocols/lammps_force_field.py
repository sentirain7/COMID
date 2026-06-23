"""
LAMMPS force field and neighbor setting generators.

Standalone functions extracted from LAMMPSInputGenerator for generating
force field setup, pair coefficients, neighbor settings, crystal groups,
and group energy commands.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.schemas import GroupEnergySpec, StudyType

if TYPE_CHECKING:
    from protocols.protocol_chain import ProtocolChain

logger = get_logger("protocols.lammps_force_field")


# ---------------------------------------------------------------------------
# Method 1a — Adaptive cutoff vacuum (CED method redesign v3+, PR 2 v4)
# ---------------------------------------------------------------------------
#
# Numeric values live in ``contracts.policies.forcefield`` as the SSOT
# (``DEFAULT_VACUUM_EXTENDED_CUTOFF_POLICY``).  The module-level constants
# below are mirrors maintained for backward compatibility with existing
# callers and unit tests; they MUST stay in sync with the policy.

from contracts.policies.forcefield import (  # noqa: E402
    DEFAULT_VACUUM_EXTENDED_CUTOFF_POLICY as _VAC_POLICY,
)

VACUUM_DEFAULT_CUTOFF_A = _VAC_POLICY.legacy_default_cutoff_a
VACUUM_EXTENDED_MIN_CUTOFF_A = _VAC_POLICY.min_cutoff_a
VACUUM_EXTENDED_EXTENT_MULTIPLIER = _VAC_POLICY.extent_multiplier


def compute_max_pairwise_distance_from_data_file(data_file_path: str) -> float:
    """Read atom coordinates from a LAMMPS data file and return max pairwise distance (Å).

    Returns 0.0 if the file cannot be parsed or contains < 2 atoms.  Tolerates
    non-UTF8 bytes via ``errors="replace"`` so user-provided data files with
    legacy encodings do not abort Method 1a tagging.

    Args:
        data_file_path: Path to LAMMPS data file (Atoms section in 'full' style).
    """
    if not data_file_path:
        return 0.0
    p = Path(data_file_path)
    if not p.is_file():
        return 0.0
    coords: list[tuple[float, float, float]] = []
    in_atoms = False
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                if in_atoms and coords:
                    break
                continue
            if line.startswith("Atoms"):
                in_atoms = True
                continue
            if in_atoms:
                if line[0].isalpha():
                    break
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        coords.append((float(parts[4]), float(parts[5]), float(parts[6])))
                    except ValueError:
                        continue
    except OSError:
        return 0.0
    n = len(coords)
    if n < 2:
        return 0.0
    max_d2 = 0.0
    for i in range(n):
        xi, yi, zi = coords[i]
        for j in range(i + 1, n):
            xj, yj, zj = coords[j]
            d2 = (xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2
            if d2 > max_d2:
                max_d2 = d2
    return math.sqrt(max_d2)


def resolve_vacuum_cutoff(
    data_file_path: str | None,
    *,
    extended: bool,
    min_cutoff: float = VACUUM_EXTENDED_MIN_CUTOFF_A,
    extent_multiplier: float = VACUUM_EXTENDED_EXTENT_MULTIPLIER,
    default_cutoff: float = VACUUM_DEFAULT_CUTOFF_A,
) -> tuple[float, str]:
    """Resolve the vacuum LJ/Coulomb cutoff for SINGLE_MOLECULE_VACUUM jobs.

    Method 1a (adaptive cutoff) yields cutoff = max(min_cutoff, multiplier * max_pairwise_distance).
    Falls back to legacy ``default_cutoff`` (12 Å) when ``extended`` is False or extent is unknown.

    Returns a tuple ``(cutoff_A, method_tag)`` where method_tag is one of
    ``single_molecule_vacuum`` or ``single_molecule_vacuum_adaptive_cutoff``.
    """
    if not extended:
        return default_cutoff, "single_molecule_vacuum"
    extent = compute_max_pairwise_distance_from_data_file(data_file_path or "")
    if extent <= 0.0:
        logger.warning(
            "vacuum_extended_cutoff: failed to derive molecular extent from %s — falling back to default %.1f Å",
            data_file_path,
            default_cutoff,
        )
        return default_cutoff, "single_molecule_vacuum"
    cutoff = max(min_cutoff, extent_multiplier * extent)
    return cutoff, "single_molecule_vacuum_adaptive_cutoff"


def vacuum_extended_cutoff_enabled() -> bool:
    """Method 1a opt-in flag (env var ASPHALT_VACUUM_EXTENDED_CUTOFF=1)."""
    return os.environ.get("ASPHALT_VACUUM_EXTENDED_CUTOFF", "0").strip() in {"1", "true", "True"}


# ---------------------------------------------------------------------------
# Force field dispatch
# ---------------------------------------------------------------------------


def generate_force_field(
    chain: ProtocolChain,
    *,
    has_charges: bool = True,
    has_bonds: bool = True,
) -> str:
    """Generate force field setup from ForceFieldConfig runtime profile.

    Dispatches to ``generate_organic_ff`` (GAFF2) or
    ``generate_reaxff`` based on ``chain.ff_type``.  All organic FF
    parameters are read from the ``ForceFieldConfig`` registry at
    ``contracts.policies.forcefield`` -- nothing is hardcoded here.

    For SINGLE_MOLECULE_VACUUM jobs, the protocol's resolved
    ``chain.e_intra_method`` wins. If the chain does not carry one, the
    conservative baseline Method 1 is used with a warning.
    """
    from contracts.schemas import FFType

    ff = chain.ff_type

    vacuum_cutoff: float | None = None
    method_tag = getattr(chain, "e_intra_method", None)
    if chain.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
        if not method_tag:
            logger.warning(
                "ProtocolChain.e_intra_method missing for SINGLE_MOLECULE_VACUUM; "
                "falling back to single_molecule_vacuum"
            )
            method_tag = "single_molecule_vacuum"
        if method_tag == "single_molecule_vacuum_adaptive_cutoff":
            vacuum_cutoff, method_tag = resolve_vacuum_cutoff(
                getattr(chain, "data_file_path", None), extended=True
            )
            logger.info(
                "vacuum_adaptive_cutoff (Method 1a): cutoff=%.2f Å, method=%s",
                vacuum_cutoff,
                method_tag,
            )
        elif method_tag == "single_molecule_periodic":
            vacuum_cutoff = None
        else:
            if method_tag not in (None, "single_molecule_vacuum"):
                logger.warning(
                    "Unsupported SINGLE_MOLECULE_VACUUM e_intra_method=%s; "
                    "falling back to single_molecule_vacuum",
                    method_tag,
                )
            vacuum_cutoff = VACUUM_DEFAULT_CUTOFF_A
            method_tag = "single_molecule_vacuum"
        # PR 2 SSOT: persist the decision on the chain so downstream code
        # (pipeline._attach_ced_lookup_metadata) reads the same values.
        chain.e_intra_method = method_tag
        chain.vacuum_cutoff_a = vacuum_cutoff

    if ff == FFType.BULK_FF_GAFF2:
        return generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=has_charges,
            has_bonds=has_bonds,
            study_type=chain.study_type,
            vacuum_cutoff=vacuum_cutoff,
            e_intra_method=method_tag,
        )
    elif ff == FFType.REAXFF:
        return generate_reaxff()
    else:
        logger.warning(f"Unknown ff_type {ff!r}, falling back to GAFF2")
        return generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=has_charges,
            has_bonds=has_bonds,
            study_type=chain.study_type,
            vacuum_cutoff=vacuum_cutoff,
            e_intra_method=method_tag,
        )


# ---------------------------------------------------------------------------
# Organic FF (GAFF2 / OPLS-AA)
# ---------------------------------------------------------------------------


def generate_organic_ff(
    ff_config_key: str,
    has_charges: bool = True,
    has_bonds: bool = True,
    study_type: StudyType = StudyType.BULK,
    vacuum_cutoff: float | None = None,
    e_intra_method: str | None = None,
) -> str:
    """Generate organic FF setup from ForceFieldConfig runtime profile.

    Reads dihedral_style, improper_style, special_bonds, mixing rule,
    and kspace_style from the SSOT registry instead of hardcoding.

    For layered structures (LAYER_BULKFF), forces arithmetic (L-B) mixing
    to be compatible with INTERFACE FF mineral parameters, regardless of
    the FF's native mixing rule.

    For SINGLE_MOLECULE_VACUUM, ``vacuum_cutoff`` (Å) overrides the legacy
    12 Å cutoff.  Pass an explicit value (e.g. ``max(50, 2×extent)``) to
    activate Method 1a (adaptive cutoff) so all intramolecular Coulomb is
    captured by direct summation.  When ``None`` (default), legacy 12 Å is
    used (Method 1 baseline).

    Args:
        ff_config_key: Registry key (e.g., ``"opls-aa"`` or ``"bulk_ff_gaff2"``).
        has_charges: Whether system has partial charges.
        has_bonds: Whether system has bonded interactions.
        study_type: Study type for boundary/kspace/mixing settings.
        vacuum_cutoff: Override LJ/Coulomb cutoff (Å) for vacuum study type.
        e_intra_method: Resolved E_intra method tag for single-molecule jobs.

    Returns:
        LAMMPS force field commands as a string.
    """
    from contracts.policies.forcefield import get_default_ff_registry

    registry = get_default_ff_registry()
    config = registry.get(ff_config_key)

    if config is None:
        logger.warning(f"FF config {ff_config_key!r} not found in registry, using GAFF2 defaults")
        config = registry.get("bulk_ff_gaff2")

    # Study type flags
    is_layered = study_type == StudyType.LAYER_BULKFF
    is_periodic_single_molecule = (
        study_type == StudyType.SINGLE_MOLECULE_VACUUM
        and e_intra_method == "single_molecule_periodic"
    )
    is_vacuum = study_type == StudyType.SINGLE_MOLECULE_VACUUM and not is_periodic_single_molecule

    # Read from config (with safe defaults matching GAFF2)
    display = (config.display_label or config.name) if config else "GAFF2"
    native_mix = (config.native_mixing_rule or "arithmetic") if config else "arithmetic"
    dih_style = (config.dihedral_style or "fourier") if config else "fourier"
    imp_style = (config.improper_style or "cvff") if config else "cvff"
    kspace = (config.kspace_style or "pppm 1.0e-4") if config else "pppm 1.0e-4"

    # Layered structures always use arithmetic (L-B) for INTERFACE FF compat
    mix_rule = "arithmetic" if is_layered else native_mix

    # Method 1a: vacuum cutoff override (defaults to legacy 12 Å baseline)
    vac_cut = float(vacuum_cutoff) if vacuum_cutoff is not None else VACUUM_DEFAULT_CUTOFF_A

    if has_charges:
        if is_vacuum:
            if vacuum_cutoff is not None and vac_cut > VACUUM_DEFAULT_CUTOFF_A:
                ff_label = (
                    f"{display} vacuum adaptive cutoff={vac_cut:.1f} Å (Method 1a, no kspace)"
                )
            else:
                ff_label = f"{display} vacuum (no kspace)"
        elif is_layered:
            ff_label = f"{display} + INTERFACE FF, L-B mixing"
        else:
            ff_label = f"{display} with charges"

        # Vacuum: shrink-wrapped boundary -> no PPPM, use short-range Coulomb
        pair_style = f"lj/cut/coul/cut {vac_cut}" if is_vacuum else "lj/cut/coul/long 12.0"
        lines = [
            f"# Force field settings ({ff_label})",
            f"pair_style {pair_style}",
            f"pair_modify mix {mix_rule}",
        ]
        if has_bonds:
            lines.extend(
                [
                    "bond_style harmonic",
                    "angle_style harmonic",
                    f"dihedral_style {dih_style}",
                    f"improper_style {imp_style}",
                ]
            )
        if not is_vacuum:
            lines.append(f"kspace_style {kspace}")
        if is_layered:
            lines.append("kspace_modify slab 3.0")

        # Special bonds from config's typed arrays (preferred)
        if config and config.special_bonds_lj and config.special_bonds_coul:
            lj = " ".join(f"{x}" for x in config.special_bonds_lj)
            coul = " ".join(f"{x}" for x in config.special_bonds_coul)
            lines.append(f"special_bonds lj {lj} coul {coul}")
        elif config and config.special_bonds:
            lines.append(f"special_bonds {config.special_bonds}")
        else:
            # Ultimate fallback (GAFF2 defaults)
            lines.append("special_bonds lj 0.0 0.0 0.5 coul 0.0 0.0 0.8333")
        lines.append("")
    else:
        ff_label = (
            f"{display} + INTERFACE FF, L-B mixing" if is_layered else f"{display} without charges"
        )
        nocharge_pair_style = f"lj/cut {vac_cut}" if is_vacuum else "lj/cut 12.0"
        lines = [
            f"# Force field settings ({ff_label})",
            f"pair_style {nocharge_pair_style}",
            f"pair_modify mix {mix_rule}",
        ]
        if has_bonds:
            lines.extend(
                [
                    "bond_style harmonic",
                    "angle_style harmonic",
                    f"dihedral_style {dih_style}",
                    f"improper_style {imp_style}",
                ]
            )
            # No-charge systems: only LJ special bonds
            if config and config.special_bonds_lj:
                lj = " ".join(f"{x}" for x in config.special_bonds_lj)
                lines.append(f"special_bonds lj {lj}")
            else:
                lines.append("special_bonds lj 0.0 0.0 0.5")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ReaxFF
# ---------------------------------------------------------------------------


def generate_reaxff() -> str:
    """Generate ReaxFF force field setup."""
    lines = [
        "# Force field settings (ReaxFF)",
        "pair_style reax/c NULL",
        "pair_coeff * * ffield.reax C H O N S",
        "fix qeq all qeq/reax 1 0.0 10.0 1e-6 reax/c",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pair coefficients
# ---------------------------------------------------------------------------


def generate_pair_coeffs(chain: ProtocolChain, *, coeffs_in_data: bool = True) -> str:
    """Generate pair coefficients for all atom types.

    Note: When using data files generated by MolTopologyBuilder,
    pair coefficients are already included in the data file.
    This generates a fallback for compatibility with mock/test data.
    """
    if coeffs_in_data:
        lines = [
            "# Pair coefficients read from data file",
            "",
        ]
    else:
        lines = [
            "# Pair coefficients (generic LJ fallback for mock data)",
            "pair_coeff * * 0.066 3.5",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Package commands (KOKKOS)
# ---------------------------------------------------------------------------


def generate_package_commands(opt_profile: dict | None) -> str:
    """Generate package commands (must be before read_data in LAMMPS 2025).

    LAMMPS 2025 requires package commands to be called before the simulation
    box is defined (i.e., before read_data or create_box).
    """
    if opt_profile is None:
        return ""

    pkg_cmd = opt_profile.get("package_kokkos")
    if not pkg_cmd:
        return ""

    return f"# KOKKOS package settings (before box definition)\n{pkg_cmd}\n"


# ---------------------------------------------------------------------------
# Neighbor settings
# ---------------------------------------------------------------------------


def generate_neighbor_settings(opt_profile: dict | None) -> str:
    """Generate neighbor list settings.

    Relaxes neighbor rebuild frequency (safe for slow-diffusing
    asphalt polymers, ``check yes`` ensures correctness).

    Note: package kokkos command is now in generate_package_commands()
    to comply with LAMMPS 2025 requirement (must be before read_data).
    """
    lines = ["# Neighbor settings"]

    lines.append("neighbor 2.0 bin")

    if opt_profile is not None:
        delay = opt_profile.get("neigh_delay", 10)
        every = opt_profile.get("neigh_every", 5)
        check = "yes" if opt_profile.get("neigh_check", True) else "no"
        lines.append(f"neigh_modify delay {delay} every {every} check {check}")
    else:
        lines.append("neigh_modify delay 5 every 1 check yes")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Crystal groups / freeze
# ---------------------------------------------------------------------------


def has_crystal_freeze(
    chain: ProtocolChain,
    crystal_type_ids: set[int],
) -> bool:
    """Check if crystal freeze/restraint commands should be generated."""
    return chain.study_type == StudyType.LAYER_BULKFF and bool(crystal_type_ids)


def generate_crystal_groups(
    chain: ProtocolChain,
    crystal_type_ids: set[int],
) -> str:
    """Generate crystal group + spring/self restraint for layered structures.

    Phase 1 (header): soft harmonic restraint applies tether forces during
    minimize and preserves reference positions; crystal is effectively frozen
    during dynamics (no integrator), organic alone receives time integration.
    The rigid freeze is applied later (pre_tensile_nvt) for tensile prep.

    Returns:
        LAMMPS commands string, or empty string if not applicable.
    """
    if not has_crystal_freeze(chain, crystal_type_ids):
        return ""
    type_list = " ".join(str(t) for t in sorted(crystal_type_ids))
    lines = [
        "# Crystal restraint groups (layered structure)",
        f"group crystal type {type_list}",
        "group organic subtract all crystal",
        "# Soft restraint — tether force active during minimize; crystal effectively frozen during dynamics (no integrator)",
        "fix restrain_crystal crystal spring/self 50.0",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Group energy decomposition
# ---------------------------------------------------------------------------


def generate_group_energy_commands(
    spec: GroupEnergySpec,
    *,
    include_kspace: bool = False,
) -> str:
    """Generate LAMMPS group/group energy decomposition commands.

    Uses Python string generation (not j2 template) per feedback #5.
    Supports both v1 (molecule-ID groups) and v2 (GroupSelector) patterns.

    Args:
        spec: GroupEnergySpec with group definitions and pairs.
        include_kspace: If True, add 'kspace yes' for CPU-only non-KOKKOS mode.
            KOKKOS pppm/kk does not support compute group/group with kspace yes,
            so this should only be enabled for CPU rerun scripts.

    Returns:
        LAMMPS command string for group definitions and compute group/group.
    """
    lines = ["# Group-based energy decomposition (Phase 4.2)"]

    if spec.group_selectors:
        # v2: use GroupSelector
        for name, sel in sorted(spec.group_selectors.items()):
            if sel.mode == "molecule":
                id_str = " ".join(str(m) for m in (sel.ids or []))
                lines.append(f"group {name} molecule {id_str}")
            elif sel.mode == "atom_id_range":
                lines.append(f"group {name} id {sel.range_start}:{sel.range_end}")
            elif sel.mode == "atom_id_list":
                id_str = " ".join(str(m) for m in (sel.ids or []))
                lines.append(f"group {name} id {id_str}")
    else:
        # v1: use groups dict (backward compat)
        for group_name, mol_ids in sorted(spec.groups.items()):
            mol_id_str = " ".join(str(m) for m in mol_ids)
            lines.append(f"group {group_name} molecule {mol_id_str}")

    lines.append("")
    # Note: kspace option omitted by default for KOKKOS compatibility.
    # KOKKOS pppm/kk does not support compute group/group with kspace yes.
    # Short-range LJ + direct Coulomb (within cutoff) are still computed.
    # For high-precision long-range Coulomb contribution, use CPU rerun mode
    # with include_kspace=True.
    kspace_opt = " kspace yes" if include_kspace else ""
    for pair in spec.pairs:
        lines.append(
            f"compute gg_{pair.label} {pair.group_a} group/group {pair.group_b}{kspace_opt}"
        )
    return "\n".join(lines)


def generate_layer_pe_commands(spec: GroupEnergySpec) -> str:
    """Generate per-layer total potential-energy commands for layered profiles.

    Uses ``compute pe/atom`` plus per-group ``compute reduce sum`` so each
    layer can be assigned a total potential energy that includes bonded,
    non-bonded, and long-range contributions as partitioned by LAMMPS.
    """
    if not spec.group_selectors or not spec.layer_count or spec.layer_count < 1:
        return ""

    lines = [
        "# Per-layer total potential-energy profile",
        "compute pe_layer_atoms all pe/atom",
    ]
    for layer_name in sorted(spec.group_selectors.keys()):
        if not layer_name.startswith("layer_"):
            continue
        layer_idx = layer_name.split("_", 1)[1]
        lines.append(f"compute pe_layer_{layer_idx} {layer_name} reduce sum c_pe_layer_atoms")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Thermo group helper
# ---------------------------------------------------------------------------


def thermo_group_label(study_type: StudyType, crystal_type_ids: set[int]) -> str:
    """Return 'organic' if crystal atoms present in layered study, else 'all'."""
    return "organic" if (study_type == StudyType.LAYER_BULKFF and bool(crystal_type_ids)) else "all"
