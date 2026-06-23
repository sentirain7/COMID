"""역설계 파이프라인 실행 — 승인·제출·진행집계 (P2).

계획 §4.2 ④~⑤: plan_hash/정책 재검증(§4.6) → pipeline_id 발급 →
binder cell 직접 제출(정의 binder + 첨가제, §4.7-2 batch 조성 SSOT 경로
`_batch_binder_composition`) → 계면 실험을 binder 완료 의존 deferred child로
등록(기존 DependencyScheduler 경로 재사용) → metadata 태깅 기반 진행집계.

멤버 조회·해석은 ``members.py``, 결과 집계(목표 달성·ER)는 ``results.py``로
분리(R-P1-8). 모든 빌드/제출/의존성 로직은 기존 SSOT 호출로 조립한다.
"""

import uuid
from typing import Any

from common.hashing import compute_content_hash
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode
from contracts.policies.binders import SARA_COMPONENTS as _SARA
from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    InversePipelinePolicy,
    PlannedExperimentKind,
)
from contracts.schemas import FFType, LayerSourceType, RunTier, SubmissionSource
from features.common import with_optional_session
from features.inverse_design_pipeline.members import (  # noqa: F401 — 하위호환 재export
    PIPELINE_META_KEY,
    PIPELINE_REFS_META_KEY,
    find_pipeline_members,
    resolved_members,
)
from features.inverse_design_pipeline.service import (
    PLAN_SCHEMA_VERSION,
    compute_plan_hash,
    policy_snapshot,
)

logger = get_logger(__name__)


