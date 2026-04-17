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
form label { display:block; font-size:12px; color:var(--fg2); margin:8px 0 4px; }
form select, form input[type=text], form textarea {
  width:100%; background:var(--bg); color:var(--fg); border:1px solid var(--border);
  border-radius:5px; padding:8px 10px; font:inherit;
}
form textarea { font-family: ui-monospace,Consolas,monospace; font-size:12px; min-height:80px; resize:vertical; }
form .row { display:flex; gap:10px; }
form .row > * { flex:1; }
button { background:var(--accent); color:#fff; border:0; padding:8px 16px; border-radius:5px;
  font:inherit; font-weight:600; cursor:pointer; }
button:hover { filter:brightness(1.15); }
button:disabled { opacity:.5; cursor:not-allowed; }
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
.examples { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
.examples button { background:var(--bg3); color:var(--fg2); font-size:11px; font-weight:400;
  padding:3px 8px; }
.examples button:hover { color:var(--fg); }
.tabs { display:flex; gap:4px; border-bottom:1px solid var(--border); margin-bottom:12px; }
.tab { padding:8px 14px; cursor:pointer; color:var(--fg2); font-size:13px; border-bottom:2px solid transparent; }
.tab.active { color:var(--fg); border-bottom-color:var(--accent); }
.hint { color:var(--fg2); font-size:11px; margin-top:6px; font-style:italic; }
</style>
</head>
<body>

<header>
  <h1>imkt4 · gateway</h1>
  <span class="env" id="env"></span>
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
      <form id="job-form">
        <label>Capability</label>
        <select name="capability" id="cap-select"></select>

        <label>Payload (JSON)</label>
        <textarea name="payload" id="payload" rows="6">{}</textarea>
        <div class="examples" id="examples"></div>

        <div style="margin-top:12px;">
          <button type="submit">Enviar Job</button>
        </div>
      </form>
    </div>

    <div id="panel-recipe" style="display:none;">
      <form id="recipe-form">
        <label>Receita</label>
        <select name="recipe" id="recipe-select"></select>

        <label>Input (JSON)</label>
        <textarea name="input" id="recipe-input" rows="6">{}</textarea>

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

// ── examples per capability ────────────────────────────────────────
const EXAMPLES = {
  "research.market": {
    "queries": ["tendências café gelado brasil 2026"],
    "max_results_per_query": 3,
  },
  "image.generation": {
    "model": "flux2-klein",
    "prompt": "a happy capybara sipping iced coffee on a sunny beach",
    "steps": 15, "width": 512, "height": 512,
  },
  "audio.tts": {
    "text": "Olá, este é um teste do imkt4.",
    "engine": "edge", "lang": "pt",
  },
  "review.auto": {
    "criteria": ["texto em português", "menciona café"],
    "artifacts": {"text": "Lançamento do café gelado cremoso."},
  },
};

// ── helpers ────────────────────────────────────────────────────────
async function jget(p) { const r = await fetch(API + p); return r.json(); }
async function jpost(p, b) {
  const r = await fetch(API + p, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(b),
  });
  return r.json();
}

// ── sidebar: workers, caps, recipes ────────────────────────────────
async function loadSidebar() {
  const [workers, caps, recipes] = await Promise.all([
    jget("/workers"), jget("/capabilities"), jget("/recipes"),
  ]);

  document.getElementById("workers").innerHTML = workers.map(w => `
    <div class="worker ${w.health}">
      <div class="name">${w.name}</div>
      <div class="caps">${w.capabilities.join(", ")}</div>
      <div class="meta">${w.local ? "local" : "remoto"} · prio ${w.priority} · in_flight ${w.in_flight}/${w.max_concurrent}</div>
      ${w.last_error ? `<div class="err">${w.last_error}</div>` : ""}
    </div>`).join("");

  document.getElementById("caps").innerHTML = Object.entries(caps)
    .map(([c, ws]) => `<div><strong>${c}</strong> → ${ws.join(", ")}</div>`)
    .join("");

  document.getElementById("recipes").innerHTML = recipes
    .map(r => `<div><strong>${r.name}</strong> v${r.version} (${r.stages.length} stages)</div>`)
    .join("");

  // preenche selects
  const capSel = document.getElementById("cap-select");
  capSel.innerHTML = Object.keys(caps).sort()
    .map(c => `<option value="${c}">${c}</option>`).join("");
  capSel.value = "research.market";
  updateExample();

  const recSel = document.getElementById("recipe-select");
  recSel.innerHTML = recipes.map(r => `<option value="${r.name}">${r.name}</option>`).join("");

  document.getElementById("env").textContent =
    `${workers.length} workers · ${Object.keys(caps).length} capabilities · ${recipes.length} recipes`;
}

function updateExample() {
  const cap = document.getElementById("cap-select").value;
  const ex = EXAMPLES[cap];
  if (ex) document.getElementById("payload").value = JSON.stringify(ex, null, 2);
  else    document.getElementById("payload").value = "{}";
}
document.getElementById("cap-select").addEventListener("change", updateExample);

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
  let payload;
  try { payload = JSON.parse(document.getElementById("payload").value); }
  catch (err) { alert("payload não é JSON válido: " + err.message); return; }

  const body = {
    tenant_id: "demo", user_id: "web",
    capability, payload,
    origin_channel: "web",
  };
  const res = await jpost("/jobs", body);
  console.log("job dispatched", res);
  refreshJobs();
});

document.getElementById("recipe-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("recipe-select").value;
  let input;
  try { input = JSON.parse(document.getElementById("recipe-input").value || "{}"); }
  catch (err) { alert("input não é JSON válido: " + err.message); return; }
  const res = await jpost(`/recipes/${name}/run`, {
    tenant_id: "demo", user_id: "web", input, origin_channel: "web",
  });
  console.log("recipe run", res);
  alert("Receita iniciada: run_id=" + res.run_id + "\nVeja console/API: GET /runs/" + res.run_id);
});

// ── jobs panel ────────────────────────────────────────────────────
function renderJob(j) {
  const out = j.output || {};
  let preview = "";

  // imagem
  const img = out.image_url || out.url;
  if (img && (img.endsWith(".png") || img.endsWith(".jpg") || img.endsWith(".jpeg") || img.endsWith(".webp"))) {
    preview += `<img src="${img}" alt="imagem">`;
  }
  // áudio
  const audio = out.audio_url;
  if (audio && (audio.endsWith(".wav") || audio.endsWith(".mp3"))) {
    preview += `<audio controls src="${audio}"></audio>`;
  }
  // genérico JSON
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

function escapeHtml(s) { return s.replace(/[&<>"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" })[m]); }

function timeAgo(iso) {
  const dt = new Date(iso);
  const s = (Date.now() - dt.getTime()) / 1000;
  if (s < 60) return Math.floor(s) + "s atrás";
  if (s < 3600) return Math.floor(s/60) + "m atrás";
  return Math.floor(s/3600) + "h atrás";
}

async function refreshJobs() {
  const jobs = await jget("/jobs?limit=30");
  document.getElementById("jobs-list").innerHTML = jobs.map(renderJob).join("");
}

// ── boot ──────────────────────────────────────────────────────────
loadSidebar();
refreshJobs();
setInterval(refreshJobs, 2000);
setInterval(loadSidebar, 10000);
</script>
</body>
</html>
"""
