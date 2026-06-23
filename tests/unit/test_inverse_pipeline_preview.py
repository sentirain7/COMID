"""역설계 파이프라인 preview_plan dry-run 테스트 (P1, 계획 §4.2 ①~③)."""

from types import SimpleNamespace

import pytest

from api.schemas import InverseDesignRequest
from api.schemas.recommendations import (
    AggregateSpecRequest,
    PropertyTargetItem,
)
from contracts.errors import ContractError
from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    PipelineMode,
    PlannedExperimentKind,
)
from features.inverse_design_pipeline import queries, service
from features.inverse_design_pipeline.service import (
    compute_plan_hash,
    decide_pipeline_mode,
    preview_plan,
)

_SARA = ("asphaltene", "resin", "aromatic", "saturate")
_SESSION = object()  # 쿼리 함수를 monkeypatch하므로 실제 session 불필요


def _request(metrics: list[str], **kwargs) -> InverseDesignRequest:
    return InverseDesignRequest(
        custom_targets=[PropertyTargetItem(metric_name=m, target_min=0.1) for m in metrics],
        **kwargs,
    )


@pytest.fixture
def bootstrap_env(monkeypatch):
    """champion 부재 + 라벨 0 + 유사실험 없음 → BOOTSTRAP 환경."""
    monkeypatch.setattr(service, "_get_capability_manifest", lambda: None)
    monkeypatch.setattr(queries, "count_training_labels", lambda s, m: 0)
    monkeypatch.setattr(queries, "find_experiments_by_composition", lambda *a, **k: [])


class TestDecidePipelineMode:
    def test_no_manifest_is_bootstrap(self):
        mode, rationale = decide_pipeline_mode(
            ["density"], capability_manifest=None, label_counts={"density": 100}
        )
        assert mode == PipelineMode.BOOTSTRAP
        assert rationale["champion_available"] is False

    def test_unsupported_target_is_bootstrap(self):
        mode, rationale = decide_pipeline_mode(
            ["density", "work_of_separation"],
            capability_manifest={"supported_targets": ["density"]},
            label_counts={"density": 100, "work_of_separation": 100},
        )
        assert mode == PipelineMode.BOOTSTRAP
        assert rationale["unsupported_targets"] == ["work_of_separation"]

    def test_label_starved_is_bootstrap(self):
        n_min = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.n_min_labels
        mode, rationale = decide_pipeline_mode(
            ["density"],
            capability_manifest={"supported_targets": ["density"]},
            label_counts={"density": n_min - 1},
        )
        assert mode == PipelineMode.BOOTSTRAP
        assert rationale["label_starved_targets"] == ["density"]

    def test_supported_and_labeled_is_bo(self):
        n_min = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.n_min_labels
        mode, rationale = decide_pipeline_mode(
            ["density"],
            capability_manifest={"supported_targets": ["density"]},
            label_counts={"density": n_min},
        )
        assert mode == PipelineMode.BO
        assert rationale["unsupported_targets"] == []
        assert rationale["label_starved_targets"] == []

    def test_label_counts_unavailable_is_bootstrap(self):
        mode, rationale = decide_pipeline_mode(
            ["density"],
            capability_manifest={"supported_targets": ["density"]},
            label_counts={"density": 100},
            label_counts_available=False,
        )
        assert mode == PipelineMode.BOOTSTRAP
        assert rationale["label_counts_available"] is False


