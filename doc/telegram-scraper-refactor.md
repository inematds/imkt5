# Telegram Scraper — análise + refactor baseado em telegramtopicosindex

> Relatório da análise do projeto `telegramtopicosindex` (extrator
> maduro, com 560 LOC em `extrator_rapido.py`) e justificativa do
> refactor do worker `telegram-scraper` pra reusar os padrões testados
> em vez da minha primeira implementação genérica.
>
> Data: 2026-04-20.

---

## 1. Contexto

Primeira versão do `telegram-scraper` (porta 8117) foi escrita do zero
usando `telethon.iter_messages(entity, limit=N)` — flat, sem entender
grupos fórum ou tópicos. Funciona pra grupos simples mas perde muito
em grupos organizados por tópicos (como INEMA.FTD com 1900 tópicos).

O projeto local `~/projetos/telegramtopicosindex` já tem uma solução
produção-tier pra exatamente esse caso.

---

## 2. Comparação

| Feature | `telegramtopicosindex/extrator_rapido.py` | 1ª versão `telegram-scraper` |
|---|---|---|
| Parse link `t.me/c/<grupo>/<topic>` | ✅ regex dedicada | ❌ só `@username`/id |
| Listar tópicos fórum (`GetForumTopicsRequest`) | ✅ paginado 100/pg × 50 pg | ❌ |
| Extrair mensagens de 1 tópico (`reply_to=topic_id`) | ✅ | ❌ iter flat |
| Download fotos | ✅ timeout 60s + retry | ❌ |
| Download documentos | ✅ timeout 120s | ❌ |
| Filtro por extensão (`--filtro pdf,jpg`) | ✅ | ❌ |
| Modo `--somidia` (só mídia) | ✅ | ❌ |
| Output estruturado `out/<grupo>/<topic>/` | ✅ | ❌ formato próprio |
| Graceful error (pula tópico com erro) | ✅ | ⚠ parcial |
| Progresso + estatísticas finais | ✅ | ❌ |
| Anti-duplicação via `seen_ids` | ✅ | ❌ |
| Handle `from_id` serialização (user_id vs channel_id) | ✅ | ⚠ básico |

---

## 3. Pontos-chave do `extrator_rapido.py` a reusar

### 3.1 Parse de link

```python
def parse_telegram_link(link):
    # https://t.me/c/2238677701/3512 → (-1002238677701, 3512)
    # https://t.me/c/2238677701     → (-1002238677701, None)
    clean = link.replace('https://','').replace('http://','').replace('t.me/c/','')
    m = re.match(r'(\d+)(?:/(\d+))?', clean)
    chat_id = -int(f"100{m.group(1)}")
    topic_id = int(m.group(2)) if m.group(2) else None
    return chat_id, topic_id

def internal_c_id(chat_id): return str(chat_id)[4:]   # -1002238677701 → "2238677701"
```

### 3.2 Listar tópicos de grupo fórum (paginado)

```python
input_channel = InputChannel(entity.id, entity.access_hash)
seen = set()
offset_topic = offset_id = offset_date = 0
while True:
    result = await client(GetForumTopicsRequest(
        peer=input_channel,
        offset_date=offset_date, offset_id=offset_id, offset_topic=offset_topic,
        limit=100,
    ))
    if not result.topics: break
    novos = [t for t in result.topics if t.id not in seen]
    if not novos: break
    seen.update(t.id for t in novos)
    # atualiza offsets com último item da página
    last = result.topics[-1]
    offset_topic = offset_id = last.id
    offset_date = int(last.date.timestamp()) if hasattr(last,'date') else 0
```

### 3.3 Extrair mensagens de 1 tópico

```python
async for message in client.iter_messages(chat_id, reply_to=topic_id):
    messages.append(message)
```

O parâmetro `reply_to=<topic_id>` é o que o Telegram usa internamente
pra filtrar mensagens de um tópico específico em grupo-fórum.

### 3.4 Serialização robusta de autor

```python
author = "Desconhecido"
if msg.sender:
    author = (getattr(msg.sender, 'first_name', None)
              or getattr(msg.sender, 'title', None)
              or getattr(msg.sender, 'username', None)
              or "Desconhecido")
```

Cobre Users (first_name), Channels (title), Bots (username).

### 3.5 Download com timeout configurável

```python
await asyncio.wait_for(
    client.download_media(msg.media, filepath),
    timeout=60.0,  # foto
)
# ou 120.0 pra documento
```

### 3.6 Output tri-formato (metadata/json/txt)

- `metadata.json` — índice compacto
- `messages.json` — array completo pra processamento
- `content.txt` — legível pra humano (title + autor + texto + mídia)

Isso é **exatamente o que o `telegram-topics-search` consome**, então
reusar garante pipeline end-to-end.

---

## 4. Novo design

Worker `telegram-scraper` reescrito com 4 modos:

| Mode | O que faz | Resultado |
|---|---|---|
| `list_topics` | Só lista os tópicos do grupo, salva `grupo_metadata.json` | Sem extrair mensagens |
| `extract_topic` | Extrai 1 tópico (link deve conter topic_id) | `<out>/<grupo>/<topic>/` |
| `extract_all` | Lista + extrai todos os tópicos | `<out>/<grupo>/` com N subdirs |
| `incremental` | Lista tudo, pula tópicos já existentes | Extrai só novos |

**Payload:**
```json
{
  "group_link": "https://t.me/c/2517011104" | "https://t.me/c/2517011104/163",
  "mode": "list_topics" | "extract_topic" | "extract_all" | "incremental",
  "max_topics": 10,
  "baixar_midia": false,
  "file_filter": ["pdf", "jpg"],
  "somidia": false,
  "output_dir": null        // default = TG_TOPICS_DATA_DIR
}
```

**Output:**
```json
{
  "mode": "extract_all",
  "group": { "id": -1002517011104, "title": "INEMA.FTD", "internal_id": "2517011104" },
  "topics_listed": 38,
  "topics_extracted": 35,
  "topics_skipped": 0,
  "topics_failed": [ {id, title, error} ],
  "output_dir": "/home/.../telegramtopicosindex/out/2517011104",
  "extraction_date": "2026-04-20T..."
}
```

---

## 5. Pipeline resultante

```
┌───────────────────────┐    write   ┌─────────────────────────┐
│  telegram-scraper     │ ────────▶ │ TG_TOPICS_DATA_DIR/     │
│  (port 8117, online)  │            │   <grupo>/<topic>/      │
│  cap: group_fetch     │            │     metadata.json       │
└───────────────────────┘            │     messages.json       │
                                     │     content.txt         │
                                     │     photo_*.jpg / doc_* │
                                     └───────────┬─────────────┘
                                                 │ read
                                                 ▼
                                     ┌─────────────────────────┐
                                     │ telegram-topics-search  │
                                     │ (port 8118, offline)    │
                                     │ cap: topics_search      │
                                     └─────────────────────────┘
```

Mesmo diretório, contrato compartilhado, zero cross-coupling de código.

---

## 6. Decisão

**Refactor aprovado.** Copiar a lógica do `extrator_rapido.py` pro
worker do imkt4 (não import cross-project — evita acoplamento).

Reuso = padrões + contratos, não código importado direto.
