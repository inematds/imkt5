#!/usr/bin/env bash
# scripts/notify.sh — envia notificação pro Telegram do usuário.
#
# Uso:
#   ./scripts/notify.sh "texto da mensagem"
#   echo "texto" | ./scripts/notify.sh
#
# Lê credenciais de:
#   1. $IMKT4_NOTIFY_BOT_TOKEN + $IMKT4_NOTIFY_CHAT_ID (se setado)
#   2. .env do openpcbot (default — bot pessoal, não rouba msgs do timesmkt3)
#
# Usa parse_mode=Markdown, prefixa [imkt4] pra distinguir na timeline.

set -euo pipefail

MSG="${1:-}"
if [ -z "$MSG" ] && [ ! -t 0 ]; then
  MSG="$(cat)"
fi

if [ -z "$MSG" ]; then
  echo "usage: $0 <text>   ou   echo <text> | $0" >&2
  exit 1
fi

if [ -n "${IMKT4_NOTIFY_BOT_TOKEN:-}" ] && [ -n "${IMKT4_NOTIFY_CHAT_ID:-}" ]; then
  TOKEN="$IMKT4_NOTIFY_BOT_TOKEN"
  CHAT="$IMKT4_NOTIFY_CHAT_ID"
else
  # fallback: openpcbot (bot pessoal)
  OPENPC_ENV="/home/nmaldaner/projetos/openpcbot/.env"
  if [ ! -f "$OPENPC_ENV" ]; then
    echo "notify: sem IMKT4_NOTIFY_* setado e openpcbot/.env ausente" >&2
    exit 2
  fi
  TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$OPENPC_ENV" | head -1 | cut -d= -f2-)"
  CHAT="$(grep -E '^ALLOWED_CHAT_ID=' "$OPENPC_ENV" | head -1 | cut -d= -f2-)"
fi

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  echo "notify: token ou chat_id vazios" >&2
  exit 3
fi

BODY="*\[imkt4\]* ${MSG}"

RESP=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT}" \
  -d "parse_mode=Markdown" \
  --data-urlencode "text=${BODY}")

OK=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok'))" 2>/dev/null || echo "false")

if [ "$OK" != "True" ]; then
  echo "notify: falhou — $RESP" >&2
  exit 4
fi
echo "notify: enviado"
