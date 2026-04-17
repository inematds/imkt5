"""UI web single-page do Gateway.

HTML + CSS + JS inline — zero dependências externas, serve direto do
FastAPI. Para interação rápida: chat-like, mostra workers disponíveis,
input de prompt/payload, lista de jobs recentes com auto-refresh.
"""

UI_HTML = r"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>imkt4 · gateway</title>
<style>
:root {
  --bg:#0f1419; --bg2:#1a1f2a; --bg3:#232936;
  --fg:#c9d1d9; --fg2:#8b949e; --accent:#58a6ff; --ok:#3fb950;
  --warn:#d29922; --err:#f85149; --border:#30363d;
}
* { box-sizing:border-box; }
body { margin:0; font:14px/1.45 -apple-system,'Segoe UI',ui-sans-serif,sans-serif;
  background:var(--bg); color:var(--fg); }
header { padding:12px 20px; background:var(--bg2); border-bottom:1px solid var(--border);
  display:flex; gap:16px; align-items:center; }
header h1 { margin:0; font-size:16px; font-weight:600; letter-spacing:.02em; }
header .env { color:var(--fg2); font-size:12px; }
main { display:grid; grid-template-columns: 320px 1fr; height: calc(100vh - 49px); }
aside { background:var(--bg2); border-right:1px solid var(--border); overflow:auto; padding:16px; }
section { padding:16px; overflow:auto; }
h2 { font-size:12px; font-weight:600; text-transform:uppercase; color:var(--fg2);
  letter-spacing:.08em; margin:16px 0 8px; }
h2:first-child { margin-top:0; }
.worker { padding:8px 10px; margin:4px 0; background:var(--bg3); border-radius:6px; font-size:12px;
  border-left:3px solid var(--border); }
.worker.healthy { border-left-color:var(--ok); }
.worker.degraded { border-left-color:var(--warn); }
.worker.down { border-left-color:var(--err); }
.worker .name { font-weight:600; }
.worker .caps { color:var(--fg2); font-size:11px; margin-top:2px; }
.worker .meta { color:var(--fg2); font-size:11px; margin-top:2px; }
form { background:var(--bg2); padding:16px; border-radius:8px; border:1px solid var(--border); }
form label { display:block; font-size:12px; color:var(--fg2); margin:10px 0 4px;
  display:flex; justify-content:space-between; align-items:center; }
form label .hint { color:var(--fg2); font-weight:400; font-size:11px; font-style:italic; }
form select, form input[type=text], form textarea {
  width:100%; background:var(--bg); color:var(--fg); border:1px solid var(--border);
  border-radius:5px; padding:8px 10px; font:inherit;
}
form textarea.code { font-family: ui-monospace,Consolas,monospace; font-size:12px; min-height:80px; resize:vertical; }
form textarea.text { font-size:14px; min-height:60px; resize:vertical; }
form .row { display:flex; gap:10px; align-items:center; }
button { background:var(--accent); color:#fff; border:0; padding:8px 16px; border-radius:5px;
  font:inherit; font-weight:600; cursor:pointer; }
button:hover { filter:brightness(1.15); }
button:disabled { opacity:.5; cursor:not-allowed; }
button.ghost { background:transparent; color:var(--fg2); padding:4px 8px; font-size:11px;
  font-weight:400; border:1px solid var(--border); }
button.ghost:hover { color:var(--fg); background:var(--bg3); }
.jobs { margin-top:16px; }
.job { background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:12px 14px; margin:8px 0; }
.job-head { display:flex; justify-content:space-between; align-items:center; gap:10px; font-size:12px; }
.job-head .cap { color:var(--fg2); }
.status { padding:2px 8px; border-radius:10px; font-size:11px; font-weight:600;
  text-transform:uppercase; letter-spacing:.04em; }
.status.pending, .status.running { background:var(--bg3); color:var(--warn); }
.status.success { background:rgba(63,185,80,.15); color:var(--ok); }
.status.failed  { background:rgba(248,81,73,.15); color:var(--err); }
.job-id { font-family: ui-monospace,monospace; font-size:11px; color:var(--fg2); margin-top:4px; }
.job pre { margin:8px 0 0; background:var(--bg); padding:10px; border-radius:5px;
  font-size:11px; overflow:auto; max-height:240px; white-space:pre-wrap; word-wrap:break-word; }
