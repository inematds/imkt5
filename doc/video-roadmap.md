# Video roadmap — decisões consolidadas (em construção)

Acumula as decisões do usuário item a item sobre melhorias de vídeo
pós-Fase 1+2. Quando terminarmos a lista, vira um plano único de
implementação em batch.

## Item 1 — Karaoke sincronizado com fala real ✅ decidido

**Decisão:** FAZER, no batch final com os outros.

- **Engine primário**: `faster-whisper` local (sem custo, CPU OK).
- **Alternativa via config**: poder trocar pro ElevenLabs (ou outro
  provider TTS que retorna word marks). Config via env/workers.yaml.
  Quando provider nativo entrega timings, pula o whisper.
- **Default**: karaoke **habilitado**.
- **Flag**: `use_karaoke: false` no input da run desabilita.
- **UI**: adicionar toggle (checkbox) no dialog "Nova execução" do
  `/runs-ui` pra ligar/desligar fácil.

---

## Item 2 — TTS acelerado 1.15–1.25x ✅ decidido

**Decisão:** FAZER (opção A — parametrizado por style + override por input).

- **Filter**: `ffmpeg -filter:a "atempo=X"` (preserva pitch).
- **Limite**: clamp em 1.0–1.25x (fora disso, desliga pra não distorcer).
- **Por style** (defaults sugeridos):
  - `energetico`, `bold_pop`, `streetwear_urban` → 1.20x
  - `neon_futurista`, `dark_dramatic` → 1.15x
  - `corporate_clean`, `editorial_documentary`, `data_viz` → 1.10x
  - `premium_minimal`, `emocional_cinematic`, `nature_organic` → 1.0x
  - `wellness_soft`, `organic_earth` → 0.95–1.0x (lento deliberado)
- **Override**: campo `narration_speed` no input (run) tem prioridade.
- **Aplicação**: no `_mix_audio` do `ffmpeg-local`, antes do mix; se
  karaoke sync está ativo, recalcula timings com base na duração pós-atempo.

---

## Item 3 — TTS multi-provider + dedup ✅ decidido

**Decisão:** FAZER opção C — só dedup agora. Multi-provider/troca fica
**via configuração**, não implementação agora.

- **Dedup**:
  - Hash `sha256(text + voice + lang + engine)` vira chave.
  - Armazenar em Postgres (`tts_cache` table) OU naming determinístico em
    S3 `/s3/imkt5/tts-cache/<hash>.mp3`.
  - No adapter, antes de chamar TTS upstream, checa se o hash já existe;
    se sim, devolve `audio_url` cacheado.
  - Economia esperada: 40-60% em runs repetidos/similares.
- **Trocar provider** (fica por config, não por código):
  - `.env`: `TTS_PROVIDER=inemavox` (ou `elevenlabs` quando existir).
  - `config/workers.yaml`: registrar cada adapter com `priority` e
    `capabilities: [audio.tts]`; registry já escolhe healthy de maior
    prioridade.
  - Pra testar ElevenLabs, basta adicionar o adapter depois — não mexe
    em recipe nem em runner.

---

## Item 4 — distributeSceneDurations proporcional ao áudio ✅ decidido

**Decisão:** FAZER opção A — nível completo mkt3-style (TTS por cena).

- **Muda recipe** `campanha-marketing.yaml`:
  - Stage `voiceover` vira **fanout** sobre `$.stages.video.output.scene_plan.scenes`
    (um TTS call por cena, usando `scene.narration`).
  - Output: lista de N `audio_url` (uma por cena).
- **Stage `video_render`** passa a receber `narration_urls` (lista) em
  vez de `narration_url` singular.
- **`ffmpeg-local`**:
  - Mede duração de cada mp3 via `ffprobe`.
  - `scene.duration` = `max(scene.duration_llm, audio_duration + 0.3s)`
    (garante respiro pós-palavra).
  - Concatena narrações com gaps de silêncio iguais à diferença; resultado
    sincroniza com cenas.
  - Passa timings por cena pro karaoke (item 1 fica muito mais preciso).
