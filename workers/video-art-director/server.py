"""video-art-director worker.

Capability: `video.art_direction`. Porta 8114.

Decide style + motion_preset + transition + music_genre + hook_pattern
pro video-quick/video-pro a partir do brief + audiência + plataforma +
perfil da marca.

Output: {style, motion_preset, transition, music_genre, hook_pattern,
justification}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"

VALID_STYLES = {
    "neon_futurista", "premium_minimal", "energetico", "emocional_cinematic",
    "corporate_clean", "streetwear_urban", "nature_organic", "retro_vintage",
    "bold_pop", "dark_dramatic", "playful_colorful", "editorial_documentary",
}

VALID_MOTIONS = {
    "static", "breathe", "zoom_in", "zoom_out", "pan_right", "pan_left",
    "drift", "hard_zoom",
}

VALID_TRANSITIONS = {
    "cut", "crossfade_short", "crossfade_long", "fade_black",
    "whip_pan", "zoom_blur",
}

VALID_HOOKS = {
    "stat_shot", "question_abrupt", "pattern_interrupt", "pov",
    "value_bomb", "contrast",
}

DEFAULTS_PER_STYLE = {
    "neon_futurista":        ("zoom_in", "cut", "synthwave", "pattern_interrupt"),
    "premium_minimal":       ("drift", "crossfade_long", "piano_solo", "value_bomb"),
    "energetico":            ("hard_zoom", "cut", "edm", "pattern_interrupt"),
    "emocional_cinematic":   ("pan_right", "crossfade_long", "piano_strings", "question_abrupt"),
    "corporate_clean":       ("static", "crossfade_short", "ambient", "stat_shot"),
    "streetwear_urban":      ("hard_zoom", "cut", "trap", "pattern_interrupt"),
    "nature_organic":        ("pan_right", "crossfade_long", "folk", "value_bomb"),
    "retro_vintage":         ("zoom_out", "crossfade_short", "jazz", "question_abrupt"),
    "bold_pop":              ("hard_zoom", "cut", "pop", "value_bomb"),
    "dark_dramatic":         ("zoom_in", "fade_black", "drone", "question_abrupt"),
    "playful_colorful":      ("breathe", "whip_pan", "ukulele_pop", "pov"),
    "editorial_documentary": ("static", "crossfade_short", "piano_minimal", "stat_shot"),
}


class VideoArtDirectorWorker(BaseWorker):
    name = "video-art-director"
    capabilities = ("video.art_direction",)

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
        copy = payload.get("copy")
        audience = (payload.get("audience") or "geral").strip()
        platform = (payload.get("platform") or "both").strip().lower()
        brand_profile = payload.get("brand_profile") or {}

        if not brief and not copy:
            raise ValueError("video-art-director precisa de brief/topic ou copy")

        knowledge = load_tenant_knowledge(
            job.tenant_id, files=["brand_identity.md"],
        )

        system = (
            f"{self._skill}\n\n"
            f"## CONHECIMENTO DO TENANT (brand identity)\n\n"
            f"{knowledge or '(sem brand_identity configurado)'}\n"
        )

        user_parts = [
            f"## Brief / Tópico\n\n{brief or '(sem brief)'}",
            f"\n## Audiência\n{audience}",
            f"\n## Plataforma\n{platform}",
        ]
        if copy:
            user_parts.append(
                f"\n## Copy (já produzido pelo copywriter)\n"
                f"{json.dumps(copy, ensure_ascii=False, indent=2)}"
            )
        if brand_profile:
            user_parts.append(
                f"\n## Perfil da marca (tenant)\n"
                f"{json.dumps(brand_profile, ensure_ascii=False, indent=2)}"
            )
        user = "\n".join(user_parts)

        data = await complete_json(
            system_prompt=system, user_prompt=user, temperature=0.3,
        )

        style = (data.get("style") or "corporate_clean").strip()
        if style not in VALID_STYLES:
            style = "corporate_clean"

        defaults = DEFAULTS_PER_STYLE[style]
        motion_preset = (data.get("motion_preset") or defaults[0]).strip()
        transition = (data.get("transition") or defaults[1]).strip()
        music_genre = (data.get("music_genre") or defaults[2]).strip()
        hook_pattern = (data.get("hook_pattern") or defaults[3]).strip()

        if motion_preset not in VALID_MOTIONS: motion_preset = defaults[0]
        if transition not in VALID_TRANSITIONS: transition = defaults[1]
        if hook_pattern not in VALID_HOOKS: hook_pattern = defaults[3]

        return {
            "style": style,
            "motion_preset": motion_preset,
            "transition": transition,
            "music_genre": music_genre,
            "hook_pattern": hook_pattern,
            "justification": (data.get("justification") or "").strip(),
        }


if __name__ == "__main__":
    import os
    port = int(os.environ.get("VIDEO_ART_DIRECTOR_PORT", 8114))
    VideoArtDirectorWorker().run(port=port)
