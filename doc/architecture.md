# Arquitetura — imkt5

Documento arquitetural canônico. Leitura obrigatória antes de qualquer
mudança estrutural.

## Linhagem

- **Blueprint**: projeto `intelecto` (spec pura, zero código). Define os
  contratos limpos `BaseProvider` / `BaseChannel` / `BaseTool` e a ideia de
  "stack de identidade em Markdown".
- **Peças prontas**: projeto `openpcbot` — doa schema SQLite (já keyed por
  `chat_id`), adapter WhatsApp, wrapper Claude Agent SDK, estrutura de
  dashboard.
- **Workers**: absorvidos dos projetos existentes (`timesmkt3`, `inemaimg`,
  `inemavox`, família `yt-pub-lives*`).

## Camadas

```
┌─────────────────────────────────────────────────────────┐
│  CANAIS — adapters finos                                │
│  Telegram · WhatsApp · Web                              │
└──────────────────────────┬──────────────────────────────┘
                           │ IncomingMessage (tenant_id, user_id)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  GATEWAY CONVERSACIONAL                                 │
│  • tenancy.resolver  (tg_id|wa_phone|web_user → user)   │
│  • agent loop         (pensa → memória → tools)         │
│  • context            (SOUL/AGENTS/USER por tenant)     │
│  • memory store       (SQLite FTS5 + BM25, multi-tenant)│
│  • tool registry      (save_memory, dispatch_job, ...)  │
└──────────────────────────┬──────────────────────────────┘
                           │ Job (via tool dispatch_job)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  GATEWAY JOBS / FILA                                    │
│  • API HTTP (FastAPI)  — cria/consulta job              │
│  • fila (RQ+Redis)      — uma por worker_type           │
│  • progress stream      — SSE/WS ao canal de origem     │
└──────────────────────────┬──────────────────────────────┘
                           │ Job consumido
                           ▼
┌─────────────────────────────────────────────────────────┐
│  WORKERS — stateless, escaláveis                        │
│  inemaimg · inemavox · yt-pub-lives · timesmkt3 · ...   │
│  Cada um: aceita Job → emite JobResult                  │
│  Cada um: rodável sozinho (Docker próprio, CLI própria) │
└─────────────────────────────────────────────────────────┘
```

## Contratos principais

### `IncomingMessage`
Emitida por um canal após resolver identidade. Carrega `tenant_id`, `user_id`,
`channel`, `channel_external_id`, texto, anexos (já em object storage).

### `OutgoingMessage`
Pedido do Gateway para um canal entregar algo. Pode ser progress update
(parcial) ou resposta final.

### `Job` / `JobResult`
Unidade de trabalho pesado. `Job` leva `worker_type`, `payload`, `priority`,
`dedupe_key`. `JobResult` leva status, output, progress. O schema interno de
`payload` e `output` é definido por cada worker.

### `BaseChannel`, `BaseProvider`, `BaseTool`
Interfaces abstratas em `imkt5/{channels,providers,tools}/base.py`. Todo
adapter/provider/tool concreto herda destas. **Sem exceções.**

### `ToolContext`
Mudança vs. Intelecto original: tools recebem `ctx: ToolContext` com
`tenant_id` e `user_id` explícitos. Não existe tool que roda anonimamente.

## Fluxo de um pedido (end-to-end)

1. Usuário manda "gera uma imagem de X" no Telegram.
2. `TelegramChannel` recebe, baixa anexos (se houver) para MinIO, resolve
   `chat_id → (tenant_id, user_id)` via `tenancy.resolver`, e emite
   `IncomingMessage`.
3. Gateway recebe, o **agent loop** monta contexto: SOUL/AGENTS/USER do
   tenant + memórias relevantes (via `MemoryStore.search`).
4. LLM (via `BaseProvider`) decide: responder direto OU chamar tools. Nesse
   caso, chama `dispatch_job(worker_type="inemaimg", payload=...)`.
5. Tool `dispatch_job` cria um `Job` na fila Redis (RQ), devolve `job_id`.
6. Worker `inemaimg` consome, gera a imagem, faz upload para MinIO, publica
   `JobResult(status=SUCCESS, output={"image_url": ...})`.
