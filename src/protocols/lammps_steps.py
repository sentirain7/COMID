"""
LAMMPS simulation step generators.

Standalone functions extracted from LAMMPSInputGenerator for generating
LAMMPS commands for individual simulation steps (minimize, NVT, NPT, etc.).

Each function receives the necessary parameters explicitly instead of
accessing ``self`` attributes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from common.hashing import compute_content_hash
from common.logging import get_logger
from contracts.policies.recovery import DEFAULT_RECOVERY_POLICY
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import StudyType
from protocols.template_engine import TemplateEngine

if TYPE_CHECKING:
    from protocols.protocol_chain import ProtocolChain, ProtocolStep

logger = get_logger("protocols.lammps_steps")

# Canonical LAMMPS thermo energy decomposition keywords (eimp, NOT eimprop).
ENERGY_COMPONENT_FIELDS = "ebond eangle edihed eimp evdwl ecoul epair emol elong"


def _thermo_style(
    *,
    include_temp: bool = True,
    extras: Sequence[str] = (),
) -> str:
    """Build a canonical thermo_style string with energy decomposition.

    Canonical field order:
        step [temp] pe ke etotal press vol density <energy components> [extras]
    """
    base = "step"
    if include_temp:
        base += " temp"
    base += f" pe ke etotal press vol density {ENERGY_COMPONENT_FIELDS}"
    if extras:
        base += " " + " ".join(extras)
    return f"thermo_style custom {base}"


# ---------------------------------------------------------------------------
# Helper: thermo group selection
# ---------------------------------------------------------------------------


def thermo_group(study_type: StudyType, crystal_type_ids: set[int]) -> str:
    """Return 'organic' if crystal atoms present in layered study, else 'all'."""
    return "organic" if (study_type == StudyType.LAYER_BULKFF and bool(crystal_type_ids)) else "all"


# ---------------------------------------------------------------------------
# Helper: layered neighbor override
# ---------------------------------------------------------------------------


def layered_neigh_override(study_type: StudyType, step_name: str) -> str | None:
    """Return conservative neigh_modify for early layered dynamics steps.

    During initial high-temperature equilibration of layered structures,
    aggressive neighbor list rebuild delays can cause stale lists and
    undetected collisions leading to 'Bond atoms missing' errors.

    Args:
        study_type: Current study type.
        step_name: Name of the current step.

    Returns:
        neigh_modify command string, or None if no override needed.
    """
    _EARLY_STEPS = {
        "high_temp_nvt",
        "annealing_cycles",
        "nvt_equilibration",
        "npt_equilibration",
    }
    if study_type == StudyType.LAYER_BULKFF and step_name in _EARLY_STEPS:
        return "neigh_modify delay 0 every 1 check yes"
    return None


# ---------------------------------------------------------------------------
# Checkpoint helper
# ---------------------------------------------------------------------------


def add_checkpoint_commands(lines: list[str], step_name: str) -> None:
    """Add periodic checkpoint commands to LAMMPS script if enabled.

    Uses alternating restart files for corruption protection.
    Settings are from SSOT policy (DEFAULT_RECOVERY_POLICY).

    Args:
        lines: List of LAMMPS commands to append to
        step_name: Name of the current step (used for restart filenames)
    """
    if DEFAULT_RECOVERY_POLICY.enable_periodic_checkpoint:
        checkpoint_interval = DEFAULT_RECOVERY_POLICY.checkpoint_interval_steps
        lines.append("")
        lines.append(f"# Periodic checkpoint (every {checkpoint_interval} steps)")
        lines.append(f"restart {checkpoint_interval} restart.{step_name}.a restart.{step_name}.b")


# ---------------------------------------------------------------------------
# Velocity create
# ---------------------------------------------------------------------------


def generate_velocity_create(
    chain: ProtocolChain,
    minimize_step_index: int,
    crystal_type_ids: set[int],
) -> str:
    """Generate velocity initialization after minimize.

    For layered structures (LAYER_BULKFF), assigns 10K Gaussian velocities
    to prevent 0K->high-T thermal shock when the first dynamics step starts
    (high_temp_nvt at 500K). For bulk, uses the next step's target
    temperature -- the standard LAMMPS practice.

    Args:
        chain: Protocol chain.
        minimize_step_index: Index of the minimize step in chain.steps.
        crystal_type_ids: Set of crystal atom type IDs.

    Returns:
        LAMMPS velocity create command, or empty string if no dynamics follow.
    """
    # Find next dynamics step after minimize
    next_step: ProtocolStep | None = None
    for s in chain.steps[minimize_step_index + 1 :]:
        if s.step_type in ("nvt", "npt", "nve", "annealing", "viscosity"):
            next_step = s
            break

    if next_step is None:
        return ""

    group = thermo_group(chain.study_type, crystal_type_ids)

    # Layered: 10K soft start to avoid 0K->500K thermal shock
    # Bulk: target temperature (standard practice, no thermal shock risk)
    if chain.study_type == StudyType.LAYER_BULKFF:
        vel_temp = 10.0
    else:
        vel_temp = next_step.temperature_K

    # Deterministic seed from simulation identity
    data_basename = Path(chain.data_file_path).name if chain.data_file_path else "unknown"
    seed_hash = compute_content_hash(
        {
            "data_file": data_basename,
            "study_type": chain.study_type.value,
            "next_step": next_step.name,
            "temperature_K": next_step.temperature_K,
        },
        length=8,
    )
    seed = int(seed_hash, 16) % (2**31 - 1)
    if seed == 0:
        seed = 1

    return f"velocity {group} create {vel_temp} {seed} mom yes rot yes dist gaussian"


# ---------------------------------------------------------------------------
# Minimize
# ---------------------------------------------------------------------------


def generate_minimize(step: ProtocolStep) -> str:
    """Generate minimization commands."""
    max_iter = step.constraints.get("max_iter", 10000)
    max_eval = step.constraints.get("max_eval", 100000)
    etol = step.constraints.get("etol", 1e-4)
    ftol = step.constraints.get("ftol", 1e-6)

    lines = [
        "# Energy minimization",
        f"thermo {step.thermo_interval}",
        _thermo_style(include_temp=False),
        "thermo_modify flush yes",
        f"minimize {etol} {ftol} {max_iter} {max_eval}",
        "reset_timestep 0",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NVT
# ---------------------------------------------------------------------------


def generate_nvt(
    step: ProtocolStep,
    step_index: int,
    study_type: StudyType = StudyType.BULK,
    gg_columns: Sequence[str] = (),
    *,
    opt_profile: dict | None = None,
    crystal_type_ids: set[int] | None = None,
) -> str:
    """Generate NVT ensemble commands."""
    _crystal = crystal_type_ids or set()
    fix_id = f"nvt_{step_index}"
    nsteps = TemplateEngine._filter_duration_to_steps(step.duration, step.timestep_fs)
    temp = step.temperature_K
    tdamp = step.extra_params.get("tdamp", 100.0)

    # NVT temperature ramp: use temp_start_K if specified (layered high_temp_nvt)
    temp_start = step.extra_params.get("temp_start_K", temp)

    thermo_base = _thermo_style(extras=gg_columns)

    # Dump columns: remove velocity for NVT equilibration (not used in analysis)
    opt = opt_profile
    dump_cols = "id type"
    if gg_columns:
        dump_cols += " mol"
    if opt and not opt.get("dump_velocity", True):
        dump_cols += " xu yu zu"
    else:
        dump_cols += " xu yu zu x y z vx vy vz"

    # Dump interval: computed adaptively in protocol_chain._compute_dump_interval()
    dump_interval = step.dump_interval

    group = thermo_group(study_type, _crystal)

    lines: list[str] = []

    # Conservative neighbor rebuild for early layered dynamics steps
    neigh_override = layered_neigh_override(study_type, step.name)
    if neigh_override:
        lines.append(neigh_override)

    lines.extend(
        [
            f"timestep {step.timestep_fs}",
            f"fix {fix_id} {group} nvt temp {temp_start} {temp} {tdamp}",
            "",
            f"thermo {step.thermo_interval}",
            thermo_base,
            "thermo_modify flush yes",
            f"dump d_{step_index} all custom {dump_interval} dump_{step.name}.lammpstrj {dump_cols}",
        ]
    )

    add_checkpoint_commands(lines, step.name)

    lines.extend(
        [
            "",
            f"run {nsteps}",
            f"unfix {fix_id}",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NPT
# ---------------------------------------------------------------------------


def _npt_early_stop_lines(fix_id: str, nsteps: int, thermo_interval: int) -> list[str] | None:
    """Build the opt-in NPT convergence early-stop block.

    Returns the LAMMPS lines that replace a single ``run {nsteps}`` with a
    floor segment + a ``fix halt`` monitored segment, or ``None`` when the
    feature is disabled or the run is too short for a meaningful trailing
    window (in which case the caller falls back to the fixed-duration run).

    Convergence proxy: the trailing-window coefficient of variation
    (std/mean) of density. The ``fix halt`` can only fire after a floor of
    ``early_stop_min_fraction * nsteps``, so a premature, non-equilibrated
    dip cannot end the run early. Validated against a local argon NPT.
    """
    crit = DEFAULT_TIER_POLICY.convergence_criteria
    if not crit.enable_early_stop:
        return None

    nevery = max(1, int(thermo_interval))
    nrepeat = 10
    nfreq = nevery * nrepeat
    window = 5  # trailing blocks averaged for the CV
    floor = int(nsteps * crit.early_stop_min_fraction)
    # Need the trailing window to fill (and at least one halt check) within
    # the floor; otherwise the criterion is meaningless — skip early stop.
    if nfreq * window <= 0 or floor < nfreq * window or floor >= nsteps:
        return None
    remaining = nsteps - floor
    threshold = crit.early_stop_density_cv

    return [
        "",
        "# Convergence-based early stop (opt-in): halt when the trailing-window",
        "# density CV (std/mean) drops below threshold, after a step floor.",
        f"variable {fix_id}_dens equal density",
        f"variable {fix_id}_dens2 equal density*density",
        f"fix {fix_id}_dm all ave/time {nevery} {nrepeat} {nfreq} "
        f"v_{fix_id}_dens ave window {window}",
        f"fix {fix_id}_dm2 all ave/time {nevery} {nrepeat} {nfreq} "
        f"v_{fix_id}_dens2 ave window {window}",
        f"variable {fix_id}_dcv equal "
        f"sqrt(abs(f_{fix_id}_dm2-f_{fix_id}_dm*f_{fix_id}_dm))/f_{fix_id}_dm",
        f"run {floor}",
        f"fix {fix_id}_halt all halt {nfreq} v_{fix_id}_dcv < {threshold} error continue",
        f"run {remaining}",
        f"unfix {fix_id}_halt",
        f"unfix {fix_id}_dm",
        f"unfix {fix_id}_dm2",
    ]


def generate_npt(
    step: ProtocolStep,
    step_index: int,
    study_type: StudyType = StudyType.BULK,
    gg_columns: Sequence[str] = (),
    *,
    opt_profile: dict | None = None,
    crystal_type_ids: set[int] | None = None,
) -> str:
    """Generate NPT ensemble commands."""
    _crystal = crystal_type_ids or set()
    fix_id = f"npt_{step_index}"
    nsteps = TemplateEngine._filter_duration_to_steps(step.duration, step.timestep_fs)
    temp = step.temperature_K
    press = step.pressure_atm
    tdamp = step.extra_params.get("tdamp", 100.0)
    pdamp = step.extra_params.get("pdamp", 1000.0)

    group = thermo_group(study_type, _crystal)

    # Set pressure coupling based on study type
    if study_type == StudyType.LAYER_BULKFF:
        npt_fix = f"fix {fix_id} {group} npt temp {temp} {temp} {tdamp} couple xy x {press} {press} {pdamp} y {press} {press} {pdamp}"
    else:
        npt_fix = f"fix {fix_id} {group} npt temp {temp} {temp} {tdamp} iso {press} {press} {pdamp}"

    thermo_base = _thermo_style(extras=gg_columns)

    # Dump columns: remove velocity for NPT production (not used in RDF/MSD)
    opt = opt_profile
    dump_cols = "id type"
    if gg_columns:
        dump_cols += " mol"
    if opt and not opt.get("dump_velocity", True):
        dump_cols += " xu yu zu"
    else:
        dump_cols += " xu yu zu x y z vx vy vz"

    lines: list[str] = []

    # Conservative neighbor rebuild for early layered dynamics steps
    neigh_override = layered_neigh_override(study_type, step.name)
    if neigh_override:
        lines.append(neigh_override)

    lines.extend(
        [
            f"timestep {step.timestep_fs}",
            npt_fix,
            "",
            f"thermo {step.thermo_interval}",
            thermo_base,
            "thermo_modify flush yes",
            f"dump d_{step_index} all custom {step.dump_interval} dump_{step.name}.lammpstrj {dump_cols}",
        ]
    )

    add_checkpoint_commands(lines, step.name)

    # Opt-in convergence early stop (off by default → identical fixed run).
    early_stop = _npt_early_stop_lines(fix_id, nsteps, step.thermo_interval)
    if early_stop is not None:
        lines.extend(early_stop)
    else:
        lines.extend(["", f"run {nsteps}"])

    lines.extend(
        [
            f"unfix {fix_id}",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NVE
# ---------------------------------------------------------------------------


def generate_nve(
    step: ProtocolStep,
    step_index: int,
    gg_columns: Sequence[str] = (),
) -> str:
    """Generate NVE ensemble commands."""
    fix_id = f"nve_{step_index}"
    nsteps = TemplateEngine._filter_duration_to_steps(step.duration, step.timestep_fs)

    thermo_base = _thermo_style(extras=gg_columns)

    dump_cols = "id type"
    if gg_columns:
        dump_cols += " mol"
    dump_cols += " xu yu zu x y z vx vy vz"

    lines = [
        f"timestep {step.timestep_fs}",
        f"fix {fix_id} all nve",
        "",
        f"thermo {step.thermo_interval}",
        thermo_base,
        "thermo_modify flush yes",
        f"dump d_{step_index} all custom {step.dump_interval} dump_{step.name}.lammpstrj {dump_cols}",
    ]

    add_checkpoint_commands(lines, step.name)

    lines.extend(
        [
            "",
            f"run {nsteps}",
            f"unfix {fix_id}",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Viscosity (Muller-Plathe RNEMD)
# ---------------------------------------------------------------------------


def generate_viscosity(
    step: ProtocolStep,
    step_index: int,
    gg_columns: Sequence[str] = (),
) -> str:
    """Generate Muller-Plathe viscosity calculation."""
    fix_id = f"viscosity_{step_index}"
    nsteps = TemplateEngine._filter_duration_to_steps(step.duration, step.timestep_fs)
    temp = step.temperature_K
    tdamp = step.extra_params.get("tdamp", 100.0)

    thermo_base = _thermo_style(extras=[f"f_{fix_id}", *gg_columns])

    dump_cols = "id type"
    if gg_columns:
        dump_cols += " mol"
    dump_cols += " xu yu zu x y z vx vy vz"

    lines = [
        f"timestep {step.timestep_fs}",
        f"fix nvt_{step_index} all nvt temp {temp} {temp} {tdamp}",
        "",
        "# Muller-Plathe reverse non-equilibrium MD",
        f"fix {fix_id} all viscosity 100 x z 20",
        "",
        "compute stress all stress/atom NULL",
        "compute temp_profile all temp/profile 1 0 0 z 20",
        # Thermostat on the PROFILE-UNBIASED temperature: subtract the imposed
        # x-streaming velocity (binned in z) before thermostatting, so the NVT
        # thermostat does not fight/erase the Muller-Plathe momentum flux. Without
        # this, the thermostat removes the very velocity gradient we measure,
        # collapsing dv_x/dz into noise and giving a meaningless viscosity.
        f"fix_modify nvt_{step_index} temp temp_profile",
        "",
        "# Velocity profile for viscosity calculation (20 bins matching fix viscosity)",
        f"compute chunks_{step_index} all chunk/atom bin/1d z lower 0.05 units reduced",
        f"fix vprof_{step_index} all ave/chunk 100 10 1000 chunks_{step_index} vx file vprofile_{step.name}.dat",
        "",
        f"thermo {step.thermo_interval}",
        thermo_base,
        "thermo_modify flush yes",
        f"dump d_{step_index} all custom {step.dump_interval} dump_{step.name}.lammpstrj {dump_cols}",
    ]

    # Viscosity runs are long, so checkpointing is especially important
    add_checkpoint_commands(lines, step.name)

    lines.extend(
        [
            "",
            f"run {nsteps}",
            f"unfix nvt_{step_index}",
            f"unfix {fix_id}",
            f"unfix vprof_{step_index}",
            # Reset thermo before write_restart so its System init does not
            # reference the now-removed f_{fix_id} fix. Without this, LAMMPS
            # aborts the *completed* viscosity run with
            # "ERROR: Could not find thermo fix ID viscosity_N" (thermo.cpp).
            # Mirrors the same guard in the tensile/shear generators.
            _thermo_style(extras=gg_columns),
            f"uncompute chunks_{step_index}",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Annealing
# ---------------------------------------------------------------------------


def generate_annealing(
    step: ProtocolStep,
    step_index: int,
    study_type: StudyType = StudyType.BULK,
    *,
    crystal_type_ids: set[int] | None = None,
) -> str:
    """Generate annealing cycles: N cycles of T_low<->T_high NVT temperature ramping.

    Args:
        step: Protocol step with annealing parameters.
        step_index: Step index in chain.
        study_type: Study type for thermo group selection.
        crystal_type_ids: Set of crystal atom type IDs.

    Returns:
        LAMMPS command string for annealing cycles.
    """
    _crystal = crystal_type_ids or set()
    params = step.extra_params
    n_cycles = params.get("n_cycles", 5)
    temp_high = params.get("temp_high_K", 500.0)
    temp_low = params.get("temp_low_K", step.temperature_K)
    tdamp = params.get("tdamp", 100.0)
    duration_half_ps = params.get("duration_per_half_cycle_ps", 100.0)
    dt = step.timestep_fs
    steps_per_half = int(duration_half_ps * 1000 / dt)

    dump_interval = step.dump_interval

    group = thermo_group(study_type, _crystal)

    lines = [f"# Annealing: {n_cycles} cycles, {temp_low}K <-> {temp_high}K"]

    # Conservative neighbor rebuild for early layered dynamics steps
    neigh_override = layered_neigh_override(study_type, step.name)
    if neigh_override:
        lines.append(neigh_override)

    lines.append(f"timestep {dt}")
    lines.append(f"thermo {step.thermo_interval}")
    lines.append(_thermo_style())
    lines.append("thermo_modify flush yes")
    lines.append(
        f"dump d_{step_index} all custom {dump_interval} "
        f"dump_{step.name}.lammpstrj id type xu yu zu x y z vx vy vz"
    )

    add_checkpoint_commands(lines, step.name)

    for i in range(n_cycles):
        # Heating: T_low -> T_high
        fix_id_heat = f"anneal_heat_{step_index}_{i}"
        lines.append(f"\n# Cycle {i + 1}/{n_cycles} - Heating")
        lines.append(f"fix {fix_id_heat} {group} nvt temp {temp_low} {temp_high} {tdamp}")
        lines.append(f"run {steps_per_half}")
        lines.append(f"unfix {fix_id_heat}")

        # Cooling: T_high -> T_low
        fix_id_cool = f"anneal_cool_{step_index}_{i}"
        lines.append(f"# Cycle {i + 1}/{n_cycles} - Cooling")
        lines.append(f"fix {fix_id_cool} {group} nvt temp {temp_high} {temp_low} {tdamp}")
        lines.append(f"run {steps_per_half}")
        lines.append(f"unfix {fix_id_cool}")

    lines.append(f"undump d_{step_index}")
    lines.append(f"write_restart restart.{step.name}")
    # No reset_timestep here -- step counter continues for progress tracking.
    # Tensile stages retain their own reset_timestep 0 (strain = step*dt*v).
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tensile (continuous)
# ---------------------------------------------------------------------------


def generate_tensile(
    step: ProtocolStep,
    step_index: int,
    chain: ProtocolChain,
    *,
    crystal_type_ids: set[int] | None = None,
) -> str:
    """Generate LAMMPS grip-pull interface tensile test commands.

    Args:
        step: Protocol step with tensile parameters.
        step_index: Step index in chain.
        chain: Full protocol chain (for study_type reference).
        crystal_type_ids: Set of crystal atom type IDs.

    Returns:
        LAMMPS command string for tensile test.
    """
    _crystal = crystal_type_ids or set()
    params = step.extra_params
    pull_v = params.get("pull_velocity_A_per_fs", 0.0001)
    grip_thick = params.get("grip_thickness_angstrom", 20.0)
    output_every = params.get("output_interval_steps", 100)
    temp = step.temperature_K
    tdamp = params.get("tdamp", 100.0)
    z_lo = params.get("z_lo_grip", 0.0)
    z_hi = params.get("z_hi_grip", 100.0)

    # Explicit crystal grip ranges (override grip_thickness)
    bottom_grip_z = params.get("bottom_grip_z")
    top_grip_z = params.get("top_grip_z")

    if bottom_grip_z is not None:
        z_lo_bottom, z_hi_bottom = bottom_grip_z
    else:
        z_lo_bottom, z_hi_bottom = z_lo, z_lo + grip_thick

    if top_grip_z is not None:
        z_lo_top, z_hi_top = top_grip_z
    else:
        z_lo_top, z_hi_top = z_hi - grip_thick, z_hi

    original_gap = z_lo_top - z_hi_bottom

    nsteps = TemplateEngine._filter_duration_to_steps(step.duration, step.timestep_fs)

    has_freeze = chain.study_type == StudyType.LAYER_BULKFF and bool(_crystal)

    lines = [
        "# === Tensile pull test (Phase 4.3) ===",
    ]

    # Phase 3: release global crystal freeze -- grip fixes take over
    if has_freeze:
        lines.extend(
            [
                "# Release global crystal freeze — grip fixes take over",
                "unfix freeze_crystal",
                "",
            ]
        )

    lines.extend(
        [
            "reset_timestep 0",
            f"timestep {step.timestep_fs}",
            "",
            "# Define grip regions by z-coordinate",
            f"region bottom_grip block INF INF INF INF {z_lo_bottom:.4f} {z_hi_bottom:.4f}",
            f"region top_grip block INF INF INF INF {z_lo_top:.4f} {z_hi_top:.4f}",
            "",
            "group grip_bottom region bottom_grip",
            "group grip_top region top_grip",
            "group mobile subtract all grip_bottom grip_top",
            "",
            "# Bottom grip: frozen",
            "fix freeze_bottom grip_bottom setforce 0.0 0.0 0.0",
            "velocity grip_bottom set 0.0 0.0 0.0",
            "",
            "# Top grip: constant velocity pull in +z",
            f"fix pull_top grip_top move linear 0.0 0.0 {pull_v}",
            "",
            "# NVT thermostat on mobile atoms only",
            f"fix nvt_mobile mobile nvt temp {temp} {temp} {tdamp}",
            "",
            "# Force measurement on top grip",
            "compute fz_top grip_top reduce sum fz",
            "",
            "# Stress-strain variables",
            f"variable original_gap equal {original_gap:.4f}",
            f"variable pull_vel equal {pull_v}",
            "variable disp equal step*dt*v_pull_vel",
            "variable eng_strain equal v_disp/v_original_gap",
            "# kcal/mol/A^3 -> MPa conversion: 6947.7",
            "variable area equal lx*ly",
            "variable eng_stress_MPa equal c_fz_top/v_area*6947.7",
            "",
            f"# Output stress-strain data every {output_every} steps",
            f"fix ss_output all print {output_every} "
            f'"${{eng_strain}} ${{eng_stress_MPa}}" '
            f"file stress_strain_{step.name}.dat screen no "
            f'title "# strain stress_MPa"',
            "",
            f"thermo {step.thermo_interval}",
            _thermo_style(extras=["v_eng_strain", "v_eng_stress_MPa", "c_fz_top", "lz"]),
            "thermo_modify flush yes",
            f"dump d_{step_index} all custom {step.dump_interval} "
            f"dump_{step.name}.lammpstrj id type xu yu zu x y z",
        ]
    )

    add_checkpoint_commands(lines, step.name)

    lines.extend(
        [
            "",
            f"run {nsteps}",
            "unfix freeze_bottom",
            "unfix pull_top",
            "unfix nvt_mobile",
            "unfix ss_output",
            # Reset thermo before uncompute so write_restart doesn't
            # reference the now-deleted c_fz_top / v_eng_stress_MPa.
            _thermo_style(),
            "uncompute fz_top",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tensile quasi-static
# ---------------------------------------------------------------------------


def generate_tensile_quasi_static(
    step: ProtocolStep,
    step_index: int,
    chain: ProtocolChain,
    *,
    crystal_type_ids: set[int] | None = None,
) -> str:
    """Generate LAMMPS quasi-static decohesion tensile test commands.

    Displaces the top grip incrementally, relaxing between each step.
    Force is time-averaged over the tail of each relaxation window.

    Args:
        step: Protocol step with QS tensile parameters.
        step_index: Step index in chain.
        chain: Full protocol chain (for study_type reference).
        crystal_type_ids: Set of crystal atom type IDs.

    Returns:
        LAMMPS command string for quasi-static tensile test.
    """
    _crystal = crystal_type_ids or set()
    params = step.extra_params
    grip_thick = params.get("grip_thickness_angstrom", 20.0)
    max_strain = params.get("max_strain", 0.5)
    temp = step.temperature_K
    tdamp = params.get("tdamp", 100.0)
    z_lo = params.get("z_lo_grip", 0.0)
    z_hi = params.get("z_hi_grip", 100.0)

    requested_inc = params.get("displacement_increment_angstrom", 0.5)
    relax_steps = params.get("relax_steps", 10000)
    force_avg_steps = params.get("force_average_steps", 1000)

    # Explicit crystal grip ranges
    bottom_grip_z = params.get("bottom_grip_z")
    top_grip_z = params.get("top_grip_z")

    if bottom_grip_z is not None:
        z_lo_bottom, z_hi_bottom = bottom_grip_z
    else:
        z_lo_bottom, z_hi_bottom = z_lo, z_lo + grip_thick

    if top_grip_z is not None:
        z_lo_top, z_hi_top = top_grip_z
    else:
        z_lo_top, z_hi_top = z_hi - grip_thick, z_hi

    original_gap = z_lo_top - z_hi_bottom
    max_disp = original_gap * max_strain

    n_disp_steps = max(1, math.ceil(max_disp / requested_inc)) if requested_inc > 0 else 1
    disp_inc = max_disp / n_disp_steps if n_disp_steps > 0 else requested_inc

    has_freeze = chain.study_type == StudyType.LAYER_BULKFF and bool(_crystal)

    lines = [
        "# === Quasi-static decohesion tensile test ===",
    ]

    # Release global crystal freeze
    if has_freeze:
        lines.extend(
            [
                "# Release global crystal freeze — grip fixes take over",
                "unfix freeze_crystal",
                "",
            ]
        )

    lines.extend(
        [
            "reset_timestep 0",
            f"timestep {step.timestep_fs}",
            "",
            "# Define grip regions by z-coordinate",
            f"region bottom_grip block INF INF INF INF {z_lo_bottom:.4f} {z_hi_bottom:.4f}",
            f"region top_grip block INF INF INF INF {z_lo_top:.4f} {z_hi_top:.4f}",
            "",
            "group grip_bottom region bottom_grip",
            "group grip_top region top_grip",
            "group mobile subtract all grip_bottom grip_top",
            "",
            "# Bottom grip: frozen",
            "fix freeze_bottom grip_bottom setforce 0.0 0.0 0.0",
            "velocity grip_bottom set 0.0 0.0 0.0",
            "",
            "# Top grip: held in place (updated each QS step)",
            "fix hold_top grip_top move linear 0.0 0.0 0.0",
            "",
            "# NVT thermostat on mobile atoms only",
            f"fix nvt_mobile mobile nvt temp {temp} {temp} {tdamp}",
            "",
            "# Force measurement on top grip (z-component)",
            "compute fz_top grip_top reduce sum fz",
            f"fix fz_avg all ave/time 1 {force_avg_steps} {relax_steps} c_fz_top",
            "",
            "# QS variables",
            f"variable original_gap equal {original_gap:.4f}",
            f"variable disp_inc equal {disp_inc}",
            "variable area equal lx*ly",
            "",
            f"thermo {step.thermo_interval}",
            _thermo_style(extras=["lz", "c_fz_top"]),
            "thermo_modify flush yes",
            f"dump d_{step_index} all custom {step.dump_interval} "
            f"dump_{step.name}.lammpstrj id type xu yu zu x y z",
        ]
    )

    add_checkpoint_commands(lines, step.name)

    # QS loop
    lines.extend(
        [
            "",
            f"# Quasi-static loop: {n_disp_steps} displacement steps",
            f"variable i loop {n_disp_steps}",
            "label qs_loop",
            "  # Remove top hold, displace, re-hold",
            "  unfix hold_top",
            f"  displace_atoms grip_top move 0.0 0.0 {disp_inc}",
            "  fix hold_top grip_top move linear 0.0 0.0 0.0",
            f"  run {relax_steps}",
            "  # Record stress-strain",
            "  variable qs_strain equal v_i*v_disp_inc/v_original_gap",
            "  variable qs_stress equal f_fz_avg/v_area*6947.7",
            f'  print "${{qs_strain}} ${{qs_stress}}" '
            f"append stress_strain_{step.name}.dat screen no",
            "next i",
            "jump SELF qs_loop",
            "",
            "# Cleanup",
            "unfix freeze_bottom",
            "unfix hold_top",
            "unfix nvt_mobile",
            "unfix fz_avg",
            # Reset thermo before uncompute so write_restart doesn't
            # reference the now-deleted c_fz_top / v_eng_stress_MPa.
            _thermo_style(),
            "uncompute fz_top",
            f"undump d_{step_index}",
            f"write_restart restart.{step.name}",
        ]
    )

    return "\n".join(lines)
