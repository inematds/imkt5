# Auditoria de valores default

> Onde cada default do sistema mora **hoje**. Também aponta para onde
> deveriam estar quando centralizarmos (proposta no fim).

## Resumo — 5 lugares diferentes

| Local | O que guarda | Crítica |
|---|---|---|
| `.env` | Segredos, URLs, modelos, endpoints | OK |
| `.env.example` | Template versionado | OK |
| `config/workers.yaml` | Catálogo de workers + priority/timeout/max_concurrent | OK |
| `recipes/*.yaml` | Defaults por receita (parallel, approval) | OK |
| **Código Python** | Fallbacks hardcoded (`os.environ.get(..., "default")`) | ⚠️ espalhado |

---

## Categoria A — Network / portas

| Variável | Default | Onde mora hoje | Pra onde deveria ir |
|---|---|---|---|
| `GATEWAY_HOST` | `0.0.0.0` | `.env` + `imkt5/main.py:233` | ficar |
| `GATEWAY_PORT` | `8080` | `.env` + `imkt5/main.py:234` | ficar |
| `INEMAIMG_URL` (upstream) | `http://localhost:8000` | `.env` + `workers/inemaimg-adapter/server.py:37` | ficar |
| `INEMAVOX_URL` (upstream) | `http://localhost:8010` | `.env` + `workers/inemavox-adapter/server.py:35` | ficar |
| `IMKT5_INEMAIMG_ADAPTER_PORT` | `8020` | env + adapter `__main__` | `config/workers.yaml` |
| `IMKT5_INEMAVOX_ADAPTER_PORT` | `8021` | env + adapter `__main__` | `config/workers.yaml` |
| research worker port | `8100` | **hardcoded** `workers/research/server.py:96` | ❌ env ou yaml |
| auto-reviewer port | `8200` | **hardcoded** `workers/auto-reviewer/server.py:194` | ❌ env ou yaml |
| `REDIS_URL` | `redis://localhost:6379/0` | `.env` | ficar |
| `POSTGRES_URL` | `postgresql://imkt5:imkt5@localhost:5432/imkt5` | `.env` | ficar |
| `S3_ENDPOINT` | `http://localhost:9000` | `.env` | ficar |

## Categoria B — LLM providers

| Variável | Default | Onde | Comentário |
|---|---|---|---|
| `OPENROUTER_API_KEY` | *(vazio)* | `.env` | segredo |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | `.env` + `workers/auto-reviewer/server.py:35` | ok |
| `OPENROUTER_MODEL_DEFAULT` | `google/gemini-2.0-flash-exp:free` | `.env` + `workers/auto-reviewer/server.py:37` | ok |
| `OLLAMA_URL` | `http://localhost:11434` | `.env` + `workers/auto-reviewer/server.py:30` | ok |
| `OLLAMA_ROUTER_MODEL` | `qwen2.5:14b` | `.env` + `workers/auto-reviewer/server.py:31` | ok |
| `OLLAMA_MODEL` (fallback) | `qwen3.5:35b-a3b` | `.env` | ok |
| `ANTHROPIC_API_KEY` | *(vazio)* | `.env` | segredo |

## Categoria C — Storage / memória

| Variável | Default | Onde | Comentário |
|---|---|---|---|
| `IMKT5_ARTIFACT_ROOT` | `./data/artifacts` | **código** `workers/_base/storage.py:23` | adicionar no `.env.example` |
| `MEMORY_DB_PATH` | `./data/memory.db` | `.env` | ok |

## Categoria D — Timeouts / concorrência (hardcoded em código!)

| Local | Default | Arquivo | ❌ |
|---|---|---|---|
| HttpDispatcher request timeout | `600.0s` | `imkt5/gateway/http_dispatcher.py:42` | mover |
| HttpDispatcher retry quando saturado | `0.5s` | `imkt5/gateway/http_dispatcher.py:43` | mover |
| HttpDispatcher max_pending | `1000` | `imkt5/gateway/http_dispatcher.py:44` | mover |
| HttpDispatcher `_select_with_retry` max tentativas | `120` (~60s) | `imkt5/gateway/http_dispatcher.py:121` | mover |
| CapabilityRegistry probe timeout | `3.0s` | `imkt5/capabilities/registry.py:32` | mover |
| JobsStore max_size | `500` | `imkt5/gateway/jobs_store.py:33` | mover |
| Approval default timeout | `1800s` (30min) | `imkt5/types/approvals.py:45` | mover |

## Categoria E — Per-worker (já em YAML)

`config/workers.yaml` tem, **por worker**:

| Campo | Exemplo | Default implícito |
|---|---|---|
| `priority` | `90` | 50 |
| `max_concurrent` | `1` | 4 |
| `timeout_seconds` | `180` | 120 |
| `local` | `true` | `false` |