- **Benefícios**:
  - Karaoke agora tem timings POR CENA (whisper roda em áudio curto
    por cena, mais rápido/preciso).
  - Cenas nunca truncam narração.
  - Dedup (item 3) fica ainda mais útil — narração por cena é mais
    reutilizável entre runs similares.

---

## Item 5 — Hold final + loop visual ✅ decidido

**Decisão:** FAZER ambos, com flag pro loop.

- **5a. Hold final silencioso** — default **ON** (sem flag).
  - Última cena ganha +3s: 0.5s de reprodução natural + 2.5s de frame
    congelado.
  - Áudio: padded com silêncio. Música-trilha cai pra -20dB no hold
    (respiro auditivo).
  - Sempre aplicado exceto quando `video_length < 8s` (curto demais
    pra hold não atrapalhar).
- **5b. Loop visual** — flag `loop_visual`, default **OFF**.
  - Quando ligado: último frame repete composição da primeira cena
    (mesma imagem base OU crossfade 0.3s pro frame 0 no final).
  - Video-quick/pro SKILL instruído a pedir "última cena visualmente
    rima com a primeira".
  - Target: TikTok/Reels que favorecem vídeos com alto rewatch rate.

---

## Item 6 — A/B variants ✅ decidido

**Decisão:** FAZER opção A (recipe-level). Outras opções anotadas pra v5.

### v4 (agora / próximo batch) — opção A: recipe-level

- Nova recipe `campanha-marketing-ab.yaml` (ou flag `ab_mode: true` na
  existente).
- Input aceita:
  ```json
  {
    "brief": "...",
    "hook_variants": ["stat_shot", "question_abrupt", "pov"],
    "cta_variants": ["Comece grátis", "Acesse INEMA.CLUB"]
  }
  ```
- Fanout sobre `hook_variants × cta_variants` → gera N vídeos
  (ex.: 3 × 2 = 6).
- Cada variante tem seu scene_plan próprio (hook 0 e CTA final trocam).
- Dedup de TTS (item 3) evita regerar áudio das cenas do meio que não
  mudam.

### v5 (futuro) — anotado em backlog

- **Opção B**: worker `video.ab_generator` reusa cenas do meio (render
  1x, corte N variantes). Mais eficiente mas logic complexa.
- **Opção C**: LLM propõe `alt_hooks: [...]` e `alt_ctas: [...]`; UI
  pede ao user pra escolher quais pares renderizar (A/B guiado).

---

## Item 7 — Aprovação humana bifurcada ✅ decidido

**Decisão:** FAZER. Sistema de aprovação flexível por flag em cada stage.

### Flag `approval.mode` aceita 4 valores:

| Valor | Comportamento |
|---|---|
| `none` | Passa direto, sem gate (atual default em todas as recipes) |
| `auto` | **Novo default** — LLM auto-reviewer decide. Critérios por stage. |
| `human` | Pergunta pelo canal de origem da run (Telegram bot se veio de Telegram, chat web se veio da web, WhatsApp se de WA). Timeout configurable (default 30min). |
| `agent` | LLM reviewer específico do stage decide (mais contexto que `auto`). |

### Onde vive

- Cada stage da recipe pode definir `approval: {mode: auto}` (ou `human`/`agent`/`none`).
- Input da run pode forçar override global: `"approval_mode": "human"` muda TODOS os stages pra human (casos premium / produção real).
- Canal de notificação vem do `origin_channel` da run — resolver já mapeia pra bot certo.

### Stages sugeridos pra ativar

- **scene_plan** (pós-`video`, antes de `video_render`) — maior leverage, evita render caro de plano ruim.
- **brief_strategic** (pós-`brief`, antes de `copy`) — pega direção ruim cedo.
- **creative_final** (pós-`video_render`, antes de publish) — última peneira.

### Implementação

