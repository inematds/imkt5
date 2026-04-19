"""Runs Browser — histórico por receita.

Layout 3 colunas:
  1. Receitas (com contador de runs)
  2. Runs da receita selecionada (mais recente primeiro)
  3. Detalhe da run (stages + ações)

Ações disponíveis:
  - ▶ Rodar de novo (mesma receita + input)
  - ▶ Re-rodar a partir de um stage (copia anteriores da run original)
  - 📥 Baixar bundle.zip
"""
from imkt4.gateway._media_modal import MEDIA_MODAL_HTML as _MEDIA_MODAL_HTML
from imkt4.gateway._modal_close import UNIVERSAL_MODAL_HTML as _UNIVERSAL_MODAL_HTML



RUNS_UI_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>imkt4 · runs</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; background: #0d1117; color: #e6edf3;
         font-family: system-ui, -apple-system, sans-serif; }

  .topbar { background: #161b22; border-bottom: 1px solid #30363d;
            padding: 12px 20px; display: flex; align-items: center; gap: 20px; }
  .topbar h1 { margin: 0; font-size: 18px; }
  .topbar .nav a { color: #7d8590; text-decoration: none; margin-right: 14px;
                   font-size: 13px; }
  .topbar .nav a:hover { color: #e6edf3; }
  .topbar .nav a.active { color: #1f6feb; font-weight: 600; }
  .auth { margin-left: auto; font-size: 12px; color: #7d8590; }
  .auth button { padding: 4px 10px; font-size: 11px; background: transparent;
                 border: 1px solid #30363d; color: #e6edf3; border-radius: 6px;
                 cursor: pointer; }

  /* 3 colunas */
  .body { display: grid; grid-template-columns: 240px 340px 1fr;
          height: calc(100vh - 50px); }

  .col { background: #161b22; border-right: 1px solid #30363d; overflow-y: auto; }
  .col:last-child { background: #0d1117; border-right: none; }

  .col-header { padding: 14px 16px; border-bottom: 1px solid #30363d;
                display: flex; justify-content: space-between; align-items: center;
                position: sticky; top: 0; background: #161b22; z-index: 5; }
  .col-header h2 { margin: 0; font-size: 12px; color: #7d8590;
                   text-transform: uppercase; letter-spacing: 0.5px; }

  /* Coluna 1: receitas */
  .recipe-row { padding: 12px 16px; cursor: pointer; border-left: 3px solid transparent;
                border-bottom: 1px solid #21262d; }
  .recipe-row:hover { background: #21262d; }
  .recipe-row.active { background: #21262d; border-left-color: #1f6feb; }
  .recipe-row .name { font-weight: 600; font-size: 13px; }
  .recipe-row .count { color: #7d8590; font-size: 11px; margin-top: 2px; }
  .recipe-row .count b { color: #e6edf3; }

  /* Coluna 2: runs */
  .run-row { padding: 12px 14px; cursor: pointer; border-left: 3px solid transparent;
             border-bottom: 1px solid #21262d; }
  .run-row:hover { background: #21262d; }
  .run-row.active { background: #21262d; border-left-color: #1f6feb; }
  .run-row .row-top { display: flex; justify-content: space-between; align-items: center;
                      gap: 8px; }
  .run-row .when { font-size: 12px; color: #e6edf3; font-weight: 500; }
  .run-row .meta { color: #7d8590; font-size: 10px; margin-top: 4px;
                   font-family: monospace; }
  .run-row .summary { font-size: 10px; margin-top: 6px; display: flex;
                      flex-wrap: wrap; gap: 4px; }

  /* Coluna 3: detalhe */
  .detail { padding: 20px 24px; }
  .detail h2 { margin: 0 0 4px 0; font-size: 20px; }
  .detail .run-meta { color: #7d8590; font-size: 13px; margin-bottom: 18px; }
  .detail .toolbar { display: flex; gap: 8px; margin-bottom: 20px; }
  .empty { padding: 60px 30px; text-align: center; color: #7d8590; font-size: 13px; }

  .pill { display: inline-block; padding: 2px 7px; border-radius: 10px;
          font-size: 9px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
  .pill.success { background: #238636; color: white; }
  .pill.running { background: #1f6feb; color: white; }
  .pill.failed  { background: #da3633; color: white; }
  .pill.skipped { background: #30363d; color: #7d8590; }
  .pill.awaiting_approval { background: #9e6a03; color: white; }
  .pill.pending { background: #30363d; color: #7d8590; }

  button { background: #1f6feb; color: white; border: none; padding: 7px 14px;
           border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
  button:hover { background: #388bfd; }
  button.ghost { background: transparent; border: 1px solid #30363d; color: #e6edf3; }
  button.ghost:hover { background: #21262d; }
  button.small { padding: 4px 10px; font-size: 11px; }

  .stage-card { background: #161b22; border: 1px solid #30363d;
                padding: 14px 16px; border-radius: 8px; margin-bottom: 10px; }
  .stage-card .head { display: flex; justify-content: space-between; align-items: center; }
  .stage-card .sid { font-size: 14px; font-weight: 600; }
  .stage-card .sid .cap { color: #7d8590; font-weight: normal; font-family: monospace;
                          font-size: 11px; margin-left: 8px; }
  .stage-card .desc { color: #8b949e; font-size: 12px; font-style: italic;
                      margin-top: 4px; }
  .stage-card .err { color: #f85149; font-size: 12px; font-family: monospace;
                     margin-top: 8px; background: #3b1519; padding: 8px;
                     border-radius: 4px; }
  .stage-card pre { background: #0d1117; color: #e6edf3; padding: 10px;
                    border-radius: 4px; font-size: 11px; max-height: 300px;
                    overflow: auto; margin: 8px 0 0 0; white-space: pre-wrap;
                    word-break: break-word; }
  .stage-card details summary { cursor: pointer; color: #7d8590; font-size: 12px;
                                margin-top: 6px; user-select: none; }
  .stage-card details summary:hover { color: #e6edf3; }
  .art-link { color: #1f6feb; text-decoration: none; font-size: 12px;
              word-break: break-all; }
  .art-link:hover { text-decoration: underline; }
  .art-img { max-width: 180px; max-height: 180px; border-radius: 4px;
             border: 1px solid #30363d; margin-right: 6px; margin-top: 6px; }

  .refresh-badge { font-size: 10px; color: #3fb950; margin-left: 8px; }

  .input-card {
    background: linear-gradient(135deg, rgba(31,111,235,0.08), rgba(31,111,235,0.02));
    border: 1px solid rgba(31,111,235,0.3);
    border-left: 3px solid #1f6feb;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 14px;
  }
  .input-card summary {
    cursor: pointer; list-style: none; outline: none;
    display: flex; align-items: center; gap: 10px;
  }
  .input-card summary::-webkit-details-marker { display: none; }
  .input-card summary .caret {
    font-size: 10px; color: #7d8590; transition: transform 0.15s;
  }
  .input-card[open] summary .caret { transform: rotate(90deg); }
  .input-card-label {
    font-size: 10px; color: #1f6feb; font-weight: 700;
    letter-spacing: 1px;
  }
  .input-card-preview {
    margin-left: 10px; font-size: 12px; color: #8b949e;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    flex: 1; max-width: calc(100% - 180px);
  }
  .input-card-text {
    font-size: 14px; color: #e6edf3; line-height: 1.5;
    white-space: pre-wrap; word-wrap: break-word;
    margin-top: 10px; max-height: 400px; overflow-y: auto;
  }
  .input-card-rest {
    margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px;
    font-size: 11px; color: #7d8590;
  }
  .input-card-rest .input-kv {
    background: #21262d; padding: 2px 8px; border-radius: 4px;
    font-family: ui-monospace, monospace;
  }
  .input-card-rest .input-kv b { color: #e6edf3; font-weight: 600; }
</style>
</head>
<body>

<div class="topbar">
  <h1>imkt4</h1>
  <nav style="display:flex;gap:4px;font-size:13px;">
    <a href="/ui"         style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Workspace</a>
    <a href="/recipes-ui" style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Receitas</a>
    <a href="/runs-ui"    style="color:#1f6feb;text-decoration:none;padding:6px 12px;border-radius:6px;background:#21262d;font-weight:600;">Execuções</a>
    <a href="/workers-ui" style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Workers</a>
    <a href="/chat-ui" style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Chat</a>
    <a href="/admin"      style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Admin</a>
  </nav>
  <div class="auth">
    <span id="auth-status">sem token</span>
    <button onclick="setToken()">token</button>
  </div>
</div>

<div class="body">
  <!-- Coluna 1: Receitas -->
  <aside class="col">
    <div class="col-header">
      <h2>Receitas</h2>
      <button class="small ghost" onclick="loadRecipes(true)">↻</button>
    </div>
    <div id="recipes-list"></div>
  </aside>

  <!-- Coluna 2: Runs da receita selecionada -->
  <aside class="col">
    <div class="col-header">
      <h2 id="runs-header">Histórico</h2>
      <div style="display:flex;gap:6px;align-items:center;">
        <span class="refresh-badge" id="refresh-badge"></span>
        <button class="small" onclick="openNewRunDialog()" id="new-run-btn" style="display:none;">+ nova</button>
      </div>
    </div>
    <div id="runs-list">
      <div class="empty">Selecione uma receita à esquerda</div>
    </div>
  </aside>

  <!-- Modal: nova execução -->
  <div id="new-run-modal" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0;
       background:rgba(0,0,0,0.6); z-index:100; align-items:center; justify-content:center;">
    <div style="background:#161b22; border:1px solid #30363d; border-radius:10px; padding:24px;
         max-width:640px; width:92%; max-height:92vh; overflow-y:auto;">
      <h3 style="margin:0 0 8px 0; font-size:16px;">Nova execução</h3>
      <div style="color:#7d8590; font-size:13px; margin-bottom:14px;">
        Receita: <b id="new-run-recipe-name"></b>
      </div>
      <label style="display:block;color:#7d8590;font-size:12px;margin-bottom:6px;">
        Input
        <a href="#" id="new-run-mode-toggle" style="margin-left:10px;font-size:11px;color:#1f6feb;text-decoration:none;">⚙ modo JSON</a>
      </label>
      <textarea id="new-run-input" rows="4"
        placeholder="ex.: Curso IA pra empreendedores, 30 dias resultados"
        style="width:100%; background:#0d1117; color:#e6edf3; border:1px solid #30363d;
               padding:10px; border-radius:6px; font-size:13px; font-family:ui-monospace, monospace;"></textarea>

      <!-- Opções avançadas específicas por receita -->
      <div id="advanced-opts" style="margin-top:14px;"></div>

      <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:14px;">
        <button class="ghost" onclick="closeNewRunDialog()">Cancelar</button>
        <button onclick="submitNewRun()">▶ Rodar</button>
      </div>
    </div>
  </div>

  <!-- Coluna 3: Detalhe -->
  <section class="col">
    <div class="detail" id="detail">
      <div class="empty">Selecione uma run pra ver detalhes</div>
    </div>
  </section>
</div>

<script>
// aceita user OU admin token
function getToken() {
  return localStorage.getItem('imkt4_user_token')
      || localStorage.getItem('imkt4_admin_token')
      || '';
}
function setToken() {
  const t = prompt('Token admin (Bearer):', getToken());
  if (t !== null) { localStorage.setItem('imkt4_admin_token', t.trim()); location.reload(); }
}
function updateAuthStatus() {
  const t = getToken();
  const el = document.getElementById('auth-status');
  el.textContent = t ? 'autenticado (' + t.slice(0,6) + '…)' : 'sem token (ok pra leitura)';
  el.style.color = t ? '#3fb950' : '#7d8590';
}
async function api(url, opts = {}) {
  const token = getToken();
  const h = { ...(opts.headers || {}) };
  if (token) h['Authorization'] = 'Bearer ' + token;
  return fetch(url, { ...opts, headers: h });
}

let selectedRecipe = null;
let selectedRunId = null;
let allRunsCache = [];  // cache das últimas 200 runs pra contar por receita

// Descrição curta do que cada worker/capability faz (mostrada no detalhe da run)
const CAP_DESC = {
  "research.market":           "pesquisa tendências e insights de mercado",
  "brief.strategic":           "cria o briefing estratégico da campanha",
  "copy.platform":             "redige textos por plataforma (IG, YT, Threads…)",
  "design.ad_layout":          "planeja variantes visuais (prompts p/ imagens)",
  "image.generation":          "gera imagens via Stable Diffusion (inemaimg)",
  "audio.tts":                 "sintetiza narração (text-to-speech)",
  "audio.dubbing":             "clona voz / dublagem com referência",
  "audio.transcribe":          "transcreve áudio → texto (SRT)",
  "video.cinematic":           "planeja cenas cinematográficas (scene_plan)",
  "video.render":              "renderiza vídeo final (ffmpeg: imagens + áudio)",
  "video.plan_from_outline":   "transforma outline educativo em plano de vídeo",
  "video.source_ingest":       "ingere vídeos fonte do YouTube",
  "video.clip_extraction":     "corta clips curtos de vídeos longos",
  "video.publish":             "publica vídeos em plataformas (YT/Shorts/TikTok)",
  "design.carousel":           "monta carrossel simples (PIL)",
  "design.carousel_rich":      "monta carrossel rico (Playwright + templates)",
  "design.carousel_outline":   "gera estrutura de slides a partir de tópico",
  "education.outline":         "estrutura aula em hook → conteúdo → CTA",
  "review.auto":               "revisa artefatos automaticamente (LLM)",
  "photography.direct":        "diretor de fotografia — refina prompts visuais",
  "platform.instagram":        "publica no Instagram",
  "platform.youtube":          "publica no YouTube",
  "platform.tiktok":           "publica no TikTok",
  "platform.facebook":         "publica no Facebook",
  "platform.threads":          "publica no Threads",
  "platform.linkedin":         "publica no LinkedIn",
};

// ── coluna 1: receitas ────────────────────────────────────────
async function loadRecipes(flash) {
  // lista receitas definidas + contadores das runs recentes
  const [recipesResp, runsResp] = await Promise.all([
    fetch('/recipes'), fetch('/runs?limit=200'),
  ]);
  const recipes = await recipesResp.json();
  allRunsCache = await runsResp.json();

  const counts = {};
  allRunsCache.forEach(r => { counts[r.recipe] = (counts[r.recipe] || 0) + 1; });

  const list = document.getElementById('recipes-list');
  list.innerHTML = '';
  recipes.forEach(r => {
    const c = counts[r.name] || 0;
    const row = document.createElement('div');
    row.className = 'recipe-row';
    row.dataset.name = r.name;
    if (r.name === selectedRecipe) row.classList.add('active');
    row.onclick = () => selectRecipe(r.name);
    row.innerHTML = `
      <div class="name">${r.name}</div>
      <div class="count"><b>${c}</b> runs · ${r.stages.length} stages</div>
    `;
    list.appendChild(row);
  });

  if (flash) {
    const b = document.getElementById('refresh-badge');
    b.textContent = '↻'; setTimeout(() => { b.textContent = ''; }, 1200);
  }
}

// ── coluna 2: runs da receita ─────────────────────────────────
async function selectRecipe(name) {
  selectedRecipe = name;
  document.querySelectorAll('.recipe-row').forEach(r => {
    r.classList.toggle('active', r.dataset.name === name);
  });
  document.getElementById('new-run-btn').style.display = 'inline-block';
  await loadRuns(name);
}

// ── Nova execução ─────────────────────────────────────────────
let newRunMode = 'text';  // text | json

// Schemas de opções avançadas por receita. Cada campo é renderizado
// como input apropriado. O valor final é serializado em input JSON.
const RECIPE_FIELDS = {
  'carrossel-simples': [
    {key: 'title', label: 'Título (capa)', type: 'text',
     placeholder: 'ex.: Trilha IA Express'},
    {key: 'captions', label: 'Captions (1 por linha, slides intermediários)',
     type: 'lines', rows: 4, placeholder: 'Aprenda fazendo\n1 case por dia\nSem teoria chata'},
    {key: 'cta', label: 'CTA (último slide)', type: 'text',
     placeholder: 'Inscreva-se em INEMA.CLUB'},
    {key: 'model', label: 'Modelo SD', type: 'pills',
     options: [
       ['flux2-klein', 'flux2-klein · 4 steps'],
       ['sdxl', 'SDXL · 30 steps'],
       ['sd15', 'SD 1.5 · 25 steps'],
     ],
     default: 'flux2-klein'},
    {key: 'formats', label: 'Formatos (múltipla escolha)', type: 'pills-multi',
     options: [['1:1', '1:1 · feed'], ['9:16', '9:16 · stories/reels'], ['16:9', '16:9 · youtube']],
     default: ['1:1', '9:16', '16:9']},
    {key: 'detect_text_in_bg', label: 'Detectar texto na imagem (fallback)',
     type: 'boolean', hint: 'Se o SD gerar texto indevido, suprime overlay. Default off.'},
  ],

  'carrossel-rico': [
    {key: 'slide_count', label: 'Número de slides', type: 'number',
     min: 3, max: 12, default: 7, placeholder: '7'},
    {key: 'image_source', label: 'Fonte das imagens', type: 'pills',
     options: [
       ['generate', 'Gerar novas · LLM+SD'],
       ['provided', 'Vou passar prompts'],
       ['none', 'Sem imagens · só tipografia'],
     ],
     default: 'generate'},
    {key: 'bg_prompts', label: 'Prompts de imagem (1 por linha)',
     type: 'lines', rows: 4,
     placeholder: 'minimalist office, warm light\nabstract data viz, dark bg\n...',
     hint: 'Usado apenas quando "Fonte das imagens" = "Vou passar prompts"',
     dependsOn: {key: 'image_source', value: 'provided'}},
    {key: 'template', label: 'Template', type: 'pills',
     options: [
       ['', 'Auto · art-director'],
       ['magazine', 'Magazine'],
       ['editorial', 'Editorial'],
       ['corporate_clean', 'Corporate Clean'],
       ['data_viz', 'Data Viz'],
       ['wellness_soft', 'Wellness Soft'],
       ['bold_pop', 'Bold Pop'],
       ['retro_futurism', 'Retro Futurism'],
       ['organic_earth', 'Organic Earth'],
       ['neo_minimal_luxury', 'Neo Minimal Luxury'],
     ],
     default: ''},
    {key: 'style', label: 'Style (palette)', type: 'pills',
     options: [
       ['', 'Auto · art-director'],
       ['neon_futurista', 'Neon Futurista'],
       ['editorial_documentary', 'Editorial'],
       ['corporate_clean', 'Corporate Clean'],
       ['data_viz', 'Data Viz'],
       ['wellness_soft', 'Wellness Soft'],
       ['bold_pop', 'Bold Pop'],
       ['retro_futurism', 'Retro Futurism'],
       ['organic_earth', 'Organic Earth'],
       ['neo_minimal_luxury', 'Neo Minimal Luxury'],
       ['dark_cinematic', 'Dark Cinematic'],
       ['warm_lifestyle', 'Warm Lifestyle'],
       ['nature_organic', 'Nature Organic'],
     ],
     default: ''},
    {key: 'model', label: 'Modelo SD', type: 'pills',
     options: [
       ['flux2-klein', 'flux2-klein · 4 steps'],
       ['sdxl', 'SDXL · 30 steps'],
       ['sd15', 'SD 1.5 · 25 steps'],
     ],
     default: 'flux2-klein'},
    {key: 'formats', label: 'Formatos (múltipla escolha)', type: 'pills-multi',
     options: [['1:1', '1:1'], ['9:16', '9:16'], ['16:9', '16:9']],
     default: ['1:1', '9:16', '16:9']},
    {key: 'detect_text_in_bg', label: 'Detectar texto na imagem (fallback)',
     type: 'boolean'},
  ],

  'campanha-marketing': [
    {key: 'video_mode', label: 'Modo de vídeo', type: 'pills',
     options: [
       ['quick', 'Quick · rápido, cortes secos'],
       ['pro', 'Pro · crossfade + color grading'],
       ['skip', 'Skip · sem vídeo (só imagens)'],
     ],
     default: 'quick',
     hint: 'Quick: 4-6 cenas, motion básico. Pro: xfade+color grading por seção (cool/warm).'},
    {key: 'image_count', label: 'Quantidade de imagens', type: 'number',
     min: 1, max: 8, default: 3, placeholder: '3'},
    {key: 'platform', label: 'Plataforma alvo (safe zones)', type: 'pills',
     options: [
       ['', 'Universal (25-60%)'],
       ['tiktok', 'TikTok'],
       ['instagram_reels', 'Instagram Reels'],
       ['shorts', 'YouTube Shorts'],
       ['stories', 'Instagram Stories'],
       ['feed', 'Instagram Feed'],
     ],
     default: ''},
    {key: 'use_karaoke', label: 'Karaoke (legendas sync com fala)',
     type: 'boolean',
     hint: 'Default OFF. Marque pra ligar. faster-whisper transcreve o TTS e burnuiza palavra-por-palavra sobre o vídeo (+~30s render).'},
    {key: 'use_sfx', label: 'SFX (stab/swoosh por style+hook) — default ON',
     type: 'boolean_default_on',
     hint: 'Desmarque pra desativar. Styles tranquilos (premium/wellness) já desligam automaticamente.'},
    {key: 'hold_final', label: 'Hold final 3s silencioso — default ON',
     type: 'boolean_default_on',
     hint: 'Desmarque pra desativar. Skip automático quando video < 8s.'},
    {key: 'loop_visual', label: 'Loop visual (rewatch rate)', type: 'boolean',
     hint: 'Última cena usa imagem da primeira (rima visual pro TikTok/Reels).'},
    {key: 'kinetic_presets', label: 'Kinetic presets por style', type: 'boolean',
     hint: 'Animações por style: wipe/zoom_impact/type_on/glow_pulse só em hook+emphasis.'},
    {key: 'freeze_frames', label: 'Freeze frame em revelações', type: 'boolean',
     hint: 'Auto em styles data_viz/editorial/corporate quando cena tem stat. Whisper + emphasis_word pra timing exato.'},
    {key: 'use_parallax', label: 'Parallax nível 1 (fake)', type: 'boolean',
     hint: 'Blur+unsharp em 3 camadas. Auto ON em styles cinematográficos.'},
    {key: 'depth_ai', label: 'Parallax nível 2 (Depth-Anything V2)', type: 'boolean',
     hint: 'Opt-in. Tenta depth map real; cai pro nível 1 se modelo não instalado.'},
    {key: 'narration_speed', label: 'Narração speed (atempo)', type: 'number',
     min: 1.0, max: 1.25, placeholder: 'auto por style (1.10-1.20)',
     hint: 'Clamp 1.0-1.25. Override manual. Default por style no worker.'},
    {key: 'approval_mode', label: 'Aprovação global', type: 'pills',
     options: [
       ['', 'Nenhuma (none)'],
       ['auto', 'Auto (LLM reviewer)'],
       ['human', 'Humana (canal de origem, timeout 30min)'],
       ['agent', 'Agent (LLM reviewer específico)'],
     ],
     default: ''},
    {key: 'with_research', label: 'Pesquisa prévia (Tavily)', type: 'boolean',
     hint: 'Consulta web antes do brief. Custa chamadas API.'},
  ],

  'campanha-marketing-ab': [
    {key: 'video_mode', label: 'Modo de vídeo', type: 'pills',
     options: [['quick','Quick'], ['pro','Pro']],
     default: 'quick'},
    {key: 'image_count', label: 'Imagens (base, antes de variantes)', type: 'number',
     min: 1, max: 6, default: 3, placeholder: '3'},
    {key: 'ab_ai_suggest', label: 'LLM sugere variantes (hooks+CTAs)', type: 'boolean',
     hint: 'Alternativa ao hook_variants manual. Worker video-ab-suggest decide.'},
    {key: 'hook_variants', label: 'Hook variants (1 por linha, override da AI)',
     type: 'lines', rows: 3,
     placeholder: 'stat_shot\nquestion_abrupt\npattern_interrupt'},
    {key: 'cta_variants', label: 'CTA variants (1 por linha)', type: 'lines', rows: 2,
     placeholder: 'Comece grátis\nAcesse INEMA.CLUB'},
    {key: 'platform', label: 'Plataforma alvo', type: 'pills',
     options: [['','Universal'], ['tiktok','TikTok'], ['instagram_reels','Reels'], ['shorts','Shorts']],
     default: ''},
    {key: 'use_karaoke', label: 'Karaoke', type: 'boolean'},
  ],

  'curso-educativo': [
    {key: 'slide_count', label: 'Número de slides', type: 'number',
     min: 5, max: 15, default: 10, placeholder: '10'},
    {key: 'depth', label: 'Profundidade', type: 'pills',
     options: [['iniciante','Iniciante'], ['intermediario','Intermediário'], ['avancado','Avançado']],
     default: 'iniciante'},
    {key: 'style', label: 'Estilo de voz', type: 'pills',
     options: [['didatico','Didático'], ['direto','Direto'], ['narrativo','Narrativo']],
     default: 'didatico'},
    {key: 'skip_audio', label: 'Pular narração (só carousel)', type: 'boolean'},
    {key: 'skip_video', label: 'Pular vídeo (só carousel+audio)', type: 'boolean'},
  ],
};

function renderAdvancedOpts(recipeName) {
  const container = document.getElementById('advanced-opts');
  container.innerHTML = '';
  const fields = RECIPE_FIELDS[recipeName];
  if (!fields) {
    container.innerHTML = '';
    return;
  }

  const det = document.createElement('details');
  det.style.cssText = 'margin-top:6px; background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px 12px;';
  det.open = true;
  const sum = document.createElement('summary');
  sum.style.cssText = 'cursor:pointer; color:#1f6feb; font-size:12px; font-weight:600; user-select:none;';
  sum.textContent = '⚙ Opções específicas da receita';
  det.appendChild(sum);

  const body = document.createElement('div');
  body.style.cssText = 'margin-top:12px; display:flex; flex-direction:column; gap:10px;';

  fields.forEach(f => {
    const wrap = document.createElement('div');
    wrap.dataset.fwrap = f.key;
    if (f.dependsOn) {
      wrap.dataset.dependsKey = f.dependsOn.key;
      wrap.dataset.dependsValue = f.dependsOn.value;
    }
    const lbl = document.createElement('label');
    lbl.style.cssText = 'display:block; color:#7d8590; font-size:11px; margin-bottom:4px; font-weight:500;';
    lbl.textContent = f.label;
    wrap.appendChild(lbl);

    const commonStyle = 'width:100%; background:#161b22; color:#e6edf3; border:1px solid #30363d; padding:7px 9px; border-radius:5px; font-size:12px; font-family:ui-monospace, monospace;';

    if (f.type === 'text') {
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.dataset.fkey = f.key;
      inp.placeholder = f.placeholder || '';
      inp.style.cssText = commonStyle;
      wrap.appendChild(inp);
    } else if (f.type === 'number') {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.dataset.fkey = f.key;
      inp.placeholder = f.placeholder || '';
      if (f.min !== undefined) inp.min = f.min;
      if (f.max !== undefined) inp.max = f.max;
      if (f.default !== undefined) inp.value = f.default;
      inp.style.cssText = commonStyle;
      wrap.appendChild(inp);
    } else if (f.type === 'lines') {
      const ta = document.createElement('textarea');
      ta.dataset.fkey = f.key;
      ta.rows = f.rows || 3;
      ta.placeholder = f.placeholder || '';
      ta.style.cssText = commonStyle;
      wrap.appendChild(ta);
    } else if (f.type === 'select') {
      const sel = document.createElement('select');
      sel.dataset.fkey = f.key;
      sel.style.cssText = commonStyle;
      (f.options || []).forEach(([val, label]) => {
        const o = document.createElement('option');
        o.value = val;
        o.textContent = label;
        sel.appendChild(o);
      });
      if (f.default !== undefined) sel.value = f.default;
      wrap.appendChild(sel);
    } else if (f.type === 'pills') {
      // Radio-style: clicar em uma desmarca a outra. Default destacada.
      const box = document.createElement('div');
      box.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';
      box.dataset.fkey = f.key;
      box.dataset.ftype = 'pills';
      const defaultVal = f.default !== undefined ? f.default : (f.options?.[0]?.[0] ?? '');
      box.dataset.value = defaultVal;
      (f.options || []).forEach(([val, label]) => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.dataset.val = val;
        pill.textContent = label;
        const isActive = val === defaultVal;
        pill.style.cssText = `
          padding: 5px 11px; border-radius: 14px; font-size: 11px;
          font-family: system-ui, sans-serif; font-weight: 500;
          cursor: pointer; user-select: none; transition: all 0.12s;
          background: ${isActive ? '#1f6feb' : '#0d1117'};
          color: ${isActive ? 'white' : '#e6edf3'};
          border: 1px solid ${isActive ? '#1f6feb' : '#30363d'};
        `;
        pill.onclick = (ev) => {
          ev.preventDefault();
          box.dataset.value = val;
          [...box.children].forEach(c => {
            const on = c.dataset.val === val;
            c.style.background = on ? '#1f6feb' : '#0d1117';
            c.style.color = on ? 'white' : '#e6edf3';
            c.style.borderColor = on ? '#1f6feb' : '#30363d';
          });
          // dispara event pra refreshDepends
          box.dispatchEvent(new Event('change', {bubbles: true}));
        };
        box.appendChild(pill);
      });
      wrap.appendChild(box);
    } else if (f.type === 'pills-multi') {
      // Checkbox-style: pode selecionar várias.
      const box = document.createElement('div');
      box.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';
      box.dataset.fkey = f.key;
      box.dataset.ftype = 'pills-multi';
      const selected = new Set(f.default || []);
      (f.options || []).forEach(([val, label]) => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.dataset.val = val;
        pill.textContent = label;
        const isActive = selected.has(val);
        const style = (on) => `
          padding: 5px 11px; border-radius: 14px; font-size: 11px;
          font-family: system-ui, sans-serif; font-weight: 500;
          cursor: pointer; user-select: none; transition: all 0.12s;
          background: ${on ? '#238636' : '#0d1117'};
          color: ${on ? 'white' : '#e6edf3'};
          border: 1px solid ${on ? '#238636' : '#30363d'};
        `;
        pill.style.cssText = style(isActive);
        pill.dataset.on = isActive ? '1' : '0';
        pill.onclick = (ev) => {
          ev.preventDefault();
          const on = pill.dataset.on === '1';
          pill.dataset.on = on ? '0' : '1';
          pill.style.cssText = style(!on);
        };
        box.appendChild(pill);
      });
      wrap.appendChild(box);
    } else if (f.type === 'checkboxes') {
      const box = document.createElement('div');
      box.style.cssText = 'display:flex; gap:12px; flex-wrap:wrap;';
      box.dataset.fkey = f.key;
      box.dataset.ftype = 'checkboxes';
      (f.options || []).forEach(([val, label]) => {
        const l = document.createElement('label');
        l.style.cssText = 'color:#e6edf3; font-size:12px; display:inline-flex; align-items:center; gap:4px; cursor:pointer;';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = val;
        if (f.default && f.default.includes(val)) cb.checked = true;
        l.appendChild(cb);
        l.appendChild(document.createTextNode(' ' + label));
        box.appendChild(l);
      });
      wrap.appendChild(box);
    } else if (f.type === 'boolean') {
      const l = document.createElement('label');
      l.style.cssText = 'color:#e6edf3; font-size:12px; display:inline-flex; align-items:center; gap:6px; cursor:pointer;';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.fkey = f.key;
      cb.dataset.ftype = 'boolean';
      if (f.default) cb.checked = true;
      l.appendChild(cb);
      l.appendChild(document.createTextNode(' ativar'));
      wrap.appendChild(l);
    } else if (f.type === 'boolean_default_on') {
      // Backend tem default=true pro campo. UI vem JÁ MARCADO; desmarcar
      // envia explicitamente false pra desativar.
      const l = document.createElement('label');
      l.style.cssText = 'color:#e6edf3; font-size:12px; display:inline-flex; align-items:center; gap:6px; cursor:pointer;';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.fkey = f.key;
      cb.dataset.ftype = 'boolean_default_on';
      cb.checked = true;  // default visual ligado
      l.appendChild(cb);
      l.appendChild(document.createTextNode(' ligado'));
      wrap.appendChild(l);
    }

    if (f.hint) {
      const h = document.createElement('div');
      h.style.cssText = 'color:#7d8590; font-size:10px; margin-top:3px;';
      h.textContent = f.hint;
      wrap.appendChild(h);
    }
    body.appendChild(wrap);
  });

  det.appendChild(body);
  container.appendChild(det);

  // Aplica dependsOn: esconde/mostra campos conforme o valor do campo-pai
  function refreshDepends() {
    container.querySelectorAll('[data-depends-key]').forEach(wrap => {
      const dk = wrap.dataset.dependsKey;
      const dv = wrap.dataset.dependsValue;
      const parent = container.querySelector(`[data-fkey="${dk}"]`);
      if (!parent) return;
      // Se parent é pill container, lê dataset.value; senão lê .value
      const parentVal = parent.dataset.ftype === 'pills'
        ? parent.dataset.value
        : (parent.value || '');
      wrap.style.display = (parentVal === dv) ? '' : 'none';
    });
  }
  container.querySelectorAll('[data-fkey]').forEach(el => {
    el.addEventListener('change', refreshDepends);
    el.addEventListener('input', refreshDepends);
  });
  refreshDepends();
}

function collectAdvancedOpts(recipeName) {
  const fields = RECIPE_FIELDS[recipeName];
  if (!fields) return {};
  const out = {};
  const container = document.getElementById('advanced-opts');
  fields.forEach(f => {
    // Campo invisível por dependsOn é ignorado
    const wrap = container.querySelector(`[data-fwrap="${f.key}"]`);
    if (wrap && wrap.style.display === 'none') return;

    if (f.type === 'checkboxes') {
      const box = container.querySelector(`[data-fkey="${f.key}"][data-ftype="checkboxes"]`);
      if (!box) return;
      const vals = [...box.querySelectorAll('input[type=checkbox]')]
        .filter(c => c.checked).map(c => c.value);
      const def = f.default || [];
      if (vals.length && JSON.stringify(vals) !== JSON.stringify(def)) {
        out[f.key] = vals;
      }
    } else if (f.type === 'pills') {
      const box = container.querySelector(`[data-fkey="${f.key}"][data-ftype="pills"]`);
      if (!box) return;
      const v = box.dataset.value;
      const def = f.default !== undefined ? String(f.default) : '';
      if (v && v !== def) out[f.key] = v;
      else if (v && !def) out[f.key] = v;  // default vazio → qualquer seleção conta
    } else if (f.type === 'pills-multi') {
      const box = container.querySelector(`[data-fkey="${f.key}"][data-ftype="pills-multi"]`);
      if (!box) return;
      const vals = [...box.querySelectorAll('button')]
        .filter(b => b.dataset.on === '1').map(b => b.dataset.val);
      const def = f.default || [];
      if (vals.length && JSON.stringify(vals) !== JSON.stringify(def)) {
        out[f.key] = vals;
      }
    } else if (f.type === 'boolean') {
      const cb = container.querySelector(`[data-fkey="${f.key}"][data-ftype="boolean"]`);
      if (cb && cb.checked) out[f.key] = true;
    } else if (f.type === 'boolean_default_on') {
      // Default backend é TRUE. Só enviamos explicit false quando user
      // desmarcou — se checked (default), nada enviamos (worker vai usar default).
      const cb = container.querySelector(`[data-fkey="${f.key}"][data-ftype="boolean_default_on"]`);
      if (cb && !cb.checked) out[f.key] = false;
    } else if (f.type === 'lines') {
      const ta = container.querySelector(`[data-fkey="${f.key}"]`);
      if (ta && ta.value.trim()) {
        out[f.key] = ta.value.split('\n').map(s => s.trim()).filter(Boolean);
      }
    } else {
      const el = container.querySelector(`[data-fkey="${f.key}"]`);
      if (!el) return;
      const v = el.value?.trim();
      if (!v) return;
      if (f.type === 'number') out[f.key] = Number(v);
      else out[f.key] = v;
    }
  });
  return out;
}

function openNewRunDialog() {
  if (!selectedRecipe) return;
  document.getElementById('new-run-recipe-name').textContent = selectedRecipe;
  document.getElementById('new-run-input').value = '';
  newRunMode = 'text';
  document.getElementById('new-run-mode-toggle').textContent = '⚙ modo JSON';
  renderAdvancedOpts(selectedRecipe);
  document.getElementById('new-run-modal').style.display = 'flex';
}
function closeNewRunDialog() {
  document.getElementById('new-run-modal').style.display = 'none';
}
document.getElementById('new-run-mode-toggle').onclick = (e) => {
  e.preventDefault();
  const ta = document.getElementById('new-run-input');
  const toggle = document.getElementById('new-run-mode-toggle');
  if (newRunMode === 'text') {
    newRunMode = 'json';
    const cur = ta.value.trim();
    if (cur && !cur.startsWith('{')) ta.value = JSON.stringify({brief: cur}, null, 2);
    else if (!cur) ta.value = '{}';
    ta.placeholder = '{"brief": "...", "with_research": false}';
    toggle.textContent = '← texto simples';
  } else {
    newRunMode = 'text';
    try {
      const j = JSON.parse(ta.value);
      if (j.brief && typeof j.brief === 'string') ta.value = j.brief;
      else ta.value = '';
    } catch(e) {}
    ta.placeholder = 'ex.: Curso IA pra empreendedores, 30 dias resultados';
    toggle.textContent = '⚙ modo JSON';
  }
};
// Recipes que exigem um brief/topic preenchido (textarea não-vazio)
const RECIPES_REQUIRE_BRIEF = new Set([
  'campanha-marketing', 'campanha-marketing-ab',
  'carrossel-rico', 'curso-educativo',
]);
// carrossel-simples é opcional — pode rodar só com title/captions/cta

async function submitNewRun() {
  const raw = document.getElementById('new-run-input').value.trim();
  let input;
  if (newRunMode === 'json' || raw.startsWith('{')) {
    try { input = JSON.parse(raw || '{}'); }
    catch (e) { alert('JSON inválido: ' + e.message); return; }
  } else {
    // Texto simples vira brief OU topic dependendo da recipe.
    // carrossel-simples e carrossel-rico aceitam ambos via || na recipe.
    input = raw ? { brief: raw, topic: raw } : {};
  }
  // Merge opções avançadas específicas da recipe
  const adv = collectAdvancedOpts(selectedRecipe);
  input = { ...input, ...adv };

  // Validação: recipes principais exigem brief/topic
  if (RECIPES_REQUIRE_BRIEF.has(selectedRecipe)) {
    const hasBrief = (input.brief && String(input.brief).trim()) ||
                     (input.topic && String(input.topic).trim());
    if (!hasBrief) {
      alert(
        `A receita "${selectedRecipe}" exige uma descrição (brief/topic) ` +
        `no textarea principal.\n\n` +
        `Preencha o campo "Input" no topo do modal com o tópico/objetivo ` +
        `antes de rodar.`
      );
      document.getElementById('new-run-input').focus();
      return;
    }
  }

  const r = await api('/recipes/' + encodeURIComponent(selectedRecipe) + '/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tenant_id: 'inema', user_id: 'nei',
      input, origin_channel: 'runs-ui',
    }),
  });
  if (!r.ok) { alert('Falhou: ' + r.status); return; }
  const { run_id } = await r.json();
  closeNewRunDialog();
  await loadRuns(selectedRecipe);
  selectRun(run_id);
}

async function loadRuns(recipeName) {
  if (!recipeName) return;
  document.getElementById('runs-header').textContent = 'Runs · ' + recipeName;
  const r = await fetch('/runs?recipe=' + encodeURIComponent(recipeName) + '&limit=100');
  if (!r.ok) return;
  const runs = await r.json();
  const list = document.getElementById('runs-list');
  list.innerHTML = '';
  if (runs.length === 0) {
    list.innerHTML = '<div class="empty">Nenhuma run dessa receita ainda</div>';
    return;
  }
  runs.forEach(run => {
    const row = document.createElement('div');
    row.className = 'run-row';
    row.dataset.runId = run.run_id;
    if (run.run_id === selectedRunId) row.classList.add('active');
    row.onclick = () => selectRun(run.run_id);

    const when = run.created_at
      ? new Date(run.created_at).toLocaleString('pt-BR', {
          day:'2-digit', month:'2-digit', year:'2-digit',
          hour:'2-digit', minute:'2-digit', second:'2-digit'
        })
      : '';
    const summary = Object.entries(run.stage_counts || {})
      .map(([k, v]) => `<span class="pill ${k}">${v} ${k}</span>`).join('');

    row.innerHTML = `
      <div class="row-top">
        <span class="when">${when}</span>
        <span style="display:flex;align-items:center;gap:6px;">
          <span class="pill ${run.status}">${run.status}</span>
          <button title="Deletar run" class="row-del-btn"
            onclick="event.stopPropagation(); deleteRun('${run.run_id}');"
            style="background:transparent;border:none;color:#7d8590;font-size:14px;cursor:pointer;padding:0 4px;">🗑</button>
        </span>
      </div>
      <div class="meta">${run.run_id.slice(0,8)}… · ${run.tenant_id}/${run.user_id || '-'}</div>
      <div class="summary">${summary}</div>
    `;
    list.appendChild(row);
  });
}

// ── coluna 3: detalhe da run ──────────────────────────────────
async function selectRun(runId) {
  selectedRunId = runId;
  document.querySelectorAll('.run-row').forEach(r => {
    r.classList.toggle('active', r.dataset.runId === runId);
  });
  await renderDetail(runId);
}

async function renderDetail(runId, opts) {
  // Backlog #23 — no auto-refresh, preserva scroll position (e colapsos).
  // opts.preserveScroll: true quando chamado pelo setInterval.
  const detail = document.getElementById('detail');
  const preserveScroll = opts && opts.preserveScroll;
  const prevScrollTop = preserveScroll ? detail.scrollTop : 0;
  const prevStageOpen = {};
  if (preserveScroll) {
    detail.querySelectorAll('details[data-sid]').forEach(el => {
      prevStageOpen[el.dataset.sid] = el.open;
    });
  }

  if (!preserveScroll) {
    detail.innerHTML = '<div class="empty">carregando…</div>';
  }

  const r = await api('/runs/' + runId);
  if (!r.ok) {
    if (!preserveScroll) detail.innerHTML = '<div class="empty">run não encontrada</div>';
    return;
  }
  const run = await r.json();

  const status = run.failed ? 'failed' : (run.finished ? 'success' : 'running');
  // Pills destacados: video_mode (quick/pro/skip), platform alvo, approval
  const modePills = [];
  // video_mode: default é "quick" quando recipe é campanha-marketing e não explícito
  const recipeHasVideo = ['campanha-marketing','campanha-marketing-ab'].includes(run.recipe);
  const vm = (run.input || {}).video_mode || (recipeHasVideo ? 'quick' : null);
  if (vm) {
    const vmColor = vm === 'pro' ? '#7c3aed' : (vm === 'skip' ? '#6b7280' : '#1f6feb');
    modePills.push(`<span class="pill" style="background:${vmColor};color:white;">video: ${vm.toUpperCase()}</span>`);
  }
  const pl = (run.input || {}).platform;
  if (pl) modePills.push(`<span class="pill" style="background:#10b981;color:white;">📱 ${pl}</span>`);
  const am = (run.input || {}).approval_mode;
  if (am) modePills.push(`<span class="pill" style="background:#f59e0b;color:white;">🔒 aprovação: ${am}</span>`);
  const sc = (run.input || {}).slide_count;
  if (sc) modePills.push(`<span class="pill" style="background:#475569;color:white;">${sc} slides</span>`);

  let html = `
    <h2>${run.recipe} <span class="pill ${status}">${status}</span> ${modePills.join(' ')}</h2>
    <div class="run-meta">
      <code>${run.run_id}</code> · tenant <b>${run.tenant_id}</b>
    </div>
    ${renderInputCard(run.input)}
    <div class="toolbar">
      <button onclick="rerunAll('${run.run_id}')">▶ Rodar de novo</button>
      <a class="ghost" href="/runs/${run.run_id}/bundle.zip"
         style="text-decoration:none;padding:7px 14px;border-radius:6px;border:1px solid #30363d;color:#e6edf3;font-size:13px;">
         📥 Baixar bundle.zip
      </a>
      <button class="ghost" onclick="deleteRun('${run.run_id}')"
              style="color:#f85149;border-color:#3b1519;">
         🗑 Deletar
      </button>
    </div>
  `;

  html += '<div>';
  for (const [sid, stg] of Object.entries(run.stages)) {
    const stat = stg.status;
    const outputsSample = renderOutputs(stg.outputs);
    const artifacts = extractArtifactUrls(stg.outputs);
    const cap = stg.requires || '';
    const desc = CAP_DESC[cap] || '';
    // data-sid pro preserveScroll lembrar qual details estava aberto
    html += `
      <div class="stage-card" data-sid="${sid}">
        <div class="head">
          <div class="sid">
            ${sid} <span class="pill ${stat}">${stat}</span>
            ${cap ? `<span class="cap">${escapeHtml(cap)}</span>` : ''}
          </div>
          <div>
            <button class="small ghost" onclick="rerunFrom('${run.run_id}','${sid}')">▶ re-rodar a partir</button>
          </div>
        </div>
        ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ''}
        ${stg.error ? `<div class="err">${escapeHtml(stg.error)}</div>` : ''}
        ${artifacts.length ? `<div>${artifacts.map(a => renderArtifact(a)).join('')}</div>` : ''}
        ${outputsSample ? `<details data-sid="${sid}-output"><summary>output JSON</summary>${outputsSample}</details>` : ''}
      </div>
    `;
  }
  html += '</div>';
  detail.innerHTML = html;

  // Backlog #23 — restaura scroll + open-state de <details> após re-render
  if (preserveScroll) {
    detail.querySelectorAll('details[data-sid]').forEach(el => {
      const sid = el.dataset.sid;
      if (prevStageOpen[sid] !== undefined) el.open = prevStageOpen[sid];
    });
    detail.scrollTop = prevScrollTop;
  }
}

// ── artefatos ─────────────────────────────────────────────────
// Card com o input original (texto que o user digitou pra rodar a receita)
function renderInputCard(input) {
  if (!input || (typeof input === 'object' && Object.keys(input).length === 0)) {
    return '';
  }
  // Pega o campo de texto principal (pela convenção das receitas)
  const TEXT_KEYS = ['brief', 'topic', 'prompt', 'text', 'query'];
  let mainText = null;
  let mainKey = null;
  for (const k of TEXT_KEYS) {
    if (typeof input[k] === 'string' && input[k].trim()) {
      mainText = input[k]; mainKey = k; break;
    }
  }
  // Outros campos (flags/configs) — lista compacta
  const rest = Object.entries(input)
    .filter(([k, v]) => k !== mainKey && v !== null && v !== undefined && v !== '')
    .map(([k, v]) => {
      const sv = typeof v === 'object' ? JSON.stringify(v) : String(v);
      return `<span class="input-kv"><b>${escapeHtml(k)}:</b> ${escapeHtml(sv.slice(0, 80))}</span>`;
    }).join('');

  // preview = 1 linha do texto principal (80 chars)
  const preview = mainText ? escapeHtml(mainText.replace(/\s+/g, ' ').slice(0, 80) + (mainText.length > 80 ? '…' : '')) : '';
  return `
    <details class="input-card">
      <summary>
        <span class="caret">▶</span>
        <span class="input-card-label">SOLICITAÇÃO</span>
        ${preview ? `<span class="input-card-preview">${preview}</span>` : ''}
      </summary>
      ${mainText ? `<div class="input-card-text">${escapeHtml(mainText)}</div>` : ''}
      ${rest ? `<div class="input-card-rest">${rest}</div>` : ''}
    </details>
  `;
}

function extractArtifactUrls(outputs) {
  const seen = new Set();
  const urls = [];
  const walk = (v) => {
    if (typeof v === 'string' && (v.startsWith('http') || v.startsWith('/artifacts/') || v.startsWith('/s3/') || v.startsWith('file://'))) {
      if (!seen.has(v)) { seen.add(v); urls.push(v); }
    } else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  (outputs || []).forEach(walk);
  return urls;
}
function renderArtifact(url) {
  const lower = url.toLowerCase();
  const shortUrl = url.length > 60 ? url.slice(0, 30) + '…' + url.slice(-25) : url;
  if (/\.(png|jpg|jpeg|webp|gif)(\?|$)/.test(lower)) {
    return `<a href="${url}" target="_blank"><img class="art-img" src="${url}" loading="lazy"></a>`;
  }
  if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
    return `<a class="art-link" href="${url}" target="_blank">▶ vídeo: ${shortUrl}</a><br>`;
  }
  if (/\.(mp3|wav|m4a|ogg)(\?|$)/.test(lower)) {
    return `<a class="art-link" href="${url}" target="_blank">🔊 áudio: ${shortUrl}</a><br>`;
  }
  return `<a class="art-link" href="${url}" target="_blank">🔗 ${shortUrl}</a><br>`;
}
function renderOutputs(outputs) {
  if (!outputs || outputs.length === 0) return '';
  try { return `<pre>${escapeHtml(JSON.stringify(outputs.length === 1 ? outputs[0] : outputs, null, 2))}</pre>`; }
  catch (e) { return ''; }
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── actions ───────────────────────────────────────────────────
async function deleteRun(runId) {
  if (!confirm(`Deletar permanentemente a run ${runId.slice(0,8)}…?\n\nArtefatos (imagens/vídeos) no storage NÃO serão removidos — apenas o registro da execução.`)) return;
  const r = await api('/runs/' + runId, { method: 'DELETE' });
  if (!r.ok) {
    const txt = await r.text();
    alert(`Falhou: ${r.status} — ${txt.slice(0,200)}`);
    return;
  }
  // Se era a run selecionada, limpa detalhe
  if (selectedRunId === runId) {
    selectedRunId = null;
    document.getElementById('detail').innerHTML =
      '<div class="empty">Run deletada. Selecione outra.</div>';
  }
  await loadRuns(selectedRecipe);
  await loadRecipes();  // atualiza contadores na coluna 1
}

async function rerunAll(runId) {
  if (!confirm('Re-rodar a receita inteira com o mesmo input? (nova run)')) return;
  const r = await api('/runs/' + runId + '/rerun', { method: 'POST' });
  if (r.ok) {
    const { run_id } = await r.json();
    await loadRuns(selectedRecipe);
    selectRun(run_id);
  } else alert('Falhou: ' + r.status);
}
async function rerunFrom(runId, stageId) {
  if (!confirm(`Re-rodar a partir do stage '${stageId}'? Stages anteriores serão copiados da run original (não re-executados).`)) return;
  const r = await api('/runs/' + runId + '/rerun-from/' + stageId, { method: 'POST' });
  if (r.ok) {
    const data = await r.json();
    await loadRuns(selectedRecipe);
    selectRun(data.run_id);
  } else {
    const txt = await r.text();
    alert('Falhou: ' + r.status + ' — ' + txt.slice(0, 200));
  }
}

// ── init + auto-refresh ───────────────────────────────────────
updateAuthStatus();
loadRecipes();

// Backlog #23 — auto-refresh preserva scroll + colapsos
setInterval(() => {
  loadRecipes();  // atualiza contadores (coluna 1, não afeta scroll do detail)
  if (selectedRecipe) loadRuns(selectedRecipe);
  if (selectedRunId) {
    fetch('/runs/' + selectedRunId).then(r => r.json()).then(run => {
      if (!run.finished) renderDetail(selectedRunId, { preserveScroll: true });
    }).catch(()=>{});
  }
}, 5000);
</script>
</body>
</html>
"""

RUNS_UI_HTML = RUNS_UI_HTML.replace("</body>", _MEDIA_MODAL_HTML + _UNIVERSAL_MODAL_HTML + "</body>")
