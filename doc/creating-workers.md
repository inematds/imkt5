# Criando um worker novo

Um worker é um **serviço HTTP independente** que:

1. Expõe `GET /health` (liveness/readiness + metadata)
2. Expõe `POST /execute` (recebe Job, devolve resultado)
3. Declara suas **capabilities** em `config/workers.yaml`

O restante é livre — pode ser Python, Node, Go, qualquer coisa que fale HTTP.
O `BaseWorker` em `workers/_base/worker.py` já resolve 95% do boilerplate pra Python.

## Quando criar um worker?

| Situação | Cria worker |
|---|---|
| Integrar uma API nova (ElevenLabs, OpenAI, um modelo local) | ✅ sim |
| Adicionar uma capability que ainda não existe (`video.caption`, `image.upscale`) | ✅ sim |
| Rodar múltiplas instâncias do mesmo worker pra paralelismo | ❌ não cria worker novo — registra a instância nova em `config/workers.yaml` apontando pra outra porta/endpoint |
| Variar prompts/defaults por cliente | ❌ não — isso é `profiles/<tenant>/config.yaml` |

## Receita: criar um worker Python em 5 passos

Vamos criar um worker fictício `meme-generator` que oferece a capability `image.meme`.

### 1. Estrutura de diretório

```
workers/meme-generator/
├── server.py          # o worker
├── SKILL.md            # (opcional) prompt/instruções se usa LLM
├── Dockerfile          # (opcional) pra deploy
└── requirements.txt    # (opcional) deps extras
```

### 2. `server.py`

```python
from __future__ import annotations

import os
from typing import Any

import httpx

from workers._base import BaseWorker
from workers._base.storage import get_storage


class MemeGeneratorWorker(BaseWorker):
    name = "meme-generator"
    capabilities = ("image.meme",)

    async def handle(self, job) -> dict[str, Any]:
        text_top = job.payload.get("text_top", "")
        text_bottom = job.payload.get("text_bottom", "")
        template = job.payload.get("template", "drake")

        if not text_top and not text_bottom:
            raise ValueError("payload precisa de text_top ou text_bottom")

        # ... lógica de gerar o meme (chamar imgflip API, ou PIL local, etc) ...
        image_bytes: bytes = b"..."  # resultado

        url = get_storage().save_bytes(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=f"meme-{job.job_id}.png",
            data=image_bytes,
        )
        return {
            "image_url": url,
            "template": template,
        }


if __name__ == "__main__":
    import os
    from imkt4.config import load
    # config central: defaults.yaml → workers.meme_generator.port
    default_port = 8300
    port = int(os.environ.get("MEME_GENERATOR_PORT", default_port))
    MemeGeneratorWorker().run(port=port)
```

Padrão importante:
- `name` e `capabilities` são **class attributes**, o BaseWorker usa no `/health`
- `handle(job)` recebe `Job` canônico (já validado); retorna dict
- Erros viram HTTP 500 automaticamente via BaseWorker
- Storage usa o helper `get_storage()` (dev = file local, prod = S3)

### 3. Adicionar em `config/workers.yaml`

```yaml
- name: meme-generator
  capabilities: [image.meme]
  endpoint: http://localhost:8300
  local: true
  priority: 100
  timeout_seconds: 30
  max_concurrent: 4
```

Restart o gateway — ele descobre o worker no boot:

```bash
./scripts/stop-dev.sh && ./scripts/start-dev.sh
```

Confirme:

```bash
curl http://localhost:8080/capabilities | grep image.meme
# "image.meme": ["meme-generator"]
```

### 4. Adicionar em `scripts/start-dev.sh` (opcional)

Pra subir o worker junto com o resto:

```bash
start_bg "meme-generator" "$VENV" workers/meme-generator/server.py
```

### 5. Testar

```bash
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "capability": "image.meme",
    "payload": {"text_top": "quando", "text_bottom": "o worker funciona"}
  }'
```

Na UI (`/ui`), o `meme-generator` aparece no painel de workers com status healthy; a capability `image.meme` aparece no dropdown.

## Worker que usa Claude CLI (agente via SKILL.md)

Porte de agentes do timesmkt3 — cada agente vira worker. Shape:

```python
# workers/copywriter/server.py
import subprocess
from pathlib import Path
from workers._base import BaseWorker

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class CopywriterWorker(BaseWorker):
    name = "copywriter"
    capabilities = ("copy.narrative", "copy.headlines")

    def __init__(self):
        self.skill_md = SKILL_PATH.read_text()

    async def handle(self, job):
        brief = job.payload.get("brief")
        if not brief:
            raise ValueError("precisa de 'brief'")

        # monta prompt usando SKILL.md + contexto do tenant
        tenant_profile = await _load_tenant_profile(job.tenant_id)
        prompt = f"{self.skill_md}\n\n## BRIEF\n{brief}\n\n## TENANT\n{tenant_profile}"

        # spawn Claude CLI (ou OpenAI, ou Ollama — seu call)
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "sonnet"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        return {
            "narrative": result.stdout.strip(),
            "skill_version": "copywriter@1.0",
        }

    # ...
```

O `SKILL.md` é **copiado** de `timesmkt3/skills/copywriter-agent/SKILL.md` e ajustado (remover `${project_dir}/outputs/`, adicionar placeholder `${tenant_profile}`).

## Worker que só faz wrapper de HTTP externo

Muitos workers são só tradução: Gateway → API externa → MinIO. Exemplo:

```python
class ElevenLabsAdapter(BaseWorker):
    name = "elevenlabs-adapter"
    capabilities = ("audio.tts",)

    async def handle(self, job):
        text = job.payload["text"]
        voice_id = job.payload.get("voice_id", DEFAULT_VOICE)

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                json={"text": text},
            )
            r.raise_for_status()
            audio = r.content

        url = get_storage().save_bytes(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            filename=f"tts-{job.job_id}.mp3",
            data=audio,
        )
        return {"audio_url": url}
```

Padrão `inemaimg-adapter` e `inemavox-adapter` é esse.

## Checklist antes de declarar pronto

- [ ] `GET /health` responde 200 com `{"name":"...","capabilities":[...]}`
- [ ] `POST /execute` aceita o `Job` e retorna `{"job_id":...,"status":"success","output":{...}}`
- [ ] Worker é **stateless** (não guarda memória entre jobs)
- [ ] Usa `get_storage()` pra artefatos (não escreve em path hardcoded)
- [ ] `max_concurrent` em `config/workers.yaml` reflete a realidade do upstream (se upstream serializa, `max_concurrent: 1`)
- [ ] Registrado em `config/workers.yaml` + (opcional) `scripts/start-dev.sh`
- [ ] Documentado no README ou em `doc/`

## Anti-padrões

- ❌ **Clonar o código do worker** pra rodar múltiplas instâncias. Em vez disso, registre N entradas no `config/workers.yaml` apontando pra portas/máquinas diferentes.
- ❌ **Worker com estado persistente em disco local**. Se precisa persistir, usa Postgres ou S3.
- ❌ **Worker que conhece outros workers**. Se precisa compor várias capabilities, isso é trabalho de **receita**, não de worker.
- ❌ **Escrever em `prj/<cliente>/outputs/`** (padrão do timesmkt3). No imkt4, tudo passa pelo storage helper com `tenant_id`.
