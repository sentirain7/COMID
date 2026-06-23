"""Automatic tier promotion — check z-scores, submit higher-tier jobs.

Non-blocking: promotion failures never affect the current experiment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from common.pathing import generate_exp_id
from contracts.policies.tier import DEFAULT_TIER_POLICY
from orchestrator.exp_id_helper import parse_material_id
from orchestrator.request_factory import create_build_request, create_protocol_request
from orchestrator.zscore_service import ZScoreService

if TYPE_CHECKING:
    from database.repositories.experiment_repo import ExperimentRepository

logger = get_logger("orchestrator.tier_promoter")


class TierPromoter:
    """Check tier promotion conditions and submit promoted jobs.

    Args:
        zscore_service: ZScoreService for z-score calculation
        experiment_repo: ExperimentRepository for duplicate checking
        job_manager: CeleryJobManager for job submission (required)
    """

    def __init__(
        self,
        zscore_service: ZScoreService,
        experiment_repo: ExperimentRepository,
        job_manager: object | None = None,
    ) -> None:
        self.zscore_service = zscore_service
        self.experiment_repo = experiment_repo
        self.job_manager = job_manager

    def maybe_promote(
        self,
        exp_id: str,
        current_tier: str,
        material_id: str,
        temperature_k: float,
        composition: dict,
        seed: int,
        flags: dict[str, bool] | None = None,
        ff_type: str | None = None,
    ) -> str | None:
        """Check promotion conditions and submit a higher-tier job if warranted.

        Args:
            exp_id: Current experiment ID
            current_tier: Current tier name
            material_id: Material identifier (e.g. "AAA1_X1_non_aging")
            temperature_k: Temperature in Kelvin
            composition: Composition dict (wt% or mol_count)
            seed: Random seed
            flags: Optional boolean flags
            ff_type: Force field type to propagate (defaults to bulk_ff_gaff2)

        Returns:
            New experiment ID if promoted, None otherwise
        """
        next_tier = self.zscore_service.check_tier_promotion(
            exp_id=exp_id,
            current_tier=current_tier,
            temperature_k=temperature_k,
            flags=flags,
        )

        if next_tier is None:
            return None

        # Resolve ff_type: propagate from original experiment, default to gaff2 for new
        resolved_ff_type = ff_type or "bulk_ff_gaff2"

        # Generate exp_id for the promoted experiment
        binder_type, structure_size, aging_state = parse_material_id(material_id)
        target_atoms = DEFAULT_TIER_POLICY.get_target_atoms(next_tier)

        new_exp_id = generate_exp_id(
            binder_type=binder_type,
            structure_size=structure_size,
            temperature_k=temperature_k,
            ff_type=resolved_ff_type,
            aging_state=aging_state,
            atom_count=target_atoms,
            seed=seed,
        )

        # Duplicate check
        existing = self.experiment_repo.get_by_id(new_exp_id)
        if existing is not None:
            logger.info(
                f"Promotion skipped (duplicate): {new_exp_id} already exists "
                f"(status={existing.status})"
            )
            return None

        # Determine composition mode
        all_float = all(isinstance(v, float) for v in composition.values())
        composition_mode = "wt_percent" if all_float else "mol_count"

        # Create requests
        build_request = create_build_request(
            composition=composition,
            seed=seed,
            tier=next_tier,
            composition_mode=composition_mode,
        )
        protocol_request = create_protocol_request(
            tier=next_tier,
            ff_type=resolved_ff_type,
            temperature_K=temperature_k,
        )

        # Submit via CeleryJobManager (single submission gate)
        if self.job_manager is None:
            raise RuntimeError(
                "TierPromoter requires a job_manager. Pass job_manager= to the constructor."
            )
        self.job_manager.submit(
            build_request=build_request,
            protocol_request=protocol_request,
            material_id=material_id,
            exp_id=new_exp_id,
        )

        logger.info(
            f"Tier promotion submitted: {exp_id} ({current_tier}) -> {new_exp_id} ({next_tier})"
        )
        return new_exp_id
