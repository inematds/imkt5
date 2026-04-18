"""Workers Browser — histórico de jobs por worker.

Layout 3 colunas (mesmo idioma do /runs-ui):
  1. Workers (com health e contador de jobs recentes)
  2. Jobs desse worker (mais recente primeiro)
  3. Detalhe do job (payload, output, erro)

Ações:
  - 🔁 Reprocessar (re-dispatch do mesmo payload)
"""
from imkt4.gateway._media_modal import MEDIA_MODAL_HTML as _MEDIA_MODAL_HTML
from imkt4.gateway._modal_close import UNIVERSAL_MODAL_HTML as _UNIVERSAL_MODAL_HTML



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

  /* tabs do detalhe */
  .tabs { display: flex; gap: 2px; border-bottom: 1px solid #30363d; margin-bottom: 16px; }
  .tabs button { background: transparent; border: none; color: #7d8590;
                 padding: 8px 14px; cursor: pointer; border-radius: 0;
                 font-size: 12px; border-bottom: 2px solid transparent; }
  .tabs button.active { color: #e6edf3; border-bottom-color: #1f6feb; }
  .tabs button:hover { color: #e6edf3; }
  .tab-pane { display: none; }
  .tab-pane.active { display: block; }

  /* Backlog #21 — recipes list */
  .recipe-item { background: #0d1117; border-radius: 6px; padding: 10px 12px;
                 margin-bottom: 8px; border: 1px solid #21262d; }
  .recipe-item .r-name { font-weight: 600; color: #1f6feb; font-size: 13px; }
  .recipe-item .r-ver { color: #7d8590; font-size: 11px; margin-left: 6px; }
  .recipe-item .r-stages { margin-top: 6px; font-size: 11px; font-family: monospace;
                           color: #7d8590; }
  .recipe-item .r-stage { padding: 2px 6px; background: #21262d;
                          border-radius: 3px; margin-right: 4px; margin-bottom: 3px;
                          display: inline-block; }
  .recipe-item .r-stage.fanout::after { content: ' ⚡'; color: #f0883e; }

  /* Backlog #21 — skill.md markdown */
  .skill-md { background: #0d1117; padding: 14px 16px; border-radius: 6px;
              border: 1px solid #21262d; max-height: 500px; overflow: auto;
              font-size: 12px; line-height: 1.6; }
  .skill-md h1, .skill-md h2, .skill-md h3 {
    color: #e6edf3; margin-top: 14px; margin-bottom: 6px; }
  .skill-md h1 { font-size: 16px; } .skill-md h2 { font-size: 14px; }
  .skill-md h3 { font-size: 13px; color: #1f6feb; }
  .skill-md code { background: #21262d; padding: 1px 4px; border-radius: 3px;
                   font-size: 11px; }
  .skill-md pre { background: #21262d; padding: 8px; border-radius: 4px;
                  overflow: auto; font-size: 11px; }
  .skill-md ul, .skill-md ol { padding-left: 20px; }
  .skill-md table { border-collapse: collapse; margin: 8px 0; font-size: 11px; }
  .skill-md table td, .skill-md table th {
    border: 1px solid #30363d; padding: 4px 8px; }
  .skill-md table th { background: #21262d; }

  /* Backlog #22 — modal close button universal */
  .modal-close { position: absolute; top: 14px; right: 18px;
                 background: rgba(0,0,0,0.5); color: white;
                 border: 1px solid rgba(255,255,255,0.3);
                 border-radius: 50%; width: 32px; height: 32px;
                 font-size: 16px; line-height: 1; cursor: pointer;
                 z-index: 10000; }
  .modal-close:hover { background: rgba(220, 50, 50, 0.8); border-color: white; }
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
    <a href="/chat-ui" style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Chat</a>
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
    <div class="filter-row" style="border-bottom:1px solid #30363d;">
      <button data-sort="name" class="active" onclick="setSort('name')">A-Z</button>
      <button data-sort="usage" onclick="setSort('usage')">+ usados</button>
      <button data-sort="recent" onclick="setSort('recent')">recentes</button>
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
let workerSort = localStorage.getItem('imkt4_worker_sort') || 'name';  // name | usage | recent
function setSort(s) {
  workerSort = s;
  localStorage.setItem('imkt4_worker_sort', s);
  document.querySelectorAll('[data-sort]').forEach(b => {
    b.classList.toggle('active', b.dataset.sort === s);
  });
  loadWorkers();
}

// ── workers ───────────────────────────────────────────────────
async function loadWorkers(flash) {
  const [wResp, jResp] = await Promise.all([
    fetch('/workers'), fetch('/jobs?limit=500'),
  ]);
  const workers = await wResp.json();
  const jobs = await jResp.json();

  const counts = {};
  const lastUsed = {};  // worker_name → max(updated_at)
  jobs.forEach(j => {
    const w = j.worker_name;
    if (!w) return;
    counts[w] = counts[w] || { total: 0, success: 0, failed: 0, running: 0 };
    counts[w].total++;
    if (j.status === 'success') counts[w].success++;
    else if (j.status === 'failed') counts[w].failed++;
    else if (j.status === 'running' || j.status === 'pending') counts[w].running++;
    const t = j.updated_at || j.created_at || '';
    if (!lastUsed[w] || t > lastUsed[w]) lastUsed[w] = t;
  });

  // Ordena conforme workerSort
  const sorted = [...workers].sort((a, b) => {
    if (workerSort === 'usage') {
      return (counts[b.name]?.total || 0) - (counts[a.name]?.total || 0);
    }
    if (workerSort === 'recent') {
      return (lastUsed[b.name] || '').localeCompare(lastUsed[a.name] || '');
    }
    return a.name.localeCompare(b.name);  // default: A-Z
  });

  const list = document.getElementById('workers-list');
  list.innerHTML = '';
  sorted.forEach(w => {
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
  await renderWorkerDetail(name);  // Backlog #21 — mostra SKILL + recipes por default
  await loadJobs();
}

// Backlog #21 — detalhe read-only do worker (SKILL.md + recipes)
async function renderWorkerDetail(name) {
  const main = document.getElementById('detail');
  main.innerHTML = '<div class="empty">carregando detalhe do worker…</div>';
  const r = await fetch('/workers/' + encodeURIComponent(name));
  if (!r.ok) {
    main.innerHTML = '<div class="empty">worker não encontrado</div>';
    return;
  }
  const d = await r.json();
  const caps = (d.capabilities || []).map(c => `<code>${c}</code>`).join(' ');
  const recipesHtml = (d.used_in_recipes || []).length
    ? (d.used_in_recipes).map(r => `
        <div class="recipe-item">
          <div>
            <a class="r-name" href="/recipes-ui?name=${encodeURIComponent(r.recipe)}" target="_blank">${r.recipe}</a>
            <span class="r-ver">v${r.version}</span>
          </div>
          <div class="r-stages">
            ${r.stages.map(s => `<span class="r-stage ${s.fanout ? 'fanout' : ''}" title="${s.requires}${s.fanout ? ' (fanout)' : ''}">${s.stage_id}</span>`).join('')}
          </div>
        </div>
      `).join('')
    : '<div style="color:#7d8590;font-size:12px;">Nenhuma recipe chama esse worker (pode ser via quick-dispatch).</div>';

  const siblingsHtml = (d.siblings || []).length
    ? (d.siblings).map(s => `
        <div class="recipe-item">
          <a class="r-name" href="#" onclick="selectWorker('${s.name}');return false;">${s.name}</a>
          <span class="pill ${s.health}" style="margin-left:8px;">${s.health}</span>
          <div class="r-stages">compartilham: ${s.shared_capabilities.map(c=>'<code>'+c+'</code>').join(' ')}</div>
        </div>
      `).join('')
    : '<div style="color:#7d8590;font-size:12px;">Sem outros workers oferecendo as mesmas capabilities.</div>';

  const skillHtml = d.skill_md
    ? `<div class="skill-md">${renderMarkdown(d.skill_md)}</div>`
    : '<div style="color:#7d8590;font-size:12px;">Worker não tem SKILL.md.</div>';

  main.innerHTML = `
    <h2>${d.name} <span class="pill ${d.health}">${d.health}</span></h2>
    <div class="meta">${caps} · priority=${d.priority} · max_concurrent=${d.max_concurrent} · ${d.endpoint}</div>
    ${d.last_error ? '<div class="section" style="border-color:#da3633;"><h3 style="color:#f85149;">Último erro</h3><div class="err">'+escapeHtml(d.last_error)+'</div></div>' : ''}

    <div class="tabs" id="wd-tabs">
      <button data-tab="overview" class="active" onclick="switchTab('overview')">Overview</button>
      <button data-tab="skill" onclick="switchTab('skill')">SKILL.md</button>
      <button data-tab="recipes" onclick="switchTab('recipes')">Recipes (${(d.used_in_recipes||[]).length})</button>
      <button data-tab="siblings" onclick="switchTab('siblings')">Siblings (${(d.siblings||[]).length})</button>
      <button data-tab="jobs" onclick="switchTab('jobs')">Jobs</button>
    </div>

    <div class="tab-pane active" data-pane="overview">
      <div class="section"><h3>Capabilities</h3>${caps}</div>
      <div class="section"><h3>Endpoint</h3><code>${d.endpoint}</code></div>
      <div class="section"><h3>Stats</h3>
        <div>Jobs em voo agora: <b>${d.in_flight}</b></div>
      </div>
    </div>
    <div class="tab-pane" data-pane="skill">${skillHtml}</div>
    <div class="tab-pane" data-pane="recipes">${recipesHtml}</div>
    <div class="tab-pane" data-pane="siblings">${siblingsHtml}</div>
    <div class="tab-pane" data-pane="jobs">
      <div style="color:#7d8590;font-size:12px;">Selecione um job na coluna do meio para ver detalhes.</div>
    </div>
  `;
}

function switchTab(tab) {
  document.querySelectorAll('#wd-tabs button').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.dataset.pane === tab);
  });
}

// Markdown renderer minimalista (sem dependência externa)
function renderMarkdown(md) {
  if (!md) return '';
  let h = escapeHtml(md);
  // Code blocks ```lang
  h = h.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => `<pre><code>${code}</code></pre>`);
  // Headers
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold / italic
  h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  h = h.replace(/(?<![*\w])\*([^*\n]+?)\*(?![*\w])/g, '<i>$1</i>');
  // Inline code
  h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  // Lists
  h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>[^<]*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>');
  // Tables
  h = h.replace(/(\|.+\|\n\|[-:\s|]+\|\n(?:\|.+\|\n?)+)/g, tbl => {
    const rows = tbl.trim().split('\n').filter(r => !/^\|[-:\s|]+\|$/.test(r));
    if (!rows.length) return tbl;
    const header = rows[0].slice(1, -1).split('|').map(c => `<th>${c.trim()}</th>`).join('');
    const body = rows.slice(1).map(r =>
      '<tr>' + r.slice(1, -1).split('|').map(c => `<td>${c.trim()}</td>`).join('') + '</tr>'
    ).join('');
    return `<table><tr>${header}</tr>${body}</table>`;
  });
  // Newlines → paragraphs
  h = h.split(/\n\n+/).map(p => {
    if (/^<(h\d|ul|ol|pre|table|div)/.test(p.trim())) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).join('');
  return h;
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
  // Backlog #21 — se há worker selecionado, renderiza o job DENTRO da tab "jobs"
  // em vez de sobrescrever o detalhe do worker.
  const jobsPane = document.querySelector('.tab-pane[data-pane="jobs"]');
  const main = jobsPane || document.getElementById('detail');
  if (jobsPane) {
    switchTab('jobs');
  }
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
  const seen = new Set();
  const urls = [];
  const walk = (v) => {
    if (typeof v === 'string' &&
        (v.startsWith('http') || v.startsWith('/artifacts/') || v.startsWith('/s3/') || v.startsWith('file://'))) {
      if (!seen.has(v)) { seen.add(v); urls.push(v); }
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
document.querySelectorAll('[data-sort]').forEach(b => {
  b.classList.toggle('active', b.dataset.sort === workerSort);
});
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

WORKERS_UI_HTML = WORKERS_UI_HTML.replace("</body>", _MEDIA_MODAL_HTML + _UNIVERSAL_MODAL_HTML + "</body>")
