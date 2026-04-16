"""inemavox-adapter — wrapper HTTP sobre o inemavox local.

Expõe capabilities `audio.tts` e `audio.dubbing`. SKELETON: retorna
URL mock até a integração real com `inemavox` ser feita.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from workers._base import BaseWorker

INEMAVOX_URL = os.environ.get("INEMAVOX_URL", "http://localhost:8011")


class InemavoxAdapter(BaseWorker):
    name = "inemavox-adapter"
    capabilities = ("audio.tts", "audio.dubbing")

    async def handle(self, job) -> dict[str, Any]:
        text = job.payload.get("text")
        voice_id = job.payload.get("voice_id")
        if not text:
            raise ValueError("payload precisa de 'text'")

        # TODO: integração real com inemavox.
        return {
            "audio_url": f"s3://imkt4/mock/{job.job_id}.mp3",
            "voice_id": voice_id,
            "duration_seconds": max(1, len(text.split()) // 3),
            "_note": "SKELETON: chamada real para inemavox pendente",
        }


if __name__ == "__main__":
    InemavoxAdapter().run(port=8011)
