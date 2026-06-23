"""
MD simulation pipeline — build → protocol → execute → metrics → store.

Orchestrates the full workflow with injected dependencies for
structure builder, protocol generator, LAMMPS runner, and metric calculator.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from common.logging import ExperimentLogger, get_logger
from contracts.interfaces import (
    IExperimentRepository,
    ILAMMPSRunner,
    IMetricCalculator,
    IMetricRepository,
    IProtocolGenerator,
    IStructureBuilder,
)
from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS
from contracts.policies.failure import DEFAULT_FAILURE_POLICY
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import (
    BuildRequest,
    BuildResult,
    ExperimentRecord,
    ExperimentStatus,
    LAMMPSRunResult,
    MetricResult,
    ProtocolRequest,
    ProtocolResult,
    RunTier,
    StudyType,
)
from features.dashboard.build_progress import compute_build_percent
from orchestrator.exp_id_helper import generate_exp_id_from_material

if TYPE_CHECKING:
    from orchestrator.celery_job_manager import CeleryJobManager
    from protocols.duration_adjuster import StageDurationOverride

logger = get_logger("orchestrator.pipeline")


class Pipeline:
    """
    Main pipeline for MD simulation workflow.

    This skeleton version uses injected dependencies (mocks in Phase 0,
    real implementations in Phase 2).

    Workflow:
    1. Validate composition
    2. Build structure (Packmol)
    3. Generate protocol (LAMMPS input)
    4. Run simulation (LAMMPS)
    5. Parse outputs and calculate metrics
    6. Store results in database
    """

    def __init__(
        self,
        builder: IStructureBuilder,
        protocol: IProtocolGenerator,
        calculator: IMetricCalculator,
        repository: IExperimentRepository,
        runner: ILAMMPSRunner | None = None,
        metric_repository: IMetricRepository | None = None,
        job_manager: "CeleryJobManager | None" = None,
    ):
        """
        Initialize pipeline with dependencies.

        Args:
            builder: Structure builder implementation
            protocol: Protocol generator implementation
            calculator: Metric calculator implementation
            repository: Experiment repository implementation
            runner: Optional LAMMPS runner (None for mock mode)
            metric_repository: Optional metric repository for DB storage
            job_manager: Optional job manager for tier promotion submission
        """
        self.builder = builder
        self.protocol = protocol
        self.calculator = calculator
        self.repository = repository
        self.runner = runner
        self.metric_repository = metric_repository
        self.job_manager = job_manager

        # Policies
        self.composition_constraints = DEFAULT_COMPOSITION_CONSTRAINTS
        self.tier_policy = DEFAULT_TIER_POLICY
        self.failure_policy = DEFAULT_FAILURE_POLICY
        self.stabilization_chain = DEFAULT_STABILIZATION_CHAIN

    def build_only(
        self,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        *,
        material_id: str = "default_binder",
        exp_id: str,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
    ) -> dict:
        """
        Execute CPU-only preparation phase and return serialized artifacts.

        This phase intentionally avoids GPU/LAMMPS execution.
        """
        exp_logger = ExperimentLogger(exp_id)
        logger.info("Build-only phase started: %s", exp_id)

        # Map builder internal status → user-facing label for dashboard.
        # The FF sub-phase entries (artifact_*) below are fallbacks used only
        # when the builder emits a status code without an explicit label;
        # topology_assembly normally attaches a "[i/N mol_id] " prefixed
        # label directly.
        _BUILD_STATUS_LABELS = {
            "building_structure": ("building_structure", "Initializing build..."),
            "packing_molecules": ("packing_molecules", "Packing molecules (Packmol)..."),
            "loading_molecule_topologies": (
                "loading_topologies",
                "Loading molecule topologies...",
            ),
            "assigning_types_charges": (
                "generating_ff_params",
                "Generating FF parameters (artifact ~10 min)...",
            ),
            "artifact_antechamber": (
                "generating_ff_params",
                "부분전하 계산 (antechamber AM1-BCC)",
            ),
            "artifact_parmchk2": (
                "generating_ff_params",
                "본딩 파라미터 보완 (parmchk2)",
            ),
            "artifact_tleap": (
                "generating_ff_params",
                "토폴로지 구축 (tleap)",
            ),
            "artifact_parmed": (
                "generating_ff_params",
                "LJ/bonded 파라미터 추출 (parmed)",
            ),
        }

        def _update_build_phase(phase: str, label: str, percent: float | None = None) -> None:
            """Best-effort metadata update for dashboard build phase display.

            Additive UX fields (do not change execution behaviour):
              * ``dashboard_build_started_at`` — set on first entry to
                ``composition_validation`` of each attempt (reset on retry).
              * ``dashboard_build_completed_at`` — set when ``phase`` is
                ``build_complete`` so the dashboard can freeze elapsed.
              * ``build_progress_percent`` — monotonic-max percent in
                ``[0, 100]``; reset to 0.0 at new-attempt start.
            """
            try:
                from database.repositories.experiment_repo import ExperimentRepository
                from database.session import get_session

                with get_session() as session:
                    repo = ExperimentRepository(session)
                    experiment = repo.get_by_id(exp_id)
                    if experiment:
                        meta = dict(experiment.metadata_json or {})
                        meta["build_phase"] = phase
                        meta["build_phase_label"] = label
                        now_iso = datetime.now(UTC).isoformat()
                        if phase == "composition_validation":
                            meta["dashboard_build_started_at"] = now_iso
                            meta["dashboard_build_completed_at"] = None
                            meta["build_progress_percent"] = 0.0
                        if phase == "build_complete":
                            meta["dashboard_build_completed_at"] = now_iso
                        if percent is not None:
                            prior = meta.get("build_progress_percent") or 0.0
                            try:
                                prior_val = float(prior)
                            except (TypeError, ValueError):
                                prior_val = 0.0
                            meta["build_progress_percent"] = max(prior_val, float(percent))
                        experiment.metadata_json = meta  # type: ignore[assignment]
                        session.commit()
            except Exception as exc:
                logger.debug("build_phase metadata update failed: %s", exc)

        def _builder_progress_callback(status: str, label: str | None = None) -> None:
            """Bridge builder _emit_progress to DB metadata for dashboard.

            ``label`` (when provided) overrides the status→label fallback so
            fine-grained FF sub-phase messages (with "[i/N mol_id] " prefix)
            reach the dashboard directly.
            """
            phase, default_label = _BUILD_STATUS_LABELS.get(status, (status, f"{status}..."))
            resolved_label = label or default_label
            percent = compute_build_percent(status=status, label=resolved_label)
            if percent is None:
                percent = compute_build_percent(status=phase, label=resolved_label)
            _update_build_phase(phase, resolved_label, percent=percent)

        # Wire builder's existing progress callback to DB metadata
        self.builder.set_progress_callback(_builder_progress_callback)

        _update_build_phase("composition_validation", "Validating composition...", percent=2.0)
        exp_logger.log_phase_start("composition_validation")
        composition_mode = getattr(build_request, "composition_mode", "wt_percent")
        if composition_mode == "wt_percent":
            self._validate_composition(build_request.composition)
        exp_logger.log_phase_end("composition_validation", success=True)

        _update_build_phase("structure_build", "Starting structure build...", percent=5.0)
        exp_logger.log_phase_start("structure_build")
        build_result = self.builder.build(build_request)
        # Clear callback after build completes
        self.builder.set_progress_callback(None)
        exp_logger.log_phase_end("structure_build", success=True)

        if protocol_request.group_energy_spec is None:
            # v1: build from molecule_ordering (bulk path)
            if build_result.molecule_ordering:
                from metrics.group_assignment import GroupAssignmentBuilder

                ga_builder = GroupAssignmentBuilder()
                group_energy_spec = ga_builder.build(build_result.molecule_ordering)
                protocol_request.group_energy_spec = group_energy_spec
        # else: canonical layered path already set group_energy_spec — preserve it

        _update_build_phase("protocol_generation", "Generating LAMMPS protocol...", percent=95.0)
        exp_logger.log_phase_start("protocol_generation")
        protocol_request.data_file_path = build_result.data_file_path
        if stage_duration_overrides:
            protocol_result = self.protocol.generate(
                protocol_request,
                stage_duration_overrides=stage_duration_overrides,
            )
        else:
            protocol_result = self.protocol.generate(protocol_request)
        exp_logger.log_phase_end("protocol_generation", success=True)

        _update_build_phase("build_complete", "Build complete", percent=100.0)

        return {
            "material_id": material_id,
            "build_request": build_request.model_dump(mode="json"),
            "protocol_request": protocol_request.model_dump(mode="json"),
            "build_result": build_result.model_dump(mode="json"),
            "protocol_result": protocol_result.model_dump(mode="json"),
            "stage_duration_overrides": [
                o.model_dump(mode="json") if hasattr(o, "model_dump") else o
                for o in (stage_duration_overrides or [])
            ],
        }

    def execute_with_gpu(
        self,
        *,
        exp_id: str,
        prepared_payload: dict,
        property_calculations: dict | None = None,
        additive_type: str | None = None,
        additive_wt: float = 0.0,
        additive_mol_id: str | None = None,
    ) -> str:
        """
        Execute GPU phase from prebuilt artifacts and persist completed record.
        """
        build_request = BuildRequest.model_validate(prepared_payload["build_request"])
        protocol_request = ProtocolRequest.model_validate(prepared_payload["protocol_request"])
        build_result = BuildResult.model_validate(prepared_payload["build_result"])
        protocol_result = ProtocolResult.model_validate(prepared_payload["protocol_result"])
        material_id = str(prepared_payload.get("material_id") or "default_binder")

        exp_logger = ExperimentLogger(exp_id)
        exp_logger.log_phase_start("lammps_execution")
        lammps_result = self._run_lammps(protocol_result, exp_id=exp_id)
        exp_logger.log_phase_end("lammps_execution", success=lammps_result.success)
        if not lammps_result.success:
            raise RuntimeError(f"LAMMPS failed: {lammps_result.error_message}")

        self._attach_ced_lookup_metadata(
            lammps_result, build_request, protocol_request, protocol_result=protocol_result
        )

        exp_logger.log_phase_start("metric_calculation")
        metrics = self.calculator.calculate(lammps_result)
        exp_logger.log_phase_end("metric_calculation", success=True)

        save_result = self._save_metrics_to_db(exp_id, metrics)
        extra_metadata: dict[str, object] = {}
        if property_calculations:
            extra_metadata["property_calculations"] = property_calculations

        # Store sampling metadata for provenance tracking (v00.97.00)
        if protocol_result.sampling_metadata:
            extra_metadata["sampling_metadata"] = protocol_result.sampling_metadata

        calc_metadata = self.calculator.get_calculation_metadata()
        if calc_metadata:
            extra_metadata.update(calc_metadata)

        if save_result["status"] != "success":
            extra_metadata["metrics_save_status"] = save_result["status"]
            if save_result["error"]:
                extra_metadata["metrics_save_error"] = save_result["error"]
            if save_result["status"] == "partial":
                extra_metadata["metrics_saved_count"] = save_result["saved"]
                extra_metadata["metrics_total_count"] = save_result["total"]

        # Single-molecule vacuum: store PE as E_intra after metric calculation
        if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
            self._store_e_intra_from_metrics(
                metrics, lammps_result, build_request, protocol_request, exp_id
            )

        record = self._create_experiment_record(
            exp_id=exp_id,
            material_id=material_id,
            build_request=build_request,
            protocol_request=protocol_request,
            build_result=build_result,
            protocol_result=protocol_result,
            lammps_result=lammps_result,
            metrics=metrics,
            status=ExperimentStatus.COMPLETED,
            extra_metadata=extra_metadata if extra_metadata else None,
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
        )
        self.repository.save(record)

        run_tier_value = (
            protocol_request.run_tier.value
            if isinstance(protocol_request.run_tier, RunTier)
            else str(protocol_request.run_tier)
        )
        if self.metric_repository:
            try:
                self._try_compute_tg(
                    exp_id=exp_id,
                    material_id=material_id,
                    run_tier=run_tier_value,
                )
            except Exception as e:
                logger.warning(f"Tg post-processing failed (non-blocking): {e}")

        if protocol_request.run_tier in (RunTier.SCREENING, RunTier.CONFIRM):
            try:
                self._check_tier_promotion(
                    exp_id=exp_id,
                    current_tier=run_tier_value,
                    material_id=material_id,
                    temperature_k=protocol_request.temperature_K,
                    composition=build_request.composition,
                    seed=build_request.seed,
                )
            except Exception as e:
                logger.error(
                    "Tier promotion failed: exp_id=%s tier=%s error=%s",
                    exp_id,
                    run_tier_value,
                    e,
                    exc_info=True,
                )
        return exp_id

    def run(
        self,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        material_id: str = "default_binder",
        exp_id: str | None = None,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
        property_calculations: dict | None = None,
        # Phase 5.1: additive metadata propagation
        additive_type: str | None = None,
        additive_wt: float = 0.0,
        additive_mol_id: str | None = None,
    ) -> str:
        """
        Execute full pipeline.

        Args:
            build_request: Structure build specification
            protocol_request: Protocol specification
            material_id: Material identifier
            exp_id: Optional pre-generated experiment ID
            stage_duration_overrides: Optional stage duration overrides
            property_calculations: Optional property calculation settings
            additive_type: Additive type identifier (Phase 5.1)
            additive_wt: Additive weight percent (Phase 5.1)
            additive_mol_id: Additive molecule ID (Phase 5.1)

        Returns:
            Experiment ID
        """
        # Use provided exp_id or generate new one
        if exp_id is None:
            exp_id = generate_exp_id_from_material(
                material_id=material_id,
                temperature_k=protocol_request.temperature_K,
                ff_type=protocol_request.ff_type.value,
                atom_count=build_request.target_atoms,
                seed=build_request.seed,
            )

        exp_logger = ExperimentLogger(exp_id)
        logger.info(f"Starting pipeline for experiment: {exp_id}")
        if stage_duration_overrides:
            logger.info(
                f"Using stage duration overrides: "
                f"{[(o.stage_name, o.duration_ps or o.duration_steps) for o in stage_duration_overrides]}"
            )

        try:
            # Step 1: Validate composition (skip for mol_count mode)
            exp_logger.log_phase_start("composition_validation")
            composition_mode = getattr(build_request, "composition_mode", "wt_percent")
            if composition_mode == "wt_percent":
                self._validate_composition(build_request.composition)
            else:
                logger.info(f"Skipping wt% validation for composition_mode={composition_mode}")
            exp_logger.log_phase_end("composition_validation", success=True)

            # Step 2: Build structure
            exp_logger.log_phase_start("structure_build")
            build_result = self.builder.build(build_request)
            exp_logger.log_phase_end("structure_build", success=True)
            exp_logger.log_metric("composition_error_l1", build_result.composition_error_l1, "wt%")

            # Step 2.5: Build group energy spec from build result (Phase 4.2)
            if protocol_request.group_energy_spec is None:
                # v1: build from molecule_ordering (bulk path)
                if build_result.molecule_ordering:
                    from metrics.group_assignment import GroupAssignmentBuilder

                    ga_builder = GroupAssignmentBuilder()
                    group_energy_spec = ga_builder.build(build_result.molecule_ordering)
                    protocol_request.group_energy_spec = group_energy_spec
            # else: canonical layered path already set group_energy_spec — preserve it

            # Step 3: Generate protocol
            exp_logger.log_phase_start("protocol_generation")
            protocol_request.data_file_path = build_result.data_file_path
            if stage_duration_overrides:
                protocol_result = self.protocol.generate(
                    protocol_request,
                    stage_duration_overrides=stage_duration_overrides,
                )
            else:
                protocol_result = self.protocol.generate(protocol_request)
            exp_logger.log_phase_end("protocol_generation", success=True)

            # Step 4: Run LAMMPS (or mock)
            exp_logger.log_phase_start("lammps_execution")
            lammps_result = self._run_lammps(protocol_result, exp_id=exp_id)
            # Attach group energy spec for metric calculation (Phase 4.2)
            if protocol_request.group_energy_spec:
                lammps_result.group_energy_spec = protocol_request.group_energy_spec

            # Layer v2: set interface_area_nm2 from build_request box_dimensions
            _st_val = (
                protocol_request.study_type.value
                if hasattr(protocol_request.study_type, "value")
                else str(protocol_request.study_type)
            )
            if _st_val == "layer_bulkff" and build_request.box_dimensions:
                _lx, _ly, _lz = build_request.box_dimensions
                lammps_result.interface_area_nm2 = float(_lx) * float(_ly) / 100.0

            exp_logger.log_phase_end("lammps_execution", success=lammps_result.success)

            if not lammps_result.success:
                raise RuntimeError(f"LAMMPS failed: {lammps_result.error_message}")

            # Step 5: Calculate metrics
            self._attach_ced_lookup_metadata(
                lammps_result,
                build_request,
                protocol_request,
                protocol_result=protocol_result,
            )
            exp_logger.log_phase_start("metric_calculation")
            metrics = self.calculator.calculate(lammps_result)
            exp_logger.log_phase_end("metric_calculation", success=True)

            for metric in metrics:
                if metric.value is not None:
                    exp_logger.log_metric(metric.metric_name, metric.value, metric.unit)

            # Step 6: Save metrics to metrics table separately
            save_result = self._save_metrics_to_db(exp_id, metrics)

            # Single-molecule vacuum: store PE as E_intra (run() path)
            if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
                self._store_e_intra_from_metrics(
                    metrics, lammps_result, build_request, protocol_request, exp_id
                )

            # Step 7: Create and save experiment record
            # Include metrics save status + calculator metadata in record
            extra_metadata: dict[str, object] = {}

            if property_calculations:
                extra_metadata["property_calculations"] = property_calculations

            # Propagate viscosity (and future) calculation metadata
            calc_metadata = self.calculator.get_calculation_metadata()
            if calc_metadata:
                extra_metadata.update(calc_metadata)

            if save_result["status"] != "success":
                extra_metadata["metrics_save_status"] = save_result["status"]
                if save_result["error"]:
                    extra_metadata["metrics_save_error"] = save_result["error"]
                if save_result["status"] == "partial":
                    extra_metadata["metrics_saved_count"] = save_result["saved"]
                    extra_metadata["metrics_total_count"] = save_result["total"]

            record = self._create_experiment_record(
                exp_id=exp_id,
                material_id=material_id,
                build_request=build_request,
                protocol_request=protocol_request,
                build_result=build_result,
                protocol_result=protocol_result,
                lammps_result=lammps_result,
                metrics=metrics,
                status=ExperimentStatus.COMPLETED,
                extra_metadata=extra_metadata if extra_metadata else None,
                additive_type=additive_type,
                additive_wt=additive_wt,
                additive_mol_id=additive_mol_id,
            )
            self.repository.save(record)

            # Step 7.5: Non-blocking Tg post-processing
            if self.metric_repository:
                try:
                    self._try_compute_tg(
                        exp_id=exp_id,
                        material_id=material_id,
                        run_tier=protocol_request.run_tier.value
                        if isinstance(protocol_request.run_tier, RunTier)
                        else protocol_request.run_tier,
                    )
                except Exception as e:
                    logger.warning(f"Tg post-processing failed (non-blocking): {e}")

            # Step 8: Non-blocking tier promotion check
            if protocol_request.run_tier in (RunTier.SCREENING, RunTier.CONFIRM):
                try:
                    self._check_tier_promotion(
                        exp_id=exp_id,
                        current_tier=protocol_request.run_tier.value
                        if isinstance(protocol_request.run_tier, RunTier)
                        else protocol_request.run_tier,
                        material_id=material_id,
                        temperature_k=protocol_request.temperature_K,
                        composition=build_request.composition,
                        seed=build_request.seed,
                    )
                except Exception as e:
                    logger.error(
                        "Tier promotion failed: "
                        f"exp_id={exp_id}, tier={protocol_request.run_tier}, error={e}",
                        exc_info=True,
                    )
                    # Record promotion failure in experiment metadata
                    try:
                        record = self.repository.get(exp_id)
                        if record is not None:
                            if not record.metadata:
                                record.metadata = {}
                            record.metadata["promotion_failed"] = True
                            record.metadata["promotion_error"] = str(e)
                            self.repository.save(record)
                    except Exception as meta_err:
                        logger.warning(f"Failed to record promotion failure metadata: {meta_err}")

            logger.info(f"Pipeline completed successfully: {exp_id}")
            return exp_id

        except Exception as e:
            logger.error(f"Pipeline failed: {exp_id} - {str(e)}")
            exp_logger.log_error("PIPELINE_ERROR", str(e))

            # Save failed experiment record
            record = self._create_experiment_record(
                exp_id=exp_id,
                material_id=material_id,
                build_request=build_request,
                protocol_request=protocol_request,
                status=ExperimentStatus.FAILED,
                additive_type=additive_type,
                additive_wt=additive_wt,
                additive_mol_id=additive_mol_id,
            )
            try:
                self.repository.save(record)
            except Exception:
                pass  # Don't fail on save error

            raise

    @staticmethod
    def _store_e_intra_from_metrics(
        metrics: list,
        lammps_result: LAMMPSRunResult,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        exp_id: str,
    ) -> None:
        """Store PE_total as E_intra for single-molecule vacuum experiments.

        Delegates to the shared helper in ``features.common.e_intra_helper``
        while preserving fail-closed semantics for SM jobs.
        """
        try:
            from contracts.schema_enums import StudyType

            # Extract mol_id from composition (single molecule → 1 entry)
            mol_id = None
            if build_request.composition_mode == "mol_count":
                mol_ids = list(build_request.composition.keys())
                if mol_ids:
                    mol_id = mol_ids[0]

            if not mol_id:
                logger.warning("Cannot determine mol_id for E_intra storage (exp=%s)", exp_id)
                if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
                    raise RuntimeError(
                        f"Cannot determine mol_id for single-molecule vacuum job {exp_id}"
                    )
                return

            from features.common.e_intra_helper import store_e_intra_from_metrics

            # PR 2 (Method 1a SSOT): use the method tag persisted at LAMMPS
            # input-generation time on ``lammps_result.e_intra_method``.  Do
            # not re-read env/data_file here — that was the silent-mismatch
            # path identified by peer-review.  Fall back only to default if
            # the tag was not populated (legacy path / non-SM study type).
            method_tag = getattr(lammps_result, "e_intra_method", None) or "single_molecule_vacuum"

            stored = store_e_intra_from_metrics(
                mol_id=mol_id,
                metrics=metrics,
                ff_type=protocol_request.ff_type.value,
                temperature_k=protocol_request.temperature_K,
                exp_id=exp_id,
                session=None,  # Use own session_scope (pipeline runs outside request session)
                method=method_tag,
            )

            if not stored:
                # Fail-closed for single_molecule_vacuum
                if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
                    raise RuntimeError(
                        f"Missing potential_energy metric for single-molecule vacuum job {exp_id}"
                    )

        except Exception as exc:
            # v01.02.17: fail-closed for single-molecule jobs
            logger.exception("Failed to store E_intra for exp=%s: %s", exp_id, exc)
            from contracts.schemas import StudyType

            if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
                raise RuntimeError(
                    f"E_intra storage failed for single-molecule job {exp_id}: {exc}"
                ) from exc
            # For other study types, log and continue (best-effort)

    @staticmethod
    def _attach_ced_lookup_metadata(
        lammps_result: LAMMPSRunResult,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        *,
        protocol_result: "ProtocolResult | None" = None,
    ) -> None:
        """Populate CED E_intra lookup fields on LAMMPSRunResult.

        Must be called before metric calculation so that CED calculator
        can perform exact-temperature E_intra lookup.  Works for both
        ``execute_with_gpu()`` and ``run()`` paths.

        PR 2 (Method 1a SSOT): also resolves and persists the E_intra method
        tag and vacuum cutoff *once* here, so the storage path does not need
        to re-read env/data_file.  This eliminates the "two-place re-inference"
        race identified by Codex peer-review.
        """
        if build_request.composition_mode == "mol_count":
            lammps_result.mol_counts = {k: int(v) for k, v in build_request.composition.items()}
        elif build_request.composition_mode == "wt_percent" and getattr(
            protocol_request, "ced_provenance_mol_counts", None
        ):
            lammps_result.mol_counts = {
                str(mol_id): int(count)
                for mol_id, count in (protocol_request.ced_provenance_mol_counts or {}).items()
                if str(mol_id).strip() and int(count) > 0
            }
        if getattr(protocol_request, "ced_provenance_mol_counts_by_layer", None):
            lammps_result.mol_counts_by_layer = {
                str(layer_label): {
                    str(mol_id): int(count)
                    for mol_id, count in (mol_counts or {}).items()
                    if str(mol_id).strip() and int(count) > 0
                }
                for layer_label, mol_counts in (
                    protocol_request.ced_provenance_mol_counts_by_layer or {}
                ).items()
                if str(layer_label).strip()
            }
        if getattr(protocol_request, "ced_provenance_layer_volumes_A3", None):
            lammps_result.layer_volumes_A3 = {
                str(layer_label): float(volume)
                for layer_label, volume in (
                    protocol_request.ced_provenance_layer_volumes_A3 or {}
                ).items()
                if str(layer_label).strip() and float(volume) > 0.0
            }
        if getattr(protocol_request, "ced_provenance_layer_labels", None):
            lammps_result.layer_labels = [
                str(label)
                for label in (protocol_request.ced_provenance_layer_labels or [])
                if str(label).strip()
            ]
        lammps_result.temperature_K = protocol_request.temperature_K
        lammps_result.force_field = get_ff_display_label(protocol_request.ff_type.value)
        lammps_result.ff_version = get_ff_version(protocol_request.ff_type.value)
        lammps_result.study_type = (
            protocol_request.study_type.value
            if hasattr(protocol_request.study_type, "value")
            else str(protocol_request.study_type)
        )
        if getattr(protocol_request, "e_intra_method", None):
            lammps_result.e_intra_method = protocol_request.e_intra_method

        exp_id_for_lookup = getattr(lammps_result, "exp_id", None)
        exp_meta: dict[str, object] = {}
        if exp_id_for_lookup:
            try:
                from database.connection import session_scope
                from database.models import ExperimentModel
                from database.models.experiment import ExperimentMoleculeModel
                from database.models.molecule import MoleculeModel

                with session_scope() as session:
                    exp_row = (
                        session.query(ExperimentModel)
                        .filter(ExperimentModel.exp_id == exp_id_for_lookup)
                        .first()
                    )
                    exp_meta = getattr(exp_row, "metadata_json", None) or {}

                    if not getattr(lammps_result, "mol_counts", None) and exp_row is not None:
                        mol_rows = (
                            session.query(ExperimentMoleculeModel, MoleculeModel)
                            .join(
                                MoleculeModel,
                                ExperimentMoleculeModel.molecule_id == MoleculeModel.id,
                            )
                            .filter(ExperimentMoleculeModel.experiment_id == exp_row.id)
                            .all()
                        )
                        if mol_rows:
                            lammps_result.mol_counts = {
                                molecule.mol_id: int(exp_mol.count)
                                for exp_mol, molecule in mol_rows
                                if int(getattr(exp_mol, "count", 0) or 0) > 0
                                and str(getattr(molecule, "mol_id", "") or "").strip()
                            }
                        else:
                            meta_counts = (
                                (exp_meta.get("ced_provenance") or {}).get("mol_counts")
                                or exp_meta.get("mol_counts")
                                or {}
                            )
                            if isinstance(meta_counts, dict):
                                lammps_result.mol_counts = {
                                    str(mol_id): int(count)
                                    for mol_id, count in meta_counts.items()
                                    if str(mol_id or "").strip() and int(count) > 0
                                }
                    ced_meta = (
                        (exp_meta.get("ced_provenance") or {}) if isinstance(exp_meta, dict) else {}
                    )
                    if not getattr(lammps_result, "mol_counts_by_layer", None):
                        meta_by_layer = ced_meta.get("mol_counts_by_layer") or {}
                        if isinstance(meta_by_layer, dict):
                            lammps_result.mol_counts_by_layer = {
                                str(layer_label): {
                                    str(mol_id): int(count)
                                    for mol_id, count in (mol_counts or {}).items()
                                    if str(mol_id).strip() and int(count) > 0
                                }
                                for layer_label, mol_counts in meta_by_layer.items()
                                if str(layer_label).strip() and isinstance(mol_counts, dict)
                            }
                    if not getattr(lammps_result, "layer_volumes_A3", None):
                        meta_volumes = ced_meta.get("layer_volumes_A3") or {}
                        if isinstance(meta_volumes, dict):
                            lammps_result.layer_volumes_A3 = {
                                str(layer_label): float(volume)
                                for layer_label, volume in meta_volumes.items()
                                if str(layer_label).strip() and float(volume) > 0.0
                            }
                    if not getattr(lammps_result, "layer_labels", None):
                        meta_labels = ced_meta.get("layer_labels") or []
                        if isinstance(meta_labels, list):
                            lammps_result.layer_labels = [
                                str(label) for label in meta_labels if str(label).strip()
                            ]
            except Exception as exc:
                logger.warning(
                    "structured CED provenance lookup failed for exp=%s: %s",
                    exp_id_for_lookup,
                    exc,
                )

        if getattr(lammps_result, "e_intra_method", None) is None:
            meta_method = (exp_meta.get("ced_provenance") or {}).get(
                "e_intra_method"
            ) or exp_meta.get("e_intra_method")
            if meta_method:
                from contracts.schema_enums import normalize_e_intra_method

                lammps_result.e_intra_method = normalize_e_intra_method(meta_method)

        # Persist E_intra method provenance for SINGLE_MOLECULE_VACUUM only.
        # PR 2 SSOT (Codex Round 3): primary source is structured provenance
        # — submission metadata_json["e_intra_method"] (set by single_molecule
        # submitter at experiment-creation time).  Input file detection is a
        # secondary verification path; env-driven resolution is the last
        # resort.  This eliminates ambient-env reads on the read path.
        if protocol_request.study_type == StudyType.SINGLE_MOLECULE_VACUUM:
            from pathlib import Path

            # PR 2 (Codex Round 6): import the lightweight detector module
            # directly so the pipeline worker does not pull in
            # features.scan_database.router (FastAPI/Starlette).
            from protocols.e_intra_method_detect import (
                detect_e_intra_method_from_input as _detect_e_intra_method_from_input,
            )
            from protocols.lammps_force_field import (
                VACUUM_DEFAULT_CUTOFF_A,
            )

            method_tag: str | None = None
            cutoff: float | None = None

            # 0) PR 2 (Codex Round 7): generation-time SSOT — if the
            # ProtocolResult was passed in with a structured method/cutoff
            # decided by ``generate_force_field``, use it directly.  The
            # subsequent metadata / input-file / env paths become
            # verification-only when this is set.
            if protocol_result is not None:
                method_tag = protocol_result.e_intra_method or method_tag
                if protocol_result.vacuum_cutoff_a is not None:
                    cutoff = protocol_result.vacuum_cutoff_a

            # 1) Structured provenance: the experiment row's metadata_json.
            # ``exp_id`` is read from the LAMMPS run result (set by the
            # pipeline driver before this helper is invoked) — referencing
            # an undefined free variable here was the Round 4 bug.
            if method_tag is None and exp_id_for_lookup:
                method_tag = (
                    (exp_meta.get("ced_provenance") or {}).get("e_intra_method")
                    or exp_meta.get("e_intra_method")
                    or None
                )
            else:
                logger.debug("structured E_intra provenance skipped: lammps_result.exp_id is unset")

            # 2) Input-file ground truth (verification + cutoff capture).
            log_file = getattr(lammps_result, "log_file", None)
            if log_file:
                run_dir = Path(log_file).parent
                for candidate in (run_dir / "in.lammps", run_dir / "input.lammps"):
                    if candidate.is_file():
                        detected = _detect_e_intra_method_from_input(str(candidate))
                        if method_tag is None:
                            method_tag = detected
                        elif method_tag != detected:
                            # PR 2 (Codex Round 5): use exp_id_for_lookup
                            # (the staticmethod has no ``exp_id`` in scope —
                            # the previous reference would NameError when
                            # methods drifted between metadata and input).
                            logger.warning(
                                "E_intra method drift for exp=%s: "
                                "metadata=%s, input_file=%s — using metadata",
                                exp_id_for_lookup or "?",
                                method_tag,
                                detected,
                            )
                        try:
                            for raw in candidate.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines():
                                line = raw.strip()
                                if line.startswith("pair_style") and (
                                    "lj/cut/coul/cut" in line or "lj/cut " in line
                                ):
                                    parts = line.split()
                                    for tok in reversed(parts):
                                        try:
                                            cutoff = float(tok)
                                            break
                                        except ValueError:
                                            continue
                                    break
                        except OSError:
                            cutoff = None
                        break

            # 3) Conservative last resort.
            #
            # Read/runtime paths must not resolve against the *current*
            # submission default or ambient env. If structured provenance,
            # experiment metadata, and the generated input file are all
            # unavailable, fail back to the baseline Method 1 contract
            # explicitly instead of re-reading submission-time knobs.
            if method_tag is None:
                method_tag = "single_molecule_vacuum"
                cutoff = VACUUM_DEFAULT_CUTOFF_A
                logger.warning(
                    "Missing E_intra provenance for exp=%s; using conservative "
                    "Method 1 baseline instead of ambient env/settings fallback",
                    exp_id_for_lookup or "?",
                )

            lammps_result.e_intra_method = method_tag
            lammps_result.vacuum_cutoff_a = cutoff

    def _validate_composition(self, composition: dict[str, float]) -> None:
        """Validate composition against constraints."""
        is_valid, error = self.composition_constraints.validate_composition(composition)
        if not is_valid:
            raise ValueError(f"Composition validation failed: {error}")

    def _run_lammps(
        self, protocol_result: ProtocolResult, exp_id: str | None = None
    ) -> LAMMPSRunResult:
        """
        Run LAMMPS simulation.

        In Phase 0 (skeleton), this returns a mock result.
        In Phase 2, this will use the real runner.

        Args:
            protocol_result: Protocol with input script path
            exp_id: Experiment ID for process tracking
        """
        if self.runner is not None:
            return self.runner.run(protocol_result, exp_id=exp_id)

        # Mock result for skeleton phase
        logger.warning("Running in mock mode - no actual LAMMPS execution")
        return LAMMPSRunResult(
            success=True,
            log_file="/mock/log.lammps",
            dump_files=["/mock/dump.lammpstrj"],
            wall_time_seconds=0.0,
            exit_code=0,
            exp_id=exp_id,
        )

    def _save_metrics_to_db(
        self,
        exp_id: str,
        metrics: list[MetricResult] | None,
    ) -> dict:
        """
        Save metrics to the database via IMetricRepository.

        Args:
            exp_id: Experiment ID
            metrics: List of metric results

        Returns:
            Dict with status info:
            - "status": "success" | "partial" | "failed" | "skipped"
            - "saved": Number of metrics saved
            - "total": Total metrics attempted
            - "error": Error message if any
        """
        result = {
            "status": "success",
            "saved": 0,
            "total": 0,
            "error": None,
        }

        if not metrics:
            result["status"] = "skipped"
            return result

        if not self.metric_repository:
            logger.warning("MetricRepository not injected; skipping metric save")
            result["status"] = "skipped"
            result["error"] = "MetricRepository not injected"
            return result

        try:
            # Create copies with exp_id set to avoid mutating input objects
            metrics_to_save = []
            for metric in metrics:
                if metric.value is not None or metric.array_storage is not None:
                    metric_copy = metric.model_copy(update={"exp_id": exp_id})
                    metrics_to_save.append(metric_copy)

            result["total"] = len(metrics_to_save)

            if not metrics_to_save:
                result["status"] = "skipped"
                return result

            # Use batch save (single transaction)
            saved_count = self.metric_repository.save_batch(metrics_to_save)
            result["saved"] = saved_count

            if saved_count < len(metrics_to_save):
                result["status"] = "partial"
                logger.warning(
                    f"Partial metric save for {exp_id}: {saved_count}/{len(metrics_to_save)}"
                )
            else:
                logger.info(f"Saved {saved_count} metrics for experiment: {exp_id}")

        except Exception as e:
            logger.error(f"Failed to save metrics to DB for {exp_id}: {e}", exc_info=True)
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    def _create_experiment_record(
        self,
        exp_id: str,
        material_id: str,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        build_result: BuildResult | None = None,
        protocol_result: ProtocolResult | None = None,
        lammps_result: LAMMPSRunResult | None = None,
        metrics: list[MetricResult] | None = None,
        status: ExperimentStatus = ExperimentStatus.PENDING,
        extra_metadata: dict | None = None,
        # Phase 5.1: additive metadata propagation
        additive_type: str | None = None,
        additive_wt: float = 0.0,
        additive_mol_id: str | None = None,
    ) -> ExperimentRecord:
        """Create experiment record for database storage.

        Args:
            exp_id: Experiment ID
            material_id: Material identifier
            build_request: Build request specification
            protocol_request: Protocol request specification
            build_result: Build result (optional)
            protocol_result: Protocol result (optional)
            lammps_result: LAMMPS run result (optional)
            metrics: List of metric results (optional)
            status: Experiment status
            extra_metadata: Additional metadata to include in record (optional)
            additive_type: Additive type identifier (Phase 5.1)
            additive_wt: Additive weight percent (Phase 5.1)
            additive_mol_id: Additive molecule ID (Phase 5.1)

        Returns:
            ExperimentRecord for database storage
        """
        record = ExperimentRecord(
            exp_id=exp_id,
            material_id=material_id,
            force_field_type=protocol_request.ff_type,
            force_field_name=get_ff_display_label(protocol_request.ff_type.value),
            force_field_version=get_ff_version(protocol_request.ff_type.value),
            study_type=protocol_request.study_type.value,
            run_tier=protocol_request.run_tier,
            temperature_k=protocol_request.temperature_K,
            pressure_atm=protocol_request.pressure_atm,
            target_atoms=build_request.target_atoms,
            validity_domain_tag=self.composition_constraints.get_validity_tags(
                build_request.composition
            )
            if build_request
            else [],
            status=status,
            build_result=build_result,
            protocol_result=protocol_result,
            lammps_result=lammps_result,
            metrics=metrics or [],
            completed_at=datetime.now() if status == ExperimentStatus.COMPLETED else None,
            # Phase 5.1: additive metadata
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
        )

        # Collect per-molecule source trace from build_result + artifact resolver
        _organic_sources: list[dict[str, str]] = []
        try:
            from features.molecules.artifact_service import resolve_artifact_target

            _seen_sids: set[str] = set()
            for mol_entry in build_result.molecule_ordering or []:
                mid = mol_entry.get("mol_id", "")
                if not mid:
                    continue
                try:
                    target = resolve_artifact_target(mid)
                    sid = target.source_id
                    if sid in _seen_sids:
                        continue
                    _seen_sids.add(sid)
                    # Read generation_profile from admin sidecar if available
                    _gp = "baseline"
                    try:
                        from features.molecules.admin_status import AdminStatusStore
                        from features.molecules.artifact_service import ARTIFACT_DIR

                        _sidecar = AdminStatusStore(ARTIFACT_DIR).get(sid)
                        if _sidecar and _sidecar.generation_profile:
                            _gp = _sidecar.generation_profile
                    except Exception:
                        pass
                    # Derive generator from the profile so build_ff_provenance
                    # can downgrade fragment-fallback artifacts to the
                    # research_only stack (fragment_fallback profile <=>
                    # fragment_fallback_gaff2 generator by construction).
                    _gen = (
                        "fragment_fallback_gaff2"
                        if _gp == "fragment_fallback"
                        else "antechamber_am1bcc"
                    )
                    _organic_sources.append(
                        {
                            "mol_id": mid,
                            "source_id": sid,
                            "ff_family": "gaff2",
                            "generation_profile": _gp,
                            "generator": _gen,
                        }
                    )
                except Exception:
                    continue
        except Exception:
            pass  # source collection is best-effort

        # Build FF provenance for final save
        from contracts.policies.forcefield import build_ff_provenance

        prov = build_ff_provenance(
            study_type=protocol_request.study_type.value,
            ff_type=protocol_request.ff_type.value,
            source_tag="pipeline_final_save",
            metadata_json=extra_metadata,
            build_request=build_request,
            organic_sources=_organic_sources or None,
        )

        # Merge extra metadata + provenance
        if hasattr(record, "metadata"):
            if record.metadata is None:
                record.metadata = {}
            if extra_metadata:
                record.metadata.update(extra_metadata)
            record.metadata["ff_provenance"] = prov["metadata"]

        # Attach conditions for repo.save() → _replace_conditions()
        if hasattr(record, "conditions"):
            record.conditions = prov["conditions"]

        return record

    def _check_tier_promotion(
        self,
        exp_id: str,
        current_tier: str,
        material_id: str,
        temperature_k: float,
        composition: dict,
        seed: int,
    ) -> None:
        """Check and submit tier promotion if warranted (non-blocking).

        Requires metric_repository to be injected. Silently skips otherwise.

        Args:
            exp_id: Current experiment ID
            current_tier: Current tier name
            material_id: Material identifier
            temperature_k: Temperature in Kelvin
            composition: Composition dict
            seed: Random seed
        """
        if not self.metric_repository:
            return

        from orchestrator.tier_promoter import TierPromoter
        from orchestrator.zscore_service import ZScoreService

        zscore_service = ZScoreService(
            metric_repo=self.metric_repository,
            experiment_repo=self.repository,
        )
        promoter = TierPromoter(
            zscore_service=zscore_service,
            experiment_repo=self.repository,
            job_manager=self.job_manager,
        )
        promoted_id = promoter.maybe_promote(
            exp_id=exp_id,
            current_tier=current_tier,
            material_id=material_id,
            temperature_k=temperature_k,
            composition=composition,
            seed=seed,
        )
        if promoted_id:
            logger.info(f"Tier promotion triggered: {exp_id} -> {promoted_id}")

    def _try_compute_tg(
        self,
        exp_id: str,
        material_id: str,
        run_tier: str,
    ) -> None:
        """Attempt cross-experiment Tg calculation (non-blocking).

        Args:
            exp_id: Anchor experiment ID for Tg metric storage.
            material_id: Material identifier for sibling experiment filtering.
            run_tier: Current run tier.
        """
        from orchestrator.tg_post_processor import TgPostProcessor

        processor = TgPostProcessor(
            metric_repo=self.metric_repository,
            experiment_repo=self.repository,
        )
        result = processor.try_compute_tg(exp_id, material_id, run_tier)
        if result and result.tg_k is not None:
            logger.info(f"Tg computed: {result.tg_k:.1f} K for {material_id}")
