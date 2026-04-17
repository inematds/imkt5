# Backlog — o que falta no `imkt4`

> Consolida tudo que ficou pendente até agora. Organizado por prioridade
> e com estimativas de esforço pra planejar execução.

## Legenda

- **Esforço**: S (≤1 dia), M (1–3 dias), L (3–7 dias), XL (1–3 semanas)
- **Risco**: baixo / médio / alto
- **Desbloqueia**: o que passa a ser possível quando este item terminar

## Estado atual (2026-04-17)

Fundação pronta: gateway HTTP, UI web, 4 workers reais, capability registry
local-first, recipe engine com 3 modos de aprovação, config 3-níveis, 35
testes verdes.

Falta: canais conversacionais, persistência, portar os workers grandes,
admin UI, infra de produção.

---

## 🔴 Críticos (bloqueiam a visão original do sistema)

### 1. Gateway conversacional — LLM decidindo
- **Esforço:** M | **Risco:** médio | **Desbloqueia:** Telegram/WA/Web conversacional de verdade
- **Problema hoje:** a UI força o usuário a escolher a capability no dropdown. Não é um assistente.
- **O que fazer:** agent loop em `imkt4/agent/loop.py` que:
  - Recebe `IncomingMessage`
  - Consulta memória (MemoryStore já pronto) + SOUL/AGENTS/USER do tenant
  - Chama `BaseProvider.chat()` com as tools `dispatch_job` e `run_recipe` registradas
  - LLM decide: responde direto OR dispatch OR recipe
  - Retorna `OutgoingMessage`
- **Precisa:** Provider concreto (OpenRouter ou Ollama local). Ambos já têm URL/key no `.env`.
- **Arquivos:** `imkt4/agent/loop.py` (novo), `imkt4/agent/context.py` (novo), `imkt4/providers/openrouter.py` (novo), `imkt4/providers/ollama.py` (novo).

### 2. Canal Telegram real
- **Esforço:** M | **Risco:** baixo | **Desbloqueia:** uso diário no celular
- **Problema hoje:** só UI web; interface única é frágil.
- **O que fazer:** implementar `BaseChannel` real que:
  - Long-polling via `python-telegram-bot`
  - Traduz update → `IncomingMessage` (resolve `tenant_id` + `user_id` via `tenancy/resolver.py`)
  - Chama `on_message(msg)` do Gateway
  - Envia `OutgoingMessage` (split de mensagem >4096, upload de anexo)
- **Precisa:** criar bot novo via BotFather (NÃO reusar token do timesmkt3 em uso).
- **Arquivos:** `imkt4/channels/telegram.py` (novo), `imkt4/tenancy/resolver.py` (novo).
- **Referência:** `openpcbot/src/bot.ts` + `timesmkt3/telegram/bot.js` — padrão porta.

### 3. Persistência — Postgres mínimo
- **Esforço:** M | **Risco:** baixo | **Desbloqueia:** survive restart, multi-node, audit
- **Problema hoje:** JobsStore + RecipeRun em memória; perde tudo no restart.
- **Tabelas mínimas:** `tenants`, `users`, `channel_bindings`, `source_bindings`, `publish_bindings`, `jobs`, `recipe_runs`, `approval_log`.
- **Schema já tem tipos prontos** em `imkt4/types/*.py` — só falta a camada de persistência.
- **Arquivos:** `imkt4/db/` (novo) com `schema.sql`, `jobs_repo.py`, `runs_repo.py`, `tenants_repo.py`. Trocar `JobsStore` in-memory por `PostgresJobsStore` com mesma interface.
- **Dep:** `asyncpg` ou `psycopg3`.

---

## 🟡 Importantes (faltam pra produção mas não bloqueiam)

