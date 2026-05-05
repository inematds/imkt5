"""tiktok-ingest worker.

Capability: `video.source_ingest` (prioridade menor que yt-source-ingest;
se `source.external_id` começa com @ ou URL tiktok, este worker pega).
Porta 8303.

Scan via yt-dlp --flat-playlist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

from workers._base import BaseWorker

log = logging.getLogger("imkt5.workers.tiktok-ingest")

_seen: dict[str, set[str]] = {}


class TikTokIngestWorker(BaseWorker):
    name = "tiktok-ingest"
    capabilities = ("video.source_ingest",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        source = payload.get("_fanout_item") or payload.get("source") or {}
        external = source.get("external_id") or source.get("handle", "")
        max_videos = int(payload.get("max_videos", 10))

        if not external:
            raise ValueError("source.external_id (handle) obrigatório")

        # Só responde pra handles TikTok
        if not (external.startswith("@") or "tiktok.com" in external):
            return {
                "channel_id": external,
                "new_lives": [],
                "total_new": 0,
                "mode": "mocked",
                "note": "não parece ser TikTok handle",
            }

        if not shutil.which("yt-dlp"):
            return {"channel_id": external, "new_lives": [], "total_new": 0,
                    "mode": "mocked", "note": "yt-dlp ausente"}

        url = external
        if not url.startswith("http"):
            handle = external if external.startswith("@") else f"@{external}"
            url = f"https://www.tiktok.com/{handle}"

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(max_videos),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return {"channel_id": external, "new_lives": [], "total_new": 0,
                    "mode": "real", "note": "yt-dlp falhou"}

        try:
            data = json.loads(stdout.decode())
            entries = data.get("entries", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("tiktok parse: %s", exc)
            entries = []

        seen = _seen.setdefault(external, set())
        new_lives: list[dict[str, Any]] = []
        for e in entries:
            vid = str(e.get("id") or "")
            if not vid or vid in seen:
                continue
            new_lives.append({
                "video_id": vid,
                "title": e.get("title", ""),
                "url": e.get("url") or f"https://www.tiktok.com/@{external.lstrip('@')}/video/{vid}",
            })
            seen.add(vid)

        return {
            "channel_id": external,
            "new_lives": new_lives,
            "total_new": len(new_lives),
            "mode": "real",
        }


if __name__ == "__main__":
    port = int(os.environ.get("TIKTOK_INGEST_PORT", 8303))
    TikTokIngestWorker().run(port=port)
