#!/usr/bin/env bash
# scripts/start-dev.sh — sobe gateway + workers em background.
#
# Logs vão pra logs/<servico>.log. PIDs em logs/<servico>.pid.
# Use scripts/stop-dev.sh para parar tudo.
#
# Workers que iniciam:
#   - auto-reviewer (porta 8200) — usa Ollama local (sempre disponível)
#   - research (porta 8100) — usa Tavily (precisa TAVILY_API_KEY)
#   - inemaimg-adapter (porta 8010) — só se INEMAIMG_URL responder
#   - inemavox-adapter (porta 8011) — só se INEMAVOX_URL responder
#
# Gateway na porta 8080 por default (override com GATEWAY_PORT).

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

VENV="$ROOT/.venv/bin/python"
[ -x "$VENV" ] || { echo "venv não encontrado em .venv — rode 'python -m venv .venv && .venv/bin/pip install -e \".[dev]\" pyyaml httpx'"; exit 1; }

# carrega .env pra subprocesses
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^#' .env | grep -v '^$')
  set +a
fi

start_bg() {
  local name="$1"; shift
  local cmd=("$@")
  local logf="$LOG_DIR/$name.log"
  local pidf="$LOG_DIR/$name.pid"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
    echo "  ↻ $name já rodando (pid $(cat "$pidf"))"
    return
  fi
  nohup "${cmd[@]}" >"$logf" 2>&1 &
  echo $! > "$pidf"
  sleep 0.4
  if kill -0 "$(cat "$pidf")" 2>/dev/null; then
    echo "  ✓ $name (pid $(cat "$pidf"), log: $logf)"
  else
    echo "  ✗ $name falhou ao subir — veja $logf"
    tail -5 "$logf" | sed 's/^/    /'
    rm -f "$pidf"
  fi
}

probe() {
  local url="$1"
  curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$url" 2>/dev/null || echo "000"
}

echo "── workers ──────────────────────────────────────────"

start_bg "auto-reviewer" "$VENV" workers/auto-reviewer/server.py

start_bg "research" "$VENV" workers/research/server.py

start_bg "creative-brief" "$VENV" workers/creative-brief/server.py

start_bg "copywriter" "$VENV" workers/copywriter/server.py

# inemaimg-adapter — só se o upstream responder em /health
INEMAIMG_HEALTH_URL="${INEMAIMG_URL:-http://localhost:8000}/health"
if [ "$(probe "$INEMAIMG_HEALTH_URL")" = "200" ]; then
  start_bg "inemaimg-adapter" "$VENV" workers/inemaimg-adapter/server.py
else
  echo "  ⚠ inemaimg upstream não responde em $INEMAIMG_HEALTH_URL — skip"
fi

# inemavox-adapter — inemavox não tem /health; tenta /api/jobs como liveness probe
INEMAVOX_PROBE_URL="${INEMAVOX_URL:-http://localhost:8010}/api/jobs"
INEMAVOX_CODE="$(probe "$INEMAVOX_PROBE_URL")"
if [ "$INEMAVOX_CODE" = "200" ] || [ "$INEMAVOX_CODE" = "404" ]; then
  start_bg "inemavox-adapter" "$VENV" workers/inemavox-adapter/server.py
else
  echo "  ⚠ inemavox upstream não responde em $INEMAVOX_PROBE_URL (got $INEMAVOX_CODE) — skip"
fi

echo
echo "── gateway ──────────────────────────────────────────"
start_bg "gateway" "$VENV" -m imkt4.main

sleep 1.0

GATEWAY_PORT="${GATEWAY_PORT:-8080}"
echo
if [ "$(probe "http://localhost:$GATEWAY_PORT/workers")" = "200" ]; then
  echo "✓ gateway OK em http://localhost:$GATEWAY_PORT"
  echo
  echo "Endpoints úteis:"
  echo "  GET  http://localhost:$GATEWAY_PORT/workers"
  echo "  GET  http://localhost:$GATEWAY_PORT/capabilities"
  echo "  POST http://localhost:$GATEWAY_PORT/jobs"
  echo "  POST http://localhost:$GATEWAY_PORT/recipes/{name}/run"
  echo
  echo "Veja doc/QUICKSTART.md para exemplos de curl."
else
  echo "⚠ gateway não respondeu — veja $LOG_DIR/gateway.log"
fi
