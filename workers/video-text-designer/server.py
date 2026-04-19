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
    """Font size adaptativo (mkt3-style): <30chars=80px, 30-60=64, 60+=52.
    Escala pelo width (reel 1080 = baseline)."""
    chars = max(1, len(text.strip()))
    if chars < 20:
        base = 108
    elif chars < 40:
        base = 84
    elif chars < 70:
        base = 64
    else:
        base = 52
    # Escala pelo width (>=1080 = 1.0, landscape 1920 = 1.4)
    scale = width / 1080.0
    return max(36, int(base * scale))


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

        template_name = payload.get("template", "editorial_chrome_textonly")
        tmpl = _jinja.get_template(f"{template_name}.html")
        use_dark_bar = bool(payload.get("use_dark_bar", False))
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

                    # Stat mode: quando cena tem stat_a.number E o tipo é proof/solution
                    stat_number = None
                    stat_a = sc.get("stat_a") or {}
                    if isinstance(stat_a, dict) and scene_type in ("proof", "solution"):
                        stat_number = stat_a.get("number")

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
                        "use_dark_bar": use_dark_bar,
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