7. Gateway detecta resultado, busca o canal de origem em
   `ChannelRegistry`, envia `OutgoingMessage` com o link/anexo.
8. Usuário recebe no Telegram.

Múltiplos usuários simultâneos = múltiplos jobs na fila. Múltiplos pedidos
do mesmo usuário = múltiplos jobs (ou o mesmo, se `dedupe_key` bater).

## Isolamento multi-tenant

- **DB**: coluna `tenant_id` em toda tabela. Todo índice lidera por
  `tenant_id`. Toda query filtra por `tenant_id`.
- **Profile**: `profiles/{tenant_id}/SOUL.md` etc. — nunca global.
- **Tools**: recebem `ToolContext` com `tenant_id`. `dispatch_job`
  propaga para o worker.
- **Fila**: jobs carregam `tenant_id`; workers logam com `tenant_id`;
  métricas agrupam por `tenant_id`.
- **Secrets**: chaves de API por tenant vão para KMS/vault externo, nunca
  Fernet-por-hardware (estratégia do Intelecto que não escala).

## Mapa de reuso de `openpcbot`

**Reusar:**
- `src/db.ts` — schema base para o `MemoryStore` (já adotado, portado para
  SQLite + coluna `tenant_id`).
- `src/memory.ts` — padrões de `buildMemoryContext`, `searchMemories`,
  `getRecentMemories`.
- `src/whatsapp.ts` + `scripts/wa-daemon.ts` — futuro `WhatsAppChannel`.
- `src/agent.ts` — futuro wrapper Claude como um `BaseProvider`.
- `src/dashboard.ts` + `src/dashboard-html.ts` — base do `WebChannel` + admin UI.

**Descartar:**
- `src/router.ts` — classificador de LLM, não router de jobs.
- `src/scheduler.ts` — cron, não fila real.
- `agents/{comms,content,ops,research}/` — chat-loops, não workers.
- `src/config.ts:ALLOWED_CHAT_ID` + `isAuthorised()` (25+ sites) — substituir
  por middleware multi-tenant.

## Princípios de composição (rodada 3)

5. **Provider é Worker.** Não há distinção interna entre "provider" e
   "worker" — ambos implementam o mesmo contrato e declaram a mesma
   capability. Metadata `local: true|false` + `priority: <int>` governam
   a seleção. Fallback entre providers (local → remoto) é apenas o
   runner escolhendo o próximo worker saudável com a mesma capability.
6. **Quick dispatch.** Pedidos simples não entram em receita. Gateway
   Conversacional classifica a intenção:
   - Simples (`gera uma imagem`, `dubla este áudio`) → `dispatch_job`
     direto para capability.
   - Composto conhecido → `run_recipe(name=...)`.
   - Composto novo → `run_recipe(ad_hoc=[...])` — receita montada em
     runtime.
7. **Aprovação default = `none`.** Pipeline corre sem intervenção
   humana a menos que a receita declare aprovação. Três modos quando
   requerido: `user`, `human_reviewer`, `auto_reviewer`.
8. **Research é opt-in.** Mesmo em campanha completa, pesquisa de
   mercado não corre por padrão — vem de `with_research: true` no
   input, via frase explícita do usuário ou toggle no painel.
9. **Delivery = três modos paralelos**, não estágio:
   - `chat` — entrega automática no canal de origem.
   - `download` — painel Web com endpoint `/jobs/{id}/bundle.zip`.
   - `publish` — ação do painel que dispara workers `platform-*` sob
     demanda. Nenhum publish automático.

## Princípios de composição (rodada 2)

1. **Receitas são dinâmicas, não rígidas.** Cada estágio declara uma
   `capability` necessária; o Recipe Runner casa com workers que a
   oferecem. Estágios podem ser adicionados sob demanda — quando um novo
   worker registra uma capability relevante, receitas passam a incluir-lo
   sem tocar código.
