"""Dashboard settings service."""

from common.logging import get_logger
from contracts.schema_enums import EIntraMethod

logger = get_logger("features.system")


def _mask_api_key(api_key: str) -> str:
    """Mask an API key for safe display, showing only the last 4 characters."""
    if api_key and len(api_key) > 4:
        return "***" + api_key[-4:]
    if api_key:
        return "****"
    return ""


def _is_masked(value: str) -> bool:
    """Return True if value looks like a masked API key (e.g. '***kL4A')."""
    return bool(value) and value.startswith("***")


def _save_provider_slot(settings: dict, provider: str) -> None:
    """현재 llm_api_key/llm_model을 provider별 슬롯에 보존."""
    key = settings.get("llm_api_key", "")
    model = settings.get("llm_model", "")
    if key and not _is_masked(key):
        settings[f"llm_{provider}_api_key"] = key
    if model:
        settings[f"llm_{provider}_model"] = model


def _restore_provider_slot(settings: dict, provider: str) -> None:
    """provider별 슬롯에서 llm_api_key/llm_model 복원."""
    saved_key = settings.get(f"llm_{provider}_api_key", "")
    saved_model = settings.get(f"llm_{provider}_model", "")
    if saved_key and not _is_masked(saved_key):
        settings["llm_api_key"] = saved_key
    if saved_model:
        settings["llm_model"] = saved_model


def _save_provider_slot_key(settings: dict, provider: str, api_key: str) -> None:
    """API key를 provider별 슬롯에 저장."""
    if provider in ("openai", "anthropic") and api_key and not _is_masked(api_key):
        settings[f"llm_{provider}_api_key"] = api_key


def _save_provider_slot_model(settings: dict, provider: str, model: str) -> None:
    """Model을 provider별 슬롯에 저장."""
    if provider in ("openai", "anthropic") and model:
        settings[f"llm_{provider}_model"] = model


async def get_settings() -> dict:
    """Get current dashboard settings with API key masked."""
    from config.dashboard_settings import load_dashboard_settings

    settings = load_dashboard_settings().copy()
    settings["llm_api_key"] = _mask_api_key(settings.get("llm_api_key", ""))
    return settings


async def update_settings(data: dict) -> dict[str, object]:
    """Update dashboard settings (persisted to file)."""
    import os

    from config.dashboard_settings import (
        apply_llm_env_vars,
        is_plausible_llm_api_key,
        load_dashboard_settings,
        save_dashboard_settings,
    )

    settings = load_dashboard_settings()
    settings.setdefault(
        "default_e_intra_method",
        EIntraMethod.SINGLE_MOLECULE_VACUUM.value,
    )
    previous_selected = list(settings.get("selected_gpus", []))
    previous_llm_provider = settings.get("llm_provider", "mock")
    previous_llm_api_key = settings.get("llm_api_key", "")
    previous_llm_model = settings.get("llm_model", "")

    # Provider 전환 시: 현재 provider의 key/model을 provider별 슬롯에 저장
    new_provider = data.get("llm_provider")
    if new_provider and new_provider != previous_llm_provider:
        # 현재 값을 이전 provider 슬롯에 보존
        if previous_llm_provider in ("openai", "anthropic"):
            _save_provider_slot(settings, previous_llm_provider)
        # 새 provider 슬롯에서 복원
        if new_provider in ("openai", "anthropic"):
            _restore_provider_slot(settings, new_provider)

    for key, value in data.items():
        if key in settings:
            # Skip masked API keys — the frontend always receives masked values,
            # so writing them back would destroy the real key.
            if key == "llm_api_key" and _is_masked(value):
                continue
            # 빈 문자열 API key/model은 기존 값 유지 (의도치 않은 초기화 방지)
            if key == "llm_api_key" and not value:
                continue
            if key == "llm_model" and value is not None and str(value).strip() == "":
                continue
            if key == "llm_api_key" and value:
                provider = str(data.get("llm_provider", settings.get("llm_provider", "mock")))
                if not is_plausible_llm_api_key(provider, value):
                    logger.warning("Rejected invalid llm_api_key update for provider=%s", provider)
                    continue
                # provider별 슬롯에도 동시 저장
                _save_provider_slot_key(settings, provider, value)
            if key == "llm_model" and value:
                provider = str(data.get("llm_provider", settings.get("llm_provider", "mock")))
                _save_provider_slot_model(settings, provider, str(value).strip())
            settings[key] = value
    save_dashboard_settings(settings)

    new_llm_provider = settings.get("llm_provider", "mock")
    llm_config_changed = (
        new_llm_provider != previous_llm_provider
        or settings.get("llm_api_key", "") != previous_llm_api_key
        or settings.get("llm_model", "") != previous_llm_model
    )
    if llm_config_changed:
        os.environ["LLM_PROVIDER"] = new_llm_provider
        llm_api_key = settings.get("llm_api_key", "")
        llm_model = settings.get("llm_model", "")
        apply_llm_env_vars(new_llm_provider, llm_api_key, llm_model, use_setdefault=False)

        try:
            from config.settings import reset_settings

            reset_settings()
            logger.info("Pydantic Settings cache invalidated after LLM config change")
        except Exception as e:
            logger.warning(f"Failed to reset settings cache: {e}")

    if previous_selected != list(settings.get("selected_gpus", [])):
        try:
            from api.deps import clear_gpu_tracker_cache

            clear_gpu_tracker_cache()
            logger.info("GPU tracker cache cleared due to selected_gpus change")
        except Exception as e:
            logger.warning(f"Failed to clear GPU tracker cache after settings update: {e}")

    response_settings = settings.copy()
    response_settings["llm_api_key"] = _mask_api_key(response_settings.get("llm_api_key", ""))
    return {"status": "updated", "settings": response_settings}
