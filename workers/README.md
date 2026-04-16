# workers/

Cada worker é um **serviço independente** que:

1. Expõe HTTP:
   - `GET  /health` → `{"status": "ok"}` quando saudável
   - `POST /execute` → recebe Job, devolve `JobResult`

2. Registra suas **capabilities** no `config/workers.yaml` do Gateway.

3. Roda sozinho — não conhece outros workers, não conhece o Recipe Runner.

## Convenções

- Python: `workers/<nome>/` com `server.py`, `requirements.txt`, `Dockerfile`.
- Node/TS: `workers/<nome>/` com `src/server.ts`, `package.json`, `Dockerfile`.
- Cada worker tem seu próprio `.env.example`.
- Respostas sempre em JSON. Erros devolvem status HTTP 4xx/5xx com `{"error": "..."}`.

## Workers planejados

### Fase 2 (scaffold neste commit)
- `_base/` — utilitários compartilhados (contrato HTTP, sandbox, logger)
- `auto-reviewer/` — LLM que aprova/rejeita com base em critérios
- `inemaimg-adapter/` — wrapper para inemaimg (`image.generation`)
- `inemavox-adapter/` — wrapper para inemavox (`audio.tts`, `audio.dubbing`)

### Fase 3
- `research/` — Tavily
- `creative-brief/`, `copywriter/`, `ad-designer/`, `video-quick/`,
  `video-pro/`, `platform-*/` — via Claude CLI subprocess

### Fase 4
- `yt-source-ingest/`, `yt-clip/`, `yt-publish/`, `tiktok-ingest/`

Cada worker é absorvido trazendo o código real do projeto-fonte
(`timesmkt3`, `yt-pub-lives2`, `inemaimg`, `inemavox`) quando chegar sua
vez no plano. O scaffold neste commit só tem a forma do contrato.
