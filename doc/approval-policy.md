# Política de Aprovações

> Regra fixada pelo usuário: **aprovação default = `auto_reviewer`**.
> Aprovação humana (`user` ou `human_reviewer`) só quando pedida
> explicitamente.

## Os três modos (recap)

| Mode | Decidido por | Quando |
|---|---|---|
| `none` | ninguém | stages triviais sem decisão |
| `auto_reviewer` | worker `auto-reviewer` (LLM + critérios) | **DEFAULT** pra tudo que precisa validação |
| `user` | solicitante original no chat | só quando pedido explicitamente |
| `human_reviewer` | humano de papel designado | workflow com revisor dedicado |

## Como o usuário pede aprovação humana

Três formas de opt-in:

### 1. No input da receita
```bash
curl -X POST http://localhost:8080/recipes/campanha-marketing/run \
  -d '{"input":{"brief":"...","with_user_approval":true}}'
```

Receita usa `when: $.input.with_user_approval == true` nos stages de
aprovação humana.

### 2. Via mensagem natural no chat
```
usuário: "cria uma campanha do produto X — quero aprovar antes de publicar"
```

O agent loop detecta "quero aprovar" e monta input com `with_user_approval: true`.

### 3. Tag no input/recipe
```yaml
# recipes/minha.yaml
stages:
  - id: copy
    approval:
      mode: auto_reviewer
      escalate_to_user: true   # auto-reviewer em dúvida → humano
```

## O que isso muda nas 3 receitas existentes

### `campanha-marketing.yaml`
- `brief` já era auto_reviewer ✓
- `copy` tinha `mode: user` → passa a `auto_reviewer` com critérios de qualidade
- `ads` tinha `mode: user` → passa a `auto_reviewer`
- `video` tinha `human_reviewer` → passa a `auto_reviewer`

Usuário pode ativar humanos via `with_user_approval: true` no input.

### `yt-clip-publish.yaml`
- `clip` já era auto_reviewer com critérios de duração e fala ✓
- `publish` era `none` ✓

### `simple-carrossel.yaml`
- Tudo `none` (stages triviais) ✓

## Critérios padrão sugeridos

Quando portar/criar stages criativos, usar critérios como:

```yaml
# copy
approval:
  mode: auto_reviewer
  criteria:
    - "texto em português"
    - "tem ângulo claro e CTA"
    - "não usa claims médicos sem disclaimer"
    - "não ofende nem exclui"
    - "alinhado com brand do tenant (ver profile)"
  escalate_to_user: true

# ads (visual)
approval:
  mode: auto_reviewer
  criteria:
    - "imagem tem composição balanceada"
    - "texto overlay legível"
    - "respeita paleta da marca (ver brand.colors)"
  escalate_to_user: true

# video
approval:
  mode: auto_reviewer
  criteria:
    - "áudio sincronizado com imagem"
    - "abertura em 2s captura atenção"
    - "tem CTA final claro"
  escalate_to_user: true
```

## Regra `escalate_to_user`

Estende `EscalationPolicy` existente (`on_uncertain`, `always`, `never`)
com comportamento concreto:

- Auto-reviewer retorna `decision: "uncertain"` → Gateway manda
  pergunta ao usuário no canal original → aguarda resposta humana.
- Em vez de rejeitar imediatamente em dúvida, escala pra decisão
  humana apenas quando o LLM não tem certeza.

## Por que essa política

- **Velocidade**: sem humano no loop, pipeline completo roda em
  segundos-minutos, não horas-dias.
- **Consistência**: critérios declarativos são auditáveis e reproduzíveis.
- **Escala multi-tenant**: humano não vira gargalo quando vários
  clientes rodam em paralelo.
- **Opt-in explícito**: usuário aprende que "quero aprovar" é uma
  frase mágica que ele pode usar quando quiser controlar algo crítico.
