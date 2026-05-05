"""carousel-composer worker.

Capability: `design.carousel`. Porta 8107.

Compõe slides de carrossel estilo IG/Stories usando Pillow:
  - Imagem base (filter brightness/saturation pra destacar o texto)
  - Gradient overlay (top→bottom)
  - Accent line colorida no topo (palette.primary → palette.secondary)
  - Título/caption/CTA com tipografia bold + word-wrap
  - Slide index no canto (1/5, 2/5, ...)

Input:
  {
    "images": ["/s3/..."],              // base, geradas pelo inemaimg
    "title": "Título do carrossel",
    "captions": ["cap 1", ...],         // opcional, 1 por slide
    "cta": "Comece agora",              // opcional, último slide
    "palette": {                        // opcional (de photography_plan)
      "primary": "#0099FF", "secondary": "#00FF88",
      "accent": "#FFD700", "background": "#0D0D0D",
      "text": "#FFFFFF"
    }
  }

Output: carousel com slides compostos (PNG em /s3/).
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter

from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt5.workers.carousel")

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

DEFAULT_PALETTE = {
    "primary": "#0099FF",
    "secondary": "#00FF88",
    "accent": "#FFD700",
    "background": "#0D0D0D",
    "text": "#FFFFFF",
}


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
        palette = {**DEFAULT_PALETTE, **(payload.get("palette") or {})}

        storage = get_storage()
        slides: list[dict[str, Any]] = []
        composed_urls: list[str] = []

        with tempfile.TemporaryDirectory(prefix=f"carousel-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)
            total = len(images)

            for i, url in enumerate(images):
                local = tmp_path / f"src_{i:02d}.png"
                try:
                    await _fetch(url, local)
                except Exception as exc:  # noqa: BLE001
                    log.warning("slide %d: fetch %s: %s", i, url, exc)
                    composed_urls.append(url)
                    slides.append({"index": i, "image": url, "is_cover": i == 0})
                    continue

                # Texto do slide
                if i == 0:
                    primary_text = title
                    subtitle = ""
                elif i == total - 1 and cta:
                    primary_text = cta
                    subtitle = ""
                elif i < len(captions):
                    primary_text = captions[i] or ""
                    subtitle = ""
                else:
                    primary_text = ""
                    subtitle = ""

                out = tmp_path / f"composed_{i:02d}.png"
                try:
                    await asyncio.to_thread(
                        _compose_pil, local, out, primary_text, palette,
                        slide_idx=i + 1, total=total, is_cover=(i == 0),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("slide %d: compose falhou: %s", i, exc)
                    out = local

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
                    "caption": primary_text,
                    "is_cover": i == 0,
                    "source_image": url,
                })

        return {
            "carousel": {
                "title": title,
                "slide_count": len(slides),
                "slides": slides,
                "images": list(images),
                "images_composed": composed_urls,
                "palette": palette,
            }
        }


# ── PIL composition ─────────────────────────────────────────────────────

def _compose_pil(
    src: Path, dst: Path, text: str,
    palette: dict[str, str], *,
    slide_idx: int, total: int, is_cover: bool,
) -> None:
    """Compõe 1 slide: filter na bg + gradient + accent line + texto."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    # Normaliza pra quadrado 1080 se muito grande
    target_size = 1080
    if max(w, h) > 1400:
        ratio = target_size / min(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        w, h = img.size
    # Crop central pra quadrado
    if w != h:
        side = min(w, h)
        x0 = (w - side) // 2; y0 = (h - side) // 2
        img = img.crop((x0, y0, x0 + side, y0 + side))
        w = h = side

    # 1) Filter: brightness + saturation pra ficar dramático (como no timesmkt3)
    img = ImageEnhance.Brightness(img).enhance(0.5)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.2)

    base = img.convert("RGBA")

    # 2) Gradient overlay: mais escuro no topo+fundo, tom de primary na lateral
    grad = _make_gradient(w, h, palette)
    base = Image.alpha_composite(base, grad)

    # 3) Accent line no topo (primary → secondary)
    accent = _make_accent_line(w, 8, palette)
    base.alpha_composite(accent, (0, 0))

    draw = ImageDraw.Draw(base)

    # 4) Slide counter (canto sup. direito)
    counter_font = _font(FONT_BOLD, max(22, int(h * 0.022)))
    counter_text = f"{slide_idx}/{total}"
    counter_bbox = draw.textbbox((0, 0), counter_text, font=counter_font)
    cx = w - (counter_bbox[2] - counter_bbox[0]) - int(w * 0.04)
    cy = int(h * 0.035)
    draw.text((cx, cy), counter_text, font=counter_font, fill=palette["text"])

    # 5) Texto principal
    if text.strip():
        _draw_text_block(draw, base, text, w, h, palette, is_cover=is_cover)

    # 6) Save
    base.convert("RGB").save(str(dst), "PNG", optimize=True)


