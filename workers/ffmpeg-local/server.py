"""ffmpeg-local worker — renderer de video a partir de scene_plan.

Capability: `video.render`. Porta 8105.

Gera MP4 H.264/AAC 9:16 a partir do scene_plan produzido pelo
video-quick worker. Inclui:

  - Motion simples (push-in via zoompan)
  - Text overlay com drawtext (headline do scene_plan em cada cena)
  - Narração mixada (com padding de silêncio se áudio curto)

Input (payload):
  {
    "scene_plan": {
      "width": 1080, "height": 1920,
      "scenes": [
        {"image": "URL", "duration": 3, "text_overlay": "...",
         "text_position": "top|center|bottom",
         "text_color": "#FFFFFF", "font_size": 88,
         "motion": {"type": "push-in|..."},
         ... }
      ]
    },
    "narration_url": "URL opcional"   # override do scene_plan.narration_file
  }

Output:
  { "video_url": "/artifacts/<tenant>/<job>/video.mp4",
    "duration_s": 15.0, "scene_count": 5 }
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


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
        narration_url = payload.get("narration_url") or plan.get("narration_file")

        # Overlay de marca (opcional). Procura em
        # profiles/<tenant>/assets/brand_overlay.png.
        use_brand_overlay = bool(payload.get("use_brand_overlay"))
        tenant_id = payload.get("tenant_id") or job.tenant_id
        brand_overlay: Path | None = None
        if use_brand_overlay and tenant_id:
            candidate = Path(f"profiles/{tenant_id}/assets/brand_overlay.png").resolve()
            if candidate.exists():
                brand_overlay = candidate

        with tempfile.TemporaryDirectory(prefix=f"ffrender-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)

            # 1) Baixa imagens + áudio
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

            # 2) Renderiza cada cena como mp4 parcial (motion + text overlay)
            scene_clips: list[Path] = []
            for i, (sc, img_path) in enumerate(zip(scenes, image_paths)):
                dur = max(1, int(sc.get("duration", 3)))
                out = tmp_path / f"clip_{i:02d}.mp4"
                vf = _build_vf(sc, width, height, dur, tmp_path, i)
                await _run_ffmpeg([
                    "-y", "-loop", "1", "-framerate", "30",
                    "-t", str(dur), "-i", str(img_path),
                    "-vf", vf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    # ultrafast + CRF 30: render rápido, arquivo pequeno
                    # (qualidade aceitável pra slideshow educativo).
                    "-preset", "ultrafast", "-r", "30",
                    "-crf", "30",
                    # Desativa B-frames (ultrafast já faz, mas explícito)
                    "-tune", "stillimage",
                    str(out),
                ])
                scene_clips.append(out)

            # 3) Concat
            listfile = tmp_path / "concat.txt"
            listfile.write_text("\n".join(f"file '{p}'" for p in scene_clips))
            concat_mp4 = tmp_path / "concat.mp4"
            await _run_ffmpeg([
                "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c", "copy",
                str(concat_mp4),
            ])

            # 4) Mux áudio com padding de silêncio se curto
            final = tmp_path / "final.mp4"
            total_video_dur = sum(max(1, int(sc.get("duration", 3))) for sc in scenes)

            if audio_local and audio_local.exists() and audio_local.stat().st_size > 0:
                # apad garante áudio >= duração do vídeo; -t corta pela dur do vídeo.
                await _run_ffmpeg([
                    "-y", "-i", str(concat_mp4), "-i", str(audio_local),
                    "-filter_complex", "[1:a]apad[apadded]",
                    "-map", "0:v", "-map", "[apadded]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-t", str(total_video_dur),
                    str(final),
                ])
            else:
                # sem áudio — adiciona trilha silenciosa (alguns players
                # se comportam melhor com stream a vazio)
                await _run_ffmpeg([
                    "-y", "-i", str(concat_mp4),
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
                    "-shortest",
                    str(final),
                ])

            # 4b) Overlay de marca (PNG no canto inferior direito), opcional.
            # Requer re-encode — só aplica se o overlay existe.
            if brand_overlay is not None:
                overlaid = tmp_path / "overlay.mp4"
                try:
                    await _run_ffmpeg([
                        "-y", "-i", str(final), "-i", str(brand_overlay),
                        "-filter_complex",
                        "[1:v]scale=iw*0.15:-1[wm];"
                        "[0:v][wm]overlay=W-w-30:H-h-30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "copy",
                        str(overlaid),
                    ])
                    if overlaid.exists() and overlaid.stat().st_size > 0:
                        final = overlaid
                except Exception:  # noqa: BLE001
                    pass  # falha silenciosa — devolve vídeo sem overlay

            # 5) Salva via storage
            storage = get_storage()
            url = storage.save_bytes(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                filename="video.mp4",
                data=final.read_bytes(),
            )

        return {
            "video_url": url,
            "duration_s": float(total_video_dur),
            "scene_count": len(scenes),
        }


# ── video filters ─────────────────────────────────────────────────────
def _build_vf(
    scene: dict[str, Any],
    width: int,
    height: int,
    duration: int,
    tmp: Path,
    idx: int,
) -> str:
    """Monta -vf pra uma cena: crop p/ aspect + motion + drawtext."""
    fps = 30
    total_frames = duration * fps

    # 1) scale/crop pro aspect correto. Upscale 1.3x (suficiente pra
    # zoom até ~1.1); valores maiores matam performance sem ganho visual.
    scale_w = int(width * 1.3)
    scale_h = int(height * 1.3)
    base = (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={scale_w}:{scale_h}"
    )

    # 2) motion — push-in (zoom lento) como default, senão estático
    motion_type = (scene.get("motion") or {}).get("type", "")
    if motion_type in ("push-in", "ken-burns-in"):
        # zoom de 1.0 → ~1.1 ao longo da cena
        zoom = (
            f"zoompan=z='min(zoom+0.0015,1.1)':"
            f"d={total_frames}:s={width}x{height}:fps={fps}"
        )
        vf = f"{base},{zoom}"
    elif motion_type == "ken-burns-out":
        zoom = (
            f"zoompan=z='if(eq(on,1),1.1,max(zoom-0.0015,1.0))':"
            f"d={total_frames}:s={width}x{height}:fps={fps}"
        )
        vf = f"{base},{zoom}"
    elif motion_type in ("drift",):
        # pan horizontal lento
        zoom = (
            f"zoompan=z=1.05:x='on*0.5':y=0:"
            f"d={total_frames}:s={width}x{height}:fps={fps}"
        )
        vf = f"{base},{zoom}"
    else:
        # estático — só reduz pra dimensão final
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"

    # 3) text overlay com word-wrap + caixa estilo carrossel
    overlay = (scene.get("text_overlay") or "").strip()
    if overlay:
        font_size = int(scene.get("font_size", 88))

        # Padding horizontal: 8% da largura de cada lado. Texto útil = 84% do
        # frame. Estimativa de largura média por char em DejaVu Sans Bold:
        # ~0.55 × font_size. Cálculo defensivo com 0.6 pra não ter sobra.
        pad_side = int(width * 0.08)
        usable_w = width - 2 * pad_side
        avg_char_w = font_size * 0.6
        max_chars_per_line = max(8, int(usable_w / avg_char_w))

        import textwrap as _tw
        wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
        # Se mesmo com wrap passou de 3 linhas, reduz fonte proporcionalmente
        n_lines = wrapped.count("\n") + 1
        if n_lines > 3:
            font_size = max(44, int(font_size * 3 / n_lines))
            avg_char_w = font_size * 0.6
            max_chars_per_line = max(8, int(usable_w / avg_char_w))
            wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
            n_lines = wrapped.count("\n") + 1

        txt_path = tmp / f"text_{idx:02d}.txt"
        txt_path.write_text(wrapped, encoding="utf-8")

        # Posição vertical: top default, mas com espaço da borda de 10%
        position = scene.get("text_position", "top")
        # Altura aproximada do bloco: font_size × 1.2 (line-height) × n_lines
        block_h = int(font_size * 1.25 * n_lines)
        margin_y = int(height * 0.08)
        if position == "top":
            y_box = margin_y
        elif position == "center":
            y_box = (height - block_h) // 2
        else:  # bottom
            y_box = height - block_h - margin_y

        # Box: largura full − pad_side × 2, altura do bloco + padding vertical
        box_pad_y = int(font_size * 0.6)
        box_pad_x = int(font_size * 0.5)
        box_x = pad_side
        box_w = width - 2 * pad_side
        box_y = y_box - box_pad_y
        box_full_h = block_h + box_pad_y * 2

        # Caixa semitransparente escura atrás do texto (estilo carrossel IG)
        # + drawtext centralizado com line_spacing pra respiro
        opacity = scene.get("overlay_opacity", 0.55)
        line_spacing = int(font_size * 0.2)
        draw = (
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_full_h}:"
            f"color=black@{opacity}:t=fill,"
            f"drawtext=fontfile={FONT_BOLD}:"
            f"textfile={txt_path}:"
            f"fontcolor=white:"
            f"fontsize={font_size}:"
            f"line_spacing={line_spacing}:"
            f"x=(w-text_w)/2:"
            f"y={y_box}:"
            f"shadowcolor=black@0.9:shadowx=0:shadowy=3"
        )
        vf = f"{vf},{draw}"

    return vf


# ── helpers ───────────────────────────────────────────────────────────
async def _fetch_to(url: str, dest: Path) -> None:
    if url.startswith("file://"):
        src = Path(url[len("file://"):])
        dest.write_bytes(src.read_bytes())
        return
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
        src = Path(root) / url[len("/artifacts/"):]
        dest.write_bytes(Path(src).read_bytes())
        return
    if url.startswith("/s3/"):
        # /s3/<bucket>/<key> — baixa direto do MinIO via boto3.
        rest = url[len("/s3/"):]
        bucket, _, key = rest.partition("/")
        import boto3
        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "").rstrip("/"),
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
            region_name=os.environ.get("S3_REGION", "us-east-1"),
        )
        obj = client.get_object(Bucket=bucket, Key=key)
        dest.write_bytes(obj["Body"].read())
        return
    if url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return
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
