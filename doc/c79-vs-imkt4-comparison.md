# c79 (cchyperframes) vs imkt4 — relatório de comparação

> Análise lado-a-lado entre o stack `cchyperframes` (Hyperframes: Chromium
> headless + HTML + GSAP) e nosso pipeline `ffmpeg-local` (video-quick +
> video-pro + carousel-designer). Inclui quando porta vale a pena, o que
> já temos superior, e o que custa quanto.
>
> Data: 2026-04-19. Refs: `cchyperframes@HEAD`, `imkt4@53b1538`.

---

## 1. O que é c79

Monorepo `cchyperframes` com 12 projetos de vídeo entregues (`.mp4` final
em cada pasta). Cada projeto é **um conjunto de arquivos HTML** ligados
por `data-composition-src`, com timeline GSAP pausada registrada em
`window.__timelines[<id>]`. A CLI `hyperframes` dirige Chromium headless
frame-a-frame para render MP4 determinístico.

**Dois gêneros de projeto presentes:**

| Gênero | Exemplos | Formato | Aspect |
|---|---|---|---|
| **Short vertical talking-head + MG** | `may-shorts-19`, `may-shorts-18` | 1080×1920 @ 30fps ~19s | 9:16 |
| **Promo de produto/marca** | `linear-promo-30s`, `aisoc-hype`, `clickup-demo`, `first-agent-promo` | 1920×1080 @ 30fps 30-60s | 16:9 |

**O documento canônico:** `MOTION_PHILOSOPHY.md` — engenharia reversa do
30s spot da Infinite Global Payments. As **11 Leis** são o nível-meta:
1. 1 ideia por beat, ~1.5s/cena
2. Preto é a canvas (90% do frame)
3. Luz é a marca, não cor (chrome gradient, halos)
4. Câmera nunca dorme (drift, breathe, parallax)
5. Motion blur é feature (mascara cortes)
6. Metáforas de objeto carregam significado (callback)
7. Paleta simbólica, não decorativa
8. Tipo é personagem (SCALE 8×, MORPH, GLOW)
9. Segure o hero shot (outro 4-6s de silêncio)
10. Uma textura unificadora (grid + crosshairs + grain)
11. Timelines preenchem seu slot (`tl.to({}, { duration: SLOT_DURATION }, 0)`)

---

## 2. Engine: comparação de arquitetura

| Eixo | c79 (Hyperframes) | imkt4 (ffmpeg-local) |
|---|---|---|
| **Render engine** | Chromium headless frame-a-frame | ffmpeg filter_complex |
| **Autoria** | HTML + CSS + GSAP + data-attrs | YAML recipe + JSON scene_plan |
| **Composição** | Sub-comps HTML com timeline pausada | Stages no runner declarativo |
| **Motion blur real** | ✅ (Chromium snapshot do frame) | ⚠ parcial (`tblend` em whip_pan) |
| **3D / WebGL** | ✅ (pré-render MP4 ou CSS `preserve-3d`) | ❌ |
| **Fonts arbitrárias** | ✅ Google Fonts CDN (qualquer família) | ⚠ limitado a fontes instaladas (Playfair, Inter, DejaVu) |
| **Chrome gradient text** | ✅ nativo (`background-clip: text`) | ❌ impossível com drawtext |
| **Kinetic SCALE 8×** | ✅ `scale: 8, duration: 1.0` | ⚠ só via ASS `\fscx/\fscy` (parcial) |
| **Determinismo** | ✅ PRNG seeded + harmonic hashes | ✅ ffmpeg puro é determinístico |
| **Tempo de render** | ~5min para 20s @ 1080p | ~20s para 20s @ 1080p (**15× mais rápido**) |
| **Custo GPU** | Alto (chromium repete frames) | Baixo (ffmpeg CPU) |
| **LOC do renderer** | ~0 próprio (CLI externa) | 1647 linhas `ffmpeg-local/server.py` |
| **Escalabilidade** | Precisa GPU/pod dedicado | Roda em qualquer worker stateless |

