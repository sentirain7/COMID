"""수분손상 트랙 테스트 (P6, 계획 §2 — water 프로비저닝 + dry/wet 페어 + ER)."""

import pytest

from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    MoistureDamagePolicy,
)
from database.models import ExperimentModel, MetricModel
from features.inverse_design_pipeline import execution
from features.inverse_design_pipeline.members import PIPELINE_META_KEY
from features.inverse_design_pipeline.results import _compute_moisture_er, get_results


class TestMoisturePolicy:
    def test_water_provisioning_defaults(self):
        m = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        assert m.water_mol_id == "H2O"
        assert m.water_layer_thickness_angstrom > 0
        assert m.water_target_density > 0
        assert m.water_default_xy_angstrom > 0

    def test_thresholds_still_validated(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MoistureDamagePolicy(er_warn_threshold=0.6, er_fail_threshold=0.7)


class TestWaterDeferredPayload:
    def test_water_layer_marker_between_crystal_and_binder(self, isolated_db_session, monkeypatch):
        _seed_exp(isolated_db_session, "parent_w")

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)

        entry = {
            "plan_exp_id": "exp-003",
            "kind": "water_interface_layered",
            "aggregate": {"material": "SiO2", "surface": "001"},
            "temperature_k": 293.0,
            "tensile_enabled": True,
            "replicate_seeds": 3,
            "dry_pair_id": "exp-002",
        }
        placeholder_id = execution._create_layered_deferred(
            entry,
            {"composition": {}, "additive_type": None},
            "parent_w",
            {"id": "pl-wet-1", "plan_exp_id": "exp-003", "kind": "water_interface_layered"},
            "hash789",
            water=True,
        )

        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id=placeholder_id).one()
        layers = row.metadata_json["deferred_submission"]["layers"]
        assert [ld["source_type"] for ld in layers] == [
            "crystal_structure",
            "interface_molecule_cell",
            "binder_cell",
        ]
        water_layer = layers[1]
        moisture = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        assert water_layer["auto_water"]["mol_id"] == moisture.water_mol_id
        assert (
            water_layer["auto_water"]["thickness_angstrom"]
            == moisture.water_layer_thickness_angstrom
        )
        assert layers[2]["prereq_exp_id"] == "parent_w"

    def test_dry_variant_has_no_water_layer(self, isolated_db_session, monkeypatch):
        _seed_exp(isolated_db_session, "parent_d")

        def fake_commit(fn):
            fn(isolated_db_session)
            isolated_db_session.flush()

        monkeypatch.setattr("features.common.run_in_session_commit", fake_commit, raising=True)
        placeholder_id = execution._create_layered_deferred(
            {
                "plan_exp_id": "exp-002",
                "aggregate": {"material": "SiO2"},
                "temperature_k": 293.0,
                "tensile_enabled": True,
                "replicate_seeds": None,
            },
            {"composition": {}, "additive_type": None},
            "parent_d",
            {"id": "pl-dry-1", "plan_exp_id": "exp-002", "kind": "layered_tensile"},
            "hash790",
        )
        row = isolated_db_session.query(ExperimentModel).filter_by(exp_id=placeholder_id).one()
        layers = row.metadata_json["deferred_submission"]["layers"]
        assert [ld["source_type"] for ld in layers] == ["crystal_structure", "binder_cell"]


