"""
Celery application configuration.

Sets up the Celery application with Redis as broker and result backend.
Configures task queues, routing, and worker settings.

IMPORTANT: worker_concurrency is set to match the number of selected GPUs.
This ensures 1 GPU = 1 Job principle (no task starts without available GPU).
"""

from celery import Celery
from kombu import Exchange, Queue

from common.logging import get_logger
from config.dashboard_settings import get_selected_gpu_count
from config.settings import get_settings
from contracts.policies.ml_policy import DEFAULT_ML_POLICY

logger = get_logger("orchestrator.celery_app")

settings = get_settings()


def create_celery_app() -> Celery:
    """
    Create and configure Celery application.

    Returns:
        Configured Celery application instance
    """
    app = Celery(
        "asphalt_md",
        broker=settings.celery.broker_url,
        backend=settings.celery.result_backend,
        include=[
            "orchestrator.tasks",
        ],
    )

    # Task serialization
    app.conf.task_serializer = settings.celery.task_serializer
    app.conf.result_serializer = settings.celery.result_serializer
    app.conf.accept_content = settings.celery.accept_content

    # Timezone
    app.conf.timezone = settings.celery.timezone
    app.conf.enable_utc = settings.celery.enable_utc

    # Task tracking
    app.conf.task_track_started = settings.celery.task_track_started
    app.conf.task_time_limit = settings.celery.task_time_limit
    app.conf.task_soft_time_limit = settings.celery.task_soft_time_limit
    # Redis broker: keep visibility timeout above long-running MD tasks to
    # avoid premature redelivery while worker is still healthy.
    visibility_timeout = max(
        int(settings.celery.task_time_limit) + 3600,
        int(settings.celery.task_soft_time_limit) + 3600,
        172800,  # 48h floor for long screening/confirm batches
    )
    app.conf.broker_transport_options = {"visibility_timeout": visibility_timeout}
    app.conf.result_backend_transport_options = {"visibility_timeout": visibility_timeout}

    # Worker settings
    # worker_concurrency = total compute slots across eligible devices, which is
    # mode-aware: MPS -> sum(GPU x N); MIG -> number of MIG instances (1 slot
    # each); none -> number of GPUs. GPU allocation cap is enforced atomically by
    # gpu_service, so concurrency matches that ceiling. Slots=1 -> 1 job/GPU.
    app.conf.worker_prefetch_multiplier = settings.celery.worker_prefetch_multiplier
    gpu_count = get_selected_gpu_count()
    try:
        from monitoring.gpu_collector import total_compute_slots

        gpu_slots = total_compute_slots()
    except Exception:  # noqa: BLE001
        gpu_slots = 0
    if gpu_slots <= 0:
        # No registry info (non-GPU/test env) -> policy-derived fallback.
        try:
            from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

            slots_per_gpu = max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        except Exception:  # noqa: BLE001
            slots_per_gpu = 1
        gpu_slots = gpu_count * slots_per_gpu
    # GPU 있으면 슬롯 천장이 권위(gpu_service가 강제), 없으면 CPU-only 설정값.
    max_concurrency = gpu_slots if gpu_count > 0 else max(1, settings.celery.worker_concurrency)
    app.conf.worker_concurrency = max_concurrency
    logger.info(f"Worker concurrency set to {max_concurrency} (total compute slots)")

    # Define exchanges
    default_exchange = Exchange("default", type="direct")
    simulation_exchange = Exchange("simulation", type="direct")
    priority_exchange = Exchange("priority", type="direct")
    analysis_exchange = Exchange("analysis", type="direct")

    # Define queues
    app.conf.task_queues = (
        Queue(
            "default",
            exchange=default_exchange,
            routing_key="default",
        ),
        Queue(
            "simulation",
            exchange=simulation_exchange,
            routing_key="simulation",
        ),
        Queue(
            "simulation.screening",
            exchange=simulation_exchange,
            routing_key="simulation.screening",
        ),
        Queue(
            "simulation.confirm",
            exchange=simulation_exchange,
            routing_key="simulation.confirm",
        ),
        Queue(
            "simulation.viscosity",
            exchange=simulation_exchange,
            routing_key="simulation.viscosity",
        ),
        Queue(
            "simulation.layer",
            exchange=simulation_exchange,
            routing_key="simulation.layer",
        ),
        Queue(
            "simulation.gpu",
            exchange=simulation_exchange,
            routing_key="simulation.gpu",
        ),
        Queue(
            "metrics",
            exchange=default_exchange,
            routing_key="metrics",
        ),
        Queue(
            "priority",
            exchange=priority_exchange,
            routing_key="priority",
        ),
        Queue(
            "batch_job_binder_cell",
            exchange=default_exchange,
            routing_key="batch_job_binder_cell",
        ),
        Queue(
            "analysis.cpu",
            exchange=analysis_exchange,
            routing_key="analysis.cpu",
        ),
        # Control plane (v01.06.14): dedicated queue for lightweight, non-blocking
        # orchestration/beat tasks (scheduler, status sync, recovery, inventory).
        # Consumed ONLY by the small `control@` worker pool so it NEVER competes
        # with long-blocking GPU jobs for a worker slot. This is what guarantees
        # the dispatcher (`schedule_ready_experiments`) always runs even when all
        # GPU workers are saturated — the root fix for control-plane starvation.
        Queue(
            "control",
            exchange=default_exchange,
            routing_key="control",
        ),
    )

    # Default queue
    app.conf.task_default_queue = "default"
    app.conf.task_default_exchange = "default"
    app.conf.task_default_routing_key = "default"

    # Task routing
    app.conf.task_routes = {
        "orchestrator.tasks.run_simulation": {
            "queue": "simulation",
            "routing_key": "simulation",
        },
        "orchestrator.tasks.run_screening_simulation": {
            "queue": "simulation.screening",
            "routing_key": "simulation.screening",
        },
        "orchestrator.tasks.run_confirm_simulation": {
            "queue": "simulation.confirm",
            "routing_key": "simulation.confirm",
        },
        "orchestrator.tasks.run_viscosity_simulation": {
            "queue": "simulation.viscosity",
            "routing_key": "simulation.viscosity",
        },
        "orchestrator.tasks.run_layer_simulation": {
            "queue": "simulation.layer",
            "routing_key": "simulation.layer",
        },
        "orchestrator.tasks.run_prepared_simulation": {
            "queue": "simulation.gpu",
            "routing_key": "simulation.gpu",
        },
        "orchestrator.tasks.calculate_metrics": {
            "queue": "metrics",
            "routing_key": "metrics",
        },
        "orchestrator.tasks.priority_simulation": {
            "queue": "priority",
            "routing_key": "priority",
        },
        "orchestrator.tasks.run_additive_batch_job_binder_cell": {
            "queue": "batch_job_binder_cell",
            "routing_key": "batch_job_binder_cell",
        },
        "orchestrator.tasks.ml_continuous_learning_check": {
            "queue": "default",
            "routing_key": "default",
        },
        "orchestrator.tasks.reconcile_unprocessed_completions": {
            "queue": "default",
            "routing_key": "default",
        },
        "orchestrator.tasks.run_cpu_rerun_einter": {
            "queue": "analysis.cpu",
            "routing_key": "analysis.cpu",
        },
        # --- Control plane (v01.06.14) ---
        # Lightweight, fast, non-blocking orchestration tasks routed to the
        # dedicated `control` queue (consumed by `control@` pool only). Keeps the
        # dispatcher and recovery loops responsive regardless of GPU/CPU load.
        # The dispatch-critical scheduler MUST be here.
        "orchestrator.tasks.schedule_ready_experiments": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.sync_job_status": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.check_stalled_jobs": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.cleanup_orphaned_tasks": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.reconcile_dependency_chains": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.recover_orphan_ready_allocations": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.refresh_gpu_inventory": {
            "queue": "control",
            "routing_key": "control",
        },
        "orchestrator.tasks.cleanup_stale_exp_locks": {
            "queue": "control",
            "routing_key": "control",
        },
    }

    # Result expiration (7 days)
    app.conf.result_expires = 604800

    # Task acknowledgement
    app.conf.task_acks_late = True
    app.conf.task_reject_on_worker_lost = True

    # Retry settings
    app.conf.task_publish_retry = True
    app.conf.task_publish_retry_policy = {
        "max_retries": 3,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    }

    return app


