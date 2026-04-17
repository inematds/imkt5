"""yt-publish worker.

Capability: `video.publish`, `platform.youtube`. Porta 8302.

Upload resumable pra YouTube Data API v3 (videos.insert).

Sem credenciais OAuth: modo mocked.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from workers._base import BaseWorker

log = logging.getLogger("imkt4.workers.yt-publish")


class YTPublishWorker(BaseWorker):
    name = "yt-publish"
    capabilities = ("video.publish", "platform.youtube")

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        clip_path = payload.get("clip_path") or payload.get("artifact_url")
        dest = payload.get("_fanout_item") or payload.get("destination") or {}

        if not clip_path:
            raise ValueError("clip_path obrigatório")

        title = payload.get("title") or f"Clip {job.job_id[:8]}"
        description = payload.get("description") or payload.get("caption", "")
        tags = payload.get("tags") or []
        privacy = payload.get("privacy", "unlisted")
        category = str(payload.get("category", "22"))

        creds = await self._resolve_credentials(dest, job.tenant_id)
        if not creds:
            mock_id = f"MOCK_{uuid.uuid4().hex[:11]}"
            return {
                "video_id": mock_id,
                "video_url": f"https://youtu.be/{mock_id}",
                "mode": "mocked",
                "note": "sem credenciais OAuth — simulado",
                "destination": dest.get("external_id") or dest.get("binding_id"),
            }

        # baixa o clip localmente pra upload
        local_path = await _fetch_to_local(clip_path)
        try:
            access_token = await _refresh_access_token(creds)
            video_id = await _upload_video(
                local_path=local_path,
                access_token=access_token,
                title=title, description=description,
                tags=tags, privacy=privacy, category=category,
            )
        finally:
            try:
                if local_path and local_path.exists():
                    local_path.unlink()
            except Exception:  # noqa: BLE001
                pass

        return {
            "video_id": video_id,
            "video_url": f"https://youtu.be/{video_id}",
            "mode": "real",
            "destination": dest.get("external_id") or dest.get("binding_id"),
        }

    async def _resolve_credentials(
        self, dest: dict[str, Any], tenant_id: str,
    ) -> dict[str, Any] | None:
        """Retorna {client_id, client_secret, refresh_token} ou None."""
        # 1) KMS via credentials_ref
        ref = dest.get("credentials_ref")
        if ref:
            try:
                from imkt4.security import get_kms
                kms = get_kms()
                data = await kms.get(ref)
                if data:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        pass
            except Exception as exc:  # noqa: BLE001
                log.warning("KMS lookup %s: %s", ref, exc)

        # 2) env fallback
        client_id = os.environ.get("YOUTUBE_CLIENT_ID") or os.environ.get("CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET") or os.environ.get("CLIENT_SECRET")
        binding_id = dest.get("binding_id", "")
        rt = (
            os.environ.get(f"YT_CHANNEL_{binding_id.upper()}_REFRESH_TOKEN")
            or os.environ.get("YT_REFRESH_TOKEN")
        )
        if client_id and client_secret and rt:
            return {"client_id": client_id, "client_secret": client_secret, "refresh_token": rt}

        return None


async def _fetch_to_local(url: str) -> Path:
    """Baixa/resolve URL pra path local."""
    if url.startswith("file://"):
        return Path(url[len("file://"):])
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
        return Path(root) / url[len("/artifacts/"):]
    if url.startswith(("http://", "https://")):
        dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in r.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
        return dest
    return Path(url)


async def _refresh_access_token(creds: dict[str, str]) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def _upload_video(
    *, local_path: Path, access_token: str,
    title: str, description: str, tags: list[str],
    privacy: str, category: str,
) -> str:
    """YouTube Data API v3 — resumable upload."""
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    file_size = local_path.stat().st_size
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
        "X-Upload-Content-Length": str(file_size),
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1) Inicia resumable session
        r = await client.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        r.raise_for_status()
        upload_url = r.headers.get("location")
        if not upload_url:
            raise RuntimeError("sem Location na resposta de init")

        # 2) Upload em chunks (simples: corpo inteiro)
        with open(local_path, "rb") as f:
            body = f.read()
        r2 = await client.put(
            upload_url,
            headers={"Content-Type": "video/*",
                     "Content-Length": str(len(body))},
            content=body, timeout=600.0,
        )
        r2.raise_for_status()
        return r2.json().get("id", "")


if __name__ == "__main__":
    port = int(os.environ.get("YT_PUBLISH_PORT", 8302))
    YTPublishWorker().run(port=port)
