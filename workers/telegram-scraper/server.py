"""telegram-scraper worker.

Capability: `telegram.group_fetch`. Porta 8117.

Coleta mensagens de grupos Telegram via MTProto (telethon) usando
session de usuário. Full history + search nativo + state tracking
por (tenant, group) pra fetch incremental.

Setup: veja SKILL.md. Precisa rodar `scripts/tg_auth.py <phone> <tenant>`
uma vez antes de usar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
STATE_FILE = SESSION_DIR / "state.json"
_state_lock = asyncio.Lock()


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("state.json corrompido, resetando: %s", exc)
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_group_state(tenant: str, group_id: int) -> dict[str, Any]:
    s = _load_state()
    return s.get(tenant, {}).get(str(group_id), {})


async def _update_group_state(
    tenant: str, group_id: int, *, last_msg_id: int, fetched_n: int,
) -> dict[str, Any]:
    async with _state_lock:
        s = _load_state()
        tenant_s = s.setdefault(tenant, {})
        gs = tenant_s.setdefault(str(group_id), {})
        gs["last_message_id"] = max(int(gs.get("last_message_id", 0)), int(last_msg_id))
        gs["last_fetched_at"] = datetime.now(timezone.utc).isoformat()
        gs["total_fetched_lifetime"] = int(gs.get("total_fetched_lifetime", 0)) + int(fetched_n)
        _save_state(s)
        return gs


def _message_to_dict(msg, include_media: bool = False) -> dict[str, Any]:
    """Serializa um telethon Message pra dict JSON-safe."""
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

    sender = getattr(msg, "sender", None)
    from_id = None
    from_name = None
    if sender is not None:
        from_id = getattr(sender, "id", None)
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        from_name = (first + " " + last).strip() or getattr(sender, "username", None)

    reactions = {}
    raw_react = getattr(msg, "reactions", None)
    if raw_react and getattr(raw_react, "results", None):
        for r in raw_react.results:
            emoji = getattr(getattr(r, "reaction", None), "emoticon", None)
            count = getattr(r, "count", 0)
            if emoji and count:
                reactions[emoji] = count

    media_info: dict[str, Any] | None = None
    if include_media and getattr(msg, "media", None):
        m = msg.media
        if isinstance(m, MessageMediaPhoto):
            media_info = {"type": "photo"}
        elif isinstance(m, MessageMediaDocument):
            doc = getattr(m, "document", None)
            mime = getattr(doc, "mime_type", "") if doc else ""
            media_info = {"type": "document", "mime_type": mime}
        else:
            media_info = {"type": type(m).__name__}

    reply_to_id = None
    rt = getattr(msg, "reply_to", None)
    if rt is not None:
        reply_to_id = getattr(rt, "reply_to_msg_id", None)

    return {
        "id": int(msg.id),
        "date": msg.date.astimezone(timezone.utc).isoformat() if msg.date else None,
        "from_id": from_id,
        "from_name": from_name,
        "text": msg.message or "",
        "views": getattr(msg, "views", None) or 0,
        "forwards": getattr(msg, "forwards", None) or 0,
        "reply_to": reply_to_id,
        "reactions": reactions,
        "media": media_info,
    }


async def _resolve_entity(client, group: Any):
    """Aceita URL t.me, @username, ou id numérico. Retorna entity
    + metadata (id, title, username, members_count)."""
    if isinstance(group, str):
        g = group.strip()
        if g.startswith("https://t.me/") or g.startswith("http://t.me/"):
            g = g.rsplit("/", 1)[-1]
        if g.startswith("@"):
            g = g[1:]
        # Pode ser username ou numeric id
        try:
            g = int(g)
        except ValueError:
            pass
    else:
        g = group

    entity = await client.get_entity(g)
    title = getattr(entity, "title", None) or getattr(entity, "first_name", "") or str(entity.id)
    username = getattr(entity, "username", None)
    members = None
    try:
        full = await client.get_entity(entity)
        members = getattr(full, "participants_count", None)
    except Exception:  # noqa: BLE001
        pass
    return entity, {
        "id": int(entity.id),
        "title": title,
        "username": username,
        "members_count": members,
    }


class TelegramScraperWorker(BaseWorker):
    name = "telegram-scraper"
    capabilities = ("telegram.group_fetch",)

    async def handle(self, job) -> dict[str, Any]:
        from telethon import TelegramClient
        from telethon.errors import FloodWaitError

        payload = job.payload
        tenant = (payload.get("tenant_id") or job.tenant_id or "default").strip()
        group_raw = payload.get("group") or payload.get("group_link") or payload.get("chat_id")
        if not group_raw:
            raise ValueError("payload.group obrigatório (URL, @username ou id)")

        mode = (payload.get("mode") or "since_last").lower()
        if mode not in ("all", "search", "since_last"):
            raise ValueError(f"mode inválido: {mode}. Use all|search|since_last.")

        query = (payload.get("query") or "").strip()
        if mode == "search" and not query:
            raise ValueError("mode=search requer query não-vazio")

        limit = int(payload.get("limit", 200))
        limit = max(1, min(limit, 2000))  # clamp

        include_media = bool(payload.get("include_media", False))

        since_date = None
        sd_raw = payload.get("since_date")
        if sd_raw:
            try:
                since_date = datetime.fromisoformat(str(sd_raw).replace("Z", "+00:00"))
                if since_date.tzinfo is None:
                    since_date = since_date.replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise ValueError(f"since_date inválido (use ISO 8601): {exc}") from exc

        api_id = os.environ.get("TELEGRAM_API_ID")
        api_hash = os.environ.get("TELEGRAM_API_HASH")
        if not api_id or not api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID e TELEGRAM_API_HASH não configurados no .env."
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
                f"Session não-autorizada. Rode: python scripts/tg_auth.py +DDI_NUMERO {tenant}",
            )

        try:
            entity, group_meta = await _resolve_entity(client, group_raw)
            group_id = group_meta["id"]

            # State pra modo since_last
            state = _get_group_state(tenant, group_id)
            min_id = 0
            if mode == "since_last":
                min_id = int(state.get("last_message_id", 0))

            messages: list[dict[str, Any]] = []
            max_msg_id = min_id

            async def _iter_with_floodwait(kwargs):
                nonlocal messages, max_msg_id
                attempt = 0
                while attempt < 3:
                    try:
                        async for msg in client.iter_messages(entity, **kwargs):
                            if since_date and msg.date and msg.date < since_date:
                                break
                            if msg.id <= min_id and mode == "since_last":
                                break
                            messages.append(_message_to_dict(msg, include_media=include_media))
                            if msg.id > max_msg_id:
                                max_msg_id = msg.id
                            if len(messages) >= limit:
                                break
                        break
                    except FloodWaitError as fw:
                        attempt += 1
                        wait_s = min(int(fw.seconds) + 1, 120)
                        log.warning("FloodWait %ds (attempt %d)", wait_s, attempt)
                        await asyncio.sleep(wait_s)

            if mode == "search":
                await _iter_with_floodwait({"search": query, "limit": limit})
            else:
                # all ou since_last
                kwargs: dict[str, Any] = {"limit": limit}
                if mode == "since_last" and min_id > 0:
                    kwargs["min_id"] = min_id
                await _iter_with_floodwait(kwargs)

            new_state = await _update_group_state(
                tenant, group_id,
                last_msg_id=max_msg_id,
                fetched_n=len(messages),
            ) if messages else state

            return {
                "messages": messages,
                "count": len(messages),
                "group": group_meta,
                "state": new_state or {
                    "last_message_id": min_id,
                    "last_fetched_at": datetime.now(timezone.utc).isoformat(),
                    "total_fetched_lifetime": 0,
                },
                "mode": mode,
                "query": query if mode == "search" else None,
            }
        finally:
            await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    TelegramScraperWorker().run(host="0.0.0.0", port=8117)
