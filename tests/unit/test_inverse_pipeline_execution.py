"""역설계 파이프라인 approve_and_run·진행집계 테스트 (P2, 계획 §4.2 ④~⑤/§4.6)."""

from types import SimpleNamespace

import pytest

from contracts.errors import ContractError
from contracts.policies.inverse_pipeline import DEFAULT_INVERSE_PIPELINE_POLICY
from database.models import ExperimentModel, JobDependencyModel
from features.inverse_design_pipeline import execution, queries, service
from features.inverse_design_pipeline.execution import (
    PIPELINE_META_KEY,
    PIPELINE_REFS_META_KEY,
    approve_and_run,
    find_pipeline_members,
    get_progress,
)
from features.inverse_design_pipeline.service import compute_plan_hash, preview_plan

_SESSION = object()


def _request(metrics, **kwargs):
    from api.schemas import InverseDesignRequest
    from api.schemas.recommendations import PropertyTargetItem

    return InverseDesignRequest(
        custom_targets=[PropertyTargetItem(metric_name=m, target_min=0.1) for m in metrics],
        **kwargs,
    )


@pytest.fixture
def bootstrap_env(monkeypatch):
    monkeypatch.setattr(service, "_get_capability_manifest", lambda: None)
    monkeypatch.setattr(queries, "count_training_labels", lambda s, m: 0)
    monkeypatch.setattr(queries, "find_experiments_by_composition", lambda *a, **k: [])


async def _make_plan(metrics=("density",), moisture_damage=False, **req_kwargs):
    result = await preview_plan(
        _request(list(metrics), **req_kwargs),
        moisture_damage=moisture_damage,
        session=_SESSION,
    )
    return result["plan"], result["plan_hash"]


@pytest.fixture
def fake_submissions(monkeypatch):
    """제출/의존성 부작용을 기록만 하는 가짜 구현."""
    calls = {"binder": [], "layered": [], "refs": []}

    def fake_binder(entry, candidate, pipeline_block, plan_hash):
        calls["binder"].append((entry, candidate, pipeline_block))
        return f"real-{entry['plan_exp_id']}", f"job-{entry['plan_exp_id']}"

    def fake_layered(entry, candidate, parent_exp_id, pipeline_block, plan_hash, **kwargs):
        calls["layered"].append((entry, parent_exp_id, pipeline_block, kwargs))
        return f"{pipeline_block['id']}-{entry['plan_exp_id']}"

    def fake_ref(exp_id, pipeline_block):
        calls["refs"].append((exp_id, pipeline_block))

    monkeypatch.setattr(execution, "_submit_binder_cell", fake_binder)
    monkeypatch.setattr(execution, "_create_layered_deferred", fake_layered)
    monkeypatch.setattr(execution, "_tag_pipeline_reference", fake_ref)
    return calls


class TestApprovalValidation:
    @pytest.mark.asyncio
    async def test_hash_mismatch_rejected(self, bootstrap_env):
        plan, plan_hash = await _make_plan()
        tampered = dict(plan)
        tampered["mode"] = "bo"
        with pytest.raises(ContractError, match="plan_hash mismatch"):
            approve_and_run(tampered, plan_hash)

    @pytest.mark.asyncio
    async def test_schema_version_mismatch_rejected(self, bootstrap_env):
        plan, _ = await _make_plan()
        plan = dict(plan)
        plan["plan_schema_version"] = "999"
        with pytest.raises(ContractError, match="schema version"):
            approve_and_run(plan, compute_plan_hash(plan))

    @pytest.mark.asyncio
    async def test_policy_change_rejected(self, bootstrap_env):
        plan, _ = await _make_plan()
        plan = dict(plan)
        snapshot = dict(plan["policy_snapshot"])
        snapshot["default_temperature_k"] = 999.0  # 미리보기 시점과 다른 정책
        plan["policy_snapshot"] = snapshot
        with pytest.raises(ContractError, match="policy changed"):
            approve_and_run(plan, compute_plan_hash(plan))

    def test_missing_inputs_rejected(self):
        with pytest.raises(ContractError, match="required"):
            approve_and_run({}, "")


