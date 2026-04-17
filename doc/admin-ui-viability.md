# Viabilidade — UI de administração

> Análise honesta: qual esforço pra ter uma interface web que permita
> editar defaults, gerenciar workers e criar/editar receitas — sem
> precisar tocar arquivos no disco.

## TL;DR

**Três features, três graus de dificuldade:**

| Feature | Dificuldade | Prazo estimado | Riscos |
|---|---|---|---|
| 1. Editor de config (defaults/tenant) | **Baixa** | 4–8h | Baixo — YAML é fácil de validar |
| 2. CRUD de workers (registrar endpoints) | **Baixa-média** | 6–10h | Confundir "registrar worker" com "criar serviço" |
| 3. Editor de receitas | **Média** | 1–3 dias | Validação complexa; preview visual opcional |
| 4. (bonus) Scaffolding de worker novo | **Alta** | 2–5 dias | Deploy/rebuild fora do escopo da UI |

Tudo factível. Recomendação abaixo de por onde começar e onde parar.

---

## 1. Editor de Config (defaults.yaml + tenant configs)

### O quê
UI com editor YAML pra:
- **Global**: `config/defaults.yaml` (admin global)
- **Tenant**: `profiles/<tenant_id>/config.yaml` (admin do tenant)

### Dificuldade: **BAIXA**

YAML → parse → validação pydantic → escreve. Backend `GET/PUT /config` já existe em forma simples (`GET /config`); só falta o PUT + frontend.

### Implementação

**Backend** (adicionar ao `imkt4/gateway/api.py`):

```python
from pathlib import Path
import yaml

@app.put("/config")
async def update_global_config(body: dict):
    # 1. validar schema
    # 2. escrever config/defaults.yaml
    # 3. recarregar settings (load(force=True))
    ...

@app.put("/config/tenant/{tenant_id}")
async def update_tenant_config(tenant_id: str, body: dict):
    path = Path(f"profiles/{tenant_id}/config.yaml")
    # ... idem
```

**Frontend** (nova rota `/admin` ou tab na UI atual):

- Editor tipo `<textarea>` com syntax highlight (Monaco ou CodeMirror CDN, ~30KB)
- Botão "Validar" (parse local)
- Botão "Salvar" (PUT)
- Warning se salvar global em prod

### Riscos
- Erro de YAML quebra o boot do gateway — **obrigatório** validar ANTES de escrever.
- Sem undo. Adicionar backup automático (`defaults.yaml.bak.<timestamp>`).
- Permissão: admin global ≠ admin de tenant. Precisa **autenticação** (hoje zero auth; MVP pode exigir token).

### Valor
Alto. Mudar um timeout ou adicionar `allowed_workers` num tenant sem SSH.

---

## 2. CRUD de Workers (registro)

### O quê
Dois casos distintos — é **crítico** não confundi-los:

#### 2a. "Registrar worker que já existe"
Apontar o registry pra um serviço HTTP que já está rodando em algum lugar. **Trivial** — só edita `config/workers.yaml`.

Exemplo: "quero adicionar uma segunda GPU rodando inemaimg" → adiciona `inemaimg-gpu1` no YAML.

#### 2b. "Criar um worker do zero"
Gerar código + Dockerfile + deploy. **Não pertence à UI.** É trabalho de engenharia.

### Dificuldade: **BAIXA** (só 2a)

Backend:

```python
@app.post("/admin/workers")
async def register_worker(w: WorkerDef):
    # 1. append em config/workers.yaml
    # 2. registry.register(w)
    # 3. dispara health check
    return {"ok": True}

@app.delete("/admin/workers/{name}")
async def unregister_worker(name: str):
    registry.unregister(name)
    # remover do YAML
```

Frontend:
- Formulário: name, endpoint, capabilities, local, priority, max_concurrent, timeout
- Botão "Testar health" (faz GET `/health` no endpoint antes de registrar)
- Lista de workers registrados com toggle enabled/disabled e delete

### Riscos
- Remover o último worker de uma capability crítica (quebra receitas).
- Registrar endpoint que responde `/health` mas não respeita `POST /execute`. Solução: teste mais rigoroso — enviar um Job de validação.

### Valor
Alto em ambiente de produção. Médio em dev local.

---

## 3. Editor de Receitas

### O quê
UI pra criar/editar receitas em `recipes/*.yaml`.

Dois níveis possíveis:

#### 3a. **YAML editor textual** (MVP)
- `<textarea>` com syntax highlight
- Validação sintática (parse)
- Validação semântica (todas capabilities existem, `needs` apontam pra stages válidos, expressões `$.` fazem sentido)
- Botão "Rodar dry-run" (tenta executar em modo sandbox, só reporta os jobs que seriam disparados)

Dificuldade: **média**. 1 dia de backend + 1 dia de frontend.

#### 3b. **Editor visual drag-and-drop** (bonus)
- Canvas com stages como nós; arestas = `needs`
- Dropdown de capability por stage
- Painel de aprovação por stage

