"""inemaimg-adapter — traduz contrato do imkt4 para API do inemaimg.

Quando o Gateway pede `image.generation`, o matcher pode escolher este
worker. Ele recebe o Job, chama a API do inemaimg local e devolve o URL
da imagem no S3/MinIO.

SKELETON — a integração real com inemaimg exige o endpoint e o shape da
API dele (em `/home/nmaldaner/projetos/inemaimg/`). Por ora, valida o
contrato e retorna URL mock.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from workers._base import BaseWorker

INEMAIMG_URL = os.environ.get("INEMAIMG_URL", "http://localhost:8010")


class InemaimgAdapter(BaseWorker):
    name = "inemaimg-adapter"
    capabilities = ("image.generation",)

    async def handle(self, job) -> dict[str, Any]:
        prompt = job.payload.get("prompt") or job.payload.get("prompts")
        if not prompt:
            raise ValueError("payload precisa de 'prompt' ou 'prompts'")

        # TODO: mapear payload para shape real do inemaimg.
        # Integração futura:
        #   async with httpx.AsyncClient() as client:
        #       r = await client.post(f"{INEMAIMG_URL}/generate", json={...})
        #       data = r.json()
        #       # upload para S3, devolver URL
        # Por enquanto, skeleton — só valida o pipeline.
        return {
            "image_url": f"s3://imkt4/mock/{job.job_id}.png",
            "prompt_used": prompt,
            "_note": "SKELETON: chamada real para inemaimg pendente",
        }


if __name__ == "__main__":
    InemaimgAdapter().run(port=8010)