@pytest.mark.asyncio
class TestApproveAndRun:
    async def test_bulk_plan_submits_binder_cells(self, bootstrap_env, fake_submissions):
        plan, plan_hash = await _make_plan(["density"])
        result = approve_and_run(plan, plan_hash)

        batch = len(plan["candidates"])
        assert result["pipeline_id"].startswith(f"pl-{plan_hash}-")
        assert result["counts"] == {"submitted": batch}
        assert len(fake_submissions["binder"]) == batch
        for member in result["members"]:
            assert member["action"] == "submitted"
            assert member["exp_id"].startswith("real-")
        # 모든 제출에 동일 pipeline_id 태깅
        ids = {block["id"] for _, _, block in fake_submissions["binder"]}
        assert ids == {result["pipeline_id"]}

    async def test_reused_binder_cells_are_tagged_not_submitted(
        self, bootstrap_env, fake_submissions, monkeypatch
    ):
        monkeypatch.setattr(
            queries,
            "find_experiments_by_composition",
            lambda *a, **k: [SimpleNamespace(exp_id="prior_001")],
        )
        plan, plan_hash = await _make_plan(["density"])
        result = approve_and_run(plan, plan_hash)

        assert result["counts"] == {"reused": len(plan["candidates"])}
        assert not fake_submissions["binder"]
        assert all(exp_id == "prior_001" for exp_id, _ in fake_submissions["refs"])

    async def test_layered_registered_with_parent_dependency(self, bootstrap_env, fake_submissions):
        from api.schemas.recommendations import AggregateSpecRequest

        plan, plan_hash = await _make_plan(
            ["work_of_separation"],
            aggregate_specs=[AggregateSpecRequest(material="SiO2", surface="001")],
        )
        result = approve_and_run(plan, plan_hash)

        deferred = [m for m in result["members"] if m["action"] == "deferred"]
        batch = len(plan["candidates"])
        assert len(deferred) == batch
        for member in deferred:
            assert member["parent_exp_id"].startswith("real-")
        # 부모 binder는 같은 후보의 binder cell
        for entry, parent_exp_id, _, _ in fake_submissions["layered"]:
            assert parent_exp_id == f"real-{entry['depends_on']}"

    async def test_water_pair_deferred_with_dry_link(self, bootstrap_env, fake_submissions):
        """수분손상 wet 페어는 water=True deferred로 등록되고 dry 페어를 참조한다 (P6)."""
        from api.schemas.recommendations import AggregateSpecRequest

        plan, plan_hash = await _make_plan(
            ["work_of_separation"],
            moisture_damage=True,
            aggregate_specs=[AggregateSpecRequest(material="SiO2", surface="001")],
        )
        result = approve_and_run(plan, plan_hash)

        batch = len(plan["candidates"])
        wet_members = [m for m in result["members"] if m["kind"] == "water_interface_layered"]
        assert len(wet_members) == batch
        assert all(m["action"] == "deferred" for m in wet_members)
        assert all(m["dry_pair_plan_exp_id"] for m in wet_members)

        wet_calls = [
            (entry, block, kwargs)
            for entry, _, block, kwargs in fake_submissions["layered"]
            if entry["kind"] == "water_interface_layered"
        ]
        assert len(wet_calls) == batch
        for entry, block, kwargs in wet_calls:
            assert kwargs.get("water") is True
            assert block["dry_pair_plan_exp_id"] == entry["dry_pair_id"]
            # dry 페어 실제 exp id도 동봉 (ER 후처리 키)
            assert block["dry_pair_exp_id"].startswith("pl-")

    async def test_member_failure_is_isolated(self, bootstrap_env, fake_submissions, monkeypatch):
        calls = {"n": 0}

        def flaky(entry, candidate, pipeline_block, plan_hash):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return f"real-{entry['plan_exp_id']}", "job"

        monkeypatch.setattr(execution, "_submit_binder_cell", flaky)
        plan, plan_hash = await _make_plan(["density"])
        result = approve_and_run(plan, plan_hash)

        batch = len(plan["candidates"])
        assert result["counts"]["error"] == 1
        assert result["counts"]["submitted"] == batch - 1
        errored = [m for m in result["members"] if m["action"] == "error"]
        assert "boom" in errored[0]["error"]

    async def test_layered_skipped_when_parent_failed(
        self, bootstrap_env, fake_submissions, monkeypatch
    ):
        from api.schemas.recommendations import AggregateSpecRequest

        def always_fail(entry, candidate, pipeline_block, plan_hash):
            raise RuntimeError("parent down")

        monkeypatch.setattr(execution, "_submit_binder_cell", always_fail)
        plan, plan_hash = await _make_plan(
            ["work_of_separation"],
            aggregate_specs=[AggregateSpecRequest(material="SiO2", surface="001")],
        )
        result = approve_and_run(plan, plan_hash)
        # 부모 실패 → layered도 error (제출 안 됨)
        assert not fake_submissions["layered"]
        assert result["counts"]["error"] == result["counts"].get("error", 0)
        layered_members = [m for m in result["members"] if m["kind"] == "layered_tensile"]
        assert all(m["action"] == "error" for m in layered_members)


