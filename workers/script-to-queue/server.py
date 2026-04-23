"""script-to-queue worker.

Capability: `video.script_to_queue`. Porta 8119.

Converte um roteiro em texto livre num array JSON de cenas no formato
aceito pelo endpoint `/nqueues/import` do SkyReels V3. Usado como etapa 3
da recipe `roteiro-video` (depois de char_refs + voiceover).

Input:
  {
    "script": "... roteiro em pt-BR ...",
    "characters": [{"name": "...", "ref_image_url": "...", "voice_id": "..."}],
    "ambients":   [{"name": "...", "ref_image_url": "..."}],
    "voiceovers": [{"scene_idx": 0, "scene_label": "...", "audio_url": "...",
                    "character": "..."}],
    "style": "...",                    // direção visual global (opcional)
    "target_duration": 60,             // segundos totais (opcional)
    "aspect_ratio": "16:9",            // opcional, default "16:9"
    "resolution": "540P",              // opcional, default "540P"
    "project": "INETUSX"               // opcional
  }

Output:
  {
    "queue_json": [ ... cenas ... ],   // pronto pra POST /nqueues/import
    "queue_name": "...",
    "project":    "...",
    "scene_count": N,
    "unresolved_refs": [ ... ]         // nomes em ref_imgs sem match no input
  }
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json

SKILL_PATH = Path(__file__).parent / "SKILL.md"

VALID_TASKS = {
    "reference_to_video",
    "single_shot_extension",
    "shot_switching_extension",
    "talking_avatar",
}
VALID_RESOLUTIONS = {"480P", "540P", "720P"}
# talking_avatar só aceita 480P e 720P — se vier 540P, webui corrige,
# mas aqui já deixamos coerente pro output ser limpo.
TALKING_AVATAR_RESOLUTIONS = {"480P", "720P"}


class ScriptToQueueWorker(BaseWorker):
    name = "script-to-queue"
    capabilities = ("video.script_to_queue",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else ""

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        script = (payload.get("script") or "").strip()
        if not script:
            raise ValueError("script vazio — passe o roteiro em pt-BR")

        characters = _normalize_named(payload.get("characters") or [])
        ambients = _normalize_named(payload.get("ambients") or [])
        # Arrays paralelos por índice (usado pelas recipes do imkt4: fanout
        # do inemaimg produz outputs[*].image_url na mesma ordem do input).
        # Preenche ref_image_url faltante em characters/ambients por posição.
        _zip_urls_into(characters, payload.get("character_image_urls") or [])
        _zip_urls_into(ambients, payload.get("ambient_image_urls") or [])
        # voiceovers pode vir como lista de dicts OU duas listas paralelas
        # (voiceover_audio_urls + queue_json.scenes) dependendo da recipe.
        voiceovers = _normalize_voiceovers(
            payload.get("voiceovers") or [],
            extra_urls=payload.get("voiceover_audio_urls") or [],
        )
        style = (payload.get("style") or "").strip()
        target_duration = _safe_int(payload.get("target_duration"), default=0)
        aspect_ratio = (payload.get("aspect_ratio") or "16:9").strip()
        resolution = (payload.get("resolution") or "540P").strip()
        if resolution not in VALID_RESOLUTIONS:
            resolution = "540P"
        project = (payload.get("project") or "").strip()

        system = self._skill or _FALLBACK_SKILL

        user_payload = {
            "script": script,
            "characters": characters,
            "ambients": ambients,
            "voiceovers": voiceovers,
            "style": style,
            "target_duration": target_duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "project": project,
        }
        user_prompt = (
            "Receba o roteiro e contexto abaixo e devolva o JSON de cenas "
            "conforme o schema do SKILL.\n\n"
            f"```json\n{json.dumps(user_payload, ensure_ascii=False, indent=2)}\n```"
        )

        data = await complete_json(
            system_prompt=system, user_prompt=user_prompt, temperature=0.4,
        )

        raw_scenes = _coerce_scenes(data)
        if not raw_scenes:
            raise RuntimeError("LLM não retornou cena alguma")

        unresolved: list[str] = []
        queue_json: list[dict[str, Any]] = []
        for i, s in enumerate(raw_scenes):
            scene = _normalize_scene(
                s,
                idx=i,
                job_id=job.job_id,
                characters=characters,
                ambients=ambients,
                voiceovers=voiceovers,
                default_resolution=resolution,
                unresolved=unresolved,
            )
            queue_json.append(scene)

        queue_name = (data.get("queue_name") if isinstance(data, dict) else None) or ""
        if not queue_name:
            # Deriva do project ou do primeiro label
            if project:
                queue_name = f"{project} — {queue_json[0].get('label', 'Roteiro')}"
            else:
                queue_name = queue_json[0].get("label") or "Roteiro"

        return {
            "queue_json": queue_json,
            "queue_name": queue_name,
            "project": project,
            "scene_count": len(queue_json),
            "unresolved_refs": sorted(set(unresolved)),
        }


# ── helpers ──────────────────────────────────────────────────────────────

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _normalize_named(items: list[Any]) -> list[dict[str, Any]]:
    """Normaliza items [{name, ref_image_url?, voice_id?}, ...] e filtra
    entradas sem nome."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "desc": (it.get("desc") or "").strip(),
            "ref_image_url": (it.get("ref_image_url") or "").strip(),
            "voice_id": (it.get("voice_id") or "").strip(),
        })
    return out


