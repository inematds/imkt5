# c79 × imkt5 — tabela comparativa consolidada

> Resumo executivo da comparação entre `cchyperframes` (Hyperframes:
> Chromium headless + HTML + GSAP) e `imkt5` (ffmpeg-local + workers
> stateless + fila + multi-tenant).
>
> Relatório completo: [`c79-vs-imkt5-comparison.md`](./c79-vs-imkt5-comparison.md).
> Data: 2026-04-19.

---

## 1. Arquitetura / Engine

| Dimensão | c79 (cchyperframes) | imkt5 (quick + pro) | Vencedor |
|---|---|---|---|
| Render engine | Chromium headless + GSAP | ffmpeg filter_complex | 🤝 usos diferentes |
| Autoria | HTML + CSS + JS hand-built | YAML recipe + JSON scene_plan | 🏆 imkt5 |
| Tempo render (20s vídeo) | ~5 min | ~20 s | 🏆 imkt5 (**15×**) |
| Custo infra | GPU + Chrome | CPU-only | 🏆 imkt5 |
| Escala horizontal | ❌ monolito local | ✅ workers stateless + fila | 🏆 imkt5 |
| Multi-tenant | ❌ single-user | ✅ desde schema | 🏆 imkt5 |
| Determinismo | ✅ seeded PRNG | ✅ ffmpeg puro | 🤝 |

---

## 2. Visual / Motion Graphics

| Técnica | c79 | imkt5 | Vencedor |
|---|---|---|---|
| Chrome gradient headline | ✅ `bg-clip:text` nativo | ❌ impossível drawtext | 🏆 c79 |
| Halo glow emphasis | ✅ text-shadow duplo | ⚠ só shadow escuro | 🏆 c79 |
| Word-by-word kinetic reveal | ✅ GSAP stagger 0.35s | ⚠ só karaoke opt-in | 🏆 c79 |
| SCALE 8× hero word | ✅ scale 1→8, opacity→0 | ❌ | 🏆 c79 |
| Perspective grid floor | ✅ CSS `rotateX(60deg)` | ❌ | 🏆 c79 |
| Vignette radial | ✅ sempre on | ✅ pro mode | 🤝 |
| Film grain | ✅ CSS puro | ✅ `noise=c0s=5` | 🤝 |
| Motion blur transições | ✅ whip-streak + Chrome | ⚠ parcial (tblend) | 🏆 c79 |
| 3D rotate (coin/wheel) | ✅ pré-render MP4 + CSS 3D | ❌ | 🏆 c79 |
| Liquid-glass cards | ✅ backdrop-filter | ❌ | 🏆 c79 |
| Sparkle particles | ✅ GSAP stagger | ❌ | 🏆 c79 |
| Callback visual | ✅ parte da doutrina | ❌ | 🏆 c79 |
| Outro hold 4-6s | ✅ lei 9 | ⚠ 3s default | 🏆 c79 |
| Pacing 1.5s/cena | ✅ lei 1 | ⚠ 3-4s default | 🏆 c79 |
| **12 styles artísticos** | ❌ 1 estética | ✅ art-director LLM | 🏆 imkt5 |
| Color grading por seção | ❌ | ✅ cool hook→warm cta | 🏆 imkt5 |

---

## 3. Áudio

| Dimensão | c79 | imkt5 | Vencedor |
|---|---|---|---|
| Narração | Talking-head real (manual) | TTS sintético auto | 🤝 |
| TTS dedup sha256 cache | ❌ | ✅ | 🏆 imkt5 |
| Música underscore | ⚠ manual 0.15 vol | ✅ sidechain duck por style | 🏆 imkt5 |
| SFX (stab/swoosh/ding) | ⚠ manual | ✅ opt-in style+hook | 🏆 imkt5 |
| Karaoke word-level | ✅ opt-in | ✅ opt-in | 🤝 |

---

## 4. Inteligência / Automação

| Capacidade | c79 | imkt5 | Vencedor |
|---|---|---|---|
| LLM art direction (style do brief) | ❌ | ✅ video-art-director | 🏆 imkt5 |
| LLM copywriter | ❌ | ✅ creative-brief + copywriter | 🏆 imkt5 |
| A/B variants LLM-suggest | ❌ | ✅ video-ab-suggest | 🏆 imkt5 |
| SD image generation inline | ❌ assets manuais | ✅ inemaimg + 8 profiles | 🏆 imkt5 |
| TEXT_NEGATIVE + imageHasText | N/A | ✅ 3 camadas | 🏆 imkt5 |
| Recipe declarativo YAML | ❌ | ✅ needs/when/fanout | 🏆 imkt5 |
| Approval flow (H/A/A) + Telegram | ❌ | ✅ | 🏆 imkt5 |

