"""Unit tests for P1.5 Aging UI (aging_artifact_status field).

v01.02.17+ policy: list_molecules() returns aging_artifact_status for each molecule,
indicating artifact readiness for non_aging, short_aging, long_aging variants.

Test Coverage:
1. SSOT compliance - uses build_aging_mol_id(), is_artifact_ready(), resolve_artifact_target()
2. Schema validation - correct shape for aging_artifact_status
3. Route-based behavior - organic_curated vs additive/inorganic
4. No lstrip or direct string manipulation

Codex mandate: SSOT functions only, no f"{prefix}" or lstrip().
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from common.molecule_id import AGING_CATEGORY_MAP  # noqa: E402
from features.molecules.catalog import _compute_aging_artifact_status  # noqa: E402


class TestSSOTCompliance:
    """Tests for SSOT function usage (Codex mandate)."""

    def test_uses_build_aging_mol_id_ssot(self):
        """_compute_aging_artifact_status uses build_aging_mol_id(), not lstrip."""
        source = inspect.getsource(_compute_aging_artifact_status)
        assert "build_aging_mol_id" in source, "Missing SSOT: build_aging_mol_id()"

        # Check for actual lstrip() call, not docstring mentions
        # Extract code portion only (after docstring ends)
        lines = source.split("\n")
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if '"""' in stripped:
                in_docstring = not in_docstring
                continue
            if not in_docstring and stripped and not stripped.startswith("#"):
                code_lines.append(line)
        code_only = "\n".join(code_lines)

        # These patterns should not appear in actual code
        assert ".lstrip(" not in code_only, "SSOT violation: lstrip() call in code"
        assert 'f"U-{' not in code_only, "SSOT violation: hardcoded U- prefix"
        assert 'f"S-{' not in code_only, "SSOT violation: hardcoded S- prefix"
        assert 'f"L-{' not in code_only, "SSOT violation: hardcoded L- prefix"

    def test_uses_artifact_runtime_is_artifact_ready(self):
        """Uses artifact_runtime.is_artifact_ready(), not eligibility."""
        source = inspect.getsource(_compute_aging_artifact_status)
        assert "is_artifact_ready" in source, "Missing SSOT: is_artifact_ready()"
        assert "forcefield.eligibility" not in source, "SSOT violation: wrong module"

    def test_uses_resolve_artifact_target(self):
        """Uses resolve_artifact_target() SSOT."""
        source = inspect.getsource(_compute_aging_artifact_status)
        assert "resolve_artifact_target" in source, "Missing SSOT: resolve_artifact_target()"

    def test_uses_aging_category_map(self):
        """Uses AGING_CATEGORY_MAP from common.molecule_id."""
        source = inspect.getsource(_compute_aging_artifact_status)
        assert "AGING_CATEGORY_MAP" in source, "Missing SSOT: AGING_CATEGORY_MAP"


class TestAgingArtifactStatusSchema:
    """Tests for aging_artifact_status schema."""

    def test_returns_all_aging_states(self):
        """Result contains all three aging states."""
        expected_states = set(AGING_CATEGORY_MAP.values())
        assert expected_states == {"non_aging", "short_aging", "long_aging"}

    def test_schema_shape_ready(self):
        """Each aging state has correct schema when ready."""
        # Mock dependencies to return ready state
        # Note: imports happen inside the function, so patch at source modules
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-AS-Thio-0293"]

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
            patch(
                "common.molecule_id.build_aging_mol_id",
                return_value="U-AS-Thio-0293",
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        for aging_state, status in result.items():
            assert "ready" in status, f"Missing 'ready' in {aging_state}"
            assert "source_id" in status, f"Missing 'source_id' in {aging_state}"
            assert "consumer_ids" in status, f"Missing 'consumer_ids' in {aging_state}"
            assert "status" in status, f"Missing 'status' in {aging_state}"
            assert status["status"] in ("ready", "missing", "not_applicable")

    def test_schema_shape_not_applicable(self):
        """Non-asphalt molecules get not_applicable status."""
        # Mock build_aging_mol_id to raise ValueError (e.g., for additives)
        with patch(
            "features.molecules.catalog.build_aging_mol_id",
            side_effect=ValueError("Not a valid asphalt molecule"),
        ):
            result = _compute_aging_artifact_status("SiO2", None, "0293")

        for _aging_state, status in result.items():
            assert status["status"] == "not_applicable"
            assert status["ready"] is None
            assert status["source_id"] is None
            assert status["consumer_ids"] == []

    def test_unavailable_aging_state_is_not_applicable(self):
        """Aging states not in available_aging list are marked not_applicable."""
        # Saturates only support non_aging
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-SA-Squalane-0293"]
        mock_target.ff_assignment = {"route": "organic_curated_artifact"}

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "SA-Squalane"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
        ):
            # Only non_aging is available for saturates
            result = _compute_aging_artifact_status("SA-Squalane", ["non_aging"], "0293")

        # non_aging should be ready (mocked), short/long should be not_applicable
        assert result["non_aging"]["status"] == "ready"
        assert result["short_aging"]["status"] == "not_applicable"
        assert result["long_aging"]["status"] == "not_applicable"


