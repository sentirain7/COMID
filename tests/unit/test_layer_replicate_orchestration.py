"""계면 replica group 오케스트레이션 + ensemble 자동 persist 테스트 (보완 #4 후속).

- tag_replicate_group: 구성원 metadata에 group 정보 태깅
- persist_replicate_ensemble: 모든 replica 종료 시 mean±SE ensemble을 primary에 보존
- submit_layered_replicates: replicate_seeds에 따른 단일/그룹 디스패치
"""

import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "src")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY  # noqa: E402
from database.models import Base, ExperimentModel, MetricModel  # noqa: E402
from features.layered_structures.replicate_orchestration import (  # noqa: E402
    REPLICATE_ENSEMBLE_KEY,
    REPLICATE_GROUP_KEY,
    persist_replicate_ensemble,
    tag_replicate_group,
)


def _exp(exp_id, status="completed", metadata=None):
    return ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status=status,
        temperature_K=298.0,
        comp_asphaltene_wt=18.0,
        comp_resin_wt=32.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        metadata_json=metadata or {},
    )


def _metric(exp_id, name, value, iface=0):
    return MetricModel(
        exp_id=exp_id,
        metric_name=name,
        namespace=DEFAULT_METRICS_REGISTRY.get_namespace(name).value,
        value=value,
        unit=DEFAULT_METRICS_REGISTRY.get_unit(name),
        interface_index=iface,
    )


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _patch_session(session):
    """Patch features.common read/commit helpers onto the given session."""

    def fake_run(fn):
        return fn(session)

    def fake_commit(fn):
        out = fn(session)
        session.commit()
        return out

    return (
        patch("features.common.run_in_session", side_effect=fake_run),
        patch("features.common.run_in_session_commit", side_effect=fake_commit),
    )


class TestTagReplicateGroup:
    def test_tags_all_members(self, session):
        session.add_all([_exp("e0", metadata={}), _exp("e1"), _exp("e2")])
        session.commit()
        p_run, p_commit = _patch_session(session)
        with p_run, p_commit:
            tag_replicate_group(["e0", "e1", "e2"], "rgrp_x")

        rows = {r.exp_id: r for r in session.query(ExperimentModel).all()}
        for eid in ("e0", "e1", "e2"):
            grp = rows[eid].metadata_json[REPLICATE_GROUP_KEY]
            assert grp["group_id"] == "rgrp_x"
            assert grp["primary_exp_id"] == "e0"
            assert grp["sibling_exp_ids"] == ["e0", "e1", "e2"]
        assert rows["e0"].metadata_json[REPLICATE_GROUP_KEY]["role"] == "primary"
        assert rows["e1"].metadata_json[REPLICATE_GROUP_KEY]["role"] == "replica"


class TestPersistReplicateEnsemble:
    def _seed_group(self, session, statuses):
        group = {
            "group_id": "rgrp_y",
            "primary_exp_id": "e0",
            "sibling_exp_ids": ["e0", "e1", "e2"],
            "role": "replica",
        }
        for i, st in enumerate(statuses):
            meta = {REPLICATE_GROUP_KEY: {**group, "role": "primary" if i == 0 else "replica"}}
            session.add(_exp(f"e{i}", status=st, metadata=meta))
        # work_of_separation values 20/24/28 → mean 24
        for i, v in enumerate((20.0, 24.0, 28.0)):
            session.add(_metric(f"e{i}", "work_of_separation", v))
        session.commit()

    def test_not_a_group_returns_none(self, session):
        session.add(_exp("solo", metadata={}))
        session.commit()
        p_run, p_commit = _patch_session(session)
        with p_run, p_commit:
            assert persist_replicate_ensemble("solo") is None

    def test_waits_when_sibling_not_terminal(self, session):
        self._seed_group(session, ["completed", "running", "completed"])
        p_run, p_commit = _patch_session(session)
        with p_run, p_commit:
            assert persist_replicate_ensemble("e0") is None
        # primary must not have an ensemble yet
        primary = session.query(ExperimentModel).filter_by(exp_id="e0").first()
        assert REPLICATE_ENSEMBLE_KEY not in (primary.metadata_json or {})

    def test_aggregates_when_all_terminal(self, session):
        self._seed_group(session, ["completed", "completed", "completed"])
        p_run, p_commit = _patch_session(session)
        with p_run, p_commit:
            out = persist_replicate_ensemble("e2")
        assert out is not None
        assert out["n_completed"] == 3
        wos = next(m for m in out["metrics"] if m["metric_name"] == "work_of_separation")
        assert abs(wos["mean"] - 24.0) < 1e-9
        assert wos["meets_min_replicates"] is True
        # persisted on the primary (e0), not the triggering exp (e2)
        primary = session.query(ExperimentModel).filter_by(exp_id="e0").first()
        assert primary.metadata_json[REPLICATE_ENSEMBLE_KEY]["group_id"] == "rgrp_y"

    def test_uses_only_completed_when_some_failed(self, session):
        self._seed_group(session, ["completed", "failed", "completed"])
        p_run, p_commit = _patch_session(session)
        with p_run, p_commit:
            out = persist_replicate_ensemble("e1")
        assert out is not None
        # only e0(20) and e2(28) completed → mean 24, n_completed 2
        assert out["n_completed"] == 2
        wos = next(m for m in out["metrics"] if m["metric_name"] == "work_of_separation")
        assert abs(wos["mean"] - 24.0) < 1e-9
        assert wos["n_replicates"] == 2


