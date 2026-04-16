# Inventário de credenciais — projetos-fonte

> Valores reais **não** estão neste documento. Só mapeia quais chaves
> existem em cada projeto e onde reutilizá-las no `imkt4`.

## Resumo

| Projeto | Arquivo | Chaves únicas |
|---|---|---|
| `timesmkt3` | `.env` | 36 |
| `inemaimg` | (sem .env) | 0 — usa defaults internos |
| `inemavox` | `.env` | 2 (HF_TOKEN, FREESOUND_API_KEY) |
| `yt-pub-lives2` | `config/.env` | 10 |
| `openpcbot` | `.env` | 20 |

## Mapeamento → uso no `imkt4`

### Workers de mídia (geração)
| Capability | Key | Origem |
|---|---|---|
| `image.generation` (inemaimg local) | `INEMAIMG_URL`, `INEMAIMG_MODEL`, `INEMAIMG_QUALITY` | `timesmkt3/.env` |
| `image.generation` (KIE) | `KIE_API_KEY`, `KIE_DEFAULT_MODEL` | `timesmkt3/.env` |
| `image.generation` (Pollinations) | `POLLINATIONS_TOKEN` | `timesmkt3/.env` |
| `image.generation` (Piramyd) | `PIRAMYD_API_KEY` | `timesmkt3/.env` ou `yt-pub-lives2` |
| `audio.tts` (ElevenLabs) | `ELEVENLABS_API_KEY` | `timesmkt3/.env` ou `openpcbot/.env` |
| `audio.tts` (MiniMax) | `MINIMAX_API_KEY`, `MINIMAX_GROUP_ID` | `timesmkt3/.env` |
| `audio.tts` (Gradium) | `GRADIUM_API_KEY`, `GRADIUM_VOICE_ID` | `openpcbot/.env` |
| `audio.tts` (Fish Audio) | `FISH_AUDIO_API_KEY` | `timesmkt3/.env` |
| `audio.tts` (Groq Whisper — STT) | `GROQ_API_KEY` | `openpcbot/.env` |
| `audio.music` (Freesound) | `FREESOUND_API_KEY` | `timesmkt3/.env` ou `inemavox` |
| `research.market` (Tavily) | `TAVILY_API_KEY` | `timesmkt3/.env` |
| `image.stock` (Pexels) | `PEXELS_API_KEY` | `timesmkt3/.env` |
| `image.stock` (Pixabay) | `PIXABAY_API_KEY` | `timesmkt3/.env` |

### LLM providers
| Uso | Key | Origem |
|---|---|---|
| auto-reviewer + classifier | `OPENROUTER_API_KEY` + `OPENROUTER_BASE_URL` | `timesmkt3/.env` (canônico) |
| Claude subprocess (alternativa) | `ANTHROPIC_API_KEY` | `openpcbot/.env` |
| Ollama local | `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_ROUTER_MODEL` | `openpcbot/.env` |

### Canais de entrada
| Canal | Keys | Origem |
|---|---|---|
| Telegram (**cuidado: tokens em uso produção**) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | `timesmkt3/.env` (em uso pelo pipeline de marketing) |
| Telegram pessoal | `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID` | `openpcbot/.env` (assistente pessoal) |
| Slack | `SLACK_USER_TOKEN` | `openpcbot/.env` |

**Recomendação**: não reutilizar o bot do `timesmkt3` em produção para o
`imkt4` — roubaria mensagens do pipeline vivo. Criar bot dedicado
(`@imkt4_bot` via BotFather) quando Fase 5 chegar. Enquanto isso,
notificações administrativas (ex.: "build pronto") podem usar qualquer
um dos dois via `sendMessage` direto.

### Publicação (PublishBindings)
| Plataforma | Keys | Origem |
|---|---|---|
| YouTube (upload) | `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | `timesmkt3/.env` |
| YouTube destinos do yt-pub-lives | `CLIENT_ID`, `CLIENT_SECRET`, `API_KEY`, `GCP_PROJECT` | `yt-pub-lives2/config/.env` (e replicado em cada lives<N>) |
| Instagram | `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_ACCESS_TOKEN` | `timesmkt3/.env` |
| Threads | `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` | `timesmkt3/.env` |
| Google Workspace | `GOOGLE_API_KEY`, `GOOGLE_CREDS_PATH`, `GMAIL_TOKEN_PATH`, `GCAL_TOKEN_PATH` | `openpcbot/.env` |

### Storage & infra
| Recurso | Keys | Origem |
|---|---|---|
| Redis (managed) | `UPSTASH_REDIS_ENDPOINT`, `UPSTASH_REDIS_PASSWORD` | `timesmkt3/.env` |
| Storage público | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | `timesmkt3/.env` |
| Sheets (fonte histórica do yt-pub-lives) | `SPREADSHEET_ID` | `yt-pub-lives2/.env` |
| Vault (second brain) | `VAULT_PATH` | `openpcbot/.env` |

## Nota de segurança

- **Nunca commitar** `imkt4/.env`; está no `.gitignore`.
- Em produção, estas chaves **não** vão em `.env` — migrar para KMS
  (Vault/AWS/gcp-secret-manager) antes do deploy. `.env` é só ambiente
  de desenvolvimento local.
- Cada chave tem um "dono" no projeto-fonte — evitar regenerá-las
  enquanto os projetos originais estiverem em produção.

## Estratégia de `credentials_ref` para bindings

Tanto `SourceBinding` quanto `PublishBinding` carregam um campo
`credentials_ref: str` (ver `imkt4/types/bindings.py`). No scaffold
atual, o ref é **o nome da variável de ambiente** (ex.:
`env:YOUTUBE_REFRESH_TOKEN`); na migração pra produção, vira o path
no KMS (ex.: `kms:secrets/tenant-abc/yt-source-xyz`).
