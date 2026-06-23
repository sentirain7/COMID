"""
Structure path utilities for 3D visualization API.

Provides path resolution based on actual directory layout and
stabilization chain order (SSOT).
"""

from pathlib import Path

from common.logging import get_logger
from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN

logger = get_logger("api.utils.structure_path")


def get_experiment_dir(
    lammps_working_dir: str | None,
    data_file_path: str | None,
) -> Path | None:
    """
    Get experiment directory from ExperimentModel fields.

    Uses lammps_working_dir if available, otherwise derives from data_file_path.

    Args:
        lammps_working_dir: LAMMPS working directory from ExperimentModel
        data_file_path: Data file path from ExperimentModel

    Returns:
        Path to experiment directory, or None if not determinable
    """
    if lammps_working_dir:
        path = Path(lammps_working_dir)
        if path.exists():
            return path

    if data_file_path:
        path = Path(data_file_path).parent
        if path.exists():
            return path

    return None


def get_structure_path(exp_dir: Path, stage: str) -> Path:
    """
    Get structure file path for a stage.

    Actual layout: flat structure (no subdirectories).

    Args:
        exp_dir: Experiment directory path
        stage: Stage name (initial, nvt_equilibration, npt_production, etc.)

    Returns:
        Path to structure file (may not exist)
    """
    if stage == "initial":
        return exp_dir / "data.lammps"
    else:
        return exp_dir / f"dump_{stage}.lammpstrj"


def get_final_stage(exp_dir: Path, tier: str) -> str:
    """
    Determine the final available stage based on chain order.

    Uses stabilization.py chain order (SSOT) to find the last
    existing dump file.

    Args:
        exp_dir: Experiment directory path
        tier: Run tier (screening, confirm, viscosity, validation)

    Returns:
        Name of the last available stage, or "initial" if no dumps exist
    """
    try:
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain(tier)
    except ValueError:
        # Unknown tier, try screening as default
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain("screening")

    # Iterate in reverse to find the last existing dump
    for step in reversed(chain):
        # Skip minimize steps (no dump file generated)
        if step.type == "minimize":
            continue

        dump_path = exp_dir / f"dump_{step.name}.lammpstrj"
        if dump_path.exists():
            logger.debug(f"Final stage for {tier}: {step.name}")
            return step.name

    # Fallback to initial if no dumps exist
    logger.debug(f"No dump files found, using initial for {tier}")
    return "initial"


def get_available_stages(exp_dir: Path, tier: str) -> list[str]:
    """
    Get list of available structure stages.

    Based on actual file existence and stabilization chain order (SSOT).

    Args:
        exp_dir: Experiment directory path
        tier: Run tier (screening, confirm, viscosity, validation)

    Returns:
        List of available stage names in chain order
    """
    stages = []

    # Check initial (data.lammps)
    if (exp_dir / "data.lammps").exists():
        stages.append("initial")

    # Get chain and check each step
    try:
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain(tier)
    except ValueError:
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain("screening")

    for step in chain:
        # Skip minimize steps (no dump)
        if step.type == "minimize":
            continue

        dump_path = exp_dir / f"dump_{step.name}.lammpstrj"
        if dump_path.exists():
            stages.append(step.name)

    # Add "final" if there's more than one stage
    if len(stages) > 1:
        stages.append("final")

    return stages
