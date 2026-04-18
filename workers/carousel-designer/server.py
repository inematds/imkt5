"""carousel-designer worker.

Capability: `design.carousel_rich`. Porta 8111.

Renderiza slides de carrossel com template HTML/CSS editorial (estilo
timesmkt3) via Playwright/Chromium headless. Fidelidade visual alta.

Input:
  {
    "images": ["/s3/..."],
    "slides": [
      {
        "headline": "A dissonância que ninguém quer enxergar",
        "context": "Texto corrido longo...",
        "stat_a": {"number": "70%", "label": "Temem o impacto"},
        "stat_b": {"number": "39%", "label": "Acham que seu cargo"},
        "question": "Você consegue ver? 🧠",
        "badge": "INEMA",
        "slide_label": "Dados · 2026",
      },
      ...
    ],
    "handle": "@inema.tds",
    "palette": {"primary": "#0099FF", "secondary": "#00FF88", ...},
    "template": "editorial",
    "width": 1080,
    "height": 1080
  }

Se `slides` vazio, gera usando `images + title/captions/cta` (fallback
simples pra receita simple-carrossel). Pra controle fino, passe
`slides[]` explicitamente.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
import jinja2

from workers._base import BaseWorker
from workers._base.storage import get_storage

log = logging.getLogger("imkt4.workers.carousel-designer")

TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
)

DEFAULT_PALETTE = {
    "primary": "#0099FF",
    "secondary": "#00FF88",
    "accent": "#FFD700",
    "background": "#0D0D0D",
    "text": "#FFFFFF",
}

# Style presets — traduzidos do video-art-direction/12_styles do timesmkt3.
# Cada um entrega uma palette coerente. Escolha via input "style".
STYLE_PRESETS: dict[str, dict[str, str]] = {
    "neon_futurista":        {"primary": "#0099FF", "secondary": "#00FF88", "accent": "#FFD700", "background": "#0D0D0D", "text": "#FFFFFF"},
    "warm_lifestyle":        {"primary": "#FF8A4C", "secondary": "#FFD166", "accent": "#EF476F", "background": "#2B1810", "text": "#FFF8E7"},
    "corporate_clean":       {"primary": "#0052CC", "secondary": "#00B8D9", "accent": "#36B37E", "background": "#F4F5F7", "text": "#172B4D"},
    "bold_pop":              {"primary": "#FF006E", "secondary": "#FFBE0B", "accent": "#8338EC", "background": "#000000", "text": "#FFFFFF"},
    "minimal_zen":           {"primary": "#3D3D3D", "secondary": "#7A7A7A", "accent": "#B8860B", "background": "#FAFAF5", "text": "#1A1A1A"},
    "dark_cinematic":        {"primary": "#E8B04B", "secondary": "#C04848", "accent": "#F2EFE9", "background": "#0A0A0A", "text": "#F2EFE9"},
    "pastel_soft":           {"primary": "#FFB3C1", "secondary": "#C8B6FF", "accent": "#B5EAD7", "background": "#FFF5F7", "text": "#3F3D56"},
    "retro_vintage":         {"primary": "#D96C35", "secondary": "#E9C46A", "accent": "#2A9D8F", "background": "#F4EDE4", "text": "#2B2118"},
    "nature_organic":        {"primary": "#588157", "secondary": "#A3B18A", "accent": "#DDA15E", "background": "#283618", "text": "#FEFAE0"},
    "urban_street":          {"primary": "#FF4D4D", "secondary": "#00FFF0", "accent": "#FFE933", "background": "#1A1A1A", "text": "#FFFFFF"},
    "luxury_gold":           {"primary": "#D4AF37", "secondary": "#F2E394", "accent": "#C78B47", "background": "#0E0E0E", "text": "#F5F0E1"},
    "editorial_documentary": {"primary": "#3C3B3B", "secondary": "#A8A8A8", "accent": "#C0392B", "background": "#F0EEE9", "text": "#1C1C1C"},
}

# Formatos canônicos — se user não passa `formats`, gera os 3.
DEFAULT_FORMATS = ["1:1", "9:16", "16:9"]


def _dims_from_ratio(r: str) -> tuple[int, int]:
    """Aceita '9:16', '1:1', '16:9' — retorna (width, height) em pixels
    escalado pra 1080 no menor lado."""
    r = r.replace("x", ":").strip()
    if ":" not in r:
        return (1080, 1080)
    a, b = r.split(":", 1)
    try:
        na, nb = int(a), int(b)
    except ValueError:
        return (1080, 1080)
    # Normaliza pra 1080 no menor lado
    if na <= nb:   # portrait ou square
        return (1080, int(1080 * nb / na))
    else:          # landscape
        return (int(1080 * na / nb), 1080)


def _aspect_name(w: int, h: int) -> str:
    ratio = w / h
    if abs(ratio - 1) < 0.05:
        return "square"
    return "portrait" if ratio < 1 else "landscape"


def _magazine_headline_size(text: str, w: int, h: int, aspect: str) -> int:
    """Tamanho de fonte magazine: grande, escala pelo comprimento do texto
    e pelo aspect. Serif (Playfair Display) precisa de mais espaço vertical."""
    chars = max(1, len(text.strip()))
    # Base: 12% da altura (slide quadrado 1080 → 130px)
    if aspect == "portrait":
        base = int(h * 0.11)
    elif aspect == "landscape":
        base = int(h * 0.15)
    else:
        base = int(h * 0.12)
    # Reduz pra textos longos
    if chars > 80:
        base = int(base * 0.75)
    elif chars > 40:
        base = int(base * 0.88)
    return max(48, min(base, 180))


def _ratio_tag(w: int, h: int) -> str:
    """Convert (1080, 1920) → '9x16'. Usado no filename."""
    from math import gcd
    g = gcd(w, h)
    return f"{w // g}x{h // g}"


def _derive_palette(p: dict[str, str]) -> dict[str, str]:
    """Gera variações (soft, border, glow, shadow, primary_text) a partir
    de primary/secondary pro CSS. Aceita hex #RRGGBB."""
    def rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore
    pr, pg, pb = rgb(p.get("primary", "#0099FF"))
    sr, sg, sb = rgb(p.get("secondary", "#00FF88"))
    return {
        **p,
        "primary_soft":   f"rgba({pr},{pg},{pb},0.15)",
        "primary_border": f"rgba({pr},{pg},{pb},0.4)",
        "primary_glow":   f"rgba({pr},{pg},{pb},0.5)",
        "primary_shadow": f"rgba({pr // 3},{pg // 3},{pb},0.88)",
        "primary_text":   f"rgba({min(255, pr+80)},{min(255, pg+80)},{min(255, pb+40)},0.85)",
        "secondary_glow": f"rgba({sr},{sg},{sb},0.4)",
    }