def approve_and_run(
    plan: dict,
    plan_hash: str,
    *,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
    loop_block: dict | None = None,
) -> dict:
    """승인된 계획을 검증 후 실행한다 (§4.2 ④ — 승인 게이트 이후).

    검증(§4.6): ① plan_hash 재계산 일치 ② plan 스키마 버전 ③ 정책 스냅샷이
    현재 정책과 일치(변경 시 재미리보기 요구). 통과 시 pipeline_id를 발급하고
    계획의 실험을 순서대로 제출한다. 멤버별 실패는 전체를 중단하지 않고
    상태로 보고한다(이미 제출된 실험은 유효한 라벨 데이터).

    Args:
        plan: preview_plan이 반환한 계획 문서 (클라이언트 회신, 변조 불가)
        plan_hash: preview_plan이 동봉한 해시
        policy: 파이프라인 정책 (SSOT)
        loop_block: 닫힌 루프(P7) 체인 상태 — 멤버 metadata에 보존

    Returns:
        {"pipeline_id", "plan_hash", "members": [...], "counts": {...}}

    Raises:
        ContractError: 해시 불일치 / 스키마 버전 불일치 / 정책 변경
    """
    _validate_plan_for_approval(plan, plan_hash, policy)

    pipeline_id = f"pl-{plan_hash}-{uuid.uuid4().hex[:8]}"
    mode = str(plan.get("mode", ""))
    candidates = list(plan.get("candidates", []))
    experiments = list(plan.get("experiments", []))
    # targets 요약을 멤버 metadata에 동봉 — get_results가 stateless로
    # 목표 대비 달성도를 복원하는 키 (§4.6 계획 비저장 설계)
    plan_targets = [
        {
            "metric_name": t.get("metric_name"),
            "target_min": t.get("target_min"),
            "target_max": t.get("target_max"),
            "direction": t.get("direction", "maximize"),
            "weight": t.get("weight", 1.0),
            "unit": t.get("unit"),
        }
        for t in plan.get("targets", [])
    ]
    # primary 온도: 다온도 세트에서 대표 스칼라 값을 읽을 기준 (R-P1-1).
    primary_temperature_k = float(
        (plan.get("request_echo") or {}).get("temperature_k_fixed")
        or (plan.get("policy_snapshot") or {}).get("default_temperature_k")
        or policy.default_temperature_k
    )

    members: list[dict] = []
    real_ids_by_plan_id: dict[str, str] = {}

    for entry in experiments:
        plan_exp_id = str(entry.get("plan_exp_id", ""))
        kind = str(entry.get("kind", ""))
        candidate = candidates[int(entry.get("candidate_index", 0))]
        pipeline_block = {
            "id": pipeline_id,
            "plan_hash": plan_hash,
            "plan_exp_id": plan_exp_id,
            "kind": kind,
            "candidate_index": int(entry.get("candidate_index", 0)),
            "mode": mode,
            "targets": plan_targets,
            "primary_temperature_k": primary_temperature_k,
        }
        if loop_block:
            # 닫힌 루프(P7) 체인 상태 — 다음 run_loop_round가 멤버 메타에서 복원
            pipeline_block["loop"] = dict(loop_block)
        if entry.get("dry_pair_id"):
            pipeline_block["dry_pair_plan_exp_id"] = str(entry["dry_pair_id"])

        member: dict[str, Any] = {"plan_exp_id": plan_exp_id, "kind": kind}
        try:
            if kind == PlannedExperimentKind.BINDER_CELL.value:
                if entry.get("action") == "reuse" and entry.get("matched_exp_ids"):
                    exp_id = str(entry["matched_exp_ids"][0])
                    _tag_pipeline_reference(exp_id, pipeline_block)
                    member.update({"action": "reused", "exp_id": exp_id})
                else:
                    exp_id, job_id = _submit_binder_cell(
                        entry, candidate, pipeline_block, plan_hash
                    )
                    member.update({"action": "submitted", "exp_id": exp_id, "job_id": job_id})
                real_ids_by_plan_id[plan_exp_id] = exp_id

            elif kind == PlannedExperimentKind.LAYERED_TENSILE.value:
                parent_plan_id = str(entry.get("depends_on", ""))
                parent_exp_id = real_ids_by_plan_id.get(parent_plan_id)
                if not parent_exp_id:
                    raise ContractError(
                        ErrorCode.INVALID_REQUEST,
                        f"Parent binder cell {parent_plan_id} was not submitted; "
                        "cannot register layered dependency.",
                    )
                exp_id = _create_layered_deferred(
                    entry, candidate, parent_exp_id, pipeline_block, plan_hash
                )
                member.update(
                    {"action": "deferred", "exp_id": exp_id, "parent_exp_id": parent_exp_id}
                )
                real_ids_by_plan_id[plan_exp_id] = exp_id

            elif kind == PlannedExperimentKind.WATER_INTERFACE_LAYERED.value:
                # 수분손상(wet) 페어 — crystal+water+binder 층상 (P6, §2).
                parent_plan_id = str(entry.get("depends_on", ""))
                parent_exp_id = real_ids_by_plan_id.get(parent_plan_id)
                if not parent_exp_id:
                    raise ContractError(
                        ErrorCode.INVALID_REQUEST,
                        f"Parent binder cell {parent_plan_id} was not submitted; "
                        "cannot register wet layered dependency.",
                    )
                dry_plan_id = str(entry.get("dry_pair_id", ""))
                if real_ids_by_plan_id.get(dry_plan_id):
                    # ER 후처리가 페어를 exp_id로도 찾을 수 있게 동봉
                    pipeline_block["dry_pair_exp_id"] = real_ids_by_plan_id[dry_plan_id]
                exp_id = _create_layered_deferred(
                    entry, candidate, parent_exp_id, pipeline_block, plan_hash, water=True
                )
                member.update(
                    {
                        "action": "deferred",
                        "exp_id": exp_id,
                        "parent_exp_id": parent_exp_id,
                        "dry_pair_plan_exp_id": dry_plan_id or None,
                    }
                )
                real_ids_by_plan_id[plan_exp_id] = exp_id

            else:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST, f"Unknown planned experiment kind: {kind}"
                )
        except Exception as exc:  # 멤버별 실패 격리 — 나머지는 계속
            logger.error("Pipeline member %s failed: %s", plan_exp_id, exc)
            member.update({"action": "error", "exp_id": None, "error": str(exc)})
        members.append(member)

    counts: dict[str, int] = {}
    for m in members:
        counts[m["action"]] = counts.get(m["action"], 0) + 1

    return {
        "pipeline_id": pipeline_id,
        "plan_hash": plan_hash,
        "mode": mode,
        "members": members,
        "counts": counts,
    }


