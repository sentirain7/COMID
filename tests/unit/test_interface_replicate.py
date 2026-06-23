"""계면 mechanical 지표 replica 앙상블 집계 테스트 (보완 #4, 원칙 9 연계).

work_of_separation·interfacial_tensile_strength 가 다중 seed/변형률 replica로
mean ± SE ensemble 로 집계되고, 레지스트리 SSOT(requires_replicates/
min_replicate_count)가 이를 강제하는지 검증한다.
"""

import math
import sys

sys.path.insert(0, "src")

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY  # noqa: E402
from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY  # noqa: E402
from contracts.schemas import MetricResult  # noqa: E402
from metrics.interface_replicate import (  # noqa: E402
    ReplicateMetricResult,
    aggregate_interface_metric,
    aggregate_interface_replicates,
)


class TestRegistrySSOT:
    def test_interface_targets_require_replicates(self):
        reg = DEFAULT_METRICS_REGISTRY
        assert reg.requires_replicates("work_of_separation") is True
        assert reg.requires_replicates("interfacial_tensile_strength") is True
        # min_replicate_count mirrors ReplicatePolicy.min_seeds.
        assert reg.min_replicate_count("work_of_separation") == DEFAULT_REPLICATE_POLICY.min_seeds

    def test_replica_required_metrics_listed(self):
        names = set(DEFAULT_METRICS_REGISTRY.replica_required_metrics())
        assert {"work_of_separation", "interfacial_tensile_strength"} <= names

    def test_bulk_metric_not_replica_required(self):
        # density 등 bulk 지표는 영향 없음(opt-in 유지).
        assert DEFAULT_METRICS_REGISTRY.requires_replicates("density") is False


class TestAggregateInterfaceMetric:
    def test_mean_and_se(self):
        res = aggregate_interface_metric(
            "interfacial_tensile_strength", [10.0, 12.0, 14.0], interface_index=0
        )
        assert isinstance(res, ReplicateMetricResult)
        assert res.n_replicates == 3
        assert abs(res.aggregate.mean - 12.0) < 1e-9
        # std (ddof=1) = 2.0, SE = 2/sqrt(3)
        assert abs(res.aggregate.std - 2.0) < 1e-9
        assert abs(res.aggregate.standard_error - 2.0 / math.sqrt(3)) < 1e-9
        assert res.meets_min_replicates is True  # 3 >= min_seeds(3)

    def test_single_replicate_is_valid_but_inadequate(self):
        res = aggregate_interface_metric("work_of_separation", [42.0])
        assert res.n_replicates == 1
        assert res.aggregate.mean == 42.0
        assert res.aggregate.standard_error == 0.0  # n=1 → SE undefined, reported 0
        assert res.meets_min_replicates is False  # 1 < 3

    def test_to_metric_result_value_is_mean_uncertainty_is_se(self):
        res = aggregate_interface_metric("work_of_separation", [20.0, 24.0, 28.0])
        mr = res.to_metric_result("exp_x", unit="mJ/m2")
        assert mr.metric_name == "work_of_separation"
        assert abs(mr.value - 24.0) < 1e-9
        assert abs(mr.uncertainty - res.aggregate.standard_error) < 1e-9
        assert mr.namespace == "mechanical"
        # 전체 통계는 array_summary(→ metadata_json)에 보존.
        assert mr.array_summary["ensemble"] is True
        assert mr.array_summary["n_replicates"] == 3
        assert mr.array_summary["meets_min_replicates"] is True

    def test_report_std_instead_of_se(self):
        res = aggregate_interface_metric("work_of_separation", [20.0, 24.0, 28.0])
        mr = res.to_metric_result("exp_x", unit="mJ/m2", report_standard_error=False)
        assert abs(mr.uncertainty - res.aggregate.std) < 1e-9

    def test_empty_values_raises(self):
        try:
            aggregate_interface_metric("work_of_separation", [])
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def _seed_metric(name: str, value: float, iface: int | None = None) -> MetricResult:
    ns = DEFAULT_METRICS_REGISTRY.get_namespace(name).value
    unit = DEFAULT_METRICS_REGISTRY.get_unit(name)
    return MetricResult(
        exp_id="e",
        metric_name=name,
        value=value,
        unit=unit,
        namespace=ns,
        interface_index=iface,
    )


