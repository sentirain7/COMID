"""
Tests for policy definitions.

This test file validates that all policies work correctly
and enforce the intended business rules.
"""

import sys

import pytest

sys.path.insert(0, "src")

from contracts.policies.budget import (
    DEFAULT_JOB_BUDGETING_POLICY,
    JobBudgetingPolicy,
    JobPriority,
)
from contracts.policies.composition import (
    DEFAULT_COMPOSITION_CONSTRAINTS,
    CompositionConstraints,
)
from contracts.policies.failure import (
    DEFAULT_FAILURE_POLICY,
    FailureCategory,
    FailurePolicy,
    RetryAction,
)
from contracts.policies.metrics import (
    DEFAULT_METRICS_REGISTRY,
    MetricNamespace,
    MetricsRegistry,
    MetricType,
)
from contracts.policies.ml_policy import (
    CalibrationPolicy,
    ContinuousLearningPolicy,
    DriftDetectionPolicy,
    ModelComparisonPolicy,
)
from contracts.policies.recommendation_policy import (
    DEFAULT_RECOMMENDATION_POLICY,
    AdditiveScoreWeights,
    DebateConfig,
)
from contracts.policies.stabilization import (
    DEFAULT_STABILIZATION_CHAIN,
    StabilizationChain,
)
from contracts.policies.tier import (
    DEFAULT_TIER_POLICY,
    TierPolicy,
)


class TestCompositionConstraints:
    """Test composition constraints policy."""

    def test_valid_composition(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }
        is_valid, error = constraints.validate_composition(composition)
        assert is_valid is True
        assert error is None

    def test_invalid_sum(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 10.0,  # Sum = 95, not 100
        }
        is_valid, error = constraints.validate_composition(composition)
        assert is_valid is False
        assert "Sum" in error

    def test_negative_values(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": -5.0,
            "resin": 55.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }
        is_valid, error = constraints.validate_composition(composition)
        assert is_valid is False
        assert "negative" in error

    def test_out_of_bounds(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 50.0,  # Max is 30
            "resin": 20.0,
            "aromatic": 20.0,
            "saturate": 10.0,
        }
        is_valid, error = constraints.validate_composition(composition)
        assert is_valid is False
        assert "asphaltene" in error

    def test_normalize_proportional(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 10.0,  # Sum = 95
        }
        normalized = constraints.normalize(composition, method="proportional")
        assert abs(sum(normalized.values()) - 100.0) < 0.01

    def test_validity_tags_normal(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }
        tags = constraints.get_validity_tags(composition)
        assert "bulk_gaff2_ok" in tags
        assert "high_asphaltene_sensitive" not in tags

    def test_validity_tags_high_asphaltene(self):
        constraints = CompositionConstraints()
        composition = {
            "asphaltene": 28.0,  # >= 25%
            "resin": 25.0,
            "aromatic": 30.0,
            "saturate": 17.0,
        }
        tags = constraints.get_validity_tags(composition)
        assert "high_asphaltene_sensitive" in tags

    def test_default_instance(self):
        assert DEFAULT_COMPOSITION_CONSTRAINTS.sum_wt_pct == 100.0
        assert DEFAULT_COMPOSITION_CONSTRAINTS.composition_error_threshold_l1 == 1.0


class TestTierPolicy:
    """Test tier policy."""

    def test_get_tier_config(self):
        policy = TierPolicy()
        config = policy.get_tier_config("screening")
        assert config.target_atoms == 100000
        assert config.npt_ps == 1000.0
        assert config.dt_fs == 1.0

    def test_get_tier_config_confirm(self):
        policy = TierPolicy()
        config = policy.get_tier_config("confirm")
        assert config.target_atoms == 200000
        assert config.npt_ps == 3000.0

    def test_get_tier_config_validation(self):
        policy = TierPolicy()
        config = policy.get_tier_config("validation")
        assert config.ff_type == "reaxff"
        assert config.dt_fs == 0.5
        assert config.cap_per_batch == 5

    def test_unknown_tier_raises(self):
        policy = TierPolicy()
        with pytest.raises(ValueError):
            policy.get_tier_config("unknown_tier")

    def test_tier_upgrade_to_confirm(self):
        policy = TierPolicy()
        next_tier = policy.should_upgrade_tier("screening", {"density_zscore": 2.5}, {})
        assert next_tier == "confirm"

    def test_tier_upgrade_with_candidate(self):
        policy = TierPolicy()
        next_tier = policy.should_upgrade_tier(
            "screening", {}, {"candidate_for_recommendation": True}
        )
        assert next_tier == "confirm"

    def test_no_tier_upgrade(self):
        policy = TierPolicy()
        next_tier = policy.should_upgrade_tier("screening", {"density_zscore": 0.5}, {})
        assert next_tier is None

    def test_default_instance(self):
        assert DEFAULT_TIER_POLICY.convergence_criteria.density_threshold_pct == 0.5


