"""Tests for settings propagation: env sync, cache invalidation, masking, validation."""

import os
from unittest.mock import patch

import pytest

from api.schemas import SettingsUpdateRequest

# ---------------------------------------------------------------------------
# Fix 1+2: update_settings triggers reset_settings on LLM config change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_settings_provider_change_triggers_resets():
    """Changing llm_provider triggers reset_settings()."""
    fake_settings = {
        "llm_provider": "mock",
        "llm_api_key": "",
        "llm_model": "",
        "selected_gpus": [],
    }

    with (
        patch(
            "config.dashboard_settings.load_dashboard_settings",
            return_value=fake_settings.copy(),
        ),
        patch("config.dashboard_settings.save_dashboard_settings"),
        patch("config.settings.reset_settings") as mock_reset_settings,
    ):
        from features.system.service import update_settings

        result = await update_settings({"llm_provider": "openai", "llm_api_key": "sk-test123"})

        mock_reset_settings.assert_called_once()
        assert result["status"] == "updated"


@pytest.mark.asyncio
async def test_update_settings_api_key_only_change_triggers_resets():
    """Changing only llm_api_key (same provider) triggers env propagation + cache invalidation."""
    fake_settings = {
        "llm_provider": "openai",
        "llm_api_key": "sk-old",
        "llm_model": "gpt-4o-mini",
        "selected_gpus": [],
    }

    with (
        patch(
            "config.dashboard_settings.load_dashboard_settings",
            return_value=fake_settings.copy(),
        ),
        patch("config.dashboard_settings.save_dashboard_settings"),
        patch("config.settings.reset_settings") as mock_reset_settings,
    ):
        from features.system.service import update_settings

        await update_settings({"llm_api_key": "sk-new"})

        mock_reset_settings.assert_called_once()
        assert os.environ.get("LLM_OPENAI_API_KEY") == "sk-new"

    # Cleanup
    os.environ.pop("LLM_OPENAI_API_KEY", None)
    os.environ.pop("LLM_PROVIDER", None)


# ---------------------------------------------------------------------------
# Fix 3: API key masking in get_settings response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_masks_api_key():
    """GET /settings response should mask the API key."""
    fake_settings = {
        "agent_mode": "real",
        "llm_provider": "openai",
        "llm_api_key": "sk-proj-abcdefgh1234",
        "llm_model": "gpt-4o-mini",
    }

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from features.system.service import get_settings

        result = await get_settings()

        assert result["llm_api_key"] == "***1234"
        # Original should NOT leak
        assert "sk-proj" not in result["llm_api_key"]


@pytest.mark.asyncio
async def test_get_settings_masks_short_api_key():
    """Short API keys should be fully masked."""
    fake_settings = {
        "agent_mode": "mock",
        "llm_provider": "mock",
        "llm_api_key": "abc",
        "llm_model": "",
    }

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from features.system.service import get_settings

        result = await get_settings()

        assert result["llm_api_key"] == "****"


@pytest.mark.asyncio
async def test_get_settings_empty_api_key():
    """Empty API key should remain empty string."""
    fake_settings = {
        "agent_mode": "mock",
        "llm_provider": "mock",
        "llm_api_key": "",
        "llm_model": "",
    }

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from features.system.service import get_settings

        result = await get_settings()

        assert result["llm_api_key"] == ""


@pytest.mark.asyncio
async def test_get_settings_exposes_default_e_intra_method():
    """GET /settings response should include the submission-default method key."""
    fake_settings = {
        "agent_mode": "mock",
        "llm_provider": "mock",
        "llm_api_key": "",
        "llm_model": "",
        "default_e_intra_method": "single_molecule_vacuum_adaptive_cutoff",
    }

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from features.system.service import get_settings

        result = await get_settings()

        assert result["default_e_intra_method"] == "single_molecule_vacuum_adaptive_cutoff"


# ---------------------------------------------------------------------------
# Fix 4: _restore_settings_from_json
# ---------------------------------------------------------------------------


