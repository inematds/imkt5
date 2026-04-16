# QUICKSTART — testar o `imkt4` end-to-end

> Como subir tudo, mandar requisições e ver respostas em ~5 minutos.

## Pré-requisitos

- **Python 3.11+** e venv pronto (`.venv/`)
- **Ollama local** rodando (`ollama serve`) com `qwen2.5:14b` instalado
  → necessário para `auto-reviewer`
- (opcional) **inemaimg** rodando em `http://localhost:8000`
  → necessário para `image.generation`
- (opcional) **inemavox** rodando em `http://localhost:8010`
  → necessário para `audio.tts`/`audio.dubbing`

`Tavily` (research) é remoto — só precisa da chave em `.env`.

## 1. Subir tudo

```bash
./scripts/start-dev.sh
```

Saída esperada:

```
── workers ──────────────────────────────────────────
  ✓ auto-reviewer (pid …, log: logs/auto-reviewer.log)
  ✓ research (pid …)
  ✓ inemaimg-adapter (pid …)        # se inemaimg upstream responder
  ✓ inemavox-adapter (pid …)        # se inemavox upstream responder
── gateway ──────────────────────────────────────────
  ✓ gateway (pid …, log: logs/gateway.log)
✓ gateway OK em http://localhost:8080
```

Para parar tudo:

```bash
./scripts/stop-dev.sh
```

## 2. Inspecionar o que está disponível

```bash
# Lista todos os workers e estado de saúde
curl -s http://localhost:8080/workers | python3 -m json.tool

# Lista capabilities oferecidas e por quem
curl -s http://localhost:8080/capabilities | python3 -m json.tool
```

## 3. Quick dispatch — pedidos simples (sem receita)

### a) Pesquisa de mercado (Tavily real)

```bash
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "user_id": "u1",
    "capability": "research.market",
    "payload": {
      "queries": ["tendências café gelado brasil 2026"],
      "max_results_per_query": 3
    }
  }'
```

Resposta:

```json
{"job_id": "abc-123-..."}
```

Resultado fica nos logs do worker:

```bash
tail -20 logs/research.log
```

### b) Geração de imagem (inemaimg flux2-klein, real)

Pré-requisito: `inemaimg` rodando em `localhost:8000`.

```bash
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "user_id": "u1",
    "capability": "image.generation",
    "payload": {
      "model": "flux2-klein",
      "prompt": "a happy capybara sipping iced coffee on a sunny beach",
      "steps": 15,
      "width": 512,
      "height": 512
    }
  }'
```

Aguarde ~10–15s. Imagem é salva em:

```
data/artifacts/demo/<job_id>/flux2-klein-<job_id>.png
```

Modelos disponíveis (no inemaimg upstream): `qwen-edit-2511`, `ernie`,
`flux2-klein`, `flux2-dev`. O default é o `INEMAIMG_MODEL` do `.env`.

### c) Aprovação automática por LLM (Ollama local)

```bash
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "user_id": "u1",
    "capability": "review.auto",
    "payload": {
      "criteria": [
        "o texto está em português",
        "o texto menciona café",
        "o texto tem pelo menos 20 caracteres"
      ],
      "artifacts": {
        "narrative": "Lançamento do café gelado cremoso, perfeito para o verão."
      }
    }
  }'
```

Worker decide `approved` / `rejected` / `uncertain` com justificativa
por critério. Veja saída em:

```bash
tail -10 logs/auto-reviewer.log
```

### d) TTS (inemavox)

Pré-requisito: `inemavox` rodando em `localhost:8010`.

```bash
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "user_id": "u1",
    "capability": "audio.tts",
    "payload": {
      "text": "Olá, este é um teste do imkt4.",
      "engine": "edge",
      "lang": "pt"
    }
  }'
```

Áudio sai em `data/artifacts/demo/<job_id>/tts-<job_id>.wav`.

## 4. Receitas — fluxos compostos

### a) `simple-carrossel` (gera 2 imagens em paralelo)

```bash
curl -s -X POST http://localhost:8080/recipes/simple-carrossel/run \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "user_id": "u1",
    "input": {
      "prompt": "minimalist coffee shop illustration",
      "model": "flux2-klein",
      "title": "Demo Carrossel"
    }
  }'
```

Resposta: `{"run_id": "..."}`. Consulta de status:

```bash
curl -s http://localhost:8080/runs/<run_id> | python3 -m json.tool
```

Stages do run: `images` (parallel: 2 → 2 PNGs gerados) →
`carrossel` (composição final, requer worker `design.carousel` —
ainda não implementado, vai falhar nessa fase).

### b) `campanha-marketing` (composição completa)

Roda os 12 stages mas a maioria vai SKIPPED porque os workers de
copywriter, ad-designer, video-pro, platforms ainda não estão
implementados. É a base pro porte da Fase 3.

### c) `yt-clip-publish`

Idem — depende dos workers de YT que serão portados na Fase 4.

## 5. Listar workers e capacidade

```bash
curl -s http://localhost:8080/workers | python3 -c "
import sys, json
ws = json.load(sys.stdin)
print(f'{\"nome\":25s} {\"saúde\":10s} {\"in_flight\":10s} capabilities')
for w in ws:
    print(f'{w[\"name\"]:25s} {w[\"health\"]:10s} {w[\"in_flight\"]:<10d} {w[\"capabilities\"]}')
"
```

## 6. Parar e reiniciar

```bash
./scripts/stop-dev.sh
./scripts/start-dev.sh
```

Logs ficam em `logs/<servico>.log`. PIDs em `logs/<servico>.pid`.

## O que JÁ funciona end-to-end (testado)

| Capability | Worker | Provider real | Status |
|---|---|---|---|
| `research.market` | research | Tavily API | ✅ retornando fontes web reais |
| `image.generation` | inemaimg-adapter | inemaimg upstream (`flux2-klein`) | ✅ PNG salvo no disco |
| `review.auto` | auto-reviewer | Ollama local (`qwen2.5:14b`) | ✅ approve/reject com justificativa |
| `audio.tts`/`dubbing`/`transcribe` | inemavox-adapter | inemavox upstream | ✅ adapter pronto, depende do upstream rodar |

## O que está PENDENTE (Fase 3+)

- `copywriter`, `creative-brief`, `ad-designer`, `video-quick`,
  `video-pro`, `platform-*`, `distribution` — porte dos agentes do
  `timesmkt3`.
- `yt-source-ingest`, `yt-clip`, `yt-publish`, `tiktok-ingest` — porte
  dos `yt-pub-lives*`.
- Canais conversacionais (Telegram/WhatsApp/Web) — Fase 5.
- Postgres pra estado de runs (hoje em memória, perde no restart).
- KMS de credenciais (hoje `.env` direto).

## Solução de problemas

**"address already in use"** — algum processo zombie. Rode
`./scripts/stop-dev.sh` e cheque com `ss -tlnp | grep :PORT`.

**Worker mostra `health: degraded http 404`** — o `/health` da URL não
respondeu 200. Normal para alguns serviços remotos. Não impede uso
se houver outro worker para a capability.

**Job aceito mas "nunca volta"** — quick dispatch é fire-and-forget.
Veja `logs/gateway.log` (procura `✗`) e `logs/<worker>.log` para
encontrar o erro.

**Recipe `failed=True`** — algum stage não tem worker disponível para
sua capability. Confirme em `/capabilities` que existe alguém
oferecendo `requires:` da receita.
