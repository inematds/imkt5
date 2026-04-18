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
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

ASSETS_DIR = Path(__file__).parent / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR = ASSETS_DIR / "sfx"


def _select_music(genre: str | None) -> Path | None:
    """Retorna trilha local pra um mood. Fallbacks progressivos."""
    if not genre:
        return None
    g = genre.lower().strip()
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

    # Karaoke ganha prioridade sobre text_overlay simples
    if karaoke:
        vf = f"{vf},{_build_karaoke_draw(karaoke, duration, width, height)}"
    elif (scene.get("text_overlay") or "").strip():
        vf = f"{vf},{_build_text_overlay(scene, width, height, tmp, idx)}"

    return vf


def _build_text_overlay(scene: dict, width: int, height: int, tmp: Path, idx: int) -> str:
    """Text overlay tradicional (fallback quando sem karaoke)."""
    overlay = (scene.get("text_overlay") or "").strip()
    font_size = int(scene.get("font_size", 88))

    pad_side = int(width * 0.08)
    usable_w = width - 2 * pad_side
    avg_char_w = font_size * 0.6
    max_chars_per_line = max(8, int(usable_w / avg_char_w))

    import textwrap as _tw
    wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
    n_lines = wrapped.count("\n") + 1
    if n_lines > 3:
        font_size = max(44, int(font_size * 3 / n_lines))
        avg_char_w = font_size * 0.6
        max_chars_per_line = max(8, int(usable_w / avg_char_w))
        wrapped = _tw.fill(overlay.upper(), width=max_chars_per_line)
        n_lines = wrapped.count("\n") + 1

    txt_path = tmp / f"text_{idx:02d}.txt"
    txt_path.write_text(wrapped, encoding="utf-8")

    position = scene.get("text_position", "top")
    block_h = int(font_size * 1.25 * n_lines)
    margin_y = int(height * 0.08)
    if position == "top":
        y_box = margin_y
    elif position == "center":
        y_box = (height - block_h) // 2
    else:
        y_box = height - block_h - margin_y

    box_pad_y = int(font_size * 0.6)
    box_x = pad_side
    box_w = width - 2 * pad_side
    box_y = y_box - box_pad_y
    box_full_h = block_h + box_pad_y * 2
    opacity = scene.get("overlay_opacity", 0.55)
    line_spacing = int(font_size * 0.2)
    return (
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


def _escape_drawtext(text: str) -> str:
    """Escapa caracteres especiais do drawtext (aspas, backslash, %, :)."""
    return (text.replace("\\", "\\\\").replace("'", "\\'")
            .replace(":", "\\:").replace("%", "\\%"))


def _build_karaoke_draw(words: list[dict], duration: int, width: int, height: int) -> str:
    """Renderiza palavras uma por uma via drawtext encadeado, cada uma com
    `enable='between(t,start,end)'`. `words` = [{text, start, end}, ...] (tempos relativos à cena).
    Palavra ativa em amarelo brilhante, fundo preto semi-transparente sob a linha.
    """
    if not words:
        return ""
    font_size = max(70, int(height * 0.045))
    y_pos = int(height * 0.72)  # parte inferior mas com margem
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
        narration_url = payload.get("narration_url") or plan.get("narration_file")
        full_narration = plan.get("full_narration") or plan.get("narration_script") or ""

        # Novos campos vindos do video-art-director
        music_genre = (payload.get("music_genre") or plan.get("music_genre") or "").strip()
        style = (payload.get("style") or plan.get("art_direction", {}).get("style") or "").strip()
        hook_pattern = (payload.get("hook_pattern") or plan.get("hook_pattern") or "").strip()
        # Default True; trata explicit None como default também (vem da recipe
        # quando user não informa; payload.get retorna None, não default).
        use_sfx = payload.get("use_sfx")
        use_sfx = True if use_sfx is None else bool(use_sfx)
        use_karaoke = payload.get("use_karaoke")
        use_karaoke = True if use_karaoke is None else bool(use_karaoke)

        # Fase 2: crossfade + color grading opt-in (ativados por video_mode="pro")
        video_mode = (payload.get("video_mode") or "").lower()
        use_crossfade = video_mode == "pro" or bool(payload.get("use_crossfade"))
        use_color_grading = video_mode == "pro" or bool(payload.get("use_color_grading"))

        # Transition do art-director vira crossfade se pro mode
        transition = (payload.get("transition") or plan.get("transition") or "cut").strip()

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

            audio_local: Path | None = None
            if narration_url:
                audio_local = tmp_path / "narration.mp3"
                try:
                    await _fetch_to(narration_url, audio_local)
                except Exception:
                    audio_local = None

            # Timings de karaoke — divide palavras do full_narration pelo total de duração.
            scene_durations = [max(1, int(sc.get("duration", 3))) for sc in scenes]
            total_video_dur = sum(scene_durations)
            karaoke_by_scene: list[list[dict] | None] = [None] * len(scenes)
            if use_karaoke and full_narration:
                all_words = _split_script_words(full_narration, total_video_dur)
                # distribui palavras proporcionalmente por cena baseada em duração
                t = 0.0
                idx_w = 0
                for si, dur in enumerate(scene_durations):
                    scene_end = t + dur
                    scene_words = []
                    while idx_w < len(all_words) and all_words[idx_w]["start"] < scene_end:
                        w = all_words[idx_w]
                        scene_words.append({
                            "text": w["text"],
                            "start": max(0.0, w["start"] - t),
                            "end": min(dur, w["end"] - t),
                        })
                        idx_w += 1
                    karaoke_by_scene[si] = scene_words if scene_words else None
                    t = scene_end

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

                vf = _build_vf(
                    sc, width, height, dur, tmp_path, i,
                    is_hook=(i == 0 and hook_pattern in ("pattern_interrupt", "stat_shot")),
                    karaoke=karaoke_by_scene[i],
                    color_grade=grade,
                )
                # -t no OUTPUT (não no input). Sem -framerate no input;
                # senão o zoompan multiplica frames (d × n_input_frames).
                await _run_ffmpeg([
                    "-y", "-loop", "1", "-i", str(img_path),
                    "-vf", vf,
                    "-t", str(dur),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast", "-r", "30",
                    "-crf", "30",
                    "-tune", "stillimage",
                    str(out),
                ])
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

            # 4) Mix de áudio: narração + música (ducking) + SFX
            final = tmp_path / "final.mp4"
            await self._mix_audio(
                concat_mp4=concat_mp4,
                out=final,
                total_dur=total_video_dur,
                narration=audio_local,
                music=music_path,
                hook_sfx=hook_sfx if (i == 0) else None,
                trans_sfx=trans_sfx,
                scene_durations=scene_durations,
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
            # Narração precisa ser split: uma vai pro sidechain da música,
            # outra vai pro amix final. asplit cria [narr_mix] e [narr_side].
            filter_parts.append(
                f"[{input_idx}:a]aformat=sample_fmts=s16:channel_layouts=stereo,apad,"
                f"asplit=2[narr_mix][narr_side]"
            )
            input_idx += 1
            # narr_mix vai pro amix final, narr_side é sidechain
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


if __name__ == "__main__":
    port = int(os.environ.get("FFMPEG_LOCAL_PORT", 8105))
    FfmpegLocalWorker().run(port=port)
