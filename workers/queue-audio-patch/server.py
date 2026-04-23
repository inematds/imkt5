"""queue-audio-patch worker.

Capability: `video.queue_audio_patch`. Porta 8121.

Proxy pure-python (sem LLM) que recebe um `queue_json` (formato
`/nqueues/import` do SkyReels V3) + uma lista paralela de `audio_urls`
(produzida por um fanout de TTS sobre as cenas) e devolve o
`queue_json` com o campo `input_audio` populado por índice em cada cena
que pediu áudio.

Regra: só patcha `input_audio` em cena cujo `audio_text` é não-vazio
(intenção explícita de ter áudio). Evita que o stub de silêncio do
inemavox (retornado pra texto vazio) vaze pra cenas não-faladas.

Input:
  {
    "queue_json": [ { cena }, ... ],
    "audio_urls": [ "path/mp3", "", "path/outro.mp3", ... ]   # paralelo a queue_json
  }

Output:
  {
    "queue_json": [ ... ] ,    # com input_audio patched
    "patched_count": N,
    "skipped_count": M          # cenas sem audio_text ou sem audio_url
  }
"""

from __future__ import annotations

import os
from typing import Any

from workers._base import BaseWorker


class QueueAudioPatchWorker(BaseWorker):
    name = "queue-audio-patch"
    capabilities = ("video.queue_audio_patch",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        queue_json = payload.get("queue_json")
        if not isinstance(queue_json, list):
            raise ValueError("queue_json inválido ou ausente")

        audio_urls = payload.get("audio_urls") or []
        if not isinstance(audio_urls, list):
            raise ValueError("audio_urls deve ser lista")

        patched = 0
        skipped = 0
        for i, scene in enumerate(queue_json):
            if not isinstance(scene, dict):
                continue
            text = (scene.get("audio_text") or "").strip()
            if not text:
                skipped += 1
                continue
            if i >= len(audio_urls):
                skipped += 1
                continue
            url = audio_urls[i]
            if not url or not isinstance(url, str):
                skipped += 1
                continue
            scene["input_audio"] = url.strip()
            patched += 1

        return {
            "queue_json": queue_json,
            "patched_count": patched,
            "skipped_count": skipped,
        }


if __name__ == "__main__":
    port = int(os.environ.get("QUEUE_AUDIO_PATCH_PORT", 8121))
    QueueAudioPatchWorker().run(port=port)
