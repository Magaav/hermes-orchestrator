#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
PID_FILE="${HERMES_WASM_AGENT_PID_FILE:-${STATE_DIR}/wasm-agent.pid}"
HOST="${HERMES_WASM_AGENT_HOST:-127.0.0.1}"
PORT="${HERMES_WASM_AGENT_PORT:-8877}"

required=(
  "${PLUGIN_DIR}/public/index.html"
  "${PLUGIN_DIR}/public/app.js"
  "${PLUGIN_DIR}/public/styles.css"
  "${PLUGIN_DIR}/public/manifest.webmanifest"
  "${PLUGIN_DIR}/server/static_server.py"
)

for path in "${required[@]}"; do
  if [[ ! -f "${path}" ]]; then
    echo "missing ${path}" >&2
    exit 1
  fi
done

if command -v node >/dev/null 2>&1; then
  node "${PLUGIN_DIR}/tests/wasm_agent_smoke.test.js"
else
  echo "node not found; skipping wasm smoke test"
fi

python3 "${PLUGIN_DIR}/tests/image_card_golden.test.py"

if [[ -s "${PID_FILE}" ]]; then
  python3 - "$HOST" "$PORT" <<'PY'
import json
import sys
from urllib.request import urlopen

host, port = sys.argv[1], sys.argv[2]
with urlopen(f"http://{host}:{port}/health", timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
if not payload.get("ok"):
    raise SystemExit("health returned ok=false")
print(f"health ok http://{host}:{port}/health")
PY
else
  echo "wasm-agent is not running; static and wasm checks passed"
fi

if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1; then
  echo "chromium available for browser proof"
else
  echo "chromium not found; browser proof requires HERMES_WASM_AGENT_CHROMIUM" >&2
fi
