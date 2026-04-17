# Arquitetura do fluxo YouTube / mídia

> **Todas as 7 perguntas fechadas.** Decisões tomadas pelo usuário
> consolidadas abaixo.

## Workers — 4 capabilities

### 1. `sources-import` — ingestão (3 fontes)

Entrada de material pro pipeline. Plugin-based — cada fonte é um fetcher
implementando a mesma interface.

**Três fontes**:

- **1. Upload direto do `imkt4`** — usuário manda arquivo via chat
  (`@imkt4bot`) ou UI. Arquivo vai pra `data/artifacts/<tenant>/<job_id>/`
  e é registrado como `material` na DB.
- **2. Redes sociais** (plugin-based) — scan de canais registrados em
  `source_bindings` do tenant. Fetchers: TikTok (hoje), Instagram Reels,
  YouTube Shorts de canais terceiros (futuros).
- **3. Diretório (filesystem watcher)** — watcher por polling.
  - `profiles/<tenant>/import/` — arquivos entram pro tenant específico.
  - `/var/imkt4/import/` **global** — compatibilidade com o comportamento
    atual do `yt-pub-lives` (inbox compartilhado). Arquivos entram como
    material do tenant "inema" (default configurável); os clips gerados
    se distribuem em sequência entre os `publish_bindings` do tenant
    via `fanout_over` na receita.

**Polling** (não inotify) — tempo configurável:
```yaml
# config/defaults.yaml
sources_import:
  watcher_poll_seconds: 60   # env: IMKT4_WATCHER_POLL
```

Capability: `video.source_ingest` (fanout sobre `source_bindings`).
Cada fetcher roda uma vez por execução, coleta materiais novos, retorna
lista com metadata.

### 2. `yt-transcribe` — transcrição (genérica)

**Worker SEPARADO** — não é exclusivo do yt-cuts. Transcreve qualquer
vídeo/áudio, assim como o `inemavox` já faz hoje.

Capability: `audio.transcribe`, `video.transcribe`.

Input: `{input: <path_or_url>, format: srt|txt|json}`.
Output: transcript file URL.

Uso reutilizável: legendas pra qualquer vídeo, análise de áudio, não
precisa cortar.

### 3. `yt-cuts` — cortes

Recebe material já transcrito, analisa tópicos via LLM, corta clips
com ffmpeg.

Capability: `video.clip_extraction`.

Input: `{material: {path, transcript_url, metadata}, prompt_cortes: str}`.
Output: `{clips: [{path, start, end, topic_title}]}`.

### 4. `yt-metadata` — metadata por plataforma

**Stage intermediário opcional** antes de publicar. LLM gera título,
descrição, tags, capítulos otimizados pra plataforma-alvo. Com
auto-review contra regras (tamanho máximo de título, palavras-chave,
spam check).

Capability: `video.metadata`.

### 5. `yt-publish` — publicação (fanout sobre destinos)

Capability: `video.publish`, `platform.youtube`.

Input: `{clip_path, metadata, destination: PublishBinding}`.
Output: `{youtube_video_id, url, published_at}`.

Fanout automático sobre `$.tenant.publish_bindings` — 1 job por destino.

---

## Decisões (respostas às 7 perguntas)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Diretório de import | **Por tenant + global** com distribuição (como no yt-pub-lives hoje) |
| 2 | Watcher | **Polling**, intervalo configurável via `config/defaults.yaml` |
| 3 | Transcrição | **Worker separado** (`yt-transcribe`) — genérico, pode transcrever qualquer vídeo |
| 4 | Aprovação de clip | **auto_reviewer** com critérios, escalate_to_user em dúvida |
| 5 | Outras redes | **Plugin-based** no `sources-import`; TikTok primeiro, extensível |
| 6 | Metadata de publicação | **Stage intermediário** `yt-metadata` com LLM + auto-review |
| 7 | Migração credenciais | **Adapter lê `.enc`** agora; KMS + migração real depois |

Regra global: **aprovações default = auto_reviewer** (ver `doc/approval-policy.md`).

---

## Fluxo end-to-end

```
╔══════════════════════════════════════════════════════════════════╗
║  1. FONTES DE IMPORT                                             ║
║  ├─ @imkt4bot recebe arquivo          (upload direto)            ║
║  ├─ tiktok_scanner (plugin)           (redes sociais)            ║
║  ├─ watcher profiles/<t>/import/      (diretório per-tenant)     ║
║  └─ watcher /var/imkt4/import/        (diretório global)         ║
║                                                                  ║
║                       ↓ sources-import                           ║
║                                                                  ║
║  DB: materials (tenant_id, source_ref, path, status=ready)       ║
╠══════════════════════════════════════════════════════════════════╣
║  2. TRANSCRIÇÃO                                                  ║
║  yt-transcribe (worker genérico — audio/video.transcribe)        ║
║  material → transcript.srt / .txt / .json                        ║
╠══════════════════════════════════════════════════════════════════╣
║  3. CORTES                                                       ║
║  yt-cuts (LLM analisa transcript → ffmpeg corta)                 ║
║  Auto-review: duração 30-180s, não corta fala                    ║
║  escalate_to_user em dúvida                                      ║
║                                                                  ║
║  DB: clips (material_id, path, topic, status=ready)              ║
╠══════════════════════════════════════════════════════════════════╣
║  4. METADATA (novo stage intermediário)                          ║
║  yt-metadata (LLM gera título + descrição + tags + capítulos)    ║
║  Auto-review: tamanhos, palavras-chave, spam                     ║
╠══════════════════════════════════════════════════════════════════╣
║  5. PUBLICAÇÃO (fanout sobre destinos)                           ║
║  yt-publish — 1 job por PublishBinding ativo do tenant           ║
║  Adapter lê credentials.enc dos yt-pub-lives<N> (curto prazo)    ║
║                                                                  ║
║  DB: publications (clip_id, destination_id, youtube_video_id)    ║
╚══════════════════════════════════════════════════════════════════╝

                          ↕ painel /ui/yt
                          gerencia: materials, clips, publicações,
                          fontes e destinos configurados
```

