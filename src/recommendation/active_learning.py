"""Active learning workflow for ML-guided MD simulation.

Integrates the recommendation agent, Bayesian optimizer, and benchmark
validation into a user-approval-based active learning loop.

Policy: ``docs/INTEGRATED_PLAN.md:171`` — "사용자 승인 후 실행, autonomous run 금지"

Workflow::

    1. ``suggest_next()``  → ML prediction + GP uncertainty → ranked candidates
    2. User reviews candidates via API / CLI
    3. ``approve(rec_id)`` → queues MD simulation (via ``queue_fn``)
    4. MD completes → ``feed_result()`` → optimizer + training store updated
    5. Repeat from 1

No step executes without explicit user approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from common.logging import get_logger
from recommendation.agent import (
    AgentConfig,
    Recommendation,
    RecommendationAgent,
    RecommendationBatch,
    RecommendationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("recommendation.active_learning")


@dataclass
class TrainingDatum:
    """A single observation for model retraining."""

    composition: dict[str, float]
    observed_properties: dict[str, float]
    exp_id: str
    temperature_k: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition": self.composition,
            "observed_properties": self.observed_properties,
            "exp_id": self.exp_id,
            "temperature_k": self.temperature_k,
            "timestamp": self.timestamp,
        }


@dataclass
class ActiveLearningState:
    """Persistent state of the active learning loop."""

    iteration: int = 0
    training_data: list[TrainingDatum] = field(default_factory=list)
    pending_experiments: dict[str, str] = field(default_factory=dict)  # rec_id → exp_id
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n_observations(self) -> int:
        return len(self.training_data)

    def summary(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "n_observations": self.n_observations,
            "n_pending": len(self.pending_experiments),
            "n_history_entries": len(self.history),
        }


class ActiveLearningWorkflow:
    """User-approval-based active learning for composition optimisation.

    This class orchestrates the ML→MD feedback loop **without autonomous
    execution**.  Every simulation must be explicitly approved by the user.

    Args:
        agent: Pre-configured ``RecommendationAgent``.
        queue_fn: Callable that submits an approved composition for MD.
            Signature: ``(composition, temperature_k, run_tier) → exp_id``.
        retrain_fn: Optional callable triggered after ``min_retrain_samples``
            new observations accumulate.
            Signature: ``(training_data: list[TrainingDatum]) → None``.
        min_retrain_samples: Minimum new observations before retraining.
    """

    def __init__(
        self,
        agent: RecommendationAgent | None = None,
        queue_fn: Callable | None = None,
        retrain_fn: Callable | None = None,
        min_retrain_samples: int = 5,
    ) -> None:
        self.agent = agent or RecommendationAgent(config=AgentConfig(auto_run=False))
        self.queue_fn = queue_fn
        self.retrain_fn = retrain_fn
        self.min_retrain_samples = min_retrain_samples
        self.state = ActiveLearningState()
        self._samples_since_retrain = 0

    # ── step 1: suggest ───────────────────────────────────────────

    def suggest_next(self, n_candidates: int = 20) -> RecommendationBatch:
        """Generate the next batch of recommendations.

        Uses the Bayesian optimiser's GP uncertainty to rank candidates
        that maximise expected information gain.

        Args:
            n_candidates: How many raw candidates to generate before
                filtering to top-k Pareto recommendations.

        Returns:
            ``RecommendationBatch`` with ``PENDING`` recommendations.
        """
        batch = self.agent.generate_recommendations(n_candidates=n_candidates)

        self.state.history.append(
            {
                "action": "suggest",
                "iteration": self.state.iteration,
                "n_candidates": n_candidates,
                "n_recommendations": len(batch.recommendations),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        logger.info(
            f"AL iteration {self.state.iteration}: "
            f"generated {len(batch.recommendations)} recommendations"
        )
        return batch

    # ── step 2: approve / reject ──────────────────────────────────

    def approve(self, recommendation_id: str, notes: str = "") -> Recommendation | None:
        """Approve a recommendation and queue the MD simulation.

        Args:
            recommendation_id: ID from ``Recommendation.id``.
            notes: Optional user notes.

        Returns:
            The approved ``Recommendation`` with ``queued_exp_id`` set,
            or ``None`` if not found / already processed.
        """
        queue_fn = self.queue_fn or self.agent.queue_fn
        if queue_fn is None:
            raise RuntimeError(
                "Queue integration is required for approval, but no queue_fn is configured."
            )

        rec = self.agent.approve_recommendation(recommendation_id, notes=notes)
        if rec is None:
            return None

        # Queue MD if recommendation was approved but not queued by agent
        if rec.queued_exp_id is None:
            try:
                exp_id = queue_fn(
                    composition=rec.composition,
                    temperature_k=self.agent.config.temperature_k,
                    run_tier=self.agent.config.run_tier,
                )
                if not isinstance(exp_id, str) or not exp_id.strip():
                    raise RuntimeError("queue_fn returned invalid experiment ID")
                rec.queued_exp_id = exp_id
                rec.status = RecommendationStatus.QUEUED
                logger.info(f"Queued MD experiment {exp_id} for {recommendation_id}")
            except Exception as e:
                logger.error(f"Failed to queue experiment: {e}")
                rec.status = RecommendationStatus.FAILED
                raise RuntimeError(f"Failed to queue approved recommendation: {e}") from e

        # Approval is considered successful only when queueing succeeded.
        if rec.status != RecommendationStatus.QUEUED or rec.queued_exp_id is None:
            rec.status = RecommendationStatus.FAILED
            raise RuntimeError(
                "Approved recommendation was not queued. "
                "Approval requires successful queue submission."
            )

        self.state.pending_experiments[recommendation_id] = rec.queued_exp_id
        self.state.history.append(
            {
                "action": "approve",
                "recommendation_id": recommendation_id,
                "exp_id": rec.queued_exp_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return rec

    def reject(self, recommendation_id: str, reason: str = "") -> Recommendation | None:
        """Reject a recommendation.

        Args:
            recommendation_id: ID from ``Recommendation.id``.
            reason: Reason for rejection.

        Returns:
            The rejected ``Recommendation`` or ``None``.
        """
        rec = self.agent.reject_recommendation(recommendation_id, reason=reason)
        if rec is not None:
            self.state.history.append(
                {
                    "action": "reject",
                    "recommendation_id": recommendation_id,
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        return rec

    # ── step 3: feed results back ─────────────────────────────────

    def feed_result(
        self,
        exp_id: str,
        composition: dict[str, float],
        observed_properties: dict[str, float],
        temperature_k: float = 298.0,
    ) -> None:
        """Feed MD simulation results back to the optimiser.

        Updates both the Bayesian optimiser (for next suggestions)
        and the training data store (for batch retraining).

        Args:
            exp_id: Experiment ID of the completed MD run.
            composition: The simulated composition.
            observed_properties: Observed metric values
                (e.g. ``{"density": 1.02, "cohesive_energy_density": 350.0}``).
            temperature_k: Simulation temperature.
        """
        # Update Bayesian optimiser
        self.agent.update_with_results(composition, observed_properties)

        # Store training datum
        datum = TrainingDatum(
            composition=composition,
            observed_properties=observed_properties,
            exp_id=exp_id,
            temperature_k=temperature_k,
        )
        self.state.training_data.append(datum)
        self._samples_since_retrain += 1

        # Remove from pending
        for rec_id, pending_eid in list(self.state.pending_experiments.items()):
            if pending_eid == exp_id:
                del self.state.pending_experiments[rec_id]
                break

        self.state.history.append(
            {
                "action": "feed_result",
                "exp_id": exp_id,
                "observed_properties": observed_properties,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        logger.info(
            f"Fed result for {exp_id} — "
            f"{self._samples_since_retrain}/{self.min_retrain_samples} samples until retrain"
        )

        # Trigger retraining if threshold reached
        if self._samples_since_retrain >= self.min_retrain_samples:
            self._maybe_retrain()

    # ── step 4: retrain ───────────────────────────────────────────

    def _maybe_retrain(self) -> None:
        """Trigger retraining if a retrain function is configured."""
        if self.retrain_fn is None:
            logger.debug("No retrain_fn configured, skipping retraining")
            self._samples_since_retrain = 0
            return

        logger.info(f"Triggering retraining with {len(self.state.training_data)} observations")
        try:
            self.retrain_fn(self.state.training_data)
            self._samples_since_retrain = 0
            self.state.iteration += 1

            self.state.history.append(
                {
                    "action": "retrain",
                    "n_observations": len(self.state.training_data),
                    "iteration": self.state.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as e:
            logger.error(f"Retraining failed: {e}")

    # ── queries ───────────────────────────────────────────────────

    def get_pending(self) -> list[Recommendation]:
        """Get all pending (unapproved) recommendations."""
        return self.agent.get_pending_recommendations()

    def get_state_summary(self) -> dict[str, Any]:
        """Get a summary of the active learning state."""
        pending_recommendations = self.get_pending()
        return {
            **self.state.summary(),
            "n_pending": len(pending_recommendations),
            "n_pending_experiments": len(self.state.pending_experiments),
            "agent_summary": self.agent.get_recommendation_summary(),
        }