- Runner já tem `ApprovalGate` (modos user/reviewer/auto). Faltam recipes configurarem.
- UI: mostrar no `/runs-ui` pro stage em `awaiting_approval` → botões [✅ Aprovar] [❌ Recusar] + razão.
- Telegram bot (já conectado) recebe card do scene_plan com mesmos botões.
- Se `rejected` com razão → stage retrai e opcionalmente re-chama LLM com "razão do rejeito" pra tentar outra versão.

---

## Item 8 — Parallax / depth effect ✅ decidido

**Decisão:** FAZER. Default nível 1 (fake parallax) + flag `depth_ai` pra
ativar nível 2 (AI depth map).

### Nível 1 — Fake parallax (default ON quando `use_parallax: true`)

- 3 camadas a partir da mesma imagem:
  - `bg`: blur forte (`boxblur=20:1`), zoompan 1.0→1.05 lento
  - `mid`: blur leve (`boxblur=4:1`), zoompan 1.0→1.08 médio
  - `fg`: sem blur, crop central, zoompan 1.0→1.12 rápido
- Composite via `overlay` com opacidade escalonada.
- Aplica na cena quando `parallax: true` (ou style tem `parallax_default`).
- Custo zero (só ffmpeg), roda em CPU.

### Nível 2 — AI depth map (flag `depth_ai: true`)

- Usa `Depth-Anything V2` (ou `MiDaS` pequeno) via Python.
- Python script gera depth map por imagem (~2-3s GPU).
- Pixel displacement baseado no depth → parallax real com profundidade.
- Só roda quando flag está ativo (não é default).
- Requer modelo baixado localmente (~150MB).

### Quando ativa automaticamente (style-based)

- `dark_dramatic`, `emocional_cinematic`, `premium_minimal` →
  `use_parallax: true` default no style.
- `bold_pop`, `energetico`, `streetwear_urban` → sem parallax (velocidade
  de corte é o motion; parallax seria concorrente visual).

---

## Item 9 — AI b-roll gerado (Runway/Kling/Sora) ⏭️ v5

**Decisão:** PULA agora. Fica pra v5 quando:
- Custo de API caia (hoje Runway ~$1.25/vídeo de 15s é proibitivo em
  volume).
- Modelos locais open-source (wan2.1, ltx-video) amadureçam a ponto de
  valer a GPU dedicada.
- Paridade de estilo entre imagem→vídeo vire controlavel (consistência
  entre cenas é o maior risco hoje).

Quando retomar: começar pela **opção D (híbrido)** — gera imagem com
flux2-klein (barato) e usa como reference pro video generator. Melhor
custo-benefício e mantém coerência visual entre cenas.

**Trigger pra adiantar pra v4**: se rodarmos `wan2.1` ou `ltx-video`
local com qualidade aceitável em testes paralelos, antecipa item pra
v4 como adapter local (zero custo recorrente).

---

## Item 10 — Lip-sync IA (avatar talking head) ⏭️ v5

**Decisão:** PULA agora. Fica pra v5.

INEMA.CLUB hoje não precisa avatar; se houver futuro brand com rosto,
decide na hora. Itens 9 e 10 compartilham o mesmo padrão: ambos
dependem de GPU-heavy models que amadurecem rápido.

**Trigger pra adiantar pra v4**: testes paralelos com `Wav2Lip` ou
`Sonic` local mostrarem qualidade aceitável na nossa GPU. Se sim,
vira adapter local (capability `video.lip_sync`), mesmo padrão que
itens 9.

---

## Item 11 — Emoji matching em caption ⏭️ v5

**Decisão:** PULA pra v5.

Quando retomar: preferência pela **opção C** — LLM inclui `emoji` no
scene_plan desde o início (campo por cena). Zero custo extra e mantém
coerência com o tom da cena (LLM conhece o contexto).

Fallback simples: **opção B** (dict regex) como default rápido caso a
opção C demore ou LLM falhe.

---

## Item 12 — Safe areas / text layout ✅ decidido (v4 + v5)

**Decisão:** opção C agora (v4), opção A na v5.

