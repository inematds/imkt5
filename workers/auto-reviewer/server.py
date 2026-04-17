"""auto-reviewer worker.

Avalia artefatos contra critérios declarados em receita. Emite decisão
`approved | rejected | uncertain` com justificativa.

Usa a chain do `workers._base.llm_client` (default: Claude Code via
SDK → Ollama → OpenRouter). Configurável via `LLM_PROVIDER_ORDER`.

Payload:
  {
    "criteria": ["regra 1", "regra 2"],
    "artifacts": {...},
  }
"""

from __future__ import annotations

import json
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json

SYSTEM_PROMPT = """\
Você é um revisor automático. Seu trabalho é decidir se um artefato atende
a uma lista de critérios.

Para cada critério, emita um veredicto: "pass" | "fail" | "unclear".

Então emita uma decisão global:
- "approved" se TODOS os critérios passam,
- "rejected" se ALGUM critério falha claramente,
- "uncertain" se há "unclear" e nenhum "fail".

Responda APENAS em JSON com este formato exato, sem texto antes ou depois:
{
  "per_criterion": [
    {"criterion": "...", "verdict": "pass|fail|unclear", "reason": "..."}
  ],
  "decision": "approved|rejected|uncertain",
  "reason": "resumo curto"
}
"""


class AutoReviewerWorker(BaseWorker):
    name = "auto-reviewer"
    capabilities = ("review.auto",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        criteria = payload.get("criteria") or []
        artifacts = payload.get("artifacts") or {}

        if not criteria:
            return {
                "decision": "approved",
                "reason": "sem critérios declarados",
                "per_criterion": [],
            }

        user_msg = self._build_user(criteria, artifacts)

        try:
            parsed = await complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_msg,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "decision": "uncertain",
                "reason": f"providers LLM falharam: {exc}",
                "per_criterion": [],
            }

        return {
            "decision": parsed.get("decision", "uncertain"),
            "reason": parsed.get("reason", ""),
            "per_criterion": parsed.get("per_criterion", []),
        }

    def _build_user(self, criteria: list[str], artifacts: dict[str, Any]) -> str:
        crit_list = "\n".join(f"- {c}" for c in criteria)
        art_str = json.dumps(artifacts, ensure_ascii=False)[:6000]
        return (
            f"Critérios:\n{crit_list}\n\n"
            f"Artefatos a revisar (JSON):\n{art_str}"
        )


if __name__ == "__main__":
    import os
    from imkt4.config import load
    port = int(os.environ.get("AUTO_REVIEWER_PORT", load().workers.auto_reviewer.port))
    AutoReviewerWorker().run(port=port)
