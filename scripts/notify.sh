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
elif [ -f "$(dirname "$0")/../.env" ]; then
  # prefere o bot dedicado @imkt4bot do proprio imkt4/.env
  IMKT4_ENV="$(dirname "$0")/../.env"
  TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$IMKT4_ENV" | head -1 | cut -d= -f2-)"
  CHAT="$(grep -E '^TELEGRAM_ALLOWED_CHAT_IDS=' "$IMKT4_ENV" | head -1 | cut -d= -f2- | cut -d, -f1)"

  # fallback: admin bot (openpcbot)
  if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
    TOKEN="$(grep -E '^TELEGRAM_ADMIN_BOT_TOKEN=' "$IMKT4_ENV" | head -1 | cut -d= -f2-)"
    CHAT="$(grep -E '^TELEGRAM_ADMIN_CHAT_ID=' "$IMKT4_ENV" | head -1 | cut -d= -f2-)"
  fi
else
  echo "notify: sem IMKT4_NOTIFY_* setado e .env ausente" >&2
  exit 2
fi

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  echo "notify: token ou chat_id vazios" >&2
  exit 3
fi

BODY="[imkt4] ${MSG}"

RESP=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT}" \
  --data-urlencode "text=${BODY}")

OK=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok'))" 2>/dev/null || echo "false")

if [ "$OK" != "True" ]; then
  echo "notify: falhou — $RESP" >&2
  exit 4
fi
echo "notify: enviado"
