"""video-ab-suggest worker.

Capability: `video.ab_suggest`. Item 6c (flag ab_ai_suggest).

LLM recebe brief + copy e sugere hook_variants/cta_variants/combinations
pra preencher automaticamente campos usados pelo recipe A/B.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class VideoAbSuggestWorker(BaseWorker):
    name = "video-ab-suggest"
    capabilities = ("video.ab_suggest",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else ""

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        brief = payload.get("brief") or payload.get("text") or ""
        copy = payload.get("copy") or {}
        audience = payload.get("audience") or ""
        platform = payload.get("platform") or ""

        system = (
            f"{self._skill}\n\n"
            f"## PARÂMETROS DESTA RUN\n"
            f"- Audience: {audience or '(não especificado)'}\n"
            f"- Platform: {platform or '(genérico)'}\n"
        )
        user = "\n".join([
            "## Brief",
            brief if isinstance(brief, str) else json.dumps(brief, ensure_ascii=False),
            "",
            "## Copy (se disponível)",
            json.dumps(copy, ensure_ascii=False, indent=2) if copy else "(sem copy)",
        ])

        data = await complete_json(system_prompt=system, user_prompt=user, temperature=0.6)

        hook_variants = data.get("hook_variants") or []
        cta_variants = data.get("cta_variants") or []
        combos = data.get("combinations_to_render") or []

        # Normaliza: se LLM não gerou combos, cria cross-prod limitado a 6
        if not combos and hook_variants and cta_variants:
            combos = [
                {"hook": h, "cta": c}
                for h in hook_variants for c in cta_variants
            ][:6]

        return {
            "hook_variants": hook_variants,
            "cta_variants": cta_variants,
            "combinations_to_render": combos,
            "justification": data.get("justification", ""),
        }


if __name__ == "__main__":
    import os
    port = int(os.environ.get("VIDEO_AB_SUGGEST_PORT", 8115))
    VideoAbSuggestWorker().run(port=port)
