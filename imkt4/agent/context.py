"""ContextBuilder — monta o system prompt + contexto do tenant.

Lê SOUL/AGENTS/USER/MEMORY do perfil do tenant (profiles/<tenant>/*.md),
combina com memórias relevantes do SQLite FTS5 e devolve o system prompt
que será injetado na primeira mensagem do LLM.
"""

from __future__ import annotations

from pathlib import Path

from imkt4.memory.store import MemoryStore


class ContextBuilder:
    def __init__(self, memory: MemoryStore | None = None) -> None:
        self._memory = memory

    async def build_system_prompt(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
    ) -> str:
        parts: list[str] = [
            "Você é o assistente do imkt4 — uma plataforma de pipeline de mídia "
            "(imagem, áudio, vídeo, pesquisa, análise). Você conversa em "
            "português brasileiro, é direto e não inventa.",
            "",
            "Você tem acesso a TOOLS pra executar trabalho pesado:",
            "- `dispatch_job(capability, payload)` para pedidos simples "
            "(1 capability: image.generation, audio.tts, research.market, etc).",
            "- `run_recipe(name, input)` para fluxos compostos "
            "(campanhas, yt-clip-publish, etc).",
            "",
            "Regras:",
            "- Se o usuário pede algo simples (1 capability), use dispatch_job.",
            "- Se pede algo composto (campanha completa, múltiplos passos "
            "encadeados), use run_recipe.",
            "- Se pode responder direto sem job, responda.",
            "- Sempre devolva o job_id ou run_id retornado pela tool pra o "
            "usuário poder acompanhar.",
            "- Se o usuário é ambíguo, pergunte antes de disparar.",
        ]

        tenant_files = self._load_tenant_profile(tenant_id)
        if tenant_files:
            parts += ["", "## CONTEXTO DESTE TENANT"]
            parts += tenant_files

        if self._memory:
            try:
                memories = await self._memory.search(
                    tenant_id=tenant_id, user_id=user_id,
                    query=query, limit=5,
                )
                if memories:
                    parts += ["", "## MEMÓRIAS RELEVANTES"]
                    parts += [f"- {m.content}" for m in memories]
            except Exception:  # noqa: BLE001
                pass

        return "\n".join(parts)

    def _load_tenant_profile(self, tenant_id: str) -> list[str]:
        """Lê SOUL/AGENTS/USER do perfil do tenant, se existir."""
        root = Path("profiles") / tenant_id
        if not root.exists():
            return []
        out: list[str] = []
        for fname in ("SOUL.md", "AGENTS.md", "USER.md"):
            p = root / fname
            if p.exists():
                out.append(f"### {fname}")
                out.append(p.read_text().strip())
                out.append("")
        return out
