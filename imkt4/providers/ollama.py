"""Ollama provider — implementa BaseProvider.

Chama `/api/chat` do Ollama local. Tools via function calling (modelos
que suportam, tipo qwen2.5, llama3.1).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from imkt4.providers.base import BaseProvider, LLMMessage, LLMResponse, ToolCall


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        from imkt4.config import load
        cfg = load().llm.ollama
        self._url = (url or os.environ.get("OLLAMA_URL", cfg.url)).rstrip("/")
        self._default_model = default_model or cfg.chat_model

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [_msg_to_ollama(m) for m in messages],
            "options": {"temperature": temperature},
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if max_tokens:
            body["options"]["num_predict"] = max_tokens

        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{self._url}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()

        msg = data.get("message", {})
        tool_calls = tuple(
            ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=tc["function"]["name"],
                arguments=tc["function"].get("arguments") or {},
            )
            for i, tc in enumerate(msg.get("tool_calls") or [])
        )
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=body["model"],
            raw=data,
        )


def _msg_to_ollama(m: LLMMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in m.tool_calls
        ]
    return d
