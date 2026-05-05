"""OpenRouter provider — implementa BaseProvider.

Usa a API HTTP do OpenRouter (compatível com OpenAI-like chat/completions)
com function calling.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from imkt5.providers.base import BaseProvider, LLMMessage, LLMResponse, ToolCall


class OpenRouterProvider(BaseProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        from imkt5.config import load
        cfg = load().llm.openrouter
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._base_url = (base_url or cfg.base_url).rstrip("/")
        self._default_model = default_model or cfg.default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY ausente")

        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [_msg_to_openai(m) for m in messages],
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/inematds/imkt5",
                    "X-Title": "imkt5 gateway",
                },
                json=body,
            )
            r.raise_for_status()
            data = r.json()

        choice = data["choices"][0]["message"]
        tool_calls = tuple(
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=_safe_json_parse(tc["function"].get("arguments", "{}")),
            )
            for tc in choice.get("tool_calls") or []
        )
        usage = data.get("usage", {})
        return LLMResponse(
            content=choice.get("content") or "",
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", body["model"]),
            raw=data,
        )


def _msg_to_openai(m: LLMMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _json_dump(tc.arguments)},
            }
            for tc in m.tool_calls
        ]
    return d


def _json_dump(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _safe_json_parse(s: str) -> dict[str, Any]:
    import json
    try:
        return json.loads(s) if isinstance(s, str) else (s or {})
    except json.JSONDecodeError:
        return {}