Defaults implícitos estão em `RegisteredWorker` (`imkt5/types/capabilities.py`).

## Categoria F — Workers específicos

### inemaimg-adapter
| Variável | Default | Onde |
|---|---|---|
| `INEMAIMG_MODEL` (default p/ requests sem model) | `qwen-edit-2511` | `.env` + código |
| `INEMAIMG_TIMEOUT` | `180s` | `.env` + código |

### inemavox-adapter
| Variável | Default | Onde |
|---|---|---|
| `INEMAVOX_POLL_INTERVAL` | `1.5s` | `.env` + código |
| `INEMAVOX_POLL_MAX_SECONDS` | `600s` | `.env` + código |

## Categoria G — Defaults de payload por capability (UI)

Arquivo: `imkt5/gateway/web_ui.py` — constante `CAP_CONFIG`.

Cada capability tem defaults do **payload** que a UI constrói a partir do texto:

| Capability | Defaults do payload |
|---|---|
| `image.generation` | `{model: "flux2-klein", steps: 4, width: 512, height: 512}` *(ver [provider-tuning.md](./provider-tuning.md) — `steps` é por modelo)* |
| `research.market` | `{max_results_per_query: 3, depth: "basic"}` |
| `audio.tts` | `{engine: "edge", lang: "pt"}` |
| `audio.dubbing` | `{engine: "chatterbox", lang: "pt"}` |
| `audio.transcribe` | `{format: "srt"}` |
| `review.auto` | `{criteria: [default lista]}` |

**Problema**: duplicado com o que os workers aceitam. Nenhuma fonte única.

## Categoria H — Tenant / Recipe stubs

Arquivo: `imkt5/main.py` — `StubTenantContext`.

| Campo | Default do tenant "demo" |
|---|---|
| `profile.visual_style` | `minimalist` |
| `profile.voice_id` | `default` |
| `profile.prompts.cortes` | `Identifique tópicos coesos de 30-180s` |
| `source_bindings` | `[]` |
| `publish_bindings` | `[]` |

---

## O que está **quebrado** nessa distribuição

1. **Magic numbers no código**: `600.0`, `0.5`, `1000`, `120`, `3.0`, `500`, `1800`. Todos deveriam vir de config.
2. **Ports hardcoded**: `8100`, `8200` (research, auto-reviewer) — outros workers puxam de env, esses dois não.
3. **Duplicação**: CAP_CONFIG na UI duplica o que os adapters já sabem fazer.
4. **Ausência de fonte única**: quando você vê um número estranho, precisa caçar em 5 lugares.

## Proposta de centralização

Criar **`config/defaults.yaml`** (novo) com todos os magic numbers + defaults globais:

```yaml
# config/defaults.yaml
gateway:
  host: 0.0.0.0
  port: 8080

dispatcher:
  request_timeout_seconds: 600
  retry_when_saturated_seconds: 0.5
  max_pending_jobs: 1000
  max_retries_select: 120

capability_registry:
  probe_timeout_seconds: 3.0
  refresh_interval_seconds: 30

jobs_store:
  max_history: 500

approvals:
  default_timeout_seconds: 1800

workers:
  defaults:
    priority: 50
    max_concurrent: 4
    timeout_seconds: 120
    local: false

  # per-worker overrides ficam em config/workers.yaml

  individual:
    research: { port: 8100 }
    auto_reviewer: { port: 8200 }
    inemaimg_adapter:
      port: 8020
      default_model: qwen-edit-2511
      request_timeout_seconds: 180
    inemavox_adapter:
      port: 8021
      poll_interval_seconds: 1.5
      poll_max_seconds: 600

storage:
  artifact_root: ./data/artifacts
```

E um carregador central em **`imkt5/config.py`**:

```python
from imkt5.config import settings
settings.dispatcher.request_timeout_seconds  # 600
settings.workers.individual.research.port    # 8100
```

Regra de precedência:
1. **Env var** (override por ambiente) — sempre primeiro
2. **`config/defaults.yaml`** (defaults do projeto)
3. **Último recurso hardcoded** (fallback defensivo)

## O que fica em cada lugar depois

| Lugar | Responsabilidade |
|---|---|
| `.env` | **só** segredos (API keys, tokens) e overrides por ambiente |
| `.env.example` | template da equipe |
| `config/defaults.yaml` | **fonte única** de todos os magic numbers e defaults operacionais |
| `config/workers.yaml` | catálogo específico de workers registrados |
| `recipes/*.yaml` | receitas declarativas |
| Código Python | apenas fallback seguro se yaml estiver quebrado |

---

## Referências rápidas

- Valores atuais carregados: `GET http://localhost:8080/config` *(endpoint a criar após centralização)*
- Conferir o que o registry tem: `GET http://localhost:8080/workers`
- Ver receitas carregadas: `GET http://localhost:8080/recipes`
