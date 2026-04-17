"""creative-brief worker.

Porta timesmkt3/skills/creative-director/SKILL.md.
Capability: `brief.strategic`.

Input (payload):
  {
    "brief": "descrição livre do usuário",
    "research": {...}     # output do research worker, opcional
  }

Output:
  {
    "creative_brief": {
       "campaign_theme": "...",
       "campaign_angle": "...",
       "positioning_statement": "...",
       "emotional_hook": "...",
       "visual_direction": {...},
       "key_messages": {"instagram": "...", "youtube": "...", ...},
       "guardrails": {...}
    }
  }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


SYSTEM_PROMPT_TEMPLATE = """\
{skill}

## CONHECIMENTO DO TENANT

{knowledge}

## REGRAS DE SAÍDA

Você DEVE retornar APENAS um JSON válido com a estrutura exata abaixo.
Sem texto antes ou depois. Sem cercas de markdown.

{{
  "creative_brief": {{
    "campaign_theme": "...",
    "campaign_angle": "...",
    "positioning_statement": "...",
    "emotional_hook": "...",
    "visual_direction": {{
      "mood": "...",
      "dominant_colors": ["#hex1", "#hex2"],
      "photography_style": "...",
      "visual_cues": ["...", "..."]
    }},
    "key_messages": {{
      "instagram": "...",
      "youtube": "...",
      "threads": "...",
      "tiktok": "...",
      "facebook": "...",
      "linkedin": "..."
    }},
    "guardrails": {{
      "tones_to_avoid": ["...", "..."],
      "imagery_to_avoid": ["...", "..."],
      "ctas_out_of_scope": ["...", "..."]
    }},
    "image_prompt_seeds": ["descrição visual 1", "descrição visual 2"]
  }}
}}
"""


class CreativeBriefWorker(BaseWorker):
    name = "creative-brief"
    capabilities = ("brief.strategic",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é um Diretor Criativo sênior."

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("brief", "").strip()
        research = payload.get("research")

        if not brief:
            raise ValueError("payload precisa de 'brief'")

        # knowledge do tenant
        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md", "product_campaign.md"],
        )

        system = SYSTEM_PROMPT_TEMPLATE.format(
            skill=self._skill,
            knowledge=knowledge or "(sem knowledge configurado para este tenant)",
        )

        user = f"## Brief do usuário\n\n{brief}\n"
        if research:
            import json
            user += f"\n## Pesquisa de mercado disponível\n\n{json.dumps(research, ensure_ascii=False)[:4000]}\n"

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.4,
        )

        # Normaliza — LLM pode ter envolvido em outro nível
        if "creative_brief" not in data and "campaign_theme" in data:
            data = {"creative_brief": data}

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("CREATIVE_BRIEF_PORT", 8101))
    CreativeBriefWorker().run(port=port)
