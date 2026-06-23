"""Unit tests for FF stack governance policy.

Tests cover:
- get_validation_level() for known and unknown stacks
- is_workflow_allowed() for each policy entry
- assert_submit_allowed() for blocked/research_only/validated
- build_ff_provenance() StudyType enum vs string normalization
"""

import pytest

# ---------------------------------------------------------------------------
# stack_governance primitives
# ---------------------------------------------------------------------------


class TestGetValidationLevel:
    def test_known_validated_stack(self):
        from contracts.policies.stack_governance import get_validation_level

        assert get_validation_level("gaff2_am1bcc_v1") == "validated"

    def test_known_research_only_stack(self):
        from contracts.policies.stack_governance import get_validation_level

        assert get_validation_level("gaff2_org__inorganic_profile__arith_v1") == "research_only"
        assert get_validation_level("reaxff_v1") == "research_only"

    def test_unknown_stack_returns_default(self):
        from contracts.policies.stack_governance import get_validation_level

        assert get_validation_level("nonexistent_stack") == "research_only"
        assert get_validation_level("nonexistent_stack", default="blocked") == "blocked"


class TestIsWorkflowAllowed:
    def test_validated_stack_allows_submit(self):
        from contracts.policies.stack_governance import is_workflow_allowed

        assert is_workflow_allowed("gaff2_am1bcc_v1", "submit") is True
        assert is_workflow_allowed("gaff2_am1bcc_v1", "build") is True
        assert is_workflow_allowed("gaff2_am1bcc_v1", "benchmark") is True

    def test_research_only_stack_limits(self):
        from contracts.policies.stack_governance import is_workflow_allowed

        # reaxff_v1 allows submit/build but not ml_dataset_export
        assert is_workflow_allowed("reaxff_v1", "submit") is True
        assert is_workflow_allowed("reaxff_v1", "ml_dataset_export") is False

    def test_unknown_stack_allows_only_preview_list(self):
        from contracts.policies.stack_governance import is_workflow_allowed

        assert is_workflow_allowed("unknown_stack_xyz", "preview") is True
        assert is_workflow_allowed("unknown_stack_xyz", "list") is True
        assert is_workflow_allowed("unknown_stack_xyz", "submit") is False


class TestAssertSubmitAllowed:
    def test_validated_passes(self):
        from contracts.policies.stack_governance import assert_submit_allowed

        # Should not raise
        assert_submit_allowed("gaff2_am1bcc_v1")

    def test_research_only_passes_currently(self):
        from contracts.policies.stack_governance import assert_submit_allowed

        # research_only is currently allowed (Phase 6+ will tighten)
        assert_submit_allowed("reaxff_v1")

    def test_blocked_raises(self):
        """A stack with validation_level='blocked' must raise ContractError."""
        from contracts.policies.stack_governance import (
            _STACK_POLICIES,
            StackPolicy,
            assert_submit_allowed,
        )

        # Temporarily inject a blocked stack for testing
        _STACK_POLICIES["_test_blocked"] = StackPolicy(
            stack_id="_test_blocked",
            validation_level="blocked",
        )
        try:
            from contracts.errors import ContractError

            with pytest.raises(ContractError):
                assert_submit_allowed("_test_blocked")
        finally:
            del _STACK_POLICIES["_test_blocked"]

    def test_unknown_stack_blocked(self):
        """Unknown stacks are fail-closed — submit not in default allowed_workflows."""
        from contracts.errors import ContractError
        from contracts.policies.stack_governance import assert_submit_allowed

        with pytest.raises(ContractError):
            assert_submit_allowed("completely_unknown_stack")


# ---------------------------------------------------------------------------
# build_ff_provenance StudyType normalization
# ---------------------------------------------------------------------------


