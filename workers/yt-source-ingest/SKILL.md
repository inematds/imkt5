# YT Source Ingest

## Role

Detecta **novas lives/vídeos** num canal source do YouTube desde a
última varredura. Usa YouTube Data API v3 (uploads playlist) +
cache de IDs já vistos (via Postgres `seen_videos`).

Capability: `video.source_ingest`. Porta 8300.

Este worker NÃO baixa vídeo — só retorna lista de `video_ids` novos
pra próximo stage (`yt-clip`) processar.

---

## Input

```json
{
  "source": {
    "binding_id": "s1",
    "external_id": "UC_canal_id_youtube",
    "credentials_ref": "youtube-api-v3"  // opcional — KMS lookup
  },
  "since_hours": 24   // opcional, default 24
}
```

Se `_fanout_item` estiver no payload (fanout da receita), usa ele como
`source`.

## Output

```json
{
  "channel_id": "UC...",
  "new_lives": [
    {"video_id": "abc123", "title": "...", "published_at": "..."}
  ],
  "total_new": 1,
  "mode": "real" | "mocked"
}
```

---

## Credenciais

- `YOUTUBE_API_KEY` env var (YouTube Data API v3 — quota 10k/dia).
- Alternativa via KMS: `credentials_ref` no source — resolve pra API key.

Se ausente, roda em **modo mocked** — retorna lista vazia ou um video
de exemplo, permite pipeline rodar sem quebrar.
