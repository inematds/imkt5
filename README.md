# imkt4

Plataforma modular multi-tenant para pipelines de mídia (imagem, áudio, vídeo, texto) com **entrada conversacional** (Telegram/WhatsApp/Web), **fila de jobs**, e **local-first com fallback remoto**.

```
Canais (TG · WA · Web)  →  Gateway  →  Fila  →  Workers
```

Cada worker é um serviço HTTP independente. Cada pedido é um `Job` que o Gateway despacha para o worker certo baseado em **capability** (`image.generation`, `audio.tts`, `research.market`, etc.). Múltiplas instâncias do mesmo worker são distribuídas pelo matcher (local antes de remoto).

## Status

**Funciona end-to-end** — gateway HTTP + UI web + 4 workers reais plugados. 35 testes passando.

| Componente | Estado |
|---|---|
| Contratos multi-tenant | ✅ implementado |
| Recipe engine (YAML declarativo + 3 modos de aprovação) | ✅ implementado |
| Capability registry com local-first + health check | ✅ implementado |
| Quick dispatch (1 capability → 1 job) | ✅ implementado |
| HTTP dispatcher + saturação + logging | ✅ implementado |
| UI web em `/ui` | ✅ implementado |
| Config centralizado 3 níveis (global/tenant/user) | ✅ implementado |
| Worker `research` (Tavily) | ✅ validado live |
| Worker `auto-reviewer` (Ollama+OpenRouter) | ✅ validado live |
| Worker `inemaimg-adapter` (flux2-klein, qwen-edit, ernie) | ✅ validado live |
| Worker `inemavox-adapter` (TTS/dubbing/transcribe) | ✅ adapter pronto |
| Canal Telegram/WhatsApp | ⏸ pendente |
| Persistência Postgres | ⏸ pendente (hoje in-memory) |
| 12 workers do timesmkt3 (copywriter, ad-designer, etc.) | ⏸ a portar |
| Workers yt-pub-lives (substitui 10 clones) | ⏸ a portar |

## Quickstart

```bash
# instalar
python -m venv .venv
.venv/bin/pip install -e ".[dev]" pyyaml fakeredis httpx

# subir tudo
./scripts/start-dev.sh

# abrir UI
open http://localhost:8080/ui

# parar tudo
./scripts/stop-dev.sh
```

Pré-requisitos:
- **Ollama** rodando (`qwen2.5:14b` baixado) — pra `auto-reviewer`
- **inemaimg** rodando em `:8000` (opcional — pra gerar imagem real)
- **inemavox** rodando em `:8010` (opcional — pra TTS real)
- `TAVILY_API_KEY` no `.env` (já populado a partir do timesmkt3)

Teste via `curl`:
```bash
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{"capability":"research.market","payload":{"queries":["café 2026"]}}'
```

## Arquitetura em 3 linhas

1. **Quick dispatch** — pedido simples (1 capability) é um `POST /jobs` direto.
2. **Recipe Runner** — fluxos compostos (múltiplas capabilities encadeadas) vêm de YAML em `recipes/*.yaml`, com dependências/paralelismo/aprovações declarativas.
3. **Capability matcher** — registry de workers com `local: true/false` + `priority` + `health`; fallback automático local → remoto.

Diagramas em `doc/diagrams/` (SVG + PNG).

## Estrutura

```
imkt4/
├── imkt4/              pacote Python (gateway, dispatcher, runner, tipos)
│   ├── config.py       loader de config 3-níveis
│   ├── gateway/        HTTP dispatcher, FastAPI, UI web, jobs store
│   ├── capabilities/   registry + matcher (local-first)
│   ├── recipes/        YAML loader, state-machine runner, approvals
│   ├── memory/         SQLite FTS5 multi-tenant
│   ├── tools/          dispatch_job + run_recipe (tools pro LLM)
│   └── types/          dataclasses canônicas
├── workers/            serviços HTTP independentes
│   ├── _base/          BaseWorker + storage helper
│   ├── auto-reviewer/  LLM review (Ollama local + OpenRouter fallback)
│   ├── inemaimg-adapter/  wrapper do inemaimg (image.generation)
│   ├── inemavox-adapter/  wrapper do inemavox (audio.*)
│   └── research/       Tavily (research.market)
├── config/
│   ├── defaults.yaml   fonte única dos magic numbers globais
│   └── workers.yaml    catálogo de workers registrados
├── profiles/           config por tenant
│   ├── _template/      stack de identidade (SOUL/AGENTS/USER/MEMORY)
│   └── <tenant_id>/    SOUL.md + config.yaml + knowledge/
├── recipes/            fluxos compostos (YAML)
├── scripts/            start-dev.sh, stop-dev.sh, notify.sh
├── data/               artefatos locais (gitignored)
├── logs/               logs de cada processo (gitignored)
├── tests/              35 testes
└── doc/                documentação
```

## Documentação

| Doc | Quando ler |
|---|---|
| [`doc/architecture.md`](doc/architecture.md) | Entender o design canônico |
| [`doc/QUICKSTART.md`](doc/QUICKSTART.md) | Testar end-to-end com curl |
| [`doc/creating-workers.md`](doc/creating-workers.md) | Criar um worker novo |
| [`doc/creating-recipes.md`](doc/creating-recipes.md) | Criar uma receita nova |
| [`doc/defaults.md`](doc/defaults.md) | Onde mora cada valor default |
| [`doc/concurrency-model.md`](doc/concurrency-model.md) | Como o sistema escala |
| [`doc/env-inventory.md`](doc/env-inventory.md) | Mapa de credenciais dos projetos-fonte |
| [`doc/api-mapping-inemaimg-inemavox.md`](doc/api-mapping-inemaimg-inemavox.md) | Contratos reais dos upstreams |
| [`doc/admin-ui-viability.md`](doc/admin-ui-viability.md) | Análise da UI de admin (viabilidade) |
| [`doc/diagrams/`](doc/diagrams/) | Diagramas visuais (arquitetura, provider chain, fluxos) |
| [`CLAUDE.md`](CLAUDE.md) | Regras pra futuras sessões de Claude Code |

## Origens

- **Blueprint arquitetural**: `intelecto` (spec — contratos `BaseProvider/Channel/Tool` + stack de identidade em Markdown)
- **Peças reutilizadas**: `openpcbot` (schema SQLite, WhatsApp bridge, dashboard structure)
- **Workers a absorver** (próximas fases): `timesmkt3` (12 agentes) · `yt-pub-lives*` (consolidação dos 10 clones)

## Licença

MIT
