"""
LAMMPS input file generator.

Generates complete LAMMPS input scripts from protocol chains
using Jinja2 templates.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.interfaces import AbstractProtocolGenerator
from contracts.policies.forcefield import get_ff_version
from contracts.policies.stabilization import StabilizationChain
from contracts.schemas import GroupEnergySpec, ProtocolRequest, ProtocolResult, StudyType
from protocols.lammps_force_field import (
    generate_crystal_groups as _ff_generate_crystal_groups,
)
from protocols.lammps_force_field import (
    generate_force_field as _ff_generate_force_field,
)
from protocols.lammps_force_field import (
    generate_group_energy_commands as _ff_generate_group_energy_commands,
)
from protocols.lammps_force_field import (
    generate_layer_pe_commands as _ff_generate_layer_pe_commands,
)
from protocols.lammps_force_field import (
    generate_neighbor_settings as _ff_generate_neighbor_settings,
)
from protocols.lammps_force_field import (
    generate_package_commands as _ff_generate_package_commands,
)
from protocols.lammps_force_field import (
    generate_pair_coeffs as _ff_generate_pair_coeffs,
)
from protocols.lammps_force_field import (
    has_crystal_freeze as _ff_has_crystal_freeze,
)
from protocols.lammps_force_field import (
    thermo_group_label as _ff_thermo_group,
)
from protocols.lammps_restart import (
    generate_restart_script_body as _restart_generate_body,
)
from protocols.lammps_steps import (
    add_checkpoint_commands as _steps_add_checkpoint,
)
from protocols.lammps_steps import (
    generate_annealing as _steps_generate_annealing,
)
from protocols.lammps_steps import (
    generate_minimize as _steps_generate_minimize,
)
from protocols.lammps_steps import (
    generate_npt as _steps_generate_npt,
)
from protocols.lammps_steps import (
    generate_nve as _steps_generate_nve,
)
from protocols.lammps_steps import (
    generate_nvt as _steps_generate_nvt,
)
from protocols.lammps_steps import (
    generate_tensile as _steps_generate_tensile,
)
from protocols.lammps_steps import (
    generate_tensile_quasi_static as _steps_generate_tensile_qs,
)
from protocols.lammps_steps import (
    generate_velocity_create as _steps_generate_velocity_create,
)
from protocols.lammps_steps import (
    generate_viscosity as _steps_generate_viscosity,
)
from protocols.lammps_steps import (
    layered_neigh_override as _steps_layered_neigh_override,
)
from protocols.protocol_chain import ProtocolChain, ProtocolChainBuilder, ProtocolStep
from protocols.protocol_hash import ProtocolHasher
from protocols.template_engine import TemplateEngine

if TYPE_CHECKING:
    from contracts.schemas import LammpsCaps
    from protocols.duration_adjuster import StageDurationOverride

logger = get_logger("protocols.lammps_input")


class LAMMPSInputGenerator(AbstractProtocolGenerator):
    """
    Generator for LAMMPS input scripts.

    Implements IProtocolGenerator interface for creating
    LAMMPS-compatible simulation inputs.
    """

    def __init__(
        self,
        template_dir: Path | None = None,
        stabilization_chain: StabilizationChain | None = None,
        caps: "LammpsCaps | None" = None,
    ):
        """
        Initialize LAMMPS input generator.

        Args:
            template_dir: Directory containing templates
            stabilization_chain: Stabilization chain policy
            caps: LAMMPS capability profile from probe (None = use defaults)
        """
        self.engine = TemplateEngine(template_dir)
        self.chain_builder = ProtocolChainBuilder(stabilization_chain=stabilization_chain)
        self.hasher = ProtocolHasher()
        self._caps = caps
        self._opt_profile: dict | None = None  # set per-generate in _generate_script

        # Ensure default templates exist
        self._create_default_templates()

    def generate(
        self,
        request: ProtocolRequest,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
    ) -> ProtocolResult:
        """
        Generate LAMMPS input file from request.

        Writes the input file to the same directory as the data file
        with the name "in.lammps".

        Args:
            request: Protocol request
            stage_duration_overrides: Optional stage duration overrides

        Returns:
            Protocol result with generation details
        """
        # Determine output path (same directory as data file)
        data_dir = Path(request.data_file_path).parent
        output_path = data_dir / "in.lammps"

        return self.generate_to_path(request, output_path, stage_duration_overrides)

    def generate_to_path(
        self,
        request: ProtocolRequest,
        output_path: Path,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
    ) -> ProtocolResult:
        """
        Generate LAMMPS input file to specific path.

        Args:
            request: Protocol request
            output_path: Path to write input file
            stage_duration_overrides: Optional stage duration overrides

        Returns:
            Protocol result with generation details
        """
        # Infer data-file capabilities (coeff sections, bonded topology).
        self._inspect_data_file_capabilities(Path(request.data_file_path))

        # Build protocol chain
        chain = self.chain_builder.build(request)

        # Apply duration overrides if provided
        if stage_duration_overrides:
            from protocols.duration_adjuster import ProtocolChainAdjuster

            adjuster = ProtocolChainAdjuster()
            chain = adjuster.apply_overrides(chain, stage_duration_overrides)
            logger.info(
                f"Applied stage duration overrides: "
                f"{[(o.stage_name, o.duration_ps or o.duration_steps) for o in stage_duration_overrides]}"
            )

        # Generate protocol hash
        protocol_hash = self._compute_protocol_hash(chain)

        # Generate LAMMPS script
        data_file = Path(request.data_file_path).name
        script = self._generate_script(
            chain, data_file, group_energy_spec=request.group_energy_spec
        )

        # Write to file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(script)

        # Calculate metrics
        total_steps = self.chain_builder.get_total_steps(chain)
        step_names = [step.name for step in chain.steps]

        # Expected outputs
        expected_outputs = self._get_expected_outputs(chain)

        # Extract sampling metadata from chain for provenance tracking (v00.97.00)
        sampling_metadata = getattr(chain, "sampling_metadata", None)
        if sampling_metadata:
            logger.debug(f"Sampling metadata: adaptive={sampling_metadata.get('adaptive_enabled')}")

        return ProtocolResult(
            input_script_path=str(output_path),
            expected_outputs=expected_outputs,
            estimated_steps=total_steps,
            protocol_hash=protocol_hash,
            stabilization_chain=step_names,
            sampling_metadata=sampling_metadata,
            # PR 2 (Codex Round 7): structured generation-time provenance
            # — propagate the chain's resolved E_intra method/cutoff so
            # downstream stages do not re-parse or re-evaluate env vars.
            e_intra_method=getattr(chain, "e_intra_method", None),
            vacuum_cutoff_a=getattr(chain, "vacuum_cutoff_a", None),
        )

    # ------------------------------------------------------------------
    # Restart-from-checkpoint script generation (v1: stage-boundary)
    # ------------------------------------------------------------------

    def generate_restart_script(
        self,
        request: ProtocolRequest,
        restart_file: Path,
        remaining_stage_indices: list[int],
        output_path: Path,
        original_data_file: Path | None = None,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
    ) -> ProtocolResult:
        """Generate a LAMMPS input script that resumes from a restart file.

        The script uses ``read_restart`` instead of ``read_data`` and only
        emits the stages listed in *remaining_stage_indices*.  @@STAGE
        markers keep their **original** indices so that the progress system
        stays consistent with the compiled execution plan.

        Args:
            request: Original protocol request (for chain building).
            restart_file: Absolute path to the restart file.
            remaining_stage_indices: Original 0-based indices of stages
                still to execute.
            output_path: Where to write ``in.restart.lammps``.
            original_data_file: Optional data file for capability
                inspection (coeff detection, crystal types).
            stage_duration_overrides: Optional duration overrides.

        Returns:
            ProtocolResult pointing to the restart script.
        """
        # Inspect original data file for FF capabilities if available.
        if original_data_file and original_data_file.is_file():
            self._inspect_data_file_capabilities(original_data_file)
        else:
            # Safe defaults (typical full-topology data files).
            self._coeffs_in_data = True
            self._has_bonds = True
            self._has_charges = True
            self._inspect_data_file_capabilities_defaults()

        # Build chain (full) and optionally apply overrides.
        chain = self.chain_builder.build(request)
        if stage_duration_overrides:
            from protocols.duration_adjuster import ProtocolChainAdjuster

            chain = ProtocolChainAdjuster().apply_overrides(chain, stage_duration_overrides)

        # Compute optimization profile.
        if self._caps is not None:
            from orchestrator.lammps_probe import get_optimization_profile

            self._opt_profile = get_optimization_profile(self._caps)
        else:
            self._opt_profile = None

        # Build the restart script.
        script = self._generate_restart_script_body(
            chain,
            restart_file,
            remaining_stage_indices,
            group_energy_spec=request.group_energy_spec,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(script, encoding="utf-8")

        # Estimated steps for remaining stages only.
        # Infer dt from the chain (first dynamics step's timestep_fs, or 1.0 fs default).
        from protocols.template_engine import TemplateEngine

        dt_fs = 1.0
        for step in chain.steps:
            if step.step_type != "minimize" and getattr(step, "timestep_fs", None):
                dt_fs = step.timestep_fs
                break

        remaining_steps = 0
        for idx in remaining_stage_indices:
            if idx < len(chain.steps):
                step = chain.steps[idx]
                if step.step_type == "minimize":
                    dur_str = (step.duration or "").strip().lower()
                    if "steps" in dur_str:
                        remaining_steps += int(dur_str.replace("steps", "").strip())
                    else:
                        remaining_steps += step.constraints.get("max_iter", 10000)
                else:
                    remaining_steps += TemplateEngine._filter_duration_to_steps(
                        step.duration, dt_fs
                    )

        protocol_hash = self._compute_protocol_hash(chain)
        step_names = [step.name for step in chain.steps]

        # Extract sampling metadata from chain for provenance tracking (v00.97.00)
        # Restart scripts should also carry sampling provenance
        sampling_metadata = getattr(chain, "sampling_metadata", None)

        return ProtocolResult(
            input_script_path=str(output_path),
            expected_outputs=self._get_expected_outputs(chain),
            estimated_steps=remaining_steps,
            protocol_hash=protocol_hash,
            stabilization_chain=step_names,
            sampling_metadata=sampling_metadata,
        )

    def _generate_restart_script_body(
        self,
        chain: ProtocolChain,
        restart_file: Path,
        remaining_indices: list[int],
        group_energy_spec: GroupEnergySpec | None = None,
    ) -> str:
        """Build the LAMMPS script text for a checkpoint restart."""
        return _restart_generate_body(
            chain,
            restart_file,
            remaining_indices,
            group_energy_spec=group_energy_spec,
            opt_profile=self._opt_profile,
            coeffs_in_data=getattr(self, "_coeffs_in_data", True),
            has_charges=getattr(self, "_has_charges", True),
            has_bonds=getattr(self, "_has_bonds", True),
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
            generate_header_fn=self._generate_header,
            generate_step_fn=self._generate_step,
        )

    def _inspect_data_file_capabilities_defaults(self) -> None:
        """Set safe default force-field toggles (no data file inspection)."""
        self._coeffs_in_data = True
        self._has_bonds = True
        self._has_charges = True
        self._crystal_type_ids: set[int] = set()

    def _inspect_data_file_capabilities(self, data_file_path: Path) -> None:
        """Set force-field generation toggles from data-file sections/counts."""
        self._inspect_data_file_capabilities_defaults()

        try:
            text = data_file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        self._coeffs_in_data = "Pair Coeffs" in text

        bond_match = re.search(r"^\s*(\d+)\s+bonds\s*$", text, flags=re.MULTILINE)
        if bond_match:
            self._has_bonds = int(bond_match.group(1)) > 0

        atom_section = re.search(
            r"^\s*Atoms(?:\s*#.*)?\s*$",
            text,
            flags=re.MULTILINE,
        )
        if atom_section:
            tail = text[atom_section.end() :].splitlines()
            for raw_line in tail:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                # full style should contain at least 7 columns: id mol type q x y z
                self._has_charges = len(parts) >= 7
                break

        # Detect crystal atom types from combined data file annotation
        crystal_match = re.search(r"^#\s*Crystal atom types:\s*(.+)$", text, flags=re.MULTILINE)
        if crystal_match:
            try:
                self._crystal_type_ids = {int(t) for t in crystal_match.group(1).split()}
            except ValueError:
                self._crystal_type_ids = set()

    def get_protocol_hash(self, tier: str) -> str:
        """
        Get reproducibility hash for protocol.

        Args:
            tier: Tier type string

        Returns:
            Protocol hash string
        """
        from contracts.policies.stabilization import StabilizationChain

        stab_chain = StabilizationChain()
        step_names = stab_chain.get_step_names(tier)

        return self.hasher.hash(
            tier=tier,
            force_field="bulk_ff_gaff2",
            ff_version=get_ff_version(),
            topology_hash="",
            temperature_K=298.0,
            pressure_atm=1.0,
            step_names=step_names,
        )

    def get_stabilization_chain(self, tier: str) -> list[str]:
        """
        Get stabilization step names for tier.

        Args:
            tier: Tier type string

        Returns:
            List of step names
        """
        from contracts.policies.stabilization import StabilizationChain

        stab_chain = StabilizationChain()
        return stab_chain.get_step_names(tier)

    def _compute_protocol_hash(self, chain: ProtocolChain) -> str:
        """Compute protocol hash from chain."""
        step_names = [step.name for step in chain.steps]
        return self.hasher.hash(
            tier=chain.tier.value,
            force_field=chain.ff_type.value,
            ff_version=get_ff_version(),
            topology_hash="",  # Will be added from build result
            temperature_K=chain.temperature_K,
            pressure_atm=chain.pressure_atm,
            step_names=step_names,
        )

    def _get_expected_outputs(self, chain: ProtocolChain) -> list[str]:
        """Get list of expected output files."""
        outputs = ["log.lammps", "final.data", "final.restart"]

        for step in chain.steps:
            outputs.append(f"restart.{step.name}")
            if step.step_type != "minimize":
                outputs.append(f"dump_{step.name}.lammpstrj")
            if step.step_type == "tensile":
                outputs.append(f"stress_strain_{step.name}.dat")

        return outputs

    def _generate_script(
        self,
        chain: ProtocolChain,
        data_file: str,
        group_energy_spec: GroupEnergySpec | None = None,
    ) -> str:
        """Generate LAMMPS script from protocol chain."""
        # Compute optimization profile for this chain (caps-aware)
        if self._caps is not None:
            from orchestrator.lammps_probe import get_optimization_profile

            self._opt_profile = get_optimization_profile(self._caps)
        else:
            self._opt_profile = None

        sections = []

        # Header
        sections.append(self._generate_header(chain))

        # Force field setup
        sections.append(self._generate_force_field(chain))

        # Package commands (MUST be before read_data in LAMMPS 2025)
        pkg_section = self._generate_package_commands()
        if pkg_section:
            sections.append(pkg_section)

        # Read data file
        sections.append(f"read_data {data_file}")

        # Pair coefficients (default LJ parameters for all atom types)
        sections.append(self._generate_pair_coeffs(chain))

        # Neighbor settings
        sections.append(self._generate_neighbor_settings())

        # Crystal restraint groups (layered structures with crystal layers)
        crystal_groups = self._generate_crystal_groups(chain)
        if crystal_groups:
            sections.append("")
            sections.append(crystal_groups)

        # Group energy decomposition (Phase 4.2)
        gg_columns: list[str] = []
        layer_pe_columns: list[str] = []
        if group_energy_spec and (group_energy_spec.groups or group_energy_spec.group_selectors):
            sections.append("")
            sections.append(self._generate_group_energy_commands(group_energy_spec))
            gg_columns = [f"c_gg_{p.label}" for p in group_energy_spec.pairs]
            if chain.study_type == StudyType.LAYER_BULKFF and group_energy_spec.layer_count:
                layer_pe_commands = self._generate_layer_pe_commands(group_energy_spec)
                if layer_pe_commands:
                    sections.append("")
                    sections.append(layer_pe_commands)
                    layer_pe_columns = [
                        f"c_pe_layer_{idx}" for idx in range(int(group_energy_spec.layer_count))
                    ]

        # Generate each step
        for i, step in enumerate(chain.steps):
            sections.append("")  # Blank line separator
            sections.append(f"# Step {i + 1}: {step.name}")
            sections.append(f'print "@@STAGE {i} {step.name}"')
            sections.append(
                self._generate_step(
                    step,
                    chain,
                    i,
                    gg_columns=[*gg_columns, *layer_pe_columns],
                )
            )

        # Final write
        sections.append("")
        sections.append("# Write final state")
        sections.append("write_data final.data")
        sections.append("write_restart final.restart")

        return "\n".join(sections)

    def _generate_header(self, chain: ProtocolChain) -> str:
        """Generate script header."""
        protocol_hash = self._compute_protocol_hash(chain)
        e_intra_method = getattr(chain, "e_intra_method", None)
        vacuum_cutoff_a = getattr(chain, "vacuum_cutoff_a", None)

        # Set boundary conditions based on study type
        if chain.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
            boundary = "p p p" if e_intra_method == "single_molecule_periodic" else "s s s"
        elif chain.study_type == StudyType.BULK:
            boundary = "p p p"
        else:
            # Layer systems: periodic in x,y only
            boundary = "p p f"

        lines = [
            "# LAMMPS input script",
            f"# Tier: {chain.tier.value}",
            f"# Force Field: {chain.ff_type.value}",
            f"# Study Type: {chain.study_type.value}",
            f"# Temperature: {chain.temperature_K} K",
            f"# Pressure: {chain.pressure_atm} atm",
            f"# Protocol hash: {protocol_hash}",
        ]
        if e_intra_method:
            lines.append(f"# E_intra Method: {e_intra_method}")
        if vacuum_cutoff_a is not None:
            lines.append(f"# Vacuum Cutoff: {vacuum_cutoff_a:.2f} A")
        lines.extend(
            [
                "",
                "# Initialization",
                "units real",
                "atom_style full",
                f"boundary {boundary}",
            ]
        )

        # Newton flag: determined by LAMMPS capability probe
        opt = self._opt_profile
        if opt is not None:
            newton_val = opt.get("newton", "on")
            lines.append(f"newton {newton_val}")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Delegated force-field helpers
    # ------------------------------------------------------------------

    def _generate_force_field(self, chain: ProtocolChain) -> str:
        """Generate force field setup from ForceFieldConfig runtime profile."""
        return _ff_generate_force_field(
            chain,
            has_charges=getattr(self, "_has_charges", True),
            has_bonds=getattr(self, "_has_bonds", True),
        )

    def _generate_organic_ff(
        self,
        ff_config_key: str,
        has_charges: bool = True,
        has_bonds: bool = True,
        study_type: StudyType = StudyType.BULK,
    ) -> str:
        """Generate organic FF setup from ForceFieldConfig runtime profile."""
        from protocols.lammps_force_field import generate_organic_ff

        return generate_organic_ff(
            ff_config_key,
            has_charges=has_charges,
            has_bonds=has_bonds,
            study_type=study_type,
        )

    def _generate_reaxff(self) -> str:
        """Generate ReaxFF force field setup."""
        from protocols.lammps_force_field import generate_reaxff

        return generate_reaxff()

    def _generate_pair_coeffs(self, chain: ProtocolChain) -> str:
        """Generate pair coefficients for all atom types."""
        return _ff_generate_pair_coeffs(
            chain, coeffs_in_data=getattr(self, "_coeffs_in_data", True)
        )

    def _generate_package_commands(self) -> str:
        """Generate package commands (must be before read_data in LAMMPS 2025)."""
        return _ff_generate_package_commands(self._opt_profile)

    def _generate_neighbor_settings(self) -> str:
        """Generate neighbor list settings."""
        return _ff_generate_neighbor_settings(self._opt_profile)

    def _has_crystal_freeze(self, chain: ProtocolChain) -> bool:
        """Check if crystal freeze/restraint commands should be generated."""
        return _ff_has_crystal_freeze(chain, getattr(self, "_crystal_type_ids", set()))

    def _generate_crystal_groups(self, chain: ProtocolChain) -> str:
        """Generate crystal group + spring/self restraint for layered structures."""
        return _ff_generate_crystal_groups(chain, getattr(self, "_crystal_type_ids", set()))

    def _generate_group_energy_commands(self, spec: GroupEnergySpec) -> str:
        """Generate LAMMPS group/group energy decomposition commands."""
        return _ff_generate_group_energy_commands(spec)

    def _generate_layer_pe_commands(self, spec: GroupEnergySpec) -> str:
        """Generate per-layer total potential-energy computes."""
        return _ff_generate_layer_pe_commands(spec)

    def _thermo_group(self, study_type: StudyType = StudyType.BULK) -> str:
        """Return 'organic' if crystal atoms present in layered study, else 'all'."""
        return _ff_thermo_group(study_type, getattr(self, "_crystal_type_ids", set()))

    def _layered_neigh_override(self, study_type: StudyType, step_name: str) -> str | None:
        """Return conservative neigh_modify for early layered dynamics steps."""
        return _steps_layered_neigh_override(study_type, step_name)

    # ------------------------------------------------------------------
    # Step dispatch (stays in facade — routes to extracted functions)
    # ------------------------------------------------------------------

    def _generate_step(
        self,
        step: ProtocolStep,
        chain: ProtocolChain,
        step_index: int,
        gg_columns: list[str] | None = None,
    ) -> str:
        """Generate LAMMPS commands for a single step."""
        _gg = gg_columns or []

        # Phase 2 transition: before pre_tensile_nvt, switch from
        # soft spring/self restraint to rigid crystal freeze.
        lines_prefix: list[str] = []
        if step.name == "pre_tensile_nvt" and self._has_crystal_freeze(chain):
            lines_prefix = [
                "# Transition: soft restraint → rigid freeze for tensile prep",
                "unfix restrain_crystal",
                "fix freeze_crystal crystal setforce 0.0 0.0 0.0",
                "velocity crystal set 0.0 0.0 0.0",
                "",
            ]

        # Restore default neigh_modify at pre_tensile_nvt (after conservative override)
        if step.name == "pre_tensile_nvt" and chain.study_type == StudyType.LAYER_BULKFF:
            opt = self._opt_profile
            if opt is not None:
                delay = opt.get("neigh_delay", 10)
                every = opt.get("neigh_every", 5)
                check = "yes" if opt.get("neigh_check", True) else "no"
                lines_prefix.append(f"neigh_modify delay {delay} every {every} check {check}")
            else:
                lines_prefix.append("neigh_modify delay 5 every 1 check yes")
            lines_prefix.append("")

        if step.step_type == "minimize":
            step_content = self._generate_minimize(step)
            vel_cmd = self._generate_velocity_create(chain, step_index)
            if vel_cmd:
                step_content += "\n" + vel_cmd
        elif step.step_type == "nvt":
            step_content = self._generate_nvt(
                step, step_index, study_type=chain.study_type, gg_columns=_gg
            )
        elif step.step_type == "npt":
            step_content = self._generate_npt(step, step_index, chain.study_type, gg_columns=_gg)
        elif step.step_type == "nve":
            step_content = self._generate_nve(step, step_index, gg_columns=_gg)
        elif step.step_type == "viscosity":
            step_content = self._generate_viscosity(step, step_index, gg_columns=_gg)
        elif step.step_type == "annealing":
            step_content = self._generate_annealing(step, step_index, study_type=chain.study_type)
        elif step.step_type == "tensile":
            mode = step.extra_params.get("tensile_mode", "continuous")
            if mode == "quasi_static":
                step_content = self._generate_tensile_quasi_static(step, step_index, chain)
            else:
                step_content = self._generate_tensile(step, step_index, chain)
        else:
            logger.warning(f"Unknown step type: {step.step_type}, defaulting to NVT")
            step_content = self._generate_nvt(step, step_index, gg_columns=_gg)

        if lines_prefix:
            return "\n".join(lines_prefix) + step_content
        return step_content

    # ------------------------------------------------------------------
    # Delegated step helpers
    # ------------------------------------------------------------------

    def _generate_velocity_create(self, chain: ProtocolChain, minimize_step_index: int) -> str:
        """Generate velocity initialization after minimize."""
        return _steps_generate_velocity_create(
            chain, minimize_step_index, getattr(self, "_crystal_type_ids", set())
        )

    def _add_checkpoint_commands(self, lines: list[str], step_name: str) -> None:
        """Add periodic checkpoint commands to LAMMPS script if enabled."""
        _steps_add_checkpoint(lines, step_name)

    def _generate_minimize(self, step: ProtocolStep) -> str:
        """Generate minimization commands."""
        return _steps_generate_minimize(step)

    def _generate_nvt(
        self,
        step: ProtocolStep,
        step_index: int,
        study_type: StudyType = StudyType.BULK,
        gg_columns: Sequence[str] = (),
    ) -> str:
        """Generate NVT ensemble commands."""
        return _steps_generate_nvt(
            step,
            step_index,
            study_type,
            gg_columns,
            opt_profile=self._opt_profile,
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
        )

    def _generate_npt(
        self,
        step: ProtocolStep,
        step_index: int,
        study_type: StudyType = StudyType.BULK,
        gg_columns: Sequence[str] = (),
    ) -> str:
        """Generate NPT ensemble commands."""
        return _steps_generate_npt(
            step,
            step_index,
            study_type,
            gg_columns,
            opt_profile=self._opt_profile,
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
        )

    def _generate_nve(
        self,
        step: ProtocolStep,
        step_index: int,
        gg_columns: Sequence[str] = (),
    ) -> str:
        """Generate NVE ensemble commands."""
        return _steps_generate_nve(step, step_index, gg_columns)

    def _generate_viscosity(
        self,
        step: ProtocolStep,
        step_index: int,
        gg_columns: Sequence[str] = (),
    ) -> str:
        """Generate Muller-Plathe viscosity calculation."""
        return _steps_generate_viscosity(step, step_index, gg_columns)

    def _generate_annealing(
        self,
        step: ProtocolStep,
        step_index: int,
        study_type: StudyType = StudyType.BULK,
    ) -> str:
        """Generate annealing cycles."""
        return _steps_generate_annealing(
            step,
            step_index,
            study_type,
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
        )

    def _generate_tensile(
        self,
        step: ProtocolStep,
        step_index: int,
        chain: ProtocolChain,
    ) -> str:
        """Generate LAMMPS grip-pull interface tensile test commands."""
        return _steps_generate_tensile(
            step,
            step_index,
            chain,
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
        )

    def _generate_tensile_quasi_static(
        self,
        step: ProtocolStep,
        step_index: int,
        chain: ProtocolChain,
    ) -> str:
        """Generate LAMMPS quasi-static decohesion tensile test commands."""
        return _steps_generate_tensile_qs(
            step,
            step_index,
            chain,
            crystal_type_ids=getattr(self, "_crystal_type_ids", set()),
        )

    def _get_default_header_template(self) -> str:
        """Return the canonical default header template.

        Prefer the repository file under ``src/templates/header.j2`` so the
        runtime fallback does not drift from the checked-in template. Keep a
        conservative inline copy only for environments where the file is
        missing.
        """
        header_path = Path(__file__).parent.parent / "templates" / "header.j2"
        try:
            return header_path.read_text(encoding="utf-8")
        except OSError:
            return """# LAMMPS input script