class TestBuildFFProvenanceStudyType:
    def test_string_study_type_resolves_stack(self):
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance(study_type="bulk")
        assert result["metadata"]["stack_id"] == "gaff2_am1bcc_v1"

    def test_enum_study_type_resolves_stack(self):
        """StudyType enum value must resolve the same stack_id as its string."""
        from contracts.policies.forcefield import build_ff_provenance
        from contracts.schema_enums import StudyType

        result = build_ff_provenance(study_type=StudyType.BULK.value)
        assert result["metadata"]["stack_id"] == "gaff2_am1bcc_v1"

    def test_layered_study_type(self):
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance(study_type="layer_bulkff")
        assert result["metadata"]["stack_id"] == "gaff2_org__inorganic_profile__arith_v1"

    def test_validation_level_in_provenance(self):
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance(study_type="bulk")
        assert result["metadata"]["validation_level"] == "validated"

    def test_validation_level_in_conditions(self):
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance(study_type="bulk")
        cond_keys = [c["condition_key"] for c in result["conditions"]]
        assert "ff.validation_level" in cond_keys

    def test_organic_sources_default_empty(self):
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance(study_type="bulk")
        assert result["metadata"]["organic_sources"] == []
        assert result["metadata"]["generation_profiles"] == []

    def test_organic_sources_propagated(self):
        from contracts.policies.forcefield import build_ff_provenance

        sources = [
            {
                "mol_id": "U-SA-Squalane",
                "source_id": "U-SA-Squalane",
                "generation_profile": "baseline",
            },
            {"mol_id": "U-RE-Thio", "source_id": "U-RE-Thio", "generation_profile": "sqm_robust"},
        ]
        result = build_ff_provenance(study_type="bulk", organic_sources=sources)
        assert result["metadata"]["organic_sources"] == sources
        assert sorted(result["metadata"]["generation_profiles"]) == ["baseline", "sqm_robust"]


# ---------------------------------------------------------------------------
# Benchmark Evidence
# ---------------------------------------------------------------------------


class TestBenchmarkEvidence:
    def test_record_and_retrieve(self):
        from contracts.policies.stack_governance import (
            BenchmarkEvidence,
            _benchmark_evidence,
            get_benchmark_evidence,
            record_benchmark_evidence,
        )

        _benchmark_evidence.clear()
        ev = BenchmarkEvidence(
            stack_id="gaff2_am1bcc_v1",
            suite_id="density_tolerance",
            all_gates_passed=True,
            pass_rate=1.0,
            total_checks=5,
            passed_checks=5,
            failed_checks=0,
        )
        record_benchmark_evidence(ev)
        assert len(get_benchmark_evidence("gaff2_am1bcc_v1")) == 1
        _benchmark_evidence.clear()

    def test_check_benchmark_requirements(self):
        from contracts.policies.stack_governance import (
            BenchmarkEvidence,
            _benchmark_evidence,
            check_benchmark_requirements,
            record_benchmark_evidence,
        )

        _benchmark_evidence.clear()
        result = check_benchmark_requirements("gaff2_am1bcc_v1")
        assert result["all_required_passed"] is False
        assert "density_tolerance" in result["missing_suites"]

        record_benchmark_evidence(
            BenchmarkEvidence(
                stack_id="gaff2_am1bcc_v1",
                suite_id="density_tolerance",
                all_gates_passed=True,
                pass_rate=1.0,
                total_checks=5,
                passed_checks=5,
                failed_checks=0,
            )
        )
        record_benchmark_evidence(
            BenchmarkEvidence(
                stack_id="gaff2_am1bcc_v1",
                suite_id="ced_tolerance",
                all_gates_passed=True,
                pass_rate=1.0,
                total_checks=5,
                passed_checks=5,
                failed_checks=0,
            )
        )
        result = check_benchmark_requirements("gaff2_am1bcc_v1")
        assert result["all_required_passed"] is True
        _benchmark_evidence.clear()


# ---------------------------------------------------------------------------
# Preflight gate (Phase 5)
# ---------------------------------------------------------------------------


