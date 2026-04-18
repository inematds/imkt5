"""art-director worker.

Capability: `design.art_director`. Porta 8113.

Escolhe template + palette (style) pro carousel-designer a partir de
brief/topic + perfil da marca + audiência + plataforma.

Output: {template, style, justification}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"

VALID_TEMPLATES = {
    "editorial", "magazine", "corporate_clean", "data_viz", "wellness_soft",
    "bold_pop", "retro_futurism", "organic_earth", "neo_minimal_luxury",
}

VALID_STYLES = {
    "neon_futurista", "warm_lifestyle", "minimal_zen", "dark_cinematic",
    "pastel_soft", "retro_vintage", "nature_organic", "urban_street",
    "luxury_gold", "editorial_documentary",
    "corporate_clean", "data_viz", "data_viz_dark", "wellness_soft",
    "bold_pop", "bold_pop_orange", "retro_futurism", "organic_earth",
    "neo_minimal_luxury", "neo_minimal_luxury_light",
}


class ArtDirectorWorker(BaseWorker):
    name = "art-director"
    capabilities = ("design.art_director",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else ""

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = (
            payload.get("brief")
            or payload.get("topic")
            or payload.get("text")
            or ""
        ).strip()
        audience = (payload.get("audience") or "geral").strip()
        platform = (payload.get("platform") or "both").strip().lower()
        brand_profile = payload.get("brand_profile") or {}

        if not brief and not payload.get("slides"):
            raise ValueError("art-director precisa de brief/topic ou slides")

        knowledge = load_tenant_knowledge(
            job.tenant_id, files=["brand_identity.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT (brand identity)\n\n"
            f"{knowledge or '(sem brand_identity configurado)'}\n"
        )

        user_parts = [
            f"## Brief / Tópico\n\n{brief or '(sem brief — usar slides do contexto)'}",
            f"\n## Audiência\n{audience}",
            f"\n## Plataforma\n{platform}",
        ]
        if brand_profile:
            user_parts.append(
                f"\n## Perfil da marca (tenant)\n"
                f"{json.dumps(brand_profile, ensure_ascii=False, indent=2)}"
            )
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system, user_prompt=user, temperature=0.3,
        )

        template = (data.get("template") or "editorial").strip()
        style = (data.get("style") or template).strip()
        justification = (
            data.get("justification") or "default fallback"
        ).strip()

        # Sanity check — se LLM inventou algo fora do catálogo, cai pro default.
        if template not in VALID_TEMPLATES:
            template = "editorial"
            justification = f"[FALLBACK — LLM retornou '{data.get('template')}'] " + justification
        if style not in VALID_STYLES:
            # tenta casar style ao template; se não bater, usa dark_cinematic
            style = {
                "editorial": "dark_cinematic",
                "magazine": "luxury_gold",
                "corporate_clean": "corporate_clean",
                "data_viz": "data_viz",
                "wellness_soft": "wellness_soft",
                "bold_pop": "bold_pop",
                "retro_futurism": "retro_futurism",
                "organic_earth": "organic_earth",
                "neo_minimal_luxury": "neo_minimal_luxury",
            }.get(template, "dark_cinematic")

        return {
            "template": template,
            "style": style,
            "justification": justification,
        }


if __name__ == "__main__":
    import os
    port = int(os.environ.get("ART_DIRECTOR_PORT", 8113))
    ArtDirectorWorker().run(port=port)
