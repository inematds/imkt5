"""Tool `dispatch_job` — o LLM do Gateway chama pra disparar 1 job direto.

Caminho do quick dispatch: pedidos simples viram 1 Job.

Caminho de receita: o Recipe Runner usa internamente, não o LLM.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from imkt4.tools.base import BaseTool, ToolContext, ToolResult
from imkt4.types.jobs import Job, JobPriority


class JobSubmitter(Protocol):
    async def dispatch(self, job: Job) -> None: ...


class DispatchJobTool(BaseTool):
    name = "dispatch_job"
    description = (
        "Dispara 1 job para pipeline (imagem, áudio, vídeo, pesquisa). "
        "Use para pedidos simples. Para composições (campanha completa, "
        "fluxos multi-estágio), use `run_recipe`."
    )
    parameters = {
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": (
                    "Nome da capability necessária: image.generation, "
                    "audio.tts, video.render, research.market, etc."
                ),
            },
            "payload": {
                "type": "object",
                "description": "Dados específicos para o worker.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "default": "normal",
            },
        },
        "required": ["capability", "payload"],
    }

    def __init__(self, submitter: JobSubmitter) -> None:
        self._submitter = submitter

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        capability = kwargs["capability"]
        payload = kwargs.get("payload", {})
        priority_str = kwargs.get("priority", "normal")

        priority_map = {
            "low": JobPriority.LOW,
            "normal": JobPriority.NORMAL,
            "high": JobPriority.HIGH,
        }
        priority = priority_map.get(priority_str, JobPriority.NORMAL)

        job = Job(
            job_id=str(uuid.uuid4()),
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            required_capability=capability,
            payload=payload,
            origin_channel=ctx.origin_channel,
            origin_channel_external_id=ctx.origin_channel_external_id,
            priority=priority,
        )
        await self._submitter.dispatch(job)
        return ToolResult(ok=True, output={"job_id": job.job_id})
