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
         max-width:560px; width:90%;">
      <h3 style="margin:0 0 8px 0; font-size:16px;">Nova execução</h3>
      <div style="color:#7d8590; font-size:13px; margin-bottom:14px;">
        Receita: <b id="new-run-recipe-name"></b>
      </div>
      <label style="display:block;color:#7d8590;font-size:12px;margin-bottom:6px;">
        Input
        <a href="#" id="new-run-mode-toggle" style="margin-left:10px;font-size:11px;color:#1f6feb;text-decoration:none;">⚙ modo JSON</a>
      </label>
      <textarea id="new-run-input" rows="6"
        placeholder="ex.: Curso IA pra empreendedores, 30 dias resultados"
        style="width:100%; background:#0d1117; color:#e6edf3; border:1px solid #30363d;
               padding:10px; border-radius:6px; font-size:13px; font-family:ui-monospace, monospace;"></textarea>
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
function openNewRunDialog() {
  if (!selectedRecipe) return;
  document.getElementById('new-run-recipe-name').textContent = selectedRecipe;
  document.getElementById('new-run-input').value = '';
  newRunMode = 'text';
  document.getElementById('new-run-mode-toggle').textContent = '⚙ modo JSON';
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
async function submitNewRun() {
  const raw = document.getElementById('new-run-input').value.trim();
  let input;
  if (newRunMode === 'json' || raw.startsWith('{')) {
    try { input = JSON.parse(raw || '{}'); }
    catch (e) { alert('JSON inválido: ' + e.message); return; }
  } else {
    input = raw ? { brief: raw } : {};
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
        <span class="pill ${run.status}">${run.status}</span>
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
  let html = `
    <h2>${run.recipe} <span class="pill ${status}">${status}</span></h2>
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