class TestSchedulerAutoWater:
    def test_auto_water_resolved_with_parent_box(self, isolated_db_session, monkeypatch):
        from orchestrator.dependency_scheduler import DependencyScheduler

        _seed_exp(isolated_db_session, "parent_box", box_lx=95.0, box_ly=96.0)

        provisioned = {}

        async def fake_ensure(lx, ly, *, mol_id, thickness_angstrom, target_density, seed=None):
            provisioned.update(
                {"lx": lx, "ly": ly, "mol_id": mol_id, "thickness": thickness_angstrom}
            )
            return "ifc_water01"

        captured = {}

        class _Resp:
            exp_id = "lay-wet-real"

        async def fake_submit(request):
            captured["request"] = request
            return _Resp()

        monkeypatch.setattr(
            "features.layered_structures.water_provisioning.ensure_water_interface_cell",
            fake_ensure,
        )
        monkeypatch.setattr(
            "features.layered_structures.service.submit_layered_replicates", fake_submit
        )
        monkeypatch.setattr(
            "features.layered_structures.service.submit_layered_structure", fake_submit
        )

        scheduler = DependencyScheduler(job_manager=None)
        payload = {
            "kind": "layered",
            "layers": [
                {"source_type": "crystal_structure", "auto_match_material": "SiO2"},
                {
                    "source_type": "interface_molecule_cell",
                    "auto_water": {
                        "mol_id": "H2O",
                        "thickness_angstrom": 10.0,
                        "target_density": 1.0,
                        "default_xy_angstrom": 40.0,
                    },
                },
                {"source_type": "binder_cell", "prereq_exp_id": "parent_box"},
            ],
            "temperature_K": 293.0,
            "tensile_enabled": True,
        }
        exp_id = scheduler._submit_layered_deferred(
            None, payload, isolated_db_session, "parent_box"
        )

        assert exp_id == "lay-wet-real"
        # parent box XY로 프로비저닝
        assert provisioned == {"lx": 95.0, "ly": 96.0, "mol_id": "H2O", "thickness": 10.0}
        request = captured["request"]
        assert request.layers[1].source_id == "ifc_water01"
        assert request.layers[2].source_id == "parent_box"

    def test_auto_water_falls_back_to_default_xy(self, isolated_db_session, monkeypatch):
        from orchestrator.dependency_scheduler import DependencyScheduler

        _seed_exp(isolated_db_session, "parent_nobox")  # box_lx/ly 없음

        provisioned = {}

        async def fake_ensure(lx, ly, **kwargs):
            provisioned.update({"lx": lx, "ly": ly})
            return "ifc_water02"

        class _Resp:
            exp_id = "lay-wet-real2"

        async def fake_submit(request):
            return _Resp()

        monkeypatch.setattr(
            "features.layered_structures.water_provisioning.ensure_water_interface_cell",
            fake_ensure,
        )
        monkeypatch.setattr(
            "features.layered_structures.service.submit_layered_structure", fake_submit
        )
        monkeypatch.setattr(
            "features.layered_structures.service.submit_layered_replicates", fake_submit
        )

        scheduler = DependencyScheduler(job_manager=None)
        payload = {
            "kind": "layered",
            "layers": [
                {"source_type": "crystal_structure", "auto_match_material": "SiO2"},
                {
                    "source_type": "interface_molecule_cell",
                    "auto_water": {"mol_id": "H2O", "default_xy_angstrom": 37.5},
                },
                {"source_type": "binder_cell", "prereq_exp_id": "parent_nobox"},
            ],
        }
        scheduler._submit_layered_deferred(None, payload, isolated_db_session, "parent_nobox")
        assert provisioned == {"lx": 37.5, "ly": 37.5}


class TestMoistureER:
    def test_er_verdicts(self):
        policy = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        dry = {"work_of_separation": {"value": 100.0}}

        ok = _compute_moisture_er(dry, {"work_of_separation": {"value": 90.0}}, policy)
        assert ok["work_of_separation"]["verdict"] == "ok"
        assert ok["work_of_separation"]["er"] == pytest.approx(0.9)

        warn = _compute_moisture_er(dry, {"work_of_separation": {"value": 75.0}}, policy)
        assert warn["work_of_separation"]["verdict"] == "warn"

        fail = _compute_moisture_er(dry, {"work_of_separation": {"value": 60.0}}, policy)
        assert fail["work_of_separation"]["verdict"] == "fail"

    def test_er_requires_both_values(self):
        policy = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        assert _compute_moisture_er({}, {"x": {"value": 1.0}}, policy) is None
        assert _compute_moisture_er({"x": {"value": 0.0}}, {"x": {"value": 1.0}}, policy) is None

    def test_get_results_attaches_moisture_er(self, isolated_db_session):
        pid = "pl-er-1"
        targets = [
            {
                "metric_name": "work_of_separation",
                "target_min": 50.0,
                "target_max": None,
                "direction": "maximize",
                "weight": 1.0,
            }
        ]
        _seed_member(
            isolated_db_session,
            pid,
            "dry1",
            kind="layered_tensile",
            targets=targets,
            metrics={"work_of_separation": 100.0},
        )
        _seed_member(
            isolated_db_session,
            pid,
            "wet1",
            kind="water_interface_layered",
            targets=targets,
            metrics={"work_of_separation": 72.0},
        )

        results = get_results(pid, session=isolated_db_session)
        candidate = results["candidates"][0]
        # dry 값이 본 결과표 (wet이 덮어쓰지 않음)
        assert candidate["per_target"]["work_of_separation"]["value"] == 100.0
        er = candidate["moisture_er"]["work_of_separation"]
        assert er["er"] == pytest.approx(0.72)
        assert er["verdict"] == "warn"
        assert er["dry"] == 100.0
        assert er["wet"] == 72.0

    def test_get_results_no_wet_no_moisture_block(self, isolated_db_session):
        pid = "pl-er-2"
        _seed_member(
            isolated_db_session,
            pid,
            "dry2",
            kind="layered_tensile",
            targets=[],
            metrics={"work_of_separation": 90.0},
        )
        results = get_results(pid, session=isolated_db_session)
        assert results["candidates"][0]["moisture_er"] is None


