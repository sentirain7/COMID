"""Dashboard settings — single source for settings.json read/write.

Consolidates the 4 independent settings.json readers:
- api/main.py (_load_settings / _save_settings / _dashboard_settings)
- orchestrator/celery_app.py (_get_selected_gpu_count)
- orchestrator/gpu_service.py (GPUService._load_selected_gpus)
- orchestrator/resource_manager.py (_initialize_resource_manager)

Default values are derived from contracts/policies/dashboard.py (SSOT).
"""

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from common.logging import get_logger
from contracts.policies.dashboard import DEFAULT_DASHBOARD_POLICY
from contracts.schema_enums import EIntraMethod, coerce_e_intra_method

logger = get_logger("config.dashboard_settings")

# Settings file path (project root / settings.json)
_SETTINGS_FILE = Path(__file__).parent.parent.parent / "settings.json"

# Default settings derived from SSOT (DashboardPolicy)
_POLICY_DEFAULTS: dict[str, Any] = asdict(DEFAULT_DASHBOARD_POLICY)
# Add selected_gpus (runtime-only, not in policy)
_POLICY_DEFAULTS["selected_gpus"] = []
# LLM provider settings (UI-configurable, env vars override)
_POLICY_DEFAULTS["llm_provider"] = "mock"
_POLICY_DEFAULTS["llm_api_key"] = ""
_POLICY_DEFAULTS["llm_model"] = ""
# Provider별 API key/model 분리 저장 (provider 전환 시 기존 값 보존)
_POLICY_DEFAULTS["llm_openai_api_key"] = ""
_POLICY_DEFAULTS["llm_openai_model"] = ""
_POLICY_DEFAULTS["llm_anthropic_api_key"] = ""
_POLICY_DEFAULTS["llm_anthropic_model"] = ""
_POLICY_DEFAULTS["default_e_intra_method"] = EIntraMethod.SINGLE_MOLECULE_VACUUM.value


def is_plausible_llm_api_key(provider: str, api_key: str) -> bool:
    """Return True when API key looks valid enough to apply."""
    if not api_key:
        return False

    stripped = api_key.strip()
    if stripped != api_key:
        return False

    if not stripped.isascii():
        return False

    if any(ch.isspace() for ch in stripped):
        return False

    lowered = stripped.lower()
    if lowered.startswith("error:") or "returned no results" in lowered:
        return False

    normalized = (provider or "").strip().lower()
    if normalized == "openai":
        return stripped.startswith("sk-")
    if normalized == "anthropic":
        return stripped.startswith("sk-ant-")

    return False


def get_settings_file_path() -> Path:
    """Return the settings.json file path."""
    return _SETTINGS_FILE


def load_dashboard_settings() -> dict[str, Any]:
    """Load settings from settings.json, merged with policy defaults.

    Returns:
        Merged settings dict (policy defaults + saved overrides)
    """
    defaults = _POLICY_DEFAULTS.copy()
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE) as f:
                saved = json.load(f)
            merged = {**defaults, **saved}
            merged["default_e_intra_method"] = (
                coerce_e_intra_method(merged.get("default_e_intra_method")).value
                if merged.get("default_e_intra_method")
                else defaults["default_e_intra_method"]
            )
            return merged
        except Exception as e:
            logger.warning(f"Failed to load settings.json: {e}")
    return defaults


def resolve_submission_e_intra_method(
    request_override: str | EIntraMethod | None = None,
) -> EIntraMethod:
    """Resolve the E_intra method for a new submission.

    Precedence:
    1. explicit request override
    2. settings.json ``default_e_intra_method``
    3. legacy env fallback (Method 1a flag)
    4. Method 1 baseline
    """
    if request_override is not None:
        method = coerce_e_intra_method(request_override)
        if method is EIntraMethod.SINGLE_MOLECULE_PERIODIC:
            logger.warning(
                "Ignoring reserved submission override e_intra_method=%r; "
                "falling back to supported submission methods",
                request_override,
            )
        else:
            return method

    configured = load_dashboard_settings().get("default_e_intra_method")
    if configured:
        try:
            method = coerce_e_intra_method(configured)
            if method is EIntraMethod.SINGLE_MOLECULE_PERIODIC:
                logger.warning(
                    "Ignoring reserved settings.json default_e_intra_method=%r; "
                    "Method 2 remains deferred for public submissions",
                    configured,
                )
            else:
                return method
        except ValueError:
            logger.warning("Ignoring invalid settings.json default_e_intra_method=%r", configured)

    from protocols.lammps_force_field import vacuum_extended_cutoff_enabled

    if vacuum_extended_cutoff_enabled():
        return EIntraMethod.SINGLE_MOLECULE_VACUUM_ADAPTIVE_CUTOFF

    return EIntraMethod.SINGLE_MOLECULE_VACUUM


def save_dashboard_settings(settings: dict[str, Any]) -> None:
    """Persist settings to settings.json.

    Args:
        settings: Settings dict to save
    """
    try:
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        logger.info(f"Settings saved to {_SETTINGS_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save settings.json: {e}")


def apply_llm_env_vars(
    provider: str,
    api_key: str,
    model: str,
    *,
    use_setdefault: bool = False,
) -> None:
    """Apply provider-specific LLM env vars.

    Args:
        provider: LLM provider name ("openai" or "anthropic")
        api_key: Provider API key
        model: Provider model name
        use_setdefault: If True, preserve existing env values
    """

    def _set_env(key: str, value: str) -> None:
        if not value:
            return
        if use_setdefault:
            os.environ.setdefault(key, value)
        else:
            os.environ[key] = value

    normalized = (provider or "").strip().lower()
    if api_key and not is_plausible_llm_api_key(normalized, api_key):
        logger.warning("Skipping invalid %s API key from settings/env sync", normalized or "LLM")
        api_key = ""

    if normalized == "openai":
        _set_env("LLM_OPENAI_API_KEY", api_key)
        _set_env("LLM_OPENAI_MODEL", model)
    elif normalized == "anthropic":
        _set_env("LLM_ANTHROPIC_API_KEY", api_key)
        _set_env("LLM_ANTHROPIC_MODEL", model)


def get_selected_gpus() -> list[int]:
    """Read selected_gpus from settings.json.

    Returns:
        List of selected GPU IDs (empty list = all available)
    """
    settings = load_dashboard_settings()
    return settings.get("selected_gpus", [])


def get_selected_gpu_count() -> int:
    """Get number of selected GPUs with dynamic detection fallback.

    Priority:
    1. settings.json selected_gpus (if non-empty)
    2. Dynamically detected system GPUs
    3. Minimum 1 (CPU-only mode)

    Returns:
        Number of GPUs (minimum 1)
    """
    gpus = get_selected_gpus()
    if gpus:
        return len(gpus)

    # Fallback to dynamic GPU detection (eligible compute GPUs only — excludes
    # sub-threshold display/consumer GPUs so they are not counted as job slots).
    try:
        from monitoring.gpu_collector import detect_eligible_compute_gpus

        detected = detect_eligible_compute_gpus()
        if detected:
            logger.info(f"Using detected eligible GPU count: {len(detected)}")
            return len(detected)
    except Exception as e:
        logger.warning(f"Failed to detect GPUs: {e}")

    logger.info("No GPUs detected or configured, using count=1")
    return 1
