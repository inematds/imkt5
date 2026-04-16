"""auto-reviewer worker.

Avalia artefatos contra critérios declarados em receita. Emite decisão
`approved | rejected | uncertain` com justificativa.

Provider chain (local-first):
  1. Ollama local (se OLLAMA_URL responder)
  2. OpenRouter (se OPENROUTER_API_KEY setado)
  3. Heurística degradada (se nenhum disponível)

Payload:
  {
    "criteria": ["regra 1", "regra 2"],
    "artifacts": {...},
    "model": "..."  # opcional; override do default
  }
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from workers._base import BaseWorker

# ── providers ────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_ROUTER_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"))

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL_DEFAULT", "google/gemini-2.0-flash-exp:free"
)

SYSTEM_PROMPT = """\
Você é um revisor automático. Seu trabalho é decidir se um artefato atende
a uma lista de critérios.

Para cada critério, emita um veredicto: "pass" | "fail" | "unclear".

Então emita uma decisão global:
- "approved" se TODOS os critérios passam,
- "rejected" se ALGUM critério falha claramente,
- "uncertain" se há "unclear" e nenhum "fail".

Responda APENAS em JSON com este formato exato, sem texto antes ou depois:
{
  "per_criterion": [
    {"criterion": "...", "verdict": "pass|fail|unclear", "reason": "..."}
  ],
  "decision": "approved|rejected|uncertain",
  "reason": "resumo curto"
}
"""


class AutoReviewerWorker(BaseWorker):
    name = "auto-reviewer"
    capabilities = ("review.auto",)

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        criteria = payload.get("criteria") or []
        artifacts = payload.get("artifacts") or {}
        model_override = payload.get("model")

        if not criteria:
            return {
                "decision": "approved",
                "reason": "sem critérios declarados",
                "per_criterion": [],
            }

        prompt = self._build_prompt(criteria, artifacts)

        # 1) Tenta Ollama local
        try:
            result = await self._call_ollama(prompt, model_override or OLLAMA_MODEL)
            result["provider"] = "ollama"
            return result
        except Exception as exc:  # noqa: BLE001
            ollama_err = f"{type(exc).__name__}: {exc}"

        # 2) Fallback OpenRouter
        if OPENROUTER_KEY:
            try:
                result = await self._call_openrouter(
                    prompt, model_override or OPENROUTER_MODEL
                )
                result["provider"] = "openrouter"
                result["_fallback_from"] = f"ollama: {ollama_err}"
                return result
            except Exception as exc:  # noqa: BLE001
                or_err = f"{type(exc).__name__}: {exc}"
                return {
                    "decision": "uncertain",
                    "reason": f"ambos providers falharam. ollama: {ollama_err}; openrouter: {or_err}",
                    "per_criterion": [],
                    "provider": "none",
                }

        # 3) Heurística (sem provider)
        return {
            "decision": "uncertain",
            "reason": f"ollama falhou ({ollama_err}); openrouter ausente",
            "per_criterion": [],
            "provider": "none",
        }

    # ── providers ─────────────────────────────────────────────────────
    def _build_prompt(self, criteria: list[str], artifacts: dict[str, Any]) -> str:
        crit_list = "\n".join(f"- {c}" for c in criteria)
        art_str = json.dumps(artifacts, ensure_ascii=False)[:6000]
        return (
            f"Critérios:\n{crit_list}\n\n"
            f"Artefatos a revisar (JSON):\n{art_str}"
        )

    async def _call_ollama(self, user_msg: str, model: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "options": {"temperature": 0.0},
                    "format": "json",
                    "stream": False,
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("message", {}).get("content", "")

        return self._parse_response(content, model)

    async def _call_openrouter(self, user_msg: str, model: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{OPENROUTER_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/inematds/imkt4",
                    "X-Title": "imkt4 auto-reviewer",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.0,
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]

        return self._parse_response(content, model)

    def _parse_response(self, content: str, model: str) -> dict[str, Any]:
        # alguns modelos envolvem em ```json ... ``` — strip
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`").lstrip("json").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {
                "decision": "uncertain",
                "reason": f"resposta inválida do LLM: {content[:200]}",
                "per_criterion": [],
                "model_used": model,
            }
        return {
            "decision": parsed.get("decision", "uncertain"),
            "reason": parsed.get("reason", ""),
            "per_criterion": parsed.get("per_criterion", []),
            "model_used": model,
        }


if __name__ == "__main__":
    AutoReviewerWorker().run(port=8200)
