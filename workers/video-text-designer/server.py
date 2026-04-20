"""video-text-designer worker.

Capability: `video.text_overlay`. Porta 8116.

Pré-renderiza texto de cena como PNG RGBA via Playwright + Chromium,
usando mesmo estilo chrome gradient + halo do carousel-designer.
Consumido pelo ffmpeg-local como overlay (opt-in via
`chrome_text_overlay: true`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import jinja2

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from workers._base import BaseWorker  # noqa: E402
from workers._base.storage import get_storage  # noqa: E402

log = logging.getLogger("imkt4.workers.video-text-designer")

TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
)


def _font_size_for(text: str, width: int, height: int) -> int:
    """Font size adaptativo — carrossel-rico style (c79 law 8 "type as character").
    Maior que drawtext tradicional, menor pra textos longos."""
    chars = max(1, len(text.strip()))
    if chars < 15:
        base = 148   # hero short (ex: "INEMA", "87%")
    elif chars < 25:
        base = 128   # short hook
    elif chars < 45:
        base = 102
    elif chars < 70:
        base = 80
    else:
        base = 64
    scale = width / 1080.0
    return max(48, int(base * scale))


def _safe_zones(width: int, height: int) -> tuple[int, int, int]:
    """Retorna (safe_top, safe_bottom, pad_h) por aspect ratio.

    Safe zones pra evitar HUD de stories/reels. Portrait (9:16) precisa de
    mais espaço no topo (barra de login) e no bottom (CTA do app).
    """
    aspect = width / height
    if aspect < 0.8:  # portrait (9:16)
        return (140, 200, 72)
    elif abs(aspect - 1.0) < 0.1:  # square
        return (80, 100, 80)
    else:  # landscape
        return (60, 80, 100)


class VideoTextDesignerWorker(BaseWorker):
    name = "video-text-designer"
    capabilities = ("video.text_overlay",)

    async def handle(self, job) -> dict[str, Any]:
        from playwright.async_api import async_playwright

        payload = job.payload
        scenes = payload.get("scenes") or []
        if not isinstance(scenes, list):
            raise ValueError("'scenes' deve ser uma lista")
        if not scenes:
            return {"outputs": []}

        # text_overlay_style (preferred) > mode > default
        style = (
            payload.get("text_overlay_style")
            or payload.get("style")
            or payload.get("mode")
            or payload.get("chrome_text_mode")
            or "chrome_overlay"
        ).lower()

        # Mapeia style → template
        STYLE_TO_TEMPLATE = {
            "chrome_overlay":    "editorial_chrome_textonly",    # chrome top/center/bottom (opt-in dark fade)
            "chrome_fullslide":  "editorial_chrome_fullslide",   # chrome centrado + dark overlay 82%
            "magazine_bar":      "magazine_bar",                 # dark bar horizontal + Playfair
            "solid_block":       "solid_block",                  # bloco colorido sólido + Inter bold
            "stamp_diagonal":    "stamp_diagonal",               # stamp rotacionado estilo c79
            "kinetic_pop":       "kinetic_pop",                  # Bebas Neue + neon glow
            "minimal_caption":   "minimal_caption",              # small caption bottom-left
            # aliases legados
            "overlay":           "editorial_chrome_textonly",
            "full_slide":        "editorial_chrome_fullslide",
        }
        # Override direto se passou template explícito
        template_name = payload.get("template") or STYLE_TO_TEMPLATE.get(style, "editorial_chrome_textonly")
        tmpl = _jinja.get_template(f"{template_name}.html")
        use_dark_bar = bool(payload.get("use_dark_bar", False))
        use_dark_top_fade = payload.get("use_dark_top_fade")
        use_dark_top_fade = True if use_dark_top_fade is None else bool(use_dark_top_fade)
        use_accent_line = payload.get("use_accent_line")
        use_accent_line = True if use_accent_line is None else bool(use_accent_line)
        # Brand moment config (aparece no scene CTA final)
        brand_logo = payload.get("brand_logo") or "INEMA"
        brand_tag = payload.get("brand_tag") or ""
        brand_handle = payload.get("brand_handle") or "@inema.tds"
        # Defaults globais (vindos do scene_plan do recipe)
        default_w = int(payload.get("width", 1080))
        default_h = int(payload.get("height", 1920))

        storage = get_storage()
        outputs: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(prefix=f"vtext-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                for i, sc in enumerate(scenes):
                    text = (sc.get("text_overlay") or "").strip()
                    if not text:
                        outputs.append({"scene_index": i, "has_text": False})
                        continue

                    width = int(sc.get("width") or default_w)
                    height = int(sc.get("height") or default_h)
                    text_position = (sc.get("text_position") or "top").lower()
                    if text_position not in ("top", "center", "bottom"):
                        text_position = "top"
                    scene_type = (sc.get("scene_type") or sc.get("type") or "").lower()

                    safe_top, safe_bottom, pad_h = _safe_zones(width, height)
                    font_size = _font_size_for(text, width, height)
                    max_text_width = int(width - 2 * pad_h)

                    # Stat mode: quando cena tem stat_a.number E tipo proof/solution
                    stat_number = None
                    stat_a = sc.get("stat_a") or {}
                    if isinstance(stat_a, dict) and scene_type in ("proof", "solution"):
                        stat_number = stat_a.get("number")
                    # Brand moment: última cena com scene_type=cta vira INEMA logo gigante
                    is_last = (i == len(scenes) - 1)
                    is_brand_moment = (
                        scene_type == "cta" and is_last
                        and bool(payload.get("brand_moment_on_cta", True))
                    )
                    # fade height ~10% da altura, min 160px
                    fade_top_height = max(160, int(height * 0.12))

                    ctx = {
                        "width": width,
                        "height": height,
                        "text_overlay": text,
                        "text_position": text_position,
                        "scene_type": scene_type,
                        "font_size": font_size,
                        "max_text_width": max_text_width,
                        "safe_top": safe_top,
                        "safe_bottom": safe_bottom,
                        "pad_h": pad_h,
                        "bar_pad_y": int(font_size * 0.40),
                        "stat_number": stat_number,
                        "stat_a": stat_a if isinstance(stat_a, dict) else None,
                        "use_dark_bar": use_dark_bar,
                        "use_dark_top_fade": use_dark_top_fade,
                        "use_accent_line": use_accent_line,
                        "fade_top_height": fade_top_height,
                        "is_brand_moment": is_brand_moment,
                        "brand_logo": brand_logo,
                        "brand_tag": brand_tag,
                        "brand_handle": brand_handle,
                        # full_slide extras
                        "badge": sc.get("badge") or "INEMA",
                        "slide_label": sc.get("slide_label") or "",
                        # solid_block extras
                        "block_color": payload.get("block_color") or "#FFD600",
                        "block_text_color": payload.get("block_text_color") or "#000000",
                        # stamp_diagonal extras
                        "stamp_color": payload.get("stamp_color") or "#F09025",
                        "stamp_glow": payload.get("stamp_glow") or "rgba(240,144,37,0.55)",
                        # kinetic_pop extras
                        "pop_color": payload.get("pop_color") or "#00E5FF",
                        "pop_glow1": payload.get("pop_glow1") or "rgba(0,229,255,0.85)",
                        "pop_glow2": payload.get("pop_glow2") or "rgba(0,229,255,0.55)",
                        "pop_glow3": payload.get("pop_glow3") or "rgba(0,229,255,0.35)",
                        # minimal_caption
                        "caption_prefix": sc.get("caption_prefix") or "",
                    }

                    html = tmpl.render(**ctx)
                    html_file = tmp_path / f"scene_{i:02d}.html"
                    html_file.write_text(html, encoding="utf-8")

                    bctx = await browser.new_context(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                    )
                    page = await bctx.new_page()
                    # Transparent background for PNG alpha
                    await page.emulate_media(media="screen")
                    await page.goto(f"file://{html_file}", wait_until="networkidle")
                    png_path = tmp_path / f"scene_{i:02d}_text.png"
                    await page.screenshot(
                        path=str(png_path),
                        omit_background=True,  # key: preserves transparency
                        clip={"x": 0, "y": 0, "width": width, "height": height},
                        type="png",
                    )
                    await bctx.close()

                    url = storage.save_bytes(
                        tenant_id=job.tenant_id,
                        job_id=job.job_id,
                        filename=f"scene_{i:02d}_text.png",
                        data=png_path.read_bytes(),
                    )
                    outputs.append({
                        "scene_index": i,
                        "has_text": True,
                        "text_png_url": url,
                        "width": width,
                        "height": height,
                        "text": text,
                        "position": text_position,
                    })
                await browser.close()

        return {
            "outputs": outputs,
            "template": template_name,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    VideoTextDesignerWorker().run(host="0.0.0.0", port=8116)
