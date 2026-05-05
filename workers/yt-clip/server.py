"""yt-clip worker.

Capability: `video.clip_extraction`. Porta 8301.

Pipeline: yt-dlp → transcript → LLM (define clipes) → ffmpeg.
Modo mocked se ferramentas ausentes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json
from workers._base.storage import get_storage

log = logging.getLogger("imkt5.workers.yt-clip")

SYSTEM_PROMPT = """\
Você é editor de vídeo. Recebe transcrição com timestamps e um prompt
do usuário sobre o que extrair. Sugira de 1 a N trechos, respeitando
duração mínima e máxima.

Retorne APENAS JSON sem texto antes/depois:
{
  "clips": [
    {"start_s": 120, "end_s": 300, "title": "...", "reason": "..."}
  ]
}
"""


class YTClipWorker(BaseWorker):
    name = "yt-clip"
    capabilities = ("video.clip_extraction",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        # `lives` vem do stage ingest fanout — pode ser lista aninhada
        raw_lives = payload.get("lives") or []
        if raw_lives and isinstance(raw_lives[0], list):
            lives: list[dict] = [v for sub in raw_lives for v in (sub or [])]
        else:
            lives = list(raw_lives)

        prompt = payload.get("prompt", "Corte os melhores trechos")
        min_dur = int(payload.get("min_duration", 120))
        max_dur = int(payload.get("max_duration", 900))
        max_clips = int(payload.get("max_clips", 3))

        if not lives:
            return {"clips": [], "mode": "mocked", "note": "sem lives no input"}

        # Checa ferramentas
        ytdlp = shutil.which("yt-dlp")
        ffmpeg = shutil.which("ffmpeg")
        if not (ytdlp and ffmpeg):
            return {
                "clips": [], "mode": "mocked",
                "note": f"deps ausentes: yt-dlp={bool(ytdlp)} ffmpeg={bool(ffmpeg)}",
            }

        # Processa só o primeiro vídeo (pipeline sequencial por cena do stage)
        live = lives[0]
        video_id = live.get("video_id")
        if not video_id:
            raise ValueError("live sem video_id")

        return await self._process_video(
            job, video_id, prompt, min_dur, max_dur, max_clips,
        )

    async def _process_video(
        self, job, video_id: str, prompt: str,
        min_dur: int, max_dur: int, max_clips: int,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"yt-clip-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)
            video_path = tmp_path / "source.mp4"

            # 1) Download via yt-dlp
            dl = await _run([
                "yt-dlp", "-f", "best[ext=mp4]/best",
                "-o", str(video_path),
                f"https://youtube.com/watch?v={video_id}",
            ])
            if dl != 0 or not video_path.exists():
                return {"clips": [], "mode": "mocked", "note": f"download falhou ({dl})"}

            # 2) Transcrição (opcional, usa youtube-transcript-api se disponível)
            transcript = await _fetch_transcript(video_id)

            # 3) LLM decide clipes
            user_msg = (
                f"Prompt do usuário: {prompt}\n\n"
                f"Duração mínima: {min_dur}s, máxima: {max_dur}s, "
                f"até {max_clips} clipes.\n\n"
                f"Transcrição (partial):\n{transcript[:8000] if transcript else '[sem transcrição disponível — use intuição baseada em duração do vídeo]'}\n"
            )
            try:
                decision = await complete_json(
                    system_prompt=SYSTEM_PROMPT, user_prompt=user_msg, temperature=0.3,
                )
            except Exception as exc:  # noqa: BLE001
                return {"clips": [], "mode": "mocked", "note": f"LLM falhou: {exc}"}

            clips_spec = decision.get("clips", [])[:max_clips]
            if not clips_spec:
                return {"clips": [], "mode": "real", "note": "LLM não sugeriu clipes"}

            # 4) Recorta cada
            storage = get_storage()
            out_clips = []
            for i, spec in enumerate(clips_spec):
                start_s = int(spec.get("start_s", 0))
                end_s = int(spec.get("end_s", start_s + min_dur))
                dur = end_s - start_s
                if dur < min_dur or dur > max_dur:
                    continue
                clip_file = tmp_path / f"clip_{i:02d}.mp4"
                rc = await _run([
                    "ffmpeg", "-y", "-ss", str(start_s), "-to", str(end_s),
                    "-i", str(video_path),
                    "-c", "copy", str(clip_file),
                ])
                if rc != 0 or not clip_file.exists():
                    continue
                url = storage.save_bytes(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    filename=f"clip_{i:02d}.mp4",
                    data=clip_file.read_bytes(),
                )
                out_clips.append({
                    "clip_path": url,
                    "start_s": start_s, "end_s": end_s,
                    "title": spec.get("title", f"Clip {i+1}"),
                    "reason": spec.get("reason", ""),
                })

            return {
                "video_id": video_id,
                "clips": out_clips,
                # Compat com a receita yt-clip-publish — espera clip_path único
                "clip_path": out_clips[0]["clip_path"] if out_clips else None,
                "mode": "real",
            }


async def _run(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning("cmd %s rc=%s stderr=%s", cmd[0], proc.returncode,
                    stderr.decode(errors="ignore")[-300:])
    return proc.returncode


async def _fetch_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(
            None, lambda: YouTubeTranscriptApi.get_transcript(
                video_id, languages=["pt", "pt-BR", "en"]
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.info("transcript falhou %s: %s", video_id, exc)
        return None
    # concat como "[mm:ss] texto"
    lines = []
    for c in chunks:
        t = int(c["start"])
        m, s = divmod(t, 60)
        lines.append(f"[{m:02d}:{s:02d}] {c['text']}")
    return "\n".join(lines)


if __name__ == "__main__":
    port = int(os.environ.get("YT_CLIP_PORT", 8301))
    YTClipWorker().run(port=port)