# Tier: {{ tier }}
# Force Field: {{ ff_type }}
# Study Type: {{ study_type | default('bulk') }}
# Temperature: {{ temperature_K }} K
# Pressure: {{ pressure_atm }} atm
# Protocol hash: {{ protocol_hash }}
{% if e_intra_method %}
# E_intra Method: {{ e_intra_method }}
{% endif %}
{% if vacuum_cutoff_a is not none %}
# Vacuum Cutoff: {{ '%.2f'|format(vacuum_cutoff_a) }} A
{% endif %}

# Initialization
units real
atom_style full
{% if study_type == 'layer_bulkff' or study_type == 'layer' %}
boundary p p f
{% elif study_type == 'single_molecule_vacuum' and e_intra_method != 'single_molecule_periodic' %}
boundary s s s
{% else %}
boundary p p p
{% endif %}
"""

    def _create_default_templates(self) -> None:
        """Create default LAMMPS templates."""
        templates = {
            "header.j2": self._get_default_header_template(),
            "minimize.j2": """# Energy minimization: {{ name }}
thermo {{ thermo_interval }}
thermo_style custom step pe ke etotal press vol density ebond eangle edihed eimp evdwl ecoul epair emol elong
thermo_modify flush yes
minimize {{ etol }} {{ ftol }} {{ max_iter }} {{ max_eval }}
reset_timestep 0
""",
            "nvt.j2": """# NVT equilibration: {{ name }}
