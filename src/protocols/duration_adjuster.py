"""
Protocol chain duration adjuster - applies user overrides to built chains.

This module provides post-processing capability for ProtocolChain objects,
allowing users to customize stage durations without modifying the SSOT
(contracts/policies/stabilization.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as EQ_POLICY
from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN
from protocols.protocol_chain import ProtocolChain

if TYPE_CHECKING:
    from contracts.policies.tier import TierPolicy


class StageDurationOverride(BaseModel):
    """User-specified duration override for a stage."""

    stage_name: str = Field(..., description="Stage name (e.g., 'nvt_equilibration')")
    duration_ps: float | None = Field(None, ge=0, description="Duration in picoseconds")
    duration_steps: int | None = Field(None, ge=0, description="Duration in steps (for minimize)")


class ProtocolChainAdjuster:
    """
    Post-processes protocol chains to apply duration overrides.

    SSOT (stabilization.py) is read-only - this class applies overrides
    to the already-built ProtocolChain without modifying contracts.

    Example:
        >>> adjuster = ProtocolChainAdjuster()
        >>> overrides = [
        ...     StageDurationOverride(stage_name="nvt_equilibration", duration_ps=500),
        ...     StageDurationOverride(stage_name="npt_production", duration_ps=2000),
        ... ]
        >>> errors = adjuster.validate_overrides("screening", overrides)
        >>> if not errors:
        ...     chain = adjuster.apply_overrides(chain, overrides)
    """

    def __init__(self, tier_policy: TierPolicy | None = None) -> None:
        """Initialize with reference to SSOT stabilization chain.

        Args:
            tier_policy: Optional custom tier policy for dump interval calculation.
                         If not provided, DEFAULT_TIER_POLICY is used.
        """
        self.stabilization_chain = DEFAULT_STABILIZATION_CHAIN
        self._tier_policy = tier_policy  # Stored for apply_overrides
        self._equilibration_compatible_tiers = {
            "screening",
            "confirm",
            "viscosity",
            "validation",
            "screening_mini",
        }

    def _get_equilibration_stage_defaults(self) -> dict[str, dict]:
        """Return validation defaults for runtime-injected equilibration stages."""
        return {
            "high_temp_nvt": {
                "type": "nvt",
                "duration_ps": EQ_POLICY.high_temp_nvt_duration_ps,
                "duration_steps": None,
                "editable": True,
            },
            "high_pressure_npt": {
                "type": "npt",
                "duration_ps": EQ_POLICY.high_pressure_npt_duration_ps,
                "duration_steps": None,
                "editable": True,
            },
        }

    def _get_validation_defaults(
        self,
        tier: str,
        *,
        include_injected_equilibration: bool = False,
    ) -> dict[str, dict]:
        """Return stage defaults for validation, optionally including injected stages."""
        defaults = self.get_default_durations(tier)
        if include_injected_equilibration and tier in self._equilibration_compatible_tiers:
            defaults.update(self._get_equilibration_stage_defaults())
        return defaults

    def get_valid_stages(
        self,
        tier: str,
        *,
        include_injected_equilibration: bool = False,
    ) -> list[str]:
        """
        Get valid stage names for a tier from SSOT.

        Args:
            tier: Run tier name (screening, confirm, viscosity, validation)
            include_injected_equilibration: Whether to include runtime-injected
                equilibration stages accepted by bulk workflows.

        Returns:
            List of valid stage names for the tier
        """
        return list(
            self._get_validation_defaults(
                tier,
                include_injected_equilibration=include_injected_equilibration,
            ).keys()
        )

    def get_default_durations(self, tier: str) -> dict[str, dict]:
        """
        Get default durations for all stages in a tier from SSOT.

        Args:
            tier: Run tier name

        Returns:
            Dict mapping stage_name to {duration_ps, duration_steps, type}
        """
        chain = self.stabilization_chain.get_chain(tier)
        result = {}

        for step in chain:
            duration_ps = None
            duration_steps = None

            if step.duration:
                dur_lower = step.duration.strip().lower()
                if "steps" in dur_lower:
                    duration_steps = int(dur_lower.replace("steps", "").strip())
                elif "ps" in dur_lower:
                    duration_ps = float(dur_lower.replace("ps", "").strip())

            result[step.name] = {
                "type": step.type,
                "duration_ps": duration_ps,
                "duration_steps": duration_steps,
                "editable": step.type != "minimize" or duration_steps is not None,
            }

        return result

    def validate_overrides(self, tier: str, overrides: list[StageDurationOverride]) -> list[str]:
        """
        Validate overrides against SSOT.

        Args:
            tier: Run tier name
            overrides: List of duration overrides to validate

        Returns:
            List of error messages (empty if all valid)
        """
        errors = []
        defaults = self._get_validation_defaults(tier, include_injected_equilibration=True)
        valid_stages = list(defaults.keys())

        for override in overrides:
            # Check stage name exists
            if override.stage_name not in valid_stages:
                errors.append(
                    f"Invalid stage '{override.stage_name}' for tier '{tier}'. "
                    f"Valid stages: {valid_stages}"
                )
                continue

            # Check duration is specified
            if override.duration_ps is None and override.duration_steps is None:
                errors.append(f"No duration specified for stage '{override.stage_name}'")
                continue

            # Check appropriate duration type for stage
            stage_info = defaults.get(override.stage_name, {})
            stage_type = stage_info.get("type", "")

            if stage_type == "minimize":
                # Minimize should use steps
                if override.duration_ps is not None and override.duration_steps is None:
                    errors.append(
                        f"Stage '{override.stage_name}' is minimization - "
                        "use duration_steps instead of duration_ps"
                    )
            else:
                # Other stages should use ps
                if override.duration_steps is not None and override.duration_ps is None:
                    errors.append(
                        f"Stage '{override.stage_name}' is {stage_type} - "
                        "use duration_ps instead of duration_steps"
                    )

        return errors

    def apply_overrides(
        self, chain: ProtocolChain, overrides: list[StageDurationOverride]
    ) -> ProtocolChain:
        """
        Apply duration overrides to a built ProtocolChain.

        Modifies the chain in place and returns it.
        Also recalculates dump_interval and sampling_metadata to maintain consistency.

        Args:
            chain: The protocol chain to modify
            overrides: List of duration overrides to apply

        Returns:
            Modified protocol chain
        """
        from contracts.policies.tier import DEFAULT_TIER_POLICY

        # Use injected tier_policy if provided, otherwise fall back to default
        # This ensures consistency with the policy used during chain building
        tier_policy = self._tier_policy if self._tier_policy is not None else DEFAULT_TIER_POLICY

        override_map = {o.stage_name: o for o in overrides}
        modified_steps = []

        for step in chain.steps:
            if step.name in override_map:
                override = override_map[step.name]

                if override.duration_ps is not None:
                    step.duration = f"{override.duration_ps} ps"
                elif override.duration_steps is not None:
                    step.duration = f"{override.duration_steps} steps"

                modified_steps.append(step.name)

        # Recalculate dump_interval and sampling_metadata for modified steps (v00.97.00)
        if modified_steps:
            self._recalculate_dump_intervals(chain, modified_steps, tier_policy)

        return chain

    def _recalculate_dump_intervals(  # type: ignore[no-untyped-def]
        self,
        chain: ProtocolChain,
        modified_steps: list[str],
        tier_policy,
    ) -> None:
        """Recalculate dump_interval and sampling_metadata for modified steps.

        Args:
            chain: The protocol chain to update
            modified_steps: List of step names that were modified
            tier_policy: Tier policy for sampling config
        """
        tier_config = tier_policy.get_tier_config(chain.tier)
        sampling = tier_config.sampling

        if sampling is None or not sampling.enabled:
            return

        # Reset sampling metadata
        steps_list: list[dict] = []
        new_sampling_metadata: dict[str, object] = {
            "tier": chain.tier.value,
            "adaptive_enabled": True,
            "steps": steps_list,
            "duration_overrides_applied": True,
        }

        for step in chain.steps:
            # Skip minimize steps
            if step.step_type == "minimize":
                continue

            # Parse duration to total steps
            total_steps = self._parse_duration_to_steps(step.duration, step.timestep_fs)

            # Determine target frames based on step type
            is_production = step.step_type in ("npt", "viscosity")
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

            # Update step's dump_interval
            step.dump_interval = dump_interval

            # Track in sampling metadata
            steps_list.append(
                {
                    "name": step.name,
                    "step_type": step.step_type,
                    "total_steps": total_steps,
                    "target_frames": target_frames,
                    "raw_interval": raw_interval,
                    "dump_interval": dump_interval,
                    "is_production": is_production,
                    "was_overridden": step.name in modified_steps,
                }
            )

        # Update chain's sampling metadata
        chain.sampling_metadata = new_sampling_metadata

    def _parse_duration_to_steps(self, duration_str: str, timestep_fs: float) -> int:
        """Parse duration string to total steps."""
        duration_str = duration_str.strip().lower()

        if "steps" in duration_str:
            return int(duration_str.replace("steps", "").strip())
        elif "ns" in duration_str:
            duration_ns = float(duration_str.replace("ns", "").strip())
            duration_fs = duration_ns * 1e6
            return int(duration_fs / timestep_fs)
        elif "ps" in duration_str:
            duration_ps = float(duration_str.replace("ps", "").strip())
            duration_fs = duration_ps * 1000
            return int(duration_fs / timestep_fs)
        elif "fs" in duration_str:
            duration_fs = float(duration_str.replace("fs", "").strip())
            return int(duration_fs / timestep_fs)
        else:
            try:
                duration_ps = float(duration_str)
                duration_fs = duration_ps * 1000
                return int(duration_fs / timestep_fs)
            except ValueError:
                return 100000

    def merge_with_defaults(self, tier: str, overrides: list[StageDurationOverride]) -> list[dict]:
        """
        Merge user overrides with default values from SSOT.

        Args:
            tier: Run tier name
            overrides: User-specified overrides

        Returns:
            Complete list of stage durations (defaults + overrides)
        """
        include_injected_equilibration = any(
            override.stage_name in {"high_temp_nvt", "high_pressure_npt"} for override in overrides
        )
        defaults = self._get_validation_defaults(
            tier,
            include_injected_equilibration=include_injected_equilibration,
        )
        override_map = {o.stage_name: o for o in overrides}

        result = []
        for stage_name in defaults:
            stage_info = defaults[stage_name]

            if stage_name in override_map:
                override = override_map[stage_name]
                result.append(
                    {
                        "stage_name": stage_name,
                        "type": stage_info["type"],
                        "duration_ps": override.duration_ps or stage_info["duration_ps"],
                        "duration_steps": override.duration_steps or stage_info["duration_steps"],
                        "is_override": True,
                    }
                )
            else:
                result.append(
                    {
                        "stage_name": stage_name,
                        "type": stage_info["type"],
                        "duration_ps": stage_info["duration_ps"],
                        "duration_steps": stage_info["duration_steps"],
                        "is_override": False,
                    }
                )

        return result
