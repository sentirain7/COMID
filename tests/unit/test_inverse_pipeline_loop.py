"""닫힌 루프 run_loop_round 테스트 (P7, 계획 §7 / DECISION_RULES R8)."""

import pytest

from contracts.errors import ContractError
from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    ClosedLoopPolicy,
)
from database.models import ExperimentModel, MetricModel
from features.inverse_design_pipeline import loop as loop_module
from features.inverse_design_pipeline.execution import PIPELINE_META_KEY
from features.inverse_design_pipeline.loop import run_loop_round
from features.inverse_design_pipeline.service import compute_plan_hash

_TARGETS = [
    {
        "metric_name": "density",
        "target_min": 1.0,
        "target_max": None,
        "direction": "maximize",
        "weight": 1.0,
        "unit": "g/cm3",
    }
]


def _policy(**loop_overrides):
    closed = ClosedLoopPolicy(enabled=True, **loop_overrides)
    return DEFAULT_INVERSE_PIPELINE_POLICY.model_copy(update={"closed_loop": closed})


def _plan(targets=_TARGETS):
    plan = {
        "plan_schema_version": "1",
        "mode": "bootstrap",
        "targets": targets,
        "candidates": [
            {"composition": {"asphaltene": 15.0, "resin": 30.0, "aromatic": 35.0, "saturate": 20.0}}
        ],
        "experiments": [{"plan_exp_id": "exp-001", "kind": "binder_cell", "candidate_index": 0}],
        "request_echo": {
            "custom_targets": [
                {"metric_name": "density", "target_min": 1.0, "direction": "maximize"}
            ],
            "temperature_k_fixed": 293.0,
        },
        "policy_snapshot": {},
    }
    return plan, compute_plan_hash(plan)


def _seed_member(
    session,
    pipeline_id,
    exp_id,
    *,
    status="completed",
    value=None,
    targets=_TARGETS,
    loop_block=None,
):
    pipe = {
        "id": pipeline_id,
        "plan_exp_id": f"plan-{exp_id}",
        "kind": "binder_cell",
        "candidate_index": 0,
        "targets": targets,
    }
    if loop_block:
        pipe["loop"] = loop_block
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
        metadata_json={PIPELINE_META_KEY: pipe},
    )
    session.add(exp)
    session.flush()
    if value is not None:
        session.add(
            MetricModel(
                experiment_id=exp.id,
                exp_id=exp_id,
                metric_name="density",
                namespace="bulk_ff",
                value=value,
                unit="g/cm3",
            )
        )
        session.flush()


class TestLoopGuards:
    @pytest.mark.asyncio
    async def test_disabled_policy_rejected(self, isolated_db_session):
        plan, plan_hash = _plan()
        with pytest.raises(ContractError, match="disabled"):
            await run_loop_round(
                plan, plan_hash, f"pl-{plan_hash}-aaaa", session=isolated_db_session
            )  # 기본 정책 OFF

    @pytest.mark.asyncio
    async def test_hash_mismatch_rejected(self, isolated_db_session):
        plan, plan_hash = _plan()
        with pytest.raises(ContractError, match="plan_hash mismatch"):
            await run_loop_round(
                {**plan, "mode": "bo"},
                plan_hash,
                f"pl-{plan_hash}-aaaa",
                policy=_policy(),
                session=isolated_db_session,
            )

    @pytest.mark.asyncio
    async def test_foreign_pipeline_rejected(self, isolated_db_session):
        plan, plan_hash = _plan()
        with pytest.raises(ContractError, match="does not belong"):
            await run_loop_round(
                plan, plan_hash, "pl-otherhash-aaaa", policy=_policy(), session=isolated_db_session
            )

    @pytest.mark.asyncio
    async def test_incomplete_round_rejected(self, isolated_db_session):
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-r1"
        _seed_member(isolated_db_session, pid, "b1", status="running")
        with pytest.raises(ContractError, match="not finished"):
            await run_loop_round(
                plan, plan_hash, pid, policy=_policy(), session=isolated_db_session
            )

    @pytest.mark.asyncio
    async def test_unknown_pipeline_rejected(self, isolated_db_session):
        plan, plan_hash = _plan()
        with pytest.raises(ContractError, match="Unknown pipeline"):
            await run_loop_round(
                plan,
                plan_hash,
                f"pl-{plan_hash}-none",
                policy=_policy(),
                session=isolated_db_session,
            )


