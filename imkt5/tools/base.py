"""Contrato de tool.

Diferente do Intelecto original (que passa argumentos via `**kwargs`), o
imkt5 exige um `ToolContext` explícito — é onde `tenant_id` e `user_id`
trafegam. Nenhuma tool roda sem contexto de quem pediu.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Identidade e contexto do chamador, injetado em toda execução de tool."""

    tenant_id: str
    user_id: str
    # Correlação: a chamada veio de uma mensagem específica.
    origin_channel: str
    origin_channel_external_id: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BaseTool(ABC):
    """Interface que toda tool implementa."""

    name: str
    description: str
    # JSON Schema dos parâmetros — como no blueprint Intelecto, entregue ao LLM.
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Executa a tool. `ctx` é injetado pelo registry; `kwargs` vêm do LLM."""