2. **Origens e destinos são bindings parametrizáveis.** `SourceBinding` e
   `PublishBinding` descrevem credenciais e alvos. Uma receita pode varrer
   `fanout_over: $.tenant.source_bindings` para N origens; outro stage
   varre destinos. Clonagem de código deixa de existir.
3. **Aprovação tem três modos** declarados por estágio:
   - `user` — solicitante responde no chat.
   - `human_reviewer` — humano designado (papel) decide.
   - `auto_reviewer` — agente LLM decide com base em critérios; escalona
     para humano em caso de dúvida.
4. **Painel de distribuição ≠ stage.** Publicação final é ação do Gateway
   Web (painel), não job. Reduz latência e desvia da fila.

## Catálogo de workers (após análise de `timesmkt3` e `yt-pub-lives*`)

### De `yt-pub-lives*` — consolidação de 10 clones

Os 10 `yt-pub-lives<N>` **não são 10 tenants**. Em produção hoje são 10
destinos publicando clips do canal `UC2QbQDyPKuHk93dwo5iq3Sw`, mas o design
não deve fixar origem — **origem e destino são ambos parametrizáveis**:

| worker_type | Função |
|---|---|
| `yt-source-ingest` | Baixa lives de **qualquer** canal-origem parametrizado, extrai transcrição, cataloga. |
| `yt-clip` | Analisa transcrição via LLM (Piramyd/Claude/OpenRouter), corta clips via FFmpeg. |
| `yt-publish` | Dado um clip + credencial de destino, gera thumbnail e publica. Fan-out: N execuções (uma por destino). |
| `tiktok-ingest` | Baixa vídeos de canais TikTok via yt-dlp. |

Os "lives1..10" viram linhas em **duas** tabelas:
- `source_bindings(tenant_id, source_channel, kind, api_key, ...)` — origens que o tenant pode clipar.
- `publish_bindings(tenant_id, dest_channel, kind, credentials_ref, ...)` — destinos onde pode publicar.

Uma receita varre `fanout_over: $.tenant.source_bindings` para gerar um
`ingest` por origem; outro stage varre `publish_bindings` para fazer N
publicações em paralelo. Cartesiano quando relevante.

### De `timesmkt3` — decomposição em workers por capability

Cada agente tem `SKILL.md` que vira contrato do worker. **Cada worker
declara capabilities**; receita pede capabilities, não worker específico:

| worker_type | Capabilities | Origem no timesmkt3 |
|---|---|---|
| `research` | `research.tavily`, `research.market` | `skills/marketing-research-agent/` |
| `creative-brief` | `brief.strategic` | `skills/creative-director/` |
| `copywriter` | `copy.narrative`, `copy.headlines` | `skills/copywriter-agent/` |
| `ad-designer` | `design.static_ad`, `design.carousel` | `skills/ad-creative-designer/` |
| `video-quick` | `video.slideshow` | `skills/video-quick/` |
| `video-pro` | `video.cinematic` | `pipeline/worker-video-pro.js` |
| `platform-instagram` | `platform.instagram` | skill IG |
| `platform-youtube` | `platform.youtube` | skill YT |
| `platform-tiktok` | `platform.tiktok` | skill TT |
| `platform-facebook` | `platform.facebook` | skill FB |
| `platform-threads` | `platform.threads` | skill TH |
| `platform-linkedin` | `platform.linkedin` | skill LI |

**`distribution_agent` do timesmkt3 NÃO vira worker.** Suas funções
(upload Supabase, gerar Publish MD, agendar post) viram **ações do painel
Web** do Gateway — o usuário vê artefatos prontos e aciona.

### Dos outros projetos citados

| worker_type | Projeto fonte |
|---|---|
| `inemaimg` | `/home/nmaldaner/projetos/inemaimg/` (análise pendente) |
| `inemavox` | `/home/nmaldaner/projetos/inemavox/` (análise pendente) |

Achado extra: o `timesmkt3` **já integra `inemaimgProvider`** como uma das
opções de geração de imagem. O contrato que o `imkt5` define aqui ratifica
um caminho que já estava começando.

## Receitas

Workers são folhas; **receitas** são as árvores. Ficam em `recipes/` como
YAML declarativo, executadas pelo Recipe Runner do Gateway.

