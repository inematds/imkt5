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

        slides = payload.get("slides") or []
        # Fallback: se não vieram slides estruturados, constrói do básico
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
        palette = _derive_palette({**DEFAULT_PALETTE, **(payload.get("palette") or {})})
        template_name = payload.get("template") or "editorial"
        width = int(payload.get("width") or 1080)
        height = int(payload.get("height") or 1080)

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

            # Playwright: 1 browser, N páginas (reuso acelera 5x)
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                ctx = await browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                for i in range(total):
                    slide = slides[i] if i < len(slides) else {}
                    bg_path = local_images[i] if i < len(local_images) else None
                    bg_url = f"file://{bg_path}" if bg_path else ""

                    # Ajusta headline_size baseado no comprimento
                    headline = (slide.get("headline") or "").strip()
                    h_len = len(headline)
                    headline_size = 60 if h_len < 50 else (52 if h_len < 90 else 42)

                    html = tmpl.render(
                        width=width, height=height,
                        palette=palette,
                        bg_image=bg_url,
                        headline=headline,
                        headline_size=headline_size,
                        context=slide.get("context", ""),
                        stat_a=slide.get("stat_a"),
                        stat_b=slide.get("stat_b"),
                        question=slide.get("question", ""),
                        handle=handle,
                        badge=slide.get("badge", "INEMA"),
                        slide_label=slide.get("slide_label", f"{i+1:02d} / {total:02d}"),
                    )

                    html_file = tmp_path / f"slide_{i:02d}.html"
                    html_file.write_text(html, encoding="utf-8")

                    page = await ctx.new_page()
                    await page.goto(f"file://{html_file}", wait_until="networkidle")
                    png_path = tmp_path / f"slide_{i:02d}.png"
                    await page.screenshot(
                        path=str(png_path),
                        clip={"x": 0, "y": 0, "width": width, "height": height},
                        omit_background=False,
                    )
                    await page.close()

                    storage = get_storage()
                    url = storage.save_bytes(
                        tenant_id=job.tenant_id,
                        job_id=job.job_id,
                        filename=f"slide_{i:02d}.png",
                        data=png_path.read_bytes(),
                    )
                    composed_urls.append(url)
                    out_slides.append({
                        "index": i, "image": url,
                        "caption": headline, "is_cover": i == 0,
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
        """Monta slides a partir de title/captions/cta (modo simples)."""
        title = payload.get("title", "")
        captions = payload.get("captions") or []
        cta = payload.get("cta", "")
        images = payload.get("images") or []
        total = max(len(images), 1)
        slides: list[dict[str, Any]] = []
        for i in range(total):
            if i == 0:
                slides.append({"headline": title, "badge": "INEMA"})
            elif i == total - 1 and cta:
                slides.append({"headline": cta, "question": cta})
            else:
                cap = captions[i] if i < len(captions) else (captions[0] if captions else "")
                slides.append({"headline": cap, "context": ""})
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
