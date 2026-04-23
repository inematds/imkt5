# Plano: Recipe `roteiro-video` + integração skyreelsv3

**Data:** 2026-04-22
**Status:** Parked — aguardando aprovação do user pra executar
**Origem:** conversa de sessão 2026-04-22 sobre recipe nova de vídeo por roteiro

---

## Contexto

Usuário pediu recipe nova no imkt4: recebe roteiro → gera plano de vídeo →
imagens iniciais/finais por cena → prompt de movimentação → animação →
concat final. Default API local, kie.ai como 2ª alternativa.

Investigação revelou que:

1. **`/home/nmaldaner/projetos/VideosDGX/`** tem 4 modelos (LTX-2, Wan 2.1,
   Wan 2.2 5B/14B, MAGI-1) expostos via `web_interface_v4_2.py` em `:7862`.
   Suporta i2v mas apenas com **keyframe inicial** (sem start+end). Cenas
   geradas são visualmente independentes — personagem muda entre cenas.
2. **`/home/nmaldaner/projetos/skyreelsv3/`** é fork maduro do SkyReels V3
   da SkyworkAI, v3.13.7 em dev ativo, com webui própria (`webui/app.py`),
   formato de roteiro definido (JSON/Markdown), e projeto real em produção
   (`projetos/INETUSX/` — série infantil animada sobre pets, 6 episódios
   em desenvolvimento, bíblia + personagens + world-building).

O skyreelsv3 resolve nativamente **consistência visual entre cenas**
(R2V com 1-4 imagens de referência) + **extensão de vídeo** + **shot
switching cinematográfico** + **talking avatar** — o que seria o "motor"
natural da recipe.

## Decisão arquitetural

**Usar skyreelsv3 como worker macro** do imkt4, não reconstruir a
funcionalidade. O imkt4 vira orquestrador de alto nível; o skyreelsv3
mantém seu próprio ciclo de vida (consumível standalone ou via imkt4).

Aderente ao princípio #1 do CLAUDE.md ("worker = caixa preta com
contrato único") e #2 ("cada worker continua executável individualmente").

## Endpoints relevantes do skyreelsv3 (mapeados)

| Método | Path | Função |
|---|---|---|
| POST | `/nqueues/import` | cria fila a partir de JSON/Markdown |
| POST | `/nqueues/<id>/run` | executa sequencial |
| POST | `/nqueues/<id>/finalize` | concatena cenas em **1 mp4** |
| POST | `/nqueues/<id>/mix-audio` | pós-mix de áudio |
| POST | `/nqueues/<id>/resume-from-error` | **não existe — PR 3** |
| GET | `/nqueues/<id>` | detalhes da fila |
| GET | `/status` | estado global de geração |
| GET | `/stream` | SSE de logs |
| GET | `/health` | **não existe estruturado — PR 1** |

`{{prev}}` e `{{job:N}}` resolvidos server-side. Sem auth, sem CORS, sem
webhook/callback (bloqueador).

## Gaps bloqueadores pra virar worker confiável

1. Sem `/health` estruturado — imkt4 não sabe se está vivo ou pendurado
2. Sem callback webhook — só SSE (frágil em desconexão) ou polling de `/status`
3. `{{prev}}` quebra silenciosamente se job anterior falha — sem retry/resume
4. `result/` global sem namespace por projeto — INETUSX e outros clientes
   colidem em 3-6 meses
5. Secundário: input JSON da cena não é salvo junto do .mp4 (sem
   auditoria/reprodutibilidade)

---

## Fase 0 — Melhorias no skyreelsv3 (bloqueadoras) ~1-2 dias

### PR 1 — Health check (~30min)

```
GET /health
  → {status: "ready"|"busy"|"starting", queue_depth, gpu_free_gb,
     version, uptime_s}
```

### PR 2 — Webhook callback (~2h)

```
POST /nqueues/<id>/run?callback_url=https://...
  → quando queue terminar (ok OU erro), POST JSON pro callback_url
  → body: {queue_id, status, output_video?, failed_jobs?, duration_s}
  → retry 3x com backoff se callback 5xx
```

### PR 3 — Resume automático (~3h)

```
POST /nqueues/<id>/resume-from-error
  → pula jobs com status=error
  → próximo pending recebe {{prev}} do último status=done
  → se primeiro job falhou, erro claro (não pode auto-resolver)
```

### PR 4 — Namespacing de projeto (~4h)

```
campo opcional `project` no JSON da queue
result/<project>/<task_type>/<seed>_<ts>.mp4   (atual: result/<task_type>/...)
finalize grava em result/<project>/finalized/<queue_name>_<ts>.mp4
retrocompat: se project ausente, fallback pro comportamento atual
```

### PR 5 (opcional) — Input sidecar (~30min)

```
ao rodar cada job, salvar <seed>_<ts>.input.json com payload original
```

---

## Fase 1 — Worker `script-to-queue` no imkt4 ~1 dia

LLM (Claude subprocess, igual outros workers-cérebro do imkt4) que recebe:

- `script` (roteiro livre em texto)
- `characters[]` (opcional — lista com `{name, ref_image_url?}`)
- `style` (opcional — direção visual global)
- `target_duration`, `aspect_ratio`, `project`

...e devolve JSON no formato `nqueues/import` do skyreelsv3:

