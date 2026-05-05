"""ChannelNotifier — entrega de resultado de job ao canal de origem.

Quando um job completa com sucesso e veio de um canal registrado
(telegram, whatsapp, web), inspeciona o output em busca de URLs de
artefato (imagem, áudio, vídeo, documento) e envia como anexo pelo
canal. Se não tem artefato, envia mensagem de texto.

É a peça que implementa o delivery mode "chat" automático.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from imkt5.channels.base import ChannelRegistry
from imkt5.types.messages import (
    AttachmentKind,
    MessageAttachment,
    OutgoingMessage,
)
from imkt5.types.tenants import ChannelKind

log = logging.getLogger("imkt5.delivery")

_IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp|gif)($|\?)", re.I)
_VIDEO_EXT = re.compile(r"\.(mp4|mov|webm|mkv)($|\?)", re.I)
_AUDIO_EXT = re.compile(r"\.(mp3|wav|ogg|m4a|flac)($|\?)", re.I)


class ChannelNotifier:
    """Escuta término de jobs e entrega resultados no canal de origem."""

    def __init__(self, channels: ChannelRegistry) -> None:
        self._channels = channels

    async def deliver(
        self,
        *,
        job_id: str,
        tenant_id: str,
        user_id: str,
        origin_channel: str,
        origin_external_id: str,
        output: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        if not origin_external_id:
            return   # sem canal, nada a fazer

        try:
            kind = ChannelKind(origin_channel)
        except ValueError:
            return   # canal não é TG/WA/Web (ex.: "web" da UI consulta via polling)

        if kind == ChannelKind.WEB:
            return   # UI web consulta /jobs, não precisa push

        # Resolve canal registrado
        try:
            channel = self._channels.get(kind)
        except KeyError:
            log.debug("delivery: canal %s não registrado", kind)
            return

        if error:
            text = f"❌ Job falhou: {error[:400]}"
            attachments: tuple[MessageAttachment, ...] = ()
        else:
            text, attachments = _compose_output(output or {})

        try:
            await channel.send(
                OutgoingMessage(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    channel=kind,
                    channel_external_id=origin_external_id,
                    text=text,
                    attachments=attachments,
                )
            )
        except Exception as exc:   # noqa: BLE001
            log.warning("delivery: falhou enviar pra %s %s: %s",
                        kind.value, origin_external_id, exc)


def _compose_output(
    output: dict[str, Any],
) -> tuple[str, tuple[MessageAttachment, ...]]:
    """Extrai anexos do output e monta texto resumido."""
    attachments: list[MessageAttachment] = []
    text_parts: list[str] = []

    # Varre o output buscando URLs
    _collect_attachments(output, attachments)

    if not attachments:
        # Sem URLs — devolve resumo em texto
        summary = _summarize_output(output)
        return summary, ()

    # Com anexos: texto curto descrevendo
    if len(attachments) == 1:
        text_parts.append("✅ Pronto!")
    else:
        text_parts.append(f"✅ Pronto — {len(attachments)} arquivos.")

    # Metadata útil
    if "model_used" in output:
        text_parts.append(f"modelo: `{output['model_used']}`")
    if "generation_time_s" in output:
        text_parts.append(f"gerou em {output['generation_time_s']:.1f}s")
    if "duration_seconds" in output:
        text_parts.append(f"duração: {output['duration_seconds']}s")

    return " · ".join(text_parts), tuple(attachments)


def _collect_attachments(
    obj: Any, out: list[MessageAttachment], depth: int = 0,
) -> None:
    """Walk recursivo do output, extrai qualquer string URL/path de mídia."""
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            # keys comuns
            if isinstance(v, str) and _looks_like_url(v):
                att = _classify(v, k)
                if att is not None:
                    out.append(att)
                    continue
            _collect_attachments(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_attachments(item, out, depth + 1)


def _looks_like_url(s: str) -> bool:
    return (
        s.startswith("file://")
        or s.startswith("/artifacts/")
        or s.startswith("/s3/")
        or s.startswith("http://")
        or s.startswith("https://")
        or s.startswith("s3://")
    )


def _classify(url: str, key_hint: str = "") -> MessageAttachment | None:
    kh = key_hint.lower()

    if _IMAGE_EXT.search(url) or "image" in kh:
        return MessageAttachment(kind=AttachmentKind.IMAGE, storage_path=url)
    if _VIDEO_EXT.search(url) or "video" in kh:
        return MessageAttachment(kind=AttachmentKind.VIDEO, storage_path=url)
    if _AUDIO_EXT.search(url) or "audio" in kh:
        return MessageAttachment(kind=AttachmentKind.AUDIO, storage_path=url)
    # Ignora URLs que não parecem mídia (ex.: "url" de resultado Tavily)
    if url.startswith(("file://", "/artifacts/", "/s3/")):
        return MessageAttachment(kind=AttachmentKind.DOCUMENT, storage_path=url)
    return None


def _summarize_output(output: dict[str, Any]) -> str:
    """Texto amigável quando não há arquivo pra enviar."""
    if not output:
        return "✅ Concluído."

    # research.market → mostra só os títulos
    if "queries_run" in output and "results" in output:
        lines = ["✅ Pesquisa concluída:"]
        for q, items in (output.get("results") or {}).items():
            lines.append(f"\n**{q}**")
            for it in (items or [])[:3]:
                t = it.get("title", "")
                u = it.get("url", "")
                lines.append(f"- {t[:70]}  —  {u[:60]}")
        return "\n".join(lines)[:3500]

    # review.auto → decisão
    if "decision" in output:
        dec = output["decision"]
        reason = output.get("reason", "")
        emoji = {"approved": "✅", "rejected": "❌", "uncertain": "❓"}.get(dec, "ℹ️")
        return f"{emoji} {dec.upper()} — {reason[:300]}"

    # fallback: json truncado
    import json
    return f"✅ Concluído:\n```\n{json.dumps(output, ensure_ascii=False)[:800]}\n```"
