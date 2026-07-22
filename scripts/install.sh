#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PLUGIN_DEST="${HERMES_HOME:-$HOME/.hermes}/plugins/bitzybridge-ag"
SKILL_DEST="${HERMES_HOME:-$HOME/.hermes}/skills/automation/bitzybridge-ag"
CONFIG_DIR="$HOME/.config/bitzybridge-ag"
ENV_FILE="$CONFIG_DIR/env"
SERVICE_DEST="$HOME/.config/systemd/user/bitzybridge-ag.service"
STATE_DIR="$HOME/.cache/bitzybridge-ag"
BACKUP_ROOT="$HOME/.local/share/bitzybridge-ag/backups"
VENV_DIR="$HOME/.local/share/bitzybridge-ag/venv"
PYTHON="$VENV_DIR/bin/python"
STAMP=$(date +%Y%m%d_%H%M%S_%N)
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
PLUGIN_BACKED_UP=0
PLUGIN_INSTALLED=0
SKILL_BACKED_UP=0
SKILL_INSTALLED=0
SERVICE_BACKED_UP=0
SERVICE_INSTALLED=0

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

rollback_on_error() {
  local status=$?
  if ((status != 0)); then
    set +e
    mkdir -p "$BACKUP_DIR"
    if ((PLUGIN_BACKED_UP || PLUGIN_INSTALLED)); then
      [ ! -e "$PLUGIN_DEST" ] || mv "$PLUGIN_DEST" "$BACKUP_DIR/failed-plugin"
      [ "$PLUGIN_BACKED_UP" -eq 0 ] || mv "$BACKUP_DIR/plugin" "$PLUGIN_DEST"
    fi
    if ((SKILL_BACKED_UP || SKILL_INSTALLED)); then
      [ ! -e "$SKILL_DEST" ] || mv "$SKILL_DEST" "$BACKUP_DIR/failed-skill"
      [ "$SKILL_BACKED_UP" -eq 0 ] || mv "$BACKUP_DIR/skill" "$SKILL_DEST"
    fi
    if ((SERVICE_BACKED_UP || SERVICE_INSTALLED)); then
      [ ! -e "$SERVICE_DEST" ] || mv "$SERVICE_DEST" "$BACKUP_DIR/failed-service"
      [ "$SERVICE_BACKED_UP" -eq 0 ] || cp --preserve=mode,timestamps "$BACKUP_DIR/bitzybridge-ag.service" "$SERVICE_DEST"
      systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    printf 'Installation failed; previous installation restored. Evidence: %s\n' "$BACKUP_DIR" >&2
  fi
  exit "$status"
}
trap rollback_on_error EXIT
command -v hermes >/dev/null 2>&1 || fail "Hermes Agent is required"
command -v systemctl >/dev/null 2>&1 || fail "systemd is required"

if [ ! -x "$PYTHON" ]; then
  mkdir -p "$VENV_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv venv --quiet "$VENV_DIR"
  else
    command -v python3 >/dev/null 2>&1 || fail "Python 3.11+ is required"
    python3 -m venv "$VENV_DIR" || fail "Could not create venv; install python3-venv or uv"
  fi
fi
[ -x "$PYTHON" ] || fail "BitzyBridge-AG Python was not created: $PYTHON"

if [ ! -f "$ENV_FILE" ]; then
  : "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN for first install}"
  : "${AG_TELEGRAM_CHAT_ID:?Set AG_TELEGRAM_CHAT_ID for first install}"
  : "${AG_TELEGRAM_USER_ID:?Set AG_TELEGRAM_USER_ID for first install}"
  [[ "$AG_TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]] || fail "AG_TELEGRAM_CHAT_ID must be numeric"
  [[ "$AG_TELEGRAM_USER_ID" =~ ^-?[0-9]+$ ]] || fail "AG_TELEGRAM_USER_ID must be numeric"
fi

mkdir -p "$BACKUP_ROOT" "$CONFIG_DIR" "$STATE_DIR" "$(dirname -- "$SERVICE_DEST")"
chmod 700 "$CONFIG_DIR" "$STATE_DIR"

if [ -e "$PLUGIN_DEST" ]; then
  mkdir -p "$BACKUP_DIR"
  mv "$PLUGIN_DEST" "$BACKUP_DIR/plugin"
  PLUGIN_BACKED_UP=1
  printf 'Backed up previous plugin to %s\n' "$BACKUP_DIR/plugin"
fi

mkdir -p "$PLUGIN_DEST"
PLUGIN_INSTALLED=1
for file in __init__.py bridge.py cdp_client.py cdp_control.py policy.py schemas.py tool_handlers.py watcher.py plugin.yaml policy.json; do
  cp --preserve=mode,timestamps "$REPO_ROOT/$file" "$PLUGIN_DEST/$file"
done

if [ -e "$SKILL_DEST" ]; then
  mkdir -p "$BACKUP_DIR"
  mv "$SKILL_DEST" "$BACKUP_DIR/skill"
  SKILL_BACKED_UP=1
  printf 'Backed up previous skill to %s\n' "$BACKUP_DIR/skill"
fi
mkdir -p "$SKILL_DEST"
SKILL_INSTALLED=1
cp --preserve=mode,timestamps "$REPO_ROOT/skills/bitzybridge-ag/SKILL.md" "$SKILL_DEST/SKILL.md"

if [ ! -f "$ENV_FILE" ]; then
  umask 077
  {
    printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN"
    printf 'AG_TELEGRAM_CHAT_ID=%s\n' "$AG_TELEGRAM_CHAT_ID"
    printf 'AG_TELEGRAM_USER_ID=%s\n' "$AG_TELEGRAM_USER_ID"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
else
  printf 'Preserving existing private environment: %s\n' "$ENV_FILE"
fi

if [ -e "$SERVICE_DEST" ]; then
  mkdir -p "$BACKUP_DIR"
  cp --preserve=mode,timestamps "$SERVICE_DEST" "$BACKUP_DIR/bitzybridge-ag.service"
  SERVICE_BACKED_UP=1
fi
cp --preserve=mode,timestamps "$REPO_ROOT/systemd/bitzybridge-ag.service" "$SERVICE_DEST"
SERVICE_INSTALLED=1

if ! "$PYTHON" -c 'import websocket' >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --quiet --python "$PYTHON" -r "$REPO_ROOT/requirements.txt"
  else
    "$PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"
  fi
fi

hermes plugins enable --no-allow-tool-override bitzybridge-ag
systemctl --user daemon-reload
systemctl --user enable --now bitzybridge-ag.service
hermes gateway restart
trap - EXIT

printf '\nBitzyBridge-AG installed.\n'
printf 'Plugin: %s\n' "$PLUGIN_DEST"
printf 'Skill:  %s\n' "$SKILL_DEST"
printf 'Config: %s\n' "$ENV_FILE"
printf 'State:  %s\n' "$STATE_DIR"
printf 'Python: %s\n' "$PYTHON"
printf 'Run:    %s/scripts/doctor.sh\n' "$REPO_ROOT"