def _layer_request(**kw):
    from api.schemas.structures import LayeredStructureSubmitRequest, LayerStackItemRequest

    return LayeredStructureSubmitRequest(
        layers=[
            LayerStackItemRequest(source_type="crystal_structure", source_id="c1"),
            LayerStackItemRequest(source_type="binder_cell", source_id="b1"),
        ],
        temperature_K=298.0,
        **kw,
    )


class TestSubmitDispatch:
    @pytest.mark.asyncio
    async def test_single_when_no_replicate_seeds(self):
        from api.schemas.structures import LayeredStructureSubmitResponse
        from features.layered_structures import service

        req = _layer_request()
        fake = AsyncMock(
            return_value=LayeredStructureSubmitResponse(exp_id="x", job_id="j", status="queued")
        )
        with patch.object(service, "submit_layered_structure", fake):
            resp = await service.submit_layered_replicates(req)
        assert fake.await_count == 1
        assert resp.replicate_group_id is None

    @pytest.mark.asyncio
    async def test_single_when_one_seed(self):
        from api.schemas.structures import LayeredStructureSubmitResponse
        from features.layered_structures import service

        req = _layer_request(replicate_seeds=[7])
        fake = AsyncMock(
            return_value=LayeredStructureSubmitResponse(exp_id="x", job_id="j", status="queued")
        )
        with patch.object(service, "submit_layered_structure", fake):
            await service.submit_layered_replicates(req)
        assert fake.await_count == 1
        # the single submit should receive seed=7 and replicate_seeds cleared
        passed = fake.await_args.args[0]
        assert passed.seed == 7
        assert passed.replicate_seeds is None

    @pytest.mark.asyncio
    async def test_group_when_multiple_seeds(self):
        from api.schemas.structures import LayeredStructureSubmitResponse
        from features.layered_structures import service

        req = _layer_request(replicate_seeds=[11, 22, 33])

        async def fake_submit(r):
            return LayeredStructureSubmitResponse(
                exp_id=f"exp_{r.seed}", job_id=f"job_{r.seed}", status="queued"
            )

        with (
            patch.object(service, "submit_layered_structure", side_effect=fake_submit),
            patch(
                "features.layered_structures.replicate_orchestration.tag_replicate_group"
            ) as mock_tag,
        ):
            resp = await service.submit_layered_replicates(req)

        assert resp.replicate_group_id is not None
        assert resp.replicate_exp_ids == ["exp_11", "exp_22", "exp_33"]
        assert resp.exp_id == "exp_11"
        mock_tag.assert_called_once_with(["exp_11", "exp_22", "exp_33"], resp.replicate_group_id)

    @pytest.mark.asyncio
    async def test_partial_failure_cancels_submitted_and_raises(self):
        # P1-2: 2번째 seed 제출 실패 → 1번째 보상 취소 + ContractError(detail에 취소 id).
        from api.schemas.structures import LayeredStructureSubmitResponse
        from contracts.errors import ContractError
        from features.layered_structures import service

        req = _layer_request(replicate_seeds=[11, 22, 33])

        async def fake_submit(r):
            if r.seed == 22:
                raise ContractError(ErrorCode_INVALID(), "boom", {})
            return LayeredStructureSubmitResponse(
                exp_id=f"exp_{r.seed}", job_id=f"job_{r.seed}", status="queued"
            )

        cancelled = []

        async def fake_cancel(exp_ids):
            cancelled.extend(exp_ids)

        with (
            patch.object(service, "submit_layered_structure", side_effect=fake_submit),
            patch.object(service, "_cancel_submitted_replicas", side_effect=fake_cancel),
        ):
            try:
                await service.submit_layered_replicates(req)
                raise AssertionError("expected ContractError")
            except ContractError as exc:
                assert exc.details.get("replicate_seed_failed") == 22
                assert exc.details.get("replicate_cancelled_exp_ids") == ["exp_11"]
        assert cancelled == ["exp_11"]

    @pytest.mark.asyncio
    async def test_tag_failure_returns_ungrouped_success(self):
        # P1-2: 태깅 실패는 응답을 죽이지 않는다 — group 없이 성공 응답.
        from api.schemas.structures import LayeredStructureSubmitResponse
        from features.layered_structures import service

        req = _layer_request(replicate_seeds=[11, 22])

        async def fake_submit(r):
            return LayeredStructureSubmitResponse(
                exp_id=f"exp_{r.seed}", job_id=f"job_{r.seed}", status="queued"
            )

        with (
            patch.object(service, "submit_layered_structure", side_effect=fake_submit),
            patch(
                "features.layered_structures.replicate_orchestration.tag_replicate_group",
                side_effect=RuntimeError("db down"),
            ),
        ):
            resp = await service.submit_layered_replicates(req)
        assert resp.exp_id == "exp_11"
        assert resp.replicate_group_id is None


def ErrorCode_INVALID():
    from contracts.errors import ErrorCode

    return ErrorCode.INVALID_REQUEST