### v4 (no batch atual)

- **Layout universal seguro**: karaoke e text_overlay sempre entre
  y=25% e y=60% do frame. Nunca entra nos 25% inferiores nem nos 15%
  superiores (bloqueados em alguma plataforma).
- **Flag de posição** quando karaoke ativo: cada cena pode sobrescrever
  via `caption_y_pct` no scene_plan (10-90%). Se a flag estiver dentro
  da safe zone (25-60%), respeita; senão clampa.
- **Template define área livre** (importante): nos templates de
  carrossel-designer, cada template já tem seu "miolo" definido (padding
  etc.). Extensão: cada template exporta uma `caption_zone` (y range)
  que o karaoke do vídeo respeita quando usa aquele template como base
  visual.
  - ex.: `editorial` → caption_zone: 50-65% (parte média-baixa, não
    competir com stats no topo)
  - `magazine` → caption_zone: 60-75% (abaixo do serif grande)
  - `data_viz` → caption_zone: 15-25% (em cima, pois o número gigante
    ocupa o meio)

### v5 (futuro)

- **Opção A — Dict de safe areas por plataforma**: quando input traz
  `platform: "tiktok"`, ajusta caption_zone pra `right: 10%, bottom:
  25%` (evita botões da direita + descrição).
- **Opção B (render por plataforma)**: descartada — 3× custo de render
  não compensa o ganho marginal de precisão.

---

## Item 13 — Kinetic typography ✅ decidido

**Decisão:** A default + B via flag.

### Default (ON sempre) — Opção A (ASS tags simples)

- Fade-in curto (`{\fad(180,0)}`) aplicado em CADA palavra do karaoke.
  Evita flash seco que incomoda em telas pequenas.
- Último palavra do CTA: mini scale bounce via `{\t(0,200,\fscx110\fscy110)\t(200,400,\fscx100\fscy100)}`.
- Zero custo computacional (ASS engine já processa).

### Flag `kinetic_presets: true` — Opção B (presets por style)

- Art-director passa a emitir `text_animation` no output:
  - `editorial` → `wipe` (frase sobe de baixo)
  - `bold_pop`, `streetwear_urban` → `zoom_impact` (palavra-chave zoom +
    SFX stab sincronizado)
  - `wellness_soft`, `nature_organic` → `type_on` (letra por letra,
    lento)
  - `neon_futurista`, `retro_futurism` → `glow_pulse` (palavra pulsa com
    glow)
  - `corporate_clean`, `data_viz` → `static` (sem animação — autoridade)
- Renderer mapeia cada preset pra sequência de tags ASS avançadas.
- Ativado explicitamente por `kinetic_presets: true` no input.
- Regra de uso: aplica presets SÓ no hook (cena 0) + 1-2 revelações
  importantes (marcadas pelo LLM como `emphasis: true`). Resto usa
  default A (fade-in). Evita poluição visual.

---

## Item 14 — Freeze frame + zoom em revelações ✅ decidido

**Decisão:** FAZER A + B combinados (B usa A como infra).

### Camada A — Freeze flag por cena (infra base)

- LLM planner marca cena com:
  ```json
  {
    "freeze_at": 1.5,          // timestamp dentro da cena (s)
    "freeze_duration": 0.8,    // duração do freeze (s)
    "freeze_zoom": 1.15,       // zoom pro efeito punch
    "freeze_sfx": "ding"       // opcional: ding|stab|swoosh
  }
  ```
- Renderer ffmpeg-local:
  - Corta o clip em 3 partes: pré-freeze, still-frame com zoom rápido,
    pós-freeze.
  - Mixes SFX no timestamp do freeze.
  - Total de duração da cena aumenta em `freeze_duration`.

### Camada B — Word-level trigger (precisão)

- **Requer item 1** (whisper word timings).
- LLM planner adiciona `emphasis: true` em palavras-chave (dados,
  verbos de impacto).
- Quando whisper devolve timings, busca a palavra marcada e **sobrescreve**
  `freeze_at` = start dessa palavra.
