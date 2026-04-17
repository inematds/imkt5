"""carousel-composer worker.

Capability: `design.carousel`. Porta 8107.

MVP: recebe lista de imagens já geradas e produz um "carousel JSON"
descritivo — a composição visual (overlay HTML→PNG, stitching grid
etc) fica pra iteração futura quando um renderer real existir.

Input:
  {
    "images": ["/s3/.../1.png", "/s3/.../2.png"],
    "title": "opcional",
    "caption": "opcional"
  }

Output:
  {
    "carousel": {
      "title": "...",
      "slide_count": 3,
      "slides": [
        {"index": 0, "image": "...", "is_cover": true},
        {"index": 1, "image": "...", "is_cover": false},
        ...
      ]
    }
  }
"""

from __future__ import annotations

import os
from typing import Any

from workers._base import BaseWorker


class CarouselComposerWorker(BaseWorker):
    name = "carousel-composer"
    capabilities = ("design.carousel",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        images = payload.get("images") or []
        # fanout: alguns stages passam images como list aninhada
        if images and isinstance(images[0], list):
            images = [x for sub in images for x in (sub or [])]
        images = [x for x in images if x]

        if not images:
            raise ValueError("payload precisa de 'images' não vazio")

        title = payload.get("title") or f"Carousel {job.job_id[:8]}"
        caption = payload.get("caption") or ""

        slides = [
            {"index": i, "image": url, "is_cover": i == 0}
            for i, url in enumerate(images)
        ]

        return {
            "carousel": {
                "title": title,
                "caption": caption,
                "slide_count": len(slides),
                "slides": slides,
                "images": list(images),
            }
        }


if __name__ == "__main__":
    port = int(os.environ.get("CAROUSEL_COMPOSER_PORT", 8107))
    CarouselComposerWorker().run(port=port)