### 4. Aprovações reais via canal
- **Esforço:** S | **Risco:** baixo | **Depende de:** #1 (Gateway conv) + #2 (Telegram)
- **Problema hoje:** `user_gate` e `reviewer_gate` em `main.py` são stubs que auto-aprovam.
- **O que fazer:** implementar gates reais que mandam `OutgoingMessage` ("aprovar? `/aprovar <stage>` ou `/rejeitar <stage> motivo`") e bloqueiam até resposta humana.
- **Arquivos:** `imkt4/recipes/approvals/telegram_gates.py` (novo).

### 5. Multi-tenant de verdade
- **Esforço:** M | **Risco:** médio | **Depende de:** #3 (Postgres)
- **Problema hoje:** tudo é tenant "demo" hardcoded em `main.py`.
- **O que fazer:**
  - `tenancy/resolver.py` que mapeia `(channel_kind, external_id) → (tenant_id, user_id)`
  - CRUD mínimo de tenants/users (pode ser CLI inicial; UI vem depois)
  - Middleware no gateway que enforce tenant em toda rota
- **Arquivos:** `imkt4/tenancy/` (novo).

### 6. Memória conversacional plugada no agent loop
- **Esforço:** S | **Risco:** baixo | **Depende de:** #1 (agent loop)
- **Problema hoje:** `MemoryStore` SQLite FTS5 existe e testado (35 testes), mas não está conectado.
- **O que fazer:** no agent loop, antes de chamar LLM, fazer `memory.search(tenant, user, query)` e injetar top-K no system prompt. Depois de responder, `memory.save(resumo)`.
- **Arquivos:** edição de `imkt4/agent/loop.py` e `context.py`.

### 7. Portar workers do timesmkt3 (escopo reduzido)
- **Esforço:** M (um por vez, ~1–2 dias cada) | **Risco:** médio
- **Escopo atual (5 workers)**: creative-brief, copywriter, ad-designer, video-quick, video-pro.
  (research ✅ feito)
- **DIFERIDOS** — NÃO portar agora: os 6 `platform-*` (instagram, youtube, tiktok, facebook, threads, linkedin). Detalhes em `doc/deferred-platform-workers.md`.
- **Padrão:** cada um copia `timesmkt3/skills/<agente>/SKILL.md` pra `workers/<nome>/SKILL.md`, adapta I/O (sem `prj/<cliente>/outputs/`, usa storage helper), registra no `config/workers.yaml`.
- **Estratégia:** começar pelo `copywriter` (mais genérico) e `ad-designer` (integração visual já existe no inemaimg).
- **Referência:** `doc/creating-workers.md` passo a passo.

### 8. Portar 4 workers do yt-pub-lives
- **Esforço:** L | **Risco:** médio
- **Os 4:** `yt-source-ingest`, `yt-clip`, `yt-publish`, `tiktok-ingest`.
- **Consolida os 10 clones** em 1 código + N entradas em `publish_bindings`.
- **Precisa:** migrar credenciais OAuth de `credentials.enc` local pra KMS (ou mock em dev).
- **Arquivos:** `workers/yt-source-ingest/`, `workers/yt-clip/`, `workers/yt-publish/`, `workers/tiktok-ingest/` (todos novos).

### 9. Admin UI — editor de config
- **Esforço:** S | **Risco:** baixo | **Depende de:** #10 (auth)
- **Análise completa:** `doc/admin-ui-viability.md`.
- **O quê:** YAML editor no `/admin/config` com validação e backup.
- **Escopo MVP:** editar `config/defaults.yaml` (admin global) e `profiles/<tenant>/config.yaml` (admin por tenant).

### 10. Auth no gateway
- **Esforço:** S | **Risco:** médio
- **Problema hoje:** gateway é 100% aberto.
- **O que fazer:** bearer token simples por papel (`admin-global`, `admin-tenant-X`, `user-Y`). Middleware FastAPI. Secret em `.env`.
- **Arquivo:** `imkt4/gateway/auth.py` (novo).

---

## 🟢 Polimento (pode esperar)

