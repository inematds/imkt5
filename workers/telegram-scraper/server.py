"""telegram-scraper worker (v2 — baseado em extrator_rapido.py).

Capability: `telegram.group_fetch`. Porta 8117.

Extrai mensagens de grupos Telegram com tópicos via MTProto (telethon).
Reutiliza padrões testados do projeto telegramtopicosindex:
  - parse de link t.me/c/<grupo>/<topic>
  - GetForumTopicsRequest paginado pra listar tópicos
  - iter_messages(reply_to=topic_id) pra extrair mensagens de 1 tópico
  - download opcional de fotos + documentos com timeout
  - filtro por extensão
  - output compatível com telegram-topics-search

Setup 1×:
  1. API_ID + API_HASH em my.telegram.org
  2. python scripts/tg_auth.py +DDI <tenant>

4 modos:
  - list_topics    só lista, não extrai mensagens
  - extract_topic  extrai 1 tópico específico (link deve ter /topic_id)
  - extract_all    extrai todos os tópicos do grupo
  - incremental    pula tópicos que já existem em disco (só novos)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from workers._base import BaseWorker  # noqa: E402

log = logging.getLogger("imkt4.workers.telegram-scraper")

SESSION_DIR = Path(os.environ.get("TELEGRAM_SESSION_DIR", "./data/tg-sessions"))
DEFAULT_OUTPUT = Path(
    os.environ.get("TG_TOPICS_DATA_DIR") or
    (Path(_ROOT).parent / "telegramtopicosindex" / "out").as_posix()
)


# ────────────────────────────────────────────────────────────────
# Parse + helpers (copiados do extrator_rapido.py)
# ────────────────────────────────────────────────────────────────

def parse_telegram_link(link: str) -> tuple[int, int | None]:
    """Parse link t.me → (chat_id, topic_id opcional).

    Aceita:
      https://t.me/c/2238677701/3512  → (-1002238677701, 3512)
      https://t.me/c/2238677701       → (-1002238677701, None)
      t.me/c/2238677701/3512          → idem
      -1002238677701                  → idem (sem topic)
    """
    s = str(link).strip()
    # já é chat_id numérico?
    if s.lstrip("-").isdigit():
        return int(s), None
    clean = (s.replace("https://", "")
              .replace("http://", "")
              .replace("t.me/c/", ""))
    m = re.match(r"(\d+)(?:/(\d+))?", clean)
    if not m:
        raise ValueError(f"Link Telegram inválido: {link}")
    chat_id = -int(f"100{m.group(1)}")
    topic_id = int(m.group(2)) if m.group(2) else None
    return chat_id, topic_id


def internal_c_id(chat_id: int) -> str:
    """-1002517011104 → '2517011104' (usado em URLs t.me/c/)."""
    s = str(chat_id)
    return s[4:] if s.startswith("-100") else s.lstrip("-")


def _resolve_author(sender) -> str:
    if sender is None:
        return "Desconhecido"
    for attr in ("first_name", "title", "username"):
        v = getattr(sender, attr, None)
        if v:
            return v
    return "Desconhecido"


def _from_id_serializable(obj) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "user_id"):
        return obj.user_id
    if hasattr(obj, "channel_id"):
        return obj.channel_id
    return str(obj)


# ────────────────────────────────────────────────────────────────
# Extração de 1 tópico
# ────────────────────────────────────────────────────────────────

async def extrair_topico_individual(
    client,
    chat_id: int,
    topic_id: int,
    output_base_dir: Path,
    *,
    baixar_midia: bool = False,
    file_filter: list[str] | None = None,
    somidia: bool = False,
) -> dict[str, Any]:
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

    grupo_id = internal_c_id(chat_id)
    output_dir = output_base_dir / grupo_id / str(topic_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Extraindo tópico %s do grupo %s", topic_id, grupo_id)

    topic_message = await client.get_messages(chat_id, ids=topic_id)

    messages = []
    async for msg in client.iter_messages(chat_id, reply_to=topic_id):
        messages.append(msg)

    metadata = {
        "topic_id": topic_id,
        "chat_id": chat_id,
        "grupo_id": grupo_id,
        "total_messages": len(messages),
        "extraction_date": datetime.now(timezone.utc).isoformat(),
        "topic_title": (topic_message.message if topic_message else None) or None,
        "topic_creation_date": (
            topic_message.date.isoformat() if topic_message and topic_message.date else None
        ),
        "midia_baixada": baixar_midia or somidia,
    }

    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    media_count = 0
    text_messages: list[dict[str, Any]] = []
    filter_lower = [f.lower() for f in file_filter] if file_filter else None

    for i, msg in enumerate(messages, 1):
        try:
            msg_data = {
                "id": msg.id,
                "author": _resolve_author(getattr(msg, "sender", None)),
                "date": msg.date.isoformat() if msg.date else None,
                "text": msg.text or "",
                "has_media": bool(msg.media),
                "media_type": type(msg.media).__name__ if msg.media else None,
            }
            text_messages.append(msg_data)

            if msg.media and (baixar_midia or somidia):
                should_download = True
                file_ext = None
                if isinstance(msg.media, MessageMediaPhoto):
                    file_ext = "jpg"
                elif isinstance(msg.media, MessageMediaDocument):
                    doc = msg.media.document
                    for attr in doc.attributes:
                        if hasattr(attr, "file_name"):
                            parts = attr.file_name.rsplit(".", 1)
                            if len(parts) > 1:
                                file_ext = parts[1].lower()
                            break
                    if not file_ext and getattr(doc, "mime_type", None):
                        file_ext = doc.mime_type.split("/")[-1]

                if filter_lower and file_ext:
                    should_download = file_ext in filter_lower
                    if not should_download:
                        msg_data["media_skipped"] = f"filter: {file_ext}"

                if should_download:
                    try:
                        if isinstance(msg.media, MessageMediaPhoto):
                            filename = f"photo_{msg.id}_{i:03d}.jpg"
                            await asyncio.wait_for(
                                client.download_media(msg.media, str(output_dir / filename)),
                                timeout=60.0,
                            )
                            msg_data["media_file"] = filename
                            media_count += 1
                        elif isinstance(msg.media, MessageMediaDocument):
                            doc = msg.media.document
                            filename = None
                            for attr in doc.attributes:
                                if hasattr(attr, "file_name"):
                                    filename = attr.file_name
                                    break
                            if not filename:
                                ext = (doc.mime_type or "application/octet-stream").split("/")[-1]
                                filename = f"document_{msg.id}_{i:03d}.{ext}"
                            await asyncio.wait_for(
                                client.download_media(msg.media, str(output_dir / filename)),
                                timeout=120.0,
                            )
                            msg_data["media_file"] = filename
                            media_count += 1
                    except asyncio.TimeoutError:
                        msg_data["media_error"] = "timeout"
                    except Exception as exc:  # noqa: BLE001
                        msg_data["media_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            log.warning("Erro processando msg %d do tópico %s: %s", i, topic_id, exc)

    # Salva messages.json + content.txt (exceto modo somidia)
    if not somidia:
        (output_dir / "messages.json").write_text(
            json.dumps(text_messages, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        content_lines = [
            f"TOPICO {topic_id}",
            "=" * 50,
            "",
            f"Titulo: {(topic_message.message if topic_message else None) or 'Sem titulo'}",
            f"Criado em: {topic_message.date if topic_message else '-'}",
            "",
            f"Total de mensagens: {len(messages)}",
            f"Midias baixadas: {media_count}"
            if (baixar_midia or somidia) else "Midias NAO baixadas (apenas metadados)",
            "",
            "-" * 50,
            "",
        ]
        for i, md in enumerate(text_messages, 1):
            content_lines.extend([
                f"MENSAGEM {i}",
                f"Autor: {md['author']}",
                f"Data: {md['date']}",
            ])
            if md["text"]:
                content_lines.extend(["Texto:", md["text"]])
            else:
                content_lines.append("Texto: [Sem texto]")
            if md["has_media"]:
                mline = f"Midia: {md['media_type']}"
                if md.get("media_file"):
                    mline += f" -> {md['media_file']}"
                content_lines.append(mline)
            content_lines.extend(["", "-" * 30, ""])
        (output_dir / "content.txt").write_text(
            "\n".join(content_lines), encoding="utf-8",
        )

    return {
        "topic_id": topic_id,
        "topic_title": metadata["topic_title"],
        "path": str(output_dir),
        "messages_count": len(messages),
        "media_count": media_count,
    }


# ────────────────────────────────────────────────────────────────
# Listagem + extração de todos tópicos
# ────────────────────────────────────────────────────────────────

async def listar_topicos_grupo(client, chat_id: int) -> tuple[Any, list[dict]]:
    """Lista todos os tópicos do grupo fórum via GetForumTopicsRequest.
    Retorna (entity, lista de {id, title, date, from_id})."""
    from telethon.tl.functions.messages import GetForumTopicsRequest
    from telethon.tl.types import InputChannel

    entity = await client.get_entity(chat_id)
    input_channel = InputChannel(channel_id=entity.id, access_hash=entity.access_hash)

    seen_ids: set[int] = set()
    all_topics: list[dict[str, Any]] = []
    offset_topic = offset_id = offset_date = 0
    page = 1

    while page <= 50:  # limite de segurança
        try:
            result = await client(GetForumTopicsRequest(
                peer=input_channel,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=100,
            ))
        except Exception as exc:  # noqa: BLE001
            log.error("Erro na página %d de GetForumTopicsRequest: %s", page, exc)
            break

        if not result.topics:
            break

        new_count = 0
        for topic in result.topics:
            if topic.id in seen_ids:
                continue
            seen_ids.add(topic.id)
            new_count += 1
            all_topics.append({
                "id": topic.id,
                "title": topic.title,
                "date": topic.date.isoformat() if hasattr(topic, "date") and topic.date else None,
                "from_id": _from_id_serializable(getattr(topic, "from_id", None)),
            })

        if new_count == 0:
            break

        last = result.topics[-1]
        offset_topic = offset_id = last.id
        offset_date = int(last.date.timestamp()) if hasattr(last, "date") and last.date else 0
        page += 1

    return entity, all_topics


async def extrair_todos_topicos(
    client,
    chat_id: int,
    output_base_dir: Path,
    *,
    max_topics: int | None = None,
    baixar_midia: bool = False,
    file_filter: list[str] | None = None,
    somidia: bool = False,
    incremental: bool = False,
) -> dict[str, Any]:
    entity, all_topics = await listar_topicos_grupo(client, chat_id)
    grupo_id = internal_c_id(chat_id)
    grupo_dir = output_base_dir / grupo_id
    grupo_dir.mkdir(parents=True, exist_ok=True)

    grupo_metadata = {
        "grupo_id": grupo_id,
        "chat_id": chat_id,
        "titulo": entity.title,
        "total_topicos": len(all_topics),
        "extraction_date": datetime.now(timezone.utc).isoformat(),
        "midia_baixada": baixar_midia or somidia,
        "topicos": all_topics,
    }
    (grupo_dir / "grupo_metadata.json").write_text(
        json.dumps(grupo_metadata, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    topics_to_extract = all_topics[:max_topics] if max_topics else all_topics
    extracted = []
    skipped = []
    failed = []

    for i, topic in enumerate(topics_to_extract, 1):
        topic_id = topic["id"]
        target_dir = grupo_dir / str(topic_id)
        if incremental and (target_dir / "metadata.json").exists():
            skipped.append({"id": topic_id, "title": topic["title"]})
            continue
        try:
            log.info("[%d/%d] Tópico %s: %s",
                     i, len(topics_to_extract), topic_id, topic["title"])
            result = await extrair_topico_individual(
                client, chat_id, topic_id, output_base_dir,
                baixar_midia=baixar_midia,
                file_filter=file_filter,
                somidia=somidia,
            )
            extracted.append(result)
        except Exception as exc:  # noqa: BLE001
            log.error("Falha no tópico %s: %s", topic_id, exc)
            failed.append({
                "id": topic_id,
                "title": topic["title"],
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {
        "group": {
            "id": int(entity.id),
            "chat_id": chat_id,
            "title": entity.title,
            "internal_id": grupo_id,
        },
        "topics_listed": len(all_topics),
        "topics_extracted": len(extracted),
        "topics_skipped": len(skipped),
        "topics_failed": failed,
        "extracted": extracted,
        "skipped": skipped,
        "output_dir": str(grupo_dir),
        "extraction_date": grupo_metadata["extraction_date"],
    }


# ────────────────────────────────────────────────────────────────
# Worker
# ────────────────────────────────────────────────────────────────

class TelegramScraperWorker(BaseWorker):
    name = "telegram-scraper"
    capabilities = ("telegram.group_fetch",)

    async def handle(self, job) -> dict[str, Any]:
        from telethon import TelegramClient

        payload = job.payload
        tenant = (payload.get("tenant_id") or job.tenant_id or "default").strip()

        group_link = (
            payload.get("group_link")
            or payload.get("group")
            or payload.get("chat_id")
        )
        if not group_link:
            raise ValueError(
                "payload.group_link obrigatório. Aceita:\n"
                "  - URL t.me/c/<grupo>[/<topic>]\n"
                "  - chat_id numérico (-100...)",
            )
        chat_id, link_topic_id = parse_telegram_link(str(group_link))

        mode = (payload.get("mode") or "extract_all").lower()
        if mode not in ("list_topics", "extract_topic", "extract_all", "incremental"):
            raise ValueError(
                f"mode inválido: {mode}. "
                "Use: list_topics | extract_topic | extract_all | incremental",
            )

        # modo extract_topic requer topic_id (do link OU do payload)
        topic_id = link_topic_id
        if payload.get("topic_id"):
            topic_id = int(payload["topic_id"])
        if mode == "extract_topic" and topic_id is None:
            raise ValueError(
                "mode=extract_topic requer topic_id (no link t.me/c/X/Y "
                "ou no payload.topic_id)",
            )

        output_dir = Path(payload.get("output_dir") or DEFAULT_OUTPUT).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        max_topics = payload.get("max_topics")
        if max_topics is not None:
            max_topics = int(max_topics)
            if max_topics < 1:
                max_topics = None

        baixar_midia = bool(payload.get("baixar_midia", False))
        somidia = bool(payload.get("somidia", False))
        file_filter = payload.get("file_filter") or None
        if file_filter and not isinstance(file_filter, list):
            raise ValueError("file_filter deve ser uma lista (ex: ['pdf','jpg'])")

        # Telegram auth
        api_id = os.environ.get("TELEGRAM_API_ID")
        api_hash = os.environ.get("TELEGRAM_API_HASH")
        if not api_id or not api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID + TELEGRAM_API_HASH não configurados no .env",
            )
        try:
            api_id_int = int(api_id)
        except ValueError as exc:
            raise RuntimeError(f"TELEGRAM_API_ID inválido: {api_id}") from exc

        session_path = SESSION_DIR / tenant
        if not Path(str(session_path) + ".session").exists():
            raise RuntimeError(
                f"Session file não existe: {session_path}.session\n"
                f"Rode: python scripts/tg_auth.py +DDI_NUMERO {tenant}",
            )

        client = TelegramClient(str(session_path), api_id_int, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                f"Session não-autorizada. "
                f"Rode: python scripts/tg_auth.py +DDI_NUMERO {tenant}",
            )

        try:
            if mode == "list_topics":
                entity, topics = await listar_topicos_grupo(client, chat_id)
                grupo_id = internal_c_id(chat_id)
                grupo_dir = output_dir / grupo_id
                grupo_dir.mkdir(parents=True, exist_ok=True)
                grupo_metadata = {
                    "grupo_id": grupo_id,
                    "chat_id": chat_id,
                    "titulo": entity.title,
                    "total_topicos": len(topics),
                    "extraction_date": datetime.now(timezone.utc).isoformat(),
                    "midia_baixada": False,
                    "topicos": topics,
                }
                (grupo_dir / "grupo_metadata.json").write_text(
                    json.dumps(grupo_metadata, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return {
                    "mode": "list_topics",
                    "group": {
                        "id": int(entity.id),
                        "chat_id": chat_id,
                        "title": entity.title,
                        "internal_id": grupo_id,
                    },
                    "topics_count": len(topics),
                    "topics": topics[:100],  # preview
                    "topics_truncated": len(topics) > 100,
                    "output_dir": str(grupo_dir),
                }

            if mode == "extract_topic":
                result = await extrair_topico_individual(
                    client, chat_id, topic_id, output_dir,
                    baixar_midia=baixar_midia,
                    file_filter=file_filter,
                    somidia=somidia,
                )
                return {
                    "mode": "extract_topic",
                    "group": {
                        "chat_id": chat_id,
                        "internal_id": internal_c_id(chat_id),
                    },
                    "topic": result,
                    "output_dir": str(output_dir / internal_c_id(chat_id)),
                }

            # extract_all ou incremental
            return await extrair_todos_topicos(
                client, chat_id, output_dir,
                max_topics=max_topics,
                baixar_midia=baixar_midia,
                file_filter=file_filter,
                somidia=somidia,
                incremental=(mode == "incremental"),
            ) | {"mode": mode}
        finally:
            await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    TelegramScraperWorker().run(host="0.0.0.0", port=8117)