class TestJobBudgetingPolicy:
    """Test job budgeting policy."""

    def test_priority_mapping(self):
        policy = JobBudgetingPolicy()
        assert policy.get_priority("screening") == JobPriority.HIGH
        assert policy.get_priority("confirm") == JobPriority.MEDIUM
        assert policy.get_priority("viscosity") == JobPriority.LOWEST

    def test_max_atoms(self):
        policy = JobBudgetingPolicy()
        assert policy.get_max_atoms("screening") == 120000
        assert policy.get_max_atoms("confirm") == 200000

    def test_can_submit_job_success(self):
        policy = JobBudgetingPolicy()
        can_submit, reason = policy.can_submit_job(
            tier="screening", atom_count=100000, current_jobs=0, gpu_usage={0: 0, 1: 0}
        )
        assert can_submit is True

    def test_can_submit_job_queue_full(self):
        """Submission blocked when queue depth exceeds max_batch_queued."""
        from contracts.policies.budget import DEFAULT_QUEUE_LIMITS_POLICY

        policy = JobBudgetingPolicy()
        can_submit, reason = policy.can_submit_job(
            tier="screening",
            atom_count=100000,
            current_jobs=4,
            gpu_usage={0: 1, 1: 1},
            queued_jobs=DEFAULT_QUEUE_LIMITS_POLICY.max_batch_queued,
        )
        assert can_submit is False
        assert "Queue full" in reason

    def test_can_submit_job_atoms_exceeded(self):
        policy = JobBudgetingPolicy()
        can_submit, reason = policy.can_submit_job(
            tier="screening",
            atom_count=150000,  # Exceeds 120000 limit
            current_jobs=0,
            gpu_usage={0: 0},
        )
        assert can_submit is False
        assert "exceeds" in reason

    def test_select_gpu(self):
        policy = JobBudgetingPolicy()
        gpu = policy.select_gpu({0: 1, 1: 0, 2: 0})
        assert gpu in [1, 2]  # Select least loaded

    def test_default_instance(self):
        assert DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_total == 4


class TestFailurePolicy:
    """Test failure policy."""

    def test_classify_failure_overlap(self):
        policy = FailurePolicy()
        category = policy.classify_failure(
            log_content="ERROR: Lost atoms during simulation", exit_code=1
        )
        assert category == FailureCategory.OVERLAP_INSTABILITY

    def test_classify_failure_pressure(self):
        policy = FailurePolicy()
        category = policy.classify_failure(log_content="Pressure diverge to NaN", exit_code=1)
        assert category == FailureCategory.PRESSURE_BLOWUP

    def test_classify_failure_qeq(self):
        policy = FailurePolicy()
        category = policy.classify_failure(
            log_content="QEq charge equilibration did not converge", exit_code=1
        )
        assert category == FailureCategory.QEQ_DIVERGENCE

    def test_classify_failure_unknown(self):
        policy = FailurePolicy()
        category = policy.classify_failure(log_content="Some unknown error", exit_code=1)
        assert category == FailureCategory.UNKNOWN

    def test_retry_action(self):
        policy = FailurePolicy()
        action = policy.get_retry_action(FailureCategory.OVERLAP_INSTABILITY)
        assert action == RetryAction.CHANGE_SEED

        action = policy.get_retry_action(FailureCategory.PRESSURE_BLOWUP)
        assert action == RetryAction.REDUCE_DT

    def test_calculate_new_dt(self):
        policy = FailurePolicy()

        # Normal reduction
        new_dt = policy.calculate_new_dt(1.0, "bulk_ff_gaff2", 0.5)
        assert new_dt == 0.5

        # At limit
        new_dt = policy.calculate_new_dt(0.5, "bulk_ff_gaff2", 0.5)
        assert new_dt == 0.25

        # Below limit
        new_dt = policy.calculate_new_dt(0.25, "bulk_ff_gaff2", 0.5)
        assert new_dt is None

    def test_check_density_valid(self):
        policy = FailurePolicy()

        is_valid, error = policy.check_density_valid(1.0)
        assert is_valid is True

        is_valid, error = policy.check_density_valid(0.1)
        assert is_valid is False
        assert "below" in error

        is_valid, error = policy.check_density_valid(1.5)
        assert is_valid is False
        assert "above" in error

    def test_density_bounds_fields(self):
        """Test density range fields for SSOT compliance."""
        policy = FailurePolicy()
        assert policy.asphalt_density_min == 0.8
        assert policy.asphalt_density_max == 1.3
        assert policy.physical_density_min == 0.5
        assert policy.physical_density_max == 2.0
        # Existing fields unchanged
        assert policy.density_min == 0.2
        assert policy.density_max == 1.3

    def test_default_instance(self):
        assert DEFAULT_FAILURE_POLICY.bulk_ff_max_retries == 2
        assert DEFAULT_FAILURE_POLICY.reaxff_max_retries == 1