def get_progress(pipeline_id: str, *, session=None) -> dict:
    """pipeline_id로 묶인 실험들의 진행 상태를 집계한다 (§4.2 ⑤).

    placeholder(층상 deferred)가 실제 layered 실험으로 치환된 경우
    ``real_layered_exp_id`` 간접참조를 따라 실효 상태를 보고한다.

    Args:
        pipeline_id: approve_and_run이 발급한 파이프라인 ID
        session: SQLAlchemy session (None이면 관리 세션 자체 개설)

    Returns:
        {"pipeline_id", "total", "status_counts", "members": [...]}
    """

    def _run(s) -> dict:
        resolved = resolved_members(s, pipeline_id)
        items: list[dict] = []
        status_counts: dict[str, int] = {}
        for r in resolved:
            meta = r["meta"]
            pipe = r["pipe"]
            replicate_group = (meta.get("replicate_group") or {}).get("group_id")
            ensemble_ready = "replicate_ensemble" in meta
            items.append(
                {
                    "exp_id": r["exp_id"],
                    "effective_exp_id": r["effective_exp_id"],
                    "plan_exp_id": pipe.get("plan_exp_id"),
                    "kind": pipe.get("kind"),
                    "candidate_index": pipe.get("candidate_index"),
                    "role": pipe.get("role", "member"),
                    "status": r["status"],
                    "effective_status": r["effective_status"],
                    "replicate_group_id": replicate_group,
                    "ensemble_ready": ensemble_ready,
                }
            )
            status_counts[r["effective_status"]] = status_counts.get(r["effective_status"], 0) + 1
        total = len(items)
        completed = status_counts.get("completed", 0)
        return {
            "pipeline_id": pipeline_id,
            "total": total,
            "completed": completed,
            "status_counts": status_counts,
            "members": items,
        }

    return with_optional_session(session, _run)


# ──────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────────────


def _validate_plan_for_approval(plan: dict, plan_hash: str, policy: InversePipelinePolicy) -> None:
    """§4.6 승인 검증 — 변조/버전/정책 변경 감지."""
    if not isinstance(plan, dict) or not plan_hash:
        raise ContractError(ErrorCode.INVALID_REQUEST, "plan and plan_hash are required")
    if compute_plan_hash(plan) != plan_hash:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "plan_hash mismatch: the plan document was modified after preview. "
            "Re-run preview to obtain a fresh plan.",
            {"failure_mode": "plan_hash_mismatch"},
        )
    if str(plan.get("plan_schema_version")) != PLAN_SCHEMA_VERSION:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Unsupported plan schema version: {plan.get('plan_schema_version')}",
            {"failure_mode": "plan_schema_version_mismatch"},
        )
    if plan.get("policy_snapshot") != policy_snapshot(policy):
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Pipeline policy changed since this plan was previewed. "
            "Re-run preview under the current policy.",
            {"failure_mode": "policy_changed"},
        )


def _deterministic_seed(plan_hash: str, plan_exp_id: str) -> int:
    """plan별 결정적 base seed — 같은 계획 승인은 같은 seed에서 출발."""
    digest = compute_content_hash({"plan_hash": plan_hash, "plan_exp_id": plan_exp_id}, length=8)
    return int(digest, 16) % 2_000_000_000


