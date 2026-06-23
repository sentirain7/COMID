"""E_inter 정밀 분석 서비스."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode
from contracts.policies.e_inter_compute import SUPPORTED_CPU_RERUN_FF_TYPES
from database.connection import session_scope
from database.models import AnalysisJobModel, ExperimentModel

from .policy import DEFAULT_E_INTER_POLICY_EVALUATOR

logger = get_logger("features.e_inter_compute")

# SUPPORTED_CPU_RERUN_FF_TYPES는 contracts SSOT에서 import(자동 활성화 판정과 공유).
SUPPORTED_CPU_RERUN_METRICS = frozenset({"e_inter_total"})
DEFAULT_CPU_RERUN_METRICS = ["e_inter_total"]


class EInterComputeService:
    """E_inter 정밀 분석 관리 서비스."""

    def get_recommendation(self, **kwargs: Any) -> dict[str, Any]:
        """추천 레벨 평가."""
        from contracts.policies.e_inter_compute import EInterPolicyInput

        policy_input = EInterPolicyInput(**kwargs)
        result = DEFAULT_E_INTER_POLICY_EVALUATOR.evaluate(policy_input)
        return {
            "level": result.level.value,
            "score": result.score,
            "reason_codes": list(result.reason_codes),
            "affected_metrics": list(result.affected_metrics),
            "estimated_cpu_cost_minutes": result.estimated_cpu_cost_minutes,
            "default_enabled": result.default_enabled,
        }

    def create_cpu_rerun_job(
        self,
        exp_id: str,
        metrics: list[str] | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        """Create CPU rerun job for completed experiment.

        Args:
            exp_id: Experiment ID
            metrics: List of metrics to compute (default: ["e_inter_total"])
            trigger: Trigger source ("manual" or "auto_after_gpu")

        Returns:
            Dict with job_id, status, exp_id, celery_task_id
        """
        # 1. Validate experiment
        self._validate_experiment_for_rerun(exp_id)

        # 2. Check for active job (409 Conflict)
        if self._has_active_job(exp_id):
            raise ContractError(
                ErrorCode.DUPLICATE_RECORD, f"Active analysis job exists for {exp_id}"
            )

        # 3. Create DB record
        job_id = f"einter_cpu_{uuid.uuid4().hex[:12]}"
        metrics_list = self._normalize_metrics(metrics)

        with session_scope() as session:
            job = AnalysisJobModel(
                analysis_job_id=job_id,
                exp_id=exp_id,
                analysis_type="cpu_rerun_einter",
                status="queued",
                metrics_json=metrics_list,
                reason_codes_json={"trigger": trigger},
                created_at=datetime.now(UTC),
            )
            session.add(job)

        # 4. Enqueue Celery task
        from orchestrator.tasks import run_cpu_rerun_einter

        task = run_cpu_rerun_einter.apply_async(
            args=(exp_id, job_id),
            kwargs={"metrics": metrics_list},
            queue="analysis.cpu",
        )

        # 5. Update celery_task_id
        with session_scope() as session:
            job = (
                session.query(AnalysisJobModel)
                .filter(AnalysisJobModel.analysis_job_id == job_id)
                .first()
            )
            if job:
                job.celery_task_id = task.id

        logger.info(f"Created and enqueued CPU rerun job {job_id} for {exp_id}, task={task.id}")
        return {
            "job_id": job_id,
            "status": "queued",
            "exp_id": exp_id,
            "celery_task_id": task.id,
        }

    def get_job_status(self, exp_id: str) -> dict[str, Any]:
        """Get analysis job status for experiment."""
        with session_scope() as session:
            job = (
                session.query(AnalysisJobModel)
                .filter(AnalysisJobModel.exp_id == exp_id)
                .order_by(AnalysisJobModel.created_at.desc())
                .first()
            )
            if not job:
                return {"status": "not_found", "exp_id": exp_id}
            return {
                "job_id": job.analysis_job_id,
                "exp_id": job.exp_id,
                "status": job.status,
                "analysis_type": job.analysis_type,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message,
            }

    def _validate_experiment_for_rerun(self, exp_id: str) -> None:
        """Validate experiment is eligible for CPU rerun."""
        with session_scope() as session:
            exp = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
            if not exp:
                raise ContractError(ErrorCode.RECORD_NOT_FOUND, f"Experiment {exp_id} not found")
            if exp.status != "completed":
                raise ContractError(
                    ErrorCode.VALIDATION_ERROR, f"Experiment not completed: {exp.status}"
                )
            if exp.ff_type not in SUPPORTED_CPU_RERUN_FF_TYPES:
                raise ContractError(
                    ErrorCode.VALIDATION_ERROR,
                    f"CPU rerun E_inter v1 supports only bulk_ff_gaff2, got {exp.ff_type}",
                )
            result = exp.lammps_result_json or {}
            if not result.get("group_energy_spec"):
                raise ContractError(ErrorCode.VALIDATION_ERROR, "No group_energy_spec found")
            if not result.get("dump_files"):
                raise ContractError(ErrorCode.VALIDATION_ERROR, "No trajectory files found")

            candidate_dirs: list[Path] = []
            if exp.lammps_working_dir:
                candidate_dirs.append(Path(exp.lammps_working_dir))
            if exp.input_file_path:
                candidate_dirs.append(Path(exp.input_file_path).parent)
            if exp.data_file_path:
                candidate_dirs.append(Path(exp.data_file_path).parent)

            data_exists = bool(exp.data_file_path and Path(exp.data_file_path).exists())
            if not data_exists:
                data_exists = any((path / "data.lammps").exists() for path in candidate_dirs)
            if not data_exists:
                raise ContractError(ErrorCode.VALIDATION_ERROR, "No LAMMPS data file found")

            dump_files = result.get("dump_files") or []
            dump_exists = any(Path(path).exists() for path in dump_files)
            if not dump_exists:
                standard_names = (
                    "dump_npt_production.lammpstrj",
                    "dump_npt_equilibration.lammpstrj",
                    "dump_viscosity_nemd.lammpstrj",
                )
                dump_exists = any(
                    (path / name).exists() for path in candidate_dirs for name in standard_names
                )
            if not dump_exists:
                raise ContractError(ErrorCode.VALIDATION_ERROR, "No readable trajectory file found")

    def _has_active_job(self, exp_id: str) -> bool:
        """Check for active analysis job."""
        with session_scope() as session:
            return (
                session.query(AnalysisJobModel)
                .filter(
                    AnalysisJobModel.exp_id == exp_id,
                    AnalysisJobModel.status.in_(["queued", "running"]),
                )
                .first()
                is not None
            )

    def _normalize_metrics(self, metrics: list[str] | None) -> list[str]:
        """Normalize and validate v1 metric requests."""
        requested = metrics or DEFAULT_CPU_RERUN_METRICS
        normalized = [metric for metric in requested if metric]
        if not normalized:
            normalized = DEFAULT_CPU_RERUN_METRICS

        unsupported = sorted(set(normalized) - SUPPORTED_CPU_RERUN_METRICS)
        if unsupported:
            raise ContractError(
                ErrorCode.VALIDATION_ERROR,
                f"Unsupported CPU rerun E_inter metric(s) for v1: {', '.join(unsupported)}",
            )
        return normalized


DEFAULT_E_INTER_COMPUTE_SERVICE = EInterComputeService()
