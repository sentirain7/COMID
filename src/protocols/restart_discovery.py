"""Restart-from-checkpoint discovery for interrupted LAMMPS simulations.

Scans experiment attempt directories for stage-boundary restart files
(``restart.{stage_name}``) and returns the best restart point so that
the simulation can resume from the last completed stage.

v1 scope: stage-boundary files only; periodic ``.a/.b`` checkpoints
are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.logging import get_logger

logger = get_logger("protocols.restart_discovery")


@dataclass(frozen=True)
class RestartPoint:
    """Describes a valid restart position within a stabilization chain.

    Attributes:
        restart_file: Absolute path to the LAMMPS restart file.
        completed_stage_index: 0-based index of the last *completed* stage.
        completed_stage_name: Stage key of the completed stage.
        remaining_stage_indices: Original indices of stages still to run.
        source_attempt_dir: The attempt directory containing the restart file.
    """

    restart_file: Path
    completed_stage_index: int
    completed_stage_name: str
    remaining_stage_indices: list[int]
    source_attempt_dir: Path


def discover_restart_point(
    exp_id: str,
    compiled_plan: dict | None,
    candidate_dirs: list[Path],
) -> RestartPoint | None:
    """Find the latest stage-boundary restart file across candidate dirs.

    Args:
        exp_id: Experiment identifier (for logging only).
        compiled_plan: ``metadata_json["compiled_execution_plan"]``.
            Must contain a ``"stages"`` list with ``"stage_key"`` entries.
        candidate_dirs: Attempt directories ordered by priority
            (active_attempt_id dir first, then celery_task_id dir,
            then newest ``attempt_*`` dirs).

    Returns:
        A ``RestartPoint`` if a usable restart file is found, else ``None``.
        Returns ``None`` when only ``final.restart`` exists (simulation
        already completed — caller should use result-recovery instead).
    """
    if not compiled_plan or "stages" not in compiled_plan:
        logger.debug("No compiled_plan for %s — cannot discover restart point", exp_id)
        return None

    stages: list[dict] = compiled_plan["stages"]
    if not stages:
        return None

    stage_names = [s["stage_key"] for s in stages]
    n_stages = len(stage_names)

    for cdir in candidate_dirs:
        if not cdir.is_dir():
            continue

        # Skip if simulation already completed (final.restart present).
        if (cdir / "final.restart").is_file():
            logger.info(
                "%s: final.restart found in %s — simulation completed, skipping restart",
                exp_id,
                cdir,
            )
            return None

        # Walk stage list in reverse to find the latest completed stage.
        for idx in range(n_stages - 1, -1, -1):
            restart_path = cdir / f"restart.{stage_names[idx]}"
            if restart_path.is_file():
                remaining = list(range(idx + 1, n_stages))
                if not remaining:
                    # All stages completed but no final.restart — unusual.
                    logger.warning(
                        "%s: restart.%s found but no remaining stages",
                        exp_id,
                        stage_names[idx],
                    )
                    return None

                logger.info(
                    "%s: restart point found at stage %d/%d (%s) in %s — %d stages remaining",
                    exp_id,
                    idx + 1,
                    n_stages,
                    stage_names[idx],
                    cdir,
                    len(remaining),
                )
                return RestartPoint(
                    restart_file=restart_path.resolve(),
                    completed_stage_index=idx,
                    completed_stage_name=stage_names[idx],
                    remaining_stage_indices=remaining,
                    source_attempt_dir=cdir,
                )

    logger.debug("%s: no restart files found in %d candidate dirs", exp_id, len(candidate_dirs))
    return None