# ──────────────────────────────────────────────────────────────────────
# 실 DB(in-memory) — placeholder/태깅/진행집계
# ──────────────────────────────────────────────────────────────────────


def _add_exp(session, exp_id, *, status="completed", metadata=None, **overrides):
    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status=status,
        comp_asphaltene_wt=15.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=20.0,
        temperature_K=293.0,
        metadata_json=metadata,
        **overrides,
    )
    session.add(exp)
    session.flush()
    return exp


class TestLayeredDeferredCreation:
    def test_creates_placeholder_and_edge(self, isolated_db_session, monkeypatch):
        from features.inverse_design_pipeline import execution as exec_module

        _add_exp(isolated_db_session, "parent_binder")

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)
        # execution 모듈은 함수 내부에서 features.common을 import하므로 위 패치로 충분

        entry = {
            "plan_exp_id": "exp-002",
            "kind": "layered_tensile",
            "aggregate": {"material": "SiO2", "surface": "001"},
            "temperature_k": 293.0,
            "tensile_enabled": True,
            "replicate_seeds": 3,
            "run_tier": "screening",
        }
        candidate = {
            "composition": {
                "asphaltene": 15.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 20.0,
            },
            "additive_type": None,
        }
        pipeline_block = {"id": "pl-test-1", "plan_exp_id": "exp-002", "kind": "layered_tensile"}

        placeholder_id = exec_module._create_layered_deferred(
            entry, candidate, "parent_binder", pipeline_block, "hash123"
        )

        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id=placeholder_id).one()
        meta = row.metadata_json
        payload = meta["deferred_submission"]
        assert payload["kind"] == "layered"
        assert payload["tensile_enabled"] is True
        assert len(payload["replicate_seeds"]) == 3
        assert payload["layers"][0]["source_type"] == "crystal_structure"
        assert payload["layers"][0]["auto_match_material"] == "SiO2"
        assert payload["layers"][1]["source_type"] == "binder_cell"
        assert payload["layers"][1]["prereq_exp_id"] == "parent_binder"
        assert meta[PIPELINE_META_KEY]["role"] == "layered_placeholder"

        edge = (
            isolated_db_session.query(JobDependencyModel)
            .filter_by(child_exp_id=placeholder_id)
            .one()
        )
        assert edge.parent_exp_id == "parent_binder"
        assert edge.status == "blocked"

    def test_single_replicate_keeps_none(self, isolated_db_session, monkeypatch):
        from features.inverse_design_pipeline import execution as exec_module

        _add_exp(isolated_db_session, "parent_b2")

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)
        entry = {
            "plan_exp_id": "exp-009",
            "aggregate": {"material": "CaCO3"},
            "temperature_k": 293.0,
            "tensile_enabled": False,
            "replicate_seeds": None,
        }
        placeholder_id = exec_module._create_layered_deferred(
            entry,
            {"composition": {}, "additive_type": None},
            "parent_b2",
            {"id": "pl-test-2", "plan_exp_id": "exp-009", "kind": "layered_tensile"},
            "hash456",
        )
        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id=placeholder_id).one()
        assert row.metadata_json["deferred_submission"]["replicate_seeds"] is None