### Modos de aprovação (por estágio)

```yaml
approval:
  mode: user | human_reviewer | auto_reviewer | none
  timeout: 30m
  # human_reviewer:
  reviewer_role: content_supervisor
  # auto_reviewer:
  reviewer_worker: auto-reviewer
  criteria: ["regra 1", "regra 2"]
  escalate_to_human_on: uncertain
```

Todas as decisões vão para `approval_log` — auditoria unificada
independentemente do modo. Workers de auto-review são workers normais do
`imkt5` (iniciando com `auto-reviewer` nativo).

### Exemplo: `campanha-marketing` (derivada do pipeline do timesmkt3)

```
research → brief → copy → [images ∥ voiceover] → ads → video
       → [6 platforms em fanout sobre capabilities]
```

Aprovações distribuídas por estágio:
- `brief` — `auto_reviewer` (critérios: ângulo claro, CTA definido).
- `copy` — `user` (solicitante revê antes de gerar mídia cara).
- `ads` — `user`.
- `video` — `human_reviewer` (supervisor de conteúdo).
- `platforms` — `user`.

Não há stage final de distribuição — o **painel Web** do Gateway exibe os
artefatos e oferece ações (publicar imediatamente, agendar, baixar pacote).

### Exemplo: `yt-clip-publish` (substitui os 10 schedulers dos clones)

```
yt-source-ingest (fanout sobre source_bindings)
    → yt-clip (auto_reviewer gatekeeping)
    → yt-publish (fanout sobre publish_bindings)
```

Ambas extremidades variam. Um tenant pode clipar do canal A e B, e
publicar em destinos X, Y, Z — cada combinação roda em paralelo.

## Decisões fixadas no scaffold

| Decisão | Valor | Por quê |
|---|---|---|
| Linguagem core | Python ≥ 3.11 | Fiel ao blueprint Intelecto |
| Orquestrador de fila | RQ + Redis | Python-nativo, simples; substituível |
| DB memória | SQLite FTS5 + BM25 | Mesmo do Intelecto/openpcbot, zero overhead |
| DB Gateway (jobs, users) | Postgres | Concurrent writes, auditoria |
| Object storage | MinIO / S3 | Anexos, outputs de workers |
| Estrutura | Monorepo | Um único repo, `workers/` subprojetos |
| Transporte canal ↔ gateway | In-process (async) | Canais rodam no mesmo processo por ora |
| Progress back | SSE/WS (futuro) | Canal lê status de job e atualiza mensagem |

## Estado atual (scaffold)

Implementado:

- Tipos canônicos (`imkt5/types/`).
- Contratos abstratos (`imkt5/channels/base.py`, `providers/base.py`,
  `tools/base.py` + registry).
- `MemoryStore` SQLite multi-tenant (`imkt5/memory/store.py`).
- Template de perfil por tenant (`profiles/_template/`).
- Infra local via `docker-compose.yml` (Redis + Postgres + MinIO).

Pendente (próximas fases, em ordem):

1. **Tenancy resolver** — `imkt5/tenancy/resolver.py`: mapa
   `(channel, external_id) → (tenant_id, user_id)`.
2. **`dispatch_job` tool** — `imkt5/tools/dispatch_job.py` + wrapper RQ em
   `imkt5/gateway/queue.py`.
3. **Gateway HTTP** — FastAPI (`imkt5/gateway/api.py`) expondo criar/status
   de jobs, e endpoint de ingest de mensagens (útil ao `WebChannel`).
4. **Agent loop** — `imkt5/agent/loop.py` (multi-tenant) + `context.py`
   (carrega SOUL/AGENTS/USER do tenant).
5. **Providers concretos** — `OpenRouterProvider`, `OllamaProvider`.
6. **Canal Telegram** — primeiro adapter real, porta simplificada de
   openpcbot.
7. **Análise dos projetos-worker** — ficha padrão nos 4+ projetos.
8. **Primeiro worker** — escolher o menor (provável: `inemaimg`) e
   encapsulá-lo no contrato Job.