def _zip_urls_into(items: list[dict[str, Any]], urls: list[Any]) -> None:
    """Preenche ref_image_url faltante em items[] pelos URLs em ordem.
    In-place. Usado com fanouts do imkt4 que produzem outputs paralelos."""
    for i, item in enumerate(items):
        if item.get("ref_image_url"):
            continue
        if i < len(urls) and urls[i]:
            item["ref_image_url"] = str(urls[i]).strip()


def _normalize_voiceovers(
    items: list[Any],
    extra_urls: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Normaliza voiceovers.
    - items: [{scene_idx?, scene_label?, audio_url, character?, text?}, ...]
    - extra_urls: lista paralela de urls (recipes fanout). Se fornecida e
      items tem mesmo tamanho, preenche audio_url faltante por posição.
    """
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        out.append({
            "scene_idx": it.get("scene_idx"),
            "scene_label": (it.get("scene_label") or "").strip(),
            "audio_url": (it.get("audio_url") or "").strip(),
            "character": (it.get("character") or "").strip(),
            "text": (it.get("text") or "").strip(),
        })
    extra_urls = extra_urls or []
    for i, vo in enumerate(out):
        if vo["audio_url"]:
            continue
        if i < len(extra_urls) and extra_urls[i]:
            vo["audio_url"] = str(extra_urls[i]).strip()
    return out


def _coerce_scenes(data: Any) -> list[dict[str, Any]]:
    """Aceita formatos: {scenes: [...]}, {queue_json: [...]}, ou lista crua."""
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    if isinstance(data, dict):
        for key in ("scenes", "queue_json", "jobs", "cenas"):
            v = data.get(key)
            if isinstance(v, list):
                return [s for s in v if isinstance(s, dict)]
    return []


def _resolve_ref(
    name: str,
    characters: list[dict[str, Any]],
    ambients: list[dict[str, Any]],
) -> str:
    """Dado um 'nome' vindo do LLM (ex.: 'Valen', 'Escola'), procura nas
    listas de characters/ambients e retorna o ref_image_url correspondente.
    Match case-insensitive sobre o primeiro nome. Retorna '' se não achar
    nem resolver como path literal (string já contendo `/` ou `.`)."""
    s = (name or "").strip()
    if not s:
        return ""
    # Já é path/URL
    if "/" in s or s.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4")):
        return s
    low = s.lower()
    for source in (characters, ambients):
        for item in source:
            item_name = item["name"].lower()
            if item_name == low or item_name.split()[0] == low.split()[0]:
                return item.get("ref_image_url", "") or ""
    return ""


def _voiceover_for(
    idx: int,
    label: str,
    voiceovers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Acha a narração pra uma cena via scene_idx (preferência) ou scene_label."""
    if not voiceovers:
        return None
    for vo in voiceovers:
        if not isinstance(vo, dict):
            continue
        vi = vo.get("scene_idx")
        if vi is not None and _safe_int(vi, -1) == idx:
            return vo
    label_low = (label or "").lower().strip()
    if not label_low:
        return None
    for vo in voiceovers:
        vl = (vo.get("scene_label") or "").lower().strip()
        if vl and (vl == label_low or vl in label_low or label_low in vl):
            return vo
    return None


def _deterministic_seed(job_id: str, scene_idx: int) -> int:
    """Seed estável pra (job_id, scene_idx). Entre 1 e 999999."""
    h = hashlib.sha256(f"{job_id}::{scene_idx}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 999_999 + 1


_SHOT_PREFIX_RE = re.compile(
    r"^\s*\[(?:ZOOM_IN_CUT|ZOOM_OUT_CUT|PAN_CUT|ANGLE_CUT|SHOT_CUT)\]", re.IGNORECASE
)


def _normalize_scene(
    raw: dict[str, Any],
    *,
    idx: int,
    job_id: str,
    characters: list[dict[str, Any]],
    ambients: list[dict[str, Any]],
    voiceovers: list[dict[str, Any]],
    default_resolution: str,
    unresolved: list[str],
) -> dict[str, Any]:
    """Valida, resolve refs e calcula defaults pra uma cena."""
    task_type = (raw.get("task_type") or "").strip()
    if task_type not in VALID_TASKS:
        # Fallback: se tem ref_imgs → R2V; se tem input_video → extension;
        # se tem input_audio + input_image → talking_avatar
        if raw.get("input_audio") and raw.get("input_image"):
            task_type = "talking_avatar"
        elif raw.get("input_video"):
            task_type = "single_shot_extension"
        else:
            task_type = "reference_to_video"

    label = (raw.get("label") or f"Cena {idx + 1}").strip()
    prompt = (raw.get("prompt") or "").strip()
    image_prompt = (raw.get("image_prompt") or "").strip()
    audio_text = (raw.get("audio_text") or "").strip()
    voice_id = (raw.get("voice_id") or "").strip()
    audio_bg = (raw.get("audio_bg") or "").strip()

    resolution = (raw.get("resolution") or default_resolution).strip()
    if resolution not in VALID_RESOLUTIONS:
        resolution = default_resolution
    if task_type == "talking_avatar" and resolution not in TALKING_AVATAR_RESOLUTIONS:
        resolution = "480P"

    duration = _safe_int(raw.get("duration"), default=5)
    duration = max(3, min(duration, 30))
    if task_type == "shot_switching_extension":
        duration = min(duration, 5)

    seed_in = _safe_int(raw.get("seed"), default=0)
    seed = seed_in if seed_in > 0 else _deterministic_seed(job_id, idx)

    scene: dict[str, Any] = {
        "task_type": task_type,
        "label": label,
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "seed": seed,
        "offload": True,
    }

    # talking_avatar pede low_vram (modelo 19B)
    if task_type == "talking_avatar":
        scene["low_vram"] = True
        scene["offload"] = False

    if image_prompt:
        scene["image_prompt"] = image_prompt
    if audio_text:
        scene["audio_text"] = audio_text
    if voice_id:
        scene["voice_id"] = voice_id
    if audio_bg:
        scene["audio_bg"] = audio_bg

    # ── ref_imgs resolution (reference_to_video) ──────────────────────
    if task_type == "reference_to_video":
        raw_refs = raw.get("ref_imgs") or []
        if isinstance(raw_refs, str):
            raw_refs = [r.strip() for r in raw_refs.split(",") if r.strip()]
        resolved = []
        for r in raw_refs[:4]:  # max 4
            name = str(r).strip()
            if not name:
                continue
            path = _resolve_ref(name, characters, ambients)
            if path:
                if path not in resolved:
                    resolved.append(path)
            else:
                # Referência desconhecida: mantém literal e registra
                if name not in resolved:
                    resolved.append(name)
                unresolved.append(name)
        scene["ref_imgs"] = resolved

    # ── extension: input_video ────────────────────────────────────────
    if task_type in ("single_shot_extension", "shot_switching_extension"):
        iv = (raw.get("input_video") or "").strip()
        scene["input_video"] = iv or "{{prev}}"
        # shot_switching_extension: força prefixo no prompt se ausente
        if task_type == "shot_switching_extension" and not _SHOT_PREFIX_RE.search(prompt):
            scene["prompt"] = f"[SHOT_CUT] {prompt}" if prompt else "[SHOT_CUT]"

    # ── talking_avatar: input_image + input_audio ─────────────────────
    if task_type == "talking_avatar":
        ii = (raw.get("input_image") or "").strip()
        if ii and not ("/" in ii or ii.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            # LLM mandou o nome do personagem em vez do path — resolver
            resolved = _resolve_ref(ii, characters, [])
            if resolved:
                ii = resolved
            else:
                unresolved.append(ii)
                ii = ""
        if not ii:
            # Fallback: retrato do personagem falante via voiceover
            vo = _voiceover_for(idx, label, voiceovers)
            char_name = (vo or {}).get("character", "") if vo else ""
            if char_name:
                ii = _resolve_ref(char_name, characters, []) or ""
        if not ii and characters:
            ii = characters[0].get("ref_image_url") or ""
        scene["input_image"] = ii

        ia = (raw.get("input_audio") or "").strip()
        if not ia:
            vo = _voiceover_for(idx, label, voiceovers)
            if vo:
                ia = (vo.get("audio_url") or "").strip()
                if not voice_id and vo.get("character"):
                    for c in characters:
                        if c["name"].lower() == vo["character"].lower() and c.get("voice_id"):
                            scene["voice_id"] = c["voice_id"]
                            break
        scene["input_audio"] = ia

    else:
        # Não-talking: auto-vincula input_audio da narração se existir e se
        # a cena tem audio_text explícito (o webui faz auto-mix).
        if audio_text:
            vo = _voiceover_for(idx, label, voiceovers)
            if vo and vo.get("audio_url"):
                scene["input_audio"] = vo["audio_url"]
                if not voice_id and vo.get("character"):
                    for c in characters:
                        if c["name"].lower() == vo["character"].lower() and c.get("voice_id"):
                            scene["voice_id"] = c["voice_id"]
                            break

    return scene


_FALLBACK_SKILL = (
    "Você é roteirista-técnico que converte roteiros em JSON de cenas pro "
    "SkyReels V3. Responda apenas com {\"scenes\": [...]} seguindo as convenções "
    "do pipeline. Veja workers/script-to-queue/SKILL.md para o schema completo."
)


if __name__ == "__main__":
    port = int(os.environ.get("SCRIPT_TO_QUEUE_PORT", 8119))
    ScriptToQueueWorker().run(port=port)
