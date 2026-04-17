# Criando uma receita

Uma receita é um YAML em `recipes/` que descreve um **fluxo composto** — vários jobs encadeados com dependências, paralelismo e aprovações. O Recipe Runner lê o YAML e despacha os jobs na ordem certa.

## Quando criar uma receita?

| Situação | Usa receita |
|---|---|
| 1 pedido = 1 capability (gerar imagem, TTS, pesquisa) | ❌ use **Quick Dispatch** (`POST /jobs`) |
| 2+ capabilities encadeadas (pesquisa → copy → imagem) | ✅ receita |
| Precisa de **aprovação humana** no meio | ✅ receita |
| Precisa de **paralelismo** (ex.: gerar 5 imagens e 1 áudio ao mesmo tempo) | ✅ receita |
| Precisa de **fanout** sobre bindings do tenant (publicar em N canais) | ✅ receita |

## Anatomia de uma receita

```yaml
name: minha-receita           # identificador único (usado em POST /recipes/<name>/run)
version: 1                     # opcional; bump quando mudar shape do input

stages:
  - id: <stage_id>             # único na receita
    requires: <capability>     # OU worker: <nome>, OU fanout_over_capabilities: [...]
    needs: [<outro_stage>]     # dependências — só dispara depois que os needs completarem
    when: <expressão>           # opcional — skip se falsa
    parallel: 1                # N execuções em paralelo (default 1)
    fanout_over: <path_list>   # OU — 1 job por item da lista
    payload_from:              # monta o payload do job a partir do contexto
      key1: $.input.algo
      key2: $.stages.outro.output.campo
    approval:                   # opcional — gate ao fim do stage
      mode: none | user | human_reviewer | auto_reviewer
      timeout: 1800
      reviewer_role: content_supervisor    # pra human_reviewer
      criteria: ["..."]                      # pra auto_reviewer
      escalation: on_uncertain
```

### Expressões suportadas em `payload_from`, `when`, `fanout_over`

Contexto disponível:
- `$.input.<k>` — o input passado no `POST /recipes/<name>/run`
- `$.tenant.<path>` — config do tenant (brand, bindings, reviewers, prompts)
- `$.stages.<stage_id>.output.<k>` — output de um stage anterior
- `$.stages.<stage_id>.output.outputs[*].<k>` — para stages com `parallel` ou `fanout`, extrai campo de cada job
- `$.fanout_item` — só dentro de stage com `fanout_over` — o item atual

Operadores em `when`: `==`, `!=`, `>`, `<`, `>=`, `<=`. Valores booleanos/numéricos/strings.

## Exemplo 1 — Receita minimalista (2 stages)

Gera imagem e depois roda uma revisão automática nela.

```yaml
# recipes/image-with-review.yaml
name: image-with-review
version: 1

stages:
  - id: gen
    requires: image.generation
    payload_from:
      prompt: $.input.prompt
      model: flux2-klein
    approval: {mode: none}

  - id: review
    requires: review.auto
    needs: [gen]
    payload_from:
      criteria: ["imagem tem boa composição", "cores vibrantes"]
      artifacts:
        image_url: $.stages.gen.output.image_url
```

Rodar:

```bash
curl -X POST http://localhost:8080/recipes/image-with-review/run \
  -H "Content-Type: application/json" \
  -d '{"input":{"prompt":"capivara chef cozinhando"}}'
```

## Exemplo 2 — Paralelismo + aprovação humana

```yaml
# recipes/ads-package.yaml
name: ads-package
version: 1

stages:
  - id: images
    requires: image.generation
    parallel: 3                      # gera 3 imagens (mesmo prompt, seeds diferentes se worker suporta)
    payload_from:
      prompt: $.input.prompt
      model: flux2-klein

  - id: voiceover
    requires: audio.tts
    payload_from:
      text: $.input.voiceover_script

  - id: review
    requires: review.auto
    needs: [images, voiceover]         # espera AMBOS terminarem
    payload_from:
      criteria: ["artefatos fazem sentido juntos"]
      artifacts:
        images: $.stages.images.output.outputs[*].image_url
        audio: $.stages.voiceover.output.audio_url
    approval:
      mode: user                       # o solicitante aprova no chat
      timeout: 3600
```

