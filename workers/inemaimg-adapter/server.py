"""inemaimg-adapter — wrapper HTTP real sobre o servidor inemaimg.

Adapta o contrato do imkt4 (`capability=image.generation`) para a API do
inemaimg (`POST /generate`). Fluxo:

  imkt4 Job payload → POST inemaimg/generate → base64 PNG
                    → storage.save_base64 → URL (file:// em dev, s3:// em prod)

Payload esperado (mínimo):
  {
    "prompt": "...",
    "model": "qwen-edit-2511",  # opcional; default do env
    "images": ["base64..."],     # opcional; só para qwen-edit
    "steps": 40,                  # opcional
    "width": 1024, "height": 768,
    "seed": 42
  }

Output:
  {
    "image_url": "file:///.../generated.png",
    "model_used": "qwen-edit-2511",
    "generation_time_s": 12.5
  }
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

INEMAIMG_URL = os.environ.get("INEMAIMG_URL", "http://localhost:8000")
INEMAIMG_MODEL_DEFAULT = os.environ.get("INEMAIMG_MODEL", "qwen-edit-2511")
INEMAIMG_TIMEOUT = float(os.environ.get("INEMAIMG_TIMEOUT", "180"))


class InemaimgAdapter(BaseWorker):
    name = "inemaimg-adapter"
    capabilities = ("image.generation",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        prompt = payload.get("prompt")
        if not prompt:
            raise ValueError("payload precisa de 'prompt'")

        model = payload.get("model") or INEMAIMG_MODEL_DEFAULT

        # Monta request para inemaimg
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }
        # passagens opcionais (passa se veio no payload)
        for k in (
            "images", "steps", "guidance_scale", "true_cfg_scale",
            "negative_prompt", "width", "height", "seed",
            "lora", "lora_weight",
        ):
            if k in payload:
                body[k] = payload[k]

        async with httpx.AsyncClient(timeout=INEMAIMG_TIMEOUT) as client:
            resp = await client.post(f"{INEMAIMG_URL}/generate", json=body)
            resp.raise_for_status()
            data = resp.json()

        b64 = data["image"]
        filename = f"{model}-{job.job_id}.png"
        storage = get_storage()
        url = storage.save_base64(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=filename,
            b64=b64,
        )

        return {
            "image_url": url,
            "model_used": data.get("model_used", model),
            "generation_time_s": data.get("generation_time_s"),
            "gpu_memory_allocated_gb": data.get("gpu_memory_allocated_gb"),
        }


if __name__ == "__main__":
    InemaimgAdapter().run(port=8010)
