"""FastAPI application bootstrap."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from api.runtime_state import clear_recovery_components, set_recovery_components
from common.logging import get_logger
from common.pathing import parse_exp_id
from contracts import __version__
from contracts.errors import ContractError
from database import close_db, init_db
from features.amorphous_cells import router as amorphous_cells_router
from features.analysis import router as analysis_router
from features.batch_job_binder_cell import router as batch_job_binder_cell_router
from features.benchmark import router as benchmark_router
from features.campaign import router as campaign_router
from features.crystal_structures import router as crystal_structures_router
from features.data_sync import router as data_sync_router
from features.e_inter_compute import router as e_inter_router
from features.experiments.router import router as experiments_router
from features.health import router as health_router
from features.interface_molecules import router as interface_molecules_router
from features.inverse_design_pipeline.router import router as inverse_pipeline_router
from features.jobs import router as jobs_router
from features.layered_structures.router import router as layered_structures_router
from features.metrics import router as metrics_router
from features.mlops import router as mlops_router
from features.molecules import router as molecules_router
from features.protocol import router as protocol_router
from features.recommendations import router as recommendations_router
from features.recovery import router as recovery_router
from features.scan_database.router import router as scan_database_router
from features.structure import router as structure_router
from features.system.router import router as system_router

# Additive Coverage (Phase 4)
try:
    from features.additive_coverage.router import router as additive_coverage_router

    ADDITIVE_COVERAGE_AVAILABLE = True
except ImportError:
    ADDITIVE_COVERAGE_AVAILABLE = False

logger = get_logger("api.main")


def _auto_resubmit_pending_experiments() -> int:
    """Auto-resubmit pending experiments on API startup."""
    from config.settings import get_settings
    from database.connection import session_scope
    from database.models import ExperimentModel

    if not get_settings().auto_resubmit_pending_on_startup:
        logger.info("Startup auto-resubmit disabled (auto_resubmit_pending_on_startup=false)")
        return 0

    resubmitted = 0

    try:
        with session_scope() as session:
            pending_exps = (
                session.query(ExperimentModel)
                .filter(
                    ExperimentModel.status == "pending",
                    ExperimentModel.data_file_path.isnot(None),
                )
                .all()
            )

            if not pending_exps:
                return 0

            logger.info(f"Found {len(pending_exps)} pending experiments to resubmit")

            from common.seed import generate_seed
            from contracts.schemas import FFType, RunTier
            from orchestrator.request_factory import create_build_request, create_protocol_request
            from orchestrator.tasks import run_simulation

            for exp in pending_exps:
                try:
                    from pathlib import Path

                    if not Path(exp.data_file_path).exists():
                        logger.warning(
                            f"Skipping {exp.exp_id}: data file not found at {exp.data_file_path}"
                        )
                        continue

                    composition = {
                        "asphaltene": exp.comp_asphaltene_wt or 0.0,
                        "resin": exp.comp_resin_wt or 0.0,
                        "aromatic": exp.comp_aromatic_wt or 0.0,
                        "saturate": exp.comp_saturate_wt or 0.0,
                    }

                    run_tier = RunTier(exp.run_tier or "screening")
                    ff_type = FFType(exp.ff_type or "bulk_ff_gaff2")

                    build_request = create_build_request(
                        composition=composition,
                        target_atoms=exp.target_atoms,
                        seed=generate_seed(exp.seed),
                        tier=run_tier,
                    )
                    protocol_request = create_protocol_request(
                        tier=run_tier,
                        ff_type=ff_type,
                        temperature_K=exp.temperature_K or 298.0,
                        pressure_atm=exp.pressure_atm or 1.0,
                        data_file_path=exp.data_file_path,
                    )

                    material_id = parse_exp_id(exp.exp_id).get("binder_type", "resubmitted")

                    task = run_simulation.delay(
                        build_request_dict=build_request.model_dump(),
                        protocol_request_dict=protocol_request.model_dump(),
                        material_id=material_id,
                        exp_id=exp.exp_id,
                    )

                    from database.repositories.experiment_repo import ExperimentRepository

                    repo = ExperimentRepository(session)
                    repo.update_celery_task_id(exp.exp_id, task.id)
                    exp.recovery_status = "auto_resubmitted"
                    resubmitted += 1
                    logger.info(f"Resubmitted {exp.exp_id} with new task {task.id}")
                except Exception as exc:
                    logger.error(f"Failed to resubmit {exp.exp_id}: {exc}")

            session.commit()

        if resubmitted > 0:
            logger.info(f"Auto-resubmitted {resubmitted} pending experiments")
    except Exception as exc:
        logger.error(f"Failed to auto-resubmit pending experiments: {exc}")

    return resubmitted


def _restore_settings_from_json() -> None:
    """Restore LLM settings from settings.json on startup.

    Uses os.environ.setdefault() so explicit env vars (.env file) take priority.
    """
    import os

    from config.dashboard_settings import (
        apply_llm_env_vars,
        is_plausible_llm_api_key,
        load_dashboard_settings,
        save_dashboard_settings,
    )

    settings = load_dashboard_settings()
    llm_provider = settings.get("llm_provider", "mock")

    if llm_provider != "mock":
        os.environ.setdefault("LLM_PROVIDER", llm_provider)

    llm_api_key = settings.get("llm_api_key", "")
    llm_model = settings.get("llm_model", "")

    # Skip masked API keys that were incorrectly persisted
    if llm_api_key and llm_api_key.startswith("***"):
        logger.warning("Ignoring masked API key found in settings.json")
        llm_api_key = ""
    elif llm_api_key and not is_plausible_llm_api_key(llm_provider, llm_api_key):
        # 키가 다른 provider용일 수 있음 — provider별 슬롯에 보존 후 현재만 비움
        logger.warning(
            "API key in settings.json doesn't match provider=%s — preserving in provider slot",
            llm_provider,
        )
        # 다른 provider용이면 해당 슬롯에 보존
        for other in ("openai", "anthropic"):
            if other != llm_provider and is_plausible_llm_api_key(other, llm_api_key):
                settings[f"llm_{other}_api_key"] = llm_api_key
                break
        llm_api_key = ""
        # provider별 슬롯에서 현재 provider의 키 복원 시도
        slot_key = settings.get(f"llm_{llm_provider}_api_key", "")
        if slot_key and is_plausible_llm_api_key(llm_provider, slot_key):
            llm_api_key = slot_key
            settings["llm_api_key"] = slot_key
        else:
            settings["llm_api_key"] = ""
        save_dashboard_settings(settings)

    apply_llm_env_vars(
        llm_provider,
        llm_api_key,
        llm_model,
        use_setdefault=True,
    )

    logger.info(
        f"Settings restored from settings.json: "
        f"llm_provider={os.getenv('LLM_PROVIDER', 'mock')}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Ensure stdout/stderr use UTF-8 to prevent UnicodeEncodeError
    # when non-ASCII text (e.g. Korean location names) reaches print/logging.
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    logger.info("Starting API server")
    _restore_settings_from_json()
    init_db()

    # v00.99.91: sweep stale .generating.lock markers on startup. Lock files
    # are intentionally left in place after every generation to preserve
    # fcntl inode-lock semantics (see artifact_service.source_generation_lock
    # docstring), so they accumulate until the 6h staleness threshold.
    # Running the sweeper at boot keeps the artifact directory tidy without
    # changing the threshold or the per-acquire cleanup call that protects
    # concurrent writers.
    try:
        from features.molecules.artifact_service import (
            cleanup_stale_generation_locks,
        )

        removed = cleanup_stale_generation_locks()
        if removed:
            logger.info(
                "Startup: cleaned up %d stale .generating.lock marker(s)",
                removed,
            )
    except Exception as exc:  # never block startup on cleanup
        logger.warning("Startup stale-lock sweep failed: %s", exc)

    try:
        from orchestrator.process_recovery import ProcessRecoveryService
        from orchestrator.process_tracker import ProcessTracker

        process_tracker = ProcessTracker()
        recovery_service = ProcessRecoveryService(process_tracker)
        set_recovery_components(process_tracker, recovery_service)

        restored = recovery_service.restore_gpu_state_from_db()
        if restored > 0:
            logger.info(f"Restored {restored} GPU allocations from previous session")

        candidates = recovery_service.check_for_recovery_needed()
        if candidates:
            logger.warning(
                f"Found {len(candidates)} processes that may need recovery. "
                "Use /recovery/candidates endpoint to review."
            )

        _auto_resubmit_pending_experiments()
    except Exception as exc:
        logger.error(f"Failed to initialize process tracking: {exc}")

    yield

    logger.info("Shutting down API server")

    clear_recovery_components()
    close_db()


app = FastAPI(
    title="Asphalt Binder MD/ML Agent API",
    description="API for asphalt binder molecular dynamics simulations",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _status_code_for_contract_error(code: str) -> int:
    """Map contract error codes to HTTP status."""
    try:
        numeric = int(code.lstrip("E"))
    except ValueError:
        return 500

    if numeric in {7001, 9505}:
        return 404
    if 8000 <= numeric < 9000:
        return 503
    if 1000 <= numeric < 2000:
        return 400
    if 3000 <= numeric < 4000:
        return 400
    return 500


@app.exception_handler(ContractError)
async def contract_error_handler(_request: Request, exc: ContractError) -> JSONResponse:
    """Return consistent JSON payload for contract-layer errors."""
    payload = exc.to_dict()
    # Keep FastAPI HTTPException-compatible field for existing clients/tests.
    payload["detail"] = exc.message
    return JSONResponse(
        status_code=_status_code_for_contract_error(exc.code.value),
        content=payload,
    )


# Feature routers
app.include_router(health_router)
app.include_router(experiments_router)
app.include_router(jobs_router)
app.include_router(metrics_router)
app.include_router(molecules_router)
app.include_router(amorphous_cells_router)
app.include_router(crystal_structures_router)
app.include_router(layered_structures_router)
app.include_router(protocol_router)
app.include_router(analysis_router)
app.include_router(structure_router)
app.include_router(batch_job_binder_cell_router)
app.include_router(campaign_router)
app.include_router(recommendations_router)
app.include_router(inverse_pipeline_router)
app.include_router(mlops_router)
app.include_router(recovery_router)
app.include_router(benchmark_router)
app.include_router(system_router)
app.include_router(scan_database_router)
app.include_router(data_sync_router)
app.include_router(interface_molecules_router)
app.include_router(e_inter_router)

from features.analysis_explorer.router import router as analysis_explorer_router  # noqa: E402

app.include_router(analysis_explorer_router)

try:
    from features.binder_analysis.router import router as binder_analysis_router

    app.include_router(binder_analysis_router)
except Exception:  # pragma: no cover - optional module
    pass

if ADDITIVE_COVERAGE_AVAILABLE:
    app.include_router(additive_coverage_router)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
