# telegram-scraper

Capability: `telegram.group_fetch`. Porta 8117.

## Papel

Extrai mensagens de **grupos Telegram com tópicos** (grupo fórum) via
MTProto (telethon, user session). Reusa padrões testados do projeto
`telegramtopicosindex` — parse de link `t.me/c/`, `GetForumTopicsRequest`
paginado, `iter_messages(reply_to=topic_id)`, download opcional de mídia.

**Pipeline:** este worker **produz** → `telegram-topics-search` **consome**
(no mesmo diretório `TG_TOPICS_DATA_DIR`).

## Pré-requisitos (setup 1×)

1. Pega `API_ID` + `API_HASH` em https://my.telegram.org/apps (grátis).
2. `.env`:
   ```
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=abcdef...
   TELEGRAM_SESSION_DIR=./data/tg-sessions
   TG_TOPICS_DATA_DIR=/caminho/pasta/out   # onde os tópicos serão salvos
   ```
3. Roda 1× pra autenticar:
   ```bash
   python scripts/tg_auth.py +55SEU_NUMERO inema
   ```
   Pede código SMS + senha 2FA. Session fica em
   `data/tg-sessions/inema.session`.
4. Sua conta já deve ser **membro** do grupo.

## 4 Modos

| Mode | O que faz | Requer link com topic? |
|---|---|---|
| `list_topics` | Só lista tópicos do grupo, salva `grupo_metadata.json`. **Não extrai mensagens.** | não |
| `extract_topic` | Extrai mensagens de **1 tópico** específico | ✅ sim (ou passar `topic_id` no payload) |
| `extract_all` | Lista tudo + extrai todos os tópicos | não |
| `incremental` | Igual `extract_all`, mas **pula tópicos que já existem** em disco (tem `metadata.json`) | não |

## Input

```json
{
  "group_link": "https://t.me/c/2517011104",
  "mode": "extract_all",
  "max_topics": 10,
  "baixar_midia": false,
  "file_filter": ["pdf", "jpg"],
  "somidia": false,
  "output_dir": null,
  "tenant_id": "inema"
}
```

- `group_link` — aceita URL `t.me/c/<grupo>[/<topic>]` OU chat_id numérico
  (ex: `-1002517011104`).
- `baixar_midia` — baixa fotos (60s timeout) e documentos (120s timeout).
- `file_filter` — só baixa extensões específicas (`["pdf","jpg"]`).
- `somidia` — baixa SÓ mídia, não cria `messages.json`/`content.txt`.
- `output_dir` — default = `TG_TOPICS_DATA_DIR` do `.env`.
- `tenant_id` — determina qual session file usar.

## Output

### Mode list_topics
```json
{
  "mode": "list_topics",
  "group": {"id": 2517011104, "chat_id": -1002517011104, "title": "INEMA.FTD", "internal_id": "2517011104"},
  "topics_count": 38,
  "topics": [{"id": 163, "title": "MENU Links Formação", "date": "...", "from_id": 7388953786}, ...],
  "topics_truncated": false,
  "output_dir": "/.../out/2517011104"
}
```

### Mode extract_topic
```json
{
  "mode": "extract_topic",
  "group": {"chat_id": -1002517011104, "internal_id": "2517011104"},
  "topic": {
    "topic_id": 163,
    "topic_title": "MENU Links Formação",
    "path": "/.../out/2517011104/163",
    "messages_count": 20,
    "media_count": 0
  },
  "output_dir": "/.../out/2517011104"
}
```

### Mode extract_all / incremental
```json
{
  "mode": "extract_all",
  "group": {...},
  "topics_listed": 38,
  "topics_extracted": 35,
  "topics_skipped": 0,
  "topics_failed": [{"id": 1234, "title": "...", "error": "..."}],
  "extracted": [{"topic_id", "path", "messages_count", "media_count"}, ...],
  "output_dir": "/.../out/2517011104",
  "extraction_date": "2026-04-20T..."
}
```

## Estrutura de saída

Segue exatamente o padrão do `telegramtopicosindex`:

```
<output_dir>/
└── <grupo_id>/
    ├── grupo_metadata.json           # {titulo, total_topicos, topicos: [...]}
    └── <topic_id>/
        ├── metadata.json              # {topic_id, total_messages, topic_title, ...}
        ├── messages.json              # [{id, author, date, text, has_media, ...}]
        ├── content.txt                # legível pra humano
        ├── photo_<msgid>_NNN.jpg      # se baixar_midia
        └── document_<msgid>_NNN.*     # se baixar_midia
```

O `telegram-topics-search` (port 8118) lê exatamente essa estrutura pra
responder queries offline.

## Limites conhecidos

- `GetForumTopicsRequest` limit 100/pg × 50 pg = 5000 tópicos max por grupo.
- Rate limit Telegram: ~30-50 req/min. Pra grupos com muitos tópicos,
  usar `max_topics` em batches ou `mode: incremental`.
- `iter_messages(reply_to=...)` pega TODAS as mensagens do tópico de uma
  vez — se o tópico é muito grande (10k+ msgs), pode demorar alguns
  minutos.
- Download de mídia é opcional pela performance — default OFF.
