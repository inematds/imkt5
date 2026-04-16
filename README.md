# imkt4

Plataforma modular que unifica vários projetos de pipeline (`timesmkt3`, `inemaimg`, `inemavox`, família `yt-pub-lives*`) em uma arquitetura única — preservando a execução individual de cada serviço — e adiciona multi-tenant, fila de atendimento e entrada por Telegram, WhatsApp e web.

## Camadas

```
Canais (TG · WA · Web)  →  Gateway Conversacional  →  Fila de Jobs  →  Workers
```

- **Canais** emitem `IncomingMessage` para o Gateway. Contrato único (`BaseChannel`) permite trocar o canal sem tocar no resto.
- **Gateway Conversacional** conversa, resolve o tenant, usa memória e LLM. Quando detecta trabalho pesado, chama a tool `dispatch_job(worker_type, payload)`.
- **Fila** desacopla pedidos de execução; permite concorrência por usuário, prioridade e retry.
- **Workers** são os projetos existentes, encapsulados como serviços stateless que aceitam `Job` e devolvem `Result`. Cada worker continua rodável sozinho.

## Origens

- **Blueprint arquitetural**: projeto `intelecto` (spec, não código). Define os contratos `BaseProvider`, `BaseChannel`, `BaseTool` e a stack de identidade em Markdown.
- **Peças reutilizadas**: projeto `openpcbot`. Doa schema SQLite multi-chat, ponte WhatsApp, wrapper Claude Agent SDK, base do dashboard web.
- **Workers**: absorvidos dos projetos `timesmkt3`, `inemaimg`, `inemavox`, `yt-pub-lives*`, etc. (análise pendente, ficha padrão definida).

## Estado

Scaffold inicial. Contratos e tipos canônicos definidos. Adapters de canal, providers de LLM e workers ainda **não implementados** — são absorvidos em fases posteriores.

Veja `doc/architecture.md` para a arquitetura completa e `ANALISE_METODO_E_PROPOSTA.md` para o contexto inicial.