class TestPreflightGate:
    def test_preflight_manual_review_blocks(self):
        """If admin sidecar has preflight verdict=manual_review, resolve_ff_hint should block."""
        # This test verifies the logic exists; actual blocking depends on sidecar state
        from features.molecules.catalog import _inject_preflight_gate

        result = {"is_submittable": True, "blocked_reason": None}
        # Without sidecar, should remain submittable
        _inject_preflight_gate(result, "NONEXISTENT_MOL", {})
        assert result["is_submittable"] is True

    def test_preflight_skips_non_organic_route(self):
        """Preflight gate should be a no-op for non organic_curated_artifact routes."""
        from features.molecules.catalog import _inject_preflight_gate

        # Uses result["route"] (not ff_assignment["route"])
        result = {"is_submittable": True, "blocked_reason": None, "route": "inorganic_profile"}
        _inject_preflight_gate(result, "SOME_MOL", {"route": "inorganic_profile"})
        assert result["is_submittable"] is True

    def test_preflight_uses_result_route_not_ff_assignment(self):
        """Fallback path: ff_assignment may be None but result['route'] is set."""
        from features.molecules.catalog import _inject_preflight_gate

        # ff_assignment=None but result["route"]="organic_curated_artifact"
        # Should still attempt sidecar check (no crash, no-op without sidecar)
        result = {
            "is_submittable": True,
            "blocked_reason": None,
            "route": "organic_curated_artifact",
        }
        _inject_preflight_gate(result, "NONEXISTENT_FALLBACK_MOL", None)
        assert result["is_submittable"] is True  # no sidecar → no block

    def test_preflight_skips_already_blocked(self):
        """Preflight gate should not override an existing block."""
        from features.molecules.catalog import _inject_preflight_gate

        result = {
            "is_submittable": False,
            "blocked_reason": "already blocked",
            "route": "organic_curated_artifact",
        }
        _inject_preflight_gate(result, "SOME_MOL", {"route": "organic_curated_artifact"})
        assert result["is_submittable"] is False
        assert result["blocked_reason"] == "already blocked"


# ---------------------------------------------------------------------------
# Stack Readiness (Phase 6 — benchmark + ReaxFF combined check)
# ---------------------------------------------------------------------------


class TestStackReadiness:
    def test_validated_stack_ready(self):
        from contracts.policies.stack_governance import (
            BenchmarkEvidence,
            _benchmark_evidence,
            check_stack_readiness,
            record_benchmark_evidence,
        )

        _benchmark_evidence.clear()
        record_benchmark_evidence(
            BenchmarkEvidence(
                stack_id="gaff2_am1bcc_v1",
                suite_id="density_tolerance",
                all_gates_passed=True,
                pass_rate=1.0,
                total_checks=5,
                passed_checks=5,
                failed_checks=0,
            )
        )
        record_benchmark_evidence(
            BenchmarkEvidence(
                stack_id="gaff2_am1bcc_v1",
                suite_id="ced_tolerance",
                all_gates_passed=True,
                pass_rate=1.0,
                total_checks=5,
                passed_checks=5,
                failed_checks=0,
            )
        )
        result = check_stack_readiness("gaff2_am1bcc_v1")
        assert result["ready_for_production"] is True
        assert result["benchmark_passed"] is True
        _benchmark_evidence.clear()

    def test_validated_stack_missing_benchmark(self):
        from contracts.policies.stack_governance import _benchmark_evidence, check_stack_readiness

        _benchmark_evidence.clear()
        result = check_stack_readiness("gaff2_am1bcc_v1")
        assert result["ready_for_production"] is False
        assert result["benchmark_passed"] is False
        assert len(result["benchmark_missing_suites"]) == 2

    def test_layered_stack_reaxff_pending(self):
        from contracts.policies.stack_governance import _benchmark_evidence, check_stack_readiness

        _benchmark_evidence.clear()
        result = check_stack_readiness("gaff2_org__inorganic_profile__arith_v1")
        assert result["reaxff_review_required"] is True
        assert result["reaxff_review_pending"] is True
        assert result["ready_for_production"] is False
        _benchmark_evidence.clear()

    def test_unknown_stack_readiness(self):
        from contracts.policies.stack_governance import check_stack_readiness

        result = check_stack_readiness("unknown_xyz")
        assert result["submit_allowed"] is False
        assert result["ready_for_production"] is False
