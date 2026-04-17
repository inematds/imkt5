"""yt-source-ingest worker.

Capability: `video.source_ingest`. Porta 8300.

Consulta YouTube Data API v3 pela playlist de uploads de um canal
(contentDetails.relatedPlaylists.uploads) e retorna vídeos publicados
nas últimas N horas que ainda não foram vistos (cache em memória —
TODO: Postgres `seen_videos`).

Sem `YOUTUBE_API_KEY`: modo mocked (retorna lista vazia, não quebra).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from workers._base import BaseWorker

YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# cache muito simples: channel_id → set de video_ids já retornados
_seen: dict[str, set[str]] = {}


class YTSourceIngestWorker(BaseWorker):
    name = "yt-source-ingest"
    capabilities = ("video.source_ingest",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        source = payload.get("_fanout_item") or payload.get("source") or {}
        channel_id = source.get("external_id") or source.get("channel_id", "")
        since_hours = int(payload.get("since_hours", 24))

        if not channel_id:
            raise ValueError("source.external_id (channel_id) obrigatório")

        if not YT_API_KEY:
            return {
                "channel_id": channel_id,
                "new_lives": [],
                "total_new": 0,
                "mode": "mocked",
                "note": "YOUTUBE_API_KEY ausente",
            }

        # 1) Descobre uploads playlist do canal
        async with httpx.AsyncClient(timeout=30.0) as client:
            ch_resp = await client.get(
                f"{YT_API_BASE}/channels",
                params={"part": "contentDetails", "id": channel_id, "key": YT_API_KEY},
            )
            ch_resp.raise_for_status()
            items = ch_resp.json().get("items", [])
            if not items:
                return {"channel_id": channel_id, "new_lives": [], "total_new": 0,
                        "mode": "real", "note": "canal não encontrado"}
            uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # 2) Lista últimos 10 uploads
            pl_resp = await client.get(
                f"{YT_API_BASE}/playlistItems",
                params={
                    "part": "snippet,contentDetails",
                    "playlistId": uploads_pl,
                    "maxResults": 10,
                    "key": YT_API_KEY,
                },
            )
            pl_resp.raise_for_status()
            entries = pl_resp.json().get("items", [])

        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        seen = _seen.setdefault(channel_id, set())
        new: list[dict[str, Any]] = []
        for e in entries:
            vid = e["contentDetails"].get("videoId")
            if not vid or vid in seen:
                continue
            published_raw = e["contentDetails"].get("videoPublishedAt") or \
                e["snippet"].get("publishedAt", "")
            try:
                pub = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                continue
            if pub < cutoff:
                continue
            new.append({
                "video_id": vid,
                "title": e["snippet"].get("title", ""),
                "published_at": published_raw,
            })
            seen.add(vid)

        return {
            "channel_id": channel_id,
            "new_lives": new,
            "total_new": len(new),
            "mode": "real",
        }


if __name__ == "__main__":
    port = int(os.environ.get("YT_SOURCE_INGEST_PORT", 8300))
    YTSourceIngestWorker().run(port=port)