class TestStabilizationChain:
    """Test stabilization chain policy."""

    def test_get_chain_screening(self):
        chain = StabilizationChain()
        steps = chain.get_chain("screening")
        assert len(steps) == 3
        assert steps[0].name == "minimize"
        assert steps[1].name == "nvt_equilibration"
        assert steps[2].name == "npt_production"

    def test_get_chain_confirm(self):
        chain = StabilizationChain()
        steps = chain.get_chain("confirm")
        assert len(steps) == 3
        # Confirm has longer minimization
        assert steps[0].parameters["etol"] == 1e-5

    def test_get_chain_viscosity(self):
        chain = StabilizationChain()
        steps = chain.get_chain("viscosity")
        assert len(steps) == 4  # Includes NEMD step
        assert steps[3].type == "nemd"

    def test_get_step_names(self):
        chain = StabilizationChain()
        names = chain.get_step_names("screening")
        assert names == ["minimize", "nvt_equilibration", "npt_production"]

    def test_protocol_hash(self):
        chain = StabilizationChain()
        hash1 = chain.get_protocol_hash("screening")
        hash2 = chain.get_protocol_hash("confirm")
        assert len(hash1) == 8
        assert hash1 != hash2  # Different tiers have different hashes

    def test_protocol_hash_deterministic(self):
        chain = StabilizationChain()
        hash1 = chain.get_protocol_hash("screening")
        hash2 = chain.get_protocol_hash("screening")
        assert hash1 == hash2  # Same tier always produces same hash

    def test_total_duration(self):
        chain = StabilizationChain()
        duration = chain.get_total_duration_ps("screening")
        assert duration == 2300.0  # 300 NVT + 2000 NPT

        duration = chain.get_total_duration_ps("confirm")
        assert duration == 3300.0  # 300 NVT + 3000 NPT

    def test_estimated_steps(self):
        chain = StabilizationChain()
        steps = chain.get_estimated_steps("screening", dt_fs=1.0)
        assert steps == 2300000  # 2300 ps / 0.001 ps per step

    def test_unknown_tier_raises(self):
        chain = StabilizationChain()
        with pytest.raises(ValueError):
            chain.get_chain("unknown_tier")

    def test_default_instance(self):
        assert "screening" in DEFAULT_STABILIZATION_CHAIN.chains


