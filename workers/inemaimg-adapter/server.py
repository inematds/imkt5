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

import logging
import os
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt4.workers.inemaimg")
logging.basicConfig(level=logging.INFO)

from imkt4.config import load as _load_cfg
_CFG = _load_cfg().workers.inemaimg_adapter
INEMAIMG_URL = os.environ.get("INEMAIMG_URL", _CFG.upstream_url)
INEMAIMG_MODEL_DEFAULT = os.environ.get("INEMAIMG_MODEL", _CFG.default_model)
INEMAIMG_TIMEOUT = float(os.environ.get("INEMAIMG_TIMEOUT", _CFG.request_timeout_seconds))


class InemaimgAdapter(BaseWorker):
    name = "inemaimg-adapter"
    capabilities = ("image.generation",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        prompt = payload.get("prompt")
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(
                f"payload precisa de 'prompt' (string não-vazia). Recebido: {type(prompt).__name__}={prompt!r}"
            )

        model = payload.get("model") or INEMAIMG_MODEL_DEFAULT

        # Monta request para inemaimg
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }
        for k in (
            "images", "steps", "guidance_scale", "true_cfg_scale",
            "negative_prompt", "width", "height", "seed",
            "lora", "lora_weight",
        ):
            if k in payload:
                body[k] = payload[k]

        log.info("job %s → upstream %s/generate model=%s prompt=%s",
                 job.job_id[:8], INEMAIMG_URL, model, prompt[:80])

        try:
            async with httpx.AsyncClient(timeout=INEMAIMG_TIMEOUT) as client:
                resp = await client.post(f"{INEMAIMG_URL}/generate", json=body)
                if resp.status_code != 200:
                    # loga o corpo do erro do upstream antes de propagar
                    err_body = resp.text[:500] if resp.text else "(vazio)"
                    log.warning("upstream %s → %s body=%s",
                                INEMAIMG_URL, resp.status_code, err_body)
                    raise RuntimeError(
                        f"inemaimg upstream retornou {resp.status_code}: {err_body}"
                    )
                data = resp.json()
        except httpx.HTTPError as exc:
            log.warning("job %s httpx err: %s", job.job_id[:8], exc)
            raise RuntimeError(f"httpx: {type(exc).__name__}: {exc}") from exc

        b64 = data.get("image")
        if not b64:
            raise RuntimeError(f"upstream não retornou 'image'. keys={list(data.keys())}")

        filename = f"{model}-{job.job_id}.png"
        try:
            storage = get_storage()
            url = storage.save_base64(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                filename=filename,
                b64=b64,
            )
        except Exception as exc:
            log.warning("job %s storage err: %s", job.job_id[:8], exc)
            raise RuntimeError(f"storage.save_base64: {type(exc).__name__}: {exc}") from exc

        return {
            "image_url": url,
            "model_used": data.get("model_used", model),
            "generation_time_s": data.get("generation_time_s"),
            "gpu_memory_allocated_gb": data.get("gpu_memory_allocated_gb"),
        }


if __name__ == "__main__":
    InemaimgAdapter().run(
        port=int(os.environ.get("IMKT4_INEMAIMG_ADAPTER_PORT", _CFG.port))
    )