timestep {{ timestep_fs }}
fix {{ fix_id }} {{ thermo_group | default('all') }} nvt temp {{ temp }} {{ temp }} {{ tdamp }}

thermo {{ thermo_interval }}
thermo_style custom step temp pe ke etotal press vol density ebond eangle edihed eimp evdwl ecoul epair emol elong
thermo_modify flush yes
dump d_{{ step_index }} all custom {{ dump_interval }} dump_{{ name }}.lammpstrj id type xu yu zu x y z vx vy vz

run {{ nsteps }}
unfix {{ fix_id }}
undump d_{{ step_index }}
write_restart restart.{{ name }}
""",
            "npt.j2": """# NPT equilibration: {{ name }}
timestep {{ timestep_fs }}
{% if study_type == 'layer_bulkff' or study_type == 'layer' %}
# Layer system: pressure coupling in x,y only (z is fixed)
fix {{ fix_id }} {{ thermo_group | default('all') }} npt temp {{ temp }} {{ temp }} {{ tdamp }} x {{ press }} {{ press }} {{ pdamp }} y {{ press }} {{ press }} {{ pdamp }}
{% else %}
# Bulk system: isotropic pressure coupling
fix {{ fix_id }} {{ thermo_group | default('all') }} npt temp {{ temp }} {{ temp }} {{ tdamp }} iso {{ press }} {{ press }} {{ pdamp }}
{% endif %}