class TestMetricsRegistry:
    """Test metrics registry policy."""

    def test_valid_metric(self):
        registry = MetricsRegistry()
        assert registry.is_valid_metric("density") is True
        assert registry.is_valid_metric("cohesive_energy_density") is True
        assert registry.is_valid_metric("unknown_metric") is False

    def test_get_unit(self):
        registry = MetricsRegistry()
        assert registry.get_unit("density") == "g/cm3"
        assert registry.get_unit("cohesive_energy_density") == "MJ/m3"
        assert registry.get_unit("viscosity") == "mPa.s"

    def test_get_type(self):
        registry = MetricsRegistry()
        assert registry.get_type("density") == MetricType.SCALAR
        assert registry.get_type("rdf_curve") == MetricType.ARRAY

    def test_get_namespace(self):
        registry = MetricsRegistry()
        assert registry.get_namespace("density") == MetricNamespace.BULK_FF_GAFF2
        assert registry.get_namespace("adhesion_energy") == MetricNamespace.LAYER
        assert registry.get_namespace("tensile_strength") == MetricNamespace.MECHANICAL

    def test_validate_metric_success(self):
        registry = MetricsRegistry()
        is_valid, error = registry.validate_metric("density", "g/cm3", "bulk_ff_gaff2")
        assert is_valid is True
        assert error is None

    def test_validate_metric_wrong_unit(self):
        registry = MetricsRegistry()
        is_valid, error = registry.validate_metric("density", "kg/m3", "bulk_ff_gaff2")
        assert is_valid is False
        assert "Unit mismatch" in error

    def test_validate_metric_wrong_namespace(self):
        registry = MetricsRegistry()
        is_valid, error = registry.validate_metric("density", "g/cm3", "layer")
        assert is_valid is False
        assert "Namespace mismatch" in error

    def test_list_scalar_metrics(self):
        registry = MetricsRegistry()
        scalars = registry.list_scalar_metrics()
        assert "density" in scalars
        assert "rdf_curve" not in scalars

    def test_list_array_metrics(self):
        registry = MetricsRegistry()
        arrays = registry.list_array_metrics()
        assert "rdf_curve" in arrays
        assert "msd_curve" in arrays
        assert "density" not in arrays

    def test_list_metrics_by_namespace(self):
        registry = MetricsRegistry()
        bulk_metrics = registry.list_scalar_metrics(namespace="bulk_ff_gaff2")
        assert "density" in bulk_metrics
        assert "adhesion_energy" not in bulk_metrics

    def test_get_array_columns(self):
        registry = MetricsRegistry()
        columns = registry.get_array_columns("rdf_curve")
        assert columns == ["r", "g_r"]

        columns = registry.get_array_columns("msd_curve")
        assert columns == ["time_ps", "msd"]

    def test_unknown_metric_raises(self):
        registry = MetricsRegistry()
        with pytest.raises(ValueError):
            registry.get_unit("unknown_metric")

    def test_default_instance(self):
        assert DEFAULT_METRICS_REGISTRY.is_valid_metric("density")

    def test_interface_e_inter_metrics_registered(self):
        """Phase 4.2: interface E_inter metrics are registered with correct enum values."""
        registry = MetricsRegistry()

        # e_inter_interface_1
        assert registry.is_valid_metric("e_inter_interface_1")
        assert registry.get_type("e_inter_interface_1") == MetricType.SCALAR
        assert registry.get_namespace("e_inter_interface_1") == MetricNamespace.LAYER
        assert registry.get_unit("e_inter_interface_1") == "kcal/mol"

        # e_inter_interface_2
        assert registry.is_valid_metric("e_inter_interface_2")
        assert registry.get_type("e_inter_interface_2") == MetricType.SCALAR
        assert registry.get_namespace("e_inter_interface_2") == MetricNamespace.LAYER

        # e_inter_layer_matrix (array)
        assert registry.is_valid_metric("e_inter_layer_matrix")
        assert registry.get_type("e_inter_layer_matrix") == MetricType.ARRAY
        assert registry.get_namespace("e_inter_layer_matrix") == MetricNamespace.LAYER
        assert registry.get_array_columns("e_inter_layer_matrix") == [
            "pair_label",
            "e_inter",
        ]

    def test_e_inter_existing_metrics_unchanged(self):
        """Phase 4.2: existing E_inter metrics are unchanged."""
        registry = MetricsRegistry()
        assert registry.is_valid_metric("e_inter_total")
        assert registry.get_namespace("e_inter_total") == MetricNamespace.BULK_FF_GAFF2
        assert registry.is_valid_metric("e_inter_additive_binder")
        assert registry.get_namespace("e_inter_additive_binder") == MetricNamespace.BULK_FF_GAFF2

    def test_energy_component_metrics_registered(self):
        """Energy decomposition scalar metrics are registered."""
        registry = MetricsRegistry()
        energy_metrics = [
            "e_bond",
            "e_angle",
            "e_dihed",
            "e_improper",
            "e_vdwl",
            "e_coul",
            "e_pair",
            "e_mol",
            "e_long",
        ]
        for name in energy_metrics:
            assert registry.is_valid_metric(name), f"{name} not registered"
            assert registry.get_type(name) == MetricType.SCALAR
            assert registry.get_unit(name) == "kcal/mol"
            assert registry.get_namespace(name) == MetricNamespace.BULK_FF_GAFF2

    def test_cross_cut_interaction_profile_registered(self):
        """Verify cross_cut_interaction_profile is registered with correct properties."""
        defn = DEFAULT_METRICS_REGISTRY.get_definition("cross_cut_interaction_profile")
        assert defn is not None
        assert defn.produced is True
        assert defn.dtype == MetricType.ARRAY
        assert defn.namespace == MetricNamespace.LAYER
        assert defn.array_columns == ["cut_index", "cross_cut_mJ_m2"]

    def test_e_inter_layer_matrix_produced(self):
        """Verify e_inter_layer_matrix is now produced=True."""
        defn = DEFAULT_METRICS_REGISTRY.get_definition("e_inter_layer_matrix")
        assert defn is not None
        assert defn.produced is True
        assert defn.dtype == MetricType.ARRAY

    def test_thermo_log_extended_columns(self):
        """thermo_log array_columns include energy decomposition fields."""
        registry = MetricsRegistry()
        columns = registry.get_array_columns("thermo_log")
        for col in [
            "ebond",
            "eangle",
            "edihed",
            "eimp",
            "evdwl",
            "ecoul",
            "epair",
            "emol",
            "elong",
        ]:
            assert col in columns, f"{col} missing from thermo_log columns"