@pytest.mark.asyncio
class TestBootstrapPreview:
    async def test_basic_bulk_target(self, bootstrap_env):
        result = await preview_plan(_request(["density"]), session=_SESSION)
        plan = result["plan"]

        assert plan["mode"] == "bootstrap"
        # 무첨가 요청의 조합 풀 = 정의 binder 3종(무첨가 control) — batch_size보다
        # 작으면 풀 전체가 후보가 된다
        pool = len(DEFAULT_INVERSE_PIPELINE_POLICY.candidate_binder_types)
        batch = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.seed_batch_size
        expected = min(batch, pool)
        assert len(plan["candidates"]) == expected
        binder_types = set()
        for cand in plan["candidates"]:
            assert cand["source"] == "bootstrap_seed"
            assert cand["binder_type"] in DEFAULT_INVERSE_PIPELINE_POLICY.candidate_binder_types
            assert cand["additive_type"] is None
            assert cand["additive_wt"] == 0.0
            binder_types.add(cand["binder_type"])
            comp = cand["composition"]
            assert set(_SARA) <= set(comp)
            assert sum(comp[c] for c in _SARA) == pytest.approx(100.0, abs=0.5)

        assert len(plan["experiments"]) == expected  # 후보당 binder cell 1개
        for exp in plan["experiments"]:
            assert exp["kind"] == PlannedExperimentKind.BINDER_CELL.value
            assert exp["temperature_k"] == DEFAULT_INVERSE_PIPELINE_POLICY.default_temperature_k
            assert exp["protocol_preset"] == "bulk"  # 점도 표적 없음 → bulk 체인
            assert exp["structure_size"] == "X1"  # 요청 미지정 → 기본 X1
            assert exp["action"] == "build"
        assert plan["design"]["feasibility"]["status"] == "unknown"

    async def test_explore_all_additives_fills_seed_batch(self, bootstrap_env):
        """첨가제 탐색 활성 시 조합 풀(binder × additive × grid)이 커져
        seed_batch_size만큼 후보가 채워진다."""
        result = await preview_plan(
            _request(["density"], explore_all_additives=True), session=_SESSION
        )
        plan = result["plan"]
        batch = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.seed_batch_size
        assert len(plan["candidates"]) == batch
        with_additive = [c for c in plan["candidates"] if c["additive_type"]]
        assert with_additive, "셔플된 시드 배치에 첨가제 조합이 포함되어야 한다"
        grid = set(DEFAULT_INVERSE_PIPELINE_POLICY.additive_wt_grid)
        for cand in with_additive:
            assert cand["additive_wt"] in grid
            assert cand["composition"]["additive"] == cand["additive_wt"]

    async def test_plan_hash_deterministic(self, bootstrap_env):
        r1 = await preview_plan(_request(["density"]), session=_SESSION)
        r2 = await preview_plan(_request(["density"]), session=_SESSION)
        assert r1["plan_hash"] == r2["plan_hash"]
        assert r1["plan_hash"] == compute_plan_hash(r1["plan"])

    async def test_tampered_plan_changes_hash(self, bootstrap_env):
        result = await preview_plan(_request(["density"]), session=_SESSION)
        tampered = dict(result["plan"])
        tampered["mode"] = "bo"
        assert compute_plan_hash(tampered) != result["plan_hash"]

    async def test_viscosity_selects_viscosity_protocol(self, bootstrap_env):
        # 점도 표적이면 NEMD 포함 viscosity 프로토콜을 '선택'(승급 아님)
        result = await preview_plan(_request(["viscosity"]), session=_SESSION)
        for exp in result["plan"]["experiments"]:
            assert exp["protocol_preset"] == "viscosity"

    async def test_structure_size_propagates_to_experiments(self, bootstrap_env):
        result = await preview_plan(_request(["density"], structure_size="X2"), session=_SESSION)
        for exp in result["plan"]["experiments"]:
            assert exp["structure_size"] == "X2"

    async def test_tg_plans_multi_temperature_sweep(self, bootstrap_env):
        result = await preview_plan(_request(["glass_transition_temperature_k"]), session=_SESSION)
        plan = result["plan"]
        sweep = DEFAULT_INVERSE_PIPELINE_POLICY.tg_temperature_sweep_k
        n_candidates = len(plan["candidates"])
        assert len(plan["experiments"]) == n_candidates * len(sweep)
        temps = {e["temperature_k"] for e in plan["experiments"] if e["candidate_index"] == 0}
        assert temps == set(sweep)

    async def test_mechanical_without_aggregate_specs_rejected(self, bootstrap_env):
        with pytest.raises(ContractError, match="aggregate_specs"):
            await preview_plan(_request(["work_of_separation"]), session=_SESSION)

    async def test_mechanical_plans_layered_with_replicates(self, bootstrap_env):
        request = _request(
            ["work_of_separation"],
            aggregate_specs=[AggregateSpecRequest(material="SiO2", surface="001")],
        )
        result = await preview_plan(request, session=_SESSION)
        experiments = result["plan"]["experiments"]

        layered = [
            e for e in experiments if e["kind"] == PlannedExperimentKind.LAYERED_TENSILE.value
        ]
        binders = {
            e["plan_exp_id"]: e
            for e in experiments
            if e["kind"] == PlannedExperimentKind.BINDER_CELL.value
        }
        assert len(layered) == len(result["plan"]["candidates"])
        for exp in layered:
            assert exp["tensile_enabled"] is True
            assert exp["replicate_seeds"] == 3  # work_of_separation min_replicate_count
            assert exp["action"] == "build"  # 계면 실험은 항상 신규 (§4.4-3)
            parent = binders[exp["depends_on"]]
            assert parent["candidate_index"] == exp["candidate_index"]
            assert parent["temperature_k"] == exp["temperature_k"]

    async def test_moisture_damage_plans_wet_pair(self, bootstrap_env):
        request = _request(
            ["work_of_separation"],
            aggregate_specs=[AggregateSpecRequest(material="SiO2", surface="001")],
        )
        result = await preview_plan(request, moisture_damage=True, session=_SESSION)
        plan = result["plan"]

        assert plan["moisture_damage"]["enabled"] is True
        policy = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        assert plan["moisture_damage"]["er_warn_threshold"] == policy.er_warn_threshold
        assert plan["moisture_damage"]["er_fail_threshold"] == policy.er_fail_threshold

        dry_ids = {
            e["plan_exp_id"]
            for e in plan["experiments"]
            if e["kind"] == PlannedExperimentKind.LAYERED_TENSILE.value
        }
        wet = [
            e
            for e in plan["experiments"]
            if e["kind"] == PlannedExperimentKind.WATER_INTERFACE_LAYERED.value
        ]
        assert len(wet) == len(dry_ids)
        for exp in wet:
            assert exp["dry_pair_id"] in dry_ids

    async def test_existing_binder_cell_reused(self, bootstrap_env, monkeypatch):
        monkeypatch.setattr(
            queries,
            "find_experiments_by_composition",
            lambda *a, **k: [SimpleNamespace(exp_id="prior_exp_001")],
        )
        result = await preview_plan(_request(["density"]), session=_SESSION)
        for exp in result["plan"]["experiments"]:
            assert exp["action"] == "reuse"
            assert exp["matched_exp_ids"] == ["prior_exp_001"]

    async def test_binder_types_restrict_candidates(self, bootstrap_env):
        """요청의 binder_types가 후보 풀을 제한한다 (SARA 탐색 폐기 후의 제약)."""
        request = _request(["density"], binder_types=["AAA1"])
        result = await preview_plan(request, session=_SESSION)
        candidates = result["plan"]["candidates"]
        assert candidates
        assert all(c["binder_type"] == "AAA1" for c in candidates)

    async def test_unknown_binder_type_rejected(self, bootstrap_env):
        with pytest.raises(ContractError, match="Unknown binder types"):
            await preview_plan(_request(["density"], binder_types=["NOPE"]), session=_SESSION)

    async def test_unmapped_namespace_rejected(self, bootstrap_env):
        with pytest.raises(ContractError, match="does not orchestrate"):
            await preview_plan(_request(["ghg_emission"]), session=_SESSION)

    async def test_unknown_metric_rejected(self, bootstrap_env):
        with pytest.raises(ContractError, match="Invalid targets"):
            await preview_plan(_request(["not_a_metric"]), session=_SESSION)


