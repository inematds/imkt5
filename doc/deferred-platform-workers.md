# Workers de plataforma — diferidos

> Decisão: os 6 workers `platform-*` **NÃO serão portados agora**. Ficam
> documentados aqui pra retomada futura quando houver demanda real.

## Quais são

Workers do `timesmkt3/skills/platform-*-agent/` que adaptam conteúdo para
cada rede social. Cada um pega os mesmos assets (vídeo, imagens,
narrativa) e gera metadata formatado para a plataforma-alvo.

| Worker | Capability | O que faz (resumido) |
|---|---|---|
| `platform-instagram` | `platform.instagram` | Carrossel (10 slides), stories, reels, captions com hashtags IG, hook de abertura, CTA |
| `platform-youtube` | `platform.youtube` | Título SEO-otimizado, descrição longa, tags, capítulos, shorts 9:16 |
| `platform-tiktok` | `platform.tiktok` | Vídeo vertical, caption curta, hook de 2s obrigatório, trending hashtags |
| `platform-facebook` | `platform.facebook` | Feed 1:1, stories 9:16, reels, vídeo 16:9 com legenda embutida |
| `platform-threads` | `platform.threads` | Posts conversacionais ≤500 chars, sequência encadeada |
| `platform-linkedin` | `platform.linkedin` | Post profissional, carrossel PDF (slides), tom B2B, primeira linha como hook |

## Por que foram diferidos

1. **Escopo inicial do `imkt4` não precisa.** Gerar imagem, áudio,
   vídeo e campanha curta não exige formatação por plataforma ainda.
2. **Maioria das decisões é específica por rede e muda com frequência**
   (algoritmo do TikTok, limites do Threads, formato de carrossel IG).
   Congelar lógica agora gera retrabalho.
3. **Complexidade não é no worker, é no conteúdo.** Um worker
   `platform-*` é 80% prompt + 20% validação de specs. Tem valor só
   quando há estratégia de conteúdo por plataforma.

## Onde estão os SKILL.md originais

Referência para o porte futuro — os prompts + regras de conteúdo por
plataforma já existem:

```
/home/nmaldaner/projetos/timesmkt3/skills/
├── platform-instagram-agent/
├── platform-youtube-agent/
├── platform-tiktok-agent/
├── platform-facebook-agent/
├── platform-threads-agent/
└── platform-linkedin-agent/
```

Além disso, `timesmkt3/prj/<cliente>/knowledge/platform_guidelines.md`
guarda specs por plataforma (formatos, dimensões, limites de caracteres).

## Como retomar no futuro

Decisão pendente no retomar: **6 workers distintos** ou **1 worker
`platform-formatter` parametrizado** — ver `doc/backlog.md` §7 e
conversa no chat. Minha recomendação continua sendo B (1 worker com
SKILL-<plataforma>.md por dentro).

Checklist pra quando voltar:

- [ ] Decidir: 6 workers ou 1 parametrizado (se B, um único código)
- [ ] Copiar SKILL.md de `timesmkt3/skills/platform-*-agent/`
- [ ] Adaptar I/O: remover `${project_dir}/outputs/`, usar `get_storage()`
- [ ] Estruturar payload:
      ```python
      {
        "video_url": "...",            # do stage video da receita
        "narrative": {...},            # do stage copy
        "brand_tone": "...",           # do tenant profile
        "platform_guidelines": "...",  # do tenant knowledge
      }
      ```
- [ ] Decidir: LLM puro (HTTP OpenRouter) ou Claude CLI subprocess.
      Para platforms, **LLM puro é suficiente** — só gera texto e metadata.
- [ ] Registrar em `config/workers.yaml` (local: true, priority 100)
- [ ] Adicionar na receita `campanha-marketing.yaml` no stage `platforms`
- [ ] Testar com uma campanha real

## Estimativa de esforço

- **Opção A (6 workers separados)**: ~1 dia cada = 6 dias total
- **Opção B (1 worker parametrizado)**: ~2-3 dias total (estrutura + 6 SKILL.md)

## O que ISSO desbloqueia quando for feito

Receita `campanha-marketing` passa a rodar **end-to-end**. Hoje ela
tranca no stage `platforms` por falta dos workers.

## O que pode rodar sem plataformas hoje

Mesmo sem platform-*, ainda dá pra fazer:

- Geração individual de imagem / áudio / vídeo
- Pesquisa + brief + copy + ads + vídeo (stage `platforms` fica pending, depois manual)
- Receita `carrossel-simples`
- Receita `yt-clip-publish` (não passa por platform-*, usa `yt-publish` direto)
