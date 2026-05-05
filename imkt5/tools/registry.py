"""Registry de tools.

Descobre tools registradas, entrega o JSON Schema agregado ao LLM, e despacha
execuções injetando `ToolContext` — nenhuma tool é executada sem identidade.
"""

from __future__ import annotations

from typing import Any

from imkt5.tools.base import BaseTool, ToolContext, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool já registrada: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def schema_for_llm(self) -> list[dict[str, Any]]:
        """Retorna a lista de tools no formato de function-calling do LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(
        self, name: str, ctx: ToolContext, **kwargs: Any
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"tool desconhecida: {name}")
        try:
            return await tool.execute(ctx, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
