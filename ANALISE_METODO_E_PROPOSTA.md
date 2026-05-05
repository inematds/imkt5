# Método de Análise e Proposta Modular — imkt5

> Relatório inicial. Define (1) como os projetos existentes serão analisados e (2) a arquitetura-alvo para unificá-los preservando execução individual.

---

## Contexto

Projetos citados pelo usuário como ponto de partida:

- `timesmkt3`
- `inemaimg`
- `inemavox`
- `yt-pub-lives` + variantes numeradas (`yt-pub-lives1..10`, `yt-pub-lives-thumb`)
- `inemavox2`

Requisitos de alto nível:

- Cada serviço continua funcionando individualmente.
- Serviços compõem um pipeline que atende um ou mais canais.
- Múltiplos usuários simultâneos.
- Múltiplos pedidos do mesmo usuário em paralelo.
- Fila de atendimento gerenciada.
- Canais de entrada: Telegram, WhatsApp e app web.
- Outros projetos serão adicionados à análise depois.

---

## 1) Método de análise (ficha padrão por projeto)

Para cada projeto, uma **ficha técnica** idêntica. A ficha tem 8 campos:

| Campo | O que investigo |
|---|---|
| **Identidade** | Nome, propósito em 1 frase, estado (ativo / legado / duplicado) |
| **Stack** | Linguagem, framework, runtime, deps externas pesadas (ffmpeg, yt-dlp, modelos IA, etc.) |
| **Entradas** | Como recebe trabalho hoje — CLI, webhook, cron, fila, arquivo? Formato do payload |
| **Saídas** | O que produz — arquivo em disco, POST para outro serviço, registro em DB, mídia enviada |
| **Estado & persistência** | DBs, buckets, diretórios `media/`, `outputs/`, filas locais |
| **Dependências entre projetos** | Quem chama quem (descoberto via grep de URLs/paths) |
| **Pontos de dor** | Hard-codes de canal, paralelismo, singleton de recursos (GPU, conta Google), rate limits |
| **Contrato reutilizável** | Qual a "função pura" que esse projeto já é, e que vira um **worker** na arquitetura nova |

### Como preencher a ficha rapidamente, sem ler tudo

1. Ler `README.md`, `PROJETO.md`, `CLAUDE.md`, `docker-compose.yml`, `package.json` / `requirements.txt`, `ecosystem.config.cjs` — entregam ~80% do entendimento em minutos.
2. Mapear entrypoints (`server.py`, `main.*`, `worker.*`, `import_worker.py`) — só os arquivos raiz, sem varrer `node_modules`.
3. Grep dirigido: `http://`, `process.env`, `CHANNEL_ID`, `telegram`, `webhook` — expõe acoplamentos.
4. Variantes numeradas (`yt-pub-lives1..10`) **não lidas uma a uma** — confirmar que são clones e tratar como instâncias do mesmo worker parametrizado por canal.

### Produto do passo 1

Um único arquivo `ANALISE.md` com as fichas empilhadas + uma matriz de dependências (quem fala com quem).

---

## 2) Proposta modular (visão inicial)

A existência de múltiplos `yt-pub-lives<N>` é um sinal clássico de **worker + fila + parametrização por tenant/canal**. A proposta abaixo generaliza esse padrão para todos os serviços.

### Camadas

```
┌─────────────────────────────────────────────────────────────┐
│  CANAIS DE ENTRADA  (Telegram bot · WhatsApp · Web app)     │
│  → cada um é só um adapter que traduz msg → Job             │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  GATEWAY / API  (único ponto)                               │
│  • autentica usuário  • cria Job  • devolve job_id          │
│  • streama progresso de volta (SSE/WS)                      │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  ORQUESTRADOR + FILA  (Redis/BullMQ ou NATS ou n8n)         │
│  • uma fila por tipo de worker                              │
│  • prioridade, retry, dedupe por (user_id, request_hash)    │
│  • multi-tenant: tag `channel_id` em todo job               │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  WORKERS independentes, cada um com contrato HTTP/fila      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ inemaimg     │  │ inemavox     │  │ yt-pub-lives │  ...  │
│  │ (gera img)   │  │ (TTS/dub)    │  │ (ingest YT)  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  Cada worker: stateless, escala horizontal, aceita          │
│  {job_id, channel_id, user_id, payload} e reporta status.   │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  ESTADO COMPARTILHADO                                       │
│  • Postgres (jobs, usuários, canais, auditoria)             │
│  • Object storage (S3/MinIO) para mídia                     │
│  • Redis (cache, locks, progresso em tempo real)            │
└─────────────────────────────────────────────────────────────┘
```

### Princípios não-negociáveis

1. **Worker = caixa preta com contrato único.** Recebe `Job`, devolve `Result`. O que hoje é `yt-pub-lives2` vira `yt-pub-lives` (singular) parametrizado por `channel_id`. Os 10 clones desaparecem.
2. **Cada worker continua rodável sozinho** (Docker isolado, CLI própria). A fila é *opcional* — se um worker for chamado direto via HTTP, funciona. Isso preserva a regra "cada um funciona individual".
3. **Fila por tipo de trabalho**, não por canal. Canal é *metadado* do job, não topologia. É o que permite "mais de uma pessoa simultânea + múltiplos pedidos da mesma pessoa" sem reescrever nada.
4. **Adapters finos de canal** (Telegram / WhatsApp / Web) só sabem falar com o Gateway. Trocar WhatsApp Business por Evolution API não toca nos workers.
5. **Fila de atendimento ≠ fila de jobs.** Uma é humana (prioridade, posição visível ao usuário), outra é de execução. Implementar as duas, separadas.
6. **Identidade única de usuário** mesmo vindo de canais diferentes: chave (`telegram_id` | `whatsapp_phone` | `web_user_id`) → `user_id` canônico.

### Decisões pendentes (após as fichas)

- **Orquestrador**: n8n (já em uso), BullMQ puro, ou Temporal? Tradeoff definido após ver o que os projetos já trazem.
- **GPU / modelos pesados** (provável em `inemavox`): worker dedicado com fila própria e `concurrency=1`, ou pool?
- **Monorepo vs. multi-repo com lib compartilhada** (contrato de Job, clientes, tipos).

---

## Próximo passo

Executar o **passo 1** (análise + ficha) nos 5 projetos citados e entregar `ANALISE.md` consolidado. Só depois fechar a arquitetura final.

Alternativa: começar por subconjunto (ex.: só os `yt-pub-lives*` para validar o padrão de worker multi-canal antes dos outros).
