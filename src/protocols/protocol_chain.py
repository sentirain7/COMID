"""
Protocol chain builder for constructing simulation workflows.

Builds sequences of simulation steps based on tier policies
and stabilization requirements.
"""

from dataclasses import dataclass, field
from typing import Any

from common.logging import get_logger
from contracts.policies.stabilization import StabilizationChain, StabilizationStep
from contracts.policies.tier import TierPolicy
from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType

logger = get_logger("protocols.protocol_chain")


@dataclass
class ProtocolStep:
    """A single step in the protocol chain."""

    name: str
    step_type: str  # minimize, nvt, npt, viscosity, annealing
    ensemble: str | None = None  # nvt, npt, nve
    temperature_K: float = 298.0
    pressure_atm: float = 1.0
    duration: str = "100 ps"
    timestep_fs: float = 1.0
    thermo_interval: int = 1000
    dump_interval: int = 10000
    constraints: dict = field(default_factory=dict)
    extra_params: dict = field(default_factory=dict)


@dataclass
class ProtocolChain:
    """Complete protocol chain for a simulation."""

    tier: RunTier
    steps: list[ProtocolStep]
    ff_type: FFType
    temperature_K: float
    pressure_atm: float
    study_type: StudyType = StudyType.BULK
    data_file_path: str = ""
    sampling_metadata: dict[str, Any] = field(default_factory=dict)
    # PR 2 (Method 1a SSOT): provenance fields populated at LAMMPS input
    # generation time so the storage path does not need to re-read env vars.
    e_intra_method: str | None = None
    vacuum_cutoff_a: float | None = None


