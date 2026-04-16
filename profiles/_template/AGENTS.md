# AGENTS — Regras operacionais para este tenant

Comportamento do agente que depende do contexto deste tenant.

## Quando usar tools
- `dispatch_job(worker_type=..., payload=...)` — sempre que o pedido precisar
  de pipeline (geração de imagem, vídeo, TTS, ingest de live). Não tente
  executar trabalho pesado inline.
- `save_memory`, `search_memory`, `forget_memory` — disponíveis; use para
  lembrar fatos relevantes do tenant/usuário.

## Workers permitidos para este tenant
Liste aqui os `worker_type` que este tenant pode invocar. O Gateway valida.
Ex.:
- `inemaimg` — geração de imagem
- `inemavox` — TTS / dublagem
- `yt-pub-lives` — ingestão de canal YouTube

## Limites
- Máximo de jobs simultâneos por usuário.
- Prioridade default.
- Canais habilitados (ex.: só Telegram; ou TG + Web).
