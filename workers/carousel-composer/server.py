"""carousel-composer worker.

Capability: `design.carousel`. Porta 8107.

Gera carousel COM texto renderizado sobre as imagens (estilo IG/Stories).
Baixa cada imagem, usa ffmpeg drawbox+drawtext com word-wrap pra compor
o slide final, salva via storage e devolve lista de URLs dos slides
renderizados + JSON descritivo.

Input:
  {
    "images": ["/s3/.../1.png", ...],   // imagens base (geradas pelo inemaimg)
    "title": "Título do carrossel",     // aparece no slide 1
    "captions": ["caption 1", ...],     // opcional: um por slide
    "cta": "Comece agora",              // opcional: aparece no último slide
  }

Output:
  {
    "carousel": {
      "title": "...", "slide_count": N,
      "slides": [
        {"index": 0, "image": "/s3/.../composed_01.png",
         "caption": "...", "is_cover": true},
        ...
      ],
      "images_composed": ["/s3/.../composed_01.png", ...]
    }
  }
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt4.workers.carousel")

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class CarouselComposerWorker(BaseWorker):
    name = "carousel-composer"
    capabilities = ("design.carousel",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        images = payload.get("images") or []
        if images and isinstance(images[0], list):
            images = [x for sub in images for x in (sub or [])]
        images = [x for x in images if x]
        if not images:
            raise ValueError("payload precisa de 'images' não vazio")

        title = payload.get("title") or f"Carousel {job.job_id[:8]}"
        captions = payload.get("captions") or []
        cta = payload.get("cta") or ""

        # Se ffmpeg não está disponível, devolve JSON descritivo só (sem render).
        if not shutil.which("ffmpeg"):
            slides = [
                {"index": i, "image": url, "is_cover": i == 0,
                 "caption": captions[i] if i < len(captions) else ""}
                for i, url in enumerate(images)
            ]
            return {
                "carousel": {
                    "title": title, "caption": "",
                    "slide_count": len(slides), "slides": slides,
                    "images": list(images),
                    "images_composed": list(images),
                    "mode": "passthrough (ffmpeg ausente)",
                }
            }

        # Renderiza texto sobre cada imagem
        storage = get_storage()
        composed_urls: list[str] = []
        slides: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(prefix=f"carousel-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)

            for i, url in enumerate(images):
                local = tmp_path / f"src_{i:02d}.png"
                try:
                    await _fetch(url, local)
                except Exception as exc:  # noqa: BLE001
                    log.warning("slide %d: fetch %s: %s", i, url, exc)
                    composed_urls.append(url)  # fallback: original
                    slides.append({"index": i, "image": url, "is_cover": i == 0})
                    continue

                # Texto do slide: título no slide 0, cta no último, caption no meio
                text = ""
                if i == 0:
                    text = title
                elif i == len(images) - 1 and cta:
                    text = cta
                elif i < len(captions):
                    text = captions[i] or ""
                elif captions and captions[0]:
                    # se só tem 1 caption genérica, usa nos do meio
                    text = captions[0]

                out = tmp_path / f"composed_{i:02d}.png"
                try:
                    await _compose_slide(local, out, text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("slide %d: compose falhou: %s", i, exc)
                    out = local  # fallback

                url2 = storage.save_bytes(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    filename=f"slide_{i:02d}.png",
                    data=out.read_bytes(),
                )
                composed_urls.append(url2)
                slides.append({
                    "index": i,
                    "image": url2,
                    "caption": text,
                    "is_cover": i == 0,
                    "source_image": url,
                })

        return {
            "carousel": {
                "title": title,
                "caption": "",
                "slide_count": len(slides),
                "slides": slides,
                "images": list(images),           # originais (sem texto)
                "images_composed": composed_urls,  # com texto (uso na UI/delivery)
            }
        }


# ── helpers ─────────────────────────────────────────────────────────────

async def _fetch(url: str, dest: Path) -> None:
    if url.startswith("file://"):
        dest.write_bytes(Path(url[len("file://"):]).read_bytes())
        return
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
        dest.write_bytes((Path(root) / url[len("/artifacts/"):]).read_bytes())
        return
    if url.startswith("/s3/"):
        rest = url[len("/s3/"):]
        bucket, _, key = rest.partition("/")
        import boto3
        c = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "").rstrip("/"),
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
            region_name=os.environ.get("S3_REGION", "us-east-1"),
        )
        dest.write_bytes(c.get_object(Bucket=bucket, Key=key)["Body"].read())
        return
    if url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return
    dest.write_bytes(Path(url).read_bytes())


async def _compose_slide(src: Path, dst: Path, text: str) -> None:
    """Aplica drawbox + drawtext sobre a imagem. Sem texto → só copia."""
    if not text.strip():
        dst.write_bytes(src.read_bytes())
        return

    # Descobre dimensões via ffprobe pra calcular posição/tamanho corretos
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", str(src),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        w, h = [int(x) for x in out.decode().strip().split(",")]
    except Exception:  # noqa: BLE001
        w, h = 1080, 1080

    # Font size: 7% da altura. Word-wrap em linhas com max_chars calculado.
    font_size = max(32, int(h * 0.07))
    pad_side = int(w * 0.06)
    usable_w = w - 2 * pad_side
    max_chars = max(10, int(usable_w / (font_size * 0.6)))
    wrapped = textwrap.fill(text.upper(), width=max_chars)
    n_lines = wrapped.count("\n") + 1
    if n_lines > 4:
        font_size = max(28, int(font_size * 4 / n_lines))
        max_chars = max(10, int(usable_w / (font_size * 0.6)))
        wrapped = textwrap.fill(text.upper(), width=max_chars)
        n_lines = wrapped.count("\n") + 1

    block_h = int(font_size * 1.3 * n_lines)
    box_pad_y = int(font_size * 0.6)
    box_h = block_h + box_pad_y * 2
    # Caixa na parte de baixo (estilo carrossel IG). Margem inferior 8%.
    box_y = h - box_h - int(h * 0.08)
    text_y = box_y + box_pad_y

    # Escreve texto num file pra escapar especiais fácil
    txt_path = dst.parent / (dst.stem + ".txt")
    txt_path.write_text(wrapped, encoding="utf-8")

    vf = (
        f"drawbox=x=0:y={box_y}:w={w}:h={box_h}:color=black@0.55:t=fill,"
        f"drawtext=fontfile={FONT_BOLD}:"
        f"textfile={txt_path}:"
        f"fontcolor=white:"
        f"fontsize={font_size}:"
        f"line_spacing={int(font_size * 0.2)}:"
        f"x=(w-text_w)/2:y={text_y}:"
        f"shadowcolor=black@0.9:shadowx=0:shadowy=3"
    )
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(src),
        "-vf", vf, "-frames:v", "1", str(dst),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="ignore")[-300:])


if __name__ == "__main__":
    port = int(os.environ.get("CAROUSEL_COMPOSER_PORT", 8107))
    CarouselComposerWorker().run(port=port)
