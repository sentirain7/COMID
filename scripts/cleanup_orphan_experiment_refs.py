#!/usr/bin/env python3
"""Cleanup orphan experiment references in database.

This script identifies and removes orphan references to deleted experiments
across all related tables. By default, it runs in dry-run mode and only
reports what would be cleaned up.

Usage:
    python scripts/cleanup_orphan_experiment_refs.py           # dry-run (default)
    python scripts/cleanup_orphan_experiment_refs.py --apply   # actual cleanup
    python scripts/cleanup_orphan_experiment_refs.py --verbose # detailed output

Tables cleaned (Priority 0 - FK by experiment.id PK):
- experiment_conditions (DELETE) ← root cause of UNIQUE constraint failure
- experiment_molecules (DELETE by PK)

Tables cleaned (Priority 1 - FK by exp_id string):
- metrics (DELETE with artifact ref_count handling)
- e_intra (DELETE)
- campaign_experiments (DELETE)
- design_simulation_records (SET NULL + status='cancelled')
- amorphous_cells (SET NULL)
- binder_analysis_runs (SET NULL)
- audit_log (SET NULL)
- llm_turns_train (SET NULL)
- pending_recommendations (SET NULL + conditional status)
- property_design_sessions (JSON cleanup)
- scenarios (JSON cleanup)
- ml_model_versions (JSON cleanup)
"""

import argparse
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Add src to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import or_, text

from common.logging import get_logger
from database.connection import session_scope
from features.common.workspace import resolve_workspace_path

logger = get_logger("cleanup_orphan_experiment_refs")

# Active recommendation statuses (to be cancelled)
_ACTIVE_RECOMMENDATION_STATUSES = {"pending", "approved", "queued", "running"}


def get_valid_exp_ids(session) -> set[str]:
    """Get all valid experiment IDs (string exp_id) from database."""
    from database.models.experiment import ExperimentModel

    return {e.exp_id for e in session.query(ExperimentModel.exp_id).all()}


def get_valid_exp_pk_ids(session) -> set[int]:
    """Get all valid experiment PK IDs (int) from database.

    Note: experiment_conditions and experiment_molecules use experiments.id (int PK)
    as FK, NOT experiments.exp_id (string). This is the root cause of orphan records
    when SQLite FK enforcement is OFF.
    """
    from database.models.experiment import ExperimentModel

    return {e.id for e in session.query(ExperimentModel.id).all()}


def cleanup_experiment_conditions(
    session, valid_exp_pk_ids: set[int], apply: bool, verbose: bool
) -> int:
    """Delete orphan experiment_conditions rows.

    This is the PRIMARY target of this cleanup script - these orphans cause
    UNIQUE constraint failures when SQLite reuses deleted experiment IDs.

    Note: experiment_conditions.experiment_id references experiments.id (int PK),
    NOT experiments.exp_id (string).
    """
    from database.models.experiment import ExperimentConditionModel

    if not valid_exp_pk_ids:
        # If no valid experiments exist, all conditions are orphans
        query = session.query(ExperimentConditionModel)
    else:
        query = session.query(ExperimentConditionModel).filter(
            ~ExperimentConditionModel.experiment_id.in_(valid_exp_pk_ids)
        )

    count = query.count()

    if verbose and count > 0:
        # Show affected experiment_ids for debugging
        orphan_exp_ids = {row.experiment_id for row in query.limit(100).all()}
        logger.info(
            f"Found {count} orphan experiment_conditions "
            f"(experiment_ids: {sorted(orphan_exp_ids)[:10]}{'...' if len(orphan_exp_ids) > 10 else ''})"
        )

    if apply and count > 0:
        query.delete(synchronize_session=False)

    return count


