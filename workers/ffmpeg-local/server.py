"""ffmpeg-local worker — renderer de video a partir de scene_plan.

Capability: `video.render`. Porta 8105.

Fase 1 (paridade mkt3 + features 2026):
  - Motion interpolado (zoom_start → zoom_end, intensity)
  - Music ducking (trilha -18dB sob voz via sidechaincompress)
  - SFX por transição (swoosh/stab via adelay)
  - Karaoke captions palavra-por-palavra (drawtext com enable timing)
  - Hook pattern (primeira cena com motion mais agressivo + SFX stab)

Input (payload):
  {
    "scene_plan": {...},
    "narration_url": "...",
    "music_genre": "ambient|synthwave|edm|...",
    "use_sfx": true,
    "use_karaoke": true,
    "style": "corporate_clean" (do video-art-director)
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("imkt4.ffmpeg")

from workers._base import BaseWorker
from workers._base.storage import get_storage

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Fontes do estilo editorial magazine (padrão mkt3 video-quick).
# Serif black pro headline, Inter sem-serif pro body. Se ausentes, cai pro FONT_BOLD.
_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
FONT_SERIF_EDITORIAL = str(_FONT_DIR / "PlayfairDisplay.ttf")
FONT_SANS_EDITORIAL  = str(_FONT_DIR / "Inter.ttf")


def _pick_font(font_family: str | None = None) -> str:
    """Escolhe o arquivo de fonte pelo nome lógico (ou fallback)."""
    fam = (font_family or "").lower().strip()
    if fam in ("lora", "playfair", "dm serif display", "dm serif", "serif", "editorial"):
        if Path(FONT_SERIF_EDITORIAL).exists():
            return FONT_SERIF_EDITORIAL
    if fam in ("inter", "sans", "sans-serif"):
        if Path(FONT_SANS_EDITORIAL).exists():
            return FONT_SANS_EDITORIAL
    # fallback
    return FONT_BOLD

# Item 2 — defaults de narration_speed por style do video-art-director
NARRATION_SPEED_BY_STYLE = {
    "energetico": 1.20, "bold_pop": 1.20, "streetwear_urban": 1.20,
    "neon_futurista": 1.15, "dark_dramatic": 1.15,
    "corporate_clean": 1.10, "editorial_documentary": 1.10, "data_viz": 1.10,
    "retro_futurism": 1.10,
    "premium_minimal": 1.0, "emocional_cinematic": 1.0, "nature_organic": 1.0,
    "organic_earth": 1.0, "neo_minimal_luxury": 1.0,
    "wellness_soft": 1.0,  # clamp inferior; não aceleramos (pode ir 0.95 via override)
}

# Item 8 — styles que ativam parallax default (nível 1)
PARALLAX_DEFAULT_STYLES = {
    "dark_dramatic", "emocional_cinematic", "premium_minimal",
    "editorial_documentary", "neo_minimal_luxury", "retro_futurism",
}

# Item 13b — presets por style (art-director emite text_animation)
KINETIC_PRESETS_BY_STYLE = {
    "editorial_documentary": "wipe",
    "bold_pop": "zoom_impact", "streetwear_urban": "zoom_impact",
    "energetico": "zoom_impact",
    "wellness_soft": "type_on", "nature_organic": "type_on", "organic_earth": "type_on",
    "neon_futurista": "glow_pulse", "retro_futurism": "glow_pulse",
    "corporate_clean": "static", "data_viz": "static",
}

# Item 12 — caption_zone (y% range: start-end) por template/style
CAPTION_ZONE_BY_STYLE = {
    "editorial_documentary": (0.50, 0.65),
    "magazine": (0.60, 0.75),
    "data_viz": (0.15, 0.25),  # stats ocupam meio; caption em cima
    "corporate_clean": (0.45, 0.60),
    "wellness_soft": (0.55, 0.70),
    "bold_pop": (0.40, 0.55),
    "streetwear_urban": (0.40, 0.55),
    "neo_minimal_luxury": (0.55, 0.70),
    "retro_futurism": (0.50, 0.65),
    "neon_futurista": (0.50, 0.65),
    "dark_dramatic": (0.55, 0.70),
    "emocional_cinematic": (0.55, 0.70),
    "organic_earth": (0.55, 0.70),
    "nature_organic": (0.55, 0.70),
}

# Safe zone universal: nunca nos 15% topo nem 25% inferiores
SAFE_ZONE_Y = (0.25, 0.60)

# Item 12b — safe zones POR PLATAFORMA (flag opcional).
# tiktok tem botões à direita + descrição em baixo → zona vertical mais alta.
# instagram_reels: descrição no rodapé → zona ~45-60%.
# youtube_shorts: similar ao tiktok mas com share à direita.
# Quando `platform` não é passado, cai pro SAFE_ZONE_Y + caption_zone do style.
PLATFORM_SAFE_ZONES = {
    "tiktok": (0.30, 0.55),            # evita: top 15% (search), bottom 30% (desc + botões)
    "reels": (0.35, 0.55),             # evita: top 10% + bottom 35% (descrição/audio)
    "instagram_reels": (0.35, 0.55),
    "shorts": (0.28, 0.58),            # youtube shorts: similar ao tiktok
    "youtube_shorts": (0.28, 0.58),
    "stories": (0.25, 0.55),           # instagram stories
    "instagram_stories": (0.25, 0.55),
    "feed": (0.15, 0.70),              # feed quadrado é mais livre
    "instagram_feed": (0.15, 0.70),
}


def _resolve_narration_speed(user_override: Any, style: str) -> float:
    """Item 2 — resolve narration speed. User override > style default > 1.0.
    Clamp [1.0, 1.25] (fora disso desliga pra não distorcer)."""
    if user_override is not None:
        try:
            s = float(user_override)
            return max(1.0, min(1.25, s))
        except (ValueError, TypeError):
            pass
    default = NARRATION_SPEED_BY_STYLE.get(style, 1.0)
    return max(1.0, min(1.25, default))


def _parallax_default_for_style(style: str) -> bool:
    """Item 8 — parallax nível 1 default ON para styles cinematográficos."""
    return style in PARALLAX_DEFAULT_STYLES


def _caption_zone_for_style(
    style: str, platform: str | None = None,
) -> tuple[float, float]:
    """Item 12 — retorna caption_zone (y%_start, y%_end).

    Item 12b (flag opcional) — se `platform` é passado, usa a safe zone
    específica da plataforma como BOUND (mais conservador que safe zone
    universal). Intersecta com o caption_zone do style pra respeitar os
    dois ao mesmo tempo.

    Sem platform → cai pro caption_zone do style + safe zone universal
    (comportamento v4 original).
    """
    zone = CAPTION_ZONE_BY_STYLE.get(style, SAFE_ZONE_Y)
    bound = SAFE_ZONE_Y
    if platform:
        bound = PLATFORM_SAFE_ZONES.get(platform.lower(), SAFE_ZONE_Y)
    # Intersecção: zone ∩ bound. Se disjuntos, volta pro bound (plataforma
    # manda — o botão do tiktok não some porque o template pede caption baixa).
    y_start = max(bound[0], zone[0])
    y_end = min(bound[1], zone[1])
    if y_end <= y_start + 0.05:
        # Conflito: style pedia fora da zona segura. Usa só bound.
        y_start, y_end = bound
    return (y_start, y_end)

ASSETS_DIR = Path(__file__).parent / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR = ASSETS_DIR / "sfx"


def _select_music(genre: str | None) -> Path | None:
    """Retorna trilha local pra um mood. Fallbacks progressivos."""
    if not genre:
        return None
    # Normaliza espaços/hifens: "piano solo" → "piano_solo"
    g = genre.lower().strip().replace(" ", "_").replace("-", "_")
    # aliases mais comuns
    aliases = {
        "synthwave": "synthwave", "synth": "synthwave", "retro": "synthwave",
        "edm": "edm", "electronic": "edm", "dance": "edm",
        "ambient": "ambient", "lofi": "ambient", "ambiance": "ambient",
        "piano_solo": "piano_solo", "piano": "piano_solo",
        "pop": "pop", "upbeat": "pop", "ukulele_pop": "pop",
        "piano_strings": "piano_strings", "cinematic": "piano_strings",
        "folk": "folk", "acoustic": "folk",
        "drone": "drone", "dark": "drone",
        "trap": "synthwave",  # fallback
        "jazz": "piano_strings", "jazz_blues": "piano_strings",
        "piano_minimal": "piano_solo",
    }
    key = aliases.get(g, g)
    cand = MUSIC_DIR / f"{key}.mp3"
    if cand.exists():
        return cand
    # último fallback: qualquer mp3 que existe
    for p in MUSIC_DIR.glob("*.mp3"):
        return p
    return None


def _sfx_for_style(style: str | None, hook_pattern: str | None) -> tuple[Path | None, Path | None]:
    """Retorna (hook_sfx, transition_sfx) com base no style+hook.
    Hook usa stab (forte); transição usa swoosh (suave)."""
    hook = SFX_DIR / "stab.mp3"
    transition = SFX_DIR / "swoosh.mp3"
    if hook_pattern in ("pattern_interrupt", "stat_shot"):
        hook_sfx = hook if hook.exists() else None
    else:
        hook_sfx = None
    trans_sfx = transition if transition.exists() else None
    # styles tranquilos não usam SFX
    if style in ("premium_minimal", "emocional_cinematic", "editorial_documentary", "nature_organic"):
        hook_sfx = None
        trans_sfx = None
    return hook_sfx, trans_sfx


def _motion_zoompan(motion: dict, width: int, height: int, total_frames: int, fps: int = 30) -> str:
    """Monta expressão zoompan a partir de motion = {type, zoom_start, zoom_end, intensity}.
    Aceita também o motion.type legado sem zoom_start/end (infere).
    """
    mtype = (motion or {}).get("type", "static")
    intensity = (motion or {}).get("intensity", "moderate")
    z_start = float(motion.get("zoom_start", 0) or 0)
    z_end = float(motion.get("zoom_end", 0) or 0)

    # Infere zoom_start/end a partir do tipo se não vier parametrizado
    if not z_start and not z_end:
        if mtype in ("zoom_in", "push-in", "ken-burns-in"):
            z_start, z_end = 1.0, 1.08 if intensity != "strong" else 1.15
        elif mtype in ("zoom_out", "ken-burns-out", "pull-out"):
            z_start, z_end = 1.08, 1.0
        elif mtype == "hard_zoom":
            z_start, z_end = 1.0, 1.18  # agressivo, pattern interrupt
        elif mtype == "breathe":
            z_start, z_end = 1.0, 1.025
        elif mtype in ("pan_right", "drift"):
            z_start, z_end = 1.05, 1.05  # zoom fixo, pan via x
        elif mtype == "pan_left":
            z_start, z_end = 1.05, 1.05
        else:
            z_start, z_end = 1.0, 1.0  # static

    # Expressão linear: z_start + (z_end - z_start) * on/total
    z_expr = f"({z_start:.3f}+({z_end - z_start:.3f})*on/{total_frames})"

    # x/y: center-cropped default; pan lateral se pan_*
    if mtype in ("pan_right", "drift"):
        x_expr = f"(iw-(iw/zoom))*on/{total_frames}"
    elif mtype == "pan_left":
        x_expr = f"(iw-(iw/zoom))*(1-on/{total_frames})"
    else:
        x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={total_frames}:s={width}x{height}:fps={fps}"
    )


def _build_vf(
    scene: dict[str, Any],
    width: int, height: int,
    duration: int, tmp: Path, idx: int,
    is_hook: bool = False,
    karaoke: list[dict] | None = None,
    color_grade: str | None = None,  # "cool" | "warm" | None
    ass_karaoke_active: bool = False,  # se True, pula text_overlay pesado
    use_vignette: bool = False,
    use_grain: bool = False,
) -> str:
    """Monta -vf: crop → motion → color grading → (karaoke | text overlay)."""
    fps = 30
    total_frames = duration * fps

    # Base: scale 1.3× pra ter margem de zoom
    scale_w = int(width * 1.3)
    scale_h = int(height * 1.3)
    base = (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={scale_w}:{scale_h}"
    )

    motion = scene.get("motion") or {}
    # Hook: força motion mais agressivo se for pattern interrupt
    if is_hook and motion.get("type") in (None, "static"):
        motion = {"type": "hard_zoom"}
    mtype = motion.get("type", "static")

    if mtype == "static":
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        zoom = _motion_zoompan(motion, width, height, total_frames, fps)
        vf = f"{base},{zoom}"

    # Color grading por seção narrativa (Fase 2).
    # cool = azul/frio (hook/tensão); warm = dourado (solução/CTA).
    if color_grade == "cool":
        vf = f"{vf},colorchannelmixer=rr=0.88:gg=0.92:bb=1.08,eq=saturation=0.92"
    elif color_grade == "warm":
        vf = f"{vf},colorchannelmixer=rr=1.08:gg=1.02:bb=0.92,eq=saturation=1.08"

    # Fase 3 — decorações pro mode (cchyperframes MOTION_PHILOSOPHY):
    # - Vignette radial-gradient (lei 2 "Black is the canvas") — PI/4
    # - Film grain super faint (lei 10 "one unifying texture") — noise c0s=5
    if use_vignette:
        vf = f"{vf},vignette=PI/4:eval=init"
    if use_grain:
        # noise c0s=5 = grain sutil no canal Y (luminância), quase imperceptível
        vf = f"{vf},noise=c0s=5:c0f=t+u"

    # Karaoke por cena (LEGADO — ASS chain é aplicado após concat).
    if karaoke:
        vf = f"{vf},{_build_karaoke_draw(karaoke, duration, width, height)}"
    elif not ass_karaoke_active and (scene.get("text_overlay") or "").strip():
        # text_overlay (drawbox+drawtext) só quando ASS não está ativo —
        # evita conflito visual entre título estático + karaoke fluindo.
        vf = f"{vf},{_build_text_overlay(scene, width, height, tmp, idx)}"

    return vf


def _build_text_overlay(scene: dict, width: int, height: int, tmp: Path, idx: int) -> str:
    """Text overlay estilo MAGAZINE EDITORIAL (padrão mkt3 video-quick):
       - serif black (Playfair Display) — headline dominante
       - SEM drawbox preto cobrindo fundo (apenas um gradiente sutil)
       - shadow forte: '0 4px 12px rgba(0,0,0,0.8)' = shadowy=4 + dark box
       - outline 3px preto (bordercolor+borderw) pra legibilidade
       - safe zone: 120px topo em 9:16 (6.25% altura), 80px em 1:1
       - text_position default 'top' (NUNCA 'bottom' por baixo = área de ação).
    """
    overlay = (scene.get("text_overlay") or "").strip()
    font_size = int(scene.get("font_size", 88))

    pad_side = int(width * 0.07)
    usable_w = width - 2 * pad_side
    avg_char_w = font_size * 0.55
    max_chars_per_line = max(8, int(usable_w / avg_char_w))

    import textwrap as _tw
    wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
    n_lines = wrapped.count("\n") + 1
    if n_lines > 3:
        font_size = max(48, int(font_size * 3 / n_lines))
        avg_char_w = font_size * 0.55
        max_chars_per_line = max(8, int(usable_w / avg_char_w))
        wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
        n_lines = wrapped.count("\n") + 1

    txt_path = tmp / f"text_{idx:02d}.txt"
    txt_path.write_text(wrapped, encoding="utf-8")

    position = scene.get("text_position", "top")
    block_h = int(font_size * 1.15 * n_lines)
    # Safe zone editorial (mkt3): 120px top em 9:16 (1920h → 6.25%).
    # Em 1:1 (1080h) usa 80px (7.4%). Mínimo 48px pra landscape curto.
    is_vertical = height > width * 1.1
    margin_y = 120 if is_vertical else max(48, int(height * 0.075))
    if position == "top":
        y_txt = margin_y
    elif position == "center":
        y_txt = (height - block_h) // 2
    else:
        y_txt = height - block_h - margin_y

    # Fonte: scene pode pedir font_family específica; default serif editorial
    font_family = scene.get("font_family") or "Playfair"
    font_file = _pick_font(font_family)
    line_spacing = int(font_size * 0.1)

    # Overlay escuro SUTIL na zona do texto (vignette local) em vez de drawbox
    # cobrindo tudo. Usa apenas a FAIXA vertical onde o texto fica, com
    # gradient horizontal que desaparece nas laterais.
    # Implementação: boxblur só atrás do texto, alpha baixa.
    shadow_y1 = max(0, y_txt - int(font_size * 0.3))
    shadow_h = block_h + int(font_size * 0.6)
    opacity = scene.get("overlay_opacity", 0.32)  # antes era 0.55; reduzido

    return (
        # Faixa horizontal escurecida APENAS onde texto vai (sem ocupar a
        # tela inteira; dá contraste sem esconder a imagem de fundo).
        f"drawbox=x=0:y={shadow_y1}:w={width}:h={shadow_h}:"
        f"color=black@{opacity}:t=fill,"
        # Headline — serif black, shadow forte, outline 3px preto
        f"drawtext=fontfile={font_file}:"
        f"textfile={txt_path}:"
        f"fontcolor=white:"
        f"fontsize={font_size}:"
        f"line_spacing={line_spacing}:"
        f"x=(w-text_w)/2:"
        f"y={y_txt}:"
        # Outline 3px + shadow 4px simula 'text-shadow: 0 4px 12px rgba(0,0,0,0.8)'
        f"borderw=3:bordercolor=black@0.85:"
        f"shadowcolor=black@0.75:shadowx=0:shadowy=4"
    )


def _escape_drawtext(text: str) -> str:
    """Escapa caracteres especiais do drawtext (aspas, backslash, %, :)."""
    return (text.replace("\\", "\\\\").replace("'", "\\'")
            .replace(":", "\\:").replace("%", "\\%"))


def _build_karaoke_draw(words: list[dict], duration: int, width: int, height: int) -> str:
    """LEGADO — via drawtext encadeado. Mantido como fallback mas o fluxo
    principal agora usa ASS subtitles (ver _build_ass_karaoke). ASS evita
    overlap em narrações densas que ocorria com o drawtext chain.
    """
    if not words:
        return ""
    font_size = max(70, int(height * 0.045))
    y_pos = int(height * 0.72)
    box_y = y_pos - int(font_size * 0.3)
    box_h = int(font_size * 1.6)
    parts = [
        f"drawbox=x=0:y={box_y}:w={width}:h={box_h}:"
        f"color=black@0.45:t=fill:"
        f"enable='between(t,{words[0]['start']:.2f},{words[-1]['end']:.2f})'"
    ]
    for w in words:
        txt = _escape_drawtext(w["text"].upper())
        parts.append(
            f"drawtext=fontfile={FONT_BOLD}:"
            f"text='{txt}':"
            f"fontcolor=yellow:"
            f"fontsize={font_size}:"
            f"x=(w-text_w)/2:y={y_pos}:"
            f"shadowcolor=black@0.95:shadowx=0:shadowy=4:"
            f"enable='between(t,{w['start']:.2f},{w['end']:.2f})'"
        )
    return ",".join(parts)


def _ass_time(seconds: float) -> str:
    """Formata float seconds pro formato ASS: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _build_ass_karaoke_with_zone(
    words_global: list[dict],
    width: int,
    height: int,
    caption_zone: tuple[float, float] = (0.25, 0.60),
    scenes: list[dict] | None = None,
    scene_starts: list[float] | None = None,
    kinetic_presets: bool = False,
    kinetic_style: str | None = None,
) -> str:
    """Item 12 + 13a + 13b — ASS com caption_zone do template + fade-in
    default + kinetic presets opcionais.

    caption_zone = (y%_start, y%_end) onde o texto deve aparecer.
    MarginV em ASS é distance-from-bottom; converte: y_pct → pixels abaixo
    → distance do bottom.
    """
    font_size = max(70, int(height * 0.045))

    # Posição: centro da caption_zone, convertido pra MarginV (from bottom)
    y_pct_center = (caption_zone[0] + caption_zone[1]) / 2.0
    # y_pixels from top = y_pct_center * height → dist from bottom = height - y_pixels
    margin_v = int(height - (y_pct_center * height) - font_size / 2)
    margin_v = max(int(height * 0.05), margin_v)  # clamp mínimo

    # PrimaryColour em ASS é &HAABBGGRR& (alpha inverso): amarelo = &H0000FFFF
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BorderStyle, Outline, Shadow, Alignment, MarginV\n"
        f"Style: Karaoke,DejaVu Sans,{font_size},&H0000FFFF,&H00000000,"
        f"1,4,3,2,{margin_v}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # Identifica: é hook (scene 0)? é última palavra do CTA (última cena)?
    last_scene_idx = (len(scenes) - 1) if scenes else None
    n_words = len(words_global)
    last_word_idx = n_words - 1

    lines = []
    for wi, w in enumerate(words_global):
        start = _ass_time(w["start"])
        end = _ass_time(w["end"])
        txt_raw = w["text"].upper()
        txt = txt_raw.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

        # Item 13a (default ON): fade-in 180ms em toda palavra
        tags = "{\\fad(180,0)}"

        # Item 13a (bounce na última palavra do CTA, cena final)
        scene_i = w.get("scene_index", -1)
        is_last_of_cta = (
            scene_i == last_scene_idx and wi == last_word_idx and scenes
        )
        if is_last_of_cta:
            tags = "{\\fad(180,0)\\t(0,200,\\fscx110\\fscy110)\\t(200,400,\\fscx100\\fscy100)}"

        # Item 13b — presets por style (só no hook cena 0 ou emphasis explícito)
        if kinetic_presets and kinetic_style and scenes:
            is_hook_scene = scene_i == 0
            scene_obj = scenes[scene_i] if 0 <= scene_i < len(scenes) else {}
            is_emphasis = bool(scene_obj.get("emphasis"))
            if (is_hook_scene or is_emphasis) and kinetic_style != "static":
                tags = _ass_preset_tag(kinetic_style, is_last_of_cta)

        lines.append(f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{tags}{txt}")
    return header + "\n".join(lines) + "\n"


def _ass_preset_tag(preset: str, is_last: bool) -> str:
    """Mapeia preset nome → tags ASS. Item 13b."""
    base_fade = "\\fad(180,0)"
    if preset == "wipe":
        # slide up do bottom com clip progressivo (editorial)
        return "{" + base_fade + "\\move(0,100,0,0,0,200)}"
    if preset == "zoom_impact":
        # scale punch: 130% → 100% (bold_pop)
        return "{" + base_fade + "\\fscx130\\fscy130\\t(0,120,\\fscx100\\fscy100)}"
    if preset == "type_on":
        # letra-por-letra seria muito pesado em ASS engine; simula com fade longo
        return "{\\fad(400,0)}"
    if preset == "glow_pulse":
        # pulsa outline (neon) — usa \bord piscante
        return "{" + base_fade + "\\bord4\\t(0,400,\\bord8)\\t(400,800,\\bord4)}"
    return "{" + base_fade + "}"


def _build_ass_karaoke(words_global: list[dict], width: int, height: int) -> str:
    """Gera conteúdo .ass com 1 dialog por palavra. `words_global` tem
    timings ABSOLUTOS (video inteiro). Cada palavra aparece no seu slot;
    ASS engine garante zero overlap mesmo com narração densa."""
    font_size = max(70, int(height * 0.045))
    # PrimaryColour em ASS é &HAABBGGRR& (alpha inverso): amarelo = &H0000FFFF
    # OutlineColour preto; Alignment 2 = bottom center; MarginV = distância ao bottom
    margin_v = int(height * 0.22)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: " + str(width) + "\n"
        "PlayResY: " + str(height) + "\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BorderStyle, Outline, Shadow, Alignment, MarginV\n"
        f"Style: Karaoke,DejaVu Sans,{font_size},&H0000FFFF,&H00000000,"
        f"1,4,3,2,{margin_v}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for w in words_global:
        start = _ass_time(w["start"])
        end = _ass_time(w["end"])
        # Escape de {}, \ e , no texto ASS
        txt = w["text"].upper().replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{txt}")
    return header + "\n".join(lines) + "\n"


def _annotate_freeze_word_timings(scenes: list[dict], words: list[dict]) -> None:
    """Item 14b — quando whisper deu timings reais, sobrescreve freeze_at
    pra EXATAMENTE o start da palavra marcada com emphasis=true no LLM.
    Se scene.emphasis_word não tem match nos whisper words, deixa o
    freeze_at heurístico (60% da cena).
    """
    # Agrupa words por scene_index
    by_scene: dict[int, list[dict]] = {}
    for w in words:
        si = w.get("scene_index", -1)
        by_scene.setdefault(si, []).append(w)

    for i, sc in enumerate(scenes):
        emphasis_word = sc.get("emphasis_word") or sc.get("stat_a") or sc.get("stat_b")
        if not emphasis_word or not isinstance(emphasis_word, str):
            continue
        target = re.sub(r"[^a-zA-Z0-9%]", "", emphasis_word.upper())
        if not target:
            continue
        scene_words = by_scene.get(i, [])
        if not scene_words:
            continue
        scene_start = scene_words[0]["start"]
        for w in scene_words:
            clean = re.sub(r"[^a-zA-Z0-9%]", "", w["text"].upper())
            if clean == target or (target in clean and len(clean) <= len(target) + 2):
                # sobrescreve freeze_at pro offset local (dentro da cena)
                sc["freeze_at"] = max(0.3, w["start"] - scene_start)
                break


def _freeze_spec_for_scene(sc: dict, scene_type: str, idx: int) -> dict | None:
    """Item 14 — decide se cena leva freeze. LLM planner pode passar
    freeze_at/duration/zoom/sfx explícitos no scene; senão heurística
    auto dispara em cenas com stat_a/stat_b OU scene_type proof/solution."""
    # Explícito pelo planner
    if sc.get("freeze_at") is not None:
        return {
            "freeze_at": float(sc.get("freeze_at", 1.5)),
            "freeze_duration": float(sc.get("freeze_duration", 0.8)),
            "freeze_zoom": float(sc.get("freeze_zoom", 1.15)),
            "freeze_sfx": sc.get("freeze_sfx"),
        }
    # Heurística: dado numérico em stat_a/stat_b ou tipo=proof/solution
    has_stat = bool(sc.get("stat_a") or sc.get("stat_b"))
    is_reveal = scene_type in ("proof", "solution")
    if has_stat or is_reveal:
        dur_sc = float(sc.get("duration", 3))
        # freeze_at: ~60% da cena (quando o "boom" naturalmente cai)
        return {
            "freeze_at": max(0.5, min(dur_sc - 1.0, dur_sc * 0.6)),
            "freeze_duration": 0.8,
            "freeze_zoom": 1.15,
            "freeze_sfx": "ding",
        }
    return None


def _apply_parallax_fake(vf: str, duration: int, width: int, height: int) -> str:
    """Item 8 nível 1 — parallax fake via ajuste na chain de vf.
    Adiciona blur sutil pra simular profundidade sem depth map real.
    """
    if "boxblur" not in vf:
        vf = vf + f",boxblur=lr=2:lp=1:cr=0:cp=0,unsharp=lx=3:ly=3:la=0.5"
    return vf


_DEPTH_MODEL = None


def _depth_anything_model():
    """Item 8b — lazy load do Depth-Anything V2 (se disponível).
    Se transformers + torch não instalados, devolve None — pipeline cai
    silenciosamente pro nível 1 (fake parallax).
    """
    global _DEPTH_MODEL
    if _DEPTH_MODEL is not None:
        return _DEPTH_MODEL if _DEPTH_MODEL != "unavailable" else None
    try:
        # Depth-Anything é disponível via transformers (pipeline
        # 'depth-estimation'). Requer torch instalado.
        from transformers import pipeline
        import torch  # noqa: F401  (verificação)
        _DEPTH_MODEL = pipeline(
            "depth-estimation",
            model=os.environ.get("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf"),
            device=0 if _has_cuda() else -1,
        )
        return _DEPTH_MODEL
    except Exception as exc:  # noqa: BLE001
        log.info("depth_ai indisponível (%s) — usa parallax nível 1", exc)
        _DEPTH_MODEL = "unavailable"
        return None


def _has_cuda() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


async def _generate_depth_map(image_path: Path, out_path: Path) -> bool:
    """Item 8b — gera depth map 16-bit pra uma imagem. Retorna True se ok."""
    model = _depth_anything_model()
    if model is None:
        return False
    try:
        def _sync():
            from PIL import Image
            img = Image.open(image_path).convert("RGB")
            out = model(img)
            depth = out["depth"]  # PIL.Image grayscale
            depth.save(out_path)
            return True
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)
    except Exception as exc:  # noqa: BLE001
        log.warning("depth map falhou pra %s: %s", image_path, exc)
        return False