def _submit_binder_cell(
    entry: dict, candidate: dict, pipeline_block: dict, plan_hash: str
) -> tuple[str, str]:
    """정의 binder(+첨가제) binder cell 직접 제출 (§4.7-2).

    조성은 batch job binder 경로의 SSOT(YAML 정의 조성 + 첨가제 주입)를 그대로
    사용한다 — 정방향(UI batch)과 역설계가 동일한 분자 시스템을 생성한다.
    """
    from api.deps import get_job_manager
    from common.pathing import generate_exp_id
    from features.experiments.submission import _resolve_unique_exp_id
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade
    from protocols.stage_plan_compiler import build_stage_plan_metadata

    binder_type = str(candidate.get("binder_type") or "")
    if not binder_type:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Candidate is missing binder_type — regenerate the plan with preview_plan "
            "(binder/additive combination candidates).",
        )
    composition_view = dict(candidate.get("composition") or {})
    additive_mol_id = candidate.get("additive_type")
    additive_wt = float(candidate.get("additive_wt", composition_view.get("additive", 0.0)))
    if not (additive_mol_id and additive_wt > 0.0):
        additive_mol_id = None
        additive_wt = 0.0
    # 프로토콜 프리셋(승급 아닌 선택) → stabilization chain. structure_size는
    # 셀 크기(분자 수). 둘 다 계획 entry에서 — 레거시 폴백은 기본값.
    protocol_preset = str(entry.get("protocol_preset", "bulk"))
    structure_size = str(entry.get("structure_size", BINDER_STRUCTURE_SIZE))
    chain_tier = _protocol_preset_to_chain(protocol_preset)
    temperature_k = float(
        entry.get("temperature_k", DEFAULT_INVERSE_PIPELINE_POLICY.default_temperature_k)
    )
    stage_duration_overrides = entry.get("stage_duration_overrides") or None
    if stage_duration_overrides:
        # plan 문서(JSON)의 dict를 모델로 강제 — CeleryJobManager는 model_dump
        # 가능한 객체를 기대한다 (스키마 검증 겸용)
        from api.schemas import StageDurationOverrideRequest

        stage_duration_overrides = [
            StageDurationOverrideRequest.model_validate(o) if isinstance(o, dict) else o
            for o in stage_duration_overrides
        ]
    ff_type = FFType.BULK_FF_GAFF2.value
    base_seed = _deterministic_seed(plan_hash, str(entry.get("plan_exp_id", "")))

    mol_counts, sara_wt = _batch_binder_composition(
        binder_type=binder_type,
        additive_mol_id=str(additive_mol_id) if additive_mol_id else None,
        additive_wt=additive_wt,
        temperature_k=temperature_k,
        structure_size=structure_size,
    )
    # target_atoms는 tier가 아니라 실제 조성 원자 수 합으로 산출(mol_count 모드라
    # 빌드엔 무영향이나 메타/exp_id 명목값을 정확히). entry 오버라이드 우선.
    target_atoms = int(entry.get("target_atoms") or _composition_atom_count(mol_counts))
    build_request = create_build_request(
        composition=mol_counts,
        composition_mode="mol_count",
        target_atoms=target_atoms,
        seed=base_seed,
        tier=chain_tier,
        # batch와 동일 기본(미지정 → BuildRequest 기본 밀도). entry 오버라이드는
        # smoke/pilot 다운스케일용 명시적 사용자 결정(plan_hash 봉인).
        initial_density=(float(entry["initial_density"]) if entry.get("initial_density") else None),
    )

    protocol_request = create_protocol_request(
        tier=chain_tier,
        ff_type=ff_type,
        temperature_K=temperature_k,
    )
    metadata = build_stage_plan_metadata(
        protocol_request=protocol_request,
        canonical_stage_requests=[],
        base_metadata={
            "source": SubmissionSource.INVERSE_PIPELINE.value,
            PIPELINE_META_KEY: pipeline_block,
        },
    )

    exp_id, seed = _resolve_unique_exp_id(
        base_seed=base_seed,
        exp_id_builder=lambda candidate_seed: generate_exp_id(
            binder_type=binder_type,
            structure_size=structure_size,
            temperature_k=temperature_k,
            additive=additive_mol_id,
            ff_type=ff_type,
            aging_state=BINDER_AGING_STATE,
            atom_count=target_atoms,
            seed=candidate_seed,
        ),
    )
    if seed != base_seed:
        build_request = build_request.model_copy(update={"seed": seed})

    job_id, _ = SubmissionFacade.submit_experiment(
        job_manager=get_job_manager(),
        exp_id=exp_id,
        run_tier=chain_tier,
        ff_type=ff_type,
        target_atoms=target_atoms,
        temperature_k=temperature_k,
        pressure_atm=1.0,
        seed=seed,
        comp_asphaltene_wt=sara_wt["asphaltene"],
        comp_resin_wt=sara_wt["resin"],
        comp_aromatic_wt=sara_wt["aromatic"],
        comp_saturate_wt=sara_wt["saturate"],
        build_request=build_request,
        protocol_request=protocol_request,
        material_id="inverse_pipeline",
        stage_duration_overrides=stage_duration_overrides,
        additive_type=additive_mol_id,
        additive_wt=additive_wt,
        additive_mol_id=additive_mol_id,
        metadata_json=metadata,
    )
    return exp_id, job_id


# 기본 구조 단위(요청 미지정 시) / 기본 노화 상태.
BINDER_STRUCTURE_SIZE = "X1"
BINDER_AGING_STATE = "non_aging"


def _protocol_preset_to_chain(preset: str) -> str:
    """프로토콜 프리셋(승급 아닌 선택)을 stabilization chain 키로 매핑.

    역설계는 tier 승급 사다리를 쓰지 않는다 — 목표 물성에 따라 NEMD 스테이지를
    포함한 viscosity 체인을 '선택'할 뿐이다. RunTier enum 값은 프로토콜 정책이
    공유하는 체인 키이므로 그대로 재사용하되, 의미는 프리셋 선택으로 격리한다.
    """
    return RunTier.VISCOSITY.value if preset == "viscosity" else RunTier.SCREENING.value


