# Video Style Study — mkt3 + cchyperframes → imkt4

> Relatório consolidado da análise dos templates, estilos e técnicas de
> rendering de vídeo do **timesmkt3** + do **cchyperframes**
> (MOTION_PHILOSOPHY), com comparação ao estado atual do **imkt4** e
> lista priorizada de melhorias.
>
> Data: 2026-04-19. Commits relevantes: `3d81316` (editorial magazine),
> `5baa61d` (model-profiles), `ab6ae28` (reorder campanha).

---

## 1. mkt3 — catálogo canônico

### 1.1 Os 12 estilos visuais (`skills/video-art-direction/SKILL.md`)

| # | Style | Uso | Paleta primária | Motion | Transição | Music |
|---|---|---|---|---|---|---|
| 1 | **Neon Futurista** | tech/IA/startup | #00E5FF + #39FF14 | push-in, parallax-zoom | cut + glitch | synthwave 110-130 BPM |
| 2 | **Premium Minimal** | luxo, aspiracional | mono (#F2EFE9 + #C9A96E) | drift, subtle breathe | crossfade_long | piano_solo |
| 3 | **Energético** | fitness, youth | oranges + magentas | hard_zoom | cut | EDM 128+ BPM |
| 4 | **Emocional Cinematic** | storytelling | teal + dusty gold | pan_right, ken_burns | crossfade_long | piano_strings |
| 5 | **Corporate Clean** | B2B, institucional | #2563EB + whites | static | crossfade_short | ambient |
| 6 | **Streetwear Urban** | gen-Z, casual | duotone neon | hard_zoom | cut | trap |
| 7 | **Nature Organic** | wellness, sustentabilidade | greens+earthy | pan_right | crossfade_long | folk |
| 8 | **Retro Vintage** | 80s, nostalgia | VHS duotone | zoom_out | crossfade_short | jazz |
| 9 | **Bold Pop** | impacto, call-out | primárias saturadas | hard_zoom | cut | pop |
| 10 | **Dark Dramatic** | thriller, mistério | low-key + vermelho | zoom_in | fade_black | drone |
| 11 | **Playful Colorful** | kids, apps | pastels + saturados | breathe | whip_pan | ukulele_pop |
| 12 | **Editorial Documentary** | jornalismo, factual | earthy + sober | static | crossfade_short | piano_minimal |

**imkt4 status:** ✅ portados todos os 12 via `video-art-director` worker
(porta 8114) com a mesma nomenclatura. Hook_pattern/motion/transition/music
mapeados no dict `DEFAULTS_PER_STYLE`.

### 1.2 Os 8 "ffmpeg presets" (`skills/video-engineering/style-dictionary.json`)

Diferente dos styles visuais, são **perfis técnicos de encoding**. Cada
um carrega filter_chain ffmpeg específico e parâmetros de spring/easing
pro Remotion.

| Preset | ffmpeg filter | CRF | Fps | Mood |
|---|---|---|---|---|
| 01_hero_film | `curves=vintage, yuv422p10le, noise=alls=3` | 17 | 24 | premium |
| 02_product_demo | `unsharp=7:7:0.8` | - | - | clarity |
| 03_explainer | `scale=1920:-2,fps=30` | - | 30 | simplicity |
| 10_problem_solution | split+curves (dual LUT) | - | - | relief |
| 13_kinetic_typography | `drawtext+alpha(t)` animado | - | - | impact |
| 14_short_vertical | `scale=1080:1920+crop` | - | - | retention |
| 20_performance_ad | `setpts=0.5,tblend=average` | - | - | urgency |
| inema_hightech | **default INEMA** — high-tech + urgency | - | - | conversion |

**imkt4 status:** ❌ NÃO portado. Temos só color_grading (cool/warm)
genérico + letterbox via padding implícito. Cada preset aqui é uma
"receita completa" de render (grain + color curve + fps).

**Oportunidade:** criar `workers/ffmpeg-local/style_presets.json`
espelhando essa estrutura. `video_render` aceitaria `style_preset`
além de `style`. Ativaria filter_chain completo por preset.

### 1.3 Pipeline render (`pipeline/render-video-ffmpeg.js`)

**Nível de sofisticação:** 667 linhas. Features relevantes:

1. **Detecção automática `imageHasText`** via regex no filename
   (`/carousel_|logo_|banner|oficial|calendar/`).
   → Se detectou: `text_overlay = ""` + `zoom = 1.0` (estático, não
   corta o texto embutido).

2. **Banner/clip/imageHasText**: renderiza imagem 1:1 como **blurred
   background + sharp center** em 9:16 (sem crop, sem letterbox preto).
   ```
   scale=vidW:vidH:force_original_aspect_ratio=decrease + 
   blur no background + overlay center crisp
   ```

3. **Texto via ASS subtitles** (não `drawtext` direto). Permite kinetic
   typography, word-by-word reveal, animações avançadas.

4. **Fade in/out automático**: `min(0.4, duration/4)` em toda cena.

5. **Background types por cena** (`text_layout.background`):
   - `gradient`: faixa full-width na posição do texto
   - `dark_box`: caixa retangular centrada (85% width)
   - `none`: texto puro sobre imagem

6. **Safe margin** configurável (default 120px em 9:16).

7. **Font size adaptativo**: `<30chars=80px, 30-60=64, 60+=52`.

**imkt4 status:**
- ✅ Fade in/out: NÃO tem (mkt3 faz `fade=t=in:st=0:d=0.4`)
- ✅ Safe margin 120px: adicionado no último commit editorial
- ❌ Detecção `imageHasText`: NÃO temos (mas temos prevenção via
  TEXT_NEGATIVE + detecção heurística PIL no carousel-designer)
- ❌ Blur background composite pra 1:1→9:16: NÃO temos
- ❌ Text via ASS: só temos pra karaoke. drawtext direto pro overlay.
- ✅ Background types: temos só "faixa" (drawbox com opacity 0.32)
- ✅ Font size adaptativo: ajustado no último commit (88→60→44)

---

## 2. cchyperframes — MOTION PHILOSOPHY (as 11 Leis)

Repo `github.com/inematds/cchyperframes` — engenharia reversa do
**Infinite Global Payments 30s spot**. Resumo das leis:

1. **One idea per beat. Cut fast.** — avg 1.5s/cena
2. **Black is the canvas.** — 90% frame preto/escuro
3. **Light is the brand, not color.** — chrome gradients, halos, light beams
4. **Camera never sleeps.** — grid recuando, coin rotating, particles — static = death
5. **Motion blur is a feature.** — mascara cortes, feels expensive
6. **Object metaphors carry meaning.** — mesmo coin volta 3x = continuidade = brand
7. **Palette is symbolic, not decorative.** — cada cor = um conceito
8. **Type is a character.** — words SCALE 8×, MORPH, COMPRESS, GLOW
9. **Hold the hero shot.** — logo reveal 2s, outro 5s+. Kinetic chaos → calm = catharsis
10. **One unifying texture across everything.** — perspective grid + crosshairs + grain
11. **Timelines must fill their slots.** (HF-specific; N/A pra ffmpeg)

### 2.1 Vocabulário visual (11 técnicas principais)

| # | Técnica | Impl HF/GSAP | Impl via ffmpeg | imkt4? |
|---|---|---|---|---|
| 1 | Perspective grid floor | CSS `rotateX(60deg)` + repeating-gradient | overlay PNG pré-gerada | ❌ |
| 2 | Vignette radial | absolute overlay radial-gradient | `vignette=PI/4:eval=init` | ✅ pro mode |
| 3 | Pure black stage | body bg: #000 | background: #000 entre cenas | parcial |
| 4 | Horizontal speed lines | repeating-gradient + anima bg-position | `geq` custom | ❌ |
| 5 | Iridescent gradient | conic-gradient ou video loop | lookup LUT | ❌ |
| 6 | Conical light beam | conic-gradient blurred | PNG overlay | ❌ |
| 7 | Sparkle particles | stagger tween em divs | overlay particle loop | ❌ |
| 8 | Subtle film grain | shader | `noise=c0s=5:c0f=t+u` | ✅ pro mode |
| 9 | Liquid-glass card | backdrop-filter blur + highlight | N/A pure ffmpeg | ❌ |
| 10 | Film strip CSS | repeating-linear-gradient | N/A | ❌ |
| 11 | Chrome gradient text | pré-render como PNG transparente | Playwright like carousel | ❌ |

---

## 3. imkt4 — estado atual

### 3.1 O que temos alinhado ao mkt3

- ✅ **12 styles visuais** portados em `video-art-director`
- ✅ **Motion presets** (zoom_in/out, pan_left/right, hard_zoom, breathe, drift, static)
- ✅ **Hook patterns** (pattern_interrupt, stat_shot, question_abrupt, pov, value_bomb, contrast)
- ✅ **Transições** (cut, crossfade_short/long, fade_black, whip_pan) via ffmpeg xfade
- ✅ **Music genre** com 8 faixas sintéticas em `assets/music/`
- ✅ **SFX** (stab/swoosh/ding) opt-in por style+hook
- ✅ **Color grading** por seção narrativa (cool hook/tension → warm solution/CTA)
- ✅ **Karaoke** via ASS + faster-whisper (word-level timings reais)
- ✅ **Narration per-scene** (fanout TTS + sync ffprobe + dedup sha256)
- ✅ **Hold final 3s** + loop visual
- ✅ **Kinetic ASS presets** por style (fade/wipe/zoom_impact/type_on/glow_pulse)
- ✅ **Freeze frame** + zoom em revelações com whisper word-exact
- ✅ **Parallax fake** nível 1 (blur+unsharp) + depth_ai nível 2 (flag)
- ✅ **Safe zones por plataforma** (tiktok/reels/shorts)
- ✅ **Editorial magazine typography** (Playfair + outline 3px + shadow cinematic)
- ✅ **Vignette + grain** em pro mode (cchyperframes lei 2 + 10)

### 3.2 Gaps (o que o mkt3 tem e nós não)

**Alto impacto (quick wins):**

1. **Fade in/out automático por cena** (mkt3 pattern): `fade=t=in:d=0.4,fade=t=out:d=0.4`. 20min de trabalho. Dá polish imediato.

2. **Blur background composite 1:1→9:16**: quando imagem vem em formato diferente da cena alvo, em vez de crop+letterbox, usar **imagem original como blur background + center crisp**. Mata o crop ugly. ~1h.

3. **Detecção `imageHasText` automática**: regex no filename + flag auto-zero em zoom/overlay. ~40min.

**Médio impacto:**

4. **Style ffmpeg presets** (`01_hero_film`, `13_kinetic_typography`, `inema_hightech`): port do `style-dictionary.json` + aplicação via filter_chain. ~2-3h. Desbloqueia "hero film 2.35:1 + grain + 10-bit curves" com 1 flag.

5. **Text via ASS para overlay estático** (não só karaoke): permite kinetic type (SCALE 8×, MORPH), background types (gradient/dark_box/none) per-scene. ~3h.

6. **Chrome gradient text**: pré-renderizar headline via Playwright + overlay PNG no ffmpeg. ~2h. Reutiliza stack do carousel-designer.

**Longo prazo (grandes):**

7. **Pipeline HTML+GSAP motion graphics** (hyperframes-style): refatoração gigante. Substituiria ffmpeg-local por chromium-based render. Permitiria TODAS as técnicas avançadas (liquid glass, sparkle particles, perspective grid animado). Só faz sentido quando tivermos volume de renders que pague a GPU.

### 3.3 O que temos que mkt3 NÃO tem

- ✅ **Multi-tenant** desde o schema (mkt3 é single-user)
- ✅ **Fila capability-based** (mkt3 dispara direto)
- ✅ **Dedup TTS** sha256 cache (mkt3 regera sempre)
- ✅ **A/B variants com LLM suggest** (`video-ab-suggest`)
- ✅ **Approval flexível** (human/auto/agent) global override
- ✅ **Recipe runner declarativo YAML** com fanout/when/needs
- ✅ **UI completa**: runs/workers/recipes com modal/pills/tabs

---

## 4. Plano de evolução priorizado

### Fase 4a — Quick wins (total ~2h)
- [ ] **F1**: fade in/out por cena no ffmpeg-local (20min)
- [ ] **F2**: detecção imageHasText via regex filename (40min)
- [ ] **F3**: blur composite 1:1→9:16 quando dimensions mismatch (1h)

### Fase 4b — Style presets mkt3 (total ~3-4h)
- [ ] **F4**: port de `style-dictionary.json` pra
  `config/video-style-presets.json`
- [ ] **F5**: worker ffmpeg-local aceita `style_preset` + aplica
  filter_chain completa
- [ ] **F6**: UI modal adiciona pills de style_preset
  (hero_film/product_demo/kinetic_typo/inema_hightech)

### Fase 4c — ASS overlay + kinetic avançado (~4h)
- [ ] **F7**: migrar `_build_text_overlay` de drawtext pra ASS subtitles
- [ ] **F8**: text_animations kinetic (SCALE 8×, MORPH, fade-slide) via ASS
- [ ] **F9**: background types (gradient/dark_box/none) por cena

### Fase 4d — Motion graphics decorations (~3h)
- [ ] **F10**: perspective grid overlay pré-renderizado (PNG loop)
- [ ] **F11**: chrome gradient headline via Playwright PNG
- [ ] **F12**: sparkle particles loop mp4 asset
- [ ] **F13**: motion blur intencional em whip_pan (ffmpeg tblend)

### Fase 4e — Novo stack HTML+GSAP (v5, longo prazo)
- Avaliar quando: volume de render > 50/dia OU cliente premium exige
  qualidade Infinite-level
- Worker `video-motion-graphics` usando chromium headless + GSAP
- Compatibilidade retrógrada: recipe aceita `render_engine: ffmpeg|motion`

---

## 5. Testes realizados 2026-04-19

### Run QUICK (`f0b1470f-4493-4c1f-93bb-d798427c13fc`)
- Input: brief + image_count=3 + video_mode=quick
- Duração: 20.94s | Karaoke: False (novo default)
- Stages: 9/9 OK
- Art direction: ✅ escolheu style + motion + music automaticamente
- Issues: texto no overlay ainda em DejaVu (pré-commit editorial)

### Run PRO (`d5eccdf5-8359-432e-ac6a-fe0fb2d1317c`)
- Input: brief + video_mode=pro + use_parallax + freeze_frames + kinetic_presets
- Duração: 22.09s | Karaoke: False
- Stages: 9/9 OK
- Issues: vignette+grain NÃO aplicados (commit posterior ao run)

**Re-teste necessário após commit `3d81316`** (editorial + vignette +
grain) — próxima iteração.

---

## 6. Referências

- **mkt3 SKILLs estudados:**
  - `video-quick/SKILL.md` — magazine style (122 linhas)
  - `video-art-direction/SKILL.md` — 12 estilos catalogados
  - `video-engineering/style-dictionary.json` — 8 ffmpeg presets
  - `video-composition/advanced-composition-reference.md` — 20 composições + transições
  - `typography-on-image/SKILL.md` — hierarquia 5-tier
- **mkt3 pipeline:**
  - `pipeline/render-video-ffmpeg.js` — 667 linhas
  - `skills/image-generation/model-profiles.json` — 8 perfis de SD
- **cchyperframes:**
  - `MOTION_PHILOSOPHY.md` — 11 leis + vocabulário visual
  - Reference video: Infinite Global Payments 30s (1920×1080 30fps)

---

**Resumo:** Temos **~70% de paridade** com o mkt3 em features de vídeo,
com edge superior em multi-tenant, dedup e approvals. Os 30% restantes
são quase todos polish visual (fade, blur composite, ASS-driven text,
perspective grid). Implementável em 2 fases (~6h core + ~3h polish)
sem mudar arquitetura.
