"""inemavox-adapter — wrapper HTTP sobre o job-queue do inemavox.

Esconde o modelo async do inemavox atrás de uma chamada sync do ponto de
vista do imkt4. Fluxo:

  imkt4 Job → POST inemavox/api/jobs/tts → job_id
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
import os
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

INEMAVOX_URL = os.environ.get("INEMAVOX_URL", "http://localhost:8000")
POLL_INTERVAL = float(os.environ.get("INEMAVOX_POLL_INTERVAL", "1.5"))
POLL_MAX = int(os.environ.get("INEMAVOX_POLL_MAX_SECONDS", "600"))


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
        text = payload.get("text")
        if not text:
            raise ValueError("audio.tts precisa de 'text'")

        body = {
            "text": text,
            "engine": payload.get("engine", "edge"),
            "lang": payload.get("lang", "pt"),
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

        url = get_storage().save_bytes(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=f"tts-{job.job_id}.{ext}",
            data=audio,
        )
        return {
            "audio_url": url,
            "inemavox_job_id": vx_job_id,
            "engine": body["engine"],
            "duration_seconds": None,  # inemavox não devolve; worker downstream calcula se precisa
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
    InemavoxAdapter().run(port=int(os.environ.get("IMKT4_INEMAVOX_ADAPTER_PORT", "8021")))