- Decide `task_type` por cena (R2V quando introduz personagem, extension
  p/ continuidade, shot_switching p/ cortes, talking_avatar p/ narração)
- Preenche `ref_imgs` apontando pras imagens geradas pelo inemaimg
- Insere `{{prev}}` automaticamente em cenas encadeadas
- Insere prefixos `[ZOOM_IN_CUT]` etc quando o roteiro indica corte
- Seeds determinísticas (hash do `job_id + scene_idx`)

Capability nova: `video.script_to_queue`. Porta `:8119`.

---

## Fase 2 — Worker `skyreels-adapter` no imkt4 ~1 dia

Proxy fino que traduz contrato `/execute` do imkt4 pra skyreelsv3:

1. Recebe payload `{queue_json, project, callback_hint}`
2. POSTa `/nqueues/import` → pega `nq_id`
3. POSTa `/nqueues/<id>/run?callback_url=<gateway>/queue-callback/<job_id>`
4. Devolve `{status: pending, external_id: nq_id}` imediatamente
5. Quando skyreelsv3 callback chega no gateway, adapter resolve o job e
   devolve `{status: success, outputs: {video_url}}`

Capability nova: `video.skyreels_queue`. Porta `:8120`.

**Endpoint novo no gateway imkt4:** `POST /queue-callback/<job_id>` — só
aceita do IP do skyreelsv3.

---

## Fase 3 — Recipe `roteiro-video.yaml` no imkt4 ~half-day

5 stages:

1. `char_refs` — fanout: gera imagens de referência dos personagens
   (inemaimg) — **só se input não passou ref_imgs**
2. `voiceover` — fanout: narração das cenas talking_avatar (inemavox) —
   só se tem cena talking
3. `script_to_queue` — roteiro + refs + narrações → JSON skyreelsv3
4. `skyreels_render` — dispara queue no skyreelsv3, espera callback,
   retorna mp4 finalizado
5. `audio_post` (opcional) — mix música/sfx final sobre o mp4 se
   `use_music`/`use_sfx`

Atualização no `config/workers.yaml`: registrar os 2 workers novos.

---

## Fase 4 — melhorias opcionais (pós-MVP)

- Cache de seeds (skip re-render se `<project>/<seed>.mp4` existe) —
  economia gigante em iteração de roteiro
- Queue pause/resume — usuário para no meio, ajusta cena 7, continua
- Real ETA baseado em runs anteriores (hoje é estimativa fixa)

---

## Sugestões independentes para o skyreelsv3 amadurecer

(Não são pré-requisito da integração imkt4, mas aumentam robustez do
produto standalone.)

- **CORS configurável** (hoje webui é rede interna — fica frágil se mudar)
- **Auth opcional via API key** (header `X-SkyReels-Key`) — pré-requisito
  pra expor na nuvem
- **Progresso granular por job no `/nqueues/<id>`** — hoje é só
  `status + estimated_minutes` total; ter `current_job_idx,
  current_job_progress_pct` desbloqueia UI bonita
- **Log estruturado JSON** além do texto — facilita ingest em observability
- **Audio mixing ANTES do render** (não post-render) — ganho de tempo e
  menos risco de corrupção
- **Tests automatizados** em `/nqueues/*` — o skyreelsv3 está em v3.13.7,
  13 features e 7 fixes, sem suíte visível

---

## Decisões em aberto

1. **Ordem:** fase 0 sequencial antes da 1-3 (1-2 dias a mais, integração
   sólida) OU fase 0 + 1-3 em paralelo com polling frágil temporariamente
   (mais rápido, gambiarra).
2. **Escopo de `project`/namespacing:** se INETUSX é único consumidor
   planejado pros próximos meses, PR 4 da fase 0 pode ser adiado.
3. **Reconciliação com workers video-* atuais do imkt4**
   (`video-quick`, `video-pro`, `video-art-director`, `ffmpeg-local`):
   continuam servindo o caminho "marketing curto" (campanha-marketing);
   não são substituídos pelo skyreels. Dois pipelines distintos coexistem.

## Arquivos de referência

- `/home/nmaldaner/projetos/skyreelsv3/webui/app.py` — fonte dos endpoints
  atuais (editar pra fase 0)
- `/home/nmaldaner/projetos/skyreelsv3/doc/QUEUE_FORMAT.md` — contrato do
  JSON de roteiro (formato de input da fase 1)
- `/home/nmaldaner/projetos/skyreelsv3/doc/exemplo_roteiro.json` —
  exemplo realista (5 cenas misturando R2V + extension + shot_switching
  + talking_avatar)
- `/home/nmaldaner/projetos/skyreelsv3/projetos/INETUSX/` — projeto real
  consumindo o skyreelsv3 hoje
- `/home/nmaldaner/projetos/imkt4/recipes/campanha-marketing.yaml` —
  referência do padrão de recipe
- `/home/nmaldaner/projetos/imkt4/config/workers.yaml` — onde registrar
  workers novos
- `/home/nmaldaner/projetos/imkt4/doc/telegram-watcher-plan.md` — mesmo
  padrão de "plano parkeado" deste

## Pick up

Se retomar: começar pela fase 0 PR 1 (health check no skyreelsv3) —
menor risco, desbloqueia testes de conectividade do adapter imkt4 antes
de qualquer outra coisa. 30min de trabalho.
