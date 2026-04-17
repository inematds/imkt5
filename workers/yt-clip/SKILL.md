# YT Clip

## Role

Extrai **clipes curtos** (2-15 min) de uma live/vídeo do YouTube usando
LLM pra identificar melhores trechos e ffmpeg pra cortar.

Capability: `video.clip_extraction`. Porta 8301.

Pipeline por vídeo:
1. `yt-dlp` baixa o vídeo (formato best mp4)
2. `youtube-transcript-api` puxa transcrição + timestamps
3. LLM (chain `claude_code → ollama → openrouter`) analisa
   transcrição + `prompt` do tenant e sugere N trechos como
   `[{start_s, end_s, title, reason}]`.
4. `ffmpeg -ss <start> -to <end>` corta cada trecho.
5. Retorna paths (via storage) dos clips gerados.

---

## Input

```json
{
  "lives": [
    {"video_id": "abc123", "title": "..."}
  ],
  "prompt": "Corte os 3 trechos mais interessantes sobre AI",
  "min_duration": 120,
  "max_duration": 900,
  "max_clips": 3
}
```

## Output

```json
{
  "video_id": "abc123",
  "clips": [
    {
      "clip_path": "/artifacts/.../clip_01.mp4",
      "start_s": 340, "end_s": 520,
      "title": "Sobre AI prática",
      "reason": "..."
    }
  ],
  "mode": "real" | "mocked"
}
```

Se `lives` vem vazio ou faltam dependências (`yt-dlp`/`ffmpeg`), roda
em modo mocked (retorna `clips: []`).
