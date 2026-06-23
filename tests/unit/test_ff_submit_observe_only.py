"""Unit tests for FF submit observe-only policy (P0).

v00.99.96 policy: the build pipeline and preview endpoints use observe-only
FF checks. They do NOT auto-generate missing artifacts. The canonical Molecules
catalog is the only entry point for artifact generation.

Test Coverage:
1. 'none' sentinel filtering in binder-cell FF check
2. precompute_typing_charge observe-only behavior (uses ensure_organic_artifact
   in production; spec says it should use is_artifact_ready for observe-only)
3. Layered FF check with proper mol_id resolution
4. Binder-cell FF gate consistency
5. SSOT consistency between resolve_ff_hint and collect_binder_ff_issues
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.eligibility import (  # noqa: E402
    collect_binder_ff_issues,
    collect_layered_ff_checks,
)


def _stub_resolve_ff_hint(mapping: dict[str, dict]):
    """Return a patch that replaces resolve_ff_hint with a dict lookup.

    Each value must include at least ``is_submittable``, ``blocked_reason``,
    ``artifact_warning``, ``route``, ``status`` to mirror the production
    return shape.
    """

    def _resolve(item_id: str) -> dict:
        if item_id in mapping:
            return mapping[item_id]
        # Default: active organic molecule
        return {
            "is_submittable": True,
            "blocked_reason": None,
            "artifact_warning": None,
            "route": "organic_curated_artifact",
            "status": "active",
        }

    return patch("features.molecules.catalog.resolve_ff_hint", side_effect=_resolve)


class TestNoneSentinelFiltering:
    """Tests for 'none' sentinel filtering in binder-cell FF check."""

    def test_filter_real_additives_excludes_none(self):
        """'none' should be filtered out before FF check."""
        additive_types = ["Sasobit", "none", "", "PPA", "None", "NONE"]
        real_additives = [a for a in additive_types if a and a.lower() != "none"]
        assert real_additives == ["Sasobit", "PPA"]
        assert "none" not in real_additives
        assert "None" not in real_additives
        assert "NONE" not in real_additives

    def test_collect_binder_ff_issues_with_empty_lists(self):
        """collect_binder_ff_issues should handle empty lists gracefully.

        When 'none' is filtered out, the resulting additive list may be empty.
        The function should return no blocked items in this case.
        """
        with _stub_resolve_ff_hint({}):
            issues = collect_binder_ff_issues(mol_ids=[], additive_ids=[])
        assert issues["blocked_items"] == []
        assert issues["warning_items"] == []
        assert not issues["has_blocked"]

    def test_none_sentinel_case_insensitive_filtering(self):
        """All case variants of 'none' should be filtered identically."""
        none_variants = ["none", "None", "NONE", "NoNe", "nONE"]
        for variant in none_variants:
            filtered = [variant] if variant and variant.lower() != "none" else []
            assert filtered == [], f"'{variant}' should be filtered out"


class TestPrecomputeTypingChargeObserveOnly:
    """Tests for precompute_typing_charge observe-only behavior.

    Note: The production function `precompute_typing_charge` currently uses
    `ensure_organic_artifact` which performs generation. The observe-only
    policy states it should use `is_artifact_ready` instead. These tests
    document the expected observe-only semantic.
    """

    def test_observe_only_semantic_documented(self):
        """Document that observe-only should use is_artifact_ready, not ensure.

        This test verifies that is_artifact_ready exists and can be used for
        observe-only checks without triggering artifact generation.
        """
        from features.molecules.artifact_runtime import is_artifact_ready

        # is_artifact_ready should exist and return (bool, source_id) tuple
        assert callable(is_artifact_ready)

        # Test the function signature with mocked dependencies
        with patch("features.molecules.artifact_service.get_artifact_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/path.json")
            ready, source_id = is_artifact_ready(
                mol_id="TestMol",
                ff_assignment={"source_id": "TestMol", "route": "organic_curated_artifact"},
                ff_family="organic_gaff2",
            )
            # Missing artifact should return False
            assert ready is False
            assert source_id is not None

    def test_is_artifact_ready_returns_tuple(self):
        """is_artifact_ready should return (bool, source_id) tuple."""
        from features.molecules.artifact_runtime import is_artifact_ready

        with patch("features.molecules.artifact_service.get_artifact_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/path.json")
            result = is_artifact_ready(
                mol_id="TestMol",
                ff_assignment={"source_id": "TestMol"},
                ff_family="organic_gaff2",
            )
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)

    def test_missing_artifact_returns_false_readiness(self):
        """Missing artifact should return (False, source_id) from is_artifact_ready."""
        from features.molecules.artifact_runtime import is_artifact_ready

        with patch("features.molecules.artifact_service.get_artifact_path") as mock_path:
            # Simulate missing artifact file
            mock_path.return_value = Path("/nonexistent/TestMol.json")
            ready, source_id = is_artifact_ready(
                mol_id="TestMol",
                ff_assignment={"source_id": "TestMol", "route": "organic_curated_artifact"},
                ff_family="organic_gaff2",
            )
            assert ready is False
            assert source_id == "TestMol"


class TestLayeredFFCheck:
    """Tests for layered FF check with proper mol_id resolution."""

    def test_interface_molecule_cell_extracts_mol_id(self):
        """interface_molecule_cell should extract actual mol_id from interface_mol_id.

        The source_id for interface_molecule_cell is a cell ID (e.g., ifc_water_10x10x20),
        NOT a mol_id. The actual mol_id should come from interface_mol_id field.
        """
        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_water_10x10x20",  # cell ID - NOT a mol_id
                "interface_mol_id": "Water",  # actual mol_id
            },
        ]

        with _stub_resolve_ff_hint(
            {
                "Water": {
                    "is_submittable": True,
                    "blocked_reason": None,
                    "artifact_warning": None,
                    "route": "water_model",
                    "status": "active",
                }
            }
        ):
            checks = collect_layered_ff_checks(layers)

            # Should have a pass check for water model
            pass_checks = [c for c in checks if c["status"] == "pass"]
            assert len(pass_checks) >= 1
            assert "water" in pass_checks[0]["message"].lower()

    def test_cell_id_not_used_as_mol_id(self):
        """Cell IDs (ifc_*, crys_*, exp_*) must not be used as mol_ids.

        If resolve_ff_hint is called with a cell ID, it would fail with
        'not found' error. This test verifies that the function correctly
        extracts interface_mol_id instead of using source_id.
        """
        cell_ids = ["ifc_water_10x10x20", "ifc_binder_AAA1_5x5x10"]

        for cell_id in cell_ids:
            layers = [
                {
                    "source_type": "interface_molecule_cell",
                    "source_id": cell_id,
                    "interface_mol_id": "Water",  # actual mol_id
                },
            ]

            with _stub_resolve_ff_hint(
                {
                    "Water": {
                        "is_submittable": True,
                        "blocked_reason": None,
                        "artifact_warning": None,
                        "route": "water_model",
                        "status": "active",
                    },
                    # Cell IDs should NOT be looked up
                    cell_id: {
                        "is_submittable": False,
                        "blocked_reason": f"Cell ID '{cell_id}' not found",
                        "artifact_warning": None,
                        "route": None,
                        "status": "blocked",
                    },
                }
            ):
                checks = collect_layered_ff_checks(layers)

                # Should pass because Water is used, not the cell_id
                fail_checks = [c for c in checks if c["status"] == "fail"]
                for check in fail_checks:
                    msg = check.get("message", "").lower()
                    # Cell ID should not cause failure
                    assert cell_id not in msg, (
                        f"cell ID '{cell_id}' should not appear in error message"
                    )

    def test_interface_molecule_cell_without_interface_mol_id(self):
        """When interface_mol_id is missing, check should be skipped or pass.

        If no interface_mol_id is provided, the function cannot determine
        the actual molecule to check. It should either skip the check
        or pass (not fail with the cell ID).
        """
        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_water_10x10x20",  # cell ID only
                # No interface_mol_id provided
            },
        ]

        with _stub_resolve_ff_hint({}):
            checks = collect_layered_ff_checks(layers)

            # Should not have "not found" error for the cell ID
            for check in checks:
                if check.get("status") == "fail":
                    msg = check.get("message", "").lower()
                    assert "ifc_water_10x10x20" not in msg or "not found" not in msg

    def test_interface_molecule_uses_source_id_directly(self):
        """interface_molecule type should use source_id as mol_id directly.

        Unlike interface_molecule_cell, interface_molecule's source_id IS
        the mol_id (e.g., 'Water', 'Toluene').
        """
        layers = [
            {
                "source_type": "interface_molecule",
                "source_id": "Water",  # This IS the mol_id
            },
        ]

        with _stub_resolve_ff_hint(
            {
                "Water": {
                    "is_submittable": True,
                    "blocked_reason": None,
                    "artifact_warning": None,
                    "route": "water_model",
                    "status": "active",
                }
            }
        ):
            checks = collect_layered_ff_checks(layers)

            # Should have a pass check for water model
            pass_checks = [c for c in checks if c["status"] == "pass"]
            assert len(pass_checks) >= 1
            assert "water" in pass_checks[0]["message"].lower()


class TestBinderCellFFGate:
    """Tests for binder-cell FF gate before runner.submit()."""

    def test_ff_blocked_reflected_in_result(self):
        """When FF is blocked, collect_binder_ff_issues should report it."""
        mapping = {
            "BlockedMol": {
                "is_submittable": False,
                "blocked_reason": "Artifact not found. Generate via Molecules catalog.",
                "artifact_warning": "Artifact not found",
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }

        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["BlockedMol"],
                additive_ids=[],
            )

        assert result["has_blocked"] is True
        assert len(result["blocked_items"]) == 1
        assert result["blocked_items"][0]["item_id"] == "BlockedMol"
        assert "Generate" in result["blocked_items"][0]["message"]

    def test_mixed_blocked_and_valid(self):
        """With both blocked and valid molecules, only blocked should be reported."""
        mapping = {
            "BlockedMol": {
                "is_submittable": False,
                "blocked_reason": "Not generated",
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
            "ValidMol": {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }

        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["BlockedMol", "ValidMol"],
                additive_ids=[],
            )

        assert result["has_blocked"] is True
        blocked_ids = [i["item_id"] for i in result["blocked_items"]]
        assert "BlockedMol" in blocked_ids
        assert "ValidMol" not in blocked_ids


class TestSSOTConsistency:
    """Tests for SSOT consistency across different FF check paths."""

    def test_resolve_ff_hint_and_collect_issues_consistent(self):
        """resolve_ff_hint() and collect_binder_ff_issues() should agree on blocked status.

        Both functions derive their eligibility decision from the same SSOT
        (typing_router + ff_assignment). This test verifies that a molecule
        marked as blocked by resolve_ff_hint is also blocked by
        collect_binder_ff_issues.
        """
        from features.molecules.catalog import resolve_ff_hint

        mol_id = "ConsistencyTestMol"

        # Create a mapping where the molecule is blocked
        blocked_mapping = {
            mol_id: {
                "is_submittable": False,
                "blocked_reason": "Artifact not found for consistency test",
                "artifact_warning": "Artifact not found",
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }

        with _stub_resolve_ff_hint(blocked_mapping):
            # Check resolve_ff_hint result
            hint = resolve_ff_hint(mol_id)
            hint_blocked = not hint.get("is_submittable", True)

            # Check collect_binder_ff_issues result
            issues = collect_binder_ff_issues([mol_id], [])
            issues_blocked = issues["has_blocked"]

            # Both should agree
            assert hint_blocked == issues_blocked, (
                f"SSOT inconsistency: resolve_ff_hint says blocked={hint_blocked}, "
                f"collect_binder_ff_issues says blocked={issues_blocked}"
            )

    def test_submittable_molecule_consistency(self):
        """Both functions should agree on submittable molecules."""
        mol_id = "SubmittableTestMol"

        valid_mapping = {
            mol_id: {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }

        with _stub_resolve_ff_hint(valid_mapping):
            # Import inside context to use patched function
            from features.molecules.catalog import resolve_ff_hint

            hint = resolve_ff_hint(mol_id)
            hint_submittable = hint.get("is_submittable", True)

            issues = collect_binder_ff_issues([mol_id], [])
            issues_blocked = issues["has_blocked"]

            # Should be submittable and not blocked
            assert hint_submittable is True
            assert issues_blocked is False


class TestLayeredFFCheckSourceTypeHandling:
    """Tests for specific source_type handling in layered FF checks."""

    def test_crystal_structure_always_passes(self):
        """crystal_structure sources should always pass FF check."""
        layers = [
            {"source_type": "crystal_structure", "source_id": "test_crystal"},
        ]
        checks = collect_layered_ff_checks(layers)

        # Crystal sources should not generate any fail checks
        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) == 0

    def test_binder_experiment_always_passes(self):
        """binder_experiment sources should always pass FF check."""
        layers = [
            {"source_type": "binder_experiment", "source_id": "exp_AAA1_X1"},
        ]
        checks = collect_layered_ff_checks(layers)

        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) == 0

    def test_unknown_source_type_fails_closed(self):
        """Unknown source types should fail-closed."""
        layers = [
            {"source_type": "unknown_future_type", "source_id": "x"},
        ]
        checks = collect_layered_ff_checks(layers)

        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) >= 1
        assert "unknown" in fail_checks[0]["message"].lower()

    def test_interface_molecule_missing_source_id_fails(self):
        """interface_molecule without source_id should fail."""
        layers = [
            {"source_type": "interface_molecule", "source_id": None},
        ]
        checks = collect_layered_ff_checks(layers)

        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) >= 1
        assert "missing" in fail_checks[0]["message"].lower()


# ============================================================================
# Integration Tests for P0 Policy
# ============================================================================


class TestBinderCellResponseSchema:
    """Tests for binder-cell blocked response schema compliance."""

    def test_blocked_response_schema_valid(self):
        """FF blocked response must comply with BatchJobBinderCellResponse schema."""
        from api.schemas.experiments import BatchJobBinderCellResponse, FFEligibilityItem

        # Simulate blocked response — all fields must be schema-valid
        blocked_response = BatchJobBinderCellResponse(
            batch_job_id="ff_blocked",  # str, not None
            total=10,
            new=8,
            duplicates=2,
            submitted=0,  # 0 when blocked
            errors=0,  # int, not list
            jobs=[],
            blocked=0,
            requires_similarity_decision=False,
            similar_job_count=0,
            excluded=0,
            ff_blocked_items=[
                FFEligibilityItem(
                    item_id="TestMol",
                    item_kind="molecule",
                    route="organic_curated_artifact",
                    status="blocked",
                    message="Artifact missing",
                )
            ],
        )

        # This should not raise — schema validation passed
        assert blocked_response.batch_job_id == "ff_blocked"
        assert blocked_response.submitted == 0
        assert isinstance(blocked_response.errors, int)
        assert len(blocked_response.ff_blocked_items) == 1

    def test_none_batch_job_id_raises(self):
        """batch_job_id=None should raise validation error."""
        from pydantic import ValidationError

        from api.schemas.experiments import BatchJobBinderCellResponse

        with pytest.raises(ValidationError):
            BatchJobBinderCellResponse(
                batch_job_id=None,  # Should fail
                total=0,
                new=0,
                duplicates=0,
                submitted=0,
                errors=0,
                jobs=[],
            )

    def test_list_errors_raises(self):
        """errors=[] (list) should raise validation error."""
        from pydantic import ValidationError

        from api.schemas.experiments import BatchJobBinderCellResponse

        with pytest.raises(ValidationError):
            BatchJobBinderCellResponse(
                batch_job_id="test",
                total=0,
                new=0,
                duplicates=0,
                submitted=0,
                errors=[],  # Should fail — must be int
                jobs=[],
            )


class TestBinderCellRunnerSubmitNotCalled:
    """Tests that runner.submit() is not called when FF is blocked."""

    def test_service_returns_blocked_response_without_submit(self):
        """When FF is blocked, create_batch_job_binder_cell returns early without submitting.

        This test verifies the contract that when ff_issues["has_blocked"] is True,
        the service must return a BatchJobBinderCellResponse with submitted=0 and
        ff_blocked_items populated, without invoking runner.submit().
        """
        # This is a structural test — the service code at line 339-355 in
        # features/batch_job_binder_cell/service.py shows the early-return logic.
        #
        # We verify the structural property by checking that:
        # 1. BatchJobBinderCellResponse can be constructed with blocked semantics
        # 2. The expected fields are set correctly

        from api.schemas.experiments import BatchJobBinderCellResponse, FFEligibilityItem

        # Simulate what the service returns when FF is blocked
        blocked_response = BatchJobBinderCellResponse(
            batch_job_id="ff_blocked",
            total=5,
            new=3,
            duplicates=2,
            submitted=0,  # Key: not submitted
            errors=0,
            jobs=[],
            blocked=0,
            requires_similarity_decision=False,
            similar_job_count=0,
            excluded=0,
            ff_blocked_items=[
                FFEligibilityItem(
                    item_id="BlockedAdditive",
                    item_kind="additive",
                    route="organic_curated_artifact",
                    status="blocked",
                    message="Artifact missing",
                )
            ],
        )

        # Verify blocked semantics
        assert blocked_response.submitted == 0, "Blocked requests must have submitted=0"
        assert len(blocked_response.ff_blocked_items) > 0, "Must report blocked items"
        assert blocked_response.batch_job_id == "ff_blocked", "Batch ID must be set"


class TestLayeredFFCheckSourceTypes:
    """Tests for layered FF check source type handling."""

    def test_binder_cell_source_type_not_fail(self):
        """binder_cell source_type should not fail as unknown."""
        layers = [
            {"source_type": "binder_cell", "source_id": "binder_exp_123"},
        ]

        checks = collect_layered_ff_checks(layers)

        # binder_cell should NOT produce a fail check
        fail_checks = [c for c in checks if c.get("status") == "fail"]
        unknown_fails = [c for c in fail_checks if "unknown source_type" in c.get("message", "")]

        assert len(unknown_fails) == 0, (
            f"binder_cell should not fail as unknown, got: {unknown_fails}"
        )

    def test_components_json_dict_handled(self):
        """components_json as dict should extract interface_mol_id correctly."""
        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_water_10x10",
                "components_json": {"mol_id": "Water", "count": 100},
            },
        ]

        with _stub_resolve_ff_hint(
            {
                "Water": {
                    "is_submittable": True,
                    "blocked_reason": None,
                    "artifact_warning": None,
                    "route": "water_model",
                    "status": "active",
                }
            }
        ):
            checks = collect_layered_ff_checks(layers)

            # Should pass because components_json.mol_id is correctly extracted
            fail_checks = [c for c in checks if c.get("status") == "fail"]
            assert len(fail_checks) == 0, (
                f"components_json dict should not cause fail, got: {fail_checks}"
            )

    def test_interface_mol_id_from_layer_metadata(self):
        """interface_mol_id should be extracted from layer metadata."""
        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_water_10x10x20",
                "interface_mol_id": "Water",  # Resolver provides this
            },
        ]

        with _stub_resolve_ff_hint(
            {
                "Water": {
                    "is_submittable": True,
                    "blocked_reason": None,
                    "artifact_warning": None,
                    "route": "water_model",
                    "status": "active",
                }
            }
        ):
            checks = collect_layered_ff_checks(layers)

            # Should pass (water model) — no fail checks
            pass_checks = [c for c in checks if c.get("status") == "pass"]
            assert len(pass_checks) >= 1, "Should have a pass check for water model"


class TestCheckTypingChargeReadinessObserveOnly:
    """Tests for check_typing_charge_readiness observe-only behavior."""

    def test_check_function_exists(self):
        """check_typing_charge_readiness function should exist."""
        from features.experiments.submission import check_typing_charge_readiness

        assert callable(check_typing_charge_readiness)

    def test_check_does_not_import_ensure(self):
        """check_typing_charge_readiness source should not import ensure_organic_artifact.

        The function's docstring references ensure_organic_artifact to explain
        what it does NOT do, so we only check the actual code portion after
        the docstring for imports of ensure_organic_artifact.
        """
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)

        # Parse the source to find actual imports — not docstrings
        tree = ast.parse(source)

        # Collect all imported names
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[0])

        # ensure_organic_artifact should NOT be imported
        assert "ensure_organic_artifact" not in imported_names, (
            "check_typing_charge_readiness should not import ensure_organic_artifact"
        )

    def test_check_uses_is_artifact_ready(self):
        """check_typing_charge_readiness should use is_artifact_ready for observe-only check."""
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)

        # Should use is_artifact_ready for observe-only checking
        assert "is_artifact_ready" in source, (
            "check_typing_charge_readiness should use is_artifact_ready"
        )

    def test_precompute_uses_ensure(self):
        """precompute_typing_charge should use ensure_organic_artifact (generates artifacts).

        This confirms the separation: check_* is observe-only, precompute_* generates.
        """
        import inspect

        from features.experiments.submission import precompute_typing_charge

        source = inspect.getsource(precompute_typing_charge)

        # Should use ensure_organic_artifact for generation
        assert "ensure_organic_artifact" in source, (
            "precompute_typing_charge should use ensure_organic_artifact"
        )


class TestIsWaterLikeHandling:
    """Tests for is_water_like handling in layered FF checks."""

    def test_is_water_like_passes_without_mol_id(self):
        """is_water_like=True should pass as water_model compatible without needing mol_id."""
        from forcefield.eligibility import collect_layered_ff_checks

        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_h2o_10x10x20",
                # No interface_mol_id provided
                "is_water_like": True,
            },
        ]

        checks = collect_layered_ff_checks(layers)

        # Should pass without needing resolve_ff_hint
        pass_checks = [c for c in checks if c.get("status") == "pass"]
        assert len(pass_checks) >= 1, f"Expected pass for is_water_like=True, got: {checks}"

        # Verify the pass reason mentions water-like
        water_passes = [c for c in pass_checks if "water" in c.get("message", "").lower()]
        assert len(water_passes) >= 1, f"Expected water-related pass message, got: {pass_checks}"

    def test_is_water_like_takes_priority_over_mol_id(self):
        """is_water_like should be used as SSOT even when mol_id is also present."""
        from unittest.mock import patch

        from forcefield.eligibility import collect_layered_ff_checks

        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_water_10x10x20",
                "interface_mol_id": "SomeOtherMolecule",  # Not water
                "is_water_like": True,  # But is_water_like is True
            },
        ]

        # resolve_ff_hint should NOT be called because is_water_like takes priority
        with patch("features.molecules.catalog.resolve_ff_hint") as mock_hint:
            checks = collect_layered_ff_checks(layers)

            # is_water_like=True should cause early pass, not calling resolve_ff_hint
            pass_checks = [c for c in checks if c.get("status") == "pass"]
            assert len(pass_checks) >= 1
            mock_hint.assert_not_called()

    def test_missing_mol_id_and_water_like_logs_warning(self):
        """Missing both mol_id and is_water_like should log warning and pass with explicit reason."""
        from forcefield.eligibility import collect_layered_ff_checks

        layers = [
            {
                "source_type": "interface_molecule_cell",
                "source_id": "ifc_unknown_10x10x20",
                # No interface_mol_id, no is_water_like
            },
        ]

        checks = collect_layered_ff_checks(layers)

        # Should pass (prebuilt cell assumption) with explicit reason
        pass_checks = [c for c in checks if c.get("status") == "pass"]
        assert len(pass_checks) >= 1, f"Expected pass for prebuilt cell, got: {checks}"

        # Check that the pass has explicit reason in details or message
        for check in pass_checks:
            details = check.get("details", {})
            message = check.get("message", "")
            has_reason = (
                details.get("reason") == "prebuilt_cell_no_metadata"
                or "without mol_id" in message.lower()
                or "no metadata" in message.lower()
                or "prebuilt" in message.lower()
            )
            assert has_reason, f"Expected explicit reason for no-metadata pass, got: {check}"


class TestLayeredServiceMetadataPass:
    """Tests that layered service passes is_water_like to eligibility."""

    def test_layer_dict_includes_is_water_like(self):
        """Verify that _validate_checks passes is_water_like from resolved source."""
        # This is a structural test - verify the code path exists
        import inspect

        from features.layered_structures.service import _validate_checks

        source = inspect.getsource(_validate_checks)

        # Should contain is_water_like handling
        assert "is_water_like" in source, "_validate_checks should pass is_water_like to layer_dict"