## Exemplo 3 — Fanout sobre bindings do tenant

```yaml
# recipes/publish-everywhere.yaml
name: publish-everywhere
version: 1

stages:
  - id: create_clip
    requires: video.clip_extraction
    payload_from:
      source_url: $.input.video_url

  - id: publish
    requires: video.publish
    needs: [create_clip]
    fanout_over: $.tenant.publish_bindings   # 1 job por destino configurado no tenant
    payload_from:
      clip: $.stages.create_clip.output.clip_path
      destination: $.fanout_item               # cada job recebe um binding diferente
```

Se o tenant tem 3 `publish_bindings` em `profiles/<tenant>/config.yaml`, esse stage dispara 3 jobs em paralelo.

## Exemplo 4 — Condicional com `when`

```yaml
stages:
  - id: research
    requires: research.market
    when: $.input.with_research == true        # pula se input.with_research for falso
    payload_from:
      queries: [$.input.topic]
```

## Exemplo 5 — Fanout por capability

```yaml
stages:
  - id: platforms
    fanout_over_capabilities:       # um job por capability listada
      - platform.instagram
      - platform.youtube
      - platform.tiktok
    needs: [video]
    payload_from:
      video: $.stages.video.output
```

## Como testar

```bash
# 1) validar que carrega sem erro
.venv/bin/python -c "
from imkt4.recipes import load_recipe
r = load_recipe('recipes/minha-receita.yaml')
print(f'OK: {r.name} v{r.version} — {len(r.stages)} stages')
"

# 2) rodar e acompanhar
RUN=$(curl -s -X POST http://localhost:8080/recipes/minha-receita/run \
  -H "Content-Type: application/json" \
  -d '{"input":{"prompt":"teste"}}')
RID=$(echo "$RUN" | python3 -c "import sys,json;print(json.load(sys.stdin)['run_id'])")

# 3) status
curl -s http://localhost:8080/runs/$RID | python3 -m json.tool
```

## Aprovações — os três modos

| Mode | Quem decide | Use quando |
|---|---|---|
| `none` | ninguém (auto-approve) | stage é trivial, output não crítico |
| `user` | o solicitante original | decisão criativa/subjetiva; o dono do pedido precisa olhar |
| `human_reviewer` | humano designado por role | workflow com revisor dedicado (supervisor, compliance) |
| `auto_reviewer` | worker `auto-reviewer` (LLM) | decisão objetiva com critérios declaráveis |

`auto_reviewer` aceita `criteria: ["regra 1", "regra 2"]` e devolve `approved | rejected | uncertain`. Em `uncertain`, escalona se `escalation: on_uncertain`.

## Boas práticas

1. **Um stage = uma capability** (ou fanout). Se precisa de 3 coisas diferentes, cria 3 stages.
2. **Paralelize** sempre que possível (`parallel`, `fanout_over`). Jobs independentes não devem ser sequenciais.
3. **Aprovação opcional**. Default = `none`. Só adiciona quando o erro custa caro.
4. **Research opt-in**. Use `when: $.input.with_research == true` pra deixar pesquisa opcional.
5. **Expressões claras**. Evite paths profundos — se for longo, passe o objeto inteiro e deixa o worker decompor.
6. **Versionar a receita**. Ao mudar shape do input, bump `version`.

## Anti-padrões

- ❌ **Stage sem `requires`/`worker`/`fanout_over_capabilities`** — fica sem trabalho real; o runner reclama.
- ❌ **Stage pedindo capability que ninguém oferece** — receita falha em runtime. Confira com `GET /capabilities` antes.
- ❌ **Receita super-específica por tenant** — prefira uma receita parametrizada + `profiles/<tenant>/config.yaml` com brand/prompts.
- ❌ **Aprovação em todo stage** — mata a UX; usuário cansa. Máximo 2–3 gates por receita longa.
