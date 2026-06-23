"""Real LLM provider client adapters."""

from typing import Any


class AnthropicLLMClient:
    """Anthropic async adapter with dual-agent compatible interface."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 2048,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_key = api_key

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("anthropic package is not installed") from exc

        self._client = AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        response = await self._client.messages.create(
            model=self.model,
            system=system_prompt,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            messages=[{"role": "user", "content": user_message}],
        )
        text_chunks = []
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                text_chunks.append(getattr(block, "text", ""))
        return "".join(text_chunks).strip() or "{}"

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        _ = tools
        text = await self.generate(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text, []

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Multi-turn conversation with tool calling (Anthropic native format).

        Args:
            system_prompt: System instruction.
            messages: Full conversation history in Anthropic message format.
            tools: Tool definitions in OpenAI format (auto-converted).
            temperature: Sampling temperature.
            max_tokens: Max response tokens.

        Returns:
            (text_response, tool_calls) where tool_calls follow Anthropic format:
            [{"id": ..., "name": ..., "input": {...}}, ...]
        """
        # Convert OpenAI-style tools to Anthropic format
        anthropic_tools = []
        for tool in tools:
            fn = tool.get("function", {})
            anthropic_tools.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )

        response = await self._client.messages.create(
            model=self.model,
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
            tools=anthropic_tools,
        )

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append(
                    {
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    }
                )

        return "".join(text_parts).strip(), tool_calls

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Sync wrapper implementing LLMClientPort for intent extraction."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")

        async def _call() -> dict[str, Any]:
            # Convert OpenAI-style tools to Anthropic format
            anthropic_tools = None
            if tools:
                anthropic_tools = []
                for tool in tools:
                    fn = tool.get("function", {})
                    anthropic_tools.append(
                        {
                            "name": fn.get("name", ""),
                            "description": fn.get("description", ""),
                            "input_schema": fn.get(
                                "parameters", {"type": "object", "properties": {}}
                            ),
                        }
                    )

            kwargs: dict[str, Any] = {
                "model": self.model,
                "system": system,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": user_msg}],
            }
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools

            response = await self._client.messages.create(**kwargs)
            # Return Anthropic format for _parse_tool_call_response
            content: list[dict[str, Any]] = []
            for block in getattr(response, "content", []):
                if getattr(block, "type", None) == "text":
                    content.append({"type": "text", "text": getattr(block, "text", "")})
                elif getattr(block, "type", None) == "tool_use":
                    content.append(
                        {
                            "type": "tool_use",
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": getattr(block, "input", {}),
                        }
                    )
            return {"content": content}

        with ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, _call()).result()


class OpenAILLMClient:
    """OpenAI async adapter with dual-agent compatible interface."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 2048,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_key = api_key

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("openai package is not installed") from exc

        self._client = AsyncOpenAI(api_key=api_key)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        message = completion.choices[0].message if completion.choices else None
        return (message.content if message and message.content else "{}").strip()

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            tools=tools or None,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        message = completion.choices[0].message if completion.choices else None
        content = (message.content if message and message.content else "{}").strip()
        tool_calls = []
        if message and getattr(message, "tool_calls", None):
            for call in message.tool_calls:
                tool_calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                )
        return content, tool_calls

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Multi-turn conversation with tool calling (OpenAI format).

        Args:
            system_prompt: System instruction.
            messages: Full conversation history in OpenAI message format.
            tools: Tool definitions in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.

        Returns:
            (text_response, tool_calls) in normalized format:
            [{"id": ..., "name": ..., "input": {...}}, ...]
        """
        api_messages = [{"role": "system", "content": system_prompt}, *messages]

        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            tools=tools or None,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        message = completion.choices[0].message if completion.choices else None
        text = (message.content if message and message.content else "").strip()

        tool_calls: list[dict[str, Any]] = []
        if message and getattr(message, "tool_calls", None):
            import json

            for call in message.tool_calls:
                tool_calls.append(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "input": json.loads(call.function.arguments),
                    }
                )

        return text, tool_calls

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Sync wrapper implementing LLMClientPort for intent extraction."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        async def _call() -> dict[str, Any]:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            # Return raw-ish dict matching OpenAI format for _parse_tool_call_response
            message = completion.choices[0].message if completion.choices else None
            result: dict[str, Any] = {"choices": [{"message": {}}]}
            if message:
                result["choices"][0]["message"]["content"] = message.content or ""
                if getattr(message, "tool_calls", None):
                    result["choices"][0]["message"]["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]
            return result

        with ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, _call()).result()
