"""Factory helpers for LLM clients used by recommendation debate."""

from common.logging import get_logger
from config.settings import get_settings

from .mock_client import MockLLMClient
from .provider_clients import AnthropicLLMClient, OpenAILLMClient

logger = get_logger("llm.client_factory")


def create_llm_client(
    provider: str | None = None,
    responses: list[str] | None = None,
):
    """Create an LLM client based on settings/provider override."""
    settings = get_settings()
    selected = (provider or settings.llm.provider or "mock").lower()

    if selected == "mock":
        return MockLLMClient(responses=responses)

    if selected == "anthropic":
        if not settings.llm.anthropic_api_key:
            raise RuntimeError(
                "LLM provider anthropic selected but LLM_ANTHROPIC_API_KEY is missing"
            )
        return AnthropicLLMClient(
            api_key=settings.llm.anthropic_api_key,
            model=settings.llm.anthropic_model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )

    if selected == "openai":
        if not settings.llm.openai_api_key:
            raise RuntimeError("LLM provider openai selected but LLM_OPENAI_API_KEY is missing")
        return OpenAILLMClient(
            api_key=settings.llm.openai_api_key,
            model=settings.llm.openai_model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )

    raise RuntimeError(f"Unknown LLM provider: {selected}")
