#!/usr/bin/env bash
# scripts/stop-dev.sh — derruba todos os processos em logs/*.pid

set -euo pipefail
cd "$(dirname "$0")/.."

LOG_DIR="logs"
[ -d "$LOG_DIR" ] || { echo "nada pra parar"; exit 0; }

count=0
for pidf in "$LOG_DIR"/*.pid; do
  [ -f "$pidf" ] || continue
  name="$(basename "$pidf" .pid)"
  pid="$(cat "$pidf")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "  ✓ $name (pid $pid)"
    count=$((count + 1))
  else
    echo "  ↻ $name já parado"
  fi
  rm -f "$pidf"
done

echo "parados: $count"
