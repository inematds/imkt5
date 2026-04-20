# telegram-scraper

Capability: `telegram.group_fetch`. Porta 8117.

## Papel

Coleta mensagens de grupos Telegram (privados ou públicos) via **MTProto**
(`telethon`) usando sessão de usuário — tem acesso a histórico completo e
search nativo (Bot API não consegue).

## Pré-requisitos (setup 1×)

1. Pega `API_ID` + `API_HASH` em https://my.telegram.org/apps (grátis,
   5 min).
2. Coloca no `.env`:
   ```
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=abcdef...
   TELEGRAM_SESSION_DIR=./data/tg-sessions
   ```
3. Roda **uma vez** o script de autenticação pra gerar session file:
   ```bash
   python scripts/tg_auth.py +55SEU_NUMERO inema
   ```
   Pede código SMS (e senha 2FA se configurada). Session fica em
   `data/tg-sessions/inema.session`. Depois disso o worker usa essa
   sessão sem precisar login.
4. Sua conta já deve ser **membro** dos grupos que quer scrapeear.

## Input

```json
{
  "group": "https://t.me/meu_grupo" | "@meu_grupo" | -1001234567890,
  "mode": "search" | "all" | "since_last",
  "query": "ia agentes",
  "limit": 200,
  "since_date": "2026-04-01T00:00:00",
  "include_media": false,
  "tenant_id": "inema"
}
```

- **`mode: "since_last"`** (default) — busca só mensagens depois do
  `last_message_id` salvo pra esse grupo (idempotente). Na primeira
  chamada pega do zero (ou `since_date` se fornecido).
- **`mode: "search"`** — busca mensagens contendo `query` (Telegram
  server-side, rápido). Respeita `limit`.
- **`mode: "all"`** — re-fetch de tudo (ignora state). Use pra reindexar.

## Output

```json
{
  "messages": [
    {
      "id": 12345,
      "date": "2026-04-18T14:23:00Z",
      "from_id": 987654321,
      "from_name": "Fulano",
      "text": "Pessoal, alguém viu o post do...",
      "views": 132,
      "forwards": 3,
      "reply_to": 12340,
      "reactions": {"👍": 5, "🔥": 2},
      "media": null
    }
  ],
  "count": 50,
  "group": {
    "id": -1001234567890,
    "title": "Meu Grupo",
    "username": "meu_grupo",
    "members_count": 1234
  },
  "state": {
    "last_message_id": 12399,
    "last_fetched_at": "2026-04-20T02:58:12Z",
    "total_fetched_lifetime": 487
  }
}
```

## Tracking do "já buscou"

Arquivo `data/tg-sessions/state.json`:
```json
{
  "<tenant>": {
    "<group_id>": {
      "last_message_id": 12399,
      "last_fetched_at": "2026-04-20T02:58:12Z",
      "total_fetched_lifetime": 487
    }
  }
}
```

Atualizado após cada fetch bem-sucedido. Thread-safe via lock async.

## Limites

- Rate limit do Telegram: ~30-50 req/min pra listagem; search ~20/min.
  Worker respeita via `FloodWaitError` handler (sleep + retry).
- Mensagens muito antigas (>1 ano) podem ter text truncado pelo
  servidor.
- Se o grupo é muito grande (>500k msgs), modo `all` pode demorar — use
  `since_date` pra limitar.
- Max 200 msgs/request (Telegram API hard limit). Worker paginciona
  automaticamente se `limit > 200`.

## Segurança

- Sessão fica em `data/tg-sessions/<tenant>.session` — **sensível**
  (equivale a login). Não commitar, adicionar ao `.gitignore`.
- Worker nunca escreve mensagens (read-only por design).
- Não armazena contas de usuário além do session file.