---

## Receita atualizada

```yaml
# recipes/yt-pipeline.yaml (esboço final)
name: yt-pipeline
version: 5

stages:
  - id: ingest
    requires: video.source_ingest
    fanout_over: $.tenant.source_bindings
    approval: {mode: none}

  - id: transcribe
    requires: video.transcribe
    needs: [ingest]
    fanout_over: $.stages.ingest.output.new_materials
    payload_from:
      input: $.fanout_item.path
    approval: {mode: none}

  - id: cuts
    requires: video.clip_extraction
    needs: [transcribe]
    payload_from:
      materials: $.stages.transcribe.output.outputs[*]
      prompt_cortes: $.tenant.profile.prompts.cortes
    approval:
      mode: auto_reviewer
      criteria:
        - "clip dura 30-180s"
        - "não corta fala no meio"
        - "tem início e fim coerentes"
        - "sem silêncios longos"
      escalation: on_uncertain
      escalate_to_user: true   # dúvida → pergunta no chat

  - id: metadata
    requires: video.metadata
    needs: [cuts]
    payload_from:
      clips: $.stages.cuts.output.clips
    approval:
      mode: auto_reviewer
      criteria:
        - "título ≤ 100 chars"
        - "descrição tem 200+ chars"
        - "tags: mínimo 5, máximo 15"
        - "sem palavras bloqueadas"

  - id: publish
    requires: video.publish
    needs: [metadata]
    fanout_over: $.tenant.publish_bindings
    payload_from:
      clip: $.stages.cuts.output.clips
      metadata: $.stages.metadata.output
      destination: $.fanout_item
    approval: {mode: none}
```

---

## Schema Postgres adicional pro yt-pipeline

Tabelas a criar (depois do schema base):

```sql
CREATE TABLE materials (
    material_id   UUID PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    source        TEXT NOT NULL,          -- 'upload' | 'tiktok' | 'import_dir' | 'global_dir'
    source_ref    TEXT,                   -- ex.: URL original, username TikTok, filename
    path          TEXT NOT NULL,          -- caminho em data/artifacts/ ou s3://
    transcript_url TEXT,
    status        TEXT NOT NULL,          -- 'ready' | 'transcribed' | 'cut' | 'published'
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clips (
    clip_id       UUID PRIMARY KEY,
    material_id   UUID REFERENCES materials(material_id),
    tenant_id     TEXT NOT NULL,
    path          TEXT NOT NULL,
    topic_title   TEXT,
    start_s       REAL,
    end_s         REAL,
    status        TEXT NOT NULL,          -- 'ready' | 'published' | 'failed'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE publications (
    pub_id             UUID PRIMARY KEY,
    clip_id            UUID REFERENCES clips(clip_id),
    destination_id     TEXT NOT NULL,      -- publish_bindings.binding_id
    platform           TEXT NOT NULL,       -- 'youtube' | 'instagram' | ...
    platform_video_id  TEXT,                -- id na plataforma
    url                TEXT,
    status             TEXT NOT NULL,       -- 'pending' | 'success' | 'failed'
    published_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Painel `/ui/yt`

UI de gerenciamento (absorve `yt-pub-lives2/master-dashboard`):

- **Fontes configuradas** (lista + CRUD de `source_bindings`)
- **Destinos configurados** (lista + CRUD de `publish_bindings`)
- **Materiais** — arquivos importados + status
- **Clips** — clips gerados, preview, botão republicar
- **Publicações** — histórico por destino, filtros por data/status
- **Ações manuais**: upload de arquivo, disparar processamento, aprovar clip manual

Rota nova: `GET /ui/yt` dentro do gateway.

---

## Checklist pra retomar

- [ ] Schema Postgres adicional (materials, clips, publications)
- [ ] Worker `sources-import` com 3 fetchers (upload, TikTok, filesystem)
- [ ] Worker `yt-transcribe` (genérico, reutiliza inemavox quando possível)
- [ ] Worker `yt-cuts` (lógica do `scripts/yt-clip` adaptada)
- [ ] Worker `yt-metadata` (novo, LLM gera metadata)
- [ ] Worker `yt-publish` + thumbnail gen (lógica do `scripts/yt-publish`)
- [ ] Adapter `credentials.enc` reader (ler diretórios yt-pub-lives<N>)
- [ ] Receita `yt-pipeline.yaml` em `recipes/`
- [ ] Painel `/ui/yt`
- [ ] Popular `source_bindings` + `publish_bindings` da INEMA no Postgres