def _composition_atom_count(mol_counts: dict[str, float]) -> int:
    """mol_id→count 조성의 총 원자 수 (target_atoms 명목값 — tier 비의존).

    mol_count 빌드 경로(`_build_from_mol_counts`)와 동일하게 `get_info`로 full
    mol_id의 atom_count를 합산한다.
    """
    from api.deps import get_molecule_db

    db = get_molecule_db()
    total = 0
    for mol_id, count in mol_counts.items():
        info = db.get_info(mol_id)
        if info:
            total += int(info.atom_count) * int(count)
    return total


def _batch_binder_composition(
    *,
    binder_type: str,
    additive_mol_id: str | None,
    additive_wt: float,
    temperature_k: float,
    structure_size: str = BINDER_STRUCTURE_SIZE,
) -> tuple[dict[str, float], dict[str, float]]:
    """batch job binder 경로의 조성 SSOT 호출 (§4.7-2).

    base 조성은 YAML SSOT(`get_binder_composition_with_aging`), 첨가제는 batch와
    동일한 주입 로직(`_inject_additive_into_composition` — base를 (1-wt%)로
    스케일 + 첨가제 분자를 default_counts로 추가)을 재사용한다. 정방향(UI
    batch)과 역설계가 같은 분자 시스템을 생성하므로, batch를 개선하면 양쪽에
    동시에 적용된다. structure_size(X1/X2/X3)가 분자 수 스케일을 결정한다.

    Returns:
        (mol_id→count 조성, binder SARA fractions wt% — comp_*_wt 기록용)
    """
    from api.deps import get_aging_config, get_molecule_db
    from orchestrator.batch_job_binder_cell import (
        AdditiveBatchJobBinderCellRunner,
        BatchJobBinderCellRunner,
    )

    db = get_molecule_db()
    config = get_aging_config()
    if not config:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Molecule library config unavailable; cannot resolve binder composition.",
        )

    temp_code = db.get_temperature_code(config, temperature_k)
    base = db.get_binder_composition_with_aging(
        config,
        binder_type=binder_type,
        size=structure_size,
        aging=BINDER_AGING_STATE,
        temp_code=temp_code,
    )
    composition = {mol_id: float(count) for mol_id, count in base.items()}

    if additive_mol_id and additive_wt > 0.0:
        catalog_map: dict[str, dict] | None = None
        try:
            from features.experiments.validation import load_active_additive_catalog

            known = load_active_additive_catalog()
            if additive_mol_id in known:
                catalog_map = {additive_mol_id: known[additive_mol_id]}
        except Exception:
            catalog_map = None  # config["additives"] 폴백 (batch와 동일)
        runner = AdditiveBatchJobBinderCellRunner(experiment_repo=None, molecule_db=db)
        composition = runner._inject_additive_into_composition(
            composition,
            additive_mol_id,
            additive_wt,
            config,
            structure_size,
            additive_catalog_map=catalog_map,
        )

    sara_wt = BatchJobBinderCellRunner._resolve_sara_wt(config, db, binder_type)
    return composition, sara_wt


