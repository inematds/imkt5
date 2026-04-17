# Painéis — visão geral e divisão de responsabilidades

> Documento consolidado. O `imkt4` tem painéis web servidos pelo próprio
> Gateway (`/ui/*`). Cada painel atende um papel diferente — evita
> misturar operação diária com configuração crítica.

## Três níveis

```
┌────────────────────────────────────────────────────────────────┐
│  /ui         OPERACIONAL — dia a dia do usuário final          │
│              (chat, jobs, receitas, resultados)                │
├────────────────────────────────────────────────────────────────┤
│  /ui/yt      ESPECÍFICO DO FLUXO (módulo yt-pipeline)          │
│              (materials, clips, publicações, fontes/destinos)  │
├────────────────────────────────────────────────────────────────┤
│  /admin      CONFIGURAÇÃO — ajustes globais e por tenant       │
│              (defaults, bindings, workers, receitas YAML)      │
└────────────────────────────────────────────────────────────────┘
```

## 1. `/ui` — Painel Operacional (JÁ EXISTE)

**Quem usa**: usuário final do tenant (dono da campanha, operador de
marketing, etc.).

**Pra que serve**: uso cotidiano sem tocar em config.

**Features atuais**:
- Conversa via agent loop (tab Novo Job)
- Rodar receitas (tab Rodar Receita)
- Lista de jobs recentes com auto-refresh
- Preview de resultados (imagens inline, áudios)
- Status de workers (sidebar) + capabilities + receitas disponíveis

**Pendente**:
- Histórico de runs da receita (hoje só jobs individuais)
- Detalhe de run: árvore de stages com status + artefatos
- Aprovações pendentes do usuário (quando `mode: user` ou escalate)
- Delivery modes: botão "baixar ZIP" + botão "publicar em"

## 2. `/ui/yt` — Painel do fluxo de mídia (A CRIAR)

**Quem usa**: operador de conteúdo que gerencia o pipeline de vídeos
(pessoas que hoje usam o `master-dashboard` do `yt-pub-lives2`).

**Pra que serve**: gerenciar o fluxo específico de ingestão→corte→publicação.
Absorve a função do `master-dashboard` atual.

**Features**:

### Seção: Materiais
- Tabela de materiais importados
- Filtros: fonte (upload/tiktok/import_dir/global_dir), tenant, status, data
- Preview inline (thumbnail)
- Botão "processar" (dispara `yt-transcribe` + `yt-cuts`)
- Botão "deletar"

### Seção: Clips
- Grid de clips gerados, com preview
- Agrupamento por material-pai
- Filtros: status (ready/published/failed), duração, tema
- Botão "publicar em" (seleciona destinos, dispara fanout `yt-publish`)
- Botão "regenerar" (roda `yt-cuts` de novo com prompt ajustado)

### Seção: Publicações
- Histórico por destino
- Métricas: publicados/dia por canal, erros
- Link pro vídeo no YouTube
- Botão "despublicar" (se plataforma permitir)

### Seção: Fontes configuradas (`source_bindings`)
- Lista de canais TikTok monitorados, diretórios watchers, etc.
- CRUD: adicionar TikTok (username), registrar diretório, editar credenciais
- Teste de conexão

### Seção: Destinos configurados (`publish_bindings`)
- Lista de canais YouTube / outras redes configuradas
- CRUD: novo destino, edit, disable
- Status OAuth (token válido? expira quando?)
- **Migração dos 10 `yt-pub-lives<N>`**: botão "importar destinos do
  yt-pub-lives*" — adapter lê os `credentials.enc` e cria
  `publish_bindings` novos (decisão P7).

## 3. `/admin` — Painel de Configuração (A CRIAR)

**Quem usa**: admin global (você) e admin do tenant (dono da empresa
cliente).

**Pra que serve**: editar config, gerenciar workers, criar receitas.
Decisão fina em `doc/admin-ui-viability.md`.