thermo {{ thermo_interval }}
thermo_style custom step temp pe ke etotal press vol density ebond eangle edihed eimp evdwl ecoul epair emol elong
thermo_modify flush yes
dump d_{{ step_index }} all custom {{ dump_interval }} dump_{{ name }}.lammpstrj id type xu yu zu x y z vx vy vz

run {{ nsteps }}
unfix {{ fix_id }}
undump d_{{ step_index }}
write_restart restart.{{ name }}
""",
            "viscosity.j2": """# Viscosity calculation: {{ name }}
timestep {{ timestep_fs }}
fix nvt_{{ step_index }} all nvt temp {{ temp }} {{ temp }} {{ tdamp }}

# Muller-Plathe reverse non-equilibrium MD
fix {{ fix_id }} all viscosity 100 x z 20

compute stress all stress/atom NULL
compute temp_profile all temp/profile 1 0 0 z 20
# Thermostat on the profile-unbiased temperature so it does not erase the
# imposed Muller-Plathe momentum flux (else dv_x/dz collapses into noise).
fix_modify nvt_{{ step_index }} temp temp_profile

# Velocity profile for viscosity calculation (20 bins matching fix viscosity)
compute chunks_{{ step_index }} all chunk/atom bin/1d z lower 0.05 units reduced
fix vprof_{{ step_index }} all ave/chunk 100 10 1000 chunks_{{ step_index }} vx file vprofile_{{ name }}.dat

