"""outline-to-video-plan worker.

Capability: `video.plan_from_outline`. Porta 8109.

Converte o output do `education-outline` + lista de imagens + voiceover_url
em um `scene_plan` compatível com o ffmpeg-local (capability `video.render`).

Input:
  {
    "outline": {
      "title": "...",
      "slides": [
        {"index": 1, "type": "hook", "title": "...",
         "narration": "...", "image_prompt": "...", "duration_s": 8}, ...
      ],
      "narration_concat": "...",
      "total_duration_s": 95,
      "language": "pt-BR"
    },
    "ads": ["/s3/.../slide_01.png", ...],   // mesma ordem dos slides
    "voiceover_url": "/s3/.../tts.mp3"      // opcional
  }

Output: `{"scene_plan": {...}}` já no formato que ffmpeg-local aceita.
"""

from __future__ import annotations

import os
from typing import Any

from workers._base import BaseWorker


class OutlineToVideoPlanWorker(BaseWorker):
    name = "outline-to-video-plan"
    capabilities = ("video.plan_from_outline",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        outline = payload.get("outline") or {}
        slides = outline.get("slides") or []
        ads = payload.get("ads") or []
        voiceover_url = payload.get("voiceover_url")

        if not slides:
            raise ValueError("outline.slides vazio")
        if not ads:
            raise ValueError("ads vazio — stage images não gerou imagens?")
        if len(ads) < len(slides):
            # Último fallback: repete última imagem pra cobrir slides extras
            ads = list(ads) + [ads[-1]] * (len(slides) - len(ads))

        # Motions alternados pra não ficar visualmente estático
        motion_types = ["push-in", "ken-burns-in", "drift", "ken-burns-out"]

        scenes = []
        for i, s in enumerate(slides):
            dur = max(3, int(s.get("duration_s") or 10))
            overlay = s.get("title") or ""
            # Hook e CTA destacados em posição top; conteúdo default top também
            position = "top"
            # Tipografia: hook maior, cta bold, content normal
            stype = s.get("type") or "content"
            font_size = 92 if stype in ("hook", "cta") else 80
            # Motion só no hook e no CTA (impacto visual onde importa).
            # Conteúdo fica estático = render 3-5x mais rápido.
            motion = None
            if stype in ("hook", "cta"):
                motion = {
                    "type": motion_types[i % len(motion_types)],
                    "intensity": "moderate",
                }
            scenes.append({
                "id": f"{stype}_{i+1:02d}",
                "type": stype,
                "duration": dur,
                "image": ads[i],
                "narration": s.get("narration", "") or "",
                "text_overlay": overlay[:60],  # limite visual
                "text_color": "#FFFFFF",
                "text_position": position,
                "overlay_opacity": 0.5,
                "font_family": "Lora",
                "font_size": font_size,
                "font_weight": "900",
                "text_shadow": "0 4px 12px rgba(0,0,0,0.8)",
                "motion": motion,
            })

        width = int(payload.get("width") or 1080)
        height = int(payload.get("height") or 1920)

        scene_plan = {
            "titulo": outline.get("title", "Curso educativo"),
            "video_length": sum(int(s["duration"]) for s in scenes),
            "format": "9:16",
            "width": width,
            "height": height,
            "narration_file": voiceover_url,
            "narration_volume": 1,
            "music": None,
            "music_volume": 0.15,
            "scenes": scenes,
            # compat com ffmpeg-local (lê narration_file de ambos lugares)
            "full_narration": outline.get("narration_concat", ""),
        }

        return {"scene_plan": scene_plan}


if __name__ == "__main__":
    port = int(os.environ.get("OUTLINE_TO_VIDEO_PLAN_PORT", 8109))
    OutlineToVideoPlanWorker().run(port=port)
