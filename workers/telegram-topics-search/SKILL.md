# telegram-topics-search

Capability: `telegram.topics_search`. Porta 8118.

## Papel

**Busca offline** no dataset já extraído pelo projeto
`telegramtopicosindex`. Lê a árvore `<root>/<group_id>/<topic_id>/`
com `messages.json` + `metadata.json` + `content.txt` e responde queries
em milissegundos sem tocar na API do Telegram.

Complementa o worker `telegram-scraper` (online, usa MTProto) — use este
pra pesquisar o que já foi coletado, e o scraper pra adicionar novo.

## Setup

Configurar no `.env`:
```
TG_TOPICS_DATA_DIR=/home/nmaldaner/projetos/telegramtopicosindex/out
```

Se não setar, default = `../telegramtopicosindex/out` (relativo ao repo).

## Estrutura do dataset esperada

```
<root>/
├── <group_id>/                    # ex: 2517011104
│   ├── grupo_metadata.json        # {titulo, total_topicos, topicos: [...]}
│   └── <topic_id>/                # ex: 163
│       ├── metadata.json          # {topic_id, topic_title, total_messages, ...}
│       ├── messages.json          # [{id, author, date, text, has_media, media_type}]
│       ├── content.txt            # versão legível
│       └── photo_*.jpg            # mídia (opcional)
```

## Input

```json
{
  "query": "IA Claude Code",
  "group_id": "2517011104",          // opcional, limita a um grupo
  "limit": 20,
  "include_messages": true,           // retorna as msgs match (default true)
  "case_sensitive": false,
  "search_in": ["title", "text", "author"]   // default todos
}
```

## Output

```json
{
  "matches": [
    {
      "group_id": "2517011104",
      "group_title": "INEMA.FTD",
      "topic_id": 163,
      "topic_title": "MENU Links Formação",
      "total_messages": 20,
      "matched_count": 3,
      "score": 12.5,
      "messages": [
        {"id": 717, "author": "INEMA", "date": "...", "text": "...", "snippet_html": "...<mark>Claude</mark>..."}
      ]
    }
  ],
  "total_matches": 5,
  "groups_scanned": 3,
  "topics_scanned": 187,
  "query": "IA Claude Code",
  "index_last_refresh": "2026-04-20T03:15:00Z"
}
```

## Algoritmo de scoring

Por tópico:
- +3 pontos se query bate no título
- +1 pontos por ocorrência no texto das mensagens
- +2 pontos se match no autor
- Bonus decaimento por recência: +0.5 se data mais recente < 30 dias

Ordenação desc por score, tiebreak por data mais recente.

## Cache de índice

- Carrega tudo em memória na primeira query (~50-200ms dependendo do volume)
- Checa mtime do diretório antes de cada query; re-indexa se mudou
- `limit` default 20, max 200

## Uso via recipe

Recipe `telegram-search.yaml` pode chamar este worker passando query.
Ou chama direto via `POST /jobs` com capability `telegram.topics_search`.