class TestPipelineMembershipAndProgress:
    def test_find_members_exact_match(self, isolated_db_session):
        _add_exp(
            isolated_db_session,
            "m1",
            metadata={PIPELINE_META_KEY: {"id": "pl-abc", "plan_exp_id": "exp-001"}},
        )
        _add_exp(
            isolated_db_session,
            "m2",
            metadata={PIPELINE_REFS_META_KEY: [{"id": "pl-abc", "role": "reused"}]},
        )
        # 다른 파이프라인/태그 없음 → 미포함
        _add_exp(isolated_db_session, "other", metadata={PIPELINE_META_KEY: {"id": "pl-xyz"}})
        _add_exp(isolated_db_session, "plain", metadata=None)

        members = find_pipeline_members(isolated_db_session, "pl-abc")
        assert {m.exp_id for m in members} == {"m1", "m2"}

    def test_progress_counts_and_indirection(self, isolated_db_session):
        pid = "pl-prog-1"
        _add_exp(
            isolated_db_session,
            "b1",
            status="completed",
            metadata={
                PIPELINE_META_KEY: {"id": pid, "plan_exp_id": "exp-001", "kind": "binder_cell"}
            },
        )
        # placeholder → real layered 간접참조 (real도 메타 전파로 태깅됨)
        _add_exp(
            isolated_db_session,
            "ph1",
            status="cancelled",
            metadata={
                PIPELINE_META_KEY: {
                    "id": pid,
                    "plan_exp_id": "exp-002",
                    "kind": "layered_tensile",
                    "role": "layered_placeholder",
                },
                "real_layered_exp_id": "lay1",
            },
        )
        _add_exp(
            isolated_db_session,
            "lay1",
            status="running",
            metadata={
                PIPELINE_META_KEY: {
                    "id": pid,
                    "plan_exp_id": "exp-002",
                    "kind": "layered_tensile",
                    "role": "layered",
                }
            },
        )

        progress = get_progress(pid, session=isolated_db_session)

        # placeholder는 실제 layered가 직접 멤버이므로 dedupe
        assert progress["total"] == 2
        assert progress["status_counts"] == {"completed": 1, "running": 1}
        kinds = {m["plan_exp_id"]: m for m in progress["members"]}
        assert kinds["exp-002"]["effective_status"] == "running"
        assert kinds["exp-002"]["exp_id"] == "lay1"

    def test_progress_follows_indirection_when_real_not_tagged(self, isolated_db_session):
        pid = "pl-prog-2"
        _add_exp(
            isolated_db_session,
            "ph2",
            status="cancelled",
            metadata={
                PIPELINE_META_KEY: {"id": pid, "plan_exp_id": "exp-003", "kind": "layered_tensile"},
                "real_layered_exp_id": "lay2",
            },
        )
        _add_exp(isolated_db_session, "lay2", status="queued", metadata=None)  # 태깅 전파 전

        progress = get_progress(pid, session=isolated_db_session)
        assert progress["total"] == 1
        member = progress["members"][0]
        assert member["exp_id"] == "ph2"
        assert member["effective_exp_id"] == "lay2"
        assert member["effective_status"] == "queued"

    def test_tag_pipeline_reference_appends_once(self, isolated_db_session, monkeypatch):
        from features.inverse_design_pipeline import execution as exec_module

        _add_exp(isolated_db_session, "reusable", metadata={"source": "experiment_submit"})

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)
        block = {"id": "pl-ref-1", "plan_exp_id": "exp-001", "kind": "binder_cell"}
        exec_module._tag_pipeline_reference("reusable", block)
        exec_module._tag_pipeline_reference("reusable", block)  # 중복 호출 무해

        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id="reusable").one()
        refs = row.metadata_json[PIPELINE_REFS_META_KEY]
        assert len(refs) == 1
        assert refs[0]["role"] == "reused"
        assert row.metadata_json["source"] == "experiment_submit"  # 기존 메타 보존


