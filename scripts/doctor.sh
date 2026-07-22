#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PYTHON="${BITZYBRIDGE_PYTHON:-$HOME/.local/share/bitzybridge-ag/venv/bin/python}"
MODE=${1:-live}

if [ ! -x "$PYTHON" ]; then
  PYTHON="${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/python"
fi
[ -x "$PYTHON" ] || { printf 'BitzyBridge-AG Python not found; run ./install.sh first\n' >&2; exit 1; }

printf '[1/5] Python syntax\n'
"$PYTHON" -m compileall -q "$REPO_ROOT"

printf '[2/5] Unit tests\n'
(
  cd "$REPO_ROOT"
  "$PYTHON" -m unittest discover -v -s tests
)

printf '[3/5] Dependency\n'
"$PYTHON" -c 'import websocket; print("websocket-client: ok")'

printf '[4/5] Public-source hygiene\n'
"$PYTHON" "$REPO_ROOT/scripts/source_hygiene.py" "$REPO_ROOT"

printf '[5/5] Runtime\n'
if [ "$MODE" = "--offline" ]; then
  printf 'offline mode: live CDP and service checks skipped\n'
else
  (
    cd "$REPO_ROOT"
    "$PYTHON" watcher.py --self-test
  )
  systemctl --user is-active bitzybridge-ag.service
  hermes gateway status >/dev/null
fi

printf 'BitzyBridge-AG doctor: PASS (%s)\n' "$MODE"
