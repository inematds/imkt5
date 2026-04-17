"""AgentLoop — coração conversacional do Gateway.

Recebe IncomingMessage → monta contexto (SOUL + memória) → chama LLM
com tools (dispatch_job, run_recipe) → executa tools iteradas → devolve
OutgoingMessage.

Limita a 5 rodadas de tool calling por mensagem (como no Intelecto).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from imkt4.agent.context import ContextBuilder
from imkt4.memory.store import MemoryStore, MemoryCategory
from imkt4.providers.base import BaseProvider, LLMMessage, LLMResponse, ToolCall
from imkt4.tools.registry import ToolRegistry
from imkt4.tools.base import ToolContext
from imkt4.types.messages import IncomingMessage, OutgoingMessage

log = logging.getLogger("imkt4.agent")

MAX_ROUNDS = 5


@dataclass
class AgentConfig:
    model: str
    temperature: float = 0.3


class AgentLoop:
    def __init__(
        self,
        *,
        provider: BaseProvider,
        tools: ToolRegistry,
        context_builder: ContextBuilder,
        memory: MemoryStore | None = None,
        config: AgentConfig | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._ctx = context_builder
        self._memory = memory
        self._config = config or AgentConfig(model="qwen2.5:14b")

    async def process_message(
        self, incoming: IncomingMessage
    ) -> OutgoingMessage:
        sys_prompt = await self._ctx.build_system_prompt(
            tenant_id=incoming.tenant_id,
            user_id=incoming.user_id,
            query=incoming.text,
        )

        tool_ctx = ToolContext(
            tenant_id=incoming.tenant_id,
            user_id=incoming.user_id,
            origin_channel=incoming.channel.value,
            origin_channel_external_id=incoming.channel_external_id,
        )

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=incoming.text),
        ]

        tools_schema = self._tools.schema_for_llm()

        final_text: str | None = None
        for round_n in range(MAX_ROUNDS):
            try:
                resp: LLMResponse = await self._provider.chat(
                    messages,
                    model=self._config.model,
                    tools=tools_schema or None,
                    temperature=self._config.temperature,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("provider erro: %s", exc)
                final_text = f"❌ Erro no LLM: {exc}"
                break

            # sem tool_calls → resposta final
            if not resp.tool_calls:
                final_text = resp.content.strip() or "(sem resposta)"
                break

            # com tool_calls → executa cada, adiciona resposta, itera
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=resp.content or "",
                    tool_calls=resp.tool_calls,
                )
            )
            for tc in resp.tool_calls:
                log.info(
                    "tool call round=%d tool=%s args=%s",
                    round_n, tc.name, tc.arguments,
                )
                result = await self._tools.execute(tc.name, tool_ctx, **tc.arguments)
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(
                            {"ok": result.ok, "output": result.output, "error": result.error},
                            ensure_ascii=False,
                        ),
                        tool_call_id=tc.id,
                    )
                )
        else:
            final_text = (
                "(limite de rodadas atingido — operação pode estar em andamento, "
                "consulte /jobs ou /runs)"
            )

        # salva memória leve da conversa
        if self._memory and final_text:
            try:
                await self._memory.save(
                    tenant_id=incoming.tenant_id,
                    user_id=incoming.user_id,
                    content=f"USER: {incoming.text[:200]} | ASSISTANT: {final_text[:200]}",
                    category=MemoryCategory.CONVERSATION,
                )
            except Exception:  # noqa: BLE001
                pass

        return OutgoingMessage(
            tenant_id=incoming.tenant_id,
            user_id=incoming.user_id,
            channel=incoming.channel,
            channel_external_id=incoming.channel_external_id,
            text=final_text or "(?)",
        )
