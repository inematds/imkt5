"""Chat Web — interface de conversa com o agent loop.

Servido em GET /chat-ui. Mensagens + input, estilo Telegram/WhatsApp,
mas é outro "canal" (channel=web). Os artefatos gerados por jobs
disparados no chat são renderizados inline (polling /jobs filtrado
por origin_channel_external_id = session_id do chat).
"""

CHAT_UI_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>imkt4 · chat</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: #0d1117; color: #e6edf3;
    font-family: system-ui, -apple-system, sans-serif;
    display: flex; flex-direction: column;
  }

  .topbar { background: #161b22; border-bottom: 1px solid #30363d;
            padding: 12px 20px; display: flex; align-items: center; gap: 20px; }
  .topbar h1 { margin: 0; font-size: 18px; }
  .topbar nav { display: flex; gap: 4px; font-size: 13px; }
  .topbar nav a { color: #7d8590; text-decoration: none;
                  padding: 6px 12px; border-radius: 6px; }
  .topbar nav a.active { color: #1f6feb; background: #21262d; font-weight: 600; }
  .auth { margin-left: auto; font-size: 12px; color: #7d8590;
          display: flex; gap: 8px; align-items: center; }
  .auth button { padding: 4px 10px; font-size: 11px; background: transparent;
                 border: 1px solid #30363d; color: #e6edf3; border-radius: 6px;
                 cursor: pointer; }

  .chat-wrap {
    flex: 1; display: flex; flex-direction: column;
    max-width: 820px; width: 100%; margin: 0 auto;
    padding: 16px; overflow: hidden;
  }

  .messages {
    flex: 1; overflow-y: auto;
    padding: 8px 4px 16px;
    scroll-behavior: smooth;
  }

  .msg { display: flex; margin: 8px 0; gap: 10px; animation: pop 0.2s ease; }
  @keyframes pop { from { transform: translateY(6px); opacity: 0; } to { transform: none; opacity: 1; } }
  .msg.user { flex-direction: row-reverse; }
  .msg .bubble {
    max-width: 75%;
    padding: 10px 14px; border-radius: 14px;
    background: #21262d; color: #e6edf3;
    font-size: 14px; line-height: 1.5;
    word-wrap: break-word; white-space: pre-wrap;
  }
  .msg.user .bubble { background: #1f6feb; color: white; }
  .msg.bot .bubble { background: #21262d; }
  .msg.system .bubble { background: #2d2110; color: #f4ba5a; font-size: 12px;
                        font-style: italic; max-width: 90%; }
  .msg .ts { color: #7d8590; font-size: 10px; margin: 2px 4px; }

  .bubble img { display: block; max-width: 100%; border-radius: 8px; margin: 6px 0; }
  .bubble video { display: block; max-width: 100%; border-radius: 8px; margin: 6px 0; }
  .bubble audio { display: block; width: 100%; margin: 6px 0; }
  .bubble a.file-link { color: #1f6feb; text-decoration: none; font-size: 12px;
                        word-break: break-all; }
  .bubble a.file-link:hover { text-decoration: underline; }
  .job-status { font-size: 11px; color: #7d8590; margin-top: 6px; }
  .job-status.running { color: #1f6feb; }
  .job-status.failed { color: #f85149; }
  .job-status.success { color: #3fb950; }

  .composer {
    display: flex; gap: 8px;
    padding: 12px 0; border-top: 1px solid #30363d;
    background: #0d1117;
  }
  .composer textarea {
    flex: 1; resize: none; min-height: 44px; max-height: 200px;
    background: #161b22; color: #e6edf3;
    border: 1px solid #30363d; border-radius: 8px;
    padding: 10px 14px; font-family: inherit; font-size: 14px;
    outline: none;
  }
  .composer textarea:focus { border-color: #1f6feb; }
  .composer button {
    background: #1f6feb; color: white; border: none; padding: 0 20px;
    border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500;
  }
  .composer button:disabled { opacity: 0.5; cursor: wait; }

  .hint {
    padding: 20px; text-align: center; color: #7d8590; font-size: 13px;
  }
  .session {
    font-size: 11px; color: #7d8590;
    display: flex; gap: 8px; align-items: center;
  }
  .session button {
    padding: 2px 8px; font-size: 10px; background: transparent;
    border: 1px solid #30363d; color: #7d8590; border-radius: 4px;
    cursor: pointer;
  }
  .session button:hover { color: #e6edf3; }
</style>
</head>
<body>

<div class="topbar">
  <h1>imkt4</h1>
  <nav>
    <a href="/ui">Workspace</a>
    <a href="/recipes-ui">Receitas</a>
    <a href="/runs-ui">Execuções</a>
    <a href="/workers-ui">Workers</a>
    <a href="/chat-ui" class="active">Chat</a>
    <a href="/admin">Admin</a>
  </nav>
  <div class="auth">
    <div class="session">
      <span id="session-label">sessão —</span>
      <button onclick="newSession()">nova</button>
    </div>
    <span id="auth-status">sem token</span>
    <button onclick="setToken()">token</button>
  </div>
</div>

<div class="chat-wrap">
  <div class="messages" id="messages">
    <div class="hint">Digite uma mensagem — o agente decide responder direto ou disparar um job/receita.</div>
  </div>
  <div class="composer">
    <textarea id="composer-input" placeholder="Mensagem... (Enter envia · Shift+Enter quebra linha)"
              rows="1"></textarea>
    <button id="send-btn" onclick="send()">Enviar</button>
  </div>
</div>

<script>
// ── token ─────────────────────────────────────────────────────
function getToken() {
  return localStorage.getItem('imkt4_user_token')
      || localStorage.getItem('imkt4_admin_token') || '';
}
function setToken() {
  const t = prompt('Token (Bearer):', getToken());
  if (t !== null) {
    localStorage.setItem('imkt4_user_token', t.trim());
    location.reload();
  }
}
function updateAuthStatus() {
  const t = getToken();
  const el = document.getElementById('auth-status');
  el.textContent = t ? 'auth ' + t.slice(0, 6) + '…' : 'sem token';
  el.style.color = t ? '#3fb950' : '#f85149';
}
async function api(url, opts = {}) {
  const token = getToken();
  const h = { ...(opts.headers || {}) };
  if (token) h['Authorization'] = 'Bearer ' + token;
  return fetch(url, { ...opts, headers: h });
}

// ── session ───────────────────────────────────────────────────
function getSession() {
  let s = localStorage.getItem('imkt4_chat_session');
  if (!s) {
    s = 'chat-' + crypto.randomUUID().slice(0, 8);
    localStorage.setItem('imkt4_chat_session', s);
  }
  return s;
}
function newSession() {
  if (!confirm('Nova sessão? Histórico da conversa atual continua visível mas o agente perde contexto.')) return;
  const s = 'chat-' + crypto.randomUUID().slice(0, 8);
  localStorage.setItem('imkt4_chat_session', s);
  localStorage.removeItem('imkt4_chat_history');
  location.reload();
}
function updateSessionLabel() {
  document.getElementById('session-label').textContent = 'sessão ' + getSession();
}

// ── history (em localStorage pra sobreviver refresh) ──────────
function getHistory() {
  try { return JSON.parse(localStorage.getItem('imkt4_chat_history') || '[]'); }
  catch { return []; }
}
function saveHistory(h) {
  localStorage.setItem('imkt4_chat_history', JSON.stringify(h.slice(-200)));
}

// ── render ────────────────────────────────────────────────────
const ARTIFACT_RE = /(https?:\/\/\S+|\/s3\/\S+|\/artifacts\/\S+|file:\/\/\S+)/g;

function renderAttachments(container, urls) {
  urls.forEach(url => {
    const low = url.toLowerCase();
    let el;
    if (/\.(png|jpg|jpeg|webp|gif)(\?|$)/.test(low)) {
      el = document.createElement('img');
      el.src = url; el.loading = 'lazy';
    } else if (/\.(mp4|webm|mov)(\?|$)/.test(low)) {
      el = document.createElement('video');
      el.src = url; el.controls = true;
    } else if (/\.(mp3|wav|m4a|ogg)(\?|$)/.test(low)) {
      el = document.createElement('audio');
      el.src = url; el.controls = true;
    } else {
      el = document.createElement('a');
      el.href = url; el.target = '_blank'; el.className = 'file-link';
      el.textContent = '🔗 ' + (url.length > 60 ? url.slice(0,30)+'…'+url.slice(-25) : url);
    }
    container.appendChild(el);
  });
}

function addMessage(role, text, opts = {}) {
  const { artifacts = [], persist = true, jobId = null } = opts;
  const ctr = document.getElementById('messages');
  // remove hint se ainda está
  const hint = ctr.querySelector('.hint');
  if (hint) hint.remove();

  const row = document.createElement('div');
  row.className = 'msg ' + role;
  if (jobId) row.dataset.jobId = jobId;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (text) {
    // Extrai URLs do texto pra renderizar como attachments
    const urls = [...new Set((text.match(ARTIFACT_RE) || []))];
    const cleanText = text.replace(ARTIFACT_RE, '').trim();
    if (cleanText) bubble.appendChild(document.createTextNode(cleanText));
    renderAttachments(bubble, urls);
  }
  if (artifacts.length) renderAttachments(bubble, artifacts);

  const ts = document.createElement('div');
  ts.className = 'ts';
  ts.textContent = new Date().toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'});

  row.appendChild(bubble);
  row.appendChild(ts);
  ctr.appendChild(row);
  ctr.scrollTop = ctr.scrollHeight;

  if (persist) {
    const h = getHistory();
    h.push({ role, text, artifacts, ts: Date.now() });
    saveHistory(h);
  }
}

function addJobStatus(row, status) {
  let st = row.querySelector('.job-status');
  if (!st) {
    st = document.createElement('div');
    st.className = 'job-status';
    row.querySelector('.bubble').appendChild(st);
  }
  st.className = 'job-status ' + status;
  st.textContent = ({running:'⏳ processando…', success:'✓ concluído', failed:'✗ falhou'}[status]) || status;
}

function loadHistory() {
  const h = getHistory();
  const ctr = document.getElementById('messages');
  ctr.innerHTML = '';
  if (h.length === 0) {
    ctr.innerHTML = '<div class="hint">Digite uma mensagem — o agente decide responder direto ou disparar um job/receita.</div>';
    return;
  }
  h.forEach(m => addMessage(m.role, m.text, { artifacts: m.artifacts || [], persist: false }));
}

// ── send ──────────────────────────────────────────────────────
async function send() {
  const input = document.getElementById('composer-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  const btn = document.getElementById('send-btn');
  btn.disabled = true;

  addMessage('user', text);

  try {
    const r = await api('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: 'inema',
        user_id: 'web',
        text,
        channel: 'web',
        channel_external_id: getSession(),
      }),
    });
    if (!r.ok) {
      const body = await r.text();
      addMessage('system', '✗ erro ' + r.status + ': ' + body.slice(0, 200));
    } else {
      const data = await r.json();
      addMessage('bot', data.text || '(sem resposta)');
    }
  } catch (e) {
    addMessage('system', '✗ rede: ' + e.message);
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

// ── poll jobs do session pra mostrar artefatos ────────────────
const renderedJobs = new Set();

async function pollJobs() {
  const sess = getSession();
  try {
    const r = await fetch('/jobs?origin_channel=web&origin_external_id='
                          + encodeURIComponent(sess) + '&limit=50');
    if (!r.ok) return;
    const jobs = await r.json();
    // Ordena do mais antigo pro mais novo
    jobs.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    for (const j of jobs) {
      if (renderedJobs.has(j.job_id)) continue;
      if (j.status === 'success' && j.output) {
        const urls = extractArtifactUrls(j.output);
        if (urls.length) {
          addMessage('bot',
            'Gerei pra você (' + (j.capability || j.worker_name) + '):',
            { artifacts: urls });
          renderedJobs.add(j.job_id);
        } else if (j.capability !== 'review.auto') {
          // Só texto simples do output
          const summary = JSON.stringify(j.output).slice(0, 200);
          addMessage('bot', '✓ ' + (j.capability || j.worker_name) + ': ' + summary);
          renderedJobs.add(j.job_id);
        }
      } else if (j.status === 'failed') {
        addMessage('system', '✗ ' + (j.capability || j.worker_name) + ': ' + (j.error || 'falhou').slice(0, 200));
        renderedJobs.add(j.job_id);
      }
    }
  } catch (e) { /* noop */ }
}

function extractArtifactUrls(obj) {
  const urls = [];
  const walk = v => {
    if (typeof v === 'string' &&
        (v.startsWith('http') || v.startsWith('/s3/') || v.startsWith('/artifacts/') || v.startsWith('file://'))) {
      urls.push(v);
    } else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(obj);
  return urls;
}

// ── UX: Enter envia, Shift+Enter quebra linha; auto-resize ────
document.getElementById('composer-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
document.getElementById('composer-input').addEventListener('input', e => {
  e.target.style.height = 'auto';
  e.target.style.height = Math.min(200, e.target.scrollHeight) + 'px';
});

// init
updateAuthStatus();
updateSessionLabel();
loadHistory();
setInterval(pollJobs, 4000);
pollJobs();
</script>
</body>
</html>
"""
