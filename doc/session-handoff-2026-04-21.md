# Session Handoff — 2026-04-20 → 21

> Estado consolidado da sessão de trabalho Abril 2026. Use este doc pra
> retomar sem precisar ler todo o histórico.

---

## 🎯 O que foi feito (20 commits)

### Fase α — c79/cchyperframes integration

| Commit | O que |
|---|---|
| `53b1538` | Estudo video-style (mkt3 + c79), plano 4a-4e |
| `3d81316` | video-quick editorial magazine style (mkt3) |
| `c7deb44` | Relatório c79 × imkt4 (MD + PDF + tabela consolidada) |
| `4c51df0` | **Fase α**: chrome gradient + grid + vignette + whip_streak opt-in |
| `9c6d132` | **Fase α-bis**: chrome text overlay no vídeo (worker video-text-designer :8116) |
| `3cfab7c` | Overlay reforçado + modo `full_slide` (carrossel-rico) |
| `18c8a33` | **7 estilos** com galeria visual + modal no-dismiss |
| `481f21d` | Manifest único `styles.json` + `editorial_chrome_rico` + preset thumbs |

### UX / Modal

| Commit | O que |
|---|---|
| `2a46f2e` | Detalhe da run: formulário completo com defaults + botão clonar |
| `78f5dbc` | Fix `_urls_in_output` recursivo nos stages outputs |
| `d292316` | **3 abas no modal** (Formulário / Presets / Exemplos) + seções |
| `159bcf3` | Fix dependsOn com checkbox (text_overlay_style ficava invisível) |
| `51d98c9` | Aba Exemplos: thumb real (`/video-thumb?u=...`) + click abre preview |
| `d178133` | Workers UI: thumbnails inline em cada job |

### Telegram workers

| Commit | O que |
|---|---|
| `599f118` | `telegram-scraper` (:8117 online MTProto) + `telegram-topics-search` (:8118 offline) |
| `26a32e1` | **v2 do scraper** baseado em `extrator_rapido.py` — 4 modos: `list_topics` / `extract_topic` / `extract_all` / `incremental` |
| `4986bc2` | Plano parkeado do `telegram-watcher` (daemon real-time) |

---

## 📂 Docs criados (6 novos)

| Doc | Conteúdo |
|---|---|
| `doc/c79-vs-imkt4-comparison.md` + `.pdf` | Análise completa cchyperframes × imkt4 |
| `doc/c79-vs-imkt4-table.md` + `.pdf` | Tabela consolidada |
| `doc/video-style-study.md` | Estudo mkt3 + c79 (270 linhas) |
| `doc/telegram-scraper-refactor.md` | Análise extrator_rapido → refactor scraper |
| `doc/telegram-watcher-plan.md` | Plano parkeado ~4-5h |
| `doc/session-handoff-2026-04-21.md` | Este arquivo |

---

## 🔧 Workers / Recursos novos

### Porta 8116 — `video-text-designer`
Playwright headless renderiza texto de cena como PNG RGBA transparente.
Consumido pelo `ffmpeg-local` via `chrome_text_overlay: true`.

**Catálogo de 8 estilos** em `workers/video-text-designer/styles.json`:
- chrome_overlay · chrome_fullslide · **editorial_chrome_rico** (carrossel-rico layout completo)
- magazine_bar · solid_block · stamp_diagonal · kinetic_pop · minimal_caption

**Regerar thumbs:** `python scripts/gen_text_style_thumbs.py` (idempotente).

### Porta 8117 — `telegram-scraper` (online, MTProto)
Reusa padrões de `extrator_rapido.py`:
- Parse `t.me/c/<grupo>[/<topic>]`
- `GetForumTopicsRequest` paginado (100/pg × 50pg)
- `iter_messages(reply_to=topic_id)` pra tópico fórum
- Download opcional fotos/docs com timeout + filtro extensão

**Modos:** `list_topics` / `extract_topic` / `extract_all` / `incremental`.

### Porta 8118 — `telegram-topics-search` (offline)
Busca indexada em milissegundos no dataset extraído. Scoring + highlight `<mark>`. Zero API.

---

## 🟢 Serviços rodando (13)

Gateway + 12 workers:
- carousel-composer, carousel-designer, carousel-outline
- ffmpeg-local, video-quick, video-pro
- video-art-director, video-ab-suggest, video-text-designer
- telegram-scraper, telegram-topics-search
- + 1 worker auxiliar

**Restart:** `./scripts/stop-dev.sh && ./scripts/start-dev.sh`

---

## ⚠️ Pendências / Setup necessário

1. **Telegram user auth** (pra destravar `telegram-scraper` online):
   - `.env`: `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` (pega em my.telegram.org)
   - Rodar 1×: `python scripts/tg_auth.py +55SEU_NUMERO inema`
   - Session fica em `data/tg-sessions/inema.session`

2. **Test pipeline Telegram completo** (scraper produz → search consome)

---

## 🅿️ Parked (retomar quando quiser)

| Item | Doc de referência | Esforço |
|---|---|---|
| `telegram-watcher` daemon (real-time NewMessage events) | `doc/telegram-watcher-plan.md` | ~4-5h |
| Fase β cchyperframes (worker HTML+GSAP paralelo) | `doc/c79-vs-imkt4-comparison.md` | 3-4 dias |
| Style presets mkt3 (8 ffmpeg filter_chains) | `doc/video-style-study.md` | ~3-4h |
| Recipe UI + form field pro telegram-scraper | — | ~1-2h |

---

## 🧠 Decisões arquiteturais importantes

1. **Dois workers Telegram complementares** (online + offline, mesmo diretório de I/O)
2. **`styles.json` como source of truth** dos estilos de text overlay
3. **Flag `data-modal-no-dismiss`** no modal Nova Execução (só X ou Rodar fecham)
4. **`_urls_in_output` recursivo** pra URLs `file://` aninhadas em stages
5. **Seções do form abertas por default** (user pode fechar)
6. **Recipe `carrossel-simples` v7 + `carrossel-rico` v6 + `campanha-marketing` v12** — todos aceitam text overlay flags

---

## 🔗 Onde pegar as coisas

- **UI de execuções:** http://localhost:8080/runs-ui
- **UI de workers:** http://localhost:8080/workers-ui
- **Thumbs text-style:** http://localhost:8080/text-style-thumbs/{slug}.jpg
- **Video thumb extraído:** http://localhost:8080/video-thumb?u=<url>
- **Catálogo de text styles:** http://localhost:8080/text-style-catalog

---

## 💬 Como retomar em sessão nova

Pra continuar onde parou, carrega `doc/session-handoff-2026-04-21.md` +
olha `TaskList` (esperado: vazio ou com próximas parked).

Comandos úteis pra validar estado:
```bash
cd ~/projetos/imkt4
./scripts/start-dev.sh                                 # sobe tudo
curl -s http://localhost:8080/ | head -1               # gateway OK?
curl -s http://localhost:8118/health                   # topics-search OK?
git log --oneline -5                                   # últimos commits
ls doc/ | tail -5                                      # docs recentes
```

---

Sessão fechada: 2026-04-21. Context estava 64% ao encerrar — ideal reset.