def _make_gradient(w: int, h: int, palette: dict[str, str]) -> Image.Image:
    """Gradient diagonal primary + vertical dark top/bottom."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    primary_rgba = _hex_to_rgba(palette["primary"], 64)
    # Gradient vertical (top+bottom escuros)
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tdr = ImageDraw.Draw(top)
    for y in range(h):
        if y < h * 0.3:
            alpha = int(140 * (1 - y / (h * 0.3)))
        elif y > h * 0.55:
            alpha = int(200 * ((y - h * 0.55) / (h * 0.45)))
        else:
            alpha = 40
        tdr.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, top)
    # Gradient diagonal (tint primary)
    diag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ddr = ImageDraw.Draw(diag)
    for y in range(h):
        alpha = int(primary_rgba[3] * (1 - y / h))
        ddr.line([(0, y), (int(w * 0.35), y)],
                 fill=(*primary_rgba[:3], alpha))
    img = Image.alpha_composite(img, diag)
    return img


def _make_accent_line(w: int, h: int, palette: dict[str, str]) -> Image.Image:
    """Linha primary→secondary no topo."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    start = _hex_to_rgb(palette["primary"])
    end = _hex_to_rgb(palette["secondary"])
    for x in range(w):
        t = x / max(w - 1, 1)
        r = int(start[0] * (1 - t) + end[0] * t)
        g = int(start[1] * (1 - t) + end[1] * t)
        b = int(start[2] * (1 - t) + end[2] * t)
        d.line([(x, 0), (x, h)], fill=(r, g, b, 255))
    return img


def _draw_text_block(
    draw, img: Image.Image, text: str,
    w: int, h: int, palette: dict[str, str], *, is_cover: bool,
) -> None:
    """Renderiza texto com word-wrap + shadow no terço inferior."""
    # Cover = fonte bigger; subsequentes = menor
    base_size = int(h * 0.095) if is_cover else int(h * 0.068)
    pad_side = int(w * 0.07)
    usable_w = w - 2 * pad_side

    font = _font(FONT_BOLD, base_size)
    # Wrap por largura real (usa getbbox)
    wrapped = _wrap_to_pixels(text.upper(), font, usable_w)
    # Se mais de 4 linhas, reduz
    while wrapped.count("\n") + 1 > 4 and base_size > 32:
        base_size = int(base_size * 0.88)
        font = _font(FONT_BOLD, base_size)
        wrapped = _wrap_to_pixels(text.upper(), font, usable_w)

    lines = wrapped.split("\n")
    line_h = int(base_size * 1.22)
    block_h = line_h * len(lines)
    y_start = h - block_h - int(h * 0.12)

    # Shadow sob o bloco de texto
    shadow_pad = int(base_size * 0.5)
    shadow_box = Image.new(
        "RGBA",
        (w, block_h + shadow_pad * 2),
        (0, 0, 0, int(255 * 0.5)),
    )
    # Aplica blur no shadow
    shadow_box = shadow_box.filter(ImageFilter.GaussianBlur(radius=8))
    img.alpha_composite(shadow_box, (0, y_start - shadow_pad))

    # Escreve texto centralizado
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = y_start + i * line_h
        # Duplo shadow (drop + hard)
        draw.text((x + 2, y + 4), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=palette["text"])


def _wrap_to_pixels(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """Wrap baseado em largura pixel real."""
    words = text.split()
    if not words:
        return ""
    lines = []
    cur = words[0]
    for word in words[1:]:
        candidate = cur + " " + word
        bbox = font.getbbox(candidate)
        if (bbox[2] - bbox[0]) <= max_w:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return "\n".join(lines)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore


def _hex_to_rgba(h: str, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(h)
    return (r, g, b, alpha)


# ── fetch helpers ───────────────────────────────────────────────────────
async def _fetch(url: str, dest: Path) -> None:
    if url.startswith("file://"):
        dest.write_bytes(Path(url[len("file://"):]).read_bytes()); return
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT5_ARTIFACT_ROOT", "./data/artifacts")
        dest.write_bytes((Path(root) / url[len("/artifacts/"):]).read_bytes()); return
    if url.startswith("/s3/"):
        rest = url[len("/s3/"):]; bucket, _, key = rest.partition("/")
        import boto3
        c = boto3.client("s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "").rstrip("/"),
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
            region_name=os.environ.get("S3_REGION", "us-east-1"))
        dest.write_bytes(c.get_object(Bucket=bucket, Key=key)["Body"].read()); return
    if url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url); r.raise_for_status()
            dest.write_bytes(r.content); return
    dest.write_bytes(Path(url).read_bytes())


if __name__ == "__main__":
    port = int(os.environ.get("CAROUSEL_COMPOSER_PORT", 8107))
    CarouselComposerWorker().run(port=port)
