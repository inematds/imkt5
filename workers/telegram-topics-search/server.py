"""telegram-topics-search worker.

Capability: `telegram.topics_search`. Porta 8118.

Busca offline no dataset já extraído pelo projeto `telegramtopicosindex`.
Lê JSONs direto do filesystem, indexa em memória, ranqueia por score.
Zero API Telegram — milissegundos de latência.

Complementa o `telegram-scraper` (online/MTProto) — use este pra
pesquisar o que já foi coletado.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from workers._base import BaseWorker  # noqa: E402

log = logging.getLogger("imkt4.workers.telegram-topics-search")

DEFAULT_ROOT = Path(
    os.environ.get("TG_TOPICS_DATA_DIR") or
    (Path(_ROOT).parent / "telegramtopicosindex" / "out").as_posix()
)

# Cache em memória. Chave: str(root). Valor: {index, last_refresh_mtime}
_INDEX_CACHE: dict[str, dict[str, Any]] = {}


def _scan_dataset(root: Path) -> dict[str, Any]:
    """Percorre <root>/<group>/<topic>/ e retorna estrutura indexada
    pronta pra query."""
    if not root.exists() or not root.is_dir():
        return {"groups": [], "topics": [], "root": str(root), "error": "root_not_found"}

    groups = []
    topics = []
    for group_dir in sorted(root.iterdir()):
        if not group_dir.is_dir():
            continue
        gmeta_path = group_dir / "grupo_metadata.json"
        gmeta: dict[str, Any] = {"grupo_id": group_dir.name, "titulo": group_dir.name}
        if gmeta_path.exists():
            try:
                gmeta = json.loads(gmeta_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("grupo_metadata.json inválido em %s: %s", group_dir, exc)

        group_id = str(gmeta.get("grupo_id") or group_dir.name)
        group_title = gmeta.get("titulo") or group_id
        topic_titles_by_id = {
            str(t.get("id")): t.get("title")
            for t in (gmeta.get("topicos") or [])
            if isinstance(t, dict)
        }

        groups.append({
            "group_id": group_id,
            "title": group_title,
            "total_topics_meta": gmeta.get("total_topicos"),
            "path": str(group_dir),
        })

        for topic_dir in sorted(group_dir.iterdir()):
            if not topic_dir.is_dir():
                continue
            topic_id = topic_dir.name
            meta_path = topic_dir / "metadata.json"
            msgs_path = topic_dir / "messages.json"

            topic_title = topic_titles_by_id.get(topic_id) or None
            total_messages = 0
            topic_creation_date = None
            if meta_path.exists():
                try:
                    tmeta = json.loads(meta_path.read_text(encoding="utf-8"))
                    topic_title = topic_title or tmeta.get("topic_title")
                    total_messages = int(tmeta.get("total_messages") or 0)
                    topic_creation_date = tmeta.get("topic_creation_date")
                except Exception as exc:  # noqa: BLE001
                    log.warning("metadata.json inválido em %s: %s", topic_dir, exc)

            messages = []
            if msgs_path.exists():
                try:
                    raw = json.loads(msgs_path.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        messages = raw
                    elif isinstance(raw, dict):
                        messages = raw.get("messages") or []
                except Exception as exc:  # noqa: BLE001
                    log.warning("messages.json inválido em %s: %s", topic_dir, exc)

            topics.append({
                "group_id": group_id,
                "group_title": group_title,
                "topic_id": topic_id,
                "topic_title": topic_title,
                "total_messages": total_messages or len(messages),
                "topic_creation_date": topic_creation_date,
                "messages": messages,
                "path": str(topic_dir),
            })

    return {
        "groups": groups,
        "topics": topics,
        "root": str(root),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_or_build_index(root: Path) -> dict[str, Any]:
    key = str(root)
    now = time.time()
    cached = _INDEX_CACHE.get(key)
    # Invalida se root mudou mtime (cheaper than re-scanning)
    try:
        root_mtime = root.stat().st_mtime if root.exists() else 0
    except OSError:
        root_mtime = 0
    if cached and cached.get("root_mtime") == root_mtime:
        # Ainda válido
        return cached["data"]
    log.info("Reindexando %s (mtime mudou ou cache frio)", root)
    t0 = time.time()
    data = _scan_dataset(root)
    elapsed = time.time() - t0
    _INDEX_CACHE[key] = {"data": data, "root_mtime": root_mtime, "built_at": now}
    log.info("Index pronto: %d topics em %d groups, %.1fms",
             len(data.get("topics", [])), len(data.get("groups", [])), elapsed * 1000)
    return data


def _score_topic(topic: dict, query: str, *, case_sensitive: bool,
                 search_in: set[str]) -> tuple[float, list[dict]]:
    """Score um tópico pra uma query + lista de mensagens que bateram."""
    flags = 0 if case_sensitive else re.IGNORECASE
    # escape query mas permite múltiplas palavras como OR
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    if not tokens:
        return 0.0, []
    patterns = [re.compile(re.escape(t), flags) for t in tokens]

    score = 0.0

    # 1) título (peso 3 por token que bate)
    title = topic.get("topic_title") or ""
    if "title" in search_in and title:
        for pat in patterns:
            if pat.search(title):
                score += 3.0

    matched_messages: list[dict] = []
    if "text" in search_in or "author" in search_in:
        for msg in topic.get("messages", []):
            match_in_msg = 0
            text = msg.get("text") or ""
            author = msg.get("author") or ""
            if "text" in search_in and text:
                for pat in patterns:
                    match_in_msg += len(pat.findall(text))
            if "author" in search_in and author:
                for pat in patterns:
                    if pat.search(author):
                        match_in_msg += 2
            if match_in_msg > 0:
                score += float(match_in_msg)
                # Gera snippet com highlight
                snippet = _make_snippet(text, patterns, max_chars=240)
                matched_messages.append({
                    "id": msg.get("id"),
                    "author": author,
                    "date": msg.get("date"),
                    "text": text[:500],  # trunca
                    "snippet_html": snippet,
                    "has_media": msg.get("has_media", False),
                    "media_type": msg.get("media_type"),
                    "hits": match_in_msg,
                })

    # Bonus por recência — baseado no topic_creation_date
    cd = topic.get("topic_creation_date")
    if cd:
        try:
            dt = datetime.fromisoformat(cd.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - dt).days
            if days < 30:
                score += 0.5
            elif days < 180:
                score += 0.2
        except (ValueError, AttributeError):
            pass

    return score, matched_messages


def _make_snippet(text: str, patterns: list[re.Pattern], max_chars: int = 240) -> str:
    """Gera snippet com <mark>…</mark> em volta de cada match."""
    if not text:
        return ""
    # Acha primeira ocorrência pra centralizar snippet
    first_hit = None
    for pat in patterns:
        m = pat.search(text)
        if m and (first_hit is None or m.start() < first_hit):
            first_hit = m.start()
    if first_hit is None:
        return text[:max_chars]
    start = max(0, first_hit - max_chars // 3)
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    # Escape HTML basic + mark
    snippet = (snippet.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
    for pat in patterns:
        snippet = pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", snippet)
    return snippet


class TelegramTopicsSearchWorker(BaseWorker):
    name = "telegram-topics-search"
    capabilities = ("telegram.topics_search",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        query = (payload.get("query") or "").strip()
        if not query:
            raise ValueError("payload.query obrigatório (string não-vazia)")

        root = Path(payload.get("root") or DEFAULT_ROOT).resolve()
        group_filter = payload.get("group_id")
        limit = int(payload.get("limit", 20))
        limit = max(1, min(limit, 200))
        include_messages = bool(payload.get("include_messages", True))
        case_sensitive = bool(payload.get("case_sensitive", False))
        search_in_raw = payload.get("search_in") or ["title", "text", "author"]
        search_in = set(s.lower() for s in search_in_raw
                        if s in ("title", "text", "author"))
        if not search_in:
            search_in = {"title", "text", "author"}

        index = _get_or_build_index(root)
        if index.get("error") == "root_not_found":
            return {
                "matches": [], "total_matches": 0,
                "groups_scanned": 0, "topics_scanned": 0,
                "query": query,
                "error": f"Dataset root não encontrado: {root}",
            }

        topics = index["topics"]
        if group_filter:
            topics = [t for t in topics if str(t["group_id"]) == str(group_filter)]

        scored: list[tuple[float, dict, list[dict]]] = []
        for topic in topics:
            score, matched_msgs = _score_topic(
                topic, query,
                case_sensitive=case_sensitive,
                search_in=search_in,
            )
            if score > 0:
                scored.append((score, topic, matched_msgs))

        # Ordena desc por score, tiebreak por topic_creation_date (desc)
        def _sort_key(item):
            score, topic, _ = item
            cd = topic.get("topic_creation_date") or ""
            return (-score, cd and cd[::-1])  # reverse str pra desc

        scored.sort(key=lambda x: (-x[0],
                                   -_date_ts(x[1].get("topic_creation_date"))))

        # Monta resultado
        matches = []
        for score, topic, matched_msgs in scored[:limit]:
            match = {
                "group_id": topic["group_id"],
                "group_title": topic["group_title"],
                "topic_id": topic["topic_id"],
                "topic_title": topic["topic_title"],
                "total_messages": topic["total_messages"],
                "matched_count": len(matched_msgs),
                "topic_creation_date": topic.get("topic_creation_date"),
                "score": round(score, 2),
            }
            if include_messages:
                # Ordena matched_msgs por hits desc
                matched_msgs.sort(key=lambda m: m["hits"], reverse=True)
                match["messages"] = matched_msgs[:10]  # top 10 msgs matched por tópico
            matches.append(match)

        return {
            "matches": matches,
            "total_matches": len(scored),
            "groups_scanned": len(index.get("groups", [])),
            "topics_scanned": len(topics),
            "query": query,
            "group_filter": group_filter,
            "index_root": str(root),
            "index_scanned_at": index.get("scanned_at"),
        }


def _date_ts(dstr: str | None) -> float:
    if not dstr:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(dstr).replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return 0.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    TelegramTopicsSearchWorker().run(host="0.0.0.0", port=8118)
