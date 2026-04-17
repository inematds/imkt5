"""photography-director worker.

Capability: `design.photo_direction`. Porta 8110.

Produz photography_plan — linguagem visual completa (style preset,
palette, tipografia por seção, câmera por seção, transições).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class PhotographyDirectorWorker(BaseWorker):
    name = "photography-director"
    capabilities = ("design.photo_direction",)

    def __init__(self) -> None:
        self._skill = (
            SKILL_PATH.read_text() if SKILL_PATH.exists()
            else "Você é diretor de fotografia sênior."
        )

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("creative_brief")
        outline = payload.get("outline")
        platform_targets = payload.get("platform_targets") or [
            "instagram_feed", "instagram_stories", "youtube_thumbnail",
        ]
        language = payload.get("language") or "pt-BR"

        if not brief:
            raise ValueError("payload precisa de 'creative_brief'")

        knowledge = load_tenant_knowledge(
            job.tenant_id, files=["brand_identity.md"]
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado)'}\n\n"
            f"## PARÂMETROS DESTA RUN\n\n"
            f"- Idioma dos textos: {language}\n"
            f"- Plataformas-alvo: {', '.join(platform_targets)}\n"
        )

        user_parts = [
            "## Creative Brief",
            json.dumps(brief, ensure_ascii=False, indent=2),
        ]
        if outline:
            user_parts += [
                "",
                "## Outline (se pipeline educativo)",
                json.dumps(outline, ensure_ascii=False, indent=2)[:3000],
            ]
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.4,
        )

        # Normaliza se vier sem o wrapper
        if "photography_plan" not in data and "style_preset" in data:
            data = {"photography_plan": data}

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PHOTOGRAPHY_DIRECTOR_PORT", 8110))
    PhotographyDirectorWorker().run(port=port)
