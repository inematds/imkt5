"""LLM client compartilhado — chain local-first Ollama → OpenRouter.

Usado pelos workers de texto (creative-brief, copywriter, ad-designer).
Cada worker não precisa saber sobre provider — só chama `complete_json(...)`
e recebe dict estruturado.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("imkt4.workers.llm")


async def complete_json(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Completa prompt e devolve JSON parseado.

    Estratégia: tenta Ollama local primeiro (format=json nativo), cai pro
    OpenRouter se Ollama falhar. Se ambos falharem, raise.
    """
    errors: list[str] = []

    # 1) Ollama local (format=json garante output estruturado)
    try:
        return await _call_ollama(system_prompt, user_prompt, temperature, max_tokens)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ollama: {exc}")
        log.info("ollama falhou (%s); tentando OpenRouter", exc)

    # 2) OpenRouter
    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            return await _call_openrouter(system_prompt, user_prompt, temperature, max_tokens)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"openrouter: {exc}")

    raise RuntimeError(f"todos providers LLM falharam: {'; '.join(errors)}")


async def complete_text(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.5,
    max_tokens: int | None = None,
) -> str:
    """Completa prompt texto livre (sem forçar JSON). Mesma chain."""
    errors: list[str] = []
    try:
        d = await _call_ollama(system_prompt, user_prompt, temperature, max_tokens, json_mode=False)
        return str(d.get("content", "")) if isinstance(d, dict) else str(d)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ollama: {exc}")

    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            d = await _call_openrouter(system_prompt, user_prompt, temperature, max_tokens, json_mode=False)
            return str(d.get("content", "")) if isinstance(d, dict) else str(d)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"openrouter: {exc}")

    raise RuntimeError(f"todos providers LLM falharam: {'; '.join(errors)}")


# ── providers internos ────────────────────────────────────────────────

async def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int | None,
    *, json_mode: bool = True,
) -> dict[str, Any]:
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_ROUTER_MODEL") or os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": temperature},
        "stream": False,
    }
    if json_mode:
        body["format"] = "json"
    if max_tokens:
        body["options"]["num_predict"] = max_tokens

    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(f"{url}/api/chat", json=body)
        r.raise_for_status()
        data = r.json()

    content = data.get("message", {}).get("content", "")
    if not json_mode:
        return {"content": content}
    return _safe_json_parse(content)


async def _call_openrouter(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int | None,
    *, json_mode: bool = True,
) -> dict[str, Any]:
    key = os.environ["OPENROUTER_API_KEY"]
    url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = os.environ.get("OPENROUTER_MODEL_DEFAULT", "google/gemini-2.0-flash-exp:free")

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{url}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://github.com/inematds/imkt4",
                "X-Title": "imkt4 worker",
            },
            json=body,
        )
        r.raise_for_status()
        data = r.json()

    content = data["choices"][0]["message"]["content"]
    if not json_mode:
        return {"content": content}
    return _safe_json_parse(content)


def _safe_json_parse(s: str) -> dict[str, Any]:
    s = (s or "").strip()
    # remover cercas ```json ... ```
    if s.startswith("```"):
        s = s.strip("`").lstrip("json").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"resposta LLM não é JSON válido: {s[:200]}") from exc


# ── carrega knowledge do tenant ───────────────────────────────────────
def load_tenant_knowledge(tenant_id: str, files: list[str] | None = None) -> str:
    """Carrega profiles/<tenant>/knowledge/*.md e concatena.

    `files` opcional filtra por nome (ex.: ["brand_identity.md"]).
    """
    from pathlib import Path
    root = Path("profiles") / tenant_id / "knowledge"
    if not root.exists():
        return ""
    mds = sorted(root.glob("*.md"))
    if files:
        mds = [p for p in mds if p.name in files]
    out = []
    for p in mds:
        out.append(f"=== {p.name} ===\n{p.read_text().strip()}")
    return "\n\n".join(out)
