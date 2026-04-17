"""ffmpeg-local worker — renderer de video a partir de scene_plan.

Capability: `video.render`. Porta 8105.

MVP: imagens estáticas (sem motion) + áudio. Text overlay virá depois.

Input (payload):
  {
    "scene_plan": {
      "width": 1080, "height": 1920, "format": "9:16",
      "narration_file": "URL opcional (/artifacts/... ou file:// ou http)",
      "scenes": [
        {"image": "URL", "duration": 3, "text_overlay": "...", ...},
        ...
      ]
    }
  }

Output:
  { "video_url": "/artifacts/<tenant>/<job>/video.mp4",
    "duration_s": 15.0,
    "scene_count": 5 }
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage


class FfmpegLocalWorker(BaseWorker):
    name = "ffmpeg-local"
    capabilities = ("video.render",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        plan = payload.get("scene_plan") or payload
        scenes = plan.get("scenes") or []
        if not scenes:
            raise ValueError("scene_plan precisa de 'scenes' não vazio")

        width = int(plan.get("width", 1080))
        height = int(plan.get("height", 1920))
        narration_url = plan.get("narration_file")

        with tempfile.TemporaryDirectory(prefix=f"ffrender-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)

            # 1) Baixa/copia todos os assets pro tmp
            image_paths: list[Path] = []
            for i, sc in enumerate(scenes):
                img_url = sc.get("image")
                if not img_url:
                    raise ValueError(f"scene {i} sem campo 'image'")
                img_local = tmp_path / f"scene_{i:02d}.png"
                await _fetch_to(img_url, img_local)
                image_paths.append(img_local)

            audio_local: Path | None = None
            if narration_url:
                audio_local = tmp_path / "narration.mp3"
                try:
                    await _fetch_to(narration_url, audio_local)
                except Exception:
                    audio_local = None

            # 2) Renderiza cada cena como mp4 parcial
            scene_clips: list[Path] = []
            for i, (sc, img_path) in enumerate(zip(scenes, image_paths)):
                dur = max(1, int(sc.get("duration", 3)))
                out = tmp_path / f"clip_{i:02d}.mp4"
                await _run_ffmpeg([
                    "-y", "-loop", "1", "-framerate", "30",
                    "-t", str(dur), "-i", str(img_path),
                    "-vf", (
                        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height}"
                    ),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "veryfast", "-r", "30",
                    str(out),
                ])
                scene_clips.append(out)

            # 3) Concat via listfile
            listfile = tmp_path / "concat.txt"
            listfile.write_text("\n".join(f"file '{p}'" for p in scene_clips))
            concat_mp4 = tmp_path / "concat.mp4"
            await _run_ffmpeg([
                "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c", "copy",
                str(concat_mp4),
            ])

            # 4) Muxa com áudio se disponível
            final = tmp_path / "final.mp4"
            if audio_local and audio_local.exists() and audio_local.stat().st_size > 0:
                await _run_ffmpeg([
                    "-y", "-i", str(concat_mp4), "-i", str(audio_local),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", str(final),
                ])
            else:
                final = concat_mp4

            # 5) Salva via storage e retorna URL
            storage = get_storage()
            url = storage.save_bytes(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                filename="video.mp4",
                data=final.read_bytes(),
            )

        total_dur = sum(max(1, int(sc.get("duration", 3))) for sc in scenes)
        return {
            "video_url": url,
            "duration_s": float(total_dur),
            "scene_count": len(scenes),
        }


# ── helpers ───────────────────────────────────────────────────────────
async def _fetch_to(url: str, dest: Path) -> None:
    """URL local ('/artifacts/...' ou 'file://') ou http(s) → arquivo."""
    if url.startswith("file://"):
        src = Path(url[len("file://"):])
        dest.write_bytes(src.read_bytes())
        return
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
        src = Path(root) / url[len("/artifacts/"):]
        dest.write_bytes(Path(src).read_bytes())
        return
    if url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return
    # fallback: path absoluto
    dest.write_bytes(Path(url).read_bytes())


async def _run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode(errors="ignore")[-500:]
        raise RuntimeError(f"ffmpeg falhou (rc={proc.returncode}): {tail}")


if __name__ == "__main__":
    port = int(os.environ.get("FFMPEG_LOCAL_PORT", 8105))
    FfmpegLocalWorker().run(port=port)
