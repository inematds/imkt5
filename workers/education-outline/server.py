"""education-outline worker.

Capability: `education.outline`. Porta 8108.

Recebe um tópico educativo e produz outline com N slides seguindo a
estrutura hook → conteúdo → CTA.

Output consumido pela receita `curso-educativo` por:
  - inemaimg (fanout sobre slides[].image_prompt)
  - inemavox (via outline.narration_concat)
  - video-quick / video-edu-planner (scene_plan)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class EducationOutlineWorker(BaseWorker):
    name = "education-outline"
    capabilities = ("education.outline",)

    def __init__(self) -> None:
        self._skill = (
            SKILL_PATH.read_text() if SKILL_PATH.exists()
            else "Você é roteirista pedagógico sênior."
        )

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        topic = (payload.get("topic") or payload.get("brief") or "").strip()
        if not topic:
            raise ValueError("payload precisa de 'topic' (ou 'brief' como alias)")

        slide_count = int(payload.get("slide_count") or 10)
        slide_count = max(5, min(15, slide_count))
        language = payload.get("language") or "pt-BR"
        depth = payload.get("depth") or "iniciante"
        audience = payload.get("audience") or "público geral"
        style = payload.get("style") or "didatico"

        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md", "product_campaign.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado para este tenant)'}\n\n"
            f"## PARÂMETROS DESTA RUN\n\n"
            f"- Idioma: {language}\n"
            f"- Número de slides: exatamente {slide_count}\n"
            f"- Profundidade: {depth}\n"
            f"- Audience: {audience}\n"
            f"- Estilo: {style}\n"
            f"- Primeiro slide DEVE ser type=hook; último type=cta; demais type=content.\n"
        )

        user = f"## Tópico do conteúdo\n\n{topic}\n"

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.5,
        )

        # Normaliza se vier sem o wrapper "outline"
        if "outline" not in data and "slides" in data:
            data = {"outline": data}

        outline = data.get("outline", {})
        slides = outline.get("slides", [])

        # Fallback defensivo: se LLM esqueceu narration_concat, monta aqui.
        if slides and not outline.get("narration_concat"):
            parts = [s.get("narration", "").strip() for s in slides if s.get("narration")]
            outline["narration_concat"] = " ".join(parts)

        # Soma de durations pra total_duration_s
        if slides and not outline.get("total_duration_s"):
            outline["total_duration_s"] = sum(
                int(s.get("duration_s", 10)) for s in slides
            )

        # Garante `topic` e `language` ecoados
        outline.setdefault("topic", topic)
        outline.setdefault("language", language)
        data["outline"] = outline

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("EDUCATION_OUTLINE_PORT", 8108))
    EducationOutlineWorker().run(port=port)
