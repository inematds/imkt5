"""Contrato de provider de LLM.

Provider é stateless — só transforma `messages + tools` em resposta. Seleção
de modelo vem do perfil do tenant (não de config global). Rate-limiting e
retry são responsabilidade do provider concreto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # Para role=="tool": id do tool_call a que responde.
    tool_call_id: str | None = None
    # Para role=="assistant" com tool_calls geradas.
    tool_calls: tuple["ToolCall", ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    # Telemetria para billing e auditoria — preencher se o provider suportar.
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Interface de um provider de LLM (OpenRouter, Ollama, Anthropic, ...)."""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Uma rodada de chat. Fiel ao contrato do blueprint Intelecto."""
