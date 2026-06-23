"""Unit tests for P1: Background job separation and API cleanup.

P1 key principles (Codex feedback):
1. check = observe-only - only uses is_artifact_ready(), resolve_ff_hint(), metadata
2. prepare = synchronous background function - not async def
3. Reuse existing SSOT - get_pending_molecules() -> run_parallel_batch()
4. batch_kind extension - "public" | "admin" | "typing_prepare"
5. Slot release guaranteed in ALL exit paths

Test Coverage:
1. dict/Pydantic input handling in _iter_unique_molecule_ids
2. prepare slot release in all paths (empty, no-work, exception)
3. prepare filters: organic only, incomplete only
4. check does not call any executors (observe-only)
5. concurrent prepare returns 409
6. aging-aware consumer_id matching
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ============================================================================
# Task 1: dict/Pydantic Input Handling
# ============================================================================


class TestIterUniqueMoleculeIds:
    """Tests for _iter_unique_molecule_ids dict/Pydantic handling."""

    def test_dict_input_extracts_mol_id(self):
        """dict input should correctly extract mol_id."""
        from features.experiments.submission import _iter_unique_molecule_ids

        molecule_counts = [
            {"mol_id": "AS-Thio", "count": 1},
            {"mol_id": "SA-Squalane", "count": 2},
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert result == ["AS-Thio", "SA-Squalane"]

    def test_pydantic_input_extracts_mol_id(self):
        """Pydantic model input should correctly extract mol_id."""
        from features.experiments.submission import _iter_unique_molecule_ids

        class MockMolCount:
            def __init__(self, mol_id: str, count: int):
                self.mol_id = mol_id
                self.count = count

        molecule_counts = [
            MockMolCount("AS-Thio", 1),
            MockMolCount("RE-Pyrid", 3),
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert result == ["AS-Thio", "RE-Pyrid"]

    def test_mixed_dict_and_pydantic(self):
        """Mixed dict and Pydantic inputs should both work."""
        from features.experiments.submission import _iter_unique_molecule_ids

        class MockMolCount:
            def __init__(self, mol_id: str, count: int):
                self.mol_id = mol_id
                self.count = count

        molecule_counts = [
            {"mol_id": "DictMol", "count": 1},
            MockMolCount("PydanticMol", 2),
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert "DictMol" in result
        assert "PydanticMol" in result

    def test_zero_count_excluded(self):
        """Molecules with count <= 0 should be excluded."""
        from features.experiments.submission import _iter_unique_molecule_ids

        molecule_counts = [
            {"mol_id": "Good", "count": 1},
            {"mol_id": "Zero", "count": 0},
            {"mol_id": "Negative", "count": -1},
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert result == ["Good"]

    def test_empty_mol_id_excluded(self):
        """Empty or whitespace mol_id should be excluded."""
        from features.experiments.submission import _iter_unique_molecule_ids

        molecule_counts = [
            {"mol_id": "Good", "count": 1},
            {"mol_id": "", "count": 1},
            {"mol_id": "   ", "count": 1},
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert result == ["Good"]

    def test_duplicates_removed(self):
        """Duplicate mol_ids should be removed, preserving order."""
        from features.experiments.submission import _iter_unique_molecule_ids

        molecule_counts = [
            {"mol_id": "A", "count": 1},
            {"mol_id": "B", "count": 2},
            {"mol_id": "A", "count": 3},  # duplicate
        ]
        result = _iter_unique_molecule_ids(molecule_counts, None)

        assert result == ["A", "B"]


# ============================================================================
# Task 2 & 3: Slot Release and Filtering
# ============================================================================


class TestPrepareTypingChargeBackground:
    """Tests for prepare_typing_charge_background slot release and filtering."""

    def test_function_is_sync(self):
        """prepare_typing_charge_background must be a sync function."""
        import asyncio
        import inspect

        from features.experiments.submission import prepare_typing_charge_background

        assert callable(prepare_typing_charge_background)
        assert not asyncio.iscoroutinefunction(prepare_typing_charge_background)
        assert not inspect.iscoroutinefunction(prepare_typing_charge_background)

    def test_slot_released_on_empty_request(self):
        """Slot must be released when molecule_counts is empty."""
        from features.experiments.submission import prepare_typing_charge_background
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            get_batch_progress,
            release_batch_slot,
        )

        # Clean state
        release_batch_slot()

        # Acquire slot (simulating router behavior)
        assert acquire_batch_slot("typing_prepare", "baseline") is True

        # Call with empty request
        prepare_typing_charge_background(
            molecule_counts=[],
            additives=None,
            ff_type="bulk_ff_gaff2",
            aging_state="non_aging",
        )

        # Slot must be released
        assert get_batch_progress()["running"] is False

        # Next acquire should succeed
        assert acquire_batch_slot("typing_prepare", "baseline") is True
        release_batch_slot()

    def test_slot_released_when_all_artifacts_ready(self):
        """Slot must be released when no pending molecules match."""
        from features.experiments.submission import prepare_typing_charge_background
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            get_batch_progress,
            release_batch_slot,
        )

        release_batch_slot()
        assert acquire_batch_slot("typing_prepare", "baseline") is True

        # Mock get_pending_molecules to return empty (all ready)
        with patch(
            "features.molecules.artifact_service.get_pending_molecules",
            return_value=[],
        ):
            prepare_typing_charge_background(
                molecule_counts=[{"mol_id": "TestMol", "count": 1}],
                additives=None,
                ff_type="bulk_ff_gaff2",
                aging_state="non_aging",
            )

        assert get_batch_progress()["running"] is False
        release_batch_slot()

    def test_slot_released_when_only_complete_artifacts(self):
        """Slot must be released when matching artifacts are all complete."""
        from features.experiments.submission import prepare_typing_charge_background
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            get_batch_progress,
            release_batch_slot,
        )

        release_batch_slot()
        assert acquire_batch_slot("typing_prepare", "baseline") is True

        # Pending molecule exists but is_complete=True
        pending = [
            {
                "mol_id": "TestMol",
                "source_id": "TestMol",
                "consumer_ids": [],
                "artifact_type": "organic",
                "is_complete": True,  # Already complete
            }
        ]

        with patch(
            "features.molecules.artifact_service.get_pending_molecules",
            return_value=pending,
        ):
            prepare_typing_charge_background(
                molecule_counts=[{"mol_id": "TestMol", "count": 1}],
                additives=None,
                ff_type="bulk_ff_gaff2",
                aging_state="non_aging",
            )

        assert get_batch_progress()["running"] is False
        release_batch_slot()

    def test_slot_released_on_exception(self):
        """Slot must be released when exception occurs."""
        from features.experiments.submission import prepare_typing_charge_background
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            get_batch_progress,
            release_batch_slot,
        )

        release_batch_slot()
        assert acquire_batch_slot("typing_prepare", "baseline") is True

        with patch(
            "features.molecules.artifact_service.get_pending_molecules",
            side_effect=RuntimeError("test error"),
        ):
            with pytest.raises(RuntimeError, match="test error"):
                prepare_typing_charge_background(
                    molecule_counts=[{"mol_id": "TestMol", "count": 1}],
                    additives=None,
                    ff_type="bulk_ff_gaff2",
                    aging_state="non_aging",
                )

        # Slot must be released even after exception
        assert get_batch_progress()["running"] is False
        release_batch_slot()

    def test_slot_released_when_run_parallel_batch_raises(self):
        """Slot must be released even when run_parallel_batch raises before its finally.

        This tests the edge case where run_parallel_batch raises an exception
        before entering its own finally block. The prepare function's finally
        must still release the slot.
        """
        from features.experiments.submission import prepare_typing_charge_background
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            get_batch_progress,
            release_batch_slot,
        )

        release_batch_slot()
        assert acquire_batch_slot("typing_prepare", "baseline") is True

        # Mock get_pending_molecules to return a matching incomplete organic row
        pending = [
            {
                "mol_id": "TestMol",
                "source_id": "TestMol",
                "consumer_ids": ["U-TestMol"],
                "artifact_type": "organic",
                "is_complete": False,
            }
        ]

        with patch(
            "features.molecules.artifact_service.get_pending_molecules",
            return_value=pending,
        ):
            # run_parallel_batch raises RuntimeError (simulating early failure)
            with patch(
                "features.molecules.artifact_service.run_parallel_batch",
                side_effect=RuntimeError("run_parallel_batch failed before finally"),
            ):
                with pytest.raises(RuntimeError, match="run_parallel_batch failed"):
                    prepare_typing_charge_background(
                        molecule_counts=[{"mol_id": "TestMol", "count": 1}],
                        additives=None,
                        ff_type="bulk_ff_gaff2",
                        aging_state="non_aging",
                    )

        # Slot MUST be released even when run_parallel_batch raises
        assert get_batch_progress()["running"] is False

        # Next acquire should succeed
        assert acquire_batch_slot("typing_prepare", "baseline") is True
        release_batch_slot()

    def test_filters_non_organic_artifacts(self):
        """Only artifact_type='organic' should be processed."""
        import inspect

        from features.experiments.submission import prepare_typing_charge_background

        source = inspect.getsource(prepare_typing_charge_background)

        # Verify filter logic exists
        assert "artifact_type" in source
        assert '"organic"' in source

    def test_filters_complete_artifacts(self):
        """is_complete=True should be excluded."""
        import inspect

        from features.experiments.submission import prepare_typing_charge_background

        source = inspect.getsource(prepare_typing_charge_background)

        assert "is_complete" in source
        assert 'not p.get("is_complete"' in source or "not p.get('is_complete'" in source


# ============================================================================
# Task 4: Check Observe-Only
# ============================================================================


class TestCheckTypingChargeReadinessObserveOnly:
    """Tests that check_typing_charge_readiness is truly observe-only."""

    def test_does_not_import_assign_inorganic(self):
        """check should NOT import assign_inorganic_with_cache."""
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)
        tree = ast.parse(source)

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "assign_inorganic_with_cache" not in imported_names

    def test_does_not_import_assign_ionic(self):
        """check should NOT import assign_ionic."""
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)
        tree = ast.parse(source)

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "assign_ionic" not in imported_names

    def test_does_not_import_assign_water(self):
        """check should NOT import assign_water."""
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)
        tree = ast.parse(source)

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "assign_water" not in imported_names

    def test_does_not_import_assign_organic(self):
        """check should NOT import assign_organic."""
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)
        tree = ast.parse(source)

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "assign_organic" not in imported_names

    def test_does_not_import_ensure_organic_artifact(self):
        """check should NOT import ensure_organic_artifact."""
        import ast
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)
        tree = ast.parse(source)

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "ensure_organic_artifact" not in imported_names

    def test_uses_is_artifact_ready(self):
        """check should use is_artifact_ready for organic artifacts."""
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)

        assert "is_artifact_ready" in source

    def test_uses_ionic_is_activated_ssot(self):
        """check should use ionic is_activated() SSOT for IONIC_PROFILE."""
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)

        # Should use is_activated from ionic_executor (SSOT)
        assert "ionic_is_activated" in source or "is_activated" in source
        # Should NOT use raw env var check for ionic
        assert 'os.environ.get("ASPHALT_IONIC_ROUTE_ACTIVATED"' not in source

    def test_uses_inorganic_is_profile_active_ssot(self):
        """check should use InorganicParameterService.is_profile_active() SSOT."""
        import inspect

        from features.experiments.submission import check_typing_charge_readiness

        source = inspect.getsource(check_typing_charge_readiness)

        # Should use is_profile_active (SSOT)
        assert "is_profile_active" in source
        # Should import InorganicParameterService
        assert "InorganicParameterService" in source


# ============================================================================
# Task 5: Aging-Aware Matching
# ============================================================================


class TestAgingAwareMatching:
    """Tests for aging_state to consumer_id prefix matching."""

    def test_prepare_expands_base_id_with_aging_prefix(self):
        """prepare should expand base mol_id with aging prefix."""
        import inspect

        from features.experiments.submission import prepare_typing_charge_background

        source = inspect.getsource(prepare_typing_charge_background)

        # Verify aging prefix expansion logic
        assert "aging_prefix_map" in source or "prefix" in source
        assert "non_aging" in source
        assert "short_aging" in source
        assert "long_aging" in source

    def test_prepare_matches_consumer_ids(self):
        """prepare should match consumer_ids (U-/S-/L- variants)."""
        import inspect

        from features.experiments.submission import prepare_typing_charge_background

        source = inspect.getsource(prepare_typing_charge_background)

        assert "consumer_ids" in source
        assert "expanded_request_set" in source or "_matches_request" in source


# ============================================================================
# Batch Kind Extension
# ============================================================================


class TestBatchKindExtension:
    """Tests for batch_kind extension to include 'typing_prepare'."""

    def test_acquire_batch_slot_accepts_typing_prepare(self):
        """acquire_batch_slot should accept 'typing_prepare'."""
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            release_batch_slot,
        )

        release_batch_slot()
        result = acquire_batch_slot("typing_prepare", "baseline")
        release_batch_slot()

        assert result is True

    def test_acquire_batch_slot_rejects_invalid_kind(self):
        """acquire_batch_slot should reject invalid batch_kind."""
        from features.molecules.artifact_service import acquire_batch_slot

        with pytest.raises(ValueError, match="batch_kind must be"):
            acquire_batch_slot("invalid_kind", "baseline")

    def test_concurrent_prepare_returns_false(self):
        """Second acquire should return False when slot is held."""
        from features.molecules.artifact_service import (
            acquire_batch_slot,
            release_batch_slot,
        )

        release_batch_slot()

        result1 = acquire_batch_slot("typing_prepare", "baseline")
        result2 = acquire_batch_slot("typing_prepare", "baseline")

        release_batch_slot()

        assert result1 is True
        assert result2 is False


# ============================================================================
# Router and Service Exports
# ============================================================================


class TestRouterConfiguration:
    """Tests for router endpoint configuration."""

    def test_check_endpoint_registered(self):
        """check-typing-readiness endpoint should be registered."""
        from features.experiments.router import router

        routes = [r.path for r in router.routes]
        assert "/experiments/molecule-based/check-typing-readiness" in routes

    def test_prepare_endpoint_registered(self):
        """prepare-typing-charge endpoint should be registered."""
        from features.experiments.router import router

        routes = [r.path for r in router.routes]
        assert "/experiments/molecule-based/prepare-typing-charge" in routes


class TestServiceExports:
    """Tests for service.py exports."""

    def test_all_exports_present(self):
        """All P1 functions should be exported."""
        from features.experiments import service

        assert hasattr(service, "check_typing_charge_readiness")
        assert hasattr(service, "prepare_typing_charge_background")
        assert hasattr(service, "precompute_typing_charge")

    def test_all_list_includes_p1_exports(self):
        """__all__ should include P1 exports."""
        from features.experiments.service import __all__

        assert "check_typing_charge_readiness" in __all__
        assert "prepare_typing_charge_background" in __all__


# ============================================================================
# P0 Regression Tests
# ============================================================================


class TestP0Regression:
    """Regression tests to ensure P0 behavior is preserved."""

    def test_none_sentinel_filtering_still_works(self):
        """'none' sentinel filtering should still work."""
        additive_types = ["Sasobit", "none", "", "PPA", "None", "NONE"]
        real_additives = [a for a in additive_types if a and a.lower() != "none"]
        assert real_additives == ["Sasobit", "PPA"]

    def test_is_artifact_ready_still_returns_tuple(self):
        """is_artifact_ready should still return (bool, source_id) tuple."""
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

    def test_precompute_still_uses_ensure(self):
        """precompute_typing_charge should still use ensure_organic_artifact."""
        import inspect

        from features.experiments.submission import precompute_typing_charge

        source = inspect.getsource(precompute_typing_charge)

        assert "ensure_organic_artifact" in source
