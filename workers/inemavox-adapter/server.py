"""inemavox-adapter — wrapper HTTP sobre o job-queue do inemavox.

Esconde o modelo async do inemavox atrás de uma chamada sync do ponto de
vista do imkt5. Fluxo:

  imkt5 Job → POST inemavox/api/jobs/tts → job_id
            → poll GET inemavox/api/jobs/{id} até completed
            → GET inemavox/api/jobs/{id}/audio → bytes
            → storage.save_bytes → URL

Capabilities:
- audio.tts
- audio.dubbing (via /api/jobs/voice-clone)
- audio.transcribe (via /api/jobs/transcribe)

Payload mínimo (audio.tts):
  {
    "text": "olá mundo",
    "engine": "edge",   # edge | chatterbox
    "lang": "pt"
  }
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt5.inemavox")

from imkt5.config import load as _load_cfg
_CFG = _load_cfg().workers.inemavox_adapter
INEMAVOX_URL = os.environ.get("INEMAVOX_URL", _CFG.upstream_url)
POLL_INTERVAL = float(os.environ.get("INEMAVOX_POLL_INTERVAL", _CFG.poll_interval_seconds))
POLL_MAX = int(os.environ.get("INEMAVOX_POLL_MAX_SECONDS", _CFG.poll_max_seconds))


class InemavoxAdapter(BaseWorker):
    name = "inemavox-adapter"
    capabilities = ("audio.tts", "audio.dubbing", "audio.transcribe")

    async def handle(self, job) -> dict[str, Any]:
        cap = job.required_capability

        if cap == "audio.tts":
            return await self._handle_tts(job)
        if cap == "audio.dubbing":
            return await self._handle_voice_clone(job)
        if cap == "audio.transcribe":
            return await self._handle_transcribe(job)
        raise ValueError(f"capability não suportada: {cap}")

    # ── audio.tts ─────────────────────────────────────────────────────
    async def _handle_tts(self, job) -> dict[str, Any]:
        payload = job.payload
        text = payload.get("text") or ""
        text = text.strip() if isinstance(text, str) else str(text or "")
        if not text:
            # Cena sem narração (ex: pattern_interrupt silencioso) — devolve
            # stub de 0.3s de silêncio cacheado. Permite fanout por cena sem
            # explodir quando uma cena tem narração vazia.
            return await self._silent_stub(job)

        # `or` trata explicitamente None/"" (receita passa None quando
        # input opcional não foi fornecido).
        engine = payload.get("engine") or "edge"
        if engine == "auto":
            engine = "edge"
        lang = payload.get("lang") or "pt"
        # Normaliza "pt-BR" → "pt" (edge usa locale curto)
        if lang and lang.startswith("pt"):
            lang = "pt"

        body = {
            "text": text,
            "engine": engine,
            "lang": lang,
        }

        # Dedup: sha256(text+voice+lang+engine+speed) → cache key.
        # Mesmo áudio gerado novamente devolve URL cacheada (economiza 40-60%
        # em runs repetidos/similares). `voice` opcional no payload — se user
        # passar voice específica, faz parte da chave.
        voice = (payload.get("voice") or "").strip()
        speed = str(payload.get("speed") or "1.0")
        dedup_material = f"{text}|{engine}|{lang}|{voice}|{speed}"
        dedup_hash = hashlib.sha256(dedup_material.encode("utf-8")).hexdigest()
        cache_key = f"{dedup_hash}.mp3"
        storage = get_storage()
        cached_url = storage.get_cached(namespace="tts", key=cache_key)
        if cached_url:
            log.info("tts cache HIT key=%s text=%r", dedup_hash[:12], text[:40])
            return {
                "audio_url": cached_url,
                "inemavox_job_id": None,
                "engine": engine,
                "duration_seconds": None,
                "cached": True,
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{INEMAVOX_URL}/api/jobs/tts", json=body)
            r.raise_for_status()
            vx_job_id = r.json()["id"]
            await self._wait_completed(client, vx_job_id)
            audio_resp = await client.get(
                f"{INEMAVOX_URL}/api/jobs/{vx_job_id}/audio"
            )
            audio_resp.raise_for_status()
            audio = audio_resp.content
            ext = self._guess_audio_ext(audio_resp.headers.get("content-type", ""))

        # Salva no cache cross-tenant (dedup) E no storage per-job
        # (pra auditoria). URL devolvida é do cache (compartilhável).
        cache_url = storage.save_cached(
            namespace="tts",
            key=f"{dedup_hash}.{ext}",
            data=audio,
        )
        log.info("tts cache MISS key=%s text=%r saved=%s",
                 dedup_hash[:12], text[:40], cache_url)
        return {
            "audio_url": cache_url,
            "inemavox_job_id": vx_job_id,
            "engine": body["engine"],
            "duration_seconds": None,
            "cached": False,
            "cache_key": dedup_hash,
        }

    async def _silent_stub(self, job) -> dict[str, Any]:
        """Gera (ou reusa) um mp3 silencioso de 0.3s pra cenas sem narração."""
        key = "silent_300ms.mp3"
        storage = get_storage()
        cached = storage.get_cached(namespace="tts", key=key)
        if cached:
            return {
                "audio_url": cached,
                "inemavox_job_id": None,
                "engine": "silence",
                "duration_seconds": 0.3,
                "cached": True,
            }
        # Gera via ffmpeg: anullsrc → mp3 0.3s
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi",
                 "-i", "anullsrc=r=44100:cl=stereo",
                 "-t", "0.3", "-c:a", "libmp3lame", "-b:a", "64k", tmp],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            data = open(tmp, "rb").read()
        finally:
            os.unlink(tmp)
        url = storage.save_cached(namespace="tts", key=key, data=data)
        return {
            "audio_url": url,
            "inemavox_job_id": None,
            "engine": "silence",
            "duration_seconds": 0.3,
            "cached": False,
        }

    # ── audio.dubbing (voice-clone) ──────────────────────────────────
    async def _handle_voice_clone(self, job) -> dict[str, Any]:
        payload = job.payload
        text = payload.get("text")
        ref_url = payload.get("ref_url")
        if not text or not ref_url:
            raise ValueError("audio.dubbing precisa de 'text' e 'ref_url'")

        body = {
            "text": text,
            "ref_url": ref_url,
            "engine": payload.get("engine", "chatterbox"),
            "lang": payload.get("lang", "pt"),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{INEMAVOX_URL}/api/jobs/voice-clone/url", json=body
            )
            r.raise_for_status()
            vx_job_id = r.json()["id"]
            await self._wait_completed(client, vx_job_id)
            audio_resp = await client.get(
                f"{INEMAVOX_URL}/api/jobs/{vx_job_id}/audio"
            )
            audio_resp.raise_for_status()
            audio = audio_resp.content

        url = get_storage().save_bytes(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=f"vc-{job.job_id}.wav",
            data=audio,
        )
        return {"audio_url": url, "inemavox_job_id": vx_job_id}

    # ── audio.transcribe ──────────────────────────────────────────────
    async def _handle_transcribe(self, job) -> dict[str, Any]:
        payload = job.payload
        src = payload.get("input")
        if not src:
            raise ValueError("audio.transcribe precisa de 'input'")

        fmt = payload.get("format", "srt")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{INEMAVOX_URL}/api/jobs/transcribe", json={"input": src}
            )
            r.raise_for_status()
            vx_job_id = r.json()["id"]
            await self._wait_completed(client, vx_job_id)
            t = await client.get(
                f"{INEMAVOX_URL}/api/jobs/{vx_job_id}/transcript",
                params={"format": fmt},
            )
            t.raise_for_status()
            content = t.content

        url = get_storage().save_bytes(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=f"transcript-{job.job_id}.{fmt}",
            data=content,
        )
        return {"transcript_url": url, "inemavox_job_id": vx_job_id}

    # ── helpers ───────────────────────────────────────────────────────
    async def _wait_completed(self, client: httpx.AsyncClient, vx_job_id: str) -> None:
        elapsed = 0.0
        while elapsed < POLL_MAX:
            r = await client.get(f"{INEMAVOX_URL}/api/jobs/{vx_job_id}")
            r.raise_for_status()
            status = r.json().get("status")
            if status == "completed":
                return
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError(f"inemavox job {vx_job_id} {status}")
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
        raise TimeoutError(
            f"inemavox job {vx_job_id} não completou em {POLL_MAX}s"
        )

    @staticmethod
    def _guess_audio_ext(content_type: str) -> str:
        if "mpeg" in content_type or "mp3" in content_type:
            return "mp3"
        return "wav"


if __name__ == "__main__":
    InemavoxAdapter().run(
        port=int(os.environ.get("IMKT5_INEMAVOX_ADAPTER_PORT", _CFG.port))
    )
