# TikTok Ingest

## Role

Detecta **vídeos novos** num perfil TikTok via `yt-dlp --flat-playlist`
(não precisa API oficial — scraping da página pública). Cache de IDs
já vistos em memória (TODO: Postgres).

Capability: `video.source_ingest` (mesma do yt-source-ingest — prioridade
por worker resolve). Porta 8303.

## Input

```json
{
  "source": {
    "binding_id": "t1",
    "external_id": "@handle_tiktok"
  },
  "since_hours": 24,
  "max_videos": 10
}
```

## Output

```json
{
  "channel_id": "@handle",
  "new_lives": [
    {"video_id": "1234567...", "title": "...", "url": "..."}
  ],
  "total_new": N,
  "mode": "real" | "mocked"
}
```

Sem `yt-dlp` no PATH: modo mocked.
