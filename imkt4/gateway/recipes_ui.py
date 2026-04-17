"""Recipes Studio — interface dedicada a gerenciar receitas.

Servido em GET /recipes-ui. Single-page:

- Topo: painel com stats (total de receitas, stages, capabilities usadas).
- Lista à esquerda: receitas disponíveis.
- Área principal: detalhe da receita selecionada (YAML + visualização
  dos stages/deps).
- Botão "nova receita" — cria skeleton e abre pra editar.

Reusa endpoints /admin/recipes (com token admin).
Não interfere com a /ui existente.
"""

RECIPES_UI_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>imkt4 · recipes studio</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; background: #0d1117; color: #e6edf3;
         font-family: system-ui, -apple-system, sans-serif; }

  .topbar { background: #161b22; border-bottom: 1px solid #30363d;
            padding: 12px 20px; display: flex; align-items: center; gap: 20px; }
  .topbar h1 { margin: 0; font-size: 18px; }
  .topbar .nav { color: #7d8590; font-size: 13px; }
  .topbar .nav a { color: #7d8590; text-decoration: none; margin-right: 14px; }
  .topbar .nav a:hover { color: #e6edf3; }
  .topbar .nav a.active { color: #1f6feb; font-weight: 600; }
  .auth { margin-left: auto; font-size: 12px; color: #7d8590; }
  .auth button { padding: 4px 10px; font-size: 11px;
                 background: transparent; border: 1px solid #30363d;
                 color: #e6edf3; border-radius: 6px; cursor: pointer; }

  .dashboard { display: grid; grid-template-columns: repeat(4, 1fr);
               gap: 12px; padding: 16px 20px; background: #0d1117;
               border-bottom: 1px solid #30363d; }
  .stat { background: #161b22; border: 1px solid #30363d; padding: 14px;
          border-radius: 8px; }
  .stat .label { color: #7d8590; font-size: 11px; text-transform: uppercase;
                 letter-spacing: 0.5px; }
  .stat .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
  .stat .sub { color: #7d8590; font-size: 11px; margin-top: 4px;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .body { display: grid; grid-template-columns: 280px 1fr;
          gap: 0; height: calc(100vh - 210px); }

  .sidebar { background: #161b22; border-right: 1px solid #30363d;
             overflow-y: auto; }
  .sidebar .header { padding: 14px 16px; display: flex;
                     justify-content: space-between; align-items: center;
                     border-bottom: 1px solid #30363d; }
  .sidebar .header h2 { margin: 0; font-size: 14px; color: #7d8590;
                        text-transform: uppercase; letter-spacing: 0.5px; }
  .sidebar .list { padding: 8px 0; }
  .recipe-row { padding: 10px 16px; cursor: pointer; border-left: 3px solid transparent;
                transition: background 0.1s; }
  .recipe-row:hover { background: #21262d; }
  .recipe-row.active { background: #21262d; border-left-color: #1f6feb; }
  .recipe-row .name { font-weight: 500; font-size: 14px; }
  .recipe-row .meta { color: #7d8590; font-size: 12px; margin-top: 2px; }
  .recipe-row.new { color: #3fb950; font-weight: 500; }

  .main { display: flex; flex-direction: column; overflow: hidden; }
  .main .toolbar { padding: 12px 20px; background: #161b22;
                   border-bottom: 1px solid #30363d;
                   display: flex; gap: 10px; align-items: center; }
  .main .toolbar .title { font-size: 16px; font-weight: 600; }
  .main .toolbar .spacer { flex: 1; }
  .main .content { flex: 1; display: grid; grid-template-columns: 1fr 1fr;
                   gap: 0; overflow: hidden; }
  .main .pane { overflow: auto; padding: 16px 20px; border-right: 1px solid #30363d; }
  .main .pane:last-child { border-right: none; }
  .main .pane h3 { margin: 0 0 10px 0; font-size: 12px; color: #7d8590;
                   text-transform: uppercase; letter-spacing: 0.5px; }

  textarea { width: 100%; height: calc(100% - 30px); min-height: 400px;
             background: #0d1117; color: #e6edf3; border: 1px solid #30363d;
             padding: 12px; border-radius: 6px; resize: none;
             font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px;
             line-height: 1.5; }

  .stage-box { background: #161b22; border: 1px solid #30363d;
               padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; }
  .stage-box .sid { font-weight: 600; font-size: 14px; }
  .stage-box .cap { color: #1f6feb; font-size: 12px; font-family: monospace; }
  .stage-box .deps { color: #7d8590; font-size: 11px; margin-top: 4px; }
  .stage-box .badge { display: inline-block; padding: 1px 6px; border-radius: 3px;
                      font-size: 10px; margin-left: 6px; font-weight: 500; }
  .stage-box .badge.fanout { background: #1f6feb; color: white; }
  .stage-box .badge.approval { background: #9e6a03; color: white; }
  .stage-box .badge.when { background: #30363d; color: #7d8590; }

  button { background: #1f6feb; color: white; border: none; padding: 7px 14px;
           border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
  button:hover { background: #388bfd; }
  button.ghost { background: transparent; border: 1px solid #30363d; color: #e6edf3; }
  button.ghost:hover { background: #21262d; }
  button.danger { background: #da3633; }

  input { background: #0d1117; color: #e6edf3; border: 1px solid #30363d;
          padding: 7px 10px; border-radius: 6px; font-size: 13px; }

  .empty { padding: 40px; text-align: center; color: #7d8590; }
  .status { font-size: 12px; color: #7d8590; margin-left: 10px; }
  .status.ok { color: #3fb950; }
  .status.err { color: #f85149; }
</style>
</head>
<body>

<div class="topbar">
  <h1>imkt4</h1>
  <nav style="display:flex;gap:4px;font-size:13px;">
    <a href="/ui"         style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Workspace</a>
    <a href="/recipes-ui" style="color:#1f6feb;text-decoration:none;padding:6px 12px;border-radius:6px;background:#21262d;font-weight:600;">Receitas</a>
    <a href="/runs-ui"    style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Execuções</a>
    <a href="/admin"      style="color:#7d8590;text-decoration:none;padding:6px 12px;border-radius:6px;">Admin</a>
  </nav>
  <div class="auth">
    <span id="auth-status">sem token</span>
    <button onclick="setToken()">token</button>
  </div>
</div>

<!-- Dashboard -->
<div class="dashboard">
  <div class="stat"><div class="label">Receitas</div>
    <div class="value" id="s-recipes">—</div><div class="sub" id="s-recipes-sub"></div></div>
  <div class="stat"><div class="label">Stages totais</div>
    <div class="value" id="s-stages">—</div><div class="sub" id="s-stages-sub"></div></div>
  <div class="stat"><div class="label">Capabilities únicas</div>
    <div class="value" id="s-caps">—</div><div class="sub" id="s-caps-sub"></div></div>
  <div class="stat"><div class="label">Workers ativos</div>
    <div class="value" id="s-workers">—</div><div class="sub" id="s-workers-sub"></div></div>
</div>

<div class="body">
  <aside class="sidebar">
    <div class="header">
      <h2>Receitas</h2>
      <button onclick="newRecipe()" style="padding: 4px 10px; font-size: 11px;">+ nova</button>
    </div>
    <div class="list" id="recipes-list"></div>
  </aside>

  <section class="main">
    <div class="toolbar">
      <span class="title" id="recipe-title">—</span>
      <span class="status" id="save-status"></span>
      <span class="spacer"></span>
      <button class="ghost" onclick="runRecipe()">▶ Rodar</button>
      <button onclick="saveRecipe()">Salvar</button>
      <button class="danger" onclick="deleteRecipe()" id="del-btn" style="display:none;">excluir</button>
    </div>
    <div class="content">
      <div class="pane">
        <h3>YAML</h3>
        <textarea id="yaml" placeholder="selecione uma receita..."
                  oninput="renderStages()"></textarea>
      </div>
      <div class="pane">
        <h3>Stages</h3>
        <div id="stages"></div>
      </div>
    </div>
  </section>
</div>

<script>
// ── auth ──────────────────────────────────────────────────────
function getToken() { return localStorage.getItem('imkt4_admin_token') || ''; }
function setToken() {
  const t = prompt('Token admin (Bearer):', getToken());
  if (t !== null) {
    localStorage.setItem('imkt4_admin_token', t.trim());
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
  const r = await fetch(url, { ...opts, headers: h });
  if (r.status === 401) alert('Token inválido. Clique em [token].');
  return r;
}

let currentRecipe = null;

// ── dashboard ─────────────────────────────────────────────────
async function loadDashboard() {
  // receitas (endpoint público /recipes — não requer token)
  try {
    const rR = await fetch('/recipes');
    const recipes = await rR.json();
    document.getElementById('s-recipes').textContent = recipes.length;
    document.getElementById('s-recipes-sub').textContent =
      recipes.map(r => r.name).join(', ');

    const allStages = recipes.flatMap(r => r.stages || []);
    document.getElementById('s-stages').textContent = allStages.length;
    const avg = recipes.length ? (allStages.length / recipes.length).toFixed(1) : '0';
    document.getElementById('s-stages-sub').textContent = 'avg ' + avg + ' por receita';

    const caps = new Set(allStages.map(s => s.requires).filter(Boolean));
    document.getElementById('s-caps').textContent = caps.size;
    document.getElementById('s-caps-sub').textContent =
      Array.from(caps).sort().slice(0, 4).join(', ') + (caps.size > 4 ? '…' : '');
  } catch (e) { console.error(e); }

  try {
    const rW = await fetch('/workers');
    const workers = await rW.json();
    const healthy = workers.filter(w => w.health === 'healthy');
    document.getElementById('s-workers').textContent = `${healthy.length}/${workers.length}`;
    document.getElementById('s-workers-sub').textContent =
      healthy.slice(0, 3).map(w => w.name).join(', ') + (healthy.length > 3 ? '…' : '');
  } catch (e) {}
}

// ── lista de receitas ─────────────────────────────────────────
async function loadRecipes() {
  const r = await api('/admin/recipes');
  if (!r.ok) return;
  const names = await r.json();
  const list = document.getElementById('recipes-list');
  list.innerHTML = '';

  // Busca metadata de cada
  const meta = await (await fetch('/recipes')).json();
  const byName = Object.fromEntries(meta.map(m => [m.name, m]));

  names.forEach(name => {
    const m = byName[name];
    const row = document.createElement('div');
    row.className = 'recipe-row';
    row.onclick = () => selectRecipe(name);
    row.innerHTML = `
      <div class="name">${name}</div>
      <div class="meta">${m ? (m.stages.length + ' stages · v' + m.version) : ''}</div>
    `;
    row.dataset.name = name;
    list.appendChild(row);
  });
}

async function selectRecipe(name) {
  currentRecipe = name;
  document.querySelectorAll('.recipe-row').forEach(r => {
    r.classList.toggle('active', r.dataset.name === name);
  });
  document.getElementById('recipe-title').textContent = name;
  document.getElementById('del-btn').style.display = 'inline-block';

  const r = await api('/admin/recipes/' + encodeURIComponent(name));
  if (r.ok) {
    document.getElementById('yaml').value = await r.text();
    renderStages();
  }
}

// ── visualização de stages ────────────────────────────────────
function renderStages() {
  const yaml = document.getElementById('yaml').value;
  const container = document.getElementById('stages');
  container.innerHTML = '';

  // Parser YAML muito simples só pros stages (só precisa pra visual)
  const stages = parseStagesSimple(yaml);
  if (stages.length === 0) {
    container.innerHTML = '<div class="empty">sem stages detectados</div>';
    return;
  }
  stages.forEach(s => {
    const div = document.createElement('div');
    div.className = 'stage-box';
    let badges = '';
    if (s.fanout_over) badges += '<span class="badge fanout">fanout</span>';
    if (s.fanout_over_capabilities) badges += '<span class="badge fanout">fanout-caps</span>';
    if (s.approval && s.approval !== 'none') badges += `<span class="badge approval">${s.approval}</span>`;
    if (s.when) badges += '<span class="badge when">when</span>';
    div.innerHTML = `
      <div class="sid">${s.id}${badges}</div>
      <div class="cap">${s.requires || '(sem capability)'}</div>
      ${s.needs.length ? `<div class="deps">depende de: ${s.needs.join(', ')}</div>` : ''}
    `;
    container.appendChild(div);
  });
}

// Parser ingênuo — funciona pro formato padrão das receitas
function parseStagesSimple(yaml) {
  const lines = yaml.split('\n');
  const out = [];
  let cur = null;
  let inStages = false;
  for (const line of lines) {
    if (/^\s*stages\s*:/.test(line)) { inStages = true; continue; }
    if (!inStages) continue;
    const m = line.match(/^\s*-\s*id:\s*(\S+)/);
    if (m) {
      if (cur) out.push(cur);
      cur = { id: m[1], requires: '', needs: [], fanout_over: null,
              fanout_over_capabilities: null, approval: null, when: null };
      continue;
    }
    if (!cur) continue;
    const keyVal = line.match(/^\s{4,}(\w+):\s*(.*)$/);
    if (!keyVal) continue;
    const [, k, v] = keyVal;
    if (k === 'requires') cur.requires = v.trim();
    else if (k === 'needs') {
      const arr = v.match(/\[(.*)\]/);
      cur.needs = arr ? arr[1].split(',').map(x => x.trim()).filter(Boolean) : [];
    } else if (k === 'fanout_over') cur.fanout_over = v.trim();
    else if (k === 'fanout_over_capabilities') cur.fanout_over_capabilities = v.trim();
    else if (k === 'when') cur.when = v.trim();
    else if (k === 'approval') {
      const mode = v.match(/mode:\s*(\w+)/);
      cur.approval = mode ? mode[1] : 'custom';
    }
  }
  if (cur) out.push(cur);
  return out;
}

// ── salvar / criar / deletar / rodar ─────────────────────────
async function saveRecipe() {
  if (!currentRecipe) return;
  const body = document.getElementById('yaml').value;
  const r = await api('/admin/recipes/' + encodeURIComponent(currentRecipe), {
    method: 'PUT',
    headers: { 'Content-Type': 'text/plain' },
    body,
  });
  const el = document.getElementById('save-status');
  if (r.ok) {
    el.textContent = '✓ salvo';
    el.className = 'status ok';
    setTimeout(() => { el.textContent = ''; }, 2000);
    loadRecipes();
    loadDashboard();
  } else {
    const txt = await r.text();
    el.textContent = '✗ ' + txt.slice(0, 120);
    el.className = 'status err';
  }
}
async function newRecipe() {
  const name = prompt('Nome da nova receita (sem extensão):');
  if (!name) return;
  const skeleton = `name: ${name}\nversion: 1\n\nstages:\n  - id: step1\n    requires: some.capability\n    payload_from:\n      input: $.input.field\n    approval: {mode: none}\n`;
  const r = await api('/admin/recipes/' + encodeURIComponent(name), {
    method: 'PUT',
    headers: { 'Content-Type': 'text/plain' },
    body: skeleton,
  });
  if (r.ok) {
    await loadRecipes();
    await loadDashboard();
    selectRecipe(name);
  } else {
    alert('Falhou: ' + r.status);
  }
}
async function deleteRecipe() {
  if (!currentRecipe) return;
  if (!confirm(`Excluir a receita '${currentRecipe}'?`)) return;
  // Não há endpoint DELETE ainda — avisa.
  alert('Delete via API ainda não implementado. Pra remover, apague o arquivo recipes/' + currentRecipe + '.yaml manualmente e recarregue.');
}
async function runRecipe() {
  if (!currentRecipe) return;
  const input = prompt('Input JSON da receita (deixe {} se não precisa):', '{"brief":"teste"}');
  if (input === null) return;
  let parsed;
  try { parsed = JSON.parse(input); }
  catch (e) { alert('JSON inválido'); return; }
  const r = await fetch('/recipes/' + encodeURIComponent(currentRecipe) + '/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tenant_id: 'inema', user_id: 'nei', input: parsed }),
  });
  if (r.ok) {
    const { run_id } = await r.json();
    window.open('/ui#run=' + run_id, '_blank');
  } else {
    alert('Falhou: ' + r.status);
  }
}

// init
updateAuthStatus();
if (!getToken()) setToken();
loadDashboard();
loadRecipes();
</script>
</body>
</html>
"""
