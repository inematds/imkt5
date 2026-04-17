"""video-pro worker.

Porta timesmkt3/skills/video-editor-agent (escopo reduzido MVP).
Capability: `video.cinematic_pro`. Porta 8106.

Mesmo contrato do video-quick mas com scene_plan mais elaborado:
8-12 cenas, 45-90s, estrutura narrativa hook→tension→solution→proof→cta.

Output é consumido pelo mesmo ffmpeg-local (`video.render`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class VideoProWorker(BaseWorker):
    name = "video-pro"
    capabilities = ("video.cinematic_pro",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else "Você é diretor de edição sênior."

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

        language = payload.get("language") or "pt-BR"
        video_template = payload.get("video_template") or "auto"

        knowledge = load_tenant_knowledge(
            job.tenant_id, files=["brand_identity.md", "product_campaign.md"]
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT\n\n"
            f"{knowledge or '(sem knowledge configurado)'}\n\n"
            f"## REGRAS DESTA RUN\n\n"
            f"- Idioma das narrations e text_overlays: {language}.\n"
            f"- Template solicitado: {video_template}.\n"
        )

        user_parts = [
            "## Creative Brief",
            json.dumps(brief, ensure_ascii=False, indent=2),
            "",
            "## Imagens disponíveis (`ads`)",
            json.dumps(ads, ensure_ascii=False, indent=2),
        ]
        if copy:
            user_parts += ["", "## Copy", json.dumps(copy, ensure_ascii=False, indent=2)]
        if voiceover_url:
            user_parts += [
                "",
                f"## Voiceover disponível: {voiceover_url}",
                "Use no campo `narration_file`.",
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

        narrations = [
            sc.get("narration", "").strip()
            for sc in sp.get("scenes", [])
            if sc.get("narration")
        ]
        sp["full_narration"] = " ".join(narrations)

        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("VIDEO_PRO_PORT", 8106))
    VideoProWorker().run(port=port)