class TestDeterministicSeed:
    def test_same_plan_same_seed(self):
        s1 = execution._deterministic_seed("hash", "exp-001")
        s2 = execution._deterministic_seed("hash", "exp-001")
        s3 = execution._deterministic_seed("hash", "exp-002")
        assert s1 == s2
        assert s1 != s3
        assert 0 <= s1 < 2_000_000_000


class TestPolicySnapshotCoverage:
    """R-P1-2: 실험 구조를 결정하는 정책 필드가 스냅샷에 포함돼야 한다."""

    @pytest.mark.asyncio
    async def test_snapshot_includes_structure_fields(self, bootstrap_env):
        plan, _ = await _make_plan(["density"])
        snapshot = plan["policy_snapshot"]
        assert snapshot["tg_temperature_sweep_k"] == list(
            DEFAULT_INVERSE_PIPELINE_POLICY.tg_temperature_sweep_k
        )
        assert snapshot["viscosity_stage_metrics"] == list(
            DEFAULT_INVERSE_PIPELINE_POLICY.viscosity_stage_metrics
        )
        assert "moisture" in snapshot

    @pytest.mark.asyncio
    async def test_tg_sweep_change_invalidates_plan(self, bootstrap_env):
        plan, _ = await _make_plan(["density"])
        plan = dict(plan)
        snapshot = dict(plan["policy_snapshot"])
        snapshot["tg_temperature_sweep_k"] = [100.0]  # 미리보기 후 정책 변경 시뮬레이션
        plan["policy_snapshot"] = snapshot
        with pytest.raises(ContractError, match="policy changed"):
            approve_and_run(plan, compute_plan_hash(plan))

    @pytest.mark.asyncio
    async def test_binder_blocks_carry_primary_temperature(self, bootstrap_env, fake_submissions):
        """R-P1-1 전제: 승인 시 pipeline 블록에 primary_temperature_k 동봉."""
        plan, plan_hash = await _make_plan(["density"], temperature_k_fixed=313.0)
        approve_and_run(plan, plan_hash)
        for _, _, block in fake_submissions["binder"]:
            assert block["primary_temperature_k"] == 313.0


class TestBuildRequestFactoryMode:
    """실 E2E에서 발견된 latent 버그 회귀: wt_percent 모드 명시 보장."""

    def test_wt_percent_mode_is_explicit(self):
        from orchestrator.request_factory import create_build_request

        request = create_build_request(
            composition={"asphaltene": 15.0, "resin": 30.0, "aromatic": 35.0, "saturate": 20.0},
            target_atoms=3000,
            seed=1,
        )
        # BuildRequest 스키마 기본값(mol_count)에 가려지면 SARA wt%가
        # 분자 수로 해석돼 워커 빌드가 E2002로 실패한다.
        assert request.composition_mode == "wt_percent"

    def test_mol_count_mode_passthrough(self):
        from orchestrator.request_factory import create_build_request

        request = create_build_request(
            composition={"U-AS-Thio-0293": 10},
            target_atoms=3000,
            seed=1,
            composition_mode="mol_count",
        )
        assert request.composition_mode == "mol_count"


