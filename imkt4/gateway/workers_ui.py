"""Workers Browser — histórico de jobs por worker.

Layout 3 colunas (mesmo idioma do /runs-ui):
  1. Workers (com health e contador de jobs recentes)
  2. Jobs desse worker (mais recente primeiro)
  3. Detalhe do job (payload, output, erro)

Ações:
  - 🔁 Reprocessar (re-dispatch do mesmo payload)
"""

WORKERS_UI_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>imkt4 · workers</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; background: #0d1117; color: #e6edf3;
         font-family: system-ui, -apple-system, sans-serif; }

  .topbar { background: #161b22; border-bottom: 1px solid #30363d;
            padding: 12px 20px; display: flex; align-items: center; gap: 20px; }
  .topbar h1 { margin: 0; font-size: 18px; }
  .topbar nav { display: flex; gap: 4px; font-size: 13px; }
  .topbar nav a { color: #7d8590; text-decoration: none;
                  padding: 6px 12px; border-radius: 6px; }
  .topbar nav a.active { color: #1f6feb; background: #21262d; font-weight: 600; }
  .auth { margin-left: auto; font-size: 12px; color: #7d8590; }
  .auth button { padding: 4px 10px; font-size: 11px; background: transparent;
                 border: 1px solid #30363d; color: #e6edf3; border-radius: 6px;
                 cursor: pointer; }

  .body { display: grid; grid-template-columns: 260px 380px 1fr;
          height: calc(100vh - 50px); }

  .col { background: #161b22; border-right: 1px solid #30363d; overflow-y: auto; }
  .col:last-child { background: #0d1117; border-right: none; }

  .col-header { padding: 14px 16px; border-bottom: 1px solid #30363d;
                display: flex; justify-content: space-between; align-items: center;
                position: sticky; top: 0; background: #161b22; z-index: 5; }
  .col-header h2 { margin: 0; font-size: 12px; color: #7d8590;
                   text-transform: uppercase; letter-spacing: 0.5px; }

  /* workers */
  .worker-row { padding: 12px 14px; cursor: pointer; border-left: 3px solid transparent;
                border-bottom: 1px solid #21262d; }
  .worker-row:hover { background: #21262d; }
  .worker-row.active { background: #21262d; border-left-color: #1f6feb; }
  .worker-row .name-line { display: flex; justify-content: space-between;
                           align-items: center; }
  .worker-row .name { font-weight: 600; font-size: 13px; }
  .worker-row .caps { color: #7d8590; font-family: monospace; font-size: 10px;
                      margin-top: 4px; line-height: 1.4; word-break: break-all; }
  .worker-row .jobs-count { color: #7d8590; font-size: 11px; margin-top: 4px; }
  .worker-row .jobs-count b { color: #e6edf3; }

  /* jobs */
  .job-row { padding: 12px 14px; cursor: pointer; border-left: 3px solid transparent;
             border-bottom: 1px solid #21262d; }
  .job-row:hover { background: #21262d; }
  .job-row.active { background: #21262d; border-left-color: #1f6feb; }
  .job-row .row-top { display: flex; justify-content: space-between; align-items: center; }
  .job-row .when { font-size: 12px; font-weight: 500; }
  .job-row .meta { color: #7d8590; font-size: 10px; font-family: monospace; margin-top: 4px; }
  .job-row .cap { color: #1f6feb; font-size: 11px; font-family: monospace; margin-top: 4px; }

  .pill { display: inline-block; padding: 2px 7px; border-radius: 10px;
          font-size: 9px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
  .pill.healthy { background: #238636; color: white; }
  .pill.degraded, .pill.pending { background: #9e6a03; color: white; }
  .pill.unhealthy { background: #da3633; color: white; }
  .pill.success { background: #238636; color: white; }
  .pill.running { background: #1f6feb; color: white; }
  .pill.failed  { background: #da3633; color: white; }
  .pill.saturated { background: #9e6a03; color: white; }

  .detail { padding: 20px 24px; }
  .detail h2 { margin: 0 0 4px 0; font-size: 20px; }
  .detail .meta { color: #7d8590; font-size: 13px; margin-bottom: 16px;
                  font-family: monospace; }
  .detail .toolbar { display: flex; gap: 8px; margin-bottom: 20px; }
  .detail .section { background: #161b22; border: 1px solid #30363d;
                     padding: 14px 16px; border-radius: 8px; margin-bottom: 12px; }
  .detail .section h3 { margin: 0 0 8px 0; font-size: 12px; color: #7d8590;
                        text-transform: uppercase; letter-spacing: 0.5px; }
  .detail pre { background: #0d1117; color: #e6edf3; padding: 10px;
                border-radius: 4px; font-size: 11px; max-height: 400px;
                overflow: auto; margin: 0; white-space: pre-wrap;
                word-break: break-word; }
  .detail .err { color: #f85149; font-family: monospace; font-size: 12px;
                 background: #3b1519; padding: 10px; border-radius: 4px;
                 white-space: pre-wrap; word-break: break-word; }

  .art-link { color: #1f6feb; text-decoration: none; font-size: 12px;
              word-break: break-all; }
  .art-link:hover { text-decoration: underline; }
  .art-img { max-width: 200px; max-height: 200px; border-radius: 4px;
             border: 1px solid #30363d; margin-right: 6px; margin-top: 6px; }

  .empty { padding: 60px 30px; text-align: center; color: #7d8590; font-size: 13px; }

  button { background: #1f6feb; color: white; border: none; padding: 7px 14px;
           border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
  button:hover { background: #388bfd; }
  button.ghost { background: transparent; border: 1px solid #30363d; color: #e6edf3; }
  button.ghost:hover { background: #21262d; }
  button.small { padding: 4px 10px; font-size: 11px; }

  .refresh-badge { font-size: 10px; color: #3fb950; }

  .filter-row { padding: 8px 14px; background: #0d1117; border-bottom: 1px solid #30363d;
                display: flex; gap: 6px; }
  .filter-row button { font-size: 10px; padding: 3px 8px; background: transparent;
                       border: 1px solid #30363d; color: #7d8590; }
  .filter-row button.active { background: #21262d; color: #e6edf3; border-color: #1f6feb; }
</style>
</head>
<body>

<div class="topbar">
  <h1>imkt4</h1>
  <nav>
    <a href="/ui">Workspace</a>
    <a href="/recipes-ui">Receitas</a>
    <a href="/runs-ui">Execuções</a>
    <a href="/workers-ui" class="active">Workers</a>
    <a href="/admin">Admin</a>
  </nav>
  <div class="auth">
    <span id="auth-status">sem token</span>
    <button onclick="setToken()">token</button>
  </div>
</div>

<div class="body">
  <aside class="col">
    <div class="col-header">
      <h2>Workers</h2>
      <button class="small ghost" onclick="loadWorkers(true)">↻</button>
    </div>
    <div id="workers-list"></div>
  </aside>

  <aside class="col">
    <div class="col-header">
      <h2 id="jobs-header">Jobs</h2>
      <span class="refresh-badge" id="refresh-badge"></span>
    </div>
    <div class="filter-row" id="filter-row" style="display:none;">
      <button data-st="" class="active" onclick="setStatusFilter('')">todos</button>
      <button data-st="success" onclick="setStatusFilter('success')">success</button>
      <button data-st="failed"  onclick="setStatusFilter('failed')">failed</button>
      <button data-st="running" onclick="setStatusFilter('running')">running</button>
    </div>
    <div id="jobs-list">
      <div class="empty">Selecione um worker à esquerda</div>
    </div>
  </aside>

  <section class="col">
    <div class="detail" id="detail">
      <div class="empty">Selecione um job pra ver detalhes</div>
    </div>
  </section>
</div>

<script>
function getToken() { return localStorage.getItem('imkt4_admin_token') || ''; }
function setToken() {
  const t = prompt('Token admin (Bearer):', getToken());
  if (t !== null) { localStorage.setItem('imkt4_admin_token', t.trim()); location.reload(); }
}
function updateAuthStatus() {
  const t = getToken();
  const el = document.getElementById('auth-status');
  el.textContent = t ? 'autenticado (' + t.slice(0,6) + '…)' : 'sem token';
  el.style.color = t ? '#3fb950' : '#7d8590';
}
async function api(url, opts = {}) {
  const token = getToken();
  const h = { ...(opts.headers || {}) };
  if (token) h['Authorization'] = 'Bearer ' + token;
  return fetch(url, { ...opts, headers: h });
}

let selectedWorker = null;
let selectedJobId = null;
let statusFilter = '';

// ── workers ───────────────────────────────────────────────────
async function loadWorkers(flash) {
  const [wResp, jResp] = await Promise.all([
    fetch('/workers'), fetch('/jobs?limit=200'),
  ]);
  const workers = await wResp.json();
  const jobs = await jResp.json();

  const counts = {};
  jobs.forEach(j => {
    const w = j.worker_name;
    if (!w) return;
    counts[w] = counts[w] || { total: 0, success: 0, failed: 0, running: 0 };
    counts[w].total++;
    if (j.status === 'success') counts[w].success++;
    else if (j.status === 'failed') counts[w].failed++;
    else if (j.status === 'running' || j.status === 'pending') counts[w].running++;
  });

  const list = document.getElementById('workers-list');
  list.innerHTML = '';
  workers.forEach(w => {
    const c = counts[w.name] || { total: 0, success: 0, failed: 0, running: 0 };
    const row = document.createElement('div');
    row.className = 'worker-row';
    row.dataset.name = w.name;
    if (w.name === selectedWorker) row.classList.add('active');
    row.onclick = () => selectWorker(w.name);

    const okRate = c.total > 0 ? Math.round(100 * c.success / c.total) : null;
    row.innerHTML = `
      <div class="name-line">
        <span class="name">${w.name}</span>
        <span class="pill ${w.health}">${w.health}</span>
      </div>
      <div class="caps">${w.capabilities.join(', ')}</div>
      <div class="jobs-count">
        <b>${c.total}</b> jobs
        ${c.failed ? `· <span style="color:#f85149;">${c.failed} failed</span>` : ''}
        ${c.running ? `· <span style="color:#1f6feb;">${c.running} running</span>` : ''}
        ${okRate !== null ? `· ${okRate}% ok` : ''}
      </div>
    `;
    list.appendChild(row);
  });

  if (flash) {
    const b = document.getElementById('refresh-badge');
    b.textContent = '↻'; setTimeout(() => { b.textContent = ''; }, 1200);
  }
}

// ── jobs do worker ────────────────────────────────────────────
async function selectWorker(name) {
  selectedWorker = name;
  selectedJobId = null;
  document.querySelectorAll('.worker-row').forEach(r => {
    r.classList.toggle('active', r.dataset.name === name);
  });
  document.getElementById('filter-row').style.display = 'flex';
  document.getElementById('detail').innerHTML =
    '<div class="empty">Selecione um job pra ver detalhes</div>';
  await loadJobs();
}

function setStatusFilter(st) {
  statusFilter = st;
  document.querySelectorAll('.filter-row button').forEach(b => {
    b.classList.toggle('active', b.dataset.st === st);
  });
  loadJobs();
}

async function loadJobs() {
  if (!selectedWorker) return;
  document.getElementById('jobs-header').textContent = 'Jobs · ' + selectedWorker;

  let url = '/jobs?limit=100&worker_name=' + encodeURIComponent(selectedWorker);
  if (statusFilter) url += '&status=' + encodeURIComponent(statusFilter);
  const r = await fetch(url);
  if (!r.ok) return;
  const jobs = await r.json();

  const list = document.getElementById('jobs-list');
  list.innerHTML = '';
  if (jobs.length === 0) {
    list.innerHTML = '<div class="empty">Sem jobs pra esse worker' + (statusFilter ? ' (filtro ' + statusFilter + ')' : '') + '</div>';
    return;
  }
  jobs.forEach(j => {
    const row = document.createElement('div');
    row.className = 'job-row';
    row.dataset.jobId = j.job_id;
    if (j.job_id === selectedJobId) row.classList.add('active');
    row.onclick = () => selectJob(j.job_id);

    const when = j.updated_at
      ? new Date(j.updated_at).toLocaleString('pt-BR', {
          day:'2-digit', month:'2-digit', year:'2-digit',
          hour:'2-digit', minute:'2-digit', second:'2-digit',
        })
      : '';
    row.innerHTML = `
      <div class="row-top">
        <span class="when">${when}</span>
        <span class="pill ${j.status}">${j.status}</span>
      </div>
      <div class="cap">${j.capability || j.worker_type || '?'}</div>
      <div class="meta">${j.job_id.slice(0,8)}… · ${j.tenant_id}/${j.user_id || '-'}</div>
    `;
    list.appendChild(row);
  });
}

// ── detalhe ───────────────────────────────────────────────────
async function selectJob(jobId) {
  selectedJobId = jobId;
  document.querySelectorAll('.job-row').forEach(r => {
    r.classList.toggle('active', r.dataset.jobId === jobId);
  });
  await renderDetail(jobId);
}

async function renderDetail(jobId) {
  const main = document.getElementById('detail');
  main.innerHTML = '<div class="empty">carregando…</div>';

  const r = await fetch('/jobs/' + jobId);
  if (!r.ok) { main.innerHTML = '<div class="empty">job não encontrado</div>'; return; }
  const j = await r.json();

  const artifacts = extractArtifactUrls(j.output);

  let html = `
    <h2>${j.capability || j.worker_type} <span class="pill ${j.status}">${j.status}</span></h2>
    <div class="meta">${j.job_id} · ${j.tenant_id}/${j.user_id || '-'} · ${j.updated_at ? new Date(j.updated_at).toLocaleString('pt-BR') : ''}</div>
    <div class="toolbar">
      <button onclick="retryJob('${j.job_id}')">🔁 Reprocessar</button>
    </div>
  `;

  if (j.error) {
    html += `<div class="section"><h3>Erro</h3><div class="err">${escapeHtml(j.error)}</div></div>`;
  }

  if (artifacts.length) {
    html += `<div class="section"><h3>Artefatos</h3>${artifacts.map(renderArtifact).join('')}</div>`;
  }

  html += `<div class="section"><h3>Output</h3>${
    j.output && Object.keys(j.output).length
      ? `<pre>${escapeHtml(JSON.stringify(j.output, null, 2))}</pre>`
      : '<div style="color:#7d8590;font-size:12px;">(vazio)</div>'
  }</div>`;

  main.innerHTML = html;
}

async function retryJob(jobId) {
  const r = await fetch('/jobs/' + jobId);
  if (!r.ok) { alert('job não encontrado'); return; }
  const j = await r.json();
  // Sem payload persistido no store, copia do backend via uma api /jobs/retry?
  // por ora, informa que retry requer payload original
  if (!confirm('Reprocessar (dispatch novo job com mesmos capability/tenant/user)?\nObs: payload original não é persistido, será payload vazio.')) return;
  const resp = await fetch('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tenant_id: j.tenant_id, user_id: j.user_id,
      capability: j.capability, worker_type: j.worker_type,
      payload: {},
    }),
  });
  if (resp.ok) {
    const { job_id } = await resp.json();
    await loadJobs();
    selectJob(job_id);
  } else {
    alert('Falhou: ' + resp.status);
  }
}

// ── artefatos ─────────────────────────────────────────────────
function extractArtifactUrls(obj) {
  const urls = [];
  const walk = (v) => {
    if (typeof v === 'string' &&
        (v.startsWith('http') || v.startsWith('/artifacts/') || v.startsWith('file://'))) {
      urls.push(v);
    } else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(obj);
  return urls;
}
function renderArtifact(url) {
  const lower = url.toLowerCase();
  const shortUrl = url.length > 60 ? url.slice(0, 30) + '…' + url.slice(-25) : url;
  if (/\.(png|jpg|jpeg|webp|gif)(\?|$)/.test(lower)) {
    return `<a href="${url}" target="_blank"><img class="art-img" src="${url}" loading="lazy"></a>`;
  }
  if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
    return `<a class="art-link" href="${url}" target="_blank">▶ ${shortUrl}</a><br>`;
  }
  if (/\.(mp3|wav|m4a|ogg)(\?|$)/.test(lower)) {
    return `<a class="art-link" href="${url}" target="_blank">🔊 ${shortUrl}</a><br>`;
  }
  return `<a class="art-link" href="${url}" target="_blank">🔗 ${shortUrl}</a><br>`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// init
updateAuthStatus();
loadWorkers();
setInterval(() => {
  loadWorkers();
  if (selectedWorker) loadJobs();
  if (selectedJobId) {
    fetch('/jobs/' + selectedJobId).then(r => r.json()).then(j => {
      if (j.status === 'running' || j.status === 'pending') renderDetail(selectedJobId);
    }).catch(()=>{});
  }
}, 5000);
</script>
</body>
</html>
"""