class TestPolicyIntegration:
    """Test policy integration scenarios."""

    def test_composition_to_tier_workflow(self):
        """Test workflow from composition validation to tier selection."""
        comp_policy = CompositionConstraints()
        tier_policy = TierPolicy()

        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        # Validate composition
        is_valid, _ = comp_policy.validate_composition(composition)
        assert is_valid

        # Get validity tags
        tags = comp_policy.get_validity_tags(composition)
        assert "bulk_gaff2_ok" in tags

        # Get tier config
        config = tier_policy.get_tier_config("screening")
        assert config.target_atoms == 100000

    def test_failure_retry_workflow(self):
        """Test failure handling and retry workflow."""
        failure_policy = FailurePolicy()
        tier_policy = TierPolicy()

        # Simulate failure
        category = failure_policy.classify_failure(log_content="Pressure diverge", exit_code=1)
        assert category == FailureCategory.PRESSURE_BLOWUP

        # Get retry action
        action = failure_policy.get_retry_action(category)
        assert action == RetryAction.REDUCE_DT

        # Calculate new dt
        original_dt = tier_policy.get_dt("screening")
        new_dt = failure_policy.calculate_new_dt(original_dt, "bulk_ff_gaff2")
        assert new_dt == 0.5


class TestRecommendationPolicy:
    """Test recommendation policy imports/defaults."""

    def test_debate_config_defaults(self):
        cfg = DebateConfig()
        assert cfg.max_rounds == 5
        assert cfg.merge_bo_weight == 0.6
        assert cfg.evidence_k_similar == 10

    def test_additive_score_weights_defaults(self):
        w = AdditiveScoreWeights()
        assert w.effectiveness == 0.30
        assert w.cost_benefit == 0.20
        assert w.compatibility == 0.25
        assert w.scalability == 0.25

    def test_default_recommendation_policy_has_debate(self):
        assert DEFAULT_RECOMMENDATION_POLICY.debate.max_rounds >= 1


class TestMLPolicyPhase8:
    """Test newly added Phase 8 ML policy sections."""

    def test_drift_detection_defaults(self):
        cfg = DriftDetectionPolicy()
        assert cfg.ks_test_alpha == 0.05
        assert cfg.feature_drift_threshold == 0.1

    def test_model_comparison_defaults(self):
        cfg = ModelComparisonPolicy()
        assert cfg.comparison_test == "wilcoxon"
        assert cfg.promotion_rmse_improvement_pct == 2.0

    def test_calibration_defaults(self):
        cfg = CalibrationPolicy()
        assert cfg.ece_n_bins == 10
        assert cfg.max_acceptable_ece == 0.10

    def test_continuous_learning_defaults(self):
        cfg = ContinuousLearningPolicy()
        assert cfg.check_interval_hours == 24
        assert cfg.max_model_versions == 20


class TestTensileLayerChain:
    """Phase 4.3: tensile_layer stabilization chain tests."""

    def test_tensile_layer_chain_exists(self):
        """tensile_layer chain is defined in StabilizationChain."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        assert len(steps) > 0

    def test_tensile_layer_chain_has_seven_steps(self):
        """tensile_layer chain has 7 steps (literature-based protocol)."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        assert len(steps) == 7
        step_names = [s.name for s in steps]
        assert step_names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
            "pre_tensile_nvt",
            "tensile_pull",
        ]

    def test_tensile_layer_total_duration(self):
        """tensile_layer total duration is 5700 ps."""
        chain = StabilizationChain()
        total = chain.get_total_duration_ps("tensile_layer")
        assert total == 5700.0

    def test_tensile_pull_step_type(self):
        """tensile_pull step has type='tensile'."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        tensile_step = steps[-1]
        assert tensile_step.type == "tensile"
        assert tensile_step.name == "tensile_pull"

    def test_tensile_pull_parameters(self):
        """tensile_pull step has updated pull velocity (5 m/s)."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        tensile_step = steps[-1]
        assert tensile_step.parameters["pull_velocity_A_per_fs"] == 0.00005
        assert tensile_step.parameters["grip_thickness_angstrom"] == 20.0
        assert tensile_step.parameters["max_strain"] == 0.5

    def test_annealing_step_type(self):
        """annealing_cycles step has type='annealing'."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        anneal_step = steps[2]
        assert anneal_step.name == "annealing_cycles"
        assert anneal_step.type == "annealing"
        assert anneal_step.parameters["n_cycles"] == 5
        assert anneal_step.parameters["temp_high_K"] == 500.0

    def test_high_temp_nvt_step(self):
        """high_temp_nvt step is 500K NVT for 100 ps."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        ht_step = steps[1]
        assert ht_step.name == "high_temp_nvt"
        assert ht_step.type == "nvt"
        assert ht_step.parameters["temperature_K"] == 500.0
        assert ht_step.duration == "100 ps"

    def test_pre_tensile_nvt_step_type(self):
        """pre_tensile_nvt is NVT at 100 ps."""
        chain = StabilizationChain()
        steps = chain.get_chain("tensile_layer")
        pt_step = steps[5]
        assert pt_step.name == "pre_tensile_nvt"
        assert pt_step.type == "nvt"
        assert pt_step.duration == "100 ps"


