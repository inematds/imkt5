# Provider-specific tuning

> Regra geral: **capability abstrai o tipo do trabalho, mas parâmetros e prompts
> são específicos do modelo**. Ao trocar `model:` numa recipe ou no adapter de
> um worker, re-tunar antes de usar.

Válido para qualquer LLM/IA/humano operando o projeto — não é guidance
Claude-específica. CLAUDE.md apenas aponta pra cá.

---

## Por que isso importa

Workers no imkt4 são plugáveis por capability: `image.generation`,
`audio.tts`, `video.render`, `llm.*`, etc. Trocar o modelo subjacente é fácil
(campo `model:` na recipe ou env no adapter). Mas os parâmetros ótimos
**não viajam entre modelos** — copiar `steps: 15` de um SDXL pra um flux2-klein
gera imagem pior *e* mais lenta que o default de 4 steps que o klein foi
treinado pra usar.

Sintomas típicos de não seguir esta regra:
- imagem borrada/ruim + pipeline absurdamente lento (steps altos demais);
- imagem OK mas custo/latência alto sem necessidade;
- prompt "funcionando mal" porque o estilo não bate com o modelo;
- erros silenciosos de schema (campo aceito num provider, ignorado em outro).

---

## Cheatsheet — `image.generation`

| Modelo | `steps` recomendado | `cfg_scale` | Estilo de prompt | Observação |
|---|---|---|---|---|
| `flux2-klein` | **4** | — | linguagem natural rica | destilado, mais steps desperdiça |
| `flux-dev` | 20–28 | 3.5 | linguagem natural | |
| `SDXL` / `SDXL-turbo` | 25–40 / 1–4 | 6–8 / 1–2 | tags + pesos `(detailed:1.2)` | turbo é destilado |
| `SD 1.5` | 20–30 | 7–9 | tags + pesos | legado |
| `qwen-edit-2511` | (N/A p/ edit) | — | instrução em PT ok | modo edit, não txt2img puro |
| `DALL-E 3` | — | — | prompt natural; API reescreve | sem `steps` expostos |

## Cheatsheet — `audio.tts`

| Engine | `voice` | Observação |
|---|---|---|
| `edge` | `pt-BR-AntonioNeural` etc | rápido, grátis; limitado em expressividade |
| `chatterbox` | voice clone | precisa sample de referência; ótimo p/ dublagem |
| ElevenLabs | id da voz | melhor qualidade; custa por char |

Prompt style: `edge` é pura leitura literal; chatterbox responde a tags SSML-like
em alguns modos; ElevenLabs aceita `stability`/`similarity_boost` que mudam muito
o resultado.

## Cheatsheet — `llm.*` (auto-reviewer, brief, copy…)

| Provider | Modelo default | Temperatura sugerida | Formato de prompt |
|---|---|---|---|
| Claude (via OAuth/CLI) | Opus/Sonnet atual | 0.3–0.7 | XML tags funcionam bem |
| Ollama | `qwen2.5:14b` | 0.2–0.5 | ChatML; evitar instruções longas |
| OpenRouter | `google/gemini-2.0-flash-exp:free` | 0.3–0.5 | prompt direto, evita system longo |

Fallback chain configurada em `.env`:
`LLM_CHAIN=claude_code,ollama,openrouter`.

---

## Onde ajustar

Ao mudar um modelo, revisar **sempre estas 3 camadas**:

1. **Recipes** — `recipes/*.yaml`, campo `payload_from` do stage.
   - Ex.: `recipes/carrossel-simples.yaml` → stage `images` → `steps: 4`.
2. **Adapter do worker** — `workers/<name>/server.py`, defaults do request
   quando o payload não traz.
   - Ex.: `workers/inemaimg-adapter/server.py` → `INEMAIMG_MODEL` env +
     fallback no código.
3. **UI defaults** — `imkt4/gateway/web_ui.py` → `CAP_CONFIG`.
   - Ex.: `image.generation` → `{model: "flux2-klein", steps: 4, ...}`.
   - Esses viram o payload inicial quando a UI cria um job sem override.

Se o default do modelo muda entre providers, **a camada mais específica ganha**
(recipe > UI > adapter fallback).

## Procedimento ao trocar um modelo

1. Ler docs oficiais do novo provider (`steps`, `cfg`, `sampler`, formato de prompt).
2. Atualizar o default na camada certa (ver acima).
3. Reescrever prompts se o novo modelo interpreta diferente (ex.: migrar de SDXL
   pra Flux → tirar pesos `(x:1.2)` e reescrever em linguagem natural).
4. Validar qualidade visual/auditiva com 1 run real antes de deployar.
5. Anotar nova linha no cheatsheet acima (este arquivo).

---

## Caso recente — `flux2-klein` steps=4

O modelo `flux2-klein` é um flux destilado treinado pra convergir em ~4 steps.
Usar `steps: 15+` nele:
- não melhora qualidade (saturou em 4);
- triplica o tempo de geração por imagem;
- em recipes com `parallel` alto, triplica a carga do GPU.

Default correto em todas as camadas:
- `recipes/carrossel-simples.yaml` → `steps: 4` ✓
- `imkt4/gateway/web_ui.py` CAP_CONFIG — **verificar/fixar** se ainda tem 15.

Referência descoberta em 2026-04-18.