Dificuldade: **alta**. 3+ dias. ReactFlow + validação elaborada.

### Backend (3a)

```python
@app.get("/admin/recipes")
async def list_recipes_raw():
    return [{"name": p.stem, "yaml": p.read_text()}
            for p in Path("recipes").glob("*.yaml")]

@app.put("/admin/recipes/{name}")
async def save_recipe(name: str, body: RecipeRaw):
    # 1. parse YAML + validar com load_recipe
    # 2. validar todas capabilities existem no registry
    # 3. validar `needs` e expressões
    # 4. escrever recipes/{name}.yaml
    # 5. recarregar catálogo
    return {"ok": True, "stages": [...]}

@app.post("/admin/recipes/{name}/dry-run")
async def dry_run(name: str, input: dict):
    # roda uma "simulação" com dispatcher fake — só reporta
    # quais jobs seriam criados, sem executar
    ...
```

### Valor
Alto. Criar novos fluxos (campanhas customizadas por tenant, workflows de suporte) sem SSH.

### Riscos
- Receita inválida em produção quebra Recipe Runner. **Obrigatório** validar no save.
- Expressões com referências circulares (`$.stages.A` em A mesmo). Detectável, mas precisa checar.

---

## 4. (Bonus) Scaffolding de worker novo

### O quê
UI permite: "criar um worker HTTP que chama uma API externa X com essas credenciais". Gera:
- `workers/<nome>/server.py` (template `BaseWorker` preenchido)
- `workers/<nome>/Dockerfile`
- `workers/<nome>/requirements.txt`
- entrada em `config/workers.yaml`
- entrada em `scripts/start-dev.sh`

### Dificuldade: **alta**

Não é difícil gerar o código — templates Jinja resolvem. O problema é o **deploy**:

- Em dev local: ok, gera arquivo + precisa restart manual.
- Em produção: precisa rebuild do container/imagem + `docker-compose up`. UI sozinha não resolve isso sem pipeline CI/CD integrado.

### Recomendação
**Não incluir no MVP.** Vale mais um template CLI:

```bash
./scripts/new-worker.sh meme-generator "image.meme" "image.upscale"
# → cria workers/meme-generator/server.py estruturado
# → adiciona em config/workers.yaml
# → lembra de editar handle() e rodar start-dev.sh
```

Mais simples, cobre 80% do valor.

---

## MVP recomendado (em ordem de impacto vs esforço)

### Sprint 1 (1–2 dias)
- `GET/PUT /admin/config/defaults` + UI: editor de defaults global
- `GET/PUT /admin/config/tenant/{tenant_id}` + UI: editor por tenant
- Validação sintática + backup antes de escrever

### Sprint 2 (1 dia)
- `POST/DELETE /admin/workers` + UI: registrar/remover endpoints HTTP já existentes
- Botão "Testar health" antes de registrar

### Sprint 3 (2 dias)
- `GET/PUT /admin/recipes/{name}` + UI: editor YAML textual com syntax highlight e validação
- `POST /admin/recipes/{name}/dry-run` pra testar antes de salvar

### Opcional (outros 2–3 dias)
- Editor visual drag-and-drop de receitas (ReactFlow)
- Scaffolding CLI de worker novo (`scripts/new-worker.sh`)

**Total MVP:** ~4–5 dias de desenvolvimento.

## Pendências críticas antes desse MVP

1. **Autenticação.** Hoje o gateway é aberto. Admin UI sem auth é inaceitável em qualquer ambiente multi-user.
2. **Persistência do histórico.** Edição de config/receita deveria gerar audit log (quem mudou o quê, quando) — precisa Postgres.
3. **RBAC.** Admin global ≠ admin de tenant. Role-based access control.

Os três itens acima são **pré-requisitos** de produção — em dev local, dá pra começar sem.

## Alternativa: não fazer UI, investir em DX

Uma opção é **não** construir essa UI e investir em:

- `.yaml` bem estruturado + schema documentado (já temos)
- Git como fonte da verdade (`recipes/` e `config/` versionados)
- Um bot no Telegram que responde `/config`, `/add-worker`, `/new-recipe` com fluxos guiados

Argumento: em multi-tenant real, o admin é o dono da empresa, não um desenvolvedor. Um bot no Telegram é mais acessível que uma UI nova. Gateway conversacional (próximo passo do plano) já cobre isso parcialmente.

## Recomendação final

**Começar por 1 (editor de config)** porque:
- Menor esforço
- Valor imediato (mudar timeout, ativar workers por tenant)
- Padrão reutilizável (editor YAML com validação) vira base pros outros

**Pular scaffolding de worker** no MVP — deixa pra CLI.

**Editor de receitas textual** (3a) entra no sprint 3; editor visual (3b) é backlog.

Esta é uma feature que vale esperar o Gateway conversacional + canal Telegram ficarem prontos primeiro — sem canal, a UI web é o único acesso e fica frágil. Com Telegram em paralelo, a UI web é uma das interfaces, não a única.
