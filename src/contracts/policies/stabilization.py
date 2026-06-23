"""
Stabilization chain policy - SSOT for protocol step definitions.

All sessions must use this policy for protocol generation.
"""

import hashlib
import json

from pydantic import BaseModel, Field


class StabilizationStep(BaseModel):
    """Definition of a single stabilization step."""

    name: str = Field(..., description="Step name")
    type: str = Field(..., description="Step type: minimize, nvt, npt, custom")
    duration: str | None = Field(None, description="Duration (ps or steps)")
    parameters: dict = Field(default_factory=dict, description="Step parameters")


class StabilizationChain(BaseModel):
    """
    Stabilization chain policy - SSOT for protocol definitions.

    This defines the stabilization steps for each tier.
    """

    chains: dict[str, list[StabilizationStep]] = Field(
        default={
            "screening": [
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="1000 steps",
                    parameters={
                        "etol": 1e-4,
                        "ftol": 1e-6,
                        "maxiter": 10000,
                        "maxeval": 100000,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="300 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_production",
                    type="npt",
                    duration="2000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
            ],
            "confirm": [
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="5000 steps",
                    parameters={
                        "etol": 1e-5,
                        "ftol": 1e-7,
                        "maxiter": 50000,
                        "maxeval": 500000,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="300 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_production",
                    type="npt",
                    duration="3000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
            ],
            "viscosity": [
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="5000 steps",
                    parameters={
                        "etol": 1e-5,
                        "ftol": 1e-7,
                        "maxiter": 50000,
                        "maxeval": 500000,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="300 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_production",
                    type="npt",
                    duration="3000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
                StabilizationStep(
                    name="viscosity_nemd",
                    type="nemd",
                    duration="5000 ps",
                    parameters={
                        "method": "muller_plathe",
                        "swap_every": 100,
                    },
                ),
            ],
            "validation": [
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="1000 steps",
                    parameters={
                        "etol": 1e-4,
                        "ftol": 1e-6,
                        "maxiter": 10000,
                        "maxeval": 100000,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="300 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "qeq_every": 1,
                    },
                ),
                StabilizationStep(
                    name="npt_production",
                    type="npt",
                    duration="1000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                        "qeq_every": 1,
                    },
                ),
            ],
            "tensile_layer": [
                # 1. minimize: 10000 steps (literature: 5000-10000)
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="10000 steps",
                    parameters={
                        "etol": 1e-5,
                        "ftol": 1e-7,
                        "maxiter": 50000,
                        "maxeval": 500000,
                    },
                ),
                # 2. High-T relaxation: NVT 10K→500K ramp, 100 ps (resolve overlaps)
                StabilizationStep(
                    name="high_temp_nvt",
                    type="nvt",
                    duration="100 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "temperature_K": 500.0,
                        "temp_start_K": 10.0,
                    },
                ),
                # 3. Annealing: 5 cycles T_target↔500K, total 1000 ps
                StabilizationStep(
                    name="annealing_cycles",
                    type="annealing",
                    duration="1000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "n_cycles": 5,
                        "temp_high_K": 500.0,
                        "duration_per_half_cycle_ps": 100.0,
                    },
                ),
                # 4. NVT equilibration: 500 ps (post-annealing stabilization)
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="500 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                # 5. NPT equilibration: 2000 ps (interface density convergence)
                StabilizationStep(
                    name="npt_equilibration",
                    type="npt",
                    duration="2000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
                # 6. Pre-tensile NVT: 100 ps (relax from NPT before tensile)
                StabilizationStep(
                    name="pre_tensile_nvt",
                    type="nvt",
                    duration="100 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                # 7. Tensile pull: v=0.00005 A/fs (5 m/s, literature lower bound)
                StabilizationStep(
                    name="tensile_pull",
                    type="tensile",
                    duration="2000 ps",
                    parameters={
                        "pull_velocity_A_per_fs": 0.00005,
                        "grip_thickness_angstrom": 20.0,
                        "max_strain": 0.5,
                        "output_interval_steps": 100,
                    },
                ),
            ],
            "tensile_layer_qs": [
                # Quasi-static decohesion: same equilibration as tensile_layer,
                # but with longer pre-tensile NVT and QS tensile step.
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="10000 steps",
                    parameters={
                        "etol": 1e-5,
                        "ftol": 1e-7,
                        "maxiter": 50000,
                        "maxeval": 500000,
                    },
                ),
                StabilizationStep(
                    name="high_temp_nvt",
                    type="nvt",
                    duration="100 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "temperature_K": 500.0,
                        "temp_start_K": 10.0,
                    },
                ),
                StabilizationStep(
                    name="annealing_cycles",
                    type="annealing",
                    duration="1000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "n_cycles": 5,
                        "temp_high_K": 500.0,
                        "duration_per_half_cycle_ps": 100.0,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="500 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_equilibration",
                    type="npt",
                    duration="2000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
                StabilizationStep(
                    name="pre_tensile_nvt",
                    type="nvt",
                    duration="200 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="tensile_pull",
                    type="tensile",
                    duration="auto",
                    parameters={
                        "tensile_mode": "quasi_static",
                        "displacement_increment_angstrom": 0.5,
                        "relax_steps": 10000,
                        "force_average_steps": 1000,
                        "grip_thickness_angstrom": 20.0,
                        "max_strain": 0.5,
                        "output_interval_steps": 100,
                    },
                ),
            ],
            "layer": [
                # Generic layered workflow (no tensile pull)
                # Same as tensile_layer minus the tensile_pull step
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="10000 steps",
                    parameters={
                        "etol": 1e-5,
                        "ftol": 1e-7,
                        "maxiter": 50000,
                        "maxeval": 500000,
                    },
                ),
                StabilizationStep(
                    name="high_temp_nvt",
                    type="nvt",
                    duration="100 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "temperature_K": 500.0,
                        "temp_start_K": 10.0,
                    },
                ),
                StabilizationStep(
                    name="annealing_cycles",
                    type="annealing",
                    duration="1000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                        "n_cycles": 5,
                        "temp_high_K": 500.0,
                        "duration_per_half_cycle_ps": 100.0,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="500 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_equilibration",
                    type="npt",
                    duration="2000 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
            ],
            "screening_mini": [
                # Minimal version for E2E smoke test
                StabilizationStep(
                    name="minimize",
                    type="minimize",
                    duration="100 steps",
                    parameters={
                        "etol": 1e-3,
                        "ftol": 1e-5,
                        "maxiter": 1000,
                        "maxeval": 10000,
                    },
                ),
                StabilizationStep(
                    name="nvt_equilibration",
                    type="nvt",
                    duration="50 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "tdamp": 100.0,
                    },
                ),
                StabilizationStep(
                    name="npt_production",
                    type="npt",
                    duration="100 ps",
                    parameters={
                        "thermostat": "nose-hoover",
                        "barostat": "nose-hoover",
                        "tdamp": 100.0,
                        "pdamp": 1000.0,
                    },
                ),
            ],
        },
        description="Stabilization chains by tier",
    )

    def get_chain(self, tier: str) -> list[StabilizationStep]:
        """
        Get stabilization chain for a tier.

        Args:
            tier: Run tier name

        Returns:
            List of stabilization steps
        """
        if tier not in self.chains:
            raise ValueError(f"Unknown tier: {tier}")
        return self.chains[tier]

    def get_step_names(self, tier: str) -> list[str]:
        """Get list of step names for a tier."""
        return [step.name for step in self.get_chain(tier)]

    def get_protocol_hash(self, tier: str) -> str:
        """
        Generate reproducibility hash for protocol.

        Args:
            tier: Run tier name

        Returns:
            8-character hash string
        """
        chain = self.get_chain(tier)
        chain_data = [step.model_dump() for step in chain]
        json_str = json.dumps(chain_data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()[:8]

    def get_total_duration_ps(self, tier: str) -> float:
        """
        Calculate total simulation duration for a tier.

        Args:
            tier: Run tier name

        Returns:
            Total duration in ps
        """
        total = 0.0
        for step in self.get_chain(tier):
            if step.duration:
                duration_str = step.duration.strip().lower()
                # Check for "ps" (picoseconds) but NOT "steps"
                if duration_str.endswith(" ps") or (
                    duration_str.endswith("ps") and "step" not in duration_str
                ):
                    # Remove "ps" suffix and parse the number
                    value_str = duration_str.replace("ps", "").strip()
                    total += float(value_str)
                # Minimization steps (e.g., "1000 steps") don't count toward simulation time
        return total

    def get_estimated_steps(self, tier: str, dt_fs: float) -> int:
        """
        Estimate total timesteps for a tier.

        Args:
            tier: Run tier name
            dt_fs: Timestep in femtoseconds

        Returns:
            Estimated total steps
        """
        total_ps = self.get_total_duration_ps(tier)
        # Convert ps to fs, then divide by dt
        total_fs = total_ps * 1000.0
        return int(total_fs / dt_fs)

    def get_stage_steps(self, tier: str, dt_fs: float = 1.0) -> list[dict]:
        """
        Get step counts for each stage in a tier.

        Args:
            tier: Run tier name
            dt_fs: Timestep in femtoseconds (default 1.0)

        Returns:
            List of {"name": str, "type": str, "steps": int, "cumulative": int}
        """
        stages = []
        cumulative = 0

        for step in self.get_chain(tier):
            if step.duration:
                duration_str = step.duration.strip().lower()
                if "steps" in duration_str:
                    # For minimize: this is the expected step budget for progress display.
                    # Actual iterations may be less (early convergence) or up to maxiter.
                    # duration ≤ maxiter is guaranteed; minimize usually converges faster.
                    steps = int(duration_str.replace("steps", "").strip())
                elif "ps" in duration_str:
                    # "300 ps" -> 300000 (at dt=1.0fs)
                    ps = float(duration_str.replace("ps", "").strip())
                    steps = int(ps * 1000 / dt_fs)
                else:
                    steps = 0
            else:
                steps = 0

            cumulative += steps
            stages.append(
                {
                    "name": step.name,
                    "type": step.type,
                    "steps": steps,
                    "cumulative": cumulative,
                }
            )

        return stages

    def get_stage_info(self, tier: str, current_step: int, dt_fs: float = 1.0) -> dict:
        """
        Get current stage information based on current step.

        Args:
            tier: "screening", "confirm", "viscosity", "validation"
            current_step: Current LAMMPS step
            dt_fs: Timestep in femtoseconds

        Returns:
            Dictionary with stage information:
            - current_stage: Stage name (e.g., "nvt_equilibration")
            - stage_type: Stage type (e.g., "nvt")
            - stage_index: Current stage number (1-based)
            - total_stages: Total number of stages
            - stage_step: Current step within this stage
            - stage_total_steps: Total steps in this stage
            - stage_percent: Progress within this stage (%)
        """
        stages = self.get_stage_steps(tier, dt_fs)
        total_stages = len(stages)

        prev_cumulative = 0
        for i, stage in enumerate(stages):
            if current_step < stage["cumulative"]:
                stage_step = current_step - prev_cumulative
                stage_total = stage["steps"]
                stage_percent = round(stage_step / stage_total * 100, 1) if stage_total > 0 else 0

                return {
                    "current_stage": stage["name"],
                    "stage_type": stage["type"],
                    "stage_index": i + 1,
                    "total_stages": total_stages,
                    "stage_step": stage_step,
                    "stage_total_steps": stage_total,
                    "stage_percent": stage_percent,
                }
            prev_cumulative = stage["cumulative"]

        # current_step exceeds total (finished)
        last = stages[-1]
        return {
            "current_stage": last["name"],
            "stage_type": last["type"],
            "stage_index": total_stages,
            "total_stages": total_stages,
            "stage_step": last["steps"],
            "stage_total_steps": last["steps"],
            "stage_percent": 100.0,
        }


# Default instance for convenience
DEFAULT_STABILIZATION_CHAIN = StabilizationChain()