**Leitura curta:** c79 produz **qualidade motion-graphics Infinite-tier**
ao custo de render lento e stack browser. Nós produzimos **rápido e
barato** com limitações intrínsecas de filter_graph (sem chrome text,
sem 3D, sem DOM real).

---

## 3. Vídeo: nosso quick+pro vs may-shorts-19 (9:16 short-form)

**Comparável mais próximo:** `video-projects/may-shorts-19` (vertical
talking-head + MG + karaoke, 18.84s). É o projeto c79 mais alinhado com
nosso *use case* (reels/shorts/tiktok).

### 3.1 Estrutura lado a lado

| Elemento | c79 may-shorts-19 | imkt4 quick | imkt4 pro |
|---|---|---|---|
| Aspect | 9:16 1080×1920 | 9:16 1080×1920 | 9:16 1080×1920 |
| Duração alvo | 18.84s (fixo) | 10-20s | 10-30s |
| Nº cenas | 7 cenas (scene1–scene7) + ambient-bg | 4-6 cenas | 4-6 cenas |
| Duração média de cena | **2.2s** (avg fixo) | 3-4s | 3-4s |
| Narração | talking-head real (face video) | TTS sintético (inemavox) | TTS sintético |
| Legendas | karaoke ASS word-level via whisper | ❌ default off | ✅ karaoke ASS word-level via whisper |
| Ambient bg | `ambient-bg.html` (radial + grid + particles + vignette) | ❌ | ✅ vignette + grain (recente) |
| Face/image | Vídeo MP4 real | SD images (inemaimg) | SD images |
| Chrome gradient headline | ✅ em todas cenas de tipografia | ❌ | ❌ |
| Halo glow em emphasis word | ✅ text-shadow `0 0 20px rgba(255,255,255,0.6)` | ⚠ só shadow escuro | ⚠ só shadow escuro |
| Word-by-word kinetic reveal | ✅ GSAP stagger 0.35s | ❌ fade-in da cena | ⚠ karaoke word highlight (se on) |
| SCALE 8× na hero word | ✅ `fromTo({scale:1, opacity:1}, {scale:8, opacity:0})` | ❌ | ❌ |
| Motion entre cenas | whip-streak blur (0.4s) | cut / crossfade | crossfade_short/long + whip_pan ffmpeg |
| Background | ambient-bg drifting grid | imagem cheia | imagem cheia + vignette radial |
| Grain overlay | ✅ `grain-overlay` package | ❌ | ✅ `noise=c0s=5` |
| Callback visual | ⚠ opcional (Infinite tem coin 3×) | ❌ | ❌ |
| Tempo render | ~5min | ~20s | ~30s |

### 3.2 Veredicto por dimensão

- **Qualidade visual percebida:** c79 >> nosso pro >> nosso quick.
  Diferença vem 70% de chrome-gradient + halo + grid-drift + whip-streak
  (essas 4 coisas sozinhas explicam o "feels expensive").
- **Velocidade de produção:** nosso pipeline é **15-20× mais rápido**.
  May-shorts-19 leva horas de autoria HTML + 5min de render. Nosso quick
  leva 20s end-to-end, zero autoria manual (recipe faz tudo).
- **Variedade:** temos 12 estilos artísticos prontos. c79 tem 1 estética
  (Infinite-like) + variações por projeto (todas hand-built).
- **Multi-tenant:** c79 é single-user (um dev local com Chrome). Nosso é
  tenant-aware desde schema.
- **Narração:** talking-head real (c79) sempre ganha de TTS sintético em
  *authenticity*. Nosso caso de uso típico não tem face disponível.

---

## 4. Técnicas específicas — o que podemos portar (priorizado)

### Tier A — Alto impacto, baixo custo (**quick wins ~4h**)

