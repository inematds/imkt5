"""carousel-outline worker.

Capability: `design.carousel_outline`. Porta 8112.

Recebe texto livre (topic) e devolve slides[] estruturados pro
carousel-designer renderizar direto.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class CarouselOutlineWorker(BaseWorker):
    name = "carousel-outline"
    capabilities = ("design.carousel_outline",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else ""

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        topic = (payload.get("topic") or payload.get("text") or payload.get("brief") or "").strip()
        if not topic:
            raise ValueError("payload precisa de 'topic' (ou 'text'/'brief')")

        slide_count = int(payload.get("slide_count") or 5)
        slide_count = max(3, min(10, slide_count))
        language = payload.get("language") or "pt-BR"
        style = payload.get("style") or "didatico"
        audience = payload.get("audience") or "público geral"

        knowledge = load_tenant_knowledge(
            job.tenant_id, files=["brand_identity.md", "product_campaign.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge)'}\n\n"
            f"## PARÂMETROS DESTA RUN\n\n"
            f"- Idioma: {language}\n"
            f"- N slides: {slide_count}\n"
            f"- Estilo de voz: {style}\n"
            f"- Audience: {audience}\n"
        )

        user = f"## Tópico\n\n{topic}\n"

        data = await complete_json(
            system_prompt=system, user_prompt=user, temperature=0.5,
        )

        # Normaliza — aceita { slides: [...] } ou lista direta
        if isinstance(data, list):
            data = {"slides": data}
        slides = data.get("slides", [])
        if not slides:
            raise RuntimeError(f"LLM não gerou slides. keys={list(data.keys())}")

        # O primeiro slide (cover) sempre reaproveita o TEXTO ORIGINAL
        # do usuário como headline — preserva a ideia como âncora.
        # Se o topic é muito longo, usa as primeiras 60 chars como
        # headline e joga o restante no `context`.
        original_headline = topic
        original_context = ""
        if len(topic) > 60:
            # Quebra numa pontuação próxima do limite pra não cortar palavra
            cut = 60
            for stop in ("—", " — ", ". ", "! ", "? ", ": ", ", "):
                idx = topic.rfind(stop, 0, 80)
                if idx > 30:
                    cut = idx + len(stop.rstrip())
                    break
            original_headline = topic[:cut].rstrip(" —,:.!?-")
            original_context = topic[cut:].lstrip(" —,:.!?-").strip()

        slide0 = dict(slides[0])
        slide0["headline"] = original_headline
        # Se o LLM já gerou context, preserva só se tiver conteúdo útil.
        # Preferimos o resto do texto original (que é o que o user escreveu).
        if original_context:
            slide0["context"] = original_context
        slides[0] = slide0

        return {
            "slides": slides,
            "title": data.get("title") or topic[:60],
            "suggested_style": data.get("suggested_style") or "neon_futurista",
            "topic": topic,
            "language": language,
        }


if __name__ == "__main__":
    import os
    port = int(os.environ.get("CAROUSEL_OUTLINE_PORT", 8112))
    CarouselOutlineWorker().run(port=port)