thermo {{ thermo_interval }}
thermo_style custom step temp pe ke etotal press vol density ebond eangle edihed eimp evdwl ecoul epair emol elong f_{{ fix_id }}
thermo_modify flush yes
dump d_{{ step_index }} all custom {{ dump_interval }} dump_{{ name }}.lammpstrj id type xu yu zu x y z vx vy vz

run {{ nsteps }}
unfix nvt_{{ step_index }}
unfix {{ fix_id }}
unfix vprof_{{ step_index }}
# Reset thermo before write_restart so its System init does not reference the
# now-removed f_{{ fix_id }} fix (LAMMPS: "Could not find thermo fix ID").
thermo_style custom step temp pe ke etotal press vol density ebond eangle edihed eimp evdwl ecoul epair emol elong
uncompute chunks_{{ step_index }}
undump d_{{ step_index }}
write_restart restart.{{ name }}
""",
        }

        for name, content in templates.items():
            template_path = self.engine.template_dir / name
            if not template_path.exists():
                template_path.write_text(content)

    def get_protocol_chain(self, request: ProtocolRequest) -> ProtocolChain:
        """Get the protocol chain for a request without generating files."""
        return self.chain_builder.build(request)

    def validate_request(self, request: ProtocolRequest) -> list[str]:
        """
        Validate a protocol request.

        Args:
            request: Protocol request to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if request.temperature_K <= 0:
            errors.append("Temperature must be positive")

        if request.pressure_atm <= 0:
            errors.append("Pressure must be positive")

        if not request.data_file_path:
            errors.append("Data file path is required")

        return errors
