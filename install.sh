#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
HERMES_HOME=${HERMES_HOME:-"$HOME/.hermes"}
PRIVATE_ENV="$HOME/.config/bitzybridge-ag/env"
HERMES_ENV="$HERMES_HOME/.env"
NON_INTERACTIVE=0
OFFLINE_CHECK=0
SKIP_DOCTOR=0

usage() {
  cat <<'EOF'
BitzyBridge-AG one-shot installer

Usage:
  ./install.sh [options]

Options:
  --non-interactive  Never prompt; required values must already be in the environment.
  --offline-check    Run the final doctor without live CDP/service checks.
  --skip-doctor      Skip final doctor (intended for packaging tests only).
  -h, --help         Show this help.

First-install variables:
  TELEGRAM_BOT_TOKEN     Reused automatically from the Hermes .env when present.
  AG_TELEGRAM_USER_ID    Telegram account allowed to approve requests.
  AG_TELEGRAM_CHAT_ID    Approval destination; defaults to USER_ID for a DM.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --offline-check) OFFLINE_CHECK=1 ;;
    --skip-doctor) SKIP_DOCTOR=1 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
  shift
done

read_env_value() {
  local file=$1 key=$2 line value
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case "$line" in
      "$key="*)
        value=${line#*=}
        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
          value=${value:1:${#value}-2}
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
          value=${value:1:${#value}-2}
        fi
        printf '%s' "$value"
        return 0
        ;;
    esac
  done < "$file"
  return 1
}

load_if_missing() {
  local variable=$1 key=$2 file=$3 value
  [ -z "${!variable-}" ] || return 0
  if value=$(read_env_value "$file" "$key"); then
    printf -v "$variable" '%s' "$value"
  fi
}

prompt_required() {
  local variable=$1 label=$2 secret=${3:-0} value
  [ -n "${!variable-}" ] && return 0
  ((NON_INTERACTIVE == 0)) || fail "$variable is required in non-interactive mode"
  [ -r /dev/tty ] || fail "$variable is missing and no interactive terminal is available"
  if ((secret)); then
    printf '%s: ' "$label" > /dev/tty
    IFS= read -r -s value < /dev/tty
    printf '\n' > /dev/tty
  else
    printf '%s: ' "$label" > /dev/tty
    IFS= read -r value < /dev/tty
  fi
  [ -n "$value" ] || fail "$variable cannot be empty"
  printf -v "$variable" '%s' "$value"
}

[ -f "$REPO_ROOT/plugin.yaml" ] || fail "Run this script from the BitzyBridge-AG repository"
[ -x "$REPO_ROOT/scripts/install.sh" ] || fail "Missing internal installer: scripts/install.sh"
command -v hermes >/dev/null 2>&1 || fail "Hermes Agent is not installed or not in PATH"

# Prefer the bridge's existing private config, then reuse Hermes Telegram credentials.
load_if_missing TELEGRAM_BOT_TOKEN TELEGRAM_BOT_TOKEN "$PRIVATE_ENV"
load_if_missing AG_TELEGRAM_USER_ID AG_TELEGRAM_USER_ID "$PRIVATE_ENV"
load_if_missing AG_TELEGRAM_CHAT_ID AG_TELEGRAM_CHAT_ID "$PRIVATE_ENV"
load_if_missing TELEGRAM_BOT_TOKEN TELEGRAM_BOT_TOKEN "$HERMES_ENV"

prompt_required TELEGRAM_BOT_TOKEN "Telegram bot token" 1
prompt_required AG_TELEGRAM_USER_ID "Authorized Telegram user ID"
AG_TELEGRAM_CHAT_ID=${AG_TELEGRAM_CHAT_ID:-$AG_TELEGRAM_USER_ID}

[[ "$AG_TELEGRAM_USER_ID" =~ ^-?[0-9]+$ ]] || fail "AG_TELEGRAM_USER_ID must be numeric"
[[ "$AG_TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]] || fail "AG_TELEGRAM_CHAT_ID must be numeric"

export TELEGRAM_BOT_TOKEN AG_TELEGRAM_USER_ID AG_TELEGRAM_CHAT_ID HERMES_HOME

printf '%s\n' '== BitzyBridge-AG one-shot setup =='
printf 'Hermes home: %s\n' "$HERMES_HOME"
printf 'Approval user: %s\n' "$AG_TELEGRAM_USER_ID"
printf 'Approval chat: %s\n' "$AG_TELEGRAM_CHAT_ID"
printf '%s\n' 'Telegram token: configured (hidden)'

"$REPO_ROOT/scripts/install.sh"

if ((SKIP_DOCTOR == 0)); then
  if ((OFFLINE_CHECK)); then
    "$REPO_ROOT/scripts/doctor.sh" --offline
  else
    "$REPO_ROOT/scripts/doctor.sh"
  fi
fi

printf '%s\n' '== BitzyBridge-AG setup complete =='