class TestMinimizeDurationVsMaxiter:
    """Verify minimize duration ≤ maxiter for all tiers (Fix 4 semantic separation)."""

    def test_minimize_duration_le_maxiter_all_tiers(self):
        """For all tiers with minimize, duration (expected steps) ≤ maxiter."""
        chain = StabilizationChain()
        for tier_name in chain.chains:
            steps = chain.get_chain(tier_name)
            for step in steps:
                if step.type == "minimize" and step.duration:
                    dur_lower = step.duration.strip().lower()
                    if "steps" in dur_lower:
                        expected = int(dur_lower.replace("steps", "").strip())
                        maxiter = step.parameters.get("maxiter", 0)
                        assert expected <= maxiter, (
                            f"Tier '{tier_name}': minimize duration {expected} > maxiter {maxiter}"
                        )


class TestTensileMetricsRegistered:
    """Phase 4.3: tensile metric registration tests."""

    def test_tensile_metrics_registered(self):
        """All tensile scalar metrics are registered."""
        registry = MetricsRegistry()
        tensile_scalars = [
            "interfacial_tensile_strength",
            "work_of_separation",
            "ductility",
            "toughness",
        ]
        for name in tensile_scalars:
            assert registry.is_valid_metric(name), f"{name} not registered"
            assert registry.get_type(name) == MetricType.SCALAR

    def test_tensile_metrics_namespace(self):
        """Tensile metrics belong to MECHANICAL namespace."""
        registry = MetricsRegistry()
        tensile_metrics = [
            "interfacial_tensile_strength",
            "work_of_separation",
            "ductility",
            "toughness",
        ]
        for name in tensile_metrics:
            assert registry.get_namespace(name) == MetricNamespace.MECHANICAL

    def test_tensile_metrics_units(self):
        """Tensile metrics have correct units."""
        registry = MetricsRegistry()
        assert registry.get_unit("interfacial_tensile_strength") == "MPa"
        assert registry.get_unit("work_of_separation") == "mJ/m2"
        assert registry.get_unit("ductility") == "dimensionless"
        assert registry.get_unit("toughness") == "MJ/m3"


class TestDefaultStagesTensileLayer:
    """Test get_default_stages('tensile_layer') returns correct stages + conditions.

    Loads features.protocol.service directly (via importlib.util) to avoid
    features/protocol/__init__.py which imports the FastAPI router.
    """

    def test_get_default_stages_tensile_layer(self):
        import asyncio
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "features.protocol.service",
            Path("src/features/protocol/service.py"),
        )
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)

        resp = asyncio.get_event_loop().run_until_complete(
            service.get_default_stages("tensile_layer")
        )
        assert len(resp.stages) == 7
        names = [s.name for s in resp.stages]
        assert names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
            "pre_tensile_nvt",
            "tensile_pull",
        ]
        assert resp.stages[0].condition.temperature_mode == "none"
        assert resp.stages[1].condition.temperature_mode == "ramp_from"
        assert resp.stages[2].condition.temperature_mode == "ramp"
        assert resp.stages[2].condition.n_cycles == 5
        assert resp.stages[3].condition.uses_target_temperature is True
        assert resp.stages[4].condition.uses_target_pressure is True
        assert resp.stages[5].condition.uses_target_temperature is True
        assert resp.stages[6].condition.temperature_mode == "target"


class TestLayerChain:
    """Verify the 5-step 'layer' chain exists and has correct structure."""

    def test_layer_chain_exists(self):
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain("layer")
        assert len(chain) == 5

    def test_layer_chain_step_names(self):
        names = DEFAULT_STABILIZATION_CHAIN.get_step_names("layer")
        assert names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
        ]

    def test_layer_chain_total_duration(self):
        total = DEFAULT_STABILIZATION_CHAIN.get_total_duration_ps("layer")
        # 100 + 1000 + 500 + 2000 = 3600 ps
        assert total == 3600.0