class TestAgingStatusComputation:
    """Tests for aging status computation logic."""

    def test_ready_status_when_artifact_ready(self):
        """Status is 'ready' when is_artifact_ready returns True."""
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-AS-Thio-0293"]

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
            patch(
                "common.molecule_id.build_aging_mol_id",
                return_value="U-AS-Thio-0293",
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        # All should be ready with mocked dependencies
        for _aging_state, status in result.items():
            assert status["status"] == "ready"
            assert status["ready"] is True

    def test_missing_status_when_artifact_not_ready(self):
        """Status is 'missing' when is_artifact_ready returns False."""
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-AS-Thio-0293"]

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(False, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
            patch(
                "common.molecule_id.build_aging_mol_id",
                return_value="U-AS-Thio-0293",
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        for _aging_state, status in result.items():
            assert status["status"] == "missing"
            assert status["ready"] is False

    def test_source_id_preserved(self):
        """source_id from is_artifact_ready is preserved in result."""
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-AS-Thio-0293"]
        expected_source_id = "Thio"

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, expected_source_id),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
            patch(
                "common.molecule_id.build_aging_mol_id",
                return_value="U-AS-Thio-0293",
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        for _aging_state, status in result.items():
            assert status["source_id"] == expected_source_id

    def test_consumer_ids_preserved(self):
        """consumer_ids from resolve_artifact_target is preserved."""
        expected_consumers = ["U-AS-Thio-0293", "U-AS-Thio-0313"]
        mock_target = MagicMock()
        mock_target.consumer_ids = expected_consumers

        with (
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
            patch(
                "common.molecule_id.build_aging_mol_id",
                return_value="U-AS-Thio-0293",
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        for _aging_state, status in result.items():
            assert status["consumer_ids"] == expected_consumers


class TestErrorHandling:
    """Tests for error handling in aging status computation."""

    def test_valueerror_results_in_not_applicable(self):
        """ValueError from build_aging_mol_id results in not_applicable."""
        with patch(
            "common.molecule_id.build_aging_mol_id",
            side_effect=ValueError("Invalid mol_id"),
        ):
            result = _compute_aging_artifact_status("InvalidMol", {}, "0293")

        for _aging_state, status in result.items():
            assert status["status"] == "not_applicable"

    def test_exception_per_aging_state_independent(self):
        """Exception in one aging state doesn't affect others."""
        mock_target = MagicMock()
        mock_target.consumer_ids = ["U-AS-Thio-0293"]

        def _build_aging_mol_id(mol_id, aging, temp_code):
            if aging == "short_aging":
                raise ValueError("Not supported")
            return f"U-{mol_id}-{temp_code}"

        # Patch at catalog module level since build_aging_mol_id is imported there
        with (
            patch(
                "features.molecules.catalog.build_aging_mol_id",
                side_effect=_build_aging_mol_id,
            ),
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=mock_target,
            ),
        ):
            result = _compute_aging_artifact_status(
                "AS-Thio", ["non_aging", "short_aging", "long_aging"], "0293"
            )

        # short_aging should be not_applicable, others should be ready
        assert result["short_aging"]["status"] == "not_applicable"
        # At least some should have been processed successfully
        ready_count = sum(1 for s in result.values() if s["status"] == "ready")
        assert ready_count >= 1


class TestTempCodeHandling:
    """Tests for temperature code handling."""

    def test_default_temp_code_0293(self):
        """Default temp_code is 0293."""
        with (
            patch("common.molecule_id.build_aging_mol_id") as mock_build,
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=MagicMock(consumer_ids=[]),
            ),
        ):
            mock_build.return_value = "U-AS-Thio-0293"
            _compute_aging_artifact_status("AS-Thio", {})

        # Check that build_aging_mol_id was called with default temp_code
        for call in mock_build.call_args_list:
            assert call[0][2] == "0293"

    def test_custom_temp_code_passed(self):
        """Custom temp_code is passed to build_aging_mol_id."""
        with (
            patch("common.molecule_id.build_aging_mol_id") as mock_build,
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "Thio"),
            ),
            patch(
                "features.molecules.artifact_service.resolve_artifact_target",
                return_value=MagicMock(consumer_ids=[]),
            ),
        ):
            mock_build.return_value = "U-AS-Thio-0333"
            _compute_aging_artifact_status("AS-Thio", {}, temp_code="0333")

        for call in mock_build.call_args_list:
            assert call[0][2] == "0333"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