| # | Técnica c79 | Viabilidade imkt4 | Custo | Ganho |
|---|---|---|---|---|
| A1 | **Chrome gradient headline text** | Render via Playwright (já temos pro carousel) → PNG transparente → overlay ffmpeg por cena | ~2h | +40% no "feels expensive" |
| A2 | **Halo glow em emphasis word** | Mesmo truque PNG: `text-shadow: 0 0 20px white` + `0 0 40px white` no HTML que renderizamos | +30min (combinado com A1) | +15% polish |
| A3 | **Perspective grid floor** | PNG estático pré-renderizado (uma vez) + overlay com scroll infinito via `scroll=SW=t*20` | ~1h | +20% premium feel |
| A4 | **Ambient drift/breathe em cena estática** | `zoompan` já temos. Ativar `motion:breathe` default mesmo em cenas sem hint | ~20min (só flag) | +10% (lei 4: câmera nunca dorme) |
| A5 | **Whip-streak transition overlay** | PNG gradient horizontal `transparent→white→transparent` + xfade customizado com ele por cima | ~1h30 | +25% (mascara cortes, parece caro) |

### Tier B — Médio impacto, médio custo (**~8h**)

| # | Técnica c79 | Viabilidade imkt4 | Custo |
|---|---|---|---|
| B1 | **Word-by-word kinetic reveal via ASS** | Já temos whisper word-timings. Criar preset `text_animation: word_stagger_reveal` que gera `.ass` com um `\an5\fad(100,0)` por palavra com delay 0.3-0.4s | 3h |
| B2 | **SCALE 8× hero word** | ASS suporta `\fscx{...}\t(...)`. Preset `kinetic_hero_dolly` animando fscx 100→800 em 1s no último word | 2h |
| B3 | **Callback visual (mesmo elemento 2-3×)** | Flag `callback_asset_url` em scene_plan + repetir em cena[-2] com motion diferente | 1h |
| B4 | **1.5s pacing mode** | Default `duration_per_scene: 1.5` + `default_scenes: 7-9` em vez de 4-6. Aciona por flag `pacing: tight` no recipe | 30min |
| B5 | **Outro hold 4-6s obrigatório** | Forçar última cena `duration >= 4` + loop visual no hold | 30min (já existe hold_final=3s, subir pra 4) |
| B6 | **Ambient-bg composite layer** | Pré-render um asset `ambient_bg_dark_minimal.mp4` (grid drift + vignette + grain) e usar como base com imagem em cima via `blend=all_mode=screen` ou overlay translúcido | 1h30 |

### Tier C — Alto impacto, alto custo (**arquitetural, fase 4e**)

| # | Técnica c79 | Viabilidade imkt4 | Custo |
|---|---|---|---|
| C1 | **Novo worker `video-motion-graphics`** (HTML+GSAP+Chromium) | Port do flow hyperframes — recipe aceita `render_engine: motion` | 3-4 dias |
| C2 | **Liquid-glass cards / iridescent wheels** | Só viável com C1 | depende de C1 |
| C3 | **True 3D rotate (coin/wheel spin)** | Só viável com C1 ou pré-renderizar MP4 de asset | depende |
| C4 | **Faux-cursor click events (UI demos)** | Só viável com C1 | depende |

---

## 5. Onde já somos superiores ao c79

| Capacidade | c79 | imkt4 |
|---|---|---|
| Multi-tenant desde schema | ❌ single-user | ✅ |
| Fila capability-based com retry/DLQ | ❌ | ✅ |
| Recipe runner declarativo YAML (needs/when/fanout) | ❌ (index.html chain) | ✅ |
| 12 estilos artísticos catalogados com motion+palette+music+transition | ❌ (1 estética) | ✅ |
| Worker art-director LLM-driven (escolhe estilo do brief) | ❌ | ✅ |
| SD image generation + edit (nanogenmini + fallback flux/SDXL) | ❌ (imagem é asset manual) | ✅ |
| TTS per-scene com dedup sha256 cache | ❌ (voiceover é asset manual) | ✅ |
| A/B variants com LLM-suggest de hooks e CTAs | ❌ | ✅ |
| Approval flow (human/auto/agent) + Telegram gate | ❌ | ✅ |
| UI web inspector (runs + workers + recipes + jobs) | ❌ (só CLI local) | ✅ |
| Carrossel rico estático para Instagram | ❌ (não existe) | ✅ |
| Tempo de render ~20s (vs 5min) | ❌ | ✅ |
| Escala horizontal (workers stateless) | ❌ (Chrome monolito) | ✅ |