def _build_depth_parallax_filter(
    depth_path: Path, width: int, height: int, duration: int,
) -> str:
    """Item 8b — constrói filter_complex pra parallax baseado em depth map.
    Implementação simples: 2 camadas (foreground / background) divididas
    pelo depth, ambas com zoompan diferente; overlay final.

    Uso simplificado aqui: aplica deslocamento horizontal pequeno proporcional
    ao depth (geomap pseudo-3D). Integração completa com depth requer
    displacement map ffmpeg (displace filter).
    """
    # displace com depth como mapa horizontal: cria ilusão 3D
    # -i main -i depth → displace=<edge=wrap>
    return (
        f"[0:v]scale={int(width*1.1)}:{int(height*1.1)},crop={width}:{height}[bg];"
        f"[1:v]scale={width}:{height}[dmap];"
        f"[bg][dmap]displace=edge=smear[vout]"
    )


def _cumulative_starts(scene_durations: list[float]) -> list[float]:
    """Retorna [0.0, d0, d0+d1, ...] — start absoluto de cada cena."""
    starts = [0.0]
    t = 0.0
    for d in scene_durations[:-1]:
        t += d
        starts.append(t)
    return starts


def _build_karaoke_per_scene(
    scenes: list[dict],
    audio_durations: list[float],
    scene_durations: list[float],
    full_narration_fallback: str = "",
) -> list[dict]:
    """Item 4 — constrói karaoke words com timing PER-SCENE.
    Cada cena distribui suas palavras dentro do seu audio_duration (não
    dentro do scene_duration inteiro, senão fica lento demais nas cenas
    com pad de silêncio). Fallback pra split global se nenhuma cena tem
    narration.

    Retorna [{text, start, end}, ...] com timings absolutos.
    """
    starts = _cumulative_starts(scene_durations)
    out: list[dict] = []
    any_scene_has_text = any(sc.get("narration") for sc in scenes)
    if not any_scene_has_text and full_narration_fallback:
        total = sum(scene_durations)
        return _split_script_words(full_narration_fallback, total)

    for i, sc in enumerate(scenes):
        text = (sc.get("narration") or "").strip()
        if not text:
            continue
        words = re.findall(r"\S+", text)
        if not words:
            continue
        start_abs = starts[i]
        # Distribui no audio_duration da cena (quando tem), senão no scene_dur.
        window = audio_durations[i] if audio_durations[i] > 0 else scene_durations[i]
        window = max(0.3, window)
        per_word = max(0.18, window / len(words))
        t = start_abs
        for w in words:
            out.append({
                "text": w,
                "start": t,
                "end": t + per_word,
                "scene_index": i,
            })
            t += per_word
    return out