class CarouselDesignerWorker(BaseWorker):
    name = "carousel-designer"
    capabilities = ("design.carousel_rich",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        images = payload.get("images") or []
        if images and isinstance(images[0], list):
            images = [x for sub in images for x in (sub or [])]
        images = [x for x in images if x]

        # Aceita slides de múltiplas fontes (coalesce):
        # 1. input.slides (controle total)
        # 2. stages.outline.output.slides (gerado pelo carousel-outline)
        # 3. fallback: constrói a partir de title/captions/cta
        slides = (
            payload.get("slides")
            or payload.get("slides_from_input")
            or payload.get("slides_from_outline")
            or []
        )
        if not slides:
            slides = self._slides_from_basic(payload)

        if not images and not slides:
            raise ValueError("precisa de 'images' ou 'slides'")
        if not slides:
            # 1 slide por imagem (só headline + handle)
            slides = [
                {"headline": payload.get("title") or "", "slide_label": f"{i+1:02d}"}
                for i in range(len(images))
            ]

        handle = payload.get("handle") or "@inema.tds"

        # Style preset (ex.: "neon_futurista") OU palette custom.
        # Palette custom sobrescreve o preset parcialmente (merge).
        style = (payload.get("style") or "neon_futurista").lower()
        base_palette = STYLE_PRESETS.get(style, DEFAULT_PALETTE)
        palette = _derive_palette({**base_palette, **(payload.get("palette") or {})})
        template_name = payload.get("template") or "editorial"

        # Formatos: se não vier `formats` nem `width/height`, gera os 3
        # canônicos (1:1, 9:16, 16:9). Se `width/height` explícito, usa só ele.
        formats = payload.get("formats")
        if formats is None and not payload.get("width"):
            formats = DEFAULT_FORMATS
        if formats:
            dims_list = [_dims_from_ratio(f) for f in formats]
        else:
            width = int(payload.get("width") or 1080)
            height = int(payload.get("height") or 1080)
            dims_list = [(width, height)]

        total = max(len(slides), len(images))
        composed_urls: list[str] = []
        out_slides: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(prefix=f"cdesign-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)

            # Baixa todas as imagens localmente (template referencia file://)
            local_images: list[Path | None] = []
            for i in range(total):
                if i < len(images):
                    local = tmp_path / f"bg_{i:02d}.png"
                    try:
                        await _fetch(images[i], local)
                        local_images.append(local)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("bg %d falhou: %s", i, exc)
                        local_images.append(None)
                else:
                    local_images.append(None)

            tmpl = _jinja.get_template(f"{template_name}.html")

            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                # Render todos os slides × todos os formatos
                for i in range(total):
                    slide = slides[i] if i < len(slides) else {}
                    bg_path = local_images[i] if i < len(local_images) else None
                    bg_url = f"file://{bg_path}" if bg_path else ""

                    headline = (slide.get("headline") or "").strip()
                    h_len = len(headline)
                    headline_size = 60 if h_len < 50 else (52 if h_len < 90 else 42)

                    slide_formats: list[dict[str, Any]] = []
                    for (w, h) in dims_list:
                        aspect = _aspect_name(w, h)
                        ratio_tag = _ratio_tag(w, h)

                        # Magazine style: tipografia grande serif, 1 mensagem,
                        # sem stats/question. Escala o headline pelo aspect.
                        mag_hsize = _magazine_headline_size(headline, w, h, aspect) if template_name == "magazine" else headline_size
                        pad_v = int(h * (0.10 if aspect != "landscape" else 0.08))
                        pad_h = int(w * (0.12 if aspect != "landscape" else 0.10))

                        html = tmpl.render(
                            width=w, height=h,
                            aspect=aspect,
                            palette=palette,
                            bg_image=bg_url,
                            headline=headline,
                            headline_size=mag_hsize,
                            pad_v=pad_v, pad_h=pad_h,
                            slide_num=f"{i+1:02d}",
                            context=slide.get("context", ""),
                            stat_a=slide.get("stat_a"),
                            stat_b=slide.get("stat_b"),
                            question=slide.get("question", ""),
                            handle=handle,
                            badge=slide.get("badge", "INEMA"),
                            slide_label=slide.get(
                                "slide_label", f"{i+1:02d} / {total:02d}",
                            ),
                        )
                        html_file = tmp_path / f"slide_{i:02d}_{ratio_tag}.html"
                        html_file.write_text(html, encoding="utf-8")

                        ctx = await browser.new_context(
                            viewport={"width": w, "height": h},
                            device_scale_factor=1,
                        )
                        page = await ctx.new_page()
                        await page.goto(f"file://{html_file}", wait_until="networkidle")
                        png_path = tmp_path / f"slide_{i:02d}_{ratio_tag}.png"
                        await page.screenshot(
                            path=str(png_path),
                            clip={"x": 0, "y": 0, "width": w, "height": h},
                        )
                        await ctx.close()

                        storage = get_storage()
                        url = storage.save_bytes(
                            tenant_id=job.tenant_id,
                            job_id=job.job_id,
                            filename=f"slide_{i:02d}_{ratio_tag}.png",
                            data=png_path.read_bytes(),
                        )
                        slide_formats.append({
                            "ratio": ratio_tag.replace("x", ":"),
                            "width": w, "height": h, "image": url,
                        })
                        # Default: usa o primeiro formato como image principal
                        if len(slide_formats) == 1:
                            composed_urls.append(url)

                    out_slides.append({
                        "index": i,
                        "image": slide_formats[0]["image"],
                        "caption": headline,
                        "is_cover": i == 0,
                        "formats": slide_formats,
                    })
                await browser.close()

        return {
            "carousel": {
                "title": (slides[0].get("headline") if slides else "") or "Carousel",
                "slide_count": total,
                "slides": out_slides,
                "images_composed": composed_urls,
                "palette": palette,
                "template": template_name,
            }
        }

    def _slides_from_basic(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Monta slides a partir de title/captions/cta (modo simples).

        Template magazine: cada slide tem UMA frase só no headline —
        nada de stats, question, context. Visual limpo estilo revista.
        """
        title = (payload.get("title") or "").strip()
        captions = [c for c in (payload.get("captions") or []) if c and c.strip()]
        cta = (payload.get("cta") or "").strip()
        images = payload.get("images") or []
        total = max(len(images), 1)

        # Constrói lista de frases: title + captions + cta (só as não-vazias)
        phrases: list[str] = []
        if title: phrases.append(title)
        phrases.extend(captions)
        if cta and cta != (phrases[-1] if phrases else ""):
            phrases.append(cta)
        if not phrases:
            phrases = [""]

        slides: list[dict[str, Any]] = []
        for i in range(total):
            text = phrases[i] if i < len(phrases) else phrases[-1]
            slides.append({
                "headline": text,
                "slide_label": "Capa" if i == 0 else ("Fim" if i == total - 1 else ""),
            })
        return slides


# ── fetch helpers ───────────────────────────────────────────────────────
async def _fetch(url: str, dest: Path) -> None:
    if url.startswith("file://"):
        dest.write_bytes(Path(url[len("file://"):]).read_bytes()); return
    if url.startswith("/artifacts/"):
        root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
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
    port = int(os.environ.get("CAROUSEL_DESIGNER_PORT", 8111))
    CarouselDesignerWorker().run(port=port)