**Leitura:** c79 é um **estúdio bespoke de 1 pessoa**. imkt4 é uma
**plataforma multi-tenant de produção**. A comparação justa não é
"quem tem vídeo mais bonito" — é "quem escala geração automatizada sob
marca + approval + tenants". Nisso não há competição.

---

## 6. Carrossel — c79 não tem, mas vale comparar o análogo

**c79 não entrega carrossel estático Instagram.** Todo deliverable é
vídeo. O análogo mais próximo é **cena com múltiplos cards simultâneos**,
como `linear-promo-30s/compositions/05-product-surfaces.html` — 3
laptops flutuando com Plan/Build/Monitor, cada um com sua screen.

### 6.1 Nosso carrossel-rico vs análogo c79

| Elemento | imkt4 carrossel-rico | c79 cena multi-surface |
|---|---|---|
| **Deliverable** | 7 PNGs estáticos para post Instagram | frame dentro de vídeo (0s estáticos puros) |
| **Motor** | Playwright + Jinja HTML → screenshot | Chromium GSAP → frame capture |
| **Tipografia** | Playfair 900 + text-shadow + outline | **Instrument Serif italic 140px + chrome gradient + halo** |
| **Background** | SD image + veil 40-55% opacity OU solid bg | Perspective grid + vignette + grain + ambient |
| **Text-in-image detection** | ✅ PIL edge heuristic + fallback solid bg | N/A |
| **Templates** | 5 variantes (magazine/editorial/data_viz/bold_pop/corporate_clean) | hand-built por projeto |
| **Stats com números grandes** | ✅ `stat_a`/`stat_b` via template | ⚠ raro, não-padrão |
| **Brand moment final slide** | ✅ logo + handle + tagline | ⚠ só em vídeo (logo outro 4-6s) |
| **Callback** | ❌ | ✅ (coin 3x, elemento volta) |
| **Autoria** | LLM (carrossel-outline) gera slides, 0 hand-build | 100% hand-build por composition |
| **Tempo produção** | ~90s end-to-end | horas/projeto |
| **Paleta** | Preto + branco + 1 accent por style | ≤5 hues, cada com significado |

### 6.2 O que podemos portar PARA carrossel-rico

**Tier A (quick wins ~3h):**

1. **Chrome gradient headline** (A1 do vídeo) — já renderizamos HTML. Basta
   trocar `color: white` por:
   ```css
   background: linear-gradient(180deg, #fff 0%, #999 100%);
   -webkit-background-clip: text;
   color: transparent;
   ```
   Em templates magazine + editorial. **30min de trabalho.**

2. **Halo glow em emphasis word** — adicionar
   `text-shadow: 0 0 20px rgba(255,255,255,0.6)` em palavras marcadas com
   `<em>` no outline. **20min.**

3. **Perspective grid floor em templates escuros** — CSS puro, sem asset
   externo:
   ```css
   .grid-floor {
     transform: perspective(900px) rotateX(60deg) translateY(25%);
     background:
       repeating-linear-gradient(0deg,  rgba(255,255,255,.05) 0 1px, transparent 1px 80px),
       repeating-linear-gradient(90deg, rgba(255,255,255,.05) 0 1px, transparent 1px 80px);
   }
   ```
   Viralização visual **enorme** com 10 linhas. **30min.**

4. **Vignette radial em todo slide** (lei 2) — não temos. É 1 linha CSS:
   ```css
   .vignette { background: radial-gradient(ellipse at center, transparent 30%, #000 95%); }
   ```
   **10min.**

5. **Noise/grain overlay por CSS** — já listado no c79 como "pure CSS, no
   PNG" (seção 2.1 item 11): três radial-gradients tiled. Deterministic,
   headless-safe, sem asset. **20min.**