.job img { max-width:100%; margin-top:10px; border-radius:6px; display:block; }
.job audio { margin-top:10px; width:100%; }
.err { color:var(--err); font-size:12px; margin-top:6px; }
.tabs { display:flex; gap:4px; border-bottom:1px solid var(--border); margin-bottom:12px; }
.tab { padding:8px 14px; cursor:pointer; color:var(--fg2); font-size:13px; border-bottom:2px solid transparent; }
.tab.active { color:var(--fg); border-bottom-color:var(--accent); }
.tab-hint { background:var(--bg2); border-left:3px solid var(--accent); padding:8px 12px;
  margin-bottom:12px; font-size:12px; color:var(--fg2); border-radius:0 4px 4px 0; }
.tab-hint strong { color:var(--fg); }
.advanced { margin-top:10px; border-top:1px dashed var(--border); padding-top:10px; }
.advanced-head { display:flex; justify-content:space-between; align-items:center; cursor:pointer;
  user-select:none; color:var(--fg2); font-size:12px; }
.advanced-head::before { content:"▸ "; margin-right:4px; }
.advanced.open .advanced-head::before { content:"▾ "; }
.advanced-body { display:none; margin-top:8px; }
.advanced.open .advanced-body { display:block; }
.recipe-stages { font-size:11px; color:var(--fg2); margin-top:4px; line-height:1.6; }
.recipe-stages .st { display:inline-block; padding:1px 6px; margin:1px 2px;
  background:var(--bg3); border-radius:3px; color:var(--fg); }
</style>
</head>
<body>

<header style="display:flex;align-items:center;gap:20px;">
  <h1 style="margin:0;">imkt4</h1>
  <nav style="display:flex;gap:4px;font-size:13px;">
    <a href="/ui"         style="color:#1f6feb;text-decoration:none;padding:6px 12px;border-radius:6px;background:var(--bg3);font-weight:600;">Workspace</a>
    <a href="/recipes-ui" style="color:var(--fg2);text-decoration:none;padding:6px 12px;border-radius:6px;">Receitas</a>
    <a href="/runs-ui"    style="color:var(--fg2);text-decoration:none;padding:6px 12px;border-radius:6px;">Execuções</a>
    <a href="/admin"      style="color:var(--fg2);text-decoration:none;padding:6px 12px;border-radius:6px;">Admin</a>
  </nav>
  <span class="env" id="env" style="margin-left:auto;"></span>
</header>

<main>
  <aside>
    <h2>Workers</h2>
    <div id="workers"></div>

    <h2>Capabilities</h2>
    <div id="caps" style="font-size:12px;color:var(--fg2);line-height:1.7;"></div>

    <h2>Recipes</h2>
    <div id="recipes" style="font-size:12px;color:var(--fg2);"></div>
  </aside>

  <section>
    <div class="tabs">
      <div class="tab active" data-tab="job">Novo Job</div>
      <div class="tab" data-tab="recipe">Rodar Receita</div>
    </div>

    <div id="panel-job">
      <div class="tab-hint">
        <strong>Novo Job</strong> = executa UMA capability direto (ex.: gerar imagem, fazer pesquisa, TTS).
        Rápido, sem aprovação, sem composição. Use pra tarefas simples.
      </div>
      <form id="job-form">
        <label>Capability
          <span class="hint" id="cap-hint"></span>
        </label>
        <select name="capability" id="cap-select"></select>

        <label>Mensagem
          <span class="hint" id="msg-hint">digite em português natural</span>
        </label>
        <textarea class="text" id="text-input" placeholder="ex.: um gato persa dormindo num sofá"></textarea>

        <div class="advanced" id="advanced">
          <div class="advanced-head" onclick="toggleAdvanced()">Payload avançado (JSON)</div>
          <div class="advanced-body">
            <textarea class="code" id="payload" rows="6">{}</textarea>
            <div style="color:var(--fg2); font-size:11px; margin-top:4px;">
              Gerado a partir da mensagem acima. Edite aqui pra ter controle total
              (ex.: trocar <code>model</code>, <code>steps</code>, <code>width</code>).
            </div>
          </div>
        </div>

        <div style="margin-top:14px;">
          <button type="submit">Enviar Job</button>
        </div>
      </form>
    </div>

    <div id="panel-recipe" style="display:none;">
      <div class="tab-hint">
        <strong>Rodar Receita</strong> = executa um FLUXO COMPOSTO de vários jobs encadeados
        (ex.: campanha inteira = pesquisa → brief → copy → imagens → vídeo → plataformas).
        Dependências, paralelismo e aprovações vêm declarados no YAML em <code>recipes/</code>.
      </div>
      <form id="recipe-form">
        <label>Receita</label>
        <select name="recipe" id="recipe-select"></select>
        <div class="recipe-stages" id="recipe-stages"></div>

        <label>Input <span id="recipe-mode-label" style="color:var(--fg2);font-weight:normal;">(texto — vira <code>{"brief": ...}</code>)</span></label>
        <textarea class="text" id="recipe-input" rows="5"
          placeholder="ex.: Curso online de produtividade com IA pra empreendedores 30-45 anos. 30 dias para resultados."></textarea>
        <div style="margin-top:6px;font-size:12px;">
          <a href="#" id="recipe-mode-toggle" style="color:var(--fg2);">⚙ modo avançado (JSON)</a>
        </div>

        <div style="margin-top:12px;">
          <button type="submit">Rodar Receita</button>
        </div>
      </form>
    </div>

    <div class="jobs" id="jobs-list"></div>
  </section>