- Resultado: freeze acontece EXATAMENTE quando a palavra é dita.

### Heurística automática

- Se cena tem `stat_a` ou `stat_b` (dado numérico) E style é
  `data_viz`/`editorial`/`corporate_clean` → ativa freeze automático
  no stat.
- User pode desabilitar com `freeze_frames: false`.

---

## Status v4 batch — 2026-04-18 ✅ IMPLEMENTADO

Todos os 11 itens do batch foram implementados e validados em produção.
Run de teste `f3f8b056-2aec-4f8d-855f-b2a03585591c` passou por todos os
stages com sucesso; dedup validado em `2e5850c5/JOB2` (cache HIT na 2ª
chamada com texto idêntico).

## Resumo das decisões — v4 batch

Itens pra fazer AGORA (batch único após aprovação final):

| # | Item | Default | Flag |
|---|---|---|---|
| 1 | Karaoke sync com faster-whisper | ON | `use_karaoke: false` desliga |
| 2 | TTS acelerado 1.15–1.25x | por style | `narration_speed` override |
| 3 | Dedup TTS (cache hash) | ON | sem flag |
| 4 | distributeSceneDurations (TTS por cena, mkt3-style) | ON | — |
| 5a | Hold final 3s silencioso | ON | — |
| 5b | Loop visual | OFF | `loop_visual: true` liga |
| 6 | A/B variants (opção A recipe-level) | — | `ab_mode: true` + `hook_variants`/`cta_variants` |
| 7 | Aprovação flexível (none/auto/human/agent) | — | `approval.mode` por stage + `approval_mode` global |
| 8 | Parallax nível 1 (fake) | default por style | `use_parallax` + `depth_ai: true` pra nível 2 |
| 12 | Layout safe (caption_zone 25-60%) | ON | `caption_y_pct` override |
| 13a | Kinetic fade-in nas palavras (ASS) | ON | — |
| 13b | Kinetic presets por style | OFF | `kinetic_presets: true` liga |
| 14 | Freeze frame em revelações | auto por style | `freeze_frames: false` desliga |

## Itens na v5 (futuro)

| # | Item | Trigger pra adiantar |
|---|---|---|
| 9 | AI b-roll gerado | local model (wan2.1/ltx-video) maduro |
| 10 | Lip-sync IA | Wav2Lip/Sonic local aceitável |
| 11 | Emoji matching em caption | LLM cost negligível + padrão real de mercado |

## Ordem de implementação sugerida (dependências)

1. **Item 3** (dedup TTS) — infra, barato, paga por si só.
2. **Item 4** (TTS por cena) — destrava itens 1, 5a, 14.
3. **Item 1** (karaoke sync com whisper) — depende de 4.
4. **Item 14b** (freeze word-level) — depende de 1.
5. **Item 2** (TTS speed) — independente; fácil.
6. **Item 5a** (hold final) — barato, destrava polish.
7. **Item 5b** (loop visual) — depende de 5a.
8. **Item 12** (safe layout) — independente; fácil.
9. **Item 13a** (ASS fade-in) — independente; 20min.
10. **Item 13b** (kinetic presets) — depende de arte direction; melhora
    a qualidade.
11. **Item 7** (aprovação) — independente, mas muda UX (UI update).
12. **Item 8** (parallax nível 1) — independente; L quando incluir nível 2.
13. **Item 6** (A/B variants) — recipe nova; independente.

### Estimativa total de esforço

- **v4 batch**: ~10-14h focado (dependendo de testes/polish).
- Fases possíveis (se quiser quebrar):
  - **Fase 3a** (itens 1, 2, 3, 4, 5a) — core audio/narration polish, 4-5h.
  - **Fase 3b** (itens 7, 12, 13a, 13b) — UX + text refinement, 3-4h.
  - **Fase 3c** (itens 5b, 8, 14) — visuals avançados, 3-4h.
  - **Fase 3d** (item 6) — A/B variants, 2-3h.

