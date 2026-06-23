"""Batch Job Binder Cell runner — submit multiple screening experiments.

Generates binder x size x temperature x aging combinations,
checks for duplicates, and submits via Celery.

Phase 5.1: AdditiveBatchJobBinderCellRunner extends BatchJobBinderCellRunner with
additive DOE axes (type x concentration full-factorial).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from common.pathing import generate_exp_id
from common.seed import generate_seed
from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import SubmissionSource
from orchestrator.submission_facade import SubmissionFacade
from protocols.stage_plan_compiler import build_stage_plan_metadata

if TYPE_CHECKING:
    from builder.molecule_db import MoleculeDB
    from database.repositories.experiment_repo import ExperimentRepository
    from orchestrator.celery_job_manager import CeleryJobManager
    from protocols.duration_adjuster import StageDurationOverride
from orchestrator.request_factory import create_build_request, create_protocol_request

logger = get_logger("orchestrator.batch_job_binder_cell")


@dataclass
class BatchJobBinderCellJob:
    """A single job within a batch Binder Cell run."""

    exp_id: str
    binder_type: str
    structure_size: str
    temperature_k: float
    aging_state: str
    tier: str
    seed: int
    status: str = "pending"  # pending, submitted, duplicate, error, blocked
    error: str | None = None
    # v00.95.02: priority and similarity tracking
    priority: str = "medium"  # highest, high, medium, low, lowest
    similar_existing: bool = False
    similar_experiment_ids: list[str] = field(default_factory=list)


@dataclass
class AdditiveBatchJobBinderCellJob(BatchJobBinderCellJob):
    """A batch Binder Cell job with additive metadata (Phase 5.1).

    Attributes:
        additive_type: Additive type name (None = control group).
        additive_concentration: Additive wt% (0.0 = control group).
        additive_mol_id: Molecule ID for the additive (if applicable).
    """

    additive_type: str | None = None
    additive_concentration: float = 0.0
    additive_mol_id: str | None = None


@dataclass
class BatchJobBinderCellResult:
    """Result of a batch Binder Cell validate/submit operation."""

    batch_job_id: str
    jobs: list[BatchJobBinderCellJob] = field(default_factory=list)
    total: int = 0
    new: int = 0
    duplicates: int = 0
    submitted: int = 0
    errors: int = 0
    # v00.95.02: queue limits and similarity tracking
    blocked: int = 0
    requires_similarity_decision: bool = False
    similar_job_count: int = 0
    # v00.95.27: user-excluded jobs
    excluded: int = 0


@dataclass
class BatchJobBinderCellSpec:
    """Specification for a batch Binder Cell job.

    Args:
        binder_types: Binder types to simulate (e.g. ["AAA1", "AAK1", "AAM1"])
        structure_sizes: Structure sizes (e.g. ["X1"])
        temperatures_k: Temperatures in Kelvin
        aging_states: Aging states (e.g. ["non_aging"])
        tier: Run tier for all jobs
        ff_type: Force field type
        seed: Random seed
        temperature_priority: Priority temperatures submitted first
        additive_types: Additive type names for DOE (Phase 5.1, empty = no additive axis)
        additive_concentrations: Additive wt% values for DOE (Phase 5.1)
        initial_density: Optional initial packing density (g/cm3) for Packmol
        stage_duration_overrides: Optional stage duration overrides
        property_calculations: Optional property calculation settings
        equilibration_settings: Optional high-temperature/high-pressure equilibration settings
        similar_existing_action: Action when similar experiments exist (v00.95.02)
    """

    binder_types: list[str]
    structure_sizes: list[str] = field(default_factory=lambda: ["X1"])
    temperatures_k: list[float] = field(
        default_factory=lambda: list(
            __import__(
                "contracts.policies.temperature",
                fromlist=["DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K"],
            ).DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K
        )
    )
    aging_states: list[str] = field(default_factory=lambda: ["non_aging"])
    tier: str = "screening"
    ff_type: str = "bulk_ff_gaff2"
    e_intra_method: str | None = None
    e_intra_method_source: str | None = None
    seed: int = field(default_factory=generate_seed)
    seeds: list[int] = field(default_factory=list)
    temperature_priority: list[float] = field(
        default_factory=lambda: list(
            __import__(
                "contracts.policies.temperature", fromlist=["DEFAULT_TEMPERATURE_PRIORITY_K"]
            ).DEFAULT_TEMPERATURE_PRIORITY_K
        )
    )
    # Phase 5.1: additive DOE axes (empty = existing behavior)
    additive_types: list[str] = field(default_factory=list)
    additive_concentrations: list[float] = field(default_factory=list)
    additive_catalog_map: dict[str, dict] = field(default_factory=dict)
    initial_density: float | None = None
    stage_duration_overrides: list[StageDurationOverride] | None = None
    stage_requests: list[dict] = field(default_factory=list)
    property_calculations: dict | None = None
    equilibration_settings: dict | None = None
    # v00.95.02: similar experiment handling
    similar_existing_action: str = "unspecified"  # unspecified, keep_priority, demote_priority
    # v00.95.27: user-excluded exp_ids
    excluded_exp_ids: list[str] = field(default_factory=list)
    # v01.02.17: E_inter 정밀 분석 설정 (CPU rerun)
    interaction_analysis: dict | None = None


class BatchJobBinderCellRunner:
    """Generate and submit batch Binder Cell runs.

    Args:
        experiment_repo: ExperimentRepository for duplicate checking
        molecule_db: Optional MoleculeDB for composition lookup
        config_path: Path to asphalt_binder.yaml
        job_manager: CeleryJobManager for job submission (required for submit())
    """

    def __init__(
        self,
        experiment_repo: ExperimentRepository,
        molecule_db: MoleculeDB | None = None,
        config_path: Path | None = None,
        job_manager: CeleryJobManager | None = None,
    ) -> None:
        """Initialize batch job runner.

        Args:
            experiment_repo: Repository for experiment persistence.
            molecule_db: Pre-initialized MoleculeDB (optional, for testing).
            config_path: Deprecated. This parameter is ignored since v00.96.35.
                         The loader now always uses the project default molecule
                         catalog (combined: binder + single + additives).
            job_manager: CeleryJobManager for job submission.
        """
        self.experiment_repo = experiment_repo
        self.molecule_db = molecule_db
        self._config: dict | None = None
        self.job_manager = job_manager

        # Preserve config_path attribute for backward compatibility (deprecated but kept)
        self.config_path = config_path or Path("data/molecules/asphalt_binder.yaml")

        # Warn if config_path is explicitly provided (deprecated parameter)
        if config_path is not None:
            logger.warning(
                "config_path parameter is deprecated and ignored since v00.96.35. "
                "The loader now always uses project default molecule catalog. "
                "Passed config_path=%s will be ignored.",
                config_path,
            )

    def _get_molecule_db(self) -> MoleculeDB:
        """Lazy-load MoleculeDB with combined config (binder + single + additives)."""
        if self.molecule_db is not None:
            return self.molecule_db
        from builder.molecule_db_loader import create_molecule_db

        self.molecule_db = create_molecule_db(allow_mock=False)
        return self.molecule_db

    def _get_config(self) -> dict:
        """Lazy-load combined molecule library config."""
        if self._config is not None:
            return self._config
        from builder.molecule_db_loader import load_combined_molecule_config_strict

        self._config = load_combined_molecule_config_strict()
        return self._config

    def _generate_batch_job_id(self, spec: BatchJobBinderCellSpec) -> str:
        """Generate a unique batch job ID."""
        binders = "_".join(sorted(spec.binder_types))
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"batch_job_binder_cell_{binders}_{spec.tier}_{ts}"

    def _get_seed_list(self, spec: BatchJobBinderCellSpec) -> list[int]:
        """Get effective seed list from spec.

        Uses spec.seeds when provided (including a single seed),
        otherwise falls back to single spec.seed for backward compatibility.

        Args:
            spec: Batch job specification

        Returns:
            List of seeds to iterate over
        """
        if len(spec.seeds) > 0:
            return spec.seeds
        return [spec.seed]

    def _generate_jobs(self, spec: BatchJobBinderCellSpec) -> list[BatchJobBinderCellJob]:
        """Generate all jobs from spec, sorted by temperature priority."""
        target_atoms = DEFAULT_TIER_POLICY.get_target_atoms(spec.tier)
        seed_list = self._get_seed_list(spec)
        jobs: list[BatchJobBinderCellJob] = []

        for binder in spec.binder_types:
            for size in spec.structure_sizes:
                for aging in spec.aging_states:
                    for temp in spec.temperatures_k:
                        for seed in seed_list:
                            exp_id = generate_exp_id(
                                binder_type=binder,
                                structure_size=size,
                                temperature_k=temp,
                                ff_type=spec.ff_type,
                                aging_state=aging,
                                atom_count=target_atoms,
                                seed=seed,
                            )
                            jobs.append(
                                BatchJobBinderCellJob(
                                    exp_id=exp_id,
                                    binder_type=binder,
                                    structure_size=size,
                                    temperature_k=temp,
                                    aging_state=aging,
                                    tier=spec.tier,
                                    seed=seed,
                                )
                            )

        # Sort: priority temperatures first, then ascending
        priority_set = set(spec.temperature_priority)
        jobs.sort(
            key=lambda j: (
                0 if j.temperature_k in priority_set else 1,
                j.temperature_k,
                j.binder_type,
            )
        )
        return jobs

    def validate(self, spec: BatchJobBinderCellSpec) -> BatchJobBinderCellResult:
        """Dry-run: generate jobs and check for duplicates without submitting.

        Args:
            spec: Batch job specification

        Returns:
            BatchJobBinderCellResult with job statuses (no submissions)
        """
        from contracts.policies.budget import (
            DEFAULT_DUPLICATE_DETECTION_POLICY,
            DEFAULT_JOB_BUDGETING_POLICY,
        )
        from features.experiments.query import find_similar_experiments

        batch_job_id = self._generate_batch_job_id(spec)
        jobs = self._generate_jobs(spec)
        session = self.experiment_repo.session

        result = BatchJobBinderCellResult(batch_job_id=batch_job_id, jobs=jobs, total=len(jobs))

        # Set default priority from tier
        default_priority = DEFAULT_JOB_BUDGETING_POLICY.get_priority(spec.tier)

        for job in jobs:
            # Set default priority
            job.priority = default_priority.value

            # Check for exact duplicate
            existing = self.experiment_repo.get_by_id(job.exp_id)
            if existing is not None:
                job.status = "duplicate"
                result.duplicates += 1
                continue

            # Check for similar experiments (completed only)
            add_type = getattr(job, "additive_type", None)
            add_conc = getattr(job, "additive_concentration", 0.0)
            add_mol_id = getattr(job, "additive_mol_id", None) or add_type

            similar = find_similar_experiments(
                session=session,
                binder_type=job.binder_type,
                aging_state=job.aging_state,
                additive_mol_id=add_mol_id,
                additive_wt=add_conc,
                temperature_k=job.temperature_k,
                temperature_tolerance=DEFAULT_DUPLICATE_DETECTION_POLICY.temperature_tolerance_k,
                limit=DEFAULT_DUPLICATE_DETECTION_POLICY.max_similarity_check_limit,
            )

            if similar:
                job.similar_existing = True
                job.similar_experiment_ids = [s.exp_id for s in similar]
                result.similar_job_count += 1

            result.new += 1

        # Determine if similarity decision is required
        result.requires_similarity_decision = result.similar_job_count > 0

        return result

    @staticmethod
    def _resolve_sara_wt(config: dict, db: MoleculeDB, binder_type: str) -> dict[str, float]:
        """Resolve binder SARA composition in wt% for experiment metadata."""
        sara = db.get_sara_fractions(config, binder_type) or {}
        asph = float(sara.get("asphaltene", 20.0) or 20.0)
        resin = float(sara.get("resin", 30.0) or 30.0)
        aromatic = float(sara.get("aromatic", 35.0) or 35.0)
        saturate = float(sara.get("saturate", 15.0) or 15.0)

        total = asph + resin + aromatic + saturate
        if 0.0 < total <= 1.01:
            asph *= 100.0
            resin *= 100.0
            aromatic *= 100.0
            saturate *= 100.0

        return {
            "asphaltene": asph,
            "resin": resin,
            "aromatic": aromatic,
            "saturate": saturate,
        }

    def submit(self, spec: BatchJobBinderCellSpec) -> BatchJobBinderCellResult:
        """Validate then submit new jobs via CeleryJobManager.

        Args:
            spec: Batch job specification

        Returns:
            BatchJobBinderCellResult with submission results

        Raises:
            RuntimeError: If job_manager is not provided
            ValueError: If similar jobs exist and action is unspecified
        """
        from contracts.errors import ContractError, ErrorCode
        from contracts.policies.budget import (
            DEFAULT_DUPLICATE_DETECTION_POLICY,
            DEFAULT_QUEUE_LIMITS_POLICY,
            JobPriority,
            SimilarExistingAction,
            demote_priority,
        )

        if self.job_manager is None:
            raise RuntimeError(
                "BatchJobBinderCellRunner.submit() requires a job_manager. "
                "Pass job_manager= to the constructor."
            )

        result = self.validate(spec)
        db = self._get_molecule_db()
        config = self._get_config()

        # Apply user exclusions BEFORE similarity gating
        excluded_set = set(spec.excluded_exp_ids)
        for job in result.jobs:
            if job.exp_id in excluded_set and job.status != "duplicate":
                job.status = "excluded"
                result.excluded += 1
                # Adjust new count since excluded jobs were counted as new in validate()
                if result.new > 0:
                    result.new -= 1

        # Recompute effective similar count after exclusions
        effective_similar = sum(
            1
            for j in result.jobs
            if j.similar_existing and j.status not in ("duplicate", "excluded")
        )

        # Check if similarity decision is required but not provided
        action = SimilarExistingAction(spec.similar_existing_action)
        if effective_similar > 0 and action == SimilarExistingAction.UNSPECIFIED:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Similar experiments exist for {effective_similar} job(s). "
                "Set similar_existing_action to 'keep_priority' or 'demote_priority'.",
                {"similar_job_count": effective_similar},
            )

        # Apply priority demotion if requested
        demotion_steps = DEFAULT_DUPLICATE_DETECTION_POLICY.similar_experiment_priority_demotion
        submitted_count = 0
        chunk_size = DEFAULT_QUEUE_LIMITS_POLICY.batch_submission_chunk_size

        for job in result.jobs:
            if job.status in ("duplicate", "excluded"):
                continue

            # Check queue limit
            if submitted_count >= chunk_size:
                job.status = "blocked"
                result.blocked += 1
                continue

            # Apply priority demotion for similar jobs
            if job.similar_existing and action == SimilarExistingAction.DEMOTE_PRIORITY:
                try:
                    original_priority = JobPriority(job.priority)
                    job.priority = demote_priority(original_priority, demotion_steps).value
                except ValueError:
                    job.priority = JobPriority.LOWEST.value

            try:
                # Get molecule counts from YAML (SSOT)
                temp_code = db.get_temperature_code(config, job.temperature_k)
                mol_counts = db.get_binder_composition_with_aging(
                    config,
                    binder_type=job.binder_type,
                    size=job.structure_size,
                    aging=job.aging_state,
                    temp_code=temp_code,
                )

                material_id = f"{job.binder_type}_{job.structure_size}_{job.aging_state}"
                composition = {key: float(value) for key, value in mol_counts.items()}

                build_request = create_build_request(
                    composition=composition,
                    seed=job.seed,
                    tier=job.tier,
                    composition_mode="mol_count",
                    initial_density=spec.initial_density,
                )
                protocol_request = create_protocol_request(
                    tier=job.tier,
                    ff_type=spec.ff_type,
                    temperature_K=job.temperature_k,
                    e_intra_method=spec.e_intra_method,
                    equilibration_settings=spec.equilibration_settings,
                )
                base_meta = {
                    "source": SubmissionSource.BATCH_JOB_BINDER_CELL.value,
                    "binder_type": job.binder_type,
                    "structure_size": job.structure_size,
                    "aging_state": job.aging_state,
                    "similar_existing": job.similar_existing,
                    "similar_experiment_ids": job.similar_experiment_ids,
                    "e_intra_method": spec.e_intra_method,
                }
                if spec.e_intra_method:
                    base_meta["ced_provenance"] = {
                        "e_intra_method": spec.e_intra_method,
                        "e_intra_method_source": spec.e_intra_method_source,
                    }
                if spec.interaction_analysis:
                    base_meta["interaction_analysis"] = spec.interaction_analysis
                metadata = build_stage_plan_metadata(
                    protocol_request=protocol_request,
                    overrides=spec.stage_duration_overrides,
                    canonical_stage_requests=spec.stage_requests,
                    base_metadata=base_meta,
                )

                sara_wt = self._resolve_sara_wt(config, db, job.binder_type)
                SubmissionFacade.submit_experiment(
                    job_manager=self.job_manager,
                    exp_id=job.exp_id,
                    run_tier=job.tier,
                    ff_type=spec.ff_type,
                    target_atoms=DEFAULT_TIER_POLICY.get_target_atoms(job.tier),
                    temperature_k=job.temperature_k,
                    pressure_atm=1.0,
                    seed=job.seed,
                    comp_asphaltene_wt=sara_wt["asphaltene"],
                    comp_resin_wt=sara_wt["resin"],
                    comp_aromatic_wt=sara_wt["aromatic"],
                    comp_saturate_wt=sara_wt["saturate"],
                    build_request=build_request,
                    protocol_request=protocol_request,
                    material_id=material_id,
                    stage_duration_overrides=spec.stage_duration_overrides,
                    property_calculations=spec.property_calculations,
                    priority=JobPriority(job.priority),
                    metadata_json=metadata,
                )

                job.status = "submitted"
                result.submitted += 1
                submitted_count += 1
                logger.info(f"Batch job submitted: {job.exp_id} (priority={job.priority})")

            except Exception as e:
                job.status = "error"
                job.error = str(e)
                result.errors += 1
                logger.error(f"Batch job failed: {job.exp_id} - {e}")

        logger.info(
            f"Batch job {result.batch_job_id}: "
            f"{result.submitted} submitted, {result.duplicates} duplicates, "
            f"{result.excluded} excluded, {result.blocked} blocked, "
            f"{result.errors} errors (total={result.total})"
        )
        return result


# =============================================================================
# Phase 5.1: Additive DOE for Batch Job Binder Cell
# =============================================================================


class AdditiveBatchJobBinderCellRunner(BatchJobBinderCellRunner):
    """Batch job runner extended with additive DOE axes.

    Generates full-factorial combinations of (additive_type x concentration),
    always including a control group (None, 0.0).

    When BatchJobBinderCellSpec.additive_types is empty, falls back to base behavior.
    """

    def _generate_additive_combos(
        self, spec: BatchJobBinderCellSpec
    ) -> list[tuple[str | None, float]]:
        """Generate additive (type, concentration) combinations.

        Always includes control group (None, 0.0).
        Full-factorial: every type x every concentration.
        Deterministic ordering: sorted by (type, conc).

        Args:
            spec: Batch job specification with additive_types / concentrations.

        Returns:
            Sorted, deduplicated list of (additive_type, concentration) tuples.
        """
        combos: set[tuple[str | None, float]] = set()
        real_types = [t for t in spec.additive_types if t != "none"]

        if "none" in spec.additive_types or not real_types:
            combos.add((None, 0.0))

        # Check if this is binder cell mode (1:1 mapping) or DOE mode (cross product)
        # Binder cell mode: additive_types and additive_concentrations have same length
        # and each type maps to its corresponding concentration
        if len(real_types) == len(spec.additive_concentrations) and len(real_types) > 0:
            # Binder cell mode: 1:1 mapping (each additive has its own fixed concentration)
            for atype, conc in zip(real_types, spec.additive_concentrations, strict=False):
                combos.add((atype, conc))
        else:
            # DOE mode: cross product of all types × all concentrations
            for atype in real_types:
                for conc in spec.additive_concentrations:
                    combos.add((atype, conc))

        # Deterministic sort: None first (control), then alphabetical type, then conc
        return sorted(combos, key=lambda c: (c[0] or "", c[1]))

    def _inject_additive_into_composition(
        self,
        base_composition: dict[str, float],
        additive_type: str | None,
        additive_concentration: float,
        config: dict,
        structure_size: str,
        additive_catalog_map: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        """Inject additive effect into mol_count composition.

        Control groups are returned unchanged.
        Treatment groups scale down base molecule counts by (1 - wt%)
        and optionally add additive molecule count when the additive
        molecule id is available in MoleculeDB.
        """
        if additive_type is None or additive_concentration <= 0.0:
            return dict(base_composition)

        max_additive_wt = DEFAULT_COMPOSITION_CONSTRAINTS.bounds.get("additive_total", (0.0, 10.0))[
            1
        ]
        if additive_concentration > max_additive_wt:
            raise ValueError(
                f"Additive concentration {additive_concentration} wt% exceeds policy maximum "
                f"{max_additive_wt} wt%"
            )

        additive_catalog_map = additive_catalog_map or {}
        additives_config = config.get("additives", {})

        if additive_catalog_map:
            if additive_type not in additive_catalog_map:
                raise ValueError(
                    f"Unknown additive type: {additive_type}. "
                    f"Available: {sorted(additive_catalog_map.keys())}"
                )
            additive_info = additive_catalog_map[additive_type]
        else:
            if additive_type not in additives_config:
                raise ValueError(
                    f"Unknown additive type: {additive_type}. "
                    f"Available: {sorted(additives_config.keys())}"
                )
            additive_info = additives_config[additive_type]

        scale_factor = 1.0 - (additive_concentration / 100.0)
        modified: dict[str, float] = {}
        for mol_id, count in base_composition.items():
            scaled = round(float(count) * scale_factor)
            if scaled > 0:
                modified[mol_id] = float(scaled)

        if not modified:
            raise ValueError(
                "Additive scaling removed all base molecules; reduce additive concentration"
            )

        # Add additive molecule only when MoleculeDB can resolve its structure.
        # Otherwise keep scaled composition and preserve additive as metadata.
        default_count = float(
            additive_info.get("default_counts", additive_info.get("counts", {})).get(
                structure_size, 2
            )
        )
        if default_count > 0 and self._get_molecule_db().has(additive_type):
            modified[additive_type] = default_count
        else:
            logger.warning(
                "Additive '%s' not found in MoleculeDB; applying scaled-base composition only",
                additive_type,
            )

        return modified

    def _generate_jobs(self, spec: BatchJobBinderCellSpec) -> list[BatchJobBinderCellJob]:
        """Generate all jobs including additive DOE axis.

        If additive_types is empty, delegates to base class.
        """
        if not spec.additive_types:
            return super()._generate_jobs(spec)

        target_atoms = DEFAULT_TIER_POLICY.get_target_atoms(spec.tier)
        seed_list = self._get_seed_list(spec)
        additive_combos = self._generate_additive_combos(spec)
        jobs: list[BatchJobBinderCellJob] = []

        for binder in spec.binder_types:
            for size in spec.structure_sizes:
                for aging in spec.aging_states:
                    for temp in spec.temperatures_k:
                        for add_type, add_conc in additive_combos:
                            for seed in seed_list:
                                exp_id = generate_exp_id(
                                    binder_type=binder,
                                    structure_size=size,
                                    temperature_k=temp,
                                    additive=add_type,
                                    ff_type=spec.ff_type,
                                    aging_state=aging,
                                    atom_count=target_atoms,
                                    seed=seed,
                                )
                                jobs.append(
                                    AdditiveBatchJobBinderCellJob(
                                        exp_id=exp_id,
                                        binder_type=binder,
                                        structure_size=size,
                                        temperature_k=temp,
                                        aging_state=aging,
                                        tier=spec.tier,
                                        seed=seed,
                                        additive_type=add_type,
                                        additive_concentration=add_conc,
                                        additive_mol_id=add_type,
                                    )
                                )

        # Sort: priority temperatures first, then ascending
        priority_set = set(spec.temperature_priority)
        jobs.sort(
            key=lambda j: (
                0 if j.temperature_k in priority_set else 1,
                j.temperature_k,
                j.binder_type,
            )
        )
        return jobs

    def submit(self, spec: BatchJobBinderCellSpec) -> BatchJobBinderCellResult:
        """Submit additive DOE batch Binder Cell jobs.

        Modifies base SARA composition to incorporate additive wt%.
        Propagates additive metadata through the full chain (FIX-1).

        Args:
            spec: Batch job specification with additive DOE axes.

        Returns:
            BatchJobBinderCellResult with submission results.

        Raises:
            RuntimeError: If job_manager is not provided
            ValueError: If similar jobs exist and action is unspecified
        """
        from contracts.errors import ContractError, ErrorCode
        from contracts.policies.budget import (
            DEFAULT_DUPLICATE_DETECTION_POLICY,
            DEFAULT_QUEUE_LIMITS_POLICY,
            JobPriority,
            SimilarExistingAction,
            demote_priority,
        )

        if self.job_manager is None:
            raise RuntimeError(
                "AdditiveBatchJobBinderCellRunner.submit() requires a job_manager. "
                "Pass job_manager= to the constructor."
            )

        # If no additive axis, delegate to base submit
        if not spec.additive_types:
            return super().submit(spec)

        result = self.validate(spec)
        db = self._get_molecule_db()
        config = self._get_config()

        # Apply user exclusions BEFORE similarity gating
        excluded_set = set(spec.excluded_exp_ids)
        for job in result.jobs:
            if job.exp_id in excluded_set and job.status != "duplicate":
                job.status = "excluded"
                result.excluded += 1
                # Adjust new count since excluded jobs were counted as new in validate()
                if result.new > 0:
                    result.new -= 1

        # Recompute effective similar count after exclusions
        effective_similar = sum(
            1
            for j in result.jobs
            if j.similar_existing and j.status not in ("duplicate", "excluded")
        )

        # Check if similarity decision is required but not provided
        action = SimilarExistingAction(spec.similar_existing_action)
        if effective_similar > 0 and action == SimilarExistingAction.UNSPECIFIED:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Similar experiments exist for {effective_similar} job(s). "
                "Set similar_existing_action to 'keep_priority' or 'demote_priority'.",
                {"similar_job_count": effective_similar},
            )

        # Apply priority demotion if requested
        demotion_steps = DEFAULT_DUPLICATE_DETECTION_POLICY.similar_experiment_priority_demotion
        submitted_count = 0
        chunk_size = DEFAULT_QUEUE_LIMITS_POLICY.batch_submission_chunk_size

        for job in result.jobs:
            if job.status in ("duplicate", "excluded"):
                continue

            # Check queue limit
            if submitted_count >= chunk_size:
                job.status = "blocked"
                result.blocked += 1
                continue

            # Apply priority demotion for similar jobs
            if job.similar_existing and action == SimilarExistingAction.DEMOTE_PRIORITY:
                try:
                    original_priority = JobPriority(job.priority)
                    job.priority = demote_priority(original_priority, demotion_steps).value
                except ValueError:
                    job.priority = JobPriority.LOWEST.value

            try:
                # Get base molecule counts from YAML (SSOT)
                temp_code = db.get_temperature_code(config, job.temperature_k)
                mol_counts = db.get_binder_composition_with_aging(
                    config,
                    binder_type=job.binder_type,
                    size=job.structure_size,
                    aging=job.aging_state,
                    temp_code=temp_code,
                )

                material_id = f"{job.binder_type}_{job.structure_size}_{job.aging_state}"
                composition = {key: float(value) for key, value in mol_counts.items()}

                # Extract additive metadata from AdditiveBatchJobBinderCellJob
                add_type: str | None = None
                add_conc: float = 0.0
                add_mol_id: str | None = None
                if isinstance(job, AdditiveBatchJobBinderCellJob):
                    add_type = job.additive_type
                    add_conc = job.additive_concentration
                    add_mol_id = job.additive_mol_id
                    if add_mol_id is None and add_type is not None:
                        add_mol_id = add_type

                composition = self._inject_additive_into_composition(
                    base_composition=composition,
                    additive_type=add_type,
                    additive_concentration=add_conc,
                    config=config,
                    structure_size=job.structure_size,
                    additive_catalog_map=spec.additive_catalog_map,
                )

                build_request = create_build_request(
                    composition=composition,
                    seed=job.seed,
                    tier=job.tier,
                    composition_mode="mol_count",
                    initial_density=spec.initial_density,
                )
                protocol_request = create_protocol_request(
                    tier=job.tier,
                    ff_type=spec.ff_type,
                    temperature_K=job.temperature_k,
                    e_intra_method=spec.e_intra_method,
                    equilibration_settings=spec.equilibration_settings,
                )
                base_meta_add = {
                    "source": SubmissionSource.BATCH_JOB_BINDER_CELL_ADDITIVE.value,
                    "binder_type": job.binder_type,
                    "structure_size": job.structure_size,
                    "aging_state": job.aging_state,
                    "similar_existing": job.similar_existing,
                    "similar_experiment_ids": job.similar_experiment_ids,
                    "e_intra_method": spec.e_intra_method,
                }
                if spec.e_intra_method:
                    base_meta_add["ced_provenance"] = {
                        "e_intra_method": spec.e_intra_method,
                        "e_intra_method_source": spec.e_intra_method_source,
                    }
                if spec.interaction_analysis:
                    base_meta_add["interaction_analysis"] = spec.interaction_analysis
                metadata = build_stage_plan_metadata(
                    protocol_request=protocol_request,
                    overrides=spec.stage_duration_overrides,
                    canonical_stage_requests=spec.stage_requests,
                    base_metadata=base_meta_add,
                )

                sara_wt = self._resolve_sara_wt(config, db, job.binder_type)
                SubmissionFacade.submit_experiment(
                    job_manager=self.job_manager,
                    exp_id=job.exp_id,
                    run_tier=job.tier,
                    ff_type=spec.ff_type,
                    target_atoms=DEFAULT_TIER_POLICY.get_target_atoms(job.tier),
                    temperature_k=job.temperature_k,
                    pressure_atm=1.0,
                    seed=job.seed,
                    comp_asphaltene_wt=sara_wt["asphaltene"],
                    comp_resin_wt=sara_wt["resin"],
                    comp_aromatic_wt=sara_wt["aromatic"],
                    comp_saturate_wt=sara_wt["saturate"],
                    build_request=build_request,
                    protocol_request=protocol_request,
                    material_id=material_id,
                    stage_duration_overrides=spec.stage_duration_overrides,
                    property_calculations=spec.property_calculations,
                    additive_type=add_type,
                    additive_wt=add_conc,
                    additive_mol_id=add_mol_id,
                    priority=JobPriority(job.priority),
                    metadata_json=metadata,
                )

                job.status = "submitted"
                result.submitted += 1
                submitted_count += 1
                logger.info(
                    f"Batch job submitted: {job.exp_id} (additive={add_type}, conc={add_conc}, priority={job.priority})"
                )

            except Exception as e:
                job.status = "error"
                job.error = str(e)
                result.errors += 1
                logger.error(f"Batch job failed: {job.exp_id} - {e}")

        logger.info(
            f"Additive batch job {result.batch_job_id}: "
            f"{result.submitted} submitted, {result.duplicates} duplicates, "
            f"{result.excluded} excluded, {result.blocked} blocked, "
            f"{result.errors} errors (total={result.total})"
        )
        return result


def select_batch_runner_cls(spec: BatchJobBinderCellSpec) -> type[BatchJobBinderCellRunner]:
    """Select the batch runner class for a spec.

    Single source of truth for the additive-vs-base runner choice that was
    previously duplicated across the batch service (validate + submit) and
    the campaign service. Resolving the class names here (module globals)
    keeps existing ``patch("orchestrator.batch_job_binder_cell.<Runner>")``
    test seams working.

    Args:
        spec: The batch job spec; presence of ``additive_types`` selects the
            additive DOE runner.

    Returns:
        ``AdditiveBatchJobBinderCellRunner`` when the spec carries additive
        axes, else ``BatchJobBinderCellRunner``.
    """
    return AdditiveBatchJobBinderCellRunner if spec.additive_types else BatchJobBinderCellRunner