6. **Instrument Serif italic como font default em `editorial`** — ao invés
   de Playfair (também serif mas mais tradicional). Google Fonts CDN, já
   usamos. **10min.**

**Tier B (~4h):**

1. **Callback element em slide-N-1** — repetir um badge/stat/ícone do
   slide de hook no slide de proof/cta com tratamento diferente. Gera
   coesão visual. **2h (inclui passo de outline).**

2. **Palette ≤ 5 hues com meaning** — hoje o art-director já escolhe,
   mas o SKILL precisa exigir **"diga o significado de cada cor"**.
   **30min (atualizar SKILL.md art-director).**

3. **Chrome-gradient sweep animado** (só em carrossel de 5+ slides, para
   sensação de "reveal progressivo"): 8-stop com dark bookends, posição
   varia por slide via CSS variable. **1h30.**

---

## 7. Matriz de decisão

Quando escolher qual abordagem:

| Contexto | Melhor stack |
|---|---|
| **Post Instagram carrossel 7 slides/dia** | 🏆 imkt4 — c79 não faz |
| **Reels/TikTok automatizado 20s + narração sintética** | 🏆 imkt4 — volume + queue + multi-tenant |
| **Reels talking-head polido semanal** | 🏆 c79 (may-shorts-19 model) — mas esforço 20× maior |
| **Promo premium 30s hero-tier (pitch investidor, launch marca)** | 🏆 c79 — só ele entrega Infinite-level |
| **Conteúdo educacional B2B em escala (100+ vídeos/mês)** | 🏆 imkt4 — c79 não escala |
| **A/B testing de hook+cta em paid media** | 🏆 imkt4 — `video-ab-suggest` nativo |

---

## 8. Plano sugerido — integração parcial

**Não é "ou x ou y".** Absorver c79 em 2 tiers:

### Fase α — quick wins no ffmpeg-local e no carousel-designer (4-6h)

Absorver só **CSS/PNG tricks** que cabem no stack atual:

- [ ] Chrome gradient text via Playwright PNG (vídeo + carrossel)
- [ ] Halo glow em emphasis
- [ ] Perspective grid CSS em templates escuros
- [ ] Vignette radial default em `.slide` container
- [ ] Grain CSS puro no carrossel (já temos no ffmpeg via noise=)
- [ ] Whip-streak transition overlay
- [ ] Pacing tight (1.5s/cena) como flag opt-in no video-pro
- [ ] Outro hold 4-6s obrigatório

**Impact esperado:** nosso pro sobe de "~70% paridade mkt3" para
"~85% paridade c79 visual" **sem trocar engine**.

### Fase β — worker paralelo `video-motion-graphics` (só se volume justifica)

- [ ] Port Hyperframes CLI como worker
- [ ] Recipe adiciona `render_engine: motion` opt-in
- [ ] Compatibilidade retrógrada: default `ffmpeg` continua sendo padrão
- [ ] Primeiros templates: port de `linear-promo-30s` + `aisoc-hype`
  parametrizados por brand-tokens.css dinâmico

**Trigger para fazer:** cliente enterprise paga premium OU volume de
renders > 50/dia OU branding-heavy que não cabe no estilo editorial.

---

## 8b. ✅ Fase α implementada (2026-04-19)

Todas as 6 técnicas core entregues **atrás de flag opt-in ou template
novo**. Zero impacto em runs existentes.

### Carrossel (template novo)

- ✅ **`editorial_chrome.html`** — template novo (não muta `editorial.html`)
  com:
  - Chrome gradient headline (Instrument Serif italic + linear-gradient
    180° white→gray→light + `-webkit-background-clip: text`)
  - Halo glow duplo (`drop-shadow(0 0 20px rgba(255,255,255,.38))` +
    `drop-shadow(0 0 40px rgba(255,255,255,.18))`)
  - Perspective grid floor (`perspective(900px) rotateX(60deg)` +
    repeating-linear-gradient duplo)
  - Vignette radial (`radial-gradient(ellipse, transparent 30%, #000 95%)`)
  - Film grain CSS puro (3 radial-gradients em 3px/5px/7px, determinístico,
    sem PNG)
  - Liquid-glass stat blocks (`backdrop-filter: blur(12px)`)
  - Chrome accent line no topo
  - Brand moment com chrome italic serif

