#!/usr/bin/env python3
"""Regera thumbnails dos estilos de text overlay.

Lê a lista de estilos de
`workers/video-text-designer/styles.json` e, pra cada um, renderiza
um JPG 360×640 mostrando como o estilo fica sobre uma cena demo.

Uso:
  python scripts/gen_text_style_thumbs.py

Gera em `workers/video-text-designer/assets/thumbs/<slug>.jpg`.
Source-of-truth pros estilos: o JSON. Adicione/edite/remova lá e
rode este script + restart do worker.
"""
import asyncio
import json
import pathlib
import random
import sys

import jinja2
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).parent.parent.resolve()
WORKER = ROOT / "workers" / "video-text-designer"
TEMPLATES = WORKER / "templates"
STYLES_JSON = WORKER / "styles.json"
OUT = WORKER / "assets" / "thumbs"

THUMB_W, THUMB_H = 360, 640       # thumb size
CANVAS_W, CANVAS_H = 1080, 1920   # render canvas (portrait 9:16)


def make_demo_bg(w: int, h: int) -> Image.Image:
    """Fundo demo — gradient escuro com luz teal no centro + noise."""
    bg = Image.new("RGB", (w, h), "#0a0f18")
    draw = ImageDraw.Draw(bg)
    for r in range(int(min(w, h) * 0.6), 0, -20):
        alpha = int(120 * (1 - r / (min(w, h) * 0.6)))
        draw.ellipse(
            [(w // 2 - r, h // 2 - r), (w // 2 + r, h // 2 + r)],
            fill=(10 + alpha // 5, 30 + alpha // 3, 60 + alpha // 2),
        )
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
    rng = random.Random(42)
    px = bg.load()
    for _ in range(w * h // 400):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        r, g, b = px[x, y]
        v = rng.randint(-12, 12)
        px[x, y] = (
            max(0, min(255, r + v)),
            max(0, min(255, g + v)),
            max(0, min(255, b + v)),
        )
    return bg


async def render_one(browser, env: jinja2.Environment, style: dict) -> pathlib.Path:
    slug = style["slug"]
    template = style["template"]
    preview = style.get("preview", {})

    tmpl_path = TEMPLATES / f"{template}.html"
    if not tmpl_path.exists():
        raise FileNotFoundError(
            f"Template {template}.html não existe (referenciado por {slug})"
        )
    tmpl = env.get_template(f"{template}.html")

    font_size = preview.get("font_size", 120)
    ctx = {
        "width": CANVAS_W,
        "height": CANVAS_H,
        "text_overlay": preview.get("text", slug.upper()),
        "text_position": preview.get("text_position", "top"),
        "scene_type": preview.get("scene_type", "hook"),
        "font_size": font_size,
        "max_text_width": 900,
        "safe_top": 140,
        "safe_bottom": 200,
        "pad_h": 72,
        "bar_pad_y": int(font_size * 0.40),
        "stat_number": preview.get("stat_number"),
        "stat_a": preview.get("stat_a"),
        "use_dark_bar": preview.get("use_dark_bar", False),
        "use_dark_top_fade": True,
        "use_accent_line": True,
        "fade_top_height": 200,
        "is_brand_moment": preview.get("is_brand_moment", False),
        "brand_logo": preview.get("brand_logo") or "INEMA",
        "brand_tag": preview.get("brand_tag", ""),
        "brand_handle": preview.get("brand_handle", "@inema.tds"),
        "badge": preview.get("badge") or "INEMA",
        "slide_label": preview.get("slide_label", ""),
        "block_color": preview.get("block_color", "#FFD600"),
        "block_text_color": preview.get("block_text_color", "#000000"),
        "stamp_color": preview.get("stamp_color", "#F09025"),
        "stamp_glow": preview.get("stamp_glow", "rgba(240,144,37,0.55)"),
        "pop_color": preview.get("pop_color", "#00E5FF"),
        "pop_glow1": preview.get("pop_glow1", "rgba(0,229,255,0.85)"),
        "pop_glow2": preview.get("pop_glow2", "rgba(0,229,255,0.55)"),
        "pop_glow3": preview.get("pop_glow3", "rgba(0,229,255,0.35)"),
        "caption_prefix": preview.get("caption_prefix", ""),
    }

    html = tmpl.render(**ctx)
    html_tmp = pathlib.Path(f"/tmp/_style_preview_{slug}.html")
    html_tmp.write_text(html, encoding="utf-8")

    bctx = await browser.new_context(
        viewport={"width": CANVAS_W, "height": CANVAS_H}, device_scale_factor=1,
    )
    page = await bctx.new_page()
    await page.goto(f"file://{html_tmp}", wait_until="networkidle")
    png_tmp = pathlib.Path(f"/tmp/_style_preview_{slug}.png")
    await page.screenshot(
        path=str(png_tmp),
        omit_background=True,
        clip={"x": 0, "y": 0, "width": CANVAS_W, "height": CANVAS_H},
        type="png",
    )
    await bctx.close()

    # Composite: demo bg + text PNG alpha → JPG
    bg = make_demo_bg(CANVAS_W, CANVAS_H).convert("RGBA")
    text = Image.open(png_tmp).convert("RGBA")
    composed = Image.alpha_composite(bg, text).convert("RGB")
    thumb = composed.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    out_path = OUT / f"{slug}.jpg"
    thumb.save(out_path, quality=85)
    return out_path


async def main() -> None:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    if not STYLES_JSON.exists():
        print(f"ERROR: {STYLES_JSON} não existe", file=sys.stderr)
        sys.exit(2)

    manifest = json.loads(STYLES_JSON.read_text(encoding="utf-8"))
    styles = manifest.get("styles", [])
    if not styles:
        print("Nenhum estilo no manifest. Nada pra fazer.", file=sys.stderr)
        return

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=jinja2.select_autoescape(["html"]),
    )

    print(f"Gerando {len(styles)} thumbnails em {OUT}…")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for style in styles:
            try:
                path = await render_one(browser, env, style)
                print(f"  ✓ {style['slug']:24s} → {path.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {style['slug']}: {exc}", file=sys.stderr)
        await browser.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