# ──────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────


def _seed_exp(session, exp_id, *, box_lx=None, box_ly=None, metadata=None):
    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="completed",
        comp_asphaltene_wt=15.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=20.0,
        temperature_K=293.0,
        box_lx=box_lx,
        box_ly=box_ly,
        metadata_json=metadata,
    )
    session.add(exp)
    session.flush()
    return exp


def _seed_member(session, pipeline_id, exp_id, *, kind, targets, metrics):
    exp = _seed_exp(
        session,
        exp_id,
        metadata={
            PIPELINE_META_KEY: {
                "id": pipeline_id,
                "plan_exp_id": f"plan-{exp_id}",
                "kind": kind,
                "candidate_index": 0,
                "targets": targets,
            }
        },
    )
    for name, value in metrics.items():
        session.add(
            MetricModel(
                experiment_id=exp.id,
                exp_id=exp_id,
                metric_name=name,
                namespace="mechanical",
                value=value,
                unit="mJ/m^2",
            )
        )
    session.flush()


class TestPrimaryTemperatureSelection:
    """R-P1-1: 다온도 세트에서 스칼라 지표는 primary 온도 값이 보고돼야 한다."""

    def _seed_binder(self, session, pid, exp_id, *, temp_k, density, targets):
        exp = ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="completed",
            comp_asphaltene_wt=15.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=20.0,
            temperature_K=temp_k,
            metadata_json={
                PIPELINE_META_KEY: {
                    "id": pid,
                    "plan_exp_id": f"plan-{exp_id}",
                    "kind": "binder_cell",
                    "candidate_index": 0,
                    "targets": targets,
                    "primary_temperature_k": 293.0,
                }
            },
        )
        session.add(exp)
        session.flush()
        session.add(
            MetricModel(
                experiment_id=exp.id,
                exp_id=exp_id,
                metric_name="density",
                namespace="bulk_ff",
                value=density,
                unit="g/cm3",
            )
        )
        session.flush()

    def test_primary_temperature_density_wins(self, isolated_db_session):
        pid = "pl-multi-t"
        targets = [
            {
                "metric_name": "density",
                "target_min": 1.0,
                "target_max": None,
                "direction": "maximize",
                "weight": 1.0,
            }
        ]
        # 393K(고온, 낮은 밀도) 실험이 나중 id — 종전 last-wins라면 이 값이 보고됨
        self._seed_binder(
            isolated_db_session, pid, "b293", temp_k=293.0, density=1.02, targets=targets
        )
        self._seed_binder(
            isolated_db_session, pid, "b393", temp_k=393.0, density=0.95, targets=targets
        )

        results = get_results(pid, session=isolated_db_session)
        per_target = results["candidates"][0]["per_target"]["density"]
        assert per_target["value"] == 1.02  # primary(293K) 값
        assert per_target["satisfied"] is True
        assert results["candidates"][0]["metrics"]["density"]["exp_id"] == "b293"

    def test_legacy_members_without_primary_fall_back(self, isolated_db_session):
        """primary 정보가 없는 레거시 멤버는 기존 동작(최신 row 우선) 폴백."""
        pid = "pl-legacy-t"
        exp = ExperimentModel(
            exp_id="legacy1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="completed",
            comp_asphaltene_wt=15.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=20.0,
            temperature_K=293.0,
            metadata_json={
                PIPELINE_META_KEY: {
                    "id": pid,
                    "plan_exp_id": "plan-legacy1",
                    "kind": "binder_cell",
                    "candidate_index": 0,
                    "targets": [],
                }
            },
        )
        isolated_db_session.add(exp)
        isolated_db_session.flush()
        results = get_results(pid, session=isolated_db_session)
        assert results["candidates"][0]["targets_satisfied"] is None
