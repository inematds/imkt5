# Arquitetura do fluxo YouTube (em escrita)

> Nota: documento em formação. Usuário está descrevendo a divisão.
> Preenchendo conforme vier informação; campos abertos em `???`.

## Divisão de responsabilidades — 3 workers separados

O fluxo YouTube é decomposto em **3 workers independentes**, mais um
**painel web** que agrega:

### 1. `yt-cuts` — cortes
- **Capability**: `video.clip_extraction`
- **Função**: a partir de um vídeo-fonte (live do YouTube, arquivo
  baixado, ou item de diretório de importação), identifica segmentos
  relevantes e corta em clips.
- **Inputs possíveis**:
  - vídeo direto (arquivo em storage)
  - URL YouTube (baixa antes)
  - item de diretório de importação
- **Output**: lista de clips com `{path, start, end, topic, title_suggestion}`
- **Dependência**: `yt-dlp` (download), `ffmpeg` (corte), LLM (análise de transcrição)
- **Hoje no `yt-pub-lives2`**: `scripts/yt-clip`

### 2. `yt-publish` — publicação
- **Capability**: `video.publish`, `platform.youtube`
- **Função**: dado um clip já cortado + credencial de canal-destino,
  gera thumbnail e publica no YouTube.
- **Input**: `{clip_path, destination: PublishBinding, metadata: {title, description, tags}}`
- **Output**: `{youtube_video_id, url, published_at}`
- **Dependência**: Google OAuth (credentials por `PublishBinding`),
  gerador de thumbnail (Piramyd ou LLM)
- **Hoje no `yt-pub-lives2`**: `scripts/yt-publish` + `scripts/yt-thumbnail`

### 3. `sources-import` — ingestão de fontes (genérico)
- **Capability**: `video.source_ingest`
- **Função**: traz material de entrada pro pipeline. **Três fontes**:
  - **Direto do `imkt4`**: quando o usuário manda arquivo/link via chat ou UI.
  - **Redes sociais** (hoje: TikTok; amanhã: outras): scan de canais registrados.
  - **Diretório de importação**: watcher numa pasta do filesystem que processa arquivos colocados ali.
- **Output**: registra na DB como material disponível para `yt-cuts`.
- **Hoje no `yt-pub-lives2`**: `tiktok_scanner.py` + `import_worker.py`

### 4. Painel web — gerenciador
- **Função**: UI que mostra:
  - materiais importados (de cada fonte)
  - clips cortados (prontos pra publicar)
  - histórico de publicações (por destino)
  - credenciais de destinos configurados (`PublishBinding`)
  - fontes configuradas (canais TikTok monitorados, pastas de watch)
- **Ações manuais**:
  - disparar corte de um material
  - aprovar/rejeitar clip antes de publicar
  - escolher destinos (fanout sobre `PublishBinding` filtrados)
- **Hoje no `yt-pub-lives2`**: `master-dashboard/` (single-tenant, ports hardcoded)
- **No `imkt4`**: seção `/ui/yt` dentro do Gateway Web, multi-tenant

## Fluxo end-to-end (visão atual)

```
[fonte]
  ├─ usuário envia no chat/UI               ─┐
  ├─ TikTok scanner (canais registrados)    ─┤
  └─ diretório de importação (watcher)      ─┤
                                              │
                                              ▼
                                    sources-import
                                    (registra na DB)
                                              │
                                              ▼
                                      [painel web]
                                      usuário seleciona
                                      → dispara corte
                                              │
                                              ▼
                                         yt-cuts
                                         (clips_pronto)
                                              │
                                              ▼
                                      [painel web]
                                      aprova clips,
                                      escolhe destinos
                                              │
                                              ▼
                                   yt-publish (fanout)
                                   um job por destino
```

## Questões em aberto (a usuária vai complementar)

- [ ] Diretório de importação: path fixo ou por tenant?
- [ ] Watcher é poll (cron) ou inotify realtime?
- [ ] Transcrição: dentro do `yt-cuts` ou stage separado?
- [ ] Aprovação de clip: automática (auto-reviewer) ou sempre humana?
- [ ] Outras redes sociais além de TikTok? Instagram Reels? YouTube Shorts importados?
- [ ] Metadata de publicação (título, descrição, tags): gerada no `yt-cuts`, no `yt-publish`, ou numa etapa intermediária (`yt-metadata`)?

## Receita sugerida

Substitui `recipes/yt-clip-publish.yaml` por um modelo mais claro:

```yaml
# recipes/yt-pipeline.yaml (esboço)
name: yt-pipeline
version: 4

stages:
  - id: ingest
    requires: video.source_ingest
    fanout_over: $.tenant.source_bindings
    approval: {mode: none}

  - id: cuts
    requires: video.clip_extraction
    needs: [ingest]
    when: $.stages.ingest.outputs[*].new_materials != []
    payload_from:
      materials: $.stages.ingest.outputs[*].new_materials
    approval:
      mode: auto_reviewer     # ou user, conforme decisão
      criteria: ["clip dura 30-180s", "fala não é cortada"]

  - id: publish
    requires: video.publish
    fanout_over: $.tenant.publish_bindings
    needs: [cuts]
    payload_from:
      clips: $.stages.cuts.output.clips
      destination: $.fanout_item
    approval: {mode: none}
```

## O que precisa ser feito (checklist pra retomar)

- [ ] Esquema Postgres: `source_bindings`, `publish_bindings`,
      `materials` (material ingerido), `clips` (pós-corte),
      `publications` (pós-publish)
- [ ] Worker `sources-import` (substitui `tiktok_scanner.py` +
      `import_worker.py` + upload via UI)
- [ ] Worker `yt-cuts` (substitui `scripts/yt-clip` + lógica de análise)
- [ ] Worker `yt-publish` (substitui `scripts/yt-publish` +
      `scripts/yt-thumbnail`)
- [ ] Painel `/ui/yt` no Gateway Web (absorve `master-dashboard/`)
- [ ] Migração de credenciais OAuth dos 10 clones (adapter pra ler
      `credentials.enc` primeiro; KMS depois — ver `doc/backlog.md` §14)
