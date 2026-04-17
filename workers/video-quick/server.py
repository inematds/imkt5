"""video-quick worker.

Porta timesmkt3/skills/video-quick/SKILL.md — planner de vídeos curtos.
Capabilities: `video.plan`, `video.cinematic` (alias temporário até
existir um video-pro real).

NÃO renderiza vídeo. Recebe imagens já geradas (pelo ad-designer +
inemaimg) e devolve um `scene_plan` JSON que um worker renderer
(`ffmpeg-local` / `remotion-local`) vai consumir.

Input (payload):
  {
    "creative_brief": {...},
    "copy": {...},
    "ads": ["url1.png", "url2.png", ...],   # pelo menos 4
    "voiceover_url": "..." or null,
  }

Output:
  {
    "scene_plan": {
      "titulo": "...",
      "video_length": 15,
      "format": "9:16",
      "scenes": [ {id, duration, image, narration, text_overlay, motion}, ... ]
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


class VideoQuickWorker(BaseWorker):
    name = "video-quick"
    # `video.cinematic` é alias temporário — até existir video-pro próprio,
    # a receita `campanha-marketing` usa essa capability e cai aqui.
    capabilities = ("video.plan", "video.cinematic")

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é planner de vídeo curto."

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("creative_brief")
        copy = payload.get("copy")
        ads = payload.get("ads") or []
        voiceover_url = payload.get("voiceover_url")

        if not brief:
            raise ValueError("payload precisa de 'creative_brief'")
        if len(ads) < 3:
            raise ValueError(f"payload precisa de pelo menos 3 imagens em 'ads' (recebido: {len(ads)})")

        # Overrides opcionais
        language = payload.get("language") or "pt-BR"
        video_template = payload.get("video_template") or "auto"

        knowledge = load_tenant_knowledge(
            job.tenant_id,
            files=["brand_identity.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado)'}\n\n"
            f"## REGRAS DESTA RUN\n\n"
            f"- Idioma das narrations e text_overlays: {language}.\n"
            f"- Template solicitado: {video_template} (use como guia do estilo — 'auto' = livre).\n"
        )

        user_parts = [
            "## Creative Brief",
            json.dumps(brief, ensure_ascii=False, indent=2),
            "",
            "## Imagens disponíveis (`ads`)",
            json.dumps(ads, ensure_ascii=False, indent=2),
        ]
        if copy:
            user_parts += [
                "",
                "## Copy",
                json.dumps(copy, ensure_ascii=False, indent=2),
            ]
        if voiceover_url:
            user_parts += [
                "",
                f"## Voiceover disponível: {voiceover_url}",
                "Use essa URL no campo `narration_file` do scene_plan.",
            ]
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.5,
        )

        if "scene_plan" not in data and "scenes" in data:
            data = {"scene_plan": data}

        sp = data.get("scene_plan", {})
        if voiceover_url and not sp.get("narration_file"):
            sp["narration_file"] = voiceover_url

        # full_narration = concatenação das narrations de cada cena
        # (consumido pelo stage voiceover depois do video plan).
        narrations = [
            sc.get("narration", "").strip()
            for sc in sp.get("scenes", [])
            if sc.get("narration")
        ]
        sp["full_narration"] = " ".join(narrations)

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("VIDEO_QUICK_PORT", 8104))
    VideoQuickWorker().run(port=port)
