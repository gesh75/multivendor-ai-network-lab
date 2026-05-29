#!/usr/bin/env bash
# Install (or reinstall) the DCN Telegram ChatOps bot as a launchd user agent.
#
#   ./telegram_bot/install_launchd.sh
#
# Creates src/.venv (if absent) with the bot's deps, renders the plist from the
# template, and bootstraps the agent. Idempotent — safe to re-run. Uninstall with:
#   launchctl bootout gui/$(id -u)/com.gesh.dcn-telegram-bot
#   rm ~/Library/LaunchAgents/com.gesh.dcn-telegram-bot.plist
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # -> .../src
LABEL="com.gesh.dcn-telegram-bot"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
PLIST="$LA_DIR/$LABEL.plist"
TEMPLATE="$SRC_DIR/telegram_bot/$LABEL.plist.template"
UID_NUM="$(id -u)"

mkdir -p "$LA_DIR" "$LOG_DIR"

# 1. Ensure a venv with the bot's deps exists.
if [ ! -x "$SRC_DIR/.venv/bin/python" ]; then
  echo "[install] creating venv at $SRC_DIR/.venv"
  python3 -m venv "$SRC_DIR/.venv"
fi
echo "[install] installing deps from telegram_bot/requirements.txt"
"$SRC_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$SRC_DIR/.venv/bin/python" -m pip install -q -r "$SRC_DIR/telegram_bot/requirements.txt"

# 2. Render the plist from the template (absolute paths for this machine).
sed -e "s|__SRC_DIR__|$SRC_DIR|g" -e "s|__LOG_DIR__|$LOG_DIR|g" "$TEMPLATE" > "$PLIST"
echo "[install] wrote $PLIST"

# 3. (Re)bootstrap the agent.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL"
echo "[install] bootstrapped $LABEL"

echo
echo "Next:"
echo "  1. edit $SRC_DIR/telegram_bot/.env  (TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS)"
echo "  2. launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo "  logs: $LOG_DIR/dcn-telegram-bot.{out,err}.log"