### 10b. Reativar auto-review nos stages `brief` e `copy` com critérios objetivos
- **Esforço:** S | **Risco:** baixo
- **Problema hoje:** `brief` e `copy` estão com `approval: {mode: none}` na receita `campanha-marketing` porque os critérios antigos eram subjetivos ("brief tem ângulo estratégico claro", "copy tem hook forte") — LLM revisor decidia aleatório (aprovava num run, rejeitava noutro).
- **O que fazer:** reescrever critérios como asserções objetivas verificáveis, tipo:
  - `brief`: `creative_brief.campaign_angle não é vazio`, `creative_brief.approved_ctas é array com ≥ 2 itens`, `creative_brief.visual_direction.dominant_colors tem ≥ 2 hex codes`.
  - `copy`: `copy.instagram_caption tem ≥ 30 caracteres`, `copy.youtube.title existe e tem ≤ 70 chars`, `copy.threads_post tem ≤ 500 chars`.
- **Padrão**: idêntico ao que está funcionando no stage `ad_design` hoje.
- **Arquivo:** `recipes/campanha-marketing.yaml` — substituir blocos `approval` dos dois stages.

### 11. Fila Redis real + RQ
- **Esforço:** S | **Risco:** baixo
- **Problema hoje:** `InMemoryDispatcher` (asyncio.Queue local) — sem persistência, sem workers cross-process.
- **O que fazer:** trocar por `HttpDispatcher` + Redis LPUSH/BRPOP (já tem `JobQueue` esqueleto em `imkt4/gateway/queue.py`). Ou migrar pra RQ/Celery se quiser feature completa.
- **Requer:** Redis rodando (já no `docker-compose.yml`).

### 12. MinIO/S3 pra artefatos públicos
- **Esforço:** S | **Risco:** baixo
- **Problema hoje:** `LocalStorage` salva em `data/artifacts/` e devolve `file://`. Funciona no browser via `/artifacts/` mas não vale pra APIs externas (YouTube upload precisa URL pública).
- **O que fazer:** implementar `S3Storage` com mesma interface de `LocalStorage`; trocar via config.
- **Requer:** MinIO rodando (já no `docker-compose.yml`).

### 13. Delivery modes (chat/download/publish)
- **Esforço:** M | **Risco:** baixo | **Depende de:** #1 (agent loop) + #2 (canal)
- **Problema hoje:** após receita, não há fluxo explícito pra entregar ao usuário.
- **O que fazer:**
  - `chat`: automático — ao fim da receita, manda artefatos no canal original
  - `download`: endpoint `GET /runs/{id}/bundle.zip` que empacota tudo
  - `publish`: painel Web com lista de artefatos + botão "publicar em Instagram/YT/etc" → dispara jobs `platform-*`

### 14. KMS pra secrets
- **Esforço:** M | **Risco:** médio
- **Problema hoje:** todas as chaves em `.env` (gitignored mas em disco cleartext).
- **Alternativas:** Vault HashiCorp, AWS Secrets Manager, GCP Secret Manager.
- **Abstração:** já existe o campo `credentials_ref` em `SourceBinding`/`PublishBinding`. Só falta resolver o ref na hora de usar.
- **Arquivo:** `imkt4/security/kms.py` (novo, interface + backend concreto).

### 15. Audit log
- **Esforço:** S | **Risco:** baixo | **Depende de:** #3 (Postgres)
- **O quê:** toda mudança de config, toda aprovação, todo dispatch → linha em `audit_log`.
- **Pra quê:** compliance, debugging, troubleshoot.

### 16. RBAC
- **Esforço:** M | **Risco:** médio | **Depende de:** #10 (auth)
- **O quê:** papéis formais — admin global, admin tenant, usuário final, revisor.
- **Reforçado em middleware** (cada endpoint declara permissão mínima).

---

## ⚪ Admin UI completa (depois do MVP)

### 17. CRUD de workers (registrar endpoints)
- **Esforço:** S-M
- **Detalhado em:** `doc/admin-ui-viability.md` §2