def _split_script_words(script: str, total_duration: float) -> list[dict]:
    """Divide o script em palavras com timing uniforme (simples).
    Assume fala ~2.5 wps em pt-BR. Se total_duration dá margem, distribui proporcionalmente."""
    if not script:
        return []
    words = re.findall(r"\S+", script)
    if not words:
        return []
    per_word = total_duration / len(words)
    # mínimo 0.2s por palavra pra dar pra ler
    per_word = max(0.2, per_word)
    out = []
    t = 0.0
    for w in words:
        out.append({"text": w, "start": t, "end": t + per_word})
        t += per_word
    return out


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

        # ── Narração: item 4 (per-scene) + fallback legado (single) ──
        narration_urls = payload.get("narration_urls")  # list[str] (item 4)
        narration_url = payload.get("narration_url") or plan.get("narration_file")
        full_narration = plan.get("full_narration") or plan.get("narration_script") or ""
        if not narration_urls and narration_url:
            # legado: single URL → wrap em lista de 1 elemento
            narration_urls = [narration_url]
        narration_urls = narration_urls or []

        # Novos campos vindos do video-art-director
        music_genre = (payload.get("music_genre") or plan.get("music_genre") or "").strip()
        style = (payload.get("style") or plan.get("art_direction", {}).get("style") or "").strip()
        hook_pattern = (payload.get("hook_pattern") or plan.get("hook_pattern") or "").strip()
        # Default True; trata explicit None como default também (vem da recipe
        # quando user não informa; payload.get retorna None, não default).
        use_sfx = payload.get("use_sfx")
        use_sfx = True if use_sfx is None else bool(use_sfx)
        # Karaoke default OFF (pedido do user 2026-04-19). Antes era ON.
        # Liga via use_karaoke:true no input ou pill no modal.
        use_karaoke = bool(payload.get("use_karaoke", False))

        # Fase 2: crossfade + color grading opt-in (ativados por video_mode="pro")
        video_mode = (payload.get("video_mode") or "").lower()
        use_crossfade = video_mode == "pro" or bool(payload.get("use_crossfade"))
        use_color_grading = video_mode == "pro" or bool(payload.get("use_color_grading"))

        # Fase 3 (inspirada em cchyperframes MOTION_PHILOSOPHY):
        # pro mode ganha vignette (Lei 2 "Black is the canvas") +
        # film grain sutil ("super faint film grain") por default.
        use_vignette = video_mode == "pro" or bool(payload.get("use_vignette"))
        use_grain = video_mode == "pro" or bool(payload.get("use_grain"))

        # Transition do art-director vira crossfade se pro mode
        transition = (payload.get("transition") or plan.get("transition") or "cut").strip()

        # ── v4 flags (item 2, 5a, 5b, 8, 12, 13a/b, 14) ─────────────
        # Item 2: TTS speed por style (aplicado pós-TTS, pré-mix)
        narration_speed = _resolve_narration_speed(
            payload.get("narration_speed"), style,
        )
        # Item 5a: hold final silencioso (default ON quando video_length >= 8s)
        hold_final = payload.get("hold_final")
        hold_final = True if hold_final is None else bool(hold_final)
        # Item 5b: loop visual — flag OFF default
        loop_visual = bool(payload.get("loop_visual", False))
        # Item 8: parallax nível 1 (por style) + nível 2 (flag depth_ai)
        use_parallax = payload.get("use_parallax")
        if use_parallax is None:
            use_parallax = _parallax_default_for_style(style)
        else:
            use_parallax = bool(use_parallax)
        depth_ai = bool(payload.get("depth_ai", False))
        # Item 13b: kinetic presets por style (flag, OFF default)
        kinetic_presets = bool(payload.get("kinetic_presets", False))
        # Item 12b: safe zone por plataforma (flag, opcional)
        target_platform = (payload.get("platform") or plan.get("platform") or "").strip()
        # Item 14: freeze frames — auto por style ou flag explícita
        freeze_frames = payload.get("freeze_frames")
        if freeze_frames is None:
            freeze_frames = style in ("data_viz", "editorial", "corporate_clean")
        else:
            freeze_frames = bool(freeze_frames)

        music_path = _select_music(music_genre) if music_genre else None
        hook_sfx, trans_sfx = _sfx_for_style(style, hook_pattern) if use_sfx else (None, None)

        use_brand_overlay = bool(payload.get("use_brand_overlay"))
        tenant_id = payload.get("tenant_id") or job.tenant_id
        brand_overlay: Path | None = None
        if use_brand_overlay and tenant_id:
            candidate = Path(f"profiles/{tenant_id}/assets/brand_overlay.png").resolve()
            if candidate.exists():
                brand_overlay = candidate

        with tempfile.TemporaryDirectory(prefix=f"ffrender-{job.job_id}-") as tmp:
            tmp_path = Path(tmp)

            # 1) Baixa imagens + narração
            image_paths: list[Path] = []
            for i, sc in enumerate(scenes):
                img_url = sc.get("image")
                if not img_url:
                    raise ValueError(f"scene {i} sem campo 'image'")
                img_local = tmp_path / f"scene_{i:02d}.png"
                await _fetch_to(img_url, img_local)
                image_paths.append(img_local)

            # ── Narration: baixa N mp3s (item 4) + aplica atempo (item 2) ──
            audio_per_scene: list[Path | None] = [None] * len(scenes)
            audio_duration_per_scene: list[float] = [0.0] * len(scenes)
            if narration_urls:
                for i, url in enumerate(narration_urls[:len(scenes)]):
                    if not url:
                        continue
                    # Path 1) baixa
                    raw = tmp_path / f"narr_raw_{i:02d}.mp3"
                    try:
                        await _fetch_to(url, raw)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("falha baixando narração cena %d: %s", i, exc)
                        continue
                    # Path 2) aplica atempo (item 2) se speed != 1.0
                    if narration_speed and abs(narration_speed - 1.0) > 0.001:
                        sped = tmp_path / f"narr_{i:02d}.mp3"
                        try:
                            await _apply_atempo(raw, sped, narration_speed)
                            raw = sped
                        except Exception as exc:  # noqa: BLE001
                            log.warning("atempo falhou cena %d (speed=%.2f): %s",
                                        i, narration_speed, exc)
                    audio_per_scene[i] = raw
                    audio_duration_per_scene[i] = await _ffprobe_duration(raw)

            # Legacy single narration — audio_local pra o pipeline velho
            audio_local: Path | None = None
            if len(narration_urls) == 1 and audio_per_scene[0] is not None:
                audio_local = audio_per_scene[0]

            # ── Adjust scene_durations pro max(declared, audio + 0.3s) (item 4) ──
            declared_durations = [max(1, int(sc.get("duration", 3))) for sc in scenes]
            scene_durations = []
            for i, declared in enumerate(declared_durations):
                a_dur = audio_duration_per_scene[i]
                if a_dur > 0:
                    scene_durations.append(max(float(declared), a_dur + 0.3))
                else:
                    scene_durations.append(float(declared))

            # Item 5a — Hold final silencioso (+3s na última cena)
            # Skip se vídeo < 8s OU só 1 cena OU hold_final explicit False.
            pre_hold_total = sum(scene_durations)
            do_hold = hold_final and len(scenes) > 1 and pre_hold_total >= 8.0
            if do_hold:
                scene_durations[-1] += 3.0  # 0.5s natural + 2.5s freeze

            total_video_dur = sum(scene_durations)

            # Karaoke agora é aplicado DEPOIS do concat via ASS subtitles.
            # Item 1 — faster-whisper por cena quando áudio disponível,
            # senão cai pro split uniforme por cena (item 4).
            ass_karaoke_path: Path | None = None
            if use_karaoke:
                all_words = await self._build_karaoke_words(
                    scenes=scenes,
                    audio_per_scene=audio_per_scene,
                    audio_durations=audio_duration_per_scene,
                    scene_durations=scene_durations,
                    full_narration_fallback=full_narration,
                )
                # Marca emphasis no freeze_at exato via whisper (item 14b)
                if all_words and freeze_frames:
                    _annotate_freeze_word_timings(scenes, all_words)
                if all_words:
                    ass_content = _build_ass_karaoke_with_zone(
                        all_words, width, height,
                        caption_zone=_caption_zone_for_style(style, target_platform),
                        scenes=scenes,
                        scene_starts=_cumulative_starts(scene_durations),
                        kinetic_presets=kinetic_presets,
                        kinetic_style=KINETIC_PRESETS_BY_STYLE.get(style),
                    )
                    ass_karaoke_path = tmp_path / "karaoke.ass"
                    ass_karaoke_path.write_text(ass_content, encoding="utf-8")
            karaoke_by_scene: list[list[dict] | None] = [None] * len(scenes)

            # 2) Renderiza cada cena como mp4 parcial
            scene_clips: list[Path] = []
            n_scenes = len(scenes)
            for i, (sc, img_path) in enumerate(zip(scenes, image_paths)):
                dur = scene_durations[i]
                out = tmp_path / f"clip_{i:02d}.mp4"

                # Color grading por posição narrativa (Fase 2):
                # hook (i=0) + tensão (middle) = cool; solução+cta (final) = warm.
                scene_type = (sc.get("type") or "").lower()
                grade = None
                if use_color_grading:
                    if scene_type in ("hook", "tension") or i == 0:
                        grade = "cool"
                    elif scene_type in ("solution", "proof", "cta") or i >= n_scenes - 1:
                        grade = "warm"

                # Item 14 — freeze frame por cena
                scene_freeze = None
                if freeze_frames:
                    scene_freeze = _freeze_spec_for_scene(sc, scene_type, i)

                vf = _build_vf(
                    sc, width, height, int(dur), tmp_path, i,
                    is_hook=(i == 0 and hook_pattern in ("pattern_interrupt", "stat_shot")),
                    karaoke=karaoke_by_scene[i],
                    color_grade=grade,
                    ass_karaoke_active=ass_karaoke_path is not None,
                    use_vignette=use_vignette,
                    use_grain=use_grain,
                )

                # Item 8 — parallax nível 1 (fake via blur+unsharp)
                # Item 8b — nível 2 (depth_ai): tenta gerar depth_map real;
                # se modelo indisponível OU falhar, cai pro nível 1.
                parallax_depth_ok = False
                if use_parallax and depth_ai:
                    depth_png = tmp_path / f"depth_{i:02d}.png"
                    parallax_depth_ok = await _generate_depth_map(img_path, depth_png)
                    if not parallax_depth_ok:
                        vf = _apply_parallax_fake(vf, int(dur), width, height)
                elif use_parallax:
                    vf = _apply_parallax_fake(vf, int(dur), width, height)

                # Item 5a — última cena + hold final: renderiza dur_render como
                # dur - 3s e depois faz "freeze" dos últimos 3s. Aqui simplifico:
                # render completo com a imagem estática; o hold é visual (mesma imagem
                # continua). Se queremos loop visual (item 5b) na última, usa img[0].
                render_img = img_path
                is_last = (i == n_scenes - 1)
                if is_last and loop_visual and len(image_paths) > 1:
                    # Item 5b — loop visual: última cena usa imagem da cena 0
                    # (crossfade com img 0 seria ideal, mas usar direto já
                    # dá "rima visual" pro TikTok/Reels rewatch).
                    render_img = image_paths[0]

                # -t no OUTPUT (não no input). Sem -framerate no input;
                # senão o zoompan multiplica frames (d × n_input_frames).
                await _run_ffmpeg([
                    "-y", "-loop", "1", "-i", str(render_img),
                    "-vf", vf,
                    "-t", str(dur),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast", "-r", "30",
                    "-crf", "30",
                    "-tune", "stillimage",
                    str(out),
                ])

                # Item 14 — freeze frame: corta clip em 3 partes (pré/still/pós)
                if scene_freeze:
                    frozen = await self._apply_freeze_frame(
                        src=out, spec=scene_freeze, dur=dur, tmp=tmp_path, idx=i,
                    )
                    if frozen:
                        out = frozen
                        # Aumenta scene_duration local em freeze_duration
                        scene_durations[i] += scene_freeze["freeze_duration"]

                scene_clips.append(out)

            # 3) Concat dos clips — com xfade se `use_crossfade`, senão concat.
            concat_mp4 = tmp_path / "concat.mp4"
            if use_crossfade and len(scene_clips) > 1:
                await self._concat_with_xfade(
                    scene_clips, scene_durations, transition, concat_mp4
                )
            else:
                listfile = tmp_path / "concat.txt"
                listfile.write_text("\n".join(f"file '{p}'" for p in scene_clips))
                await _run_ffmpeg([
                    "-y", "-f", "concat", "-safe", "0",
                    "-i", str(listfile),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast", "-crf", "30",
                    str(concat_mp4),
                ])

            # 3.5) Se karaoke via ASS: aplica após concat (antes do audio mix).
            # Subtítulos ASS ficam por cima do vídeo concatenado, sem overlap.
            if ass_karaoke_path is not None:
                subbed = tmp_path / "with_subs.mp4"
                try:
                    await _run_ffmpeg([
                        "-y", "-i", str(concat_mp4),
                        "-vf", f"subtitles='{ass_karaoke_path}'",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-preset", "ultrafast", "-crf", "30",
                        "-c:a", "copy",
                        str(subbed),
                    ])
                    if subbed.exists() and subbed.stat().st_size > 0:
                        concat_mp4 = subbed
                except Exception:  # noqa: BLE001
                    pass  # silencioso — falha do ASS não quebra o render

            # ── Concat narrações per-scene com pads (item 4) ──
            final_narration: Path | None = audio_local
            has_multi_narration = (
                narration_urls
                and sum(1 for a in audio_per_scene if a is not None) > 1
            )
            if has_multi_narration:
                # Preenche cenas sem áudio com silent stubs (0.3s pads serão concat'd)
                full_audio_list: list[Path] = []
                for i in range(len(scenes)):
                    if audio_per_scene[i] is not None:
                        full_audio_list.append(audio_per_scene[i])  # type: ignore
                    else:
                        # Cria silêncio proporcional à cena
                        silent = tmp_path / f"silent_{i:02d}.mp3"
                        await _run_ffmpeg([
                            "-y", "-f", "lavfi",
                            "-i", "anullsrc=r=44100:cl=stereo",
                            "-t", "0.3", "-c:a", "libmp3lame", "-b:a", "96k",
                            str(silent),
                        ])
                        full_audio_list.append(silent)
                        # ffprobe = 0.3s
                        audio_duration_per_scene[i] = 0.3

                merged = tmp_path / "narration_merged.mp3"
                try:
                    await _concat_narrations_with_pads(
                        clips=full_audio_list,
                        durations_scene=scene_durations,
                        durations_audio=audio_duration_per_scene,
                        out=merged,
                    )
                    final_narration = merged
                except Exception as exc:  # noqa: BLE001
                    log.warning("concat_narrations falhou: %s — usa single", exc)
                    final_narration = audio_per_scene[0]

            # Mix de áudio: narração (merged ou single) + música (ducking) + SFX
            final = tmp_path / "final.mp4"
            await self._mix_audio(
                concat_mp4=concat_mp4,
                out=final,
                total_dur=int(round(total_video_dur)),
                narration=final_narration,
                music=music_path,
                hook_sfx=hook_sfx,
                trans_sfx=trans_sfx,
                scene_durations=[int(round(d)) for d in scene_durations],
            )

            # 5) Overlay de marca (opcional)
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
                except Exception:
                    pass

            # 6) Salva
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
            "style": style,
            "music": music_path.name if music_path else None,
            "karaoke": use_karaoke and bool(full_narration),
        }

    async def _build_karaoke_words(
        self,
        *,
        scenes: list[dict],
        audio_per_scene: list[Path | None],
        audio_durations: list[float],
        scene_durations: list[float],
        full_narration_fallback: str = "",
    ) -> list[dict]:
        """Item 1 — constrói word timings para karaoke.
        Estratégia híbrida:
          - Para cada cena com áudio disponível → faster-whisper (preciso)
          - Fallback: split uniforme (item 4)
        """
        starts = _cumulative_starts(scene_durations)
        out: list[dict] = []
        for i, sc in enumerate(scenes):
            text = (sc.get("narration") or "").strip()
            a_path = audio_per_scene[i]
            a_dur = audio_durations[i]
            if not text or a_dur <= 0.2:
                continue
            # Tenta whisper se áudio existe
            scene_words: list[dict] | None = None
            if a_path is not None and a_dur > 0.3:
                scene_words = await _whisper_words(a_path, language="pt")
            # Fallback: split uniforme
            if not scene_words:
                words = re.findall(r"\S+", text)
                if not words:
                    continue
                per_word = max(0.18, a_dur / len(words))
                t = 0.0
                scene_words = []
                for w in words:
                    scene_words.append({"text": w, "start": t, "end": t + per_word})
                    t += per_word
            # Ajusta pra timings absolutos (start_abs = starts[i] + word.start)
            start_abs = starts[i]
            for w in scene_words:
                out.append({
                    "text": w["text"],
                    "start": start_abs + float(w["start"]),
                    "end": start_abs + float(w["end"]),
                    "scene_index": i,
                })
        # Fallback global (sem cenas com narração)
        if not out and full_narration_fallback:
            total = sum(scene_durations)
            return _split_script_words(full_narration_fallback, total)
        return out

    async def _apply_freeze_frame(
        self, *, src: Path, spec: dict, dur: float, tmp: Path, idx: int,
    ) -> Path | None:
        """Item 14 — corta clip em 3 partes (pré-freeze, still+zoom, pós-freeze)
        e remonta. Retorna novo clip ou None se falhar."""
        try:
            freeze_at = float(spec.get("freeze_at", 1.5))
            freeze_dur = float(spec.get("freeze_duration", 0.8))
            freeze_zoom = float(spec.get("freeze_zoom", 1.15))

            if freeze_at < 0.3 or freeze_at >= dur - 0.3:
                return None

            # 1) pre-freeze: 0 → freeze_at
            pre = tmp / f"freeze_pre_{idx:02d}.mp4"
            await _run_ffmpeg([
                "-y", "-i", str(src),
                "-t", f"{freeze_at:.2f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                "-an", str(pre),
            ])

            # 2) still frame (frame no instante freeze_at, zoom aplicado)
            still_png = tmp / f"freeze_still_{idx:02d}.png"
            await _run_ffmpeg([
                "-y", "-ss", f"{freeze_at:.2f}", "-i", str(src),
                "-frames:v", "1", str(still_png),
            ])
            # Renderiza o still com zoom
            still_mp4 = tmp / f"freeze_still_{idx:02d}.mp4"
            await _run_ffmpeg([
                "-y", "-loop", "1", "-i", str(still_png),
                "-vf", f"scale=iw*{freeze_zoom:.2f}:ih*{freeze_zoom:.2f},"
                       f"crop=iw/{freeze_zoom:.2f}:ih/{freeze_zoom:.2f}",
                "-t", f"{freeze_dur:.2f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                "-r", "30", "-an", str(still_mp4),
            ])

            # 3) post-freeze: freeze_at → dur
            post = tmp / f"freeze_post_{idx:02d}.mp4"
            await _run_ffmpeg([
                "-y", "-ss", f"{freeze_at:.2f}", "-i", str(src),
                "-t", f"{max(0.1, dur - freeze_at):.2f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                "-an", str(post),
            ])

            # Concat
            listfile = tmp / f"freeze_concat_{idx:02d}.txt"
            listfile.write_text(
                f"file '{pre}'\nfile '{still_mp4}'\nfile '{post}'\n"
            )
            out = tmp / f"freeze_out_{idx:02d}.mp4"
            await _run_ffmpeg([
                "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "ultrafast", "-crf", "30",
                "-an", str(out),
            ])
            if out.exists() and out.stat().st_size > 0:
                return out
        except Exception as exc:  # noqa: BLE001
            log.warning("freeze frame falhou cena %d: %s", idx, exc)
        return None

    async def _concat_with_xfade(
        self,
        clips: list[Path],
        durations: list[int],
        transition: str,
        out: Path,
    ) -> None:
        """Concat com xfade entre clips. transition → escolhe tipo de
        transição ffmpeg (fade, fadeblack, slideleft, dissolve, etc.)."""
        # Map de transições do art-director para xfade presets
        xfade_map = {
            "crossfade_short": ("fade", 0.3),
            "crossfade_long": ("fade", 0.8),
            "fade_black": ("fadeblack", 1.0),
            "whip_pan": ("slideleft", 0.25),
            "zoom_blur": ("fadeblack", 0.4),
        }
        xf_type, xf_dur = xfade_map.get(transition, ("fade", 0.4))

        # Monta filter_complex: cada [i:v] entra num xfade cumulativo
        inputs = []
        for p in clips:
            inputs += ["-i", str(p)]

        # filter: v0 xfade v1 @ offset d0-xf_dur, resultado xfade v2 @ ...
        parts = []
        cumulative = durations[0]
        prev_label = "[0:v]"
        for i in range(1, len(clips)):
            next_label = f"[v{i}]"
            offset = max(0, cumulative - xf_dur)
            parts.append(
                f"{prev_label}[{i}:v]"
                f"xfade=transition={xf_type}:duration={xf_dur:.2f}:offset={offset:.2f}"
                f"{next_label}"
            )
            cumulative += durations[i] - xf_dur  # efeito do overlap
            prev_label = next_label
        filter_complex = ";".join(parts)

        final_out_label = f"v{len(clips)-1}"
        await _run_ffmpeg([
            "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[{final_out_label}]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "ultrafast", "-crf", "30",
            str(out),
        ])

    async def _mix_audio(
        self,
        concat_mp4: Path, out: Path, total_dur: int,
        narration: Path | None, music: Path | None,
        hook_sfx: Path | None, trans_sfx: Path | None,
        scene_durations: list[int],
    ) -> None:
        """Monta o mix de áudio final. Caminhos:
        - só narração → narração + padding
        - narração + música → ducking (música -18dB sob voz)
        - + SFX → adelay nos tempos certos
        - sem narração → só música (ou silêncio)
        """
        args = ["-y", "-i", str(concat_mp4)]
        filter_parts = []
        labels = []
        input_idx = 1  # 0 é o vídeo

        has_narr = narration and narration.exists() and narration.stat().st_size > 0
        has_music = music and music.exists() and music.stat().st_size > 0

        if has_narr:
            args += ["-i", str(narration)]
            # Só faz asplit (pro sidechain da música) se vamos USAR a música.
            # Senão, asplit cria output órfão e ffmpeg rejeita ("unconnected output").
            if has_music:
                filter_parts.append(
                    f"[{input_idx}:a]aformat=sample_fmts=s16:channel_layouts=stereo,apad,"
                    f"asplit=2[narr_mix][narr_side]"
                )
            else:
                filter_parts.append(
                    f"[{input_idx}:a]aformat=sample_fmts=s16:channel_layouts=stereo,apad"
                    f"[narr_mix]"
                )
            input_idx += 1
            labels.append(("narr_mix", 1.0))
        if has_music:
            args += ["-stream_loop", "-1", "-i", str(music)]
            vol = 0.12 if has_narr else 0.35
            filter_parts.append(
                f"[{input_idx}:a]aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"volume={vol}[mus_raw]"
            )
            if has_narr:
                # Sidechain compress: música duck pela narração (narr_side)
                filter_parts.append(
                    f"[mus_raw][narr_side]sidechaincompress=threshold=0.05:ratio=8:"
                    f"attack=5:release=400[mus]"
                )
            else:
                filter_parts.append("[mus_raw]acopy[mus]")
            input_idx += 1
            labels.append(("mus", 1.0))

        sfx_inputs = []
        if hook_sfx and hook_sfx.exists():
            args += ["-i", str(hook_sfx)]
            filter_parts.append(
                f"[{input_idx}:a]adelay=200|200,volume=0.5[sfx_hook]"
            )
            sfx_inputs.append("sfx_hook")
            input_idx += 1
        if trans_sfx and trans_sfx.exists() and len(scene_durations) > 1:
            # SFX swoosh 100ms antes de cada transição (menos a última)
            t = 0
            for si, dur in enumerate(scene_durations[:-1]):
                t += dur
                delay_ms = max(0, (t - 0.1) * 1000)
                args += ["-i", str(trans_sfx)]
                label = f"sfx_t{si}"
                filter_parts.append(
                    f"[{input_idx}:a]adelay={int(delay_ms)}|{int(delay_ms)},volume=0.35[{label}]"
                )
                sfx_inputs.append(label)
                input_idx += 1

        # Monta amix final
        if not has_narr and not has_music:
            # sem nada — só vídeo com trilha silenciosa
            await _run_ffmpeg([
                "-y", "-i", str(concat_mp4),
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
                "-shortest",
                str(out),
            ])
            return

        # Mix — os labels já têm nome próprio; referencia por nome
        mix_inputs = [l[0] for l in labels] + sfx_inputs
        n_mix = len(mix_inputs)
        inputs_str = "".join(f"[{name}]" for name in mix_inputs)
        filter_parts.append(
            f"{inputs_str}amix=inputs={n_mix}:duration=first:normalize=0[aout]"
        )

        filter_complex = ";".join(filter_parts)

        await _run_ffmpeg(args + [
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_dur),
            str(out),
        ])


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


