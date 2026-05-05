"""research worker — pesquisa de mercado via Tavily.

Capability: `research.market` (também `research.tavily` como alias).

Payload:
  {
    "brief": "descrição do produto/campanha",
    "queries": ["tendências café gelado 2026", "concorrentes cold brew"],
    "depth": "basic" | "advanced",   # default: basic
    "max_results_per_query": 5
  }

Output:
  {
    "queries_run": [...],
    "results": {
      "query1": [{"title": "...", "url": "...", "content": "...", "score": 0.9}, ...]
    },
    "consolidated": "resumo executivo curto (se depth=advanced)"
  }

Porta a ser absorvida do `timesmkt3/skills/marketing-research-agent/` — por
ora, wrapper direto sobre Tavily sem o skill do agente Claude.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from workers._base import BaseWorker

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"


class ResearchWorker(BaseWorker):
    name = "research"
    capabilities = ("research.market", "research.tavily")

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        queries = payload.get("queries") or []
        if not queries and payload.get("brief"):
            # se só veio brief, gera 3 buscas genéricas a partir dele
            brief = payload["brief"]
            queries = [
                f"tendências {brief} 2026",
                f"concorrentes {brief}",
                f"público-alvo {brief}",
            ]
        if not queries:
            raise ValueError("research precisa de 'queries' ou 'brief'")

        if not TAVILY_KEY:
            raise RuntimeError("TAVILY_API_KEY ausente")

        depth = payload.get("depth", "basic")
        max_per = int(payload.get("max_results_per_query", 5))

        results: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=45.0) as client:
            for q in queries:
                r = await client.post(
                    TAVILY_URL,
                    json={
                        "api_key": TAVILY_KEY,
                        "query": q,
                        "search_depth": depth,
                        "max_results": max_per,
                        "include_answer": depth == "advanced",
                    },
                )
                r.raise_for_status()
                data = r.json()
                results[q] = [
                    {
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "content": item.get("content"),
                        "score": item.get("score"),
                    }
                    for item in data.get("results", [])
                ]

        return {
            "queries_run": queries,
            "results": results,
            "depth": depth,
        }


if __name__ == "__main__":
    import os
    from imkt5.config import load
    port = int(os.environ.get("RESEARCH_PORT", load().workers.research.port))
    ResearchWorker().run(port=port)