### 18. Editor textual de receitas (YAML + validação)
- **Esforço:** M
- **Detalhado em:** `doc/admin-ui-viability.md` §3a

### 19. Editor visual de receitas (drag-and-drop)
- **Esforço:** L
- **Detalhado em:** `doc/admin-ui-viability.md` §3b

### 20. CLI de scaffolding (`scripts/new-worker.sh`)
- **Esforço:** S
- Gera `workers/<nome>/server.py`, `Dockerfile`, entrada em `workers.yaml`.

---

## Roteiro sugerido

Sequência que maximiza valor entregue cedo:

```
FASE A — MVP usável (4 semanas)
  1. Provider OpenRouter/Ollama (uma tarde)
  2. Agent loop com tools    (#1 gateway conversacional)
  3. Canal Telegram           (#2)
  4. Memória plugada          (#6)
  → Aqui você já USA no Telegram.

FASE B — Multi-tenant real (2 semanas)
  5. Postgres                 (#3)
  6. Tenancy resolver         (#5)
  7. Aprovações reais         (#4)
  8. Auth                      (#10)
  → Múltiplos usuários, aprovações reais, estado persistente.

FASE C — Portar workers (1-2 semanas — escopo reduzido)
  9. copywriter + creative-brief + ad-designer (#7, núcleo)
  10. video-quick + video-pro (#7)
  11. yt-source-ingest + yt-clip + yt-publish (#8)
  → campanha-marketing roda até o vídeo (stage platforms fica pendente
    até os platform-* serem portados em fase futura — ver
    doc/deferred-platform-workers.md).
  → yt-clip-publish roda completa.

FASE D — Produção (2-3 semanas)
  13. Redis real              (#11)
  14. S3/MinIO                (#12)
  15. Delivery modes          (#13)
  16. KMS                      (#14)
  17. Audit + RBAC            (#15, #16)
  18. Admin UI (config)       (#9)
  → Pronto pra operação real.

FASE E — Extras
  19-20. Editor receitas      (#17, #18, #19)
  21. Scaffolding CLI          (#20)
```

**Total estimado:** 10–13 semanas de trabalho focado (1 dev).

## Dependências visualizadas

```
[1 Gateway conv] ──┬──> [4 Aprovações reais]
                   ├──> [6 Memória plugada]
                   └──> [13 Delivery]

[2 Canal TG] ──┬──> [4 Aprovações reais]
               └──> [13 Delivery]

[3 Postgres] ──┬──> [5 Multi-tenant real]
               ├──> [15 Audit log]
               └──> [11 Fila Redis (parcial)]

[10 Auth] ──┬──> [9 Admin UI config]
            └──> [16 RBAC]
```

## Riscos transversais

1. **Sem Telegram/WA em produção, UI web = SPOF.** Se algo derruba o gateway, ninguém acessa.
2. **Multi-tenant mal implementado = leak de dados.** Testar rigorosamente isolamento por tenant_id antes de multi-cliente real.
3. **Portar workers do timesmkt3 sem cobertura de teste** — os agentes são prompt-driven; regressão silenciosa é fácil. Criar golden tests com fixtures de output esperado.
4. **Secret sprawl.** Hoje `.env` tem 43 chaves. Em produção, isso vai pra KMS — mas o refactor é invasivo.

## Quick wins (se quiser progresso visível rápido)

- **1 dia:** portar worker `copywriter` (já tem SKILL.md pronto no timesmkt3).
- **1 dia:** adicionar MinIO no storage helper (deploy já pronto no docker-compose).
- **1 dia:** fila Redis em vez de asyncio.Queue local (a infra já existe).
- **meio dia:** Auth bearer token simples.

## Quando parar

O backlog acima é **completo**. Mas você não precisa fazer tudo. Uma linha de corte razoável:

- **Mínimo pra usar diariamente**: Fase A.
- **Mínimo pra multi-usuário**: Fase A + B.
- **Mínimo pra vender**: Fase A + B + (D parcial: auth+audit).
- **Completo**: A + B + C + D.