class ProtocolChainBuilder:
    """
    Builder for protocol chains.

    Constructs simulation protocols based on tier requirements
    and stabilization chains.
    """

    def __init__(
        self,
        stabilization_chain: StabilizationChain | None = None,
        tier_policy: TierPolicy | None = None,
    ):
        """
        Initialize protocol chain builder.

        Args:
            stabilization_chain: Stabilization chain policy
            tier_policy: Tier policy for time/step limits
        """
        self.stabilization_chain = stabilization_chain or StabilizationChain()
        self.tier_policy = tier_policy or TierPolicy()

    def build(self, request: ProtocolRequest) -> ProtocolChain:
        """
        Build a protocol chain from a request.

        Args:
            request: Protocol request with tier and parameters

        Returns:
            Complete protocol chain
        """
        tier = request.run_tier
        temperature_K = request.temperature_K
        pressure_atm = request.pressure_atm

        # Store tier for use in _convert_step
        self._current_tier = tier

        # Initialize sampling metadata tracking
        self._sampling_metadata: dict[str, Any] = {
            "tier": tier.value,
            "adaptive_enabled": False,
            "steps": [],
        }

        # Determine chain key: layer/tensile chain guard (Phase 4.3)
        tier_key = tier.value
        tensile_spec = getattr(request, "tensile_spec", None)
        if request.study_type == StudyType.LAYER_BULKFF:
            if tensile_spec is not None and tensile_spec.enabled:
                from contracts.schemas import TensileMode

                if getattr(tensile_spec, "mode", None) == TensileMode.QUASI_STATIC:
                    tier_key = "tensile_layer_qs"
                else:
                    tier_key = "tensile_layer"
            else:
                tier_key = "layer"

        # Get stabilization steps for this tier
        stab_steps = self.stabilization_chain.get_chain(tier_key)

        # Inject high-temperature/high-pressure equilibration steps if enabled
        eq_settings = getattr(request, "equilibration_settings", None)
        if eq_settings is not None and eq_settings.enabled:
            stab_steps = self._inject_equilibration_steps(stab_steps, eq_settings)
            logger.info(
                "Injected high-temp/high-pressure equilibration: "
                f"NVT@{eq_settings.high_temp_nvt_temperature_K}K ({eq_settings.high_temp_nvt_duration_ps}ps), "
                f"NPT@{eq_settings.high_pressure_npt_temperature_K}K/{eq_settings.high_pressure_npt_pressure_atm}atm ({eq_settings.high_pressure_npt_duration_ps}ps)"
            )

        # Skip requested stages
        skip_keys = getattr(request, "skip_stage_keys", None)
        if skip_keys:
            skip_set = set(skip_keys)
            stab_steps = [s for s in stab_steps if s.name not in skip_set]

        # Convert to protocol steps
        protocol_steps = []
        for stab_step in stab_steps:
            protocol_step = self._convert_step(stab_step, temperature_K, pressure_atm)
            # Inject TensileSpec parameters into tensile steps
            if protocol_step.step_type == "tensile" and tensile_spec is not None:
                self._inject_tensile_params(protocol_step, request)
            protocol_steps.append(protocol_step)

        return ProtocolChain(
            tier=tier,
            steps=protocol_steps,
            ff_type=request.ff_type,
            temperature_K=temperature_K,
            pressure_atm=pressure_atm,
            study_type=request.study_type,
            data_file_path=request.data_file_path,
            sampling_metadata=self._sampling_metadata,
            e_intra_method=request.e_intra_method,
        )

    def _inject_equilibration_steps(
        self,
        stab_steps: list[StabilizationStep],
        eq_settings: Any,
    ) -> list[StabilizationStep]:
        """Inject high-temperature/high-pressure equilibration steps after minimize.

        Protocol flow becomes:
        minimize -> [high_temp_nvt @ high_T] -> [high_pressure_npt @ high_T, high_P] -> nvt @ target_T -> npt @ target_T

        Args:
            stab_steps: Original stabilization steps
            eq_settings: Equilibration settings with temperatures/pressures/durations

        Returns:
            Modified stabilization steps with injected equilibration phases
        """
        # Create new equilibration steps
        high_temp_nvt = StabilizationStep(
            name="high_temp_nvt",
            type="nvt",
            duration=f"{eq_settings.high_temp_nvt_duration_ps} ps",
            parameters={
                "temperature_K": eq_settings.high_temp_nvt_temperature_K,
                "thermostat": "nose-hoover",
                "tdamp": 100.0,
            },
        )

        high_pressure_npt = StabilizationStep(
            name="high_pressure_npt",
            type="npt",
            duration=f"{eq_settings.high_pressure_npt_duration_ps} ps",
            parameters={
                "temperature_K": eq_settings.high_pressure_npt_temperature_K,
                "pressure_atm": eq_settings.high_pressure_npt_pressure_atm,
                "thermostat": "nose-hoover",
                "barostat": "nose-hoover",
                "tdamp": 100.0,
                "pdamp": 1000.0,
            },
        )

        # Find minimize step index and insert after it
        result = []
        for _i, step in enumerate(stab_steps):
            result.append(step)
            if step.type.lower() == "minimize":
                result.append(high_temp_nvt)
                result.append(high_pressure_npt)

        return result

    def _convert_step(
        self,
        stab_step: StabilizationStep,
        temperature_K: float,
        pressure_atm: float,
    ) -> ProtocolStep:
        """Convert a stabilization step to a protocol step."""
        step_type = self._determine_step_type(stab_step)
        ensemble = self._determine_ensemble(stab_step)

        # Get parameters from the step's parameters dict
        params = stab_step.parameters or {}

        # Override temperature for temperature ramp steps
        step_temp = params.get("temperature_K", temperature_K)

        # Normalize minimize parameters → constraints
        constraints = params.get("constraints", {})
        if step_type == "minimize":
            constraints = {
                "etol": params.get("etol", 1e-4),
                "ftol": params.get("ftol", 1e-6),
                "max_iter": params.get("maxiter", 10000),
                "max_eval": params.get("maxeval", 100000),
            }

        # Annealing: inject temp_low_K from request temperature_K
        extra = dict(params)
        if step_type == "annealing":
            extra["temp_low_K"] = temperature_K

        # Compute adaptive dump_interval from sampling policy
        dump_interval = self._compute_dump_interval(
            step_type=step_type,
            duration_str=stab_step.duration or "100 ps",
            timestep_fs=params.get("timestep_fs", 1.0),
            step_name=stab_step.name,
        )

        return ProtocolStep(
            name=stab_step.name,
            step_type=step_type,
            ensemble=ensemble,
            temperature_K=step_temp,
            pressure_atm=params.get("pressure_atm", pressure_atm),
            duration=stab_step.duration or "100 ps",
            timestep_fs=params.get("timestep_fs", 1.0),
            dump_interval=dump_interval,
            constraints=constraints,
            extra_params=extra,
        )

    def _compute_dump_interval(
        self,
        step_type: str,
        duration_str: str,
        timestep_fs: float,
        step_name: str,
    ) -> int:
        """Compute adaptive dump interval based on tier sampling policy.

        Formula: clamp(total_steps // target_frames, min_interval, max_interval)

        Args:
            step_type: Type of simulation step (minimize, nvt, npt, etc.)
            duration_str: Duration string (e.g., "300 ps", "1000 steps")
            timestep_fs: Timestep in femtoseconds
            step_name: Name of the step for metadata tracking

        Returns:
            Computed dump interval in steps
        """
        # No dump for minimize steps
        if step_type == "minimize":
            return 0

        # Get tier config and sampling policy
        tier_config = self.tier_policy.get_tier_config(self._current_tier)
        sampling = tier_config.sampling

        # Legacy fallback: no sampling policy configured
        if sampling is None or not sampling.enabled:
            return 10000

        # Parse duration to total steps
        total_steps = self._parse_duration_to_steps(duration_str, timestep_fs)

        # Determine target frames based on step type
        # Production phases: npt, viscosity
        # Equilibration phases: nvt, nve, annealing
        is_production = step_type in ("npt", "viscosity")
        target_frames = (
            sampling.production_target_frames
            if is_production
            else sampling.equilibration_target_frames
        )

        # Calculate raw interval
        if target_frames > 0:
            raw_interval = total_steps // target_frames
        else:
            raw_interval = sampling.min_interval_steps

        # Clamp to [min, max] range
        dump_interval = max(
            sampling.min_interval_steps,
            min(raw_interval, sampling.max_interval_steps),
        )

        # Track sampling metadata
        self._sampling_metadata["adaptive_enabled"] = True
        self._sampling_metadata["steps"].append(
            {
                "name": step_name,
                "step_type": step_type,
                "total_steps": total_steps,
                "target_frames": target_frames,
                "raw_interval": raw_interval,
                "dump_interval": dump_interval,
                "is_production": is_production,
            }
        )

        return dump_interval

    def _parse_duration_to_steps(self, duration_str: str, timestep_fs: float) -> int:
        """Parse duration string to total steps.

        Args:
            duration_str: Duration string (e.g., "300 ps", "1000 steps", "5 ns")
            timestep_fs: Timestep in femtoseconds

        Returns:
            Total number of MD steps
        """
        duration_str = duration_str.strip().lower()

        if "steps" in duration_str:
            # Direct step count
            return int(duration_str.replace("steps", "").strip())
        elif "ns" in duration_str:
            # Nanoseconds
            duration_ns = float(duration_str.replace("ns", "").strip())
            duration_fs = duration_ns * 1e6  # ns -> fs
            return int(duration_fs / timestep_fs)
        elif "ps" in duration_str:
            # Picoseconds
            duration_ps = float(duration_str.replace("ps", "").strip())
            duration_fs = duration_ps * 1000  # ps -> fs
            return int(duration_fs / timestep_fs)
        elif "fs" in duration_str:
            # Femtoseconds
            duration_fs = float(duration_str.replace("fs", "").strip())
            return int(duration_fs / timestep_fs)
        else:
            # Assume picoseconds as default
            try:
                duration_ps = float(duration_str)
                duration_fs = duration_ps * 1000
                return int(duration_fs / timestep_fs)
            except ValueError:
                return 100000  # Fallback

    def _determine_step_type(self, stab_step: StabilizationStep) -> str:
        """Determine the step type from stabilization step."""
        # First check the explicit type field
        step_type = stab_step.type.lower()
        if step_type in ("minimize", "nvt", "npt", "nve", "viscosity", "tensile", "annealing"):
            return step_type

        # Fall back to name-based detection
        name_lower = stab_step.name.lower()

        if "minimize" in name_lower or "min" in name_lower:
            return "minimize"
        elif "tensile" in name_lower or "pull" in name_lower:
            return "tensile"
        elif "anneal" in name_lower:
            return "annealing"
        elif "viscosity" in name_lower or "nemd" in name_lower or "muller" in name_lower:
            return "viscosity"
        elif "nvt" in name_lower:
            return "nvt"
        elif "npt" in name_lower:
            return "npt"
        elif "nve" in name_lower:
            return "nve"
        else:
            # Default to NVT for equilibration
            return "nvt"

    def _determine_ensemble(self, stab_step: StabilizationStep) -> str | None:
        """Determine ensemble from step type or name."""
        step_type = stab_step.type.lower()

        if step_type == "minimize":
            return None  # No ensemble for minimization
        elif step_type in ("nvt", "npt", "nve"):
            return step_type
        elif step_type == "viscosity":
            return "nvt"  # Viscosity uses NVT
        elif step_type == "tensile":
            return "nvt"  # Mobile atoms use NVT
        elif step_type == "annealing":
            return "nvt"  # Annealing uses NVT with temperature ramping

        # Fall back to name-based detection
        name_lower = stab_step.name.lower()
        if "minimize" in name_lower:
            return None
        elif "nve" in name_lower:
            return "nve"
        elif "npt" in name_lower:
            return "npt"
        else:
            return "nvt"

    def _inject_tensile_params(self, step: ProtocolStep, request: ProtocolRequest) -> None:
        """Inject TensileSpec + LayerSpec parameters into tensile step."""
        ts = request.tensile_spec
        if ts is None:
            return

        from contracts.schemas import TensileMode

        step.extra_params.update(
            {
                "pull_velocity_A_per_fs": ts.pull_velocity_A_per_fs,
                "grip_thickness_angstrom": ts.grip_thickness_angstrom,
                "max_strain": ts.max_strain,
                "output_interval_steps": ts.output_interval_steps,
                "tensile_mode": ts.mode.value,
            }
        )

        # QS-specific params
        if ts.mode == TensileMode.QUASI_STATIC:
            step.extra_params.update(
                {
                    "displacement_increment_angstrom": ts.displacement_increment_angstrom,
                    "relax_steps": ts.relax_steps,
                    "force_average_steps": ts.force_average_steps,
                }
            )

        # Extract z-boundaries from LayerSpec
        layer_spec = getattr(request, "layer_spec", None)
        if layer_spec is not None:
            # Prefer explicit boundary metadata from build result when provided.
            explicit_boundary_z = getattr(layer_spec, "layer_boundary_z", None)
            if explicit_boundary_z and len(explicit_boundary_z) >= 2:
                all_z = [float(z) for z in explicit_boundary_z if isinstance(z, int | float)]
            else:
                boundaries = layer_spec.get_layer_boundaries()
                all_z = [b for pair in boundaries.values() for b in pair]

            # Crystal grip ranges (from LayerSpec, not TensileSpec)
            bottom_grip = getattr(layer_spec, "bottom_grip_z_range", None)
            top_grip = getattr(layer_spec, "top_grip_z_range", None)
            if bottom_grip is not None:
                step.extra_params["bottom_grip_z"] = bottom_grip
            if top_grip is not None:
                step.extra_params["top_grip_z"] = top_grip

            if all_z:
                z_lo, z_hi = min(all_z), max(all_z)
                step.extra_params["z_lo_grip"] = z_lo
                step.extra_params["z_hi_grip"] = z_hi

                # Mixed mode: explicit grip range per side, fallback to thickness
                bottom_end = bottom_grip[1] if bottom_grip else z_lo + ts.grip_thickness_angstrom
                top_start = top_grip[0] if top_grip else z_hi - ts.grip_thickness_angstrom
                gap = top_start - bottom_end

                if gap > 0:
                    max_disp = gap * ts.max_strain
                    if ts.mode == TensileMode.QUASI_STATIC:
                        # QS: ceil so max_strain is reached; effective_inc ≤ requested
                        import math

                        n_disp_steps = max(
                            1, math.ceil(max_disp / ts.displacement_increment_angstrom)
                        )
                        total_fs = n_disp_steps * ts.relax_steps * 1.0
                        step.duration = f"{total_fs / 1000.0:.1f} ps"
                    else:
                        time_fs = max_disp / ts.pull_velocity_A_per_fs
                        step.duration = f"{time_fs / 1000.0:.1f} ps"

    def get_total_duration_ps(self, chain: ProtocolChain) -> float:
        """Calculate total duration of protocol chain in ps."""
        from protocols.template_engine import TemplateEngine

        total = 0.0

        for step in chain.steps:
            if step.step_type != "minimize":
                total += TemplateEngine._filter_duration_to_ps(step.duration)

        return total

    def get_total_steps(self, chain: ProtocolChain, timestep_fs: float = 1.0) -> int:
        """Calculate total number of MD steps."""
        from protocols.template_engine import TemplateEngine

        total = 0

        for step in chain.steps:
            if step.step_type == "minimize":
                # Use duration (expected step budget) not max_iter (solver upper bound).
                dur_str = (step.duration or "").strip().lower()
                if "steps" in dur_str:
                    total += int(dur_str.replace("steps", "").strip())
                else:
                    # fallback: no duration → use max_iter
                    total += step.constraints.get("max_iter", 10000)
            else:
                total += TemplateEngine._filter_duration_to_steps(step.duration, timestep_fs)

        return total

    def estimate_runtime_hours(
        self,
        chain: ProtocolChain,
        atom_count: int,
        gpu_speed: float = 50.0,  # ns/day/1000atoms
    ) -> float:
        """
        Estimate runtime in hours.

        Args:
            chain: Protocol chain
            atom_count: Number of atoms
            gpu_speed: GPU performance (ns/day per 1000 atoms)

        Returns:
            Estimated runtime in hours
        """
        total_ps = self.get_total_duration_ps(chain)
        total_ns = total_ps / 1000.0

        # Scale by atom count
        speed_ns_day = gpu_speed * (atom_count / 1000.0)
        if speed_ns_day > 0:
            days = total_ns / speed_ns_day
            hours = days * 24
        else:
            hours = 0.0

        return hours