@pytest.fixture
def bo_env(monkeypatch):
    """champion 존재 + 라벨 충분 → BO 환경 (predictor는 결정적 mock)."""
    n_min = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.n_min_labels
    monkeypatch.setattr(
        service,
        "_get_capability_manifest",
        lambda: {"supported_targets": ["density", "work_of_separation"]},
    )
    monkeypatch.setattr(queries, "count_training_labels", lambda s, m: n_min + 10)
    monkeypatch.setattr(queries, "find_experiments_by_composition", lambda *a, **k: [])

    def fake_predictor(pred_input: dict):
        # AAA1(asphaltene 11.1)을 최저 거리로 만드는 결정적 가짜 예측:
        # density 목표(min 0.1)는 모두 만족, asphaltene이 낮을수록 1.0에 가까움
        return {
            "density": 1.0 + float(pred_input.get("asphaltene", 0.0)) / 100.0,
            "work_of_separation": 80.0,
        }

    # _load_predictor는 (feature_set, predictor_fn) 튜플 반환 — composition 경로
    monkeypatch.setattr(service, "_load_predictor", lambda: (None, fake_predictor))


@pytest.mark.asyncio
class TestBoPreview:
    async def test_bo_ranks_combination_pool_by_prediction(self, bo_env):
        """BO 모드: 조합 풀 전수를 champion 예측으로 랭킹해 상위 n_results 선택."""
        result = await preview_plan(_request(["density"], n_results=2), session=_SESSION)
        plan = result["plan"]

        assert plan["mode"] == "bo"
        assert len(plan["candidates"]) == 2
        for cand in plan["candidates"]:
            assert cand["source"] == "bo"
            assert cand["binder_type"] in DEFAULT_INVERSE_PIPELINE_POLICY.candidate_binder_types
            assert cand["predicted_properties"] is not None
            assert cand["targets_satisfied"] is True
            assert cand["target_distance"] is not None
        # 거리 오름차순 정렬 확인
        distances = [c["target_distance"] for c in plan["candidates"]]
        assert distances == sorted(distances)
        assert plan["design"]["audit_log"]["strategy"] == "binder_additive_grid_ranking"
        # BO 후보도 동일하게 실험 편성
        assert len(plan["experiments"]) == 2

    async def test_bo_candidates_plan_all_requested_aggregates(self, bo_env):
        """후보는 골재 무관 — 요청된 모든 골재에 layered를 편성한다."""
        request = _request(
            ["work_of_separation"],
            n_results=1,
            aggregate_specs=[
                AggregateSpecRequest(material="SiO2", surface="001"),
                AggregateSpecRequest(material="CaCO3", surface="104"),
            ],
        )
        result = await preview_plan(request, session=_SESSION)

        layered = [
            e
            for e in result["plan"]["experiments"]
            if e["kind"] == PlannedExperimentKind.LAYERED_TENSILE.value
        ]
        materials = {e["aggregate"]["material"] for e in layered}
        assert materials == {"SiO2", "CaCO3"}
