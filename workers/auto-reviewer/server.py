"""auto-reviewer worker.

Recebe {artifacts, criteria} e devolve decisão: approve | reject | uncertain.
Usa LLM (OpenRouter/Anthropic) pra avaliar cada critério.

Este arquivo é um SKELETON — integração real com LLM fica pendente de
configuração (API key). Por ora, retorna 'approved' pra qualquer coisa.
"""

from __future__ import annotations

from typing import Any

from workers._base import BaseWorker


class AutoReviewerWorker(BaseWorker):
    name = "auto-reviewer"
    capabilities = ("review.auto",)

    async def handle(self, job) -> dict[str, Any]:
        criteria = job.payload.get("criteria", [])
        artifacts = job.payload.get("artifacts", {})

        # TODO: integração real com LLM. Shape esperado:
        #   prompt = f"Critérios: {criteria}\n\nArtefatos:\n{artifacts}\n\n..."
        #   resp = await provider.chat(messages=[...], model=...)
        #   parse resp into decision + reason
        # Por enquanto, skeleton que aprova se há critérios, rejeita se não.
        if not criteria:
            return {"decision": "approved", "reason": "sem critérios declarados"}

        return {
            "decision": "approved",
            "reason": "SKELETON: LLM não integrado ainda",
            "evaluated_criteria": criteria,
            "artifact_summary": str(list(artifacts.keys()))[:200],
        }


if __name__ == "__main__":
    AutoReviewerWorker().run(port=8200)
