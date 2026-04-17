"""Runs Browser — histórico de execuções de receitas.

Servido em GET /runs-ui. Mostra lista de runs recentes, e ao clicar
numa, detalhe completo com cada stage (status, outputs). Permite:
  - ▶ Rodar de novo (dispara /runs/{id}/rerun)
  - ▶ Re-rodar a partir de um stage (rerun-from/{stage_id})
  - 📥 Baixar bundle.zip

Separado da /ui, /admin, /recipes-ui.
"""

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

  .body { display: grid; grid-template-columns: 380px 1fr;
          height: calc(100vh - 50px); }

  .sidebar { background: #161b22; border-right: 1px solid #30363d;
             overflow-y: auto; }
  .sidebar .header { padding: 14px 16px; border-bottom: 1px solid #30363d;
                     display: flex; justify-content: space-between; align-items: center; }
  .sidebar .header h2 { margin: 0; font-size: 14px; color: #7d8590;
                        text-transform: uppercase; letter-spacing: 0.5px; }

  .run-row { padding: 12px 16px; cursor: pointer; border-left: 3px solid transparent;
             border-bottom: 1px solid #21262d; transition: background 0.1s; }
  .run-row:hover { background: #21262d; }
  .run-row.active { background: #21262d; border-left-color: #1f6feb; }
  .run-row .top { display: flex; justify-content: space-between; align-items: center; }
  .run-row .recipe { font-weight: 600; font-size: 14px; }
  .run-row .meta { color: #7d8590; font-size: 11px; margin-top: 2px; }
  .run-row .status-line { font-size: 11px; margin-top: 6px; }

  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 10px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
  .pill.success { background: #238636; color: white; }
  .pill.running { background: #1f6feb; color: white; }
  .pill.failed  { background: #da3633; color: white; }
  .pill.skipped { background: #30363d; color: #7d8590; }
  .pill.awaiting_approval { background: #9e6a03; color: white; }
  .pill.pending { background: #30363d; color: #7d8590; }

  .main { overflow-y: auto; padding: 20px 24px; }
  .main .empty { padding: 80px; text-align: center; color: #7d8590; font-size: 14px; }
  .main h2 { margin: 0 0 4px 0; font-size: 20px; }
  .main .run-meta { color: #7d8590; font-size: 13px; margin-bottom: 18px; }
  .main .toolbar { display: flex; gap: 8px; margin-bottom: 20px; }

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
                          font-size: 12px; margin-left: 8px; }
  .stage-card .actions { display: flex; gap: 6px; }
  .stage-card .err { color: #f85149; font-size: 12px; font-family: monospace;
                     margin-top: 8px; background: #3b1519; padding: 8px;
                     border-radius: 4px; }
  .stage-card pre { background: #0d1117; color: #e6edf3; padding: 10px;
                    border-radius: 4px; font-size: 11px; max-height: 300px;
                    overflow: auto; margin: 8px 0 0 0; white-space: pre-wrap;
                    word-break: break-word; }
  .stage-card details summary { cursor: pointer; color: #7d8590; font-size: 12px;
                                margin-top: 6px; }
  .stage-card details summary:hover { color: #e6edf3; }

  .art-link { color: #1f6feb; text-decoration: none; font-size: 12px; }
  .art-link:hover { text-decoration: underline; }
  .art-img { max-width: 180px; max-height: 180px; border-radius: 4px;
             border: 1px solid #30363d; margin-right: 6px; margin-top: 6px; }

  .refresh-badge { font-size: 11px; color: #3fb950; margin-left: 8px; }
</style>
</head>
<body>

<div class="topbar">
  <h1>🧭 runs</h1>
  <div class="nav">
    <a href="/ui">/ui</a>
    <a href="/admin">/admin</a>
    <a href="/recipes-ui">/recipes-ui</a>
    <a href="/runs-ui" class="active">/runs-ui</a>
  </div>
  <div class="auth">
    <span id="auth-status">sem token</span>
    <button onclick="setToken()">token</button>
  </div>
</div>

<div class="body">
  <aside class="sidebar">
    <div class="header">
      <h2>Histórico <span class="refresh-badge" id="refresh-badge"></span></h2>
      <button class="small ghost" onclick="loadRuns(true)">↻</button>
    </div>
    <div id="runs-list"></div>
  </aside>

  <section class="main" id="main">
    <div class="empty">Selecione uma run à esquerda</div>
  </section>
</div>

<script>
// ── auth (opcional — /runs público, mas rerun pode precisar) ─
function getToken() { return localStorage.getItem('imkt4_admin_token') || ''; }
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

let selectedRunId = null;

// ── lista ─────────────────────────────────────────────────────
async function loadRuns(flash) {
  const r = await api('/runs?limit=100');
  if (!r.ok) return;
  const runs = await r.json();
  const list = document.getElementById('runs-list');
  list.innerHTML = '';
  if (runs.length === 0) {
    list.innerHTML = '<div class="empty" style="padding:30px;color:#7d8590;font-size:13px;">Nenhuma run ainda</div>';
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
          day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'
        })
      : '';
    const stageSummary = Object.entries(run.stage_counts || {})
      .map(([k, v]) => `<span class="pill ${k}">${v} ${k}</span>`).join(' ');

    row.innerHTML = `
      <div class="top">
        <div class="recipe">${run.recipe}</div>
        <span class="pill ${run.status}">${run.status}</span>
      </div>
      <div class="meta">${when} · ${run.tenant_id}/${run.user_id || '-'}</div>
      <div class="meta" style="font-family:monospace;font-size:10px;margin-top:4px;">${run.run_id.slice(0,8)}…</div>
      <div class="status-line">${stageSummary}</div>
    `;
    list.appendChild(row);
  });

  if (flash) {
    const b = document.getElementById('refresh-badge');
    b.textContent = '↻ atualizado';
    setTimeout(() => { b.textContent = ''; }, 1200);
  }
}

// ── detalhe ───────────────────────────────────────────────────
async function selectRun(runId) {
  selectedRunId = runId;
  document.querySelectorAll('.run-row').forEach(r => {
    r.classList.toggle('active', r.dataset.runId === runId);
  });
  renderDetail(runId);
}

async function renderDetail(runId) {
  const main = document.getElementById('main');
  main.innerHTML = '<div class="empty">carregando…</div>';

  const r = await api('/runs/' + runId);
  if (!r.ok) { main.innerHTML = '<div class="empty">run não encontrada</div>'; return; }
  const run = await r.json();

  const status = run.failed ? 'failed' : (run.finished ? 'success' : 'running');
  let html = `
    <h2>${run.recipe} <span class="pill ${status}">${status}</span></h2>
    <div class="run-meta">
      <code>${run.run_id}</code> · tenant <b>${run.tenant_id}</b>
    </div>
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
    html += `
      <div class="stage-card">
        <div class="head">
          <div class="sid">${sid} <span class="pill ${stat}">${stat}</span></div>
          <div class="actions">
            <button class="small ghost" onclick="rerunFrom('${run.run_id}','${sid}')">▶ re-rodar a partir</button>
          </div>
        </div>
        ${stg.error ? `<div class="err">${escapeHtml(stg.error)}</div>` : ''}
        ${artifacts.length ? `<div>${artifacts.map(a => renderArtifact(a)).join('')}</div>` : ''}
        ${outputsSample ? `<details><summary>output JSON</summary>${outputsSample}</details>` : ''}
      </div>
    `;
  }
  html += '</div>';
  main.innerHTML = html;
}

function extractArtifactUrls(outputs) {
  const urls = [];
  const walk = (v) => {
    if (typeof v === 'string' && (v.startsWith('http') || v.startsWith('/artifacts/') || v.startsWith('file://'))) {
      urls.push(v);
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
    await loadRuns();
    selectRun(run_id);
  } else alert('Falhou: ' + r.status);
}

async function rerunFrom(runId, stageId) {
  if (!confirm(`Re-rodar a partir do stage '${stageId}'? Stages anteriores serão copiados da run original (não re-executados).`)) return;
  const r = await api('/runs/' + runId + '/rerun-from/' + stageId, { method: 'POST' });
  if (r.ok) {
    const data = await r.json();
    await loadRuns();
    selectRun(data.run_id);
  } else {
    const txt = await r.text();
    alert('Falhou: ' + r.status + ' — ' + txt.slice(0, 200));
  }
}

// ── init + polling de refresh quando runs ativas ──────────────
updateAuthStatus();
loadRuns();
setInterval(() => {
  loadRuns();
  if (selectedRunId) {
    // re-renderiza só se a run selecionada ainda está rodando
    fetch('/runs/' + selectedRunId).then(r => r.json()).then(run => {
      if (!run.finished) renderDetail(selectedRunId);
    }).catch(()=>{});
  }
}, 5000);
</script>
</body>
</html>
"""