</main>

<script>
const API = window.location.origin;

// ── configuração por capability ────────────────────────────────────
const CAP_CONFIG = {
  "research.market": {
    hint: "busca real no Tavily",
    placeholder: "ex.: tendências café gelado brasil 2026",
    buildPayload: (text) => ({
      queries: [text],
      max_results_per_query: 3,
      depth: "basic",
    }),
  },
  "research.tavily": {
    hint: "alias de research.market",
    placeholder: "ex.: concorrentes cold brew 2026",
    buildPayload: (text) => ({ queries: [text], max_results_per_query: 3 }),
  },
  "image.generation": {
    hint: "gera PNG via inemaimg (flux2-klein/qwen-edit/ernie)",
    placeholder: "ex.: um capivara tomando café gelado na praia",
    buildPayload: (text) => ({
      model: "flux2-klein",
      prompt: text,
      steps: 15,
      width: 512, height: 512,
    }),
  },
  "audio.tts": {
    hint: "gera WAV/MP3 via inemavox",
    placeholder: "ex.: olá, este é um teste",
    buildPayload: (text) => ({ text, engine: "edge", lang: "pt" }),
  },
  "audio.dubbing": {
    hint: "voice clone com áudio de referência (precisa ref_url)",
    placeholder: "ex.: texto a ser dublado",
    buildPayload: (text) => ({
      text, ref_url: "https://exemplo.com/ref.wav",
      engine: "chatterbox", lang: "pt",
    }),
  },
  "audio.transcribe": {
    hint: "Whisper — path de arquivo local",
    placeholder: "ex.: /caminho/pro/video.mp4",
    buildPayload: (text) => ({ input: text, format: "srt" }),
  },
  "review.auto": {
    hint: "LLM decide approved/rejected — cole o texto a revisar",
    placeholder: "ex.: Lançamento do café gelado cremoso, perfeito para o verão.",
    buildPayload: (text) => ({
      criteria: [
        "o texto está em português",
        "o texto tem pelo menos 20 caracteres",
      ],
      artifacts: { text },
    }),
  },
};

// ── state ─────────────────────────────────────────────────────────
let bootstrapped = false;             // já completou o primeiro load?
let advancedEdited = false;           // usuário editou o JSON manualmente?
let currentRecipes = [];

// ── helpers ───────────────────────────────────────────────────────
async function jget(p) { const r = await fetch(API + p); return r.json(); }
async function jpost(p, b) {
  const r = await fetch(API + p, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(b),
  });
  return r.json();
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" })[m]);
}

function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return Math.floor(s) + "s atrás";
  if (s < 3600) return Math.floor(s/60) + "m atrás";
  return Math.floor(s/3600) + "h atrás";
}

