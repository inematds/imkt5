"""copywriter worker.

Porta timesmkt3/skills/copywriter-agent/SKILL.md.
Capability: `copy.platform`.

Input (payload):
  {
    "creative_brief": {...}  # output do creative-brief worker
    "research": {...}        # opcional, output do research worker
  }

Output:
  {
    "copy": {
      "campaign_angle": "...",
      "topic": "...",
      "key_benefit": "...",
      "threads_post": "...",
      "instagram_caption": "...",
      "youtube": {"title": "...", "description": "...", "tags": [...]}
    }
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class CopywriterWorker(BaseWorker):
    name = "copywriter"
    capabilities = ("copy.platform",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é copywriter sênior."

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("creative_brief")
        research = payload.get("research")

        if not brief:
            raise ValueError("payload precisa de 'creative_brief' (output do worker creative-brief)")

        # knowledge do tenant — brand + platform guidelines são o que importa aqui
        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md", "platform_guidelines.md", "product_campaign.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado para este tenant)'}\n"
        )

        user_parts = [
            "## Creative Brief",
            json.dumps(brief, ensure_ascii=False, indent=2),
        ]
        if research:
            user_parts += [
                "",
                "## Research (ad_hooks + keywords)",
                json.dumps(research, ensure_ascii=False, indent=2)[:4000],
            ]
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.6,
        )

        # Normaliza — LLM pode ter retornado sem a chave "copy"
        if "copy" not in data and "threads_post" in data:
            data = {"copy": data}

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("COPYWRITER_PORT", 8102))
    CopywriterWorker().run(port=port)
