"""Shared mock LLM client for sync and async code paths."""

import json
from typing import Any


class MockLLMClient:
    """Mock LLM client with backward-compatible sync/async APIs."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self._response_index = 0
        self._chat_responses: list[dict[str, Any]] = []
        self._call_count = 0

    def set_response(self, response: dict[str, Any]) -> None:
        """Queue a response for sync chat() calls."""
        self._chat_responses.append(response)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Return queued async response payload."""
        _ = (system_prompt, user_message, temperature, max_tokens)
        if self._response_index < len(self.responses):
            response = self.responses[self._response_index]
            self._response_index += 1
            return response
        return "{}"

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return queued async response payload with no tool calls."""
        _ = tools
        response = await self.generate(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response, []

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Mock multi-turn tool calling — delegates to generate_with_tools."""
        _ = (system_prompt, temperature, max_tokens)
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        text, tool_calls_raw = await self.generate_with_tools(
            system_prompt=system_prompt,
            user_message=last_user,
            tools=tools,
        )
        # Normalize to common format: [{"id": ..., "name": ..., "input": {...}}]
        normalized: list[dict[str, Any]] = []
        for tc in tool_calls_raw:
            if "function" in tc:
                fn = tc["function"]
                args = fn.get("arguments", "{}")
                normalized.append(
                    {
                        "id": tc.get("id", "mock_call"),
                        "name": fn.get("name", ""),
                        "input": json.loads(args) if isinstance(args, str) else args,
                    }
                )
            else:
                normalized.append(tc)
        return text, normalized

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return a deterministic sync response for the provider-client probe."""
        _ = (tools, kwargs)
        self._call_count += 1

        if self._chat_responses:
            return self._chat_responses.pop(0)

        last_user_msg = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        msg_lower = str(last_user_msg).lower()

        if "recommend" in msg_lower:
            return {
                "content": "I'll recommend some compositions for you.",
                "tool_calls": [
                    {
                        "id": f"call_{self._call_count}",
                        "type": "function",
                        "function": {
                            "name": "recommend_composition",
                            "arguments": json.dumps(
                                {
                                    "objectives": [
                                        {"name": "cohesive_energy_density", "direction": "maximize"}
                                    ],
                                    "n_recommendations": 3,
                                }
                            ),
                        },
                    }
                ],
            }

        if "predict" in msg_lower:
            return {
                "content": "I'll predict the properties for that composition.",
                "tool_calls": [
                    {
                        "id": f"call_{self._call_count}",
                        "type": "function",
                        "function": {
                            "name": "predict_properties",
                            "arguments": json.dumps(
                                {
                                    "composition": {
                                        "asphaltene": 20,
                                        "resin": 30,
                                        "aromatic": 35,
                                        "saturate": 15,
                                    },
                                    "properties": ["density", "cohesive_energy_density"],
                                }
                            ),
                        },
                    }
                ],
            }

        return {
            "content": "I can help with asphalt binder simulations and recommendations.",
            "tool_calls": None,
        }