// ── payload rebuild ───────────────────────────────────────────────
function rebuildPayload() {
  if (advancedEdited) return;   // usuário tomou controle, respeita
  const cap = document.getElementById("cap-select").value;
  const text = document.getElementById("text-input").value.trim();
  const cfg = CAP_CONFIG[cap];
  const payload = (cfg && text) ? cfg.buildPayload(text) : {};
  document.getElementById("payload").value = JSON.stringify(payload, null, 2);
}

function updateCapHint() {
  const cap = document.getElementById("cap-select").value;
  const cfg = CAP_CONFIG[cap];
  document.getElementById("cap-hint").textContent = cfg ? cfg.hint : "";
  document.getElementById("text-input").placeholder =
    cfg ? cfg.placeholder : "digite sua mensagem...";
}

function toggleAdvanced() {
  document.getElementById("advanced").classList.toggle("open");
}

// ── sidebar ───────────────────────────────────────────────────────
async function loadSidebar() {
  const [workers, caps, recipes] = await Promise.all([
    jget("/workers"), jget("/capabilities"), jget("/recipes"),
  ]);
  currentRecipes = recipes;

  document.getElementById("workers").innerHTML = workers.map(w => `
    <div class="worker ${w.health}">
      <div class="name">${w.name}</div>
      <div class="caps">${w.capabilities.join(", ")}</div>
      <div class="meta">${w.local ? "local" : "remoto"} · prio ${w.priority} · in_flight ${w.in_flight}/${w.max_concurrent}</div>
      ${w.last_error ? `<div class="err">${w.last_error}</div>` : ""}
    </div>`).join("");

  document.getElementById("caps").innerHTML = Object.entries(caps)
    .map(([c, ws]) => `<div><strong>${c}</strong> → ${ws.join(", ")}</div>`).join("");

  document.getElementById("recipes").innerHTML = recipes
    .map(r => `<div><strong>${r.name}</strong> v${r.version} (${r.stages.length} stages)</div>`).join("");

  // popula selects APENAS no primeiro load — não resetar depois
  if (!bootstrapped) {
    const capSel = document.getElementById("cap-select");
    capSel.innerHTML = Object.keys(caps).sort()
      .map(c => `<option value="${c}">${c}</option>`).join("");
    if (Object.keys(caps).includes("image.generation")) {
      capSel.value = "image.generation";
    }

    const recSel = document.getElementById("recipe-select");
    recSel.innerHTML = recipes.map(r => `<option value="${r.name}">${r.name}</option>`).join("");
    renderRecipeStages();

    updateCapHint();
    rebuildPayload();
    bootstrapped = true;
  }

  document.getElementById("env").textContent =
    `${workers.length} workers · ${Object.keys(caps).length} capabilities · ${recipes.length} recipes`;
}

function renderRecipeStages() {
  const name = document.getElementById("recipe-select").value;
  const r = currentRecipes.find(x => x.name === name);
  if (!r) { document.getElementById("recipe-stages").innerHTML = ""; return; }
  document.getElementById("recipe-stages").innerHTML = "Stages: " +
    r.stages.map(s => `<span class="st">${s.id}</span>`).join(" → ");
}

// ── listeners ─────────────────────────────────────────────────────
document.getElementById("cap-select").addEventListener("change", () => {
  advancedEdited = false;          // nova capability = regenera payload do zero
  updateCapHint();
  rebuildPayload();
});

document.getElementById("text-input").addEventListener("input", () => {
  advancedEdited = false;          // digitando novo texto = regenera
  rebuildPayload();
});

document.getElementById("payload").addEventListener("input", () => {
  advancedEdited = true;           // usuário tomou controle do JSON
});

document.getElementById("recipe-select").addEventListener("change", renderRecipeStages);

// ── tabs ──────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    document.getElementById("panel-job").style.display = t.dataset.tab === "job" ? "" : "none";
    document.getElementById("panel-recipe").style.display = t.dataset.tab === "recipe" ? "" : "none";
  });
});