class TestLayerTensileLayerParity:
    """Verify layer chain == tensile_layer[:-1] (first 5 steps identical)."""

    def test_step_names_match(self):
        layer_names = DEFAULT_STABILIZATION_CHAIN.get_step_names("layer")
        tensile_names = DEFAULT_STABILIZATION_CHAIN.get_step_names("tensile_layer")
        assert layer_names == tensile_names[:5]

    def test_step_durations_match(self):
        layer_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("layer")
        tensile_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("tensile_layer")
        for layer_step, tensile_step in zip(layer_chain, tensile_chain[:5], strict=False):
            assert layer_step.duration == tensile_step.duration

    def test_step_parameters_match(self):
        layer_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("layer")
        tensile_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("tensile_layer")
        for layer_step, tensile_step in zip(layer_chain, tensile_chain[:5], strict=False):
            assert layer_step.parameters == tensile_step.parameters

    def test_step_types_match(self):
        layer_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("layer")
        tensile_chain = DEFAULT_STABILIZATION_CHAIN.get_chain("tensile_layer")
        for layer_step, tensile_step in zip(layer_chain, tensile_chain[:5], strict=False):
            assert layer_step.type == tensile_step.type


class TestDefaultStagesLayer:
    """Test get_default_stages('layer') returns 5 stages."""

    def test_get_default_stages_layer(self):
        import asyncio
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "features.protocol.service",
            Path("src/features/protocol/service.py"),
        )
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)

        resp = asyncio.get_event_loop().run_until_complete(service.get_default_stages("layer"))
        assert len(resp.stages) == 5
        names = [s.name for s in resp.stages]
        assert names == [
            "minimize",
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
        ]
        assert resp.total_duration_ps == 3600.0


class TestDefaultStagesOptionalMetadata:
    """Test default-stages service can append optional stage metadata."""

    def test_get_default_stages_screening_with_optional(self):
        import asyncio
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "features.protocol.service",
            Path("src/features/protocol/service.py"),
        )
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)

        resp = asyncio.get_event_loop().run_until_complete(
            service.get_default_stages("screening", include_optional=True)
        )
        names = [s.name for s in resp.stages]
        assert names == [
            "minimize",
            "high_temp_nvt",
            "high_pressure_npt",
            "nvt_equilibration",
            "npt_production",
            "extended_npt",
            "viscosity_nemd",
        ]
        high_temp = next(stage for stage in resp.stages if stage.name == "high_temp_nvt")
        assert high_temp.optional is True
        assert high_temp.duration_ps == 100.0
        assert high_temp.bounds["temperature_K"]["min"] == 300.0
        assert high_temp.compact_display_name == "High-T NVT"

        extended = next(stage for stage in resp.stages if stage.name == "extended_npt")
        assert extended.ui_metadata["submit_tier"] == "confirm"
        assert extended.ui_metadata["virtual_selector"] is True