# Create the global Celery app instance
celery_app = create_celery_app()
celery_app.set_default()  # Ensure all threads use this app (not just main thread)


# Beat schedule for periodic tasks (optional)
celery_app.conf.beat_schedule = {
    # NOTE (2026-06-17 incident): cleanup-old-jobs is DISABLED. It deleted
    # completed `single_molecule_vacuum` E_intra reference experiments (>24h old),
    # whose cascade wiped the e_intra table — repeatedly. maintenance.cleanup_old_jobs
    # was patched to exclude `completed` (only failed/cancelled/timeout are pruned),
    # so this entry is SAFE TO RE-ENABLE after a full `./start_all.sh` restart loads
    # the patched code into the worker. It is left off here as an immediate guard
    # while the long-running gpu@ worker still holds the pre-patch code in memory.
    # "cleanup-old-jobs": {
    #     "task": "orchestrator.tasks.cleanup_old_jobs",
    #     "schedule": 3600.0,  # Every hour
    #     "args": (24,),  # Older than 24 hours
    # },
    "check-stalled-jobs": {
        "task": "orchestrator.tasks.check_stalled_jobs",
        "schedule": 300.0,  # Every 5 minutes
    },
    "cleanup-orphaned-tasks": {
        "task": "orchestrator.tasks.cleanup_orphaned_tasks",
        "schedule": 600.0,  # Every 10 minutes
    },
    "sync-job-status": {
        "task": "orchestrator.tasks.sync_job_status",
        "schedule": 30.0,  # Every 30 seconds for quick status updates
    },
    "reconcile-unprocessed-completions": {
        "task": "orchestrator.tasks.reconcile_unprocessed_completions",
        "schedule": 120.0,
        "args": (20,),
    },
    "reconcile-dependency-chains": {
        "task": "orchestrator.tasks.reconcile_dependency_chains",
        "schedule": 30.0,  # Every 30 seconds
        "args": (10,),
    },
    "schedule-ready-experiments": {
        "task": "orchestrator.tasks.schedule_ready_experiments",
        "schedule": 5.0,
        "args": (10,),
    },
    # Fast reclaim of GPU slots stuck on `ready` rows whose Celery task died
    # before running (without this, such slots wait up to the 60-min stall
    # timeout). Seconds-scale recovery so a leaked slot doesn't shrink capacity.
    "recover-orphan-ready-allocations": {
        "task": "orchestrator.tasks.recover_orphan_ready_allocations",
        "schedule": 60.0,
        "args": (200,),
    },
    # Real-time GPU pool: re-detect eligible GPUs so a repaired/added GPU becomes
    # usable without a restart, and a removed one is marked OFFLINE. Non-destructive
    # to in-flight allocations (GPUService.refresh_inventory).
    "refresh-gpu-inventory": {
        "task": "orchestrator.tasks.refresh_gpu_inventory",
        "schedule": 60.0,
    },
    "cleanup-stale-exp-locks": {
        "task": "orchestrator.tasks.cleanup_stale_exp_locks",
        "schedule": 60.0,
        "args": (500,),
    },
    "ml-continuous-learning-check": {
        "task": "orchestrator.tasks.ml_continuous_learning_check",
        "schedule": float(DEFAULT_ML_POLICY.continuous_learning.check_interval_hours * 3600),
    },
}
