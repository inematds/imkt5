"""ad-designer worker.

Porta timesmkt3/skills/ad-creative-designer/SKILL.md (escopo reduzido).
Capability: `design.ad_layout`.

Input (payload):
  {
    "creative_brief": {...},   # obrigatório — output do creative-brief
    "copy": {...},             # opcional — output do copywriter
  }

Output:
  {
    "ad_design": {
      "campaign_angle": "...",
      "variants": [
        { "platform": "instagram_feed", "format": "square",
          "aspect_ratio": "1:1", "layout_type": "lifestyle",
          "headline": "...", "subtext": "...", "cta": "...",
          "text_position": "top", "cta_position": "bottom",
          "background_prompt": "...", "negative_prompt": "..." },
        ...
      ]
    }
  }

Workflow downstream: cada `background_prompt` pode virar um job
`image.generation` pro inemaimg. Esse worker não dispara os jobs —
devolve a especificação. Quem orquestra é a receita.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class AdDesignerWorker(BaseWorker):
    name = "ad-designer"
    capabilities = ("design.ad_layout",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é designer visual de anúncios."

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("creative_brief")
        copy = payload.get("copy")

        if not brief:
            raise ValueError("payload precisa de 'creative_brief'")

        # Overrides opcionais do input. Tudo default-safe.
        image_count = int(payload.get("image_count") or 3)
        image_formats = payload.get("image_formats") or [
            "instagram_feed", "instagram_stories", "youtube_thumbnail",
        ]
        platform_targets = payload.get("platform_targets") or [
            "instagram", "youtube", "threads"
        ]
        language = payload.get("language") or "pt-BR"
        ref_note = (payload.get("image_reference_note") or "").strip()
        bg_color = (payload.get("image_background_color") or "").strip()

        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md", "product_campaign.md"],
        )

        extra_rules = []
        extra_rules.append(
            f"Idioma dos textos visíveis: {language}."
        )
        extra_rules.append(
            f"Gere exatamente {image_count} variante(s) — priorizando os formatos: {', '.join(image_formats)}."
        )
        if platform_targets:
            extra_rules.append(
                f"Plataformas-alvo: {', '.join(platform_targets)}."
            )
        if ref_note:
            extra_rules.append(
                f"Imagem de referência (obrigatório incluir em todos os background_prompt): {ref_note}"
            )
        if bg_color:
            extra_rules.append(
                f"Cor de fundo dominante: {bg_color} — mencione no background_prompt."
            )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado para este tenant)'}\n\n"
            f"## REGRAS DESTA RUN\n\n"
            + "\n".join(f"- {r}" for r in extra_rules)
        )

        user_parts = [
            "## Creative Brief",
            json.dumps(brief, ensure_ascii=False, indent=2),
        ]
        if copy:
            user_parts += [
                "",
                "## Copy pronto do Copywriter (use APENAS esses textos)",
                json.dumps(copy, ensure_ascii=False, indent=2),
            ]
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.5,
        )

        if "ad_design" not in data and "variants" in data:
            data = {"ad_design": data}

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("AD_DESIGNER_PORT", 8103))
    AdDesignerWorker().run(port=port)