def cleanup_experiment_molecules_by_pk(
    session, valid_exp_pk_ids: set[int], apply: bool, verbose: bool
) -> int:
    """Delete orphan experiment_molecules by experiment.id FK.

    Note: experiment_molecules.experiment_id references experiments.id (int PK),
    NOT experiments.exp_id (string).
    """
    from database.models.experiment import ExperimentMoleculeModel

    if not valid_exp_pk_ids:
        query = session.query(ExperimentMoleculeModel)
    else:
        query = session.query(ExperimentMoleculeModel).filter(
            ~ExperimentMoleculeModel.experiment_id.in_(valid_exp_pk_ids)
        )

    count = query.count()

    if verbose and count > 0:
        orphan_exp_ids = {row.experiment_id for row in query.limit(100).all()}
        logger.info(
            f"Found {count} orphan experiment_molecules (by PK) "
            f"(experiment_ids: {sorted(orphan_exp_ids)[:10]}{'...' if len(orphan_exp_ids) > 10 else ''})"
        )

    if apply and count > 0:
        query.delete(synchronize_session=False)

    return count


def cleanup_metrics(session, valid_exp_ids: set[str], apply: bool, verbose: bool) -> int:
    """Delete orphan metrics and handle array artifact ref_counts.

    DEPRECATED: Use cleanup_metrics_with_fk_reconciliation() for FK-aware cleanup.
    Kept for backwards compatibility.
    """
    from database.models import MetricModel
    from database.models.metric import MetricArrayArtifactModel

    orphan_metrics = (
        session.query(MetricModel)
        .filter(~MetricModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True)
        .all()
    )

    if not orphan_metrics:
        return 0

    count = len(orphan_metrics)
    if verbose:
        logger.info(f"Found {count} orphan metrics")

    if apply:
        # Aggregate artifact refs
        artifact_ref_counts: Counter[int] = Counter()
        legacy_file_paths: set[str] = set()

        for m in orphan_metrics:
            if m.array_artifact_id:
                artifact_ref_counts[m.array_artifact_id] += 1
            elif m.array_file_path:
                legacy_file_paths.add(m.array_file_path)

        # Decrement ref_counts
        for artifact_id, ref_count in artifact_ref_counts.items():
            artifact = session.get(MetricArrayArtifactModel, artifact_id)
            if artifact:
                artifact.ref_count = max(0, (artifact.ref_count or 1) - ref_count)
                if artifact.ref_count == 0:
                    if artifact.storage_path:
                        try:
                            safe_path = resolve_workspace_path(artifact.storage_path)
                            safe_path.unlink(missing_ok=True)
                            if verbose:
                                logger.info(f"Deleted artifact file: {artifact.storage_path}")
                        except Exception as e:
                            logger.warning(f"Failed to delete artifact file: {e}")
                    session.delete(artifact)

        # Delete legacy files
        for file_path in legacy_file_paths:
            try:
                safe_path = resolve_workspace_path(file_path)
                safe_path.unlink(missing_ok=True)
                if verbose:
                    logger.info(f"Deleted legacy array file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete legacy file: {e}")

        # Delete metric rows
        exp_ids_to_delete = {m.exp_id for m in orphan_metrics}
        session.query(MetricModel).filter(
            MetricModel.exp_id.in_(exp_ids_to_delete)
        ).delete(synchronize_session=False)

    return count


