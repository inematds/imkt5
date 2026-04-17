# YT Publish

## Role

Publica um vídeo (mp4 local ou URL) em um canal YouTube via YouTube
Data API v3 (videos.insert — upload resumable).

Capability: `video.publish`, `platform.youtube`. Porta 8302.

---

## Input

```json
{
  "clip_path": "/artifacts/.../clip_00.mp4",
  "destination": {
    "binding_id": "d1",
    "external_id": "UC_canal_destino",
    "credentials_ref": "yt-channel-d1"   // opcional (KMS)
  },
  "title": "Título",
  "description": "...",
  "tags": ["tag1"],
  "privacy": "unlisted",   // public|unlisted|private
  "category": "22"
}
```

Se `_fanout_item` estiver presente (fanout sobre `publish_bindings`),
usa ele como `destination`.

## Output

```json
{
  "video_id": "XYZ",
  "video_url": "https://youtu.be/XYZ",
  "mode": "real" | "mocked"
}
```

---

## Credenciais

OAuth 2.0 com refresh token por canal. Lookup via:
1. `credentials_ref` → KMS local (`data/secrets/<ref>.enc`)
2. Fallback env: `YT_CHANNEL_<binding_id>_REFRESH_TOKEN`
3. Sem credenciais → modo mocked (simula upload, não publica).