def _load_protocol_service():
    """Load features.protocol.service via importlib to avoid FastAPI router import."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "features.protocol.service",
        Path("src/features/protocol/service.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_request_factory():
    """Load orchestrator.request_factory via importlib to avoid SQLAlchemy import chain."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "orchestrator.request_factory",
        Path("src/orchestrator/request_factory.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRampFromCondition:
    """Verify ramp_from temperature mode for layered high_temp_nvt."""

    def test_high_temp_nvt_ramp_from_has_temp_start(self):
        """Layer high_temp_nvt with temp_start_K produces ramp_from mode."""
        service = _load_protocol_service()

        step = DEFAULT_STABILIZATION_CHAIN.get_chain("layer")[1]
        assert step.name == "high_temp_nvt"
        cond = service._build_stage_condition(step)
        assert cond.temperature_mode == "ramp_from"
        assert cond.temp_start_K == 10.0
        assert cond.fixed_temperature_K == 500.0

    def test_bulk_high_temp_nvt_without_temp_start_stays_fixed(self):
        """Bulk equilibration high_temp_nvt (no temp_start_K) stays 'fixed'."""
        from contracts.policies.stabilization import StabilizationStep

        service = _load_protocol_service()

        step = StabilizationStep(
            name="high_temp_nvt",
            type="nvt",
            duration="100 ps",
            parameters={"temperature_K": 500.0, "thermostat": "nose-hoover", "tdamp": 100.0},
        )
        cond = service._build_stage_condition(step)
        assert cond.temperature_mode == "fixed"
        assert cond.temp_start_K is None

    def test_stage_condition_serialization(self):
        """StageCondition with temp_start_K serializes/deserializes correctly."""
        from api.schemas.experiments import StageCondition

        cond = StageCondition(
            temperature_mode="ramp_from", fixed_temperature_K=500.0, temp_start_K=10.0
        )
        data = cond.model_dump()
        assert data["temp_start_K"] == 10.0
        assert data["temperature_mode"] == "ramp_from"
        restored = StageCondition.model_validate(data)
        assert restored.temp_start_K == 10.0


class TestSkipStageKeys:
    """Verify ProtocolRequest.skip_stage_keys filters chain stages."""

    def test_skip_stage_keys_removes_step(self):
        """skip_stage_keys removes named steps from built chain."""
        from contracts.schemas import ProtocolRequest
        from protocols.protocol_chain import ProtocolChainBuilder

        builder = ProtocolChainBuilder(DEFAULT_STABILIZATION_CHAIN)
        request = ProtocolRequest(
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="layer_bulkff",
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/test.data",
            skip_stage_keys=["high_temp_nvt"],
        )
        chain = builder.build(request)
        step_names = [s.name for s in chain.steps]
        assert "high_temp_nvt" not in step_names
        assert "minimize" in step_names
        assert "annealing_cycles" in step_names

    def test_skip_multiple_stages(self):
        """skip_stage_keys removes multiple named steps."""
        from contracts.schemas import ProtocolRequest
        from protocols.protocol_chain import ProtocolChainBuilder

        builder = ProtocolChainBuilder(DEFAULT_STABILIZATION_CHAIN)
        request = ProtocolRequest(
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="layer_bulkff",
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/test.data",
            skip_stage_keys=["high_temp_nvt", "annealing_cycles"],
        )
        chain = builder.build(request)
        step_names = [s.name for s in chain.steps]
        assert "high_temp_nvt" not in step_names
        assert "annealing_cycles" not in step_names
        assert len(step_names) == 3  # minimize, nvt_eq, npt_eq

    def test_no_skip_preserves_all(self):
        """skip_stage_keys=None preserves all steps."""
        from contracts.schemas import ProtocolRequest
        from protocols.protocol_chain import ProtocolChainBuilder

        builder = ProtocolChainBuilder(DEFAULT_STABILIZATION_CHAIN)
        request = ProtocolRequest(
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="layer_bulkff",
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/test.data",
        )
        chain = builder.build(request)
        assert len(chain.steps) == 5


class TestLayeredSubmitRequestValidation:
    """Validate LayeredStructureSubmitRequest.stage_requests contract."""

    def _make_request(self, **overrides):
        from api.schemas.structures import LayeredStructureSubmitRequest

        base = {
            "name": "test",
            "layers": [
                {"source_type": "binder_cell", "source_id": "test1", "thickness_angstrom": 30},
                {
                    "source_type": "crystal_structure",
                    "source_id": "test2",
                    "thickness_angstrom": 10,
                },
            ],
        }
        base.update(overrides)
        return LayeredStructureSubmitRequest.model_validate(base)

    def test_disable_optional_stage_accepted(self):
        from api.schemas.experiments import StageRequest

        req = self._make_request(
            stage_requests=[StageRequest(stage_key="high_temp_nvt", enabled=False)]
        )
        assert len(req.stage_requests) == 1

    def test_required_stage_rejected(self):
        from api.schemas.experiments import StageRequest

        with pytest.raises(Exception, match="only allows disabling optional"):
            self._make_request(stage_requests=[StageRequest(stage_key="minimize", enabled=False)])

    def test_enabled_true_rejected(self):
        from api.schemas.experiments import StageRequest

        with pytest.raises(Exception, match="enabled=false"):
            self._make_request(
                stage_requests=[StageRequest(stage_key="high_temp_nvt", enabled=True)]
            )

    def test_duration_override_rejected(self):
        from api.schemas.experiments import StageRequest

        with pytest.raises(Exception, match="stage_durations"):
            self._make_request(
                stage_requests=[
                    StageRequest(stage_key="high_temp_nvt", enabled=False, duration_ps=200.0)
                ]
            )

    def test_params_override_rejected(self):
        from api.schemas.experiments import StageRequest

        with pytest.raises(Exception, match="params_override"):
            self._make_request(
                stage_requests=[
                    StageRequest(
                        stage_key="high_temp_nvt",
                        enabled=False,
                        params_override={"temperature_K": 600},
                    )
                ]
            )

    def test_duplicate_stage_key_rejected(self):
        from api.schemas.experiments import StageRequest

        with pytest.raises(Exception, match="Duplicate"):
            self._make_request(
                stage_requests=[
                    StageRequest(stage_key="high_temp_nvt", enabled=False),
                    StageRequest(stage_key="high_temp_nvt", enabled=False),
                ]
            )


class TestCreateProtocolRequestSkipStages:
    """Verify create_protocol_request passes skip_stage_keys."""

    def test_skip_stage_keys_set(self):
        factory = _load_request_factory()

        req = factory.create_protocol_request(
            data_file_path="/tmp/test.data",
            skip_stage_keys=["high_temp_nvt"],
        )
        assert req.skip_stage_keys == ["high_temp_nvt"]

    def test_skip_stage_keys_none_by_default(self):
        factory = _load_request_factory()

        req = factory.create_protocol_request(data_file_path="/tmp/test.data")
        assert req.skip_stage_keys is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
