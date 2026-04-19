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
"""


class CreativeBriefWorker(BaseWorker):
    name = "creative-brief"
    capabilities = ("brief.strategic",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é um Diretor Criativo sênior."

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        # `or ""` trata o caso do YAML resolver brief pra None (campo ausente
        # no input). payload.get("brief", "") só ajuda se a chave AUSENTE.
        raw_brief = payload.get("brief")
        brief = (raw_brief or "").strip() if isinstance(raw_brief, str) else ""
        research = payload.get("research")

        if not brief:
            raise ValueError(
                "campo 'brief' é obrigatório (string não-vazia). "
                "Preencha o textarea principal no modal Nova Execução."
            )

        # Overrides opcionais
        language = payload.get("language") or "pt-BR"
        platform_targets = payload.get("platform_targets") or [
            "instagram", "youtube", "threads", "tiktok", "facebook", "linkedin",
        ]
        ref_note = (payload.get("image_reference_note") or "").strip()

        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md", "product_campaign.md"],
        )

        extra_rules = [f"Idioma do brief: {language}."]
        if platform_targets:
            extra_rules.append(
                f"Plataformas foco da campanha: {', '.join(platform_targets)}. "
                "Preencha key_messages apenas pra essas."
            )
        if ref_note:
            extra_rules.append(
                f"Referência visual fixa (incluir em image_prompt_seeds): {ref_note}"
            )

        system = SYSTEM_PROMPT_TEMPLATE.format(
            skill=self._skill,
            knowledge=knowledge or "(sem knowledge configurado para este tenant)",
        )
        system = f"{system}\n\n## REGRAS DESTA RUN\n\n" + "\n".join(f"- {r}" for r in extra_rules)

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
