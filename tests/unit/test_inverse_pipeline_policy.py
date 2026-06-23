"""inverse_pipeline 정책 SSOT 테스트 (계획 §5/§4.5/§4.7/§7)."""

import pytest
from pydantic import ValidationError

from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    InversePipelinePolicy,
    MoistureDamagePolicy,
    PipelineMode,
    PlannedExperimentKind,
)
from contracts.policies.metrics import MetricNamespace
from contracts.policies.temperature import (
    DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K,
    DEFAULT_TEMPERATURE_PRIORITY_K,
)


class TestDefaults:
    def test_singleton_exists(self):
        assert isinstance(DEFAULT_INVERSE_PIPELINE_POLICY, InversePipelinePolicy)

    def test_cold_start_defaults(self):
        cs = DEFAULT_INVERSE_PIPELINE_POLICY.cold_start
        assert cs.n_min_labels >= 1
        assert cs.seed_batch_size >= 1
        assert isinstance(cs.seed_rng_seed, int)

    def test_similarity_defaults(self):
        sim = DEFAULT_INVERSE_PIPELINE_POLICY.similarity
        assert sim.comp_tolerance_wt > 0
        assert sim.temperature_tolerance_k >= 0
        assert sim.limit >= 1

    def test_closed_loop_disabled_by_default(self):
        assert DEFAULT_INVERSE_PIPELINE_POLICY.closed_loop.enabled is False

    def test_moisture_thresholds_ordered(self):
        m = DEFAULT_INVERSE_PIPELINE_POLICY.moisture
        assert m.er_fail_threshold <= m.er_warn_threshold

    def test_moisture_validator_rejects_inverted_thresholds(self):
        with pytest.raises(ValidationError):
            MoistureDamagePolicy(er_warn_threshold=0.7, er_fail_threshold=0.8)


class TestNamespaceMapping:
    def test_map_covers_pipeline_namespaces(self):
        policy = DEFAULT_INVERSE_PIPELINE_POLICY
        assert (
            policy.experiment_kind_for_namespace(MetricNamespace.BULK_FF_GAFF2.value)
            == PlannedExperimentKind.BINDER_CELL
        )
        assert (
            policy.experiment_kind_for_namespace(MetricNamespace.MECHANICAL.value)
            == PlannedExperimentKind.LAYERED_TENSILE
        )
        assert (
            policy.experiment_kind_for_namespace(MetricNamespace.LAYER.value)
            == PlannedExperimentKind.LAYERED_TENSILE
        )

    def test_reaxff_and_derived_unmapped(self):
        policy = DEFAULT_INVERSE_PIPELINE_POLICY
        assert policy.experiment_kind_for_namespace(MetricNamespace.REAXFF.value) is None
        assert policy.experiment_kind_for_namespace(MetricNamespace.DERIVED.value) is None

    def test_unknown_namespace_returns_none(self):
        assert DEFAULT_INVERSE_PIPELINE_POLICY.experiment_kind_for_namespace("nope") is None


class TestTemperatureSSOT:
    def test_tg_sweep_matches_temperature_policy(self):
        assert (
            DEFAULT_INVERSE_PIPELINE_POLICY.tg_temperature_sweep_k
            == DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K
        )

    def test_default_temperature_is_priority_first(self):
        assert (
            DEFAULT_INVERSE_PIPELINE_POLICY.default_temperature_k
            == DEFAULT_TEMPERATURE_PRIORITY_K[0]
        )


class TestEnums:
    def test_pipeline_modes(self):
        assert PipelineMode.BOOTSTRAP.value == "bootstrap"
        assert PipelineMode.BO.value == "bo"

    def test_experiment_kinds(self):
        assert set(PlannedExperimentKind) == {
            PlannedExperimentKind.BINDER_CELL,
            PlannedExperimentKind.LAYERED_TENSILE,
            PlannedExperimentKind.WATER_INTERFACE_LAYERED,
        }