_WHISPER_MODEL = None
_WHISPER_LOADED_SIZE: str | None = None


def _whisper_model(model_size: str = "tiny"):
    """Lazy load do faster-whisper. tiny é suficiente pra word timings
    em pt-BR (fala limpa); evita latência de 'small'/'medium'."""
    global _WHISPER_MODEL, _WHISPER_LOADED_SIZE
    if _WHISPER_MODEL is not None and _WHISPER_LOADED_SIZE == model_size:
        return _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel(
            model_size, device="cpu", compute_type="int8",
        )
        _WHISPER_LOADED_SIZE = model_size
        return _WHISPER_MODEL
    except Exception as exc:  # noqa: BLE001
        log.warning("faster-whisper indisponível: %s — karaoke fallback", exc)
        return None


async def _whisper_words(
    audio_path: Path, language: str = "pt",
) -> list[dict] | None:
    """Item 1 — usa faster-whisper pra extrair word-level timings.
    Retorna [{text, start, end}, ...] ou None se falhar."""
    model = _whisper_model(os.environ.get("WHISPER_MODEL_SIZE", "tiny"))
    if model is None:
        return None
    try:
        def _sync_transcribe():
            segments, _info = model.transcribe(
                str(audio_path),
                language=language,
                word_timestamps=True,
                beam_size=1,  # rápido
                vad_filter=False,
            )
            out = []
            for seg in segments:
                for w in (seg.words or []):
                    text = (w.word or "").strip()
                    if not text:
                        continue
                    out.append({
                        "text": text,
                        "start": float(w.start),
                        "end": float(w.end),
                    })
            return out
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_transcribe)
    except Exception as exc:  # noqa: BLE001
        log.warning("whisper transcribe falhou: %s", exc)
        return None


