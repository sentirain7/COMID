"""
LLM Integration Module for Asphalt Binder Agent.

This package now exposes only the provider-client layer used by the health
probe (``features/health/service._get_llm_status`` → ``create_llm_client``).

v01.05.x simplification history:
- The dual-agent debate stack, the orphaned training/VoI cluster, and the
  coverage_analyzer/road_advisor_prompts modules were removed.
- The function-calling stack (``function_executor``, ``function_schemas``,
  ``conversation``) was removed: nothing in the codebase invokes an LLM, so the
  executor/schemas/conversation scaffolding had zero live callers. Only the
  provider client (mock/anthropic/openai) survives, for the settings health
  probe. Decision rules live in docs/DECISION_RULES.md and contracts/policies/.
"""

from .client_factory import create_llm_client
from .mock_client import MockLLMClient
from .provider_clients import AnthropicLLMClient, OpenAILLMClient

__all__ = [
    "create_llm_client",
    "MockLLMClient",
    "AnthropicLLMClient",
    "OpenAILLMClient",
]
