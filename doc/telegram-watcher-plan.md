# Telegram Watcher — plano (parked)

> Worker daemon que escuta novas mensagens em grupos Telegram via
> telethon events e dispara recipes do imkt4 automaticamente com o
> texto da mensagem como brief.
>
> Status: **parked** — plano aprovado, implementação pendente.
> Data: 2026-04-20.

---

## 🎯 Objetivo

Automatizar o fluxo "nova ideia apareceu no grupo → gerou conteúdo
automaticamente":

```
Membro posta ideia no INEMA.FTD
        ↓
telegram-watcher detecta (real-time via NewMessage event)
        ↓
aplica filtros (autor admin? keyword? tamanho?)
        ↓
se passa → POST /recipes/campanha-marketing/run no gateway
        ↓
pipeline completo roda (brief → imagens → vídeo chrome overlay)
        ↓
approval humano via Telegram bot (opcional)
        ↓
publica ou notifica admin
```

---

## 🏗️ Arquitetura

### Worker `telegram-watcher`

**Diferente dos outros workers** — é um **daemon persistente**, não
request/response. Não tem capability `/execute` tradicional; fica
escutando eventos e dispachando jobs externamente.

**Stack:**
- telethon event handler: `client.on(events.NewMessage(chats=[...]))`
- Mantém sessão MTProto aberta (mesma session do telegram-scraper)
- Loop infinito (`client.run_until_disconnected()`)
- Port 8119 só pra endpoints de status/toggle (FastAPI)

**Estado persistido:**
- `data/tg-sessions/watcher_state.json`:
  ```json
  {
    "watchers": {
      "<watcher_name>": {
        "last_message_id": 12345,
        "last_fire_at": "2026-04-20T...",
        "total_fired": 42,
        "total_filtered": 8,
        "errors": []
      }
    }
  }
  ```

---

## 📝 Config — `config/telegram-watchers.yaml`

```yaml
watchers:
  - name: "ideas_inema_ftd"
    group: "https://t.me/c/2517011104"     # INEMA.FTD
    topic: null                              # null = todo grupo; int = tópico específico
    filters:
      from_authors_only: [7388953786]        # só admin (opcional)
      min_text_length: 40
      contains_any: ["ideia", "conteúdo", "post", "reel"]
      contains_none: ["teste", "debug"]
    trigger:
      recipe: "campanha-marketing"
      input_template:
        brief: "{message_text}"
        video_mode: "quick"
        chrome_text_overlay: true
        text_overlay_style: "chrome_overlay"
        platform: "instagram_reels"
      approval_mode: "human"                  # human | auto | none
    cooldown_seconds: 300                     # anti-spam
    enabled: true
    notify_on_trigger: true                   # DM ao admin

  - name: "daily_recap"
    group: "https://t.me/c/2389955773"
    topic: null
    filters:
      min_text_length: 100
    trigger:
      recipe: "carrossel-rico"
      input_template:
        brief: "{message_text}"
        slide_count: 5
        template: "editorial_chrome"
    cooldown_seconds: 600
    enabled: false
```

### Variáveis interpoláveis

Em `input_template`:
- `{message_text}` — texto da mensagem
- `{message_id}` — ID numérico
- `{date}` — ISO 8601 UTC
- `{from_id}` / `{from_name}`
- `{topic_id}` / `{topic_title}` (se msg em tópico)
- `{group_id}` / `{group_title}`

---

## 🎛️ Endpoints (FastAPI)

- `GET /watchers/status` → lista watchers, contadores, última atividade
- `POST /watchers/<name>/toggle` → liga/desliga sem restart
- `POST /watchers/<name>/trigger-test` → simula disparo (dry-run) pra testar filtros
- `POST /watchers/reload` → re-lê YAML (hot-reload)

---

## ⚙️ Decisões iniciais recomendadas

1. **Escopo inicial:** 1 watcher fixo pro INEMA.FTD → `campanha-marketing`.
2. **Quando disparar:** cada nova msg que bate filtros (sem batching).
3. **Review:** semi-auto — gera + manda pro admin aprovar via
   `approval_mode: human` (já suportado no recipe).

Escalar depois pra múltiplos watchers + batching + topicos específicos.

---

## 🧩 Integração com o que já existe

Reusa:
- ✅ Session do telegram-scraper (`data/tg-sessions/<tenant>.session`)
- ✅ Recipe `campanha-marketing` + stage approval human (gate Telegram)
- ✅ Bot token existente (`TELEGRAM_BOT_TOKEN`) pra notificar admin
- ✅ Gateway API `/recipes/<name>/run` pra dispatch

Adiciona:
- Worker novo `telegram-watcher/` (skill + server)
- Arquivo config `config/telegram-watchers.yaml`
- Entry em `scripts/start-dev.sh` com `--watch` flag
- Entrada em `workers.yaml` (registro pro status)
- Gitignore `data/tg-sessions/watcher_state.json`

---

## 📋 Checklist de implementação (quando retomar)

- [ ] `workers/telegram-watcher/SKILL.md` — contrato + config reference
- [ ] `workers/telegram-watcher/server.py`:
  - [ ] Load `config/telegram-watchers.yaml` + validar schema
  - [ ] Telethon client com NewMessage handler por watcher
  - [ ] Filter engine (authors, length, contains_any, contains_none)
  - [ ] Cooldown dict por watcher
  - [ ] Template interpolator (`{var}`)
  - [ ] Dispatch via httpx POST gateway
  - [ ] State persist após cada fire
  - [ ] FastAPI endpoints: /status, /toggle, /reload, /trigger-test
  - [ ] Graceful shutdown (SIGTERM → save state → disconnect)
- [ ] `config/telegram-watchers.yaml` (exemplo INEMA.FTD)
- [ ] `scripts/start-dev.sh` — adiciona `telegram-watcher`
- [ ] Notificação opcional via bot (reusa admin_bot existing)
- [ ] Teste: dispara msg teste no grupo → ve se recipe roda

---

## 🚨 Considerações de produção

- **Rate limits:** Telegram tem limite de recebimento ~30 msg/s.
  Nosso worker não faz requests, só recebe. Zero risco.
- **Dispatch limits:** se config é agressiva (ex: `contains_any: ["a"]`),
  pode disparar 100 runs/hora. Ter cooldown + pool size limit no gateway.
- **Session fail:** se sessão expirar, worker morre. Adicionar health
  check + restart automático via systemd/supervisord em prod.
- **Deploy:** supervisord restart on exit. Não é stateless — precisa ser
  unique worker, não múltiplas instâncias.

---

## 💰 Estimativa de esforço

- Implementação core: **~3h**
- Testes + tuning de filtros: **~1h**
- Deploy setup (supervisord): **~30min**

Total: **~4-5h** de trabalho.