class TestLoopDecisions:
    @pytest.mark.asyncio
    async def test_stop_when_target_met(self, isolated_db_session):
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-r1"
        _seed_member(isolated_db_session, pid, "b1", value=1.05)  # ≥1.0 충족

        result = await run_loop_round(
            plan, plan_hash, pid, policy=_policy(), session=isolated_db_session
        )
        assert result["decision"] == "stop_target_met"
        assert result["next"] is None
        assert result["diagnostics"]["any_satisfied"] is True
        assert result["audit"]["round"] == 1

    @pytest.mark.asyncio
    async def test_stop_max_rounds(self, isolated_db_session):
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-r5"
        _seed_member(
            isolated_db_session,
            pid,
            "b1",
            value=0.90,
            loop_block={"chain_id": "pl-c", "round": 5, "chain_experiments_total": 5},
        )
        result = await run_loop_round(
            plan, plan_hash, pid, policy=_policy(max_rounds=5), session=isolated_db_session
        )
        assert result["decision"] == "stop_max_rounds"

    @pytest.mark.asyncio
    async def test_stop_budget_experiments(self, isolated_db_session):
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-rb"
        _seed_member(
            isolated_db_session,
            pid,
            "b1",
            value=0.90,
            loop_block={"chain_id": "pl-c", "round": 2, "chain_experiments_total": 60},
        )
        result = await run_loop_round(
            plan,
            plan_hash,
            pid,
            policy=_policy(max_total_experiments=60),
            session=isolated_db_session,
        )
        assert result["decision"] == "stop_budget_experiments"

    @pytest.mark.asyncio
    async def test_stop_no_improvement_counts_se_threshold(self, isolated_db_session):
        """개선 폭이 SE 임계 이하 → 무개선 누적 → 정지."""
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-rn"
        _seed_member(
            isolated_db_session,
            pid,
            "b1",
            value=0.90,
            loop_block={
                "chain_id": "pl-c",
                "round": 2,
                "chain_experiments_total": 2,
                "prev_best_distance": 0.05,  # 현재 best 0.10 → 악화(개선≤임계)
                "no_improve_count": 1,
            },
        )
        result = await run_loop_round(
            plan,
            plan_hash,
            pid,
            policy=_policy(stop_no_improve_rounds=2),
            session=isolated_db_session,
        )
        assert result["decision"] == "stop_no_improvement"
        assert result["audit"]["no_improve_count"] == 2

    @pytest.mark.asyncio
    async def test_continue_launches_next_round(self, isolated_db_session, monkeypatch):
        plan, plan_hash = _plan()
        pid = f"pl-{plan_hash}-r1"
        _seed_member(isolated_db_session, pid, "b1", value=0.90)  # 미충족 → 계속

        ingested = []
        monkeypatch.setattr(
            loop_module, "_ingest_round_results", lambda p, r: ingested.append(True)
        )

        next_plan = {"experiments": [{"plan_exp_id": "exp-101"}] * 4, "request_echo": {}}

        async def fake_preview(request, *, moisture_damage=False, policy=None):
            return {"plan": next_plan, "plan_hash": "nexthash"}

        approved = {}

        def fake_approve(p, h, *, policy=None, loop_block=None):
            approved.update({"plan": p, "hash": h, "loop_block": loop_block})
            return {
                "pipeline_id": f"pl-{h}-next",
                "members": [],
                "counts": {},
                "mode": "bo",
                "plan_hash": h,
            }

        import features.inverse_design_pipeline.service as service_module

        monkeypatch.setattr(service_module, "preview_plan", fake_preview)
        monkeypatch.setattr(loop_module, "approve_and_run", fake_approve)

        result = await run_loop_round(
            plan, plan_hash, pid, policy=_policy(), session=isolated_db_session
        )

        assert result["decision"] == "continue"
        assert ingested  # 재학습 advisory 호출됨
        nxt = result["next"]
        assert nxt["pipeline_id"] == "pl-nexthash-next"
        block = approved["loop_block"]
        assert block["round"] == 2
        assert block["prev_pipeline_id"] == pid
        assert block["chain_experiments_total"] == 1 + 4  # 기존 1 + 새 배치 4
        assert block["prev_best_distance"] == result["audit"]["best_distance"]


class TestLoopMoistureRestore:
    """R-P1-6: 라운드 2+에서 moisture 플래그는 plan 문서에서 복원돼야 한다."""

    @pytest.mark.asyncio
    async def test_continue_preserves_moisture_flag(self, isolated_db_session, monkeypatch):
        plan, plan_hash = _plan()
        plan = dict(plan)
        # 서비스 레벨 InverseDesignRequest 경로 시뮬레이션: request_echo에는
        # moisture_damage가 없고 plan 문서에만 enabled=True가 있다.
        plan["moisture_damage"] = {"enabled": True, "er_warn_threshold": 0.8}
        plan_hash = compute_plan_hash(plan)
        pid = f"pl-{plan_hash}-rm"
        _seed_member(isolated_db_session, pid, "b1", value=0.90)

        monkeypatch.setattr(loop_module, "_ingest_round_results", lambda p, r: None)
        captured = {}

        async def fake_preview(request, *, moisture_damage=False, policy=None):
            captured["moisture_damage"] = moisture_damage
            return {"plan": {"experiments": [], "request_echo": {}}, "plan_hash": "nh"}

        import features.inverse_design_pipeline.service as service_module

        monkeypatch.setattr(service_module, "preview_plan", fake_preview)
        monkeypatch.setattr(
            loop_module,
            "approve_and_run",
            lambda p, h, *, policy=None, loop_block=None: {
                "pipeline_id": f"pl-{h}-x",
                "members": [],
                "counts": {},
                "mode": "bo",
                "plan_hash": h,
            },
        )

        result = await run_loop_round(
            plan, plan_hash, pid, policy=_policy(), session=isolated_db_session
        )
        assert result["decision"] == "continue"
        assert captured["moisture_damage"] is True