**Features por nível de admin**:

### Admin Global (você)
- Editor YAML de `config/defaults.yaml` (com validação + backup)
- CRUD de tenants (ver/criar/desabilitar)
- CRUD de workers registrados (adicionar endpoint, toggle enabled)
- Editor de receitas em `recipes/*.yaml`
- Logs de audit (quem mudou o quê, quando)
- Status geral do sistema (Postgres, Redis, workers saudáveis)

### Admin de Tenant (cliente)
- Editor de `profiles/<tenant>/config.yaml` (brand, reviewers, modelo preferido)
- Editor de `profiles/<tenant>/SOUL.md`, `AGENTS.md`, `USER.md`
- Editor de `profiles/<tenant>/knowledge/*.md`
- CRUD de `source_bindings` e `publish_bindings` do tenant
- CRUD de usuários do tenant
- Telegram/WA: registrar novo `channel_binding` (qual chat_id vira qual user)
- Histórico de aprovações do tenant

### Features compartilhadas
- Login (auth — hoje zero)
- Audit log visível

## Critérios de separação

Por que três painéis em vez de um monolito?

| Dimensão | /ui (operacional) | /ui/yt (mídia) | /admin (config) |
|---|---|---|---|
| Público | usuário final | operador de conteúdo | admin |
| Escrita em config? | ❌ só leitura | ⚠️ bindings do tenant | ✅ tudo |
| Risco de quebrar algo? | baixo | médio | alto |
| Frequência de uso | diário | semanal | mensal/pontual |
| Precisa de auth por papel? | tenant-user | tenant-admin | admin-global + tenant-admin |

Misturar tudo numa tela só cria o efeito "dashboard do Windows 95" —
muito botão, risco alto de clicar errado.

## Pré-requisitos compartilhados

Antes de qualquer painel novo:

1. **Auth** (#10 backlog) — bearer token por papel.
2. **Audit log** (#15 backlog) — toda mudança gravada em `audit_log`.
3. **Postgres** ✅ — já feito (#3 backlog).
4. **RBAC** (#16 backlog) — enforce papel em cada endpoint.

## Tecnologia — decisão pragmática

**Todos os painéis** seguem o padrão do `/ui` atual:
- HTML + CSS + JS inline servidos pelo Gateway
- Zero dependência de build (sem React/Vue no caminho crítico)
- Monaco ou CodeMirror CDN só onde precisa (editor YAML)
- Font stack do sistema, dark theme único

Justificativa: não tenho equipe de frontend; dev quer editar um arquivo
e dar F5. Quando houver equipe/escopo pra SPA real, reimplementa em
React com o mesmo backend.

## Ordem de implementação sugerida

```
FASE 1 (próxima)
├─ /ui melhorias operacionais (2-3 dias)
│  ├─ árvore de stages de uma run
│  ├─ aprovações pendentes do usuário
│  └─ botões de delivery (download ZIP, publicar)

FASE 2
├─ /ui/yt (3-5 dias)
│  ├─ materials + clips + publicações
│  ├─ CRUD de source_bindings e publish_bindings
│  └─ importador de credentials.enc dos yt-pub-lives<N>

FASE 3
├─ Auth + audit log (2-3 dias, pré-requisito do /admin)
└─ /admin (1-2 semanas)
   ├─ editor YAML de config (global + tenant)
   ├─ CRUD de workers
   ├─ editor de receitas
   └─ RBAC per-papel
```

Total: ~3-5 semanas focadas.

## O que fica FORA dos painéis

**Canais conversacionais não são painéis** — Telegram/WhatsApp são
outra interface pra o mesmo sistema. Usuário consegue 80% do que está
no `/ui` via comandos Telegram, sem abrir browser.

Exemplo: `"@imkt4bot aprovar copy do último run"` faz a mesma coisa
que clicar o botão de aprovação no `/ui`.