class TestAggregateInterfaceReplicates:
    def test_groups_by_metric_and_interface(self):
        per_seed = [
            [
                _seed_metric("work_of_separation", 20.0, iface=0),
                _seed_metric("interfacial_tensile_strength", 5.0, iface=0),
            ],
            [
                _seed_metric("work_of_separation", 24.0, iface=0),
                _seed_metric("interfacial_tensile_strength", 7.0, iface=0),
            ],
            [
                _seed_metric("work_of_separation", 28.0, iface=0),
                _seed_metric("interfacial_tensile_strength", 9.0, iface=0),
            ],
        ]
        results = aggregate_interface_replicates(per_seed)
        by_name = {r.metric_name: r for r in results}
        assert set(by_name) == {"work_of_separation", "interfacial_tensile_strength"}
        assert abs(by_name["work_of_separation"].aggregate.mean - 24.0) < 1e-9
        assert abs(by_name["interfacial_tensile_strength"].aggregate.mean - 7.0) < 1e-9
        assert all(r.n_replicates == 3 for r in results)

    def test_separates_distinct_interfaces(self):
        per_seed = [
            _seed_metric("work_of_separation", 20.0, iface=0),
            _seed_metric("work_of_separation", 22.0, iface=0),
            _seed_metric("work_of_separation", 50.0, iface=1),
            _seed_metric("work_of_separation", 52.0, iface=1),
        ]
        results = aggregate_interface_replicates(per_seed)
        means = {r.interface_index: r.aggregate.mean for r in results}
        assert abs(means[0] - 21.0) < 1e-9
        assert abs(means[1] - 51.0) < 1e-9

    def test_non_replica_metric_ignored(self):
        # density(bulk)는 replica-필수 아님 → 집계 대상 제외(기본).
        per_seed = [
            _seed_metric("density", 1.0),
            _seed_metric("density", 2.0),
        ]
        results = aggregate_interface_replicates(per_seed)
        assert results == []

    def test_explicit_metric_names_override(self):
        per_seed = [
            _seed_metric("density", 1.0),
            _seed_metric("density", 3.0),
        ]
        results = aggregate_interface_replicates(per_seed, metric_names=["density"])
        assert len(results) == 1
        assert abs(results[0].aggregate.mean - 2.0) < 1e-9

    def test_skips_none_values(self):
        per_seed = [
            _seed_metric("work_of_separation", 20.0, iface=0),
            _seed_metric("work_of_separation", None, iface=0),
            _seed_metric("work_of_separation", 24.0, iface=0),
        ]
        results = aggregate_interface_replicates(per_seed)
        assert len(results) == 1
        assert results[0].n_replicates == 2
        assert abs(results[0].aggregate.mean - 22.0) < 1e-9


class TestAggregateLayeredReplicateMetricsDB:
    """DB-backed read path: replica exp_id 묶음 → ensemble (layered_analysis)."""

    def _seed(self, session, rows):
        from database.models import MetricModel

        for exp_id, name, value, iface in rows:
            session.add(
                MetricModel(
                    exp_id=exp_id,
                    metric_name=name,
                    namespace=DEFAULT_METRICS_REGISTRY.get_namespace(name).value,
                    value=value,
                    unit=DEFAULT_METRICS_REGISTRY.get_unit(name),
                    interface_index=iface,
                )
            )
        session.commit()

    def _call(self, session, exp_ids, **kwargs):
        from unittest.mock import patch

        from features.layered_structures.layered_analysis import (
            aggregate_layered_replicate_metrics,
        )

        def fake_run(fn):
            return fn(session)

        with patch("features.common.run_in_session", side_effect=fake_run):
            return aggregate_layered_replicate_metrics(exp_ids, **kwargs)

    def test_ensemble_over_replicate_experiments(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from database.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        with Session(engine) as session:
            self._seed(
                session,
                [
                    ("exp_s1", "work_of_separation", 20.0, 0),
                    ("exp_s2", "work_of_separation", 24.0, 0),
                    ("exp_s3", "work_of_separation", 28.0, 0),
                    ("exp_s1", "interfacial_tensile_strength", 5.0, 0),
                    ("exp_s2", "interfacial_tensile_strength", 7.0, 0),
                    ("exp_s3", "interfacial_tensile_strength", 9.0, 0),
                    # non-replica metric (density, bulk) must be ignored
                    ("exp_s1", "density", 1.0, None),
                    ("exp_s2", "density", 2.0, None),
                ],
            )
            out = self._call(session, ["exp_s1", "exp_s2", "exp_s3"])

        by_name = {r["metric_name"]: r for r in out}
        assert set(by_name) == {"work_of_separation", "interfacial_tensile_strength"}
        wos = by_name["work_of_separation"]
        assert abs(wos["mean"] - 24.0) < 1e-9
        assert wos["n_replicates"] == 3
        assert wos["meets_min_replicates"] is True
        # values 20/24/28 → std(ddof=1)=4.0 → SE = 4/sqrt(3)
        assert abs(wos["std"] - 4.0) < 1e-9
        assert abs(wos["standard_error"] - 4.0 / math.sqrt(3)) < 1e-9

    def test_empty_exp_ids_returns_empty(self):
        from features.layered_structures.layered_analysis import (
            aggregate_layered_replicate_metrics,
        )

        out = aggregate_layered_replicate_metrics([])
        assert out == []