def cleanup_metrics_with_fk_reconciliation(
    session,
    valid_exp_ids: set[str],
    valid_exp_pk_ids: set[int],
    apply: bool,
    verbose: bool,
) -> dict[str, int | list[str]]:
    """Metrics cleanup with FK reconciliation.

    Handles only unambiguous changes:
    1. exp_id valid + experiment_id NULL → recover experiment_id.
    2. exp_id/experiment_id disagreement → report unresolved, do not auto-attach.
    3. exp_id invalid + experiment_id valid → report unresolved, because SQLite
       PK reuse can make stale metrics look attachable to a new experiment.
    4. both references invalid → delete with artifact ref_count handling.

    Returns:
        {"recovered": N, "deleted": N, "unresolved": N, "deferred_files": [...]}
    """
    from database.models import ExperimentModel, MetricModel
    from database.models.metric import MetricArrayArtifactModel

    result: dict[str, int | list[str]] = {
        "recovered": 0,
        "deleted": 0,
        "unresolved": 0,
        "deferred_files": [],
    }
    deferred_file_deletions: list[str] = []

    exp_by_exp_id = {
        exp.exp_id: exp
        for exp in session.query(ExperimentModel).filter(ExperimentModel.exp_id.in_(valid_exp_ids)).all()
    } if valid_exp_ids else {}

    # ========== Case 1: exp_id valid + experiment_id NULL → recover ==========
    if valid_exp_ids:
        metrics_missing_pk = (
            session.query(MetricModel)
            .filter(
                MetricModel.exp_id.in_(valid_exp_ids),
                MetricModel.experiment_id.is_(None),
            )
            .all()
        )

        for m in metrics_missing_pk:
            exp = exp_by_exp_id.get(m.exp_id)
            if exp:
                if apply:
                    m.experiment_id = exp.id
                result["recovered"] += 1
                if verbose:
                    logger.info(f"Recovered metric {m.id}: set experiment_id={exp.id}")

    # ========== Case 2: exp_id valid + experiment_id mismatched → unresolved ==========
    if valid_exp_ids:
        metrics_with_valid_exp_id = (
            session.query(MetricModel)
            .filter(
                MetricModel.exp_id.in_(valid_exp_ids),
                MetricModel.experiment_id.isnot(None),
            )
            .all()
        )
        for m in metrics_with_valid_exp_id:
            exp = exp_by_exp_id.get(m.exp_id)
            if exp is not None and m.experiment_id != exp.id:
                result["unresolved"] += 1
                logger.warning(
                    "Unresolved metric %s: exp_id=%s belongs to experiment_id=%s, "
                    "but metric.experiment_id=%s",
                    m.id,
                    m.exp_id,
                    exp.id,
                    m.experiment_id,
                )

    # ========== Case 3: exp_id invalid + experiment_id valid → unresolved ==========
    if valid_exp_pk_ids:
        metrics_bad_exp_id = (
            session.query(MetricModel)
            .filter(
                ~MetricModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
                MetricModel.experiment_id.in_(valid_exp_pk_ids),
            )
            .all()
        )

        for m in metrics_bad_exp_id:
            result["unresolved"] += 1
            logger.warning(
                "Unresolved metric %s: stale exp_id=%s has currently valid experiment_id=%s; "
                "not auto-attaching because experiment PKs may have been reused",
                m.id,
                m.exp_id,
                m.experiment_id,
            )

    # ========== Case 4: True orphans → delete with artifact handling ==========
    # Build query for metrics where both FK references are invalid
    true_orphan_query = session.query(MetricModel).filter(
        ~MetricModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True
    )
    if valid_exp_pk_ids:
        true_orphan_query = true_orphan_query.filter(
            or_(
                MetricModel.experiment_id.is_(None),
                ~MetricModel.experiment_id.in_(valid_exp_pk_ids),
            )
        )

    true_orphans = true_orphan_query.all()

    # Artifact ref_count handling
    artifact_ref_counts: Counter[int] = Counter()
    for m in true_orphans:
        if m.array_artifact_id:
            artifact_ref_counts[m.array_artifact_id] += 1
        elif m.array_file_path:
            deferred_file_deletions.append(m.array_file_path)

    if apply:
        # Decrement artifact ref_counts
        for artifact_id, count in artifact_ref_counts.items():
            artifact = session.get(MetricArrayArtifactModel, artifact_id)
            if artifact:
                artifact.ref_count = max(0, (artifact.ref_count or 1) - count)
                if artifact.ref_count == 0:
                    if artifact.storage_path:
                        deferred_file_deletions.append(artifact.storage_path)
                    session.delete(artifact)

        # Delete orphan metrics
        for m in true_orphans:
            session.delete(m)

    result["deleted"] = len(true_orphans)
    result["deferred_files"] = deferred_file_deletions

    if verbose:
        logger.info(
            f"Metrics cleanup: recovered={result['recovered']}, "
            f"deleted={result['deleted']}, unresolved={result['unresolved']}"
        )

    return result