- ✅ Selecionável em `template: "editorial_chrome"` OU pela UI
  (pill ✨ Editorial Chrome)
- ✅ Flags opt-in `use_perspective_grid` / `use_vignette` / `use_grain`
  ficam disponíveis pros outros templates (ignoradas pelos que não
  implementam)

### Vídeo (flags opt-in no ffmpeg-local)

- ✅ **Novas transições xfade**:
  - `whip_streak` → `hblur` 0.28s (horizontal blur c79 whip)
  - `zoom_punch` → `zoomin` 0.30s (emphasis cut)
  - `smooth_slide` → `smoothleft` 0.35s

- ✅ **`hold_final_s`**: duração configurável (default 3.0 = comportamento
  anterior, aceita 0.5-8.0). c79 law 9 recomenda 4-6s pro CTA landing.

- ✅ **`pacing: "tight"`**: clampa cada cena em `[1.5, 2.0]`s (exceto a
  última que ainda recebe hold). c79 law 1 — 1 ideia por beat, ~1.5s/cena.
  Default `""` = sem mudança.

### UI

- ✅ Modal `campanha-marketing` expõe:
  - `template` pill com ✨ Editorial Chrome
  - `use_vignette` / `use_perspective_grid` / `use_grain` (booleans)
  - `transition` pill com ✨ Whip streak / Zoom punch / Smooth slide
  - `hold_final_s` number input (step 0.5)
  - `pacing` pill (normal / ✨ tight)

### Pendente (próximas fases)

- 🟡 **Vídeo: chrome gradient headline via Playwright PNG overlay** —
  requer nova stage de pré-render no pipeline video-pro. ~2h. Fica como
  fase α-bis ou fase β.
- 🟡 **Vídeo: perspective grid PNG overlay** — 40min. Fica como fase α-bis.
- 🟡 **B1-B4**: word-by-word ASS reveal, SCALE 8× hero, callback visual,
  ajuste fino de pacing.
- 🔴 **Fase β**: worker `video-motion-graphics` HTML+GSAP (3-4 dias).

---

## 9. TL;DR

1. **c79 = qualidade Infinite-tier, stack Chromium+GSAP, hand-built.**
   Não escala, não é multi-tenant, e leva horas por vídeo.

2. **imkt4 = plataforma de produção automatizada.** 15-20× mais rápido,
   12 estilos, multi-tenant, approval, fila, A/B. Perde no "feels
   expensive" pelo limite intrínseco do ffmpeg filter_graph.

3. **6 técnicas do c79 dão pra portar em ~4h e fecham 80% do gap
   percebido:**
   chrome-gradient text · halo glow · perspective grid · whip-streak
   overlay · vignette · outro hold 4-6s.

4. **Carrossel rico nosso não tem concorrente direto em c79** — eles não
   fazem estático Instagram. Mas 4 técnicas estéticas (chrome-gradient,
   halo, grid, vignette) dão pra trazer via CSS puro em ~2h.

5. **Só migre pra HTML+GSAP (fase β) quando volume enterprise justificar
   GPU + Chrome headless.** Pra caso-uso atual, ffmpeg-local é a escolha
   certa.

---

**Referências:**
- `cchyperframes/MOTION_PHILOSOPHY.md` — 11 Leis + vocabulário completo
- `cchyperframes/video-projects/may-shorts-19/` — análogo 9:16 mais próximo
- `cchyperframes/video-projects/linear-promo-30s/` — análogo multi-surface
- `imkt4/doc/video-style-study.md` — estudo prévio mkt3 + c79 (70% paridade)
- `imkt4/workers/ffmpeg-local/server.py:1647` — nosso renderer atual
