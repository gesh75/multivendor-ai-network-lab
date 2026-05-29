#!/usr/bin/env bash
# Launch wrapper for the DCN Telegram ChatOps bot (invoked by launchd).
#
# Resolves the src/ dir relative to this script, loads telegram_bot/.env, and
# execs the bot in the project venv. If no token is configured it exits cleanly
# (0) so launchd's KeepAlive/SuccessfulExit=false does NOT crash-loop — the
# service stays dormant until you fill in .env, then `launchctl kickstart` it.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # -> .../src
cd "$SRC_DIR"

ENV_FILE="$SRC_DIR/telegram_bot/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[dcn-telegram-bot] TELEGRAM_BOT_TOKEN not set in $ENV_FILE — not starting (dormant)."
  exit 0
fi

VENV_PY="$SRC_DIR/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  VENV_PY="$(command -v python3)"
fi

echo "[dcn-telegram-bot] starting with $VENV_PY against ${DCN_API_URL:-http://localhost:5757}"
exec "$VENV_PY" -m telegram_bot.bot