def cleanup_e_intra(session, valid_exp_ids: set[str], apply: bool, verbose: bool) -> int:
    """Delete orphan e_intra entries."""
    from database.models.metric import EIntraModel

    query = session.query(EIntraModel).filter(
        EIntraModel.source_exp_id.isnot(None),
        ~EIntraModel.source_exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan e_intra entries")

    if apply and count > 0:
        query.delete(synchronize_session=False)

    return count


def cleanup_campaign_experiments(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Delete orphan campaign experiment linkages."""
    from database.models.campaign import CampaignExperimentModel

    query = session.query(CampaignExperimentModel).filter(
        ~CampaignExperimentModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan campaign_experiments")

    if apply and count > 0:
        query.delete(synchronize_session=False)

    return count


def cleanup_design_simulation_records(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Set NULL and status='cancelled' for orphan design simulation records."""
    from database.models.recommendation import DesignSimulationRecord

    query = session.query(DesignSimulationRecord).filter(
        DesignSimulationRecord.exp_id.isnot(None),
        ~DesignSimulationRecord.exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan design_simulation_records")

    if apply and count > 0:
        query.update({"exp_id": None, "status": "cancelled"}, synchronize_session=False)

    return count


def cleanup_amorphous_cells(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Set NULL for orphan amorphous_cells.stabilization_exp_id."""
    from database.models.structure import AmorphousCellModel

    query = session.query(AmorphousCellModel).filter(
        AmorphousCellModel.stabilization_exp_id.isnot(None),
        ~AmorphousCellModel.stabilization_exp_id.in_(valid_exp_ids)
        if valid_exp_ids
        else True,
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan amorphous_cells references")

    if apply and count > 0:
        query.update({"stabilization_exp_id": None}, synchronize_session=False)

    return count


def cleanup_binder_analysis_runs(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Set NULL for orphan binder_analysis_runs exp_id/matched_exp_id."""
    from database.models.binder_analysis import BinderAnalysisRunModel

    # exp_id
    query1 = session.query(BinderAnalysisRunModel).filter(
        BinderAnalysisRunModel.exp_id.isnot(None),
        ~BinderAnalysisRunModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
    )
    count1 = query1.count()

    # matched_exp_id
    query2 = session.query(BinderAnalysisRunModel).filter(
        BinderAnalysisRunModel.matched_exp_id.isnot(None),
        ~BinderAnalysisRunModel.matched_exp_id.in_(valid_exp_ids)
        if valid_exp_ids
        else True,
    )
    count2 = query2.count()

    total = count1 + count2
    if verbose and total > 0:
        logger.info(
            f"Found {count1} orphan binder_analysis_runs.exp_id, "
            f"{count2} orphan matched_exp_id"
        )

    if apply:
        if count1 > 0:
            query1.update({"exp_id": None}, synchronize_session=False)
        if count2 > 0:
            query2.update({"matched_exp_id": None}, synchronize_session=False)

    return total


def cleanup_audit_log(session, valid_exp_ids: set[str], apply: bool, verbose: bool) -> int:
    """Set NULL for orphan audit_log.exp_id."""
    from database.models.llm import AuditLogModel

    query = session.query(AuditLogModel).filter(
        AuditLogModel.exp_id.isnot(None),
        ~AuditLogModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan audit_log references")

    if apply and count > 0:
        query.update({"exp_id": None}, synchronize_session=False)

    return count


def cleanup_llm_turns_train(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Set NULL for orphan llm_turns_train.exp_id."""
    from database.models.llm import LLMTurnsTrainModel

    query = session.query(LLMTurnsTrainModel).filter(
        LLMTurnsTrainModel.exp_id.isnot(None),
        ~LLMTurnsTrainModel.exp_id.in_(valid_exp_ids) if valid_exp_ids else True,
    )
    count = query.count()

    if verbose and count > 0:
        logger.info(f"Found {count} orphan llm_turns_train references")

    if apply and count > 0:
        query.update({"exp_id": None}, synchronize_session=False)

    return count


def cleanup_pending_recommendations(
    session, valid_exp_ids: set[str], apply: bool, verbose: bool
) -> int:
    """Set NULL and conditional status for orphan pending_recommendations."""
    from sqlalchemy import func

    from database.models.recommendation import PendingRecommendationModel

    # Active status → cancelled
    query_active = session.query(PendingRecommendationModel).filter(
        PendingRecommendationModel.queued_exp_id.isnot(None),
        ~PendingRecommendationModel.queued_exp_id.in_(valid_exp_ids)
        if valid_exp_ids
        else True,
        PendingRecommendationModel.status.in_(_ACTIVE_RECOMMENDATION_STATUSES),
    )
    count_active = query_active.count()

    # Terminal status → just clear exp_id
    query_terminal = session.query(PendingRecommendationModel).filter(
        PendingRecommendationModel.queued_exp_id.isnot(None),
        ~PendingRecommendationModel.queued_exp_id.in_(valid_exp_ids)
        if valid_exp_ids
        else True,
        ~PendingRecommendationModel.status.in_(_ACTIVE_RECOMMENDATION_STATUSES),
    )
    count_terminal = query_terminal.count()

    total = count_active + count_terminal
    if verbose and total > 0:
        logger.info(
            f"Found {count_active} active orphan recommendations (→cancelled), "
            f"{count_terminal} terminal (→NULL only)"
        )

    if apply:
        if count_active > 0:
            query_active.update(
                {
                    "queued_exp_id": None,
                    "status": "cancelled",
                    "notes": func.coalesce(PendingRecommendationModel.notes, "")
                    + " [orphan cleanup]",
                },
                synchronize_session=False,
            )
        if count_terminal > 0:
            query_terminal.update({"queued_exp_id": None}, synchronize_session=False)

    return total


def cleanup_json_arrays(session, valid_exp_ids: set[str], apply: bool, verbose: bool) -> int:
    """Remove orphan exp_ids from JSON array fields."""
    from database.models.campaign import MLModelVersionModel
    from database.models.orchestration import ScenarioModel
    from database.models.recommendation import (
        PendingRecommendationModel,
        PropertyDesignSessionModel,
    )

    count = 0

    # PropertyDesignSession.simulation_exp_ids_json
    for row in session.query(PropertyDesignSessionModel).filter(
        PropertyDesignSessionModel.simulation_exp_ids_json.isnot(None)
    ).all():
        original = row.simulation_exp_ids_json or []
        cleaned = [eid for eid in original if eid in valid_exp_ids]
        if len(cleaned) != len(original):
            count += len(original) - len(cleaned)
            if apply:
                row.simulation_exp_ids_json = cleaned

    # ScenarioModel.result_exp_ids
    for row in session.query(ScenarioModel).filter(
        ScenarioModel.result_exp_ids.isnot(None)
    ).all():
        original = row.result_exp_ids or []
        cleaned = [eid for eid in original if eid in valid_exp_ids]
        if len(cleaned) != len(original):
            count += len(original) - len(cleaned)
            if apply:
                row.result_exp_ids = cleaned

    # MLModelVersionModel.holdout_exp_ids
    for row in session.query(MLModelVersionModel).filter(
        MLModelVersionModel.holdout_exp_ids.isnot(None)
    ).all():
        original = row.holdout_exp_ids or []
        cleaned = [eid for eid in original if eid in valid_exp_ids]
        if len(cleaned) != len(original):
            count += len(original) - len(cleaned)
            if apply:
                row.holdout_exp_ids = cleaned

    # PendingRecommendationModel.source_records_json (nested dict)
    exp_id_keys = {"exp_id", "source_exp_id", "queued_exp_id", "matched_exp_id"}
    for row in session.query(PendingRecommendationModel).filter(
        PendingRecommendationModel.source_records_json.isnot(None)
    ).all():
        original = row.source_records_json or []
        cleaned = []
        for item in original:
            if isinstance(item, dict):
                keep = True
                for key in exp_id_keys:
                    if item.get(key) and item.get(key) not in valid_exp_ids:
                        keep = False
                        break
                if keep:
                    cleaned.append(item)
            elif item in valid_exp_ids:
                cleaned.append(item)
        if len(cleaned) != len(original):
            count += len(original) - len(cleaned)
            if apply:
                row.source_records_json = cleaned

    if verbose and count > 0:
        logger.info(f"Found {count} orphan exp_ids in JSON arrays")

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup orphan experiment references in database"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply changes (default: dry-run)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Orphan Experiment Reference Cleanup")
    print("=" * 60)
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    # SQLite backup before apply
    backup_path = None
    if args.apply:
        db_url = os.getenv("DATABASE_URL", "")
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            if os.path.exists(db_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f"{db_path}.backup_cleanup_{timestamp}"
                shutil.copy2(db_path, backup_path)
                print(f"✅ Backup created: {backup_path}")
                print()

    totals: dict[str, int] = {}
    deferred_file_deletions: list[str] = []

    with session_scope() as session:
        # Get both exp_id (string) and id (int PK) sets
        valid_exp_ids = get_valid_exp_ids(session)
        valid_exp_pk_ids = get_valid_exp_pk_ids(session)
        print(f"Valid experiments in database: {len(valid_exp_ids)}")
        print()

        # ========== Priority 0: FK by experiment.id (int PK) ==========
        # These are the ROOT CAUSE of UNIQUE constraint failures
        print("--- Priority 0: FK by experiment.id (int PK) ---")
        totals["experiment_conditions"] = cleanup_experiment_conditions(
            session, valid_exp_pk_ids, args.apply, args.verbose
        )
        totals["experiment_molecules_pk"] = cleanup_experiment_molecules_by_pk(
            session, valid_exp_pk_ids, args.apply, args.verbose
        )

        # ========== Priority 1: FK by exp_id (string) ==========
        print("\n--- Priority 1: FK by exp_id (string) ---")

        # Use new FK-aware metrics cleanup
        metrics_result = cleanup_metrics_with_fk_reconciliation(
            session, valid_exp_ids, valid_exp_pk_ids, args.apply, args.verbose
        )
        totals["metrics_recovered"] = metrics_result["recovered"]
        totals["metrics_deleted"] = metrics_result["deleted"]
        totals["metrics_unresolved"] = metrics_result["unresolved"]
        deferred_file_deletions.extend(metrics_result.get("deferred_files", []))

        totals["e_intra"] = cleanup_e_intra(session, valid_exp_ids, args.apply, args.verbose)
        totals["campaign_experiments"] = cleanup_campaign_experiments(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["design_simulation_records"] = cleanup_design_simulation_records(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["amorphous_cells"] = cleanup_amorphous_cells(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["binder_analysis_runs"] = cleanup_binder_analysis_runs(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["audit_log"] = cleanup_audit_log(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["llm_turns_train"] = cleanup_llm_turns_train(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["pending_recommendations"] = cleanup_pending_recommendations(
            session, valid_exp_ids, args.apply, args.verbose
        )
        totals["json_arrays"] = cleanup_json_arrays(
            session, valid_exp_ids, args.apply, args.verbose
        )

        if args.apply:
            session.commit()
            print("\n✅ Changes committed.")

            # Delete deferred files after commit
            for file_path in deferred_file_deletions:
                try:
                    safe_path = resolve_workspace_path(file_path)
                    safe_path.unlink(missing_ok=True)
                    if args.verbose:
                        logger.info(f"Deleted deferred file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete deferred file: {e}")
        else:
            session.rollback()

    # FK check after cleanup
    if args.apply:
        print("\n--- FK Integrity Check ---")
        with session_scope() as session:
            try:
                fk_violations = session.execute(text("PRAGMA foreign_key_check")).fetchall()
                if fk_violations:
                    print(f"⚠️  FK violations remaining: {len(fk_violations)}")
                    for v in fk_violations[:10]:
                        print(f"    {v}")
                    if len(fk_violations) > 10:
                        print(f"    ... and {len(fk_violations) - 10} more")
                else:
                    print("✅ No FK violations (PRAGMA foreign_key_check = 0)")
            except Exception as e:
                # Non-SQLite database
                print(f"(FK check skipped: {e})")

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    for table, count in totals.items():
        if count > 0:
            status = "cleaned" if args.apply else "would clean"
            print(f"  {table}: {count} {status}")

    # Calculate total (skip recovered for total count)
    total = sum(
        v for k, v in totals.items()
        if k not in ("metrics_recovered",)  # recovered is not "cleaned"
    )
    print()
    print(f"Total orphan references: {total} {'cleaned' if args.apply else 'found'}")
    if totals.get("metrics_recovered", 0) > 0:
        print(f"Metrics recovered (FK repaired): {totals['metrics_recovered']}")

    if not args.apply and total > 0:
        print()
        print("Run with --apply to actually clean up these references.")


if __name__ == "__main__":
    main()