class TestBatchCompositionSSOT:
    """§3 회귀: binder cell 조성은 batch job binder 경로의 SSOT를 그대로 사용 —
    정방향(UI batch)과 역설계가 동일한 분자 시스템을 생성한다."""

    def test_yaml_composition_no_additive(self):
        from features.inverse_design_pipeline.execution import _batch_binder_composition

        mol_counts, sara = _batch_binder_composition(
            binder_type="AAA1", additive_mol_id=None, additive_wt=0.0, temperature_k=293.0
        )
        # YAML SSOT: AAA1 X1 = 12종 72분자 (완료 실적이 있는 batch 조성과 동일)
        assert len(mol_counts) == 12
        assert sum(int(v) for v in mol_counts.values()) == 72
        assert all(mid.startswith("U-") for mid in mol_counts)  # non_aging variant
        assert sara["asphaltene"] == pytest.approx(11.1, abs=0.1)

    def test_additive_injected_with_batch_scaling(self):
        from features.inverse_design_pipeline.execution import _batch_binder_composition

        base, _ = _batch_binder_composition(
            binder_type="AAA1", additive_mol_id=None, additive_wt=0.0, temperature_k=293.0
        )
        mixed, _ = _batch_binder_composition(
            binder_type="AAA1", additive_mol_id="SBS_3_7", additive_wt=5.0, temperature_k=293.0
        )
        # batch의 _inject_additive_into_composition와 동일: base ×(1-wt%) + 첨가제
        assert "SBS_3_7" in mixed
        base_total = sum(int(v) for v in base.values())
        scaled_total = sum(int(v) for k, v in mixed.items() if k != "SBS_3_7")
        assert scaled_total < base_total

    def test_missing_binder_type_rejected(self):
        from features.inverse_design_pipeline.execution import _submit_binder_cell

        with pytest.raises(ContractError, match="binder_type"):
            _submit_binder_cell(
                {"plan_exp_id": "exp-001", "protocol_preset": "bulk", "temperature_k": 293.0},
                {"composition": {"asphaltene": 15.0}},  # binder_type 없음 (구 plan)
                {"id": "pl-x"},
                "hash",
            )

    def test_structure_size_scales_molecule_count(self):
        from features.inverse_design_pipeline.execution import _batch_binder_composition

        x1, _ = _batch_binder_composition(
            binder_type="AAA1",
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            structure_size="X1",
        )
        x2, _ = _batch_binder_composition(
            binder_type="AAA1",
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            structure_size="X2",
        )
        # YAML size 인덱스: X2는 X1의 2배 분자 수
        assert sum(int(v) for v in x2.values()) == 2 * sum(int(v) for v in x1.values())

    def test_protocol_preset_maps_to_chain_without_tier_escalation(self):
        from features.inverse_design_pipeline.execution import _protocol_preset_to_chain

        # 승급 아닌 선택: 점도 표적이면 viscosity 체인, 아니면 screening(bulk)
        assert _protocol_preset_to_chain("viscosity") == "viscosity"
        assert _protocol_preset_to_chain("bulk") == "screening"

    def test_target_atoms_from_composition_not_tier(self):
        from features.inverse_design_pipeline.execution import (
            _batch_binder_composition,
            _composition_atom_count,
        )

        mc, _ = _batch_binder_composition(
            binder_type="AAA1",
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            structure_size="X1",
        )
        atoms = _composition_atom_count(mc)
        # tier 명목값(100k)이 아니라 실제 조성 원자 수 (AAA1 X1 ~5.5k)
        assert 3000 < atoms < 10000


class TestDeferredLayeredEInterDefault:
    """deferred layered payload는 interaction_analysis를 명시하지 않는다 —
    layered service 제출 시 자동 활성(v01.05.24, 장거리 Coulomb 복원)이
    정책 기본으로 적용되도록 서비스 기본값에 맡긴다."""

    def test_payload_omits_interaction_analysis(self, isolated_db_session, monkeypatch):
        from features.inverse_design_pipeline import execution as exec_module

        _add_exp(isolated_db_session, "parent_einter")

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)
        placeholder_id = exec_module._create_layered_deferred(
            {
                "plan_exp_id": "exp-einter",
                "aggregate": {"material": "SiO2", "surface": "001"},
                "temperature_k": 293.0,
                "tensile_enabled": True,
                "replicate_seeds": None,
            },
            {"composition": {}, "additive_type": None},
            "parent_einter",
            {"id": "pl-einter", "plan_exp_id": "exp-einter", "kind": "layered_tensile"},
            "hash789",
        )
        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id=placeholder_id).one()
        payload = row.metadata_json["deferred_submission"]
        assert "interaction_analysis" not in payload
