"""Tests for Codex-recommended improvements (v00.93.42).

Covers:
- LLM operational mode hardening (#14)
- Evidence traceability (#15)
- DetailedHealthResponse schema (#14)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Task #14 — LLM operational mode hardening
# ---------------------------------------------------------------------------


class TestLLMOperationalHardening:
    """Non-mock LLM provider failure must NOT silently degrade to mock."""

    def test_health_check_llm_status_mock(self):
        """Health check reports llm_status=mock when provider is mock."""
        from features.health.service import _get_llm_status

        mock_settings = SimpleNamespace(llm=SimpleNamespace(provider="mock"))

        with patch("config.settings.get_settings", return_value=mock_settings):
            assert _get_llm_status() == "mock"

    def test_health_check_llm_status_degraded(self):
        """Health check reports degraded when real provider init fails."""
        from features.health.service import _get_llm_status

        mock_settings = SimpleNamespace(
            llm=SimpleNamespace(
                provider="anthropic",
                anthropic_api_key=None,
                anthropic_model=None,
                temperature=0.7,
                max_tokens=1024,
            )
        )

        with (
            patch("config.settings.get_settings", return_value=mock_settings),
            patch(
                "llm.client_factory.create_llm_client",
                side_effect=RuntimeError("no key"),
            ),
        ):
            assert _get_llm_status() == "degraded"


# ---------------------------------------------------------------------------
# Task #15 — Evidence traceability
# ---------------------------------------------------------------------------


class TestDetailedHealthResponseSchema:
    """DetailedHealthResponse includes llm_status field."""

    def test_llm_status_field_present(self):
        """llm_status field should be in DetailedHealthResponse."""
        from api.schemas import DetailedHealthResponse

        resp = DetailedHealthResponse(
            status="ready",
            version="0.93.42",
            database="connected",
            lammps="not_checked",
            llm_status="ok",
        )
        assert resp.llm_status == "ok"

    def test_llm_status_defaults_to_mock(self):
        """llm_status defaults to 'mock' when not provided."""
        from api.schemas import DetailedHealthResponse

        resp = DetailedHealthResponse(
            status="ready",
            version="0.93.42",
            database="connected",
            lammps="not_checked",
        )
        assert resp.llm_status == "mock"