def _create_layered_deferred(
    entry: dict,
    candidate: dict,
    parent_exp_id: str,
    pipeline_block: dict,
    plan_hash: str,
    *,
    water: bool = False,
    policy: InversePipelinePolicy = DEFAULT_INVERSE_PIPELINE_POLICY,
) -> str:
    """layered tensile 실험을 binder 완료 의존 deferred child로 등록한다.

    placeholder 실험 행 + 의존성 edge + ``deferred_submission`` payload를
    만들고, 실제 제출은 기존 DependencyScheduler.submit_ready가 parent
    완료 시 수행한다(§4.2 ④의 의존성 등록).

    ``water=True``(수분손상 wet 페어, P6)면 crystal과 binder 사이에 water
    층을 ``auto_water`` 마커로 편성 — 실제 water cell은 parent 완료 후
    DependencyScheduler가 parent box 크기로 프로비저닝/재사용한다.
    """
    from database.models import ExperimentModel
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.job_dependency_repo import JobDependencyRepository
    from features.common import run_in_session_commit

    aggregate = dict(entry.get("aggregate") or {})
    material = aggregate.get("material")
    if not material:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Layered experiment plan entry is missing aggregate material",
        )

    composition = dict(candidate.get("composition") or {})
    sara_wt = {k: float(composition.get(k, 0.0)) for k in _SARA}
    base_seed = _deterministic_seed(plan_hash, str(entry.get("plan_exp_id", "")))
    n_replicates = entry.get("replicate_seeds")
    replicate_seed_list = (
        [base_seed + i for i in range(int(n_replicates))]
        if n_replicates and int(n_replicates) >= 2
        else None
    )
    # layered(인장)는 점도 NEMD와 무관 — protocol_preset 기반 bulk 체인.
    chain_tier = _protocol_preset_to_chain(str(entry.get("protocol_preset", "bulk")))
    temperature_k = float(entry.get("temperature_k", policy.default_temperature_k))

    layer_dicts: list[dict] = [
        {
            "source_type": LayerSourceType.CRYSTAL_STRUCTURE.value,
            "auto_match_material": material,
            "label": f"{material} slab",
        }
    ]
    if water:
        moisture = policy.moisture
        layer_dicts.append(
            {
                "source_type": LayerSourceType.INTERFACE_MOLECULE_CELL.value,
                "auto_water": {
                    "mol_id": moisture.water_mol_id,
                    "thickness_angstrom": moisture.water_layer_thickness_angstrom,
                    "target_density": moisture.water_target_density,
                    "default_xy_angstrom": moisture.water_default_xy_angstrom,
                },
                "label": "water layer",
            }
        )
    layer_dicts.append(
        {
            "source_type": LayerSourceType.BINDER_CELL.value,
            "prereq_exp_id": parent_exp_id,
            "label": "designed binder",
        }
    )

    placeholder_id = f"{pipeline_block['id']}-{entry.get('plan_exp_id', 'lay')}"
    payload = {
        "kind": "layered",
        "name": f"inverse-{entry.get('plan_exp_id', 'layered')}",
        "layers": layer_dicts,
        "run_tier": chain_tier,
        "ff_type": FFType.BULK_FF_GAFF2.value,
        "temperature_K": temperature_k,
        "tensile_enabled": bool(entry.get("tensile_enabled", False)),
        "replicate_seeds": replicate_seed_list,
    }

    def _op(session) -> None:
        exp_repo = ExperimentRepository(session)
        dep_repo = JobDependencyRepository(session)
        existing = session.query(ExperimentModel).filter_by(exp_id=placeholder_id).first()
        if existing is not None:
            raise ContractError(
                ErrorCode.DUPLICATE_RECORD,
                f"Pipeline placeholder already exists: {placeholder_id}",
            )
        exp_repo.create(
            exp_id=placeholder_id,
            run_tier=chain_tier,
            ff_type=FFType.BULK_FF_GAFF2.value,
            comp_asphaltene_wt=sara_wt["asphaltene"],
            comp_resin_wt=sara_wt["resin"],
            comp_aromatic_wt=sara_wt["aromatic"],
            comp_saturate_wt=sara_wt["saturate"],
            study_type="layer_bulkff",
            status="pending",
            temperature_K=temperature_k,
            seed=base_seed,
            additive_type=candidate.get("additive_type"),
            additive_wt=float(composition.get("additive", 0.0)),
            additive_mol_id=candidate.get("additive_type"),
            metadata_json={
                "source": SubmissionSource.INVERSE_PIPELINE.value,
                PIPELINE_META_KEY: {**pipeline_block, "role": "layered_placeholder"},
                "deferred_submission": payload,
            },
        )
        dep_repo.create_dependency(parent_exp_id, placeholder_id)

    run_in_session_commit(_op)
    return placeholder_id


def _tag_pipeline_reference(exp_id: str, pipeline_block: dict) -> None:
    """재사용된 기존 실험에 파이프라인 참조를 누적 태깅한다 (다중 소속 허용)."""
    from database.models import ExperimentModel
    from features.common import run_in_session_commit

    def _op(session) -> None:
        row = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
        if row is None:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Reusable experiment not found: {exp_id}",
            )
        meta = dict(row.metadata_json or {})
        refs = list(meta.get(PIPELINE_REFS_META_KEY) or [])
        if not any(r.get("id") == pipeline_block["id"] for r in refs if isinstance(r, dict)):
            refs.append({**pipeline_block, "role": "reused"})
        meta[PIPELINE_REFS_META_KEY] = refs
        row.metadata_json = meta  # 전체 dict 재할당(SQLAlchemy JSON 변경감지)

    run_in_session_commit(_op)
