"""Admin UI — editor de config/workers/recipes + audit viewer.

Servido em GET /admin. Single-page com 4 abas:

  - Config: edita config/defaults.yaml e profiles/<tenant>/config.yaml
  - Workers: lista + registra novos (via scripts/new-worker.sh).
  - Recipes: lista + editor textual YAML.
  - Audit: visualiza logs recentes.

Tudo textual (YAML/JSON). Editor visual drag-and-drop (E#19) fica
pra uma iteração separada — requer libs maiores (react-flow etc).
"""

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>imkt4 admin</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; margin: 0;
         background: #0d1117; color: #e6edf3; }
  .topbar { background: #161b22; padding: 10px 20px; border-bottom: 1px solid #30363d;
            display: flex; gap: 16px; align-items: center; }
  .topbar h1 { margin: 0; font-size: 18px; font-weight: 600; }
  .tabs { display: flex; gap: 4px; }
  .tab { padding: 6px 14px; cursor: pointer; border-radius: 6px;
         color: #7d8590; background: transparent; border: none; font-size: 14px; }
  .tab:hover { background: #21262d; color: #e6edf3; }
  .tab.active { background: #1f6feb; color: white; }
  .content { padding: 20px; max-width: 1200px; margin: 0 auto; }
  .panel { display: none; }
  .panel.active { display: block; }

  h2 { margin-top: 0; color: #e6edf3; font-size: 20px; }
  textarea, input, select {
    background: #0d1117; color: #e6edf3; border: 1px solid #30363d;
    padding: 8px; border-radius: 6px; font-family: ui-monospace, monospace;
    font-size: 13px; width: 100%;
  }
  textarea { min-height: 400px; resize: vertical; }
  button { background: #1f6feb; color: white; border: none; padding: 8px 16px;
           border-radius: 6px; cursor: pointer; font-size: 14px; }
  button:hover { background: #388bfd; }
  button.danger { background: #da3633; }
  button.ghost { background: transparent; border: 1px solid #30363d; color: #e6edf3; }
  .row { display: flex; gap: 10px; align-items: center; margin: 10px 0; }
  .grid { display: grid; gap: 10px; }

  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #30363d;
           font-size: 13px; }
  th { background: #161b22; font-weight: 600; color: #7d8590; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 500; }
  .pill.healthy { background: #238636; color: white; }
  .pill.degraded, .pill.pending { background: #9e6a03; color: white; }
  .pill.unhealthy, .pill.failed { background: #da3633; color: white; }
  .pill.success { background: #238636; color: white; }
  .pill.running { background: #1f6feb; color: white; }
  .pill.skipped { background: #30363d; color: #7d8590; }

  .status { padding: 10px; margin: 10px 0; border-radius: 6px; font-size: 13px; }
  .status.ok { background: #12361e; color: #3fb950; }
  .status.err { background: #3b1519; color: #f85149; }

  pre { background: #161b22; padding: 12px; border-radius: 6px; overflow-x: auto;
        font-size: 12px; }
</style>
</head>
<body>

<div class="topbar">
  <h1>imkt4 admin</h1>
  <div class="tabs">
    <button class="tab active" onclick="showTab('config')">Config</button>
    <button class="tab" onclick="showTab('workers')">Workers</button>
    <button class="tab" onclick="showTab('recipes')">Recipes</button>
    <button class="tab" onclick="showTab('channels')">Canais</button>
    <button class="tab" onclick="showTab('audit')">Audit</button>
  </div>
  <div style="margin-left:auto;font-size:12px;color:#7d8590;">
    <span id="auth-status">sem token</span>
    <button class="ghost" onclick="setToken()" style="padding:4px 10px;font-size:11px;">token</button>
  </div>
</div>

<div class="content">

  <!-- CONFIG -->
  <div class="panel active" id="panel-config">
    <h2>Config defaults (global)</h2>
    <p style="color:#7d8590;font-size:13px;">
      Edita <code>config/defaults.yaml</code>. Reinício do gateway necessário pra aplicar.
    </p>
    <textarea id="cfg-global" placeholder="carregando..."></textarea>
    <div class="row">
      <button onclick="saveConfig('global')">Salvar</button>
      <button class="ghost" onclick="loadConfig('global')">Recarregar</button>
      <span id="cfg-status"></span>
    </div>

    <h2 style="margin-top:40px;">Config por tenant</h2>
    <div class="row">
      <input id="tenant-id" placeholder="inema" style="max-width:300px;">
      <button class="ghost" onclick="loadConfig('tenant')">Carregar</button>
    </div>
    <textarea id="cfg-tenant" placeholder="selecione um tenant e clique carregar..."></textarea>
    <div class="row">
      <button onclick="saveConfig('tenant')">Salvar</button>
    </div>
  </div>

  <!-- WORKERS -->
  <div class="panel" id="panel-workers">
    <h2>Workers registrados</h2>
    <table>
      <thead><tr>
        <th>Nome</th><th>Capabilities</th><th>Endpoint</th>
        <th>Health</th><th>In-flight</th>
      </tr></thead>
      <tbody id="workers-tbody"></tbody>
    </table>
    <button class="ghost" onclick="loadWorkers()" style="margin-top:10px;">Atualizar</button>

    <h2 style="margin-top:30px;">Registrar novo (texto)</h2>
    <p style="color:#7d8590;font-size:13px;">
      Adiciona entrada em <code>config/workers.yaml</code>. Pra criar o código do worker,
      use <code>scripts/new-worker.sh &lt;nome&gt; &lt;capability&gt;</code> no shell.
    </p>
    <textarea id="new-worker-yaml" rows="8" placeholder='- name: meu-worker
  capabilities: [cap.exemplo]
  endpoint: http://localhost:8110
  local: true
  priority: 50
  timeout_seconds: 120
  max_concurrent: 2'></textarea>
    <div class="row">
      <button onclick="appendWorker()">Adicionar ao workers.yaml</button>
    </div>
  </div>

  <!-- RECIPES -->
  <div class="panel" id="panel-recipes">
    <h2>Recipes</h2>
    <div class="row">
      <select id="recipe-select" style="max-width:400px;" onchange="loadRecipe()"></select>
      <button class="ghost" onclick="loadRecipes()">Atualizar lista</button>
    </div>
    <textarea id="recipe-yaml" placeholder="selecione uma receita..."></textarea>
    <div class="row">
      <button onclick="saveRecipe()">Salvar</button>
      <span id="recipe-status"></span>
    </div>

    <h2 style="margin-top:40px;">Nova receita</h2>
    <input id="new-recipe-name" placeholder="nome-da-receita" style="max-width:400px;">
    <div class="row"><button onclick="newRecipe()">Criar skeleton</button></div>
  </div>

  <!-- CHANNELS -->
  <div class="panel" id="panel-channels">
    <h2>Canais autorizados</h2>
    <p style="color:#7d8590;font-size:13px;">
      Lista branca de chats por canal (Telegram, WhatsApp). Cada linha
      mapeia um <code>external_id</code> (chat_id do Telegram, número do
      WhatsApp) pra um <code>tenant_id</code> + <code>user_id</code>.
      Adicionar ou remover aqui aplica imediatamente — sem restart.
    </p>
    <table>
      <thead><tr>
        <th>Kind</th><th>External ID</th><th>Tenant</th><th>User</th>
        <th>Criado</th><th></th>
      </tr></thead>
      <tbody id="channels-tbody"></tbody>
    </table>
    <button class="ghost" onclick="loadChannels()" style="margin-top:10px;">Atualizar</button>

    <h2 style="margin-top:30px;">Adicionar binding</h2>
    <div class="grid" style="grid-template-columns: 120px 1fr 1fr 1fr auto; gap:10px; max-width:900px;">
      <select id="ch-kind">
        <option value="telegram">telegram</option>
        <option value="whatsapp">whatsapp</option>
        <option value="web">web</option>
      </select>
      <input id="ch-external" placeholder="external_id (chat_id, phone)">
      <input id="ch-tenant" placeholder="tenant_id (ex: inema)">
      <input id="ch-user" placeholder="user_id (ex: nei)">
      <button onclick="addChannel()">Adicionar</button>
    </div>
    <span id="ch-status"></span>
  </div>

  <!-- AUDIT -->
  <div class="panel" id="panel-audit">
    <h2>Audit log</h2>
    <div class="row">
      <input id="audit-tenant" placeholder="filtrar por tenant_id (opcional)" style="max-width:300px;">
      <input id="audit-limit" value="50" type="number" style="max-width:80px;">
      <button class="ghost" onclick="loadAudit()">Carregar</button>
    </div>
    <table>
      <thead><tr>
        <th>ts</th><th>tenant</th><th>user</th><th>event</th><th>detail</th>
      </tr></thead>
      <tbody id="audit-tbody"></tbody>
    </table>
  </div>

</div>

<script>
// ── token + fetch wrapper ─────────────────────────────────────
function getToken() {
  return localStorage.getItem('imkt4_admin_token') || '';
}
function setToken() {
  const cur = getToken();
  const t = prompt('Token admin (Bearer):', cur);
  if (t !== null) {
    localStorage.setItem('imkt4_admin_token', t.trim());
    updateAuthStatus();
    location.reload();
  }
}
function updateAuthStatus() {
  const t = getToken();
  const el = document.getElementById('auth-status');
  el.textContent = t ? 'autenticado (' + t.slice(0, 6) + '…)' : 'sem token';
  el.style.color = t ? '#3fb950' : '#f85149';
}
async function api(url, opts = {}) {
  const token = getToken();
  const h = { ...(opts.headers || {}) };
  if (token) h['Authorization'] = 'Bearer ' + token;
  const r = await api(url, { ...opts, headers: h });
  if (r.status === 401) {
    alert('Token inválido/ausente. Clique em [token] no topo pra configurar.');
  } else if (r.status === 403) {
    alert('Sem permissão (403).');
  }
  return r;
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'workers') loadWorkers();
  if (name === 'recipes') loadRecipes();
  if (name === 'audit') loadAudit();
  if (name === 'config') loadConfig('global');
  if (name === 'channels') loadChannels();
}

// ── CONFIG ────────────────────────────────────────────────────
async function loadConfig(scope) {
  const tenant = document.getElementById('tenant-id').value || '';
  const url = scope === 'global'
    ? '/admin/config/defaults'
    : '/admin/config/tenant/' + encodeURIComponent(tenant);
  const r = await api(url);
  if (!r.ok) {
    setStatus('cfg-status', 'err', 'erro: ' + r.status);
    return;
  }
  const txt = await r.text();
  const target = scope === 'global' ? 'cfg-global' : 'cfg-tenant';
  document.getElementById(target).value = txt;
  setStatus('cfg-status', 'ok', 'carregado');
}

async function saveConfig(scope) {
  const tenant = document.getElementById('tenant-id').value || '';
  const url = scope === 'global'
    ? '/admin/config/defaults'
    : '/admin/config/tenant/' + encodeURIComponent(tenant);
  const content = scope === 'global'
    ? document.getElementById('cfg-global').value
    : document.getElementById('cfg-tenant').value;
  const r = await api(url, { method: 'PUT', headers: {'Content-Type':'text/plain'}, body: content });
  if (r.ok) setStatus('cfg-status', 'ok', 'salvo');
  else setStatus('cfg-status', 'err', 'falhou: ' + r.status);
}

// ── WORKERS ───────────────────────────────────────────────────
async function loadWorkers() {
  const r = await api('/workers');
  const data = await r.json();
  const tbody = document.getElementById('workers-tbody');
  tbody.innerHTML = '';
  data.forEach(w => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${w.name}</b></td>
      <td><code>${w.capabilities.join(', ')}</code></td>
      <td><code>${w.endpoint}</code></td>
      <td><span class="pill ${w.health}">${w.health}</span></td>
      <td>${w.in_flight}/${w.max_concurrent}</td>
    `;
    tbody.appendChild(tr);
  });
}
async function appendWorker() {
  const y = document.getElementById('new-worker-yaml').value.trim();
  if (!y) return;
  const r = await api('/admin/workers/append', { method: 'POST', headers: {'Content-Type':'text/plain'}, body: y });
  if (r.ok) {
    alert('worker adicionado ao workers.yaml — reinicie pra aplicar');
    document.getElementById('new-worker-yaml').value = '';
  } else {
    alert('falhou: ' + r.status);
  }
}

// ── RECIPES ───────────────────────────────────────────────────
async function loadRecipes() {
  const r = await api('/admin/recipes');
  const names = await r.json();
  const sel = document.getElementById('recipe-select');
  sel.innerHTML = '<option value="">-- selecione --</option>';
  names.forEach(n => {
    const opt = document.createElement('option');
    opt.value = n; opt.textContent = n;
    sel.appendChild(opt);
  });
}
async function loadRecipe() {
  const name = document.getElementById('recipe-select').value;
  if (!name) return;
  const r = await api('/admin/recipes/' + encodeURIComponent(name));
  const txt = await r.text();
  document.getElementById('recipe-yaml').value = txt;
}
async function saveRecipe() {
  const name = document.getElementById('recipe-select').value;
  if (!name) return;
  const content = document.getElementById('recipe-yaml').value;
  const r = await api('/admin/recipes/' + encodeURIComponent(name), {
    method: 'PUT', headers: {'Content-Type':'text/plain'}, body: content
  });
  if (r.ok) setStatus('recipe-status', 'ok', 'salvo — reinicie pra aplicar');
  else setStatus('recipe-status', 'err', 'falhou: ' + r.status);
}
async function newRecipe() {
  const n = document.getElementById('new-recipe-name').value.trim();
  if (!n) return;
  const skeleton = `name: ${n}\nversion: 1\n\nstages:\n  - id: step1\n    requires: some.capability\n    payload_from:\n      input: $.input.some_field\n    approval: {mode: none}\n`;
  const r = await api('/admin/recipes/' + encodeURIComponent(n), {
    method: 'PUT', headers: {'Content-Type':'text/plain'}, body: skeleton
  });
  if (r.ok) {
    await loadRecipes();
    document.getElementById('recipe-select').value = n;
    await loadRecipe();
  } else {
    alert('falhou: ' + r.status);
  }
}

// ── CHANNELS ──────────────────────────────────────────────────
async function loadChannels() {
  const r = await api('/admin/channels');
  if (!r.ok) return;
  const rows = await r.json();
  const tbody = document.getElementById('channels-tbody');
  tbody.innerHTML = '';
  rows.forEach(ch => {
    const tr = document.createElement('tr');
    const created = (ch.created_at || '').toString().slice(0,19).replace('T',' ');
    tr.innerHTML = `
      <td><code>${ch.kind}</code></td>
      <td><code>${ch.external_id}</code></td>
      <td>${ch.tenant_id}</td>
      <td>${ch.user_id || ''}</td>
      <td style="color:#7d8590;">${created}</td>
      <td><button class="danger" style="padding:2px 10px;font-size:11px;"
          onclick="delChannel('${ch.kind}', '${ch.external_id}')">x</button></td>
    `;
    tbody.appendChild(tr);
  });
}
async function addChannel() {
  const body = {
    kind: document.getElementById('ch-kind').value,
    external_id: document.getElementById('ch-external').value.trim(),
    tenant_id: document.getElementById('ch-tenant').value.trim(),
    user_id: document.getElementById('ch-user').value.trim(),
  };
  if (!body.external_id || !body.tenant_id) {
    setStatus('ch-status', 'err', 'external_id e tenant_id obrigatórios'); return;
  }
  const r = await api('/admin/channels', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) {
    setStatus('ch-status', 'ok', 'adicionado');
    document.getElementById('ch-external').value = '';
    document.getElementById('ch-user').value = '';
    loadChannels();
  } else {
    const txt = await r.text();
    setStatus('ch-status', 'err', 'falhou: ' + txt.slice(0,100));
  }
}
async function delChannel(kind, externalId) {
  if (!confirm(`Remover binding ${kind}:${externalId}?`)) return;
  const r = await api('/admin/channels/' + kind + '/' + encodeURIComponent(externalId),
                     { method: 'DELETE' });
  if (r.ok) loadChannels();
  else alert('falhou: ' + r.status);
}

// ── AUDIT ─────────────────────────────────────────────────────
async function loadAudit() {
  const tenant = document.getElementById('audit-tenant').value.trim();
  const limit = document.getElementById('audit-limit').value || '50';
  let url = '/audit?limit=' + limit;
  if (tenant) url += '&tenant_id=' + encodeURIComponent(tenant);
  const r = await api(url);
  const rows = await r.json();
  const tbody = document.getElementById('audit-tbody');
  tbody.innerHTML = '';
  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="white-space:nowrap;">${(row.created_at||row.ts||'').slice(0,19).replace('T',' ')}</td>
      <td>${row.tenant_id||row.actor_tenant||''}</td>
      <td>${row.user_id||row.actor_user||''}</td>
      <td>${row.event_type||row.action||''}</td>
      <td><code>${JSON.stringify(row.details||row.detail||{})}</code></td>
    `;
    tbody.appendChild(tr);
  });
}

function setStatus(id, kind, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'status ' + kind;
  setTimeout(() => { el.textContent = ''; el.className = ''; }, 3000);
}

// init
updateAuthStatus();
if (!getToken()) setToken();
loadConfig('global');
</script>
</body>
</html>
"""
