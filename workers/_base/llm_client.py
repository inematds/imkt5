"""LLM client compartilhado — chain configurável Claude Code → Ollama → OpenRouter.

Usado pelos workers de texto (creative-brief, copywriter, ad-designer).
Cada worker não precisa saber sobre provider — só chama `complete_json(...)`
e recebe dict estruturado.

Ordem padrão definida por env `LLM_PROVIDER_ORDER` (csv). Default:
`claude_code,ollama,openrouter`. Providers sem credencial são pulados.
`claude_code` usa o Claude Agent SDK que invoca o CLI `claude` já logado
em `~/.claude/` — sem API key separada.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("imkt5.workers.llm")


def _provider_order() -> list[str]:
    raw = os.environ.get("LLM_PROVIDER_ORDER", "claude_code,ollama,openrouter")
    return [p.strip() for p in raw.split(",") if p.strip()]


async def complete_json(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Completa prompt e devolve JSON parseado.

    Percorre `LLM_PROVIDER_ORDER`. Primeiro provider que responde com JSON
    válido ganha. Se todos falharem, raise.
    """
    errors: list[str] = []
    for provider in _provider_order():
        try:
            return await _dispatch(provider, system_prompt, user_prompt, temperature, max_tokens, json_mode=True)
        except _NotConfigured:
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider}: {exc}")
            log.info("%s falhou (%s); tentando próximo", provider, exc)
    raise RuntimeError(f"todos providers LLM falharam: {'; '.join(errors) or 'nenhum configurado'}")


async def complete_text(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.5,
    max_tokens: int | None = None,
) -> str:
    """Completa prompt texto livre (sem forçar JSON). Mesma chain."""
    errors: list[str] = []
    for provider in _provider_order():
        try:
            d = await _dispatch(provider, system_prompt, user_prompt, temperature, max_tokens, json_mode=False)
            return str(d.get("content", "")) if isinstance(d, dict) else str(d)
        except _NotConfigured:
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider}: {exc}")
    raise RuntimeError(f"todos providers LLM falharam: {'; '.join(errors) or 'nenhum configurado'}")


class _NotConfigured(Exception):
    """Provider ausente/sem credenciais — pular sem contar como falha."""


async def _dispatch(
    provider: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int | None,
    *, json_mode: bool,
) -> dict[str, Any]:
    if provider == "claude_code":
        return await _call_claude_code(system_prompt, user_prompt, temperature, max_tokens, json_mode=json_mode)
    if provider == "ollama":
        return await _call_ollama(system_prompt, user_prompt, temperature, max_tokens, json_mode=json_mode)
    if provider == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise _NotConfigured("sem OPENROUTER_API_KEY")
        return await _call_openrouter(system_prompt, user_prompt, temperature, max_tokens, json_mode=json_mode)
    raise _NotConfigured(f"provider desconhecido: {provider}")


# ── providers internos ────────────────────────────────────────────────

async def _call_claude_code(
    system_prompt: str,
    user_prompt: str,
    temperature: float,  # ignorado — CLI não expõe
    max_tokens: int | None,  # ignorado
    *, json_mode: bool = True,
) -> dict[str, Any]:
    """Invoca Claude via `claude` CLI (Claude Agent SDK) usando a assinatura
    já logada em `~/.claude/`. Sem API key extra.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )
    except ImportError as exc:
        raise _NotConfigured(f"claude-agent-sdk não instalado: {exc}") from exc

    # Evita conflito quando worker é lançado de dentro de uma sessão Claude Code
    prev_claudecode = os.environ.pop("CLAUDECODE", None)
    try:
        model = os.environ.get("CLAUDE_CODE_MODEL", "claude-haiku-4-5")

        sys_prompt = system_prompt
        if json_mode:
            sys_prompt += (
                "\n\nIMPORTANTE: Responda APENAS com JSON válido. Sem texto antes/depois, "
                "sem cercas de markdown. A resposta inteira deve ser parseável por json.loads()."
            )

        opts = ClaudeAgentOptions(
            system_prompt=sys_prompt,
            model=model,
            max_turns=1,
            permission_mode="bypassPermissions",
            setting_sources=[],  # não carregar CLAUDE.md do cwd do worker
        )

        result_text: str = ""
        async for msg in query(prompt=user_prompt, options=opts):
            if isinstance(msg, ResultMessage):
                if getattr(msg, "result", None):
                    result_text = msg.result  # type: ignore[assignment]
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        result_text = block.text
    finally:
        if prev_claudecode is not None:
            os.environ["CLAUDECODE"] = prev_claudecode

    if not result_text:
        raise RuntimeError("Claude Code retornou vazio")
    if not json_mode:
        return {"content": result_text}
    return _safe_json_parse(result_text)


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
                "HTTP-Referer": "https://github.com/inematds/imkt5",
                "X-Title": "imkt5 worker",
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
    # tenta parse direto
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # tolerância: modelos às vezes prefixam com texto — extrai o primeiro
    # bloco balanceado {...}
    start = s.find("{")
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise RuntimeError(f"resposta LLM não é JSON válido: {s[:300]}")


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