---

## 5. Deliverables

| Formato | c79 | imkt5 | Vencedor |
|---|---|---|---|
| Vídeo 9:16 (reels/shorts/tiktok) | ✅ hand-built | ✅ automático | depende do ROI |
| Vídeo 16:9 (landscape promo) | ✅ hand-built | ✅ automático | depende do ROI |
| **Carrossel Instagram estático** | ❌ não existe | ✅ 5 templates | 🏆 imkt5 |
| Campanha multi-asset | ❌ | ✅ campanha-marketing.yaml | 🏆 imkt5 |

---

## 6. Carrossel rico — imkt5 vs análogo c79 (`05-product-surfaces`)

| Elemento | imkt5 carrossel-rico | c79 cena multi-surface |
|---|---|---|
| Deliverable | 7 PNGs estáticos Instagram | Frames dentro de vídeo |
| Tipografia | Playfair 900 + outline + shadow | **Instrument Serif italic 140px + chrome gradient + halo** |
| Background | SD image + veil OR solid | Perspective grid + vignette + grain |
| Text-in-image detection | ✅ PIL edge heuristic | N/A |
| Templates | 5 variantes | Hand-built por projeto |
| Stat module (números) | ✅ stat_a/stat_b | ⚠ raro |
| Brand-moment final | ✅ logo + handle + tagline | ⚠ só em vídeo |
| Callback (elemento volta) | ❌ | ✅ |
| Autoria | LLM, 0 hand-build | 100% hand-build |
| Tempo produção | ~90s | horas |

---

## 7. Matriz de decisão — quando usar qual

| Cenário | Recomendação |
|---|---|
| Post Instagram carrossel 7 slides/dia | 🏆 imkt5 (único que faz) |
| Reels/TikTok em escala (20+/semana) | 🏆 imkt5 |
| Reels talking-head polido semanal | 🏆 c79 (may-shorts-19 model) |
| Promo 30s pitch investidor / launch premium | 🏆 c79 |
| Conteúdo educacional B2B (100+ vídeos/mês) | 🏆 imkt5 |
| A/B testing paid media | 🏆 imkt5 |
| Campanha multi-asset automatizada | 🏆 imkt5 |

---

## 8. Ações priorizadas — portar do c79 para imkt5

| Prioridade | Técnica | Custo | Stack atual? |
|---|---|---|---|
| 🟢 A1 | Chrome gradient text (Playwright PNG overlay) | 2h | ✅ sem trocar engine |
| 🟢 A2 | Halo glow emphasis | 30min | ✅ |
| 🟢 A3 | Perspective grid CSS/PNG | 1h | ✅ |
| 🟢 A4 | Vignette radial default | 10min | ✅ |
| 🟢 A5 | Whip-streak transition overlay | 1h30 | ✅ |
| 🟢 A6 | Outro hold 4-6s obrigatório | 30min | ✅ |
| 🟡 B1 | Word-by-word ASS reveal | 3h | ✅ |
| 🟡 B2 | SCALE 8× hero word via ASS `\fscx` | 2h | ✅ |
| 🟡 B3 | Callback visual scene[-2] | 1h | ✅ |
| 🟡 B4 | Pacing 1.5s/cena (flag) | 30min | ✅ |
| 🔴 C1 | Worker `video-motion-graphics` HTML+GSAP | 3-4 dias | ❌ nova stack |
| 🔴 C2 | Liquid-glass / iridescent / 3D real | depende C1 | ❌ |

---

## 9. Score final por eixo

| Eixo | c79 | imkt5 |
|---|---:|---:|
| Visual / Motion Graphics | **9** | 3 |
| Áudio | 0 | **3** |
| Inteligência / Automação | 0 | **7** |
| Escala / Infra | 0 | **5** |
| Deliverables | 0 | **3** |
| **TOTAL** | **9** | **21** |

---

## 10. Conclusão

- **c79** vence no "feels expensive" puro (motion graphics Infinite-tier).
- **imkt5** vence em tudo que é volume, automação, multi-tenant e carrossel.
- **Fase α** (6 técnicas CSS/PNG em ~6h) fecha ~80% do gap visual sem trocar engine.
- **Fase β** (worker HTML+GSAP paralelo) só faz sentido quando cliente
  enterprise paga premium OU volume > 50 renders/dia.

**Risco de implementação:** zero. Tudo atrás de flag opt-in ou template
novo. Runs antigos re-rodam idênticos; novos runs escolhem estética.
