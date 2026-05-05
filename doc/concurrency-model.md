# Modelo de concorrência

> Como o `imkt5` lida com múltiplos pedidos simultâneos quando os
> serviços upstream (`inemaimg`, `inemavox`, etc.) serializam internamente.

## Realidade do upstream

| Serviço | Mecanismo interno | Vazão real |
|---|---|---|
| `inemaimg` | `asyncio.Lock` em torno da GPU (`server.py:101,225,237`) | **1 por vez** |
| `inemavox` | `asyncio.Queue` + **1** `_worker_task` (`api/job_manager.py:439-446,571`) | **1 por vez** (acumula em fila interna sem bloquear o cliente) |

Ambos são **single-slot** por instância, por design. Conta de envelope:
1 imagem = 10–60s no inemaimg → vazão ≈ 60–360 imagens/hora por GPU.

## Estratégia do `imkt5`

Resposta em três camadas, todas já implementadas:

### Camada 1 — Fila do imkt5 absorve a rajada

Pedidos chegam → enfileirados em Redis (RQ) ou `InMemoryDispatcher`. O
cliente recebe `job_id` na hora; nunca bloqueia. Múltiplos pedidos do
mesmo usuário viram múltiplos jobs com `parent_job_id` correlato.

Implementação: `imkt5/gateway/queue.py`.

### Camada 2 — `max_concurrent` por worker (saturação)

Cada worker em `config/workers.yaml` declara seu `max_concurrent`. O
`CapabilityRegistry` rastreia `in_flight` por nome (via `acquire()` /
`release()`). O `select_worker` filtra workers saturados.

```yaml
- name: inemaimg
  capabilities: [image.generation, ...]
  max_concurrent: 1   # respeita o lock interno da GPU
```

Se todos os workers de uma capability estão saturados, `select_worker`
levanta `NoWorkerAvailable`. O caller pode:

- **Default**: enfileirar de novo (RQ tem retry).
- **Override**: passar `respect_capacity=False` pra aceitar overload (ex.:
  request HTTP de prioridade alta).

### Camada 3 — Load-balancing entre INSTÂNCIAS

Paralelismo real vem de **múltiplas instâncias** da mesma capability:

```yaml
- name: inemaimg-gpu0
  capabilities: [image.generation]
  endpoint: http://localhost:8000
  local: true, priority: 100, max_concurrent: 1

- name: inemaimg-gpu1
  capabilities: [image.generation]
  endpoint: http://localhost:8001     # outra GPU/máquina
  local: true, priority: 100, max_concurrent: 1

- name: inemaimg-cloud-runpod
  capabilities: [image.generation]
  endpoint: https://runpod.../inemaimg
  local: false, priority: 30, max_concurrent: 1
```

`_sort_key` ordena: local-first → maior priority → menos `in_flight`.
Resultado: **distribuição automática** entre instâncias livres; fallback
para remoto quando locais saturadas.

Cobertura: `tests/test_capacity.py` valida load-balancing, fallback
local→remoto sob saturação, e modo escape.

## Padrão de uso recomendado

### Dev local (1 GPU)

```yaml
- name: inemaimg
  endpoint: http://localhost:8000
  max_concurrent: 1
```

Vazão limitada à GPU; fila do imkt5 absorve picos. Suficiente para
desenvolvimento e testes.

### Produção pequena (1 máquina, múltiplas GPUs)

Subir múltiplas instâncias do `inemaimg` com `--port` diferente, cada
uma com `CUDA_VISIBLE_DEVICES=N`:

```bash
CUDA_VISIBLE_DEVICES=0 python server.py --port 8000 &
CUDA_VISIBLE_DEVICES=1 python server.py --port 8001 &
```

Registrar as duas em `config/workers.yaml` (gpu0/gpu1). 2x a vazão
sem mudar uma linha do `imkt5`.

### Produção grande (múltiplas máquinas, opcional cloud)

Adicionar workers remotos com `local: false, priority: <baixa>`. O
matcher só os usa quando os locais saturam.

## O que NÃO fazer

- **Aumentar `max_concurrent` artificialmente** para 4, 8, 16.
  O upstream serializa — só vai criar timeouts/backlog interno.
- **Fork em `inemaimg2`, `inemaimg3`** seguindo o padrão antigo do
  `yt-pub-lives`. A escala correta é múltiplas *instâncias* do mesmo
  código rodando em portas/GPUs diferentes, registradas no registry.
- **Fila própria dentro do adapter**. Já existe a fila do imkt5
  (Redis/RQ) — adapter é apenas tradução de contrato, sem estado.

## Resumo em 1 frase

**Concorrência interna do upstream é = 1; concorrência do `imkt5` é = N
por escala horizontal de instâncias, com fila absorvendo picos.**
