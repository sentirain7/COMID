"""Dependency scheduler for parent->child experiment chains."""

from __future__ import annotations

from common.logging import get_logger
from contracts.errors import ErrorCode, OrchestrationError
from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY
from contracts.policies.dependency import DEFAULT_DEPENDENCY_POLICY
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import BuildRequest, ProtocolRequest
from database.connection import session_scope
from database.repositories.experiment_repo import ExperimentRepository
from database.repositories.job_dependency_repo import JobDependencyRepository

logger = get_logger("orchestrator.dependency_scheduler")


class DependencyScheduler:
    """Promote blocked dependency edges to ready when prerequisites are met."""

    def __init__(self, job_manager):
        self.job_manager = job_manager
        self.dependency_policy = DEFAULT_DEPENDENCY_POLICY
        self.budget_policy = DEFAULT_JOB_BUDGETING_POLICY

    @staticmethod
    def _reason(code: str, detail: str | None = None) -> str:
        token = str(code or "").strip().upper()
        if detail is None or str(detail).strip() == "":
            return token
        return f"{token}:{detail}"

    def reconcile_parent(self, parent_exp_id: str) -> dict[str, int]:
        """Reconcile dependents for a parent and update dependency edge status."""
        with session_scope() as session:
            exp_repo = ExperimentRepository(session)
            dep_repo = JobDependencyRepository(session)

            parent = exp_repo.get_by_id(parent_exp_id)
            if parent is None:
                raise OrchestrationError(
                    ErrorCode.DEPENDENCY_BROKEN,
                    "Parent experiment not found for dependency reconciliation",
                    {"parent_exp_id": parent_exp_id},
                )

            parent_status = str(parent.status or "").lower()
            dependents = dep_repo.list_dependents(parent_exp_id)
            db_counts = exp_repo.count_by_status()
            running_count = int(db_counts.get("running", 0))
            queued_count = int(db_counts.get("pending", 0)) + int(db_counts.get("queued", 0))

            ready = 0
            blocked = 0
            failed = 0

            for edge in dependents:
                child_exp_id = str(edge.get("child_exp_id", ""))
                if not child_exp_id:
                    continue

                if parent_status in self.dependency_policy.blocked_parent_states:
                    dep_repo.update_status(
                        parent_exp_id,
                        child_exp_id,
                        status="failed",
                        reason=self._reason("UPSTREAM_BLOCKED", parent_status),
                    )
                    failed += 1
                    continue

                if parent_status not in self.dependency_policy.allowed_parent_terminal_states:
                    dep_repo.update_status(
                        parent_exp_id,
                        child_exp_id,
                        status="blocked",
                        reason=self._reason("UPSTREAM_NOT_READY", parent_status),
                    )
                    blocked += 1
                    continue

                child = exp_repo.get_by_id(child_exp_id)
                if child is None:
                    dep_repo.update_status(
                        parent_exp_id,
                        child_exp_id,
                        status="failed",
                        reason=self._reason("CHILD_MISSING"),
                    )
                    failed += 1
                    continue

                can_submit, reason = self._check_budget(
                    child.run_tier,
                    child.target_atoms,
                    running_count=running_count,
                    queued_count=queued_count,
                )
                if can_submit:
                    dep_repo.update_status(parent_exp_id, child_exp_id, status="ready")
                    ready += 1
                else:
                    dep_repo.update_status(
                        parent_exp_id,
                        child_exp_id,
                        status="blocked",
                        reason=self._reason("BUDGET_BLOCKED", str(reason or "unknown")),
                    )
                    blocked += 1

            logger.info(
                "Dependency reconcile parent=%s ready=%d blocked=%d failed=%d",
                parent_exp_id,
                ready,
                blocked,
                failed,
            )
            return {"ready": ready, "blocked": blocked, "failed": failed}

    def reconcile_all(self, limit_parents: int = 500) -> dict[str, int]:
        """Reconcile all parents that still have blocked/ready edges."""
        with session_scope() as session:
            dep_repo = JobDependencyRepository(session)
            parents = dep_repo.list_parents_with_active_edges(limit=limit_parents)

        total_ready = 0
        total_blocked = 0
        total_failed = 0
        for parent_exp_id in parents:
            try:
                result = self.reconcile_parent(parent_exp_id)
                total_ready += int(result.get("ready", 0))
                total_blocked += int(result.get("blocked", 0))
                total_failed += int(result.get("failed", 0))
            except Exception as exc:
                logger.warning("Dependency reconcile failed for parent=%s: %s", parent_exp_id, exc)

        return {
            "parents": len(parents),
            "ready": total_ready,
            "blocked": total_blocked,
            "failed": total_failed,
        }

    def submit_ready(self, max_submissions: int = 10) -> dict[str, int]:
        """Submit child experiments whose dependency edges are READY."""
        submitted = 0
        blocked = 0
        failed = 0

        with session_scope() as session:
            dep_repo = JobDependencyRepository(session)
            exp_repo = ExperimentRepository(session)
            ready_edges = dep_repo.list_by_status("ready", limit=max_submissions)
            # Track children already processed in this batch to prevent
            # duplicate submissions when a child has multiple ready edges.
            processed_children: set[str] = set()

            for edge in ready_edges:
                # Skip if we already processed this child in this batch
                if edge.child_exp_id in processed_children:
                    continue

                child = exp_repo.get_by_id(edge.child_exp_id)
                if child is None:
                    dep_repo.update_status(
                        edge.parent_exp_id,
                        edge.child_exp_id,
                        status="failed",
                        reason=self._reason("CHILD_MISSING"),
                    )
                    failed += 1
                    continue

                if str(child.status or "").lower() in {
                    "queued",
                    "running",
                    "building",
                    "analyzing",
                    "completed",
                }:
                    dep_repo.update_status(
                        edge.parent_exp_id,
                        edge.child_exp_id,
                        status="submitted",
                        reason=self._reason("ALREADY_ACTIVE_OR_DONE"),
                    )
                    submitted += 1
                    continue

                payload = dict(child.metadata_json or {}).get("deferred_submission")
                if not isinstance(payload, dict):
                    dep_repo.update_status(
                        edge.parent_exp_id,
                        edge.child_exp_id,
                        status="blocked",
                        reason=self._reason("MISSING_DEFERRED_PAYLOAD"),
                    )
                    blocked += 1
                    continue

                try:
                    kind = payload.get("kind", "molecule")

                    if kind == "layered":
                        # Check if ALL dependency edges for this child are ready.
                        # Only proceed when every prerequisite has completed.
                        from database.models.experiment import JobDependencyModel

                        all_edges = (
                            session.query(JobDependencyModel)
                            .filter(JobDependencyModel.child_exp_id == edge.child_exp_id)
                            .all()
                        )
                        if not all(
                            str(getattr(e, "status", "")) in ("ready", "submitted")
                            for e in all_edges
                        ):
                            # Not all prerequisites ready yet — skip for now
                            continue

                        # Layered deferred submission — delegate to layered service.
                        # Returns the real layered exp_id (not the placeholder).
                        real_exp_id = self._submit_layered_deferred(
                            child, payload, session, parent_exp_id=edge.parent_exp_id
                        )
                        # Store real exp_id in placeholder metadata so BA
                        # orchestrator can follow the indirection.
                        # Mark placeholder as "cancelled" (not "queued") so it
                        # is excluded from budget calculations and active-job
                        # counts. "cancelled" is a valid transition from
                        # "pending" per SSOT state_machine policy.
                        # The real layered experiment has its own row.
                        meta = dict(child.metadata_json or {})
                        meta["real_layered_exp_id"] = real_exp_id
                        child.metadata_json = meta
                        exp_repo.update_status(child.exp_id, "cancelled")

                        # Propagate provenance metadata blocks to the real
                        # layered experiment so provenance tracking, generic
                        # stack exact-match lookup, and pipeline progress
                        # aggregation work correctly.
                        propagated = {
                            key: meta[key]
                            for key in ("binder_analysis", "pipeline")
                            if meta.get(key)
                        }
                        if isinstance(propagated.get("pipeline"), dict):
                            propagated["pipeline"] = {
                                **propagated["pipeline"],
                                "role": "layered",
                            }
                        if propagated and real_exp_id:
                            real_exp = exp_repo.get_by_id(real_exp_id)
                            if real_exp is not None:
                                real_meta = dict(real_exp.metadata_json or {})
                                real_meta.update(propagated)
                                real_exp.metadata_json = real_meta
                        # Mark ALL edges for this child as submitted
                        for e in all_edges:
                            dep_repo.update_status(
                                e.parent_exp_id,
                                e.child_exp_id,
                                status="submitted",
                            )
                        processed_children.add(edge.child_exp_id)
                        submitted += 1
                        continue
                    else:
                        # Default molecule deferred submission
                        build_request = BuildRequest.model_validate(
                            payload.get("build_request", {})
                        )
                        protocol_request = ProtocolRequest.model_validate(
                            payload.get("protocol_request", {})
                        )
                        material_id = str(payload.get("material_id") or "dependency_child")

                        job_id = self.job_manager.submit(
                            build_request=build_request,
                            protocol_request=protocol_request,
                            material_id=material_id,
                            selected_gpus=payload.get("selected_gpus"),
                            stage_duration_overrides=payload.get("stage_duration_overrides"),
                            property_calculations=payload.get("property_calculations"),
                            exp_id=child.exp_id,
                            additive_type=payload.get("additive_type"),
                            additive_wt=float(payload.get("additive_wt") or 0.0),
                            additive_mol_id=payload.get("additive_mol_id"),
                        )
                    task_id = self.job_manager.get_task_id(job_id)
                    if not task_id:
                        raise ValueError(f"Missing task_id after submit for job_id={job_id}")

                    exp_repo.update_celery_task_id(child.exp_id, task_id)
                    exp_repo.update_status(child.exp_id, "queued")
                    dep_repo.update_status(
                        edge.parent_exp_id,
                        edge.child_exp_id,
                        status="submitted",
                    )
                    processed_children.add(edge.child_exp_id)
                    submitted += 1
                except Exception as exc:
                    dep_repo.update_status(
                        edge.parent_exp_id,
                        edge.child_exp_id,
                        status="blocked",
                        reason=self._reason("SUBMIT_FAILED", str(exc)),
                    )
                    blocked += 1

            session.commit()

        return {"submitted": submitted, "blocked": blocked, "failed": failed}

    def _submit_layered_deferred(
        self,
        child: object,
        payload: dict,
        session: object,
        parent_exp_id: str,
    ) -> str:
        """Submit a deferred layered structure experiment.

        Called by submit_ready() when payload.kind == "layered".
        Resolves __parent_exp_id__ placeholders with the actual parent exp_id,
        then delegates to features.layered_structures.service.
        Returns the **real** layered exp_id (not the placeholder).
        """
        import asyncio

        from api.schemas.structures import (
            LayeredStructureSubmitRequest,
            LayerStackItemRequest,
        )
        from contracts.schemas import LayerSourceType
        from features.common.source_compat import normalize_source_type

        layer_dicts = payload.get("layers", [])
        layers: list[LayerStackItemRequest] = []
        water_slots: list[tuple[int, dict]] = []  # (layers index, auto_water spec)
        for ld in layer_dicts:
            source_id = ld.get("source_id")
            # Resolve per-layer prerequisite: each unresolved binder layer
            # stores its own prereq_exp_id (set by layer_executor.submit_deferred)
            prereq_id = ld.get("prereq_exp_id")
            if source_id is None and prereq_id:
                source_id = prereq_id
            is_water_auto = source_id is None and isinstance(ld.get("auto_water"), dict)
            if is_water_auto:
                # water 층 자동 프로비저닝(P6): parent binder 완료 후에야
                # box 크기를 알 수 있어 제출 시점에 cell을 생성/재사용한다.
                water_slots.append((len(layers), dict(ld["auto_water"])))
            layers.append(
                LayerStackItemRequest(
                    source_type=LayerSourceType(normalize_source_type(ld["source_type"])),
                    source_id="__pending_water__" if is_water_auto else source_id,
                    auto_match_material=ld.get("auto_match_material"),
                    label=ld.get("label"),
                    gap_after_angstrom=ld.get("gap_after_angstrom"),
                )
            )

        replicate_seeds = payload.get("replicate_seeds") or None

        # replicate_seeds 2개 이상이면 replica 오케스트레이션 진입점으로 위임 —
        # deferred 경로에서도 계면 지표 mean±SE ensemble 자동 집계(v01.05.27)가
        # 동작한다. 미지정/1개면 기존 단일 제출과 byte-identical.
        from features.layered_structures.service import (
            submit_layered_replicates,
            submit_layered_structure,
        )

        submit_fn = (
            submit_layered_replicates
            if replicate_seeds and len(replicate_seeds) >= 2
            else submit_layered_structure
        )

        parent_box = self._parent_box_xy(session, parent_exp_id)

        async def _provision_and_submit():
            if water_slots:
                # water spec fallback은 inverse_pipeline 정책 SSOT (R-P1-5) —
                # auto_water 마커는 그 정책에서 생성되므로 drift를 막는다.
                from contracts.policies.inverse_pipeline import (
                    DEFAULT_INVERSE_PIPELINE_POLICY,
                )
                from features.layered_structures.water_provisioning import (
                    ensure_water_interface_cell,
                )

                moisture = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
                for idx, spec in water_slots:
                    fallback = float(
                        spec.get("default_xy_angstrom", moisture.water_default_xy_angstrom)
                    )
                    lx = parent_box[0] or fallback
                    ly = parent_box[1] or fallback
                    cell_id = await ensure_water_interface_cell(
                        lx,
                        ly,
                        mol_id=str(spec.get("mol_id", moisture.water_mol_id)),
                        thickness_angstrom=float(
                            spec.get("thickness_angstrom", moisture.water_layer_thickness_angstrom)
                        ),
                        target_density=float(
                            spec.get("target_density", moisture.water_target_density)
                        ),
                    )
                    layers[idx] = layers[idx].model_copy(update={"source_id": cell_id})
            # 부재 키는 LayeredStructureSubmitRequest 스키마 기본값(SSOT)에
            # 위임 — fallback literal 이원화를 피한다 (R-P1-5).
            request_kwargs = {
                key: payload[key]
                for key in ("name", "run_tier", "ff_type", "temperature_K", "tensile_enabled")
                if payload.get(key) is not None
            }
            request = LayeredStructureSubmitRequest(
                layers=layers,
                replicate_seeds=[int(s) for s in replicate_seeds] if replicate_seeds else None,
                **request_kwargs,
            )
            return await submit_fn(request)

        # Run async submission in sync context. Python 3.12+에서
        # get_event_loop()는 루프 부재 시 RuntimeError → get_running_loop 패턴.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _provision_and_submit()).result()
        else:
            result = asyncio.run(_provision_and_submit())

        return result.exp_id

    @staticmethod
    def _parent_box_xy(session, parent_exp_id: str) -> tuple[float | None, float | None]:
        """parent binder 실험의 최종 box XY (water 층 크기 정합용)."""
        try:
            from database.models import ExperimentModel

            exp = (
                session.query(ExperimentModel).filter_by(exp_id=parent_exp_id).first()
                if session is not None
                else None
            )
            if exp is None:
                return None, None
            lx = float(exp.box_lx) if exp.box_lx else None
            ly = float(exp.box_ly) if exp.box_ly else None
            return lx, ly
        except Exception:
            return None, None

    def _check_budget(
        self,
        run_tier: str | None,
        target_atoms: int | None,
        *,
        running_count: int,
        queued_count: int,
    ) -> tuple[bool, str | None]:
        tier = str(run_tier or "screening")
        atoms = int(target_atoms or DEFAULT_TIER_POLICY.get_target_atoms(tier))

        gpu_usage: dict[int, int] = {}
        for gpu in self.job_manager.gpu_tracker.get_all_gpus():
            gpu_usage[gpu.gpu_id] = 1 if gpu.current_job_id else 0

        return self.budget_policy.can_submit_job(
            tier=tier,
            atom_count=atoms,
            current_jobs=running_count,
            gpu_usage=gpu_usage,
            queued_jobs=queued_count,
        )