// ── submit job ────────────────────────────────────────────────────
document.getElementById("job-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const capability = document.getElementById("cap-select").value;
  const text = document.getElementById("text-input").value.trim();

  let payload;
  if (advancedEdited) {
    try { payload = JSON.parse(document.getElementById("payload").value); }
    catch (err) { alert("payload JSON inválido: " + err.message); return; }
  } else {
    const cfg = CAP_CONFIG[capability];
    if (!text) { alert("digite uma mensagem ou edite o payload avançado"); return; }
    payload = cfg ? cfg.buildPayload(text) : { text };
  }

  const res = await jpost("/jobs", {
    tenant_id: "demo", user_id: "web",
    capability, payload, origin_channel: "web",
  });
  console.log("job dispatched", res);
  refreshJobs();
});

// modo do input da receita: "text" (default) | "json"
let recipeInputMode = "text";
document.getElementById("recipe-mode-toggle").addEventListener("click", (e) => {
  e.preventDefault();
  const ta = document.getElementById("recipe-input");
  const label = document.getElementById("recipe-mode-label");
  const toggle = document.getElementById("recipe-mode-toggle");
  if (recipeInputMode === "text") {
    recipeInputMode = "json";
    ta.className = "code";
    ta.placeholder = '{"brief": "...", "with_research": false}';
    // se tinha texto, converte em {brief: texto}
    const cur = ta.value.trim();
    if (cur && !cur.startsWith("{")) ta.value = JSON.stringify({brief: cur}, null, 2);
    else if (!cur) ta.value = "{}";
    label.innerHTML = "(JSON bruto)";
    toggle.textContent = "← voltar pra texto simples";
  } else {
    recipeInputMode = "text";
    ta.className = "text";
    ta.placeholder = "ex.: Curso online de produtividade com IA pra empreendedores 30-45 anos. 30 dias para resultados.";
    // se tinha JSON, extrai o brief
    try {
      const j = JSON.parse(ta.value);
      if (j.brief && typeof j.brief === "string") ta.value = j.brief;
      else ta.value = "";
    } catch(e) { /* mantém */ }
    label.innerHTML = '(texto — vira <code>{"brief": ...}</code>)';
    toggle.textContent = "⚙ modo avançado (JSON)";
  }
});

document.getElementById("recipe-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("recipe-select").value;
  const raw = document.getElementById("recipe-input").value.trim();
  let input;
  if (recipeInputMode === "json" || raw.startsWith("{")) {
    try { input = JSON.parse(raw || "{}"); }
    catch (err) { alert("input JSON inválido: " + err.message); return; }
  } else {
    // modo texto — vira {brief: texto}. Vazio → {}
    input = raw ? { brief: raw } : {};
  }
  const res = await jpost(`/recipes/${name}/run`, {
    tenant_id: "demo", user_id: "web", input, origin_channel: "web",
  });
  alert("Receita iniciada: run_id=" + res.run_id + "\nAcompanhe em /runs-ui ou /runs/" + res.run_id);
});

// ── jobs list ─────────────────────────────────────────────────────
function renderJob(j) {
  const out = j.output || {};
  let preview = "";

  const img = out.image_url || out.url;
  if (img && /\.(png|jpe?g|webp)$/i.test(img)) {
    preview += `<img src="${img}" alt="imagem">`;
  }
  const audio = out.audio_url;
  if (audio && /\.(wav|mp3)$/i.test(audio)) {
    preview += `<audio controls src="${audio}"></audio>`;
  }
  if (!preview && (Object.keys(out).length || j.error)) {
    preview = `<pre>${escapeHtml(JSON.stringify(j.error ? {error: j.error} : out, null, 2))}</pre>`;
  }

  return `<div class="job">
    <div class="job-head">
      <div>
        <span class="status ${j.status}">${j.status}</span>
        <span class="cap">${j.capability || j.worker_type || "?"}</span>
      </div>
      <span class="cap">${timeAgo(j.updated_at)}</span>
    </div>
    <div class="job-id">${j.job_id}${j.worker_name ? " · " + j.worker_name : ""}</div>
    ${preview}
  </div>`;
}

async function refreshJobs() {
  const jobs = await jget("/jobs?limit=30");
  document.getElementById("jobs-list").innerHTML = jobs.map(renderJob).join("");
}

// ── boot ──────────────────────────────────────────────────────────
loadSidebar();
refreshJobs();
setInterval(refreshJobs, 2000);
setInterval(loadSidebar, 10000);  // agora não reseta nada (bootstrapped=true)
</script>
</body>
</html>
"""