async def _ffprobe_duration(path: Path) -> float:
    """Retorna duração do áudio/vídeo em segundos via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return 0.0
    try:
        data = json.loads(out.decode())
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


async def _apply_atempo(src: Path, dst: Path, speed: float) -> Path:
    """Aplica atempo=speed (preserva pitch). Clamp 0.5-2.0 (filtro nativo);
    fora clampamos a 1.0 pra não distorcer."""
    if speed <= 0 or abs(speed - 1.0) < 0.001:
        # nada a fazer — copia
        dst.write_bytes(src.read_bytes())
        return dst
    if speed < 0.5 or speed > 2.0:
        dst.write_bytes(src.read_bytes())
        return dst
    await _run_ffmpeg([
        "-y", "-i", str(src),
        "-filter:a", f"atempo={speed:.3f}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(dst),
    ])
    return dst


async def _concat_narrations_with_pads(
    clips: list[Path],
    durations_scene: list[float],
    durations_audio: list[float],
    out: Path,
) -> None:
    """Concatena N mp3s com padding de silêncio por cena pra sincronizar
    com duração de cada scene. Cada narração começa no start da sua cena
    e é seguida de silêncio até o fim da cena.
    """
    # Usa concat demuxer com silence intercalado
    import subprocess
    n = len(clips)
    inputs: list[str] = []
    filter_parts: list[str] = []

    for i, clip in enumerate(clips):
        inputs += ["-i", str(clip)]

    # Gera silêncio para cada cena (pad = scene_dur - audio_dur, >=0)
    pad_durs = [max(0.0, durations_scene[i] - durations_audio[i]) for i in range(n)]

    # Prepara cada narração com pad via filter_complex:
    # [i:a]apad=pad_dur=X,atrim=0:scene_dur[a_i]
    filter_labels = []
    for i in range(n):
        scene_dur = durations_scene[i]
        pad = pad_durs[i]
        label = f"a{i}"
        # apad pad_dur em segundos: apad=whole_dur=<scene_dur>
        filter_parts.append(
            f"[{i}:a]aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"apad=whole_dur={scene_dur:.3f}[{label}]"
        )
        filter_labels.append(label)

    concat_inputs = "".join(f"[{l}]" for l in filter_labels)
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[aout]")

    filter_complex = ";".join(filter_parts)

    await _run_ffmpeg([
        "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out),
    ])


if __name__ == "__main__":
    port = int(os.environ.get("FFMPEG_LOCAL_PORT", 8105))
    FfmpegLocalWorker().run(port=port)
