# Mapeamento de APIs — inemaimg e inemavox

> Relatório da exploração de código feita para construir os adapters do
> `imkt5`. **Capturado em 2026-04-16**; validar antes de mudanças maiores.

## inemaimg

**Stack**: FastAPI + diffusers (HuggingFace). Modelos carregados on-demand
com `asyncio.Lock` pra serializar gerações (evita OOM).

**Porta default**: `8000` (no `Dockerfile`: `--port 8000`).

### Rotas relevantes

| Método | Path | Shape |
|---|---|---|
| `POST` | `/generate` | gera imagem síncrono; body + response abaixo |
| `GET`  | `/health` | status, modelo carregado, GPU memory |
| `GET`  | `/models` | lista modelos no registry + o ativo |
| `POST` | `/models/load` | pré-carrega um modelo (evita cold start) |

### `POST /generate` — contrato

Request body (`GenerateRequest`):

```json
{
  "model": "qwen-edit-2511",      // obrigatório
  "prompt": "...",                  // obrigatório
  "images": ["base64-png1", "..."], // só se model=qwen-edit-2511
  "steps": 40,
  "guidance_scale": 1.0,
  "true_cfg_scale": 4.0,
  "negative_prompt": "",
  "width": 1024, "height": 768,
  "seed": 42,
  "lora": "multiple-angles",
  "lora_weight": 1.0
}
```

Response:

```json
{
  "image": "base64-png",
  "model_used": "qwen-edit-2511",
  "generation_time_s": 12.5,
  "gpu_memory_allocated_gb": 35.2
}
```

Tempo típico: **10–60s** por imagem. Output é **base64 inline** (não salva
em disco, não devolve URL).

### Modelos no registry

```python
REGISTRY = {
    "qwen-edit-2511": QwenEditLoader,   # edit model (requer images[])
    "ernie": ErnieLoader,                # text-to-image
    "flux2-klein": Flux2KleinLoader,     # FLUX.2 Non-Comm
    "flux2-dev": Flux2DevLoader,         # FLUX.2 Non-Comm
}
```

---

## inemavox

**Stack**: FastAPI + **job queue assíncrona**. Requisições criam job,
devolvem `job_id`, cliente faz polling ou subscribe via WebSocket.

**Porta default**: `8000` (no `api/server.py:976`).

**Workers internos**: `chatterbox_tts_worker.py`, `chatterbox_vc_worker.py`,
`baixar_v1.py`, `clipar_v1.py`, `dublar_pro_v5.py`. Tudo via subprocess.

### Padrão de uso

```
POST /api/jobs/<op>   →  {"id": "abc", "status": "queued"}
GET  /api/jobs/abc    →  status atualizado
GET  /api/jobs/abc/<asset>  →  download (wav/mp4/srt/zip)
WS   /ws/jobs/abc     →  eventos em tempo real
```

### Operações

| Método | Path | Descrição |
|---|---|---|
| `POST` | `/api/jobs/tts` | TTS simples; body `{text, engine, lang}` |
| `POST` | `/api/jobs/tts/upload` | TTS com voice clone (multipart) |
| `POST` | `/api/jobs/voice-clone` | VC com áudio de referência local |
| `POST` | `/api/jobs/voice-clone/url` | VC baixando ref de URL (yt-dlp) |
| `POST` | `/api/jobs/cut` | Corte de clips (timestamps) |
| `POST` | `/api/jobs/cut/upload` | Corte com upload de vídeo |
| `POST` | `/api/jobs/download` | Baixa vídeo/áudio de URL |
| `POST` | `/api/jobs/transcribe` | Whisper (srt/txt/json) |
| `POST` | `/api/audio/search` | busca Freesound (music/SFX) |
| `POST` | `/api/audio/download` | baixa preview do Freesound |
| `GET`  | `/api/jobs` | lista |
| `GET`  | `/api/jobs/{id}` | status |
| `GET`  | `/api/jobs/{id}/logs?last_n=100` | logs |
| `DELETE` | `/api/jobs/{id}?delete=true` | cancela/apaga |
| `POST` | `/api/jobs/{id}/retry` | reexecuta |
| `WS`   | `/ws/jobs/{id}` | eventos |

### `POST /api/jobs/tts` — contrato

```json
// request
{"text": "Olá mundo", "engine": "edge", "lang": "pt"}

// response
{"id": "abc123", "status": "queued", ...}
```

Download após `status == "completed"`:

```
GET /api/jobs/abc123/audio  →  wav/mp3
```

### Output em disco

```
jobs/{job_id}/
├── audio_out/generated.{wav|mp3}          (TTS, VC)
├── clips/clip_001.mp4, clips.zip          (cut)
├── transcription/transcript.{srt|txt|json}(transcribe)
└── dublado/dubbed.mp4                     (dublar)
```

---

## Implicações para os adapters do `imkt5`

### Colisão de porta em dev local

Ambos usam **8000** por default. Soluções possíveis:

1. Rodar só um por vez (dev casual).
2. Configurar `uvicorn --port ...` distinto para cada.
3. Docker compose separando em containers.

Os adapters do `imkt5` usam `INEMAIMG_URL` e `INEMAVOX_URL` — qualquer
endpoint funciona.

### Shape do adapter → backend

**inemaimg-adapter** (sync, trivial):

```
imkt5 Job → POST inemaimg/generate → base64 → upload MinIO → devolve URL
```

**inemavox-adapter** (async, mais trabalho):

```
imkt5 Job → POST inemavox/api/jobs/tts → job_id
          → poll GET inemavox/api/jobs/{id}  até completed
          → GET  inemavox/api/jobs/{id}/audio → bytes
          → upload MinIO → devolve URL
```

Ambos escondem a diferença do Gateway. Do ponto de vista do Recipe Runner
ou do Quick Dispatch, é sempre "capability → URL de artefato em S3".

### O adapter precisa de storage

Para não depender de passar base64 pelos canais (Telegram/WA/Web), adapters
fazem upload do artefato em MinIO e devolvem URL. Isso já está no contrato
dos Jobs (`output.image_url`, `output.audio_url`).

Enquanto MinIO não está rodando, adapters podem:
- Salvar arquivo local em `data/artifacts/{tenant}/{job_id}/...`
- Devolver `file://` path no output

Faço essa gradação: dev local usa filesystem, prod usa MinIO/S3. Controlado
por `S3_ENDPOINT` no `.env`.
