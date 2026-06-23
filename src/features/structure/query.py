"""Structure query operations."""

from common.logging import get_logger
from contracts.errors import ContractError, DatabaseError, ErrorCode, SecurityError
from features.common import run_in_session

logger = get_logger("features.structure.query")


async def get_available_stages(exp_id: str) -> dict:
    from api.utils.structure_path import get_available_stages, get_experiment_dir
    from database.repositories.experiment_repo import ExperimentRepository

    try:

        def _load(session):
            repo = ExperimentRepository(session)
            experiment = repo.get_by_id(exp_id)
            if not experiment:
                raise DatabaseError(
                    ErrorCode.RECORD_NOT_FOUND,
                    f"Experiment {exp_id} not found",
                    {"exp_id": exp_id},
                )

            exp_dir = get_experiment_dir(experiment.lammps_working_dir, experiment.data_file_path)
            if not exp_dir:
                raise SecurityError(
                    ErrorCode.STRUCTURE_NOT_FOUND,
                    "Experiment directory not found",
                    {"exp_id": exp_id},
                )

            tier = experiment.run_tier or "screening"
            return exp_dir, tier

        exp_dir, tier = run_in_session(_load)
    except ContractError:
        raise
    except Exception as exc:
        logger.error(f"Database error for {exp_id}: {exc}")
        raise DatabaseError(
            ErrorCode.DATABASE_ERROR,
            "Database error",
            {"exp_id": exp_id},
        ) from exc

    stages = get_available_stages(exp_dir, tier)
    return {"stages": stages, "tier": tier}
