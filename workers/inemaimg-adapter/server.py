"""inemaimg-adapter — wrapper HTTP real sobre o servidor inemaimg.

Adapta o contrato do imkt5 (`capability=image.generation`) para a API do
inemaimg (`POST /generate`). Fluxo:

  imkt5 Job payload → POST inemaimg/generate → base64 PNG
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

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from imkt5.config import load as _load_cfg
from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt5.workers.inemaimg")
logging.basicConfig(level=logging.INFO)

_CFG = _load_cfg().workers.inemaimg_adapter
INEMAIMG_URL = os.environ.get("INEMAIMG_URL", _CFG.upstream_url)
INEMAIMG_MODEL_DEFAULT = os.environ.get("INEMAIMG_MODEL", _CFG.default_model)
INEMAIMG_TIMEOUT = float(os.environ.get("INEMAIMG_TIMEOUT", _CFG.request_timeout_seconds))

PROFILES_PATH = Path(__file__).resolve().parents[2] / "config" / "image-model-profiles.json"

# Regra universal: imagens geradas NUNCA devem ter texto embutido.
# Texto/headline/caption/CTA é renderizado DEPOIS (carousel-designer/ffmpeg).
# Mantido como fallback quando o profile do modelo não especifica.
TEXT_NEGATIVE = (
    "text, letters, words, captions, writing, font, typography, "
    "logo, watermark, signature, label, sign, banner, heading, "
    "title text, handwriting, script, calligraphy, numbers, "
    "alphabet, characters, roman letters, latin letters, "
    "poster with text, book cover, magazine cover, billboard, "
    "newspaper, document, printed text, typed text, written words, "
    "headline text, caption text, subtitle, tagline, slogan, "
    "embedded text, overlay text, watermarked, autograph, stamp, "
    "readable text, legible letters, (text:1.6), (words:1.6), (letters:1.5)"
)


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, Any]:
    """Carrega config/image-model-profiles.json uma vez (cache)."""
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("profiles file não carregou (%s) — usa defaults hardcoded", exc)
        return {
            "defaults": {
                "max_length": 500,
                "style_suffix": TEXT_NEGATIVE,
                "safety_suffix": "No weapons, no violence, no nudity.",
                "context_suffix": "",
                "negative_prompt_support": True,
                "orientation_in_prompt": True,
                "style_prefix": "",
            },
            "models": {},
        }


def _profile_for(model: str) -> dict[str, Any]:
    """Retorna config efetiva pro modelo: merge(defaults, models[model])."""
    data = _load_profiles()
    defaults = dict(data.get("defaults", {}))
    model_cfg = data.get("models", {}).get(model, {})
    # Merge raso: model_cfg sobrescreve defaults em campos que existirem
    out = dict(defaults)
    for k, v in model_cfg.items():
        out[k] = v
    out["_model_name"] = model
    return out


def build_image_prompt(
    user_prompt: str,
    *,
    model: str,
    width: int | None = None,
    height: int | None = None,
    allow_text_in_image: bool = False,
    user_negative_prompt: str | None = None,
) -> tuple[str, str | None]:
    """Monta (prompt_final, negative_prompt_final) aplicando o profile
    do modelo.

    Regras:
    - style_prefix + user_prompt + orientation_hint + style_suffix + safety_suffix + context_suffix
    - Trunca pro max_length do modelo (com aviso)
    - Se negative_prompt_support=false: concatena "no X" no positive
    - Se allow_text_in_image=true: pula TEXT_NEGATIVE (caso raro)
    """
    cfg = _profile_for(model)

    parts = []
    prefix = (cfg.get("style_prefix") or "").strip()
    if prefix:
        parts.append(prefix)

    parts.append(user_prompt.strip())

    # Orientation hint (se profile pedir e temos dimensões)
    if cfg.get("orientation_in_prompt") and width and height:
        ratio = width / height
        if abs(ratio - 1.0) < 0.05:
            parts.append("Square 1:1.")
        elif ratio < 1.0:
            parts.append("Vertical 9:16.")
        else:
            parts.append("Horizontal 16:9.")

    # style_suffix: inclui a regra anti-texto do modelo
    style_suffix = (cfg.get("style_suffix") or "").strip()
    if style_suffix and not allow_text_in_image:
        parts.append(style_suffix)
    elif style_suffix and allow_text_in_image:
        # remove "no text/no words" do suffix quando user quer texto na imagem
        filtered = ", ".join(
            s for s in style_suffix.split(",")
            if not any(t in s.lower() for t in ("no text", "no words", "no letters", "no watermark", "no typography"))
        ).strip(", .")
        if filtered:
            parts.append(filtered + ".")

    safety = (cfg.get("safety_suffix") or "").strip()
    if safety:
        parts.append(safety)

    ctx = (cfg.get("context_suffix") or "").strip()
    if ctx:
        parts.append(ctx)

    full = " ".join(p.rstrip(".") + "." for p in parts if p)

    # Trunca
    max_len = int(cfg.get("max_length", 500))
    if len(full) > max_len:
        log.warning(
            "prompt truncado %d → %d chars (model=%s)",
            len(full), max_len, model,
        )
        full = full[:max_len - 3].rsplit(" ", 1)[0] + "..."

    # Negative prompt
    negative = None
    if cfg.get("negative_prompt_support"):
        bits = []
        if user_negative_prompt and user_negative_prompt.strip():
            bits.append(user_negative_prompt.strip())
        if not allow_text_in_image:
            bits.append(TEXT_NEGATIVE)
        negative = ", ".join(bits) if bits else None

    return full, negative


class InemaimgAdapter(BaseWorker):
    name = "inemaimg-adapter"
    capabilities = ("image.generation",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        user_prompt = payload.get("prompt")
        if not user_prompt or not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError(
                f"payload precisa de 'prompt' (string não-vazia). Recebido: {type(user_prompt).__name__}={user_prompt!r}"
            )

        model = payload.get("model") or INEMAIMG_MODEL_DEFAULT

        # ── build_image_prompt aplica style_prefix+suffix+safety+orientation
        # do profile do modelo (timesmkt3-style). Substitui TEXT_NEGATIVE
        # hardcoded por regras específicas do modelo.
        width = payload.get("width")
        height = payload.get("height")
        full_prompt, final_negative = build_image_prompt(
            user_prompt,
            model=model,
            width=width, height=height,
            allow_text_in_image=bool(payload.get("allow_text_in_image")),
            user_negative_prompt=payload.get("negative_prompt"),
        )

        # Aplica default_steps/guidance do profile se user não passou
        profile = _profile_for(model)

        body: dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
        }
        if final_negative:
            body["negative_prompt"] = final_negative

        # Aplica defaults do profile quando user não especificou
        if "steps" not in payload and profile.get("default_steps"):
            body["steps"] = profile["default_steps"]
        if "guidance_scale" not in payload and profile.get("default_guidance_scale"):
            body["guidance_scale"] = profile["default_guidance_scale"]

        # Repassa campos que o user enviou (override explícito tem prioridade)
        for k in (
            "images", "steps", "guidance_scale", "true_cfg_scale",
            "width", "height", "seed", "lora", "lora_weight",
        ):
            if k in payload:
                body[k] = payload[k]

        log.info("job %s → upstream %s/generate model=%s prompt=%s",
                 job.job_id[:8], INEMAIMG_URL, model, full_prompt[:80])

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
        port=int(os.environ.get("IMKT5_INEMAIMG_ADAPTER_PORT", _CFG.port))
    )