def test_restore_settings_from_json_sets_env_when_missing():
    """settings.json values should be restored when env vars are not set."""
    fake_settings = {
        "llm_provider": "openai",
        "llm_api_key": "sk-restore-test",
        "llm_model": "gpt-4o",
    }

    # Clear any existing env vars
    for key in ("LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from api.application import _restore_settings_from_json

        _restore_settings_from_json()

        assert os.environ.get("LLM_PROVIDER") == "openai"
        assert os.environ.get("LLM_OPENAI_API_KEY") == "sk-restore-test"
        assert os.environ.get("LLM_OPENAI_MODEL") == "gpt-4o"

    # Cleanup
    for key in ("LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)


def test_restore_settings_respects_existing_env_vars():
    """Existing env vars should NOT be overwritten (setdefault behavior)."""
    fake_settings = {
        "llm_provider": "anthropic",
        "llm_api_key": "sk-from-json",
        "llm_model": "claude-3",
    }

    os.environ["LLM_PROVIDER"] = "openai"

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from api.application import _restore_settings_from_json

        _restore_settings_from_json()

        # Existing values should be preserved
        assert os.environ.get("LLM_PROVIDER") == "openai"

    # Cleanup
    for key in (
        "LLM_PROVIDER",
        "LLM_ANTHROPIC_API_KEY",
        "LLM_ANTHROPIC_MODEL",
    ):
        os.environ.pop(key, None)


def test_restore_settings_mock_mode_skips_env():
    """Mock mode should not set the LLM_PROVIDER env var."""
    fake_settings = {
        "llm_provider": "mock",
        "llm_api_key": "",
        "llm_model": "",
    }

    os.environ.pop("LLM_PROVIDER", None)

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from api.application import _restore_settings_from_json

        _restore_settings_from_json()

        assert "LLM_PROVIDER" not in os.environ


# ---------------------------------------------------------------------------
# Fix 6: SettingsUpdateRequest validation
# ---------------------------------------------------------------------------


def test_settings_update_request_rejects_invalid_llm_provider():
    """Invalid llm_provider values should be rejected."""
    with pytest.raises(ValueError, match="Invalid llm_provider"):
        SettingsUpdateRequest(llm_provider="gemini")


def test_settings_update_request_accepts_valid_values():
    """Valid settings should pass validation."""
    req = SettingsUpdateRequest(
        llm_provider="openai",
        llm_api_key="sk-test",
        llm_model="gpt-4o",
        gpu_enabled=True,
        max_concurrent_jobs=4,
    )
    assert req.llm_provider == "openai"
    assert req.llm_model == "gpt-4o"


def test_settings_update_request_none_fields_excluded():
    """None fields should be excluded with exclude_none=True."""
    req = SettingsUpdateRequest(llm_provider="openai")
    dumped = req.model_dump(exclude_none=True)
    assert dumped == {"llm_provider": "openai"}
    assert "llm_api_key" not in dumped
    assert "llm_model" not in dumped


# ---------------------------------------------------------------------------
# Fix: masked API key should NOT overwrite real key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_settings_masked_api_key_preserves_real_key():
    """Sending masked API key (e.g. '***kL4A') should not overwrite the real key."""
    real_key = "sk-proj-abcdefghijklmnop"
    fake_settings = {
        "agent_mode": "real",
        "llm_provider": "openai",
        "llm_api_key": real_key,
        "llm_model": "gpt-4o-mini",
        "selected_gpus": [],
        "max_concurrent_jobs": 4,
    }
    saved = {}

    def _save(settings: dict) -> None:
        saved.update(settings)

    with (
        patch(
            "config.dashboard_settings.load_dashboard_settings",
            return_value=fake_settings.copy(),
        ),
        patch("config.dashboard_settings.save_dashboard_settings", side_effect=_save),
    ):
        from features.system.service import update_settings

        # Frontend sends back masked key with an unrelated change
        await update_settings({"llm_api_key": "***mnop", "max_concurrent_jobs": 2})

    # Real key must be preserved, not overwritten with masked value
    assert saved["llm_api_key"] == real_key
    assert saved["max_concurrent_jobs"] == 2


def test_restore_settings_ignores_masked_api_key():
    """Masked API key in settings.json should not be applied as env var."""
    fake_settings = {
        "agent_mode": "real",
        "llm_provider": "openai",
        "llm_api_key": "***kL4A",
        "llm_model": "gpt-4o",
    }

    for key in ("AGENT_MODE", "LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)

    with patch(
        "config.dashboard_settings.load_dashboard_settings",
        return_value=fake_settings.copy(),
    ):
        from api.application import _restore_settings_from_json

        _restore_settings_from_json()

        # Masked key should NOT be set as env var
        assert os.environ.get("LLM_OPENAI_API_KEY") is None
        # Model should still be set
        assert os.environ.get("LLM_OPENAI_MODEL") == "gpt-4o"

    # Cleanup
    for key in ("AGENT_MODE", "LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)


@pytest.mark.asyncio
async def test_update_settings_rejects_invalid_api_key_string():
    """Error-message-like API keys must be ignored to prevent bad persistence."""
    fake_settings = {
        "agent_mode": "real",
        "llm_provider": "openai",
        "llm_api_key": "sk-real-1234",
        "llm_model": "gpt-4o-mini",
        "selected_gpus": [],
    }
    saved = {}

    def _save(settings: dict) -> None:
        saved.update(settings)

    with (
        patch(
            "config.dashboard_settings.load_dashboard_settings",
            return_value=fake_settings.copy(),
        ),
        patch("config.dashboard_settings.save_dashboard_settings", side_effect=_save),
    ):
        from features.system.service import update_settings

        await update_settings(
            {
                "llm_api_key": (
                    "Error: Geocoding returned no results for location '서울'. "
                    "Try a more specific location name."
                )
            }
        )

    assert saved["llm_api_key"] == "sk-real-1234"


def test_restore_settings_ignores_invalid_non_ascii_api_key():
    """Invalid non-ASCII error text in settings.json should be cleared and not applied."""
    fake_settings = {
        "agent_mode": "real",
        "llm_provider": "openai",
        "llm_api_key": (
            "Error: Geocoding returned no results for location '서울'. "
            "Try a more specific location name."
        ),
        "llm_model": "gpt-4o",
    }
    saved = {}

    def _save(settings: dict) -> None:
        saved.update(settings)

    for key in ("AGENT_MODE", "LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)

    with (
        patch(
            "config.dashboard_settings.load_dashboard_settings",
            return_value=fake_settings.copy(),
        ),
        patch("config.dashboard_settings.save_dashboard_settings", side_effect=_save),
    ):
        from api.application import _restore_settings_from_json

        _restore_settings_from_json()

    assert os.environ.get("LLM_OPENAI_API_KEY") is None
    assert os.environ.get("LLM_OPENAI_MODEL") == "gpt-4o"
    assert saved["llm_api_key"] == ""

    for key in ("AGENT_MODE", "LLM_PROVIDER", "LLM_OPENAI_API_KEY", "LLM_OPENAI_MODEL"):
        os.environ.pop(key, None)
