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
  node --input-type=module --check < "${PLUGIN_DIR}/public/modules/spaces/shared-voice-room.js"
  node "${PLUGIN_DIR}/tests/wasm_agent_smoke.test.js"
  node "${PLUGIN_DIR}/tests/client_state_store.test.mjs"
  node "${PLUGIN_DIR}/tests/shared_voice_room.test.mjs"
  node "${PLUGIN_DIR}/tests/ui_navigation_history.test.js"
  node "${PLUGIN_DIR}/tests/wis_engine.test.js"
else
  echo "node not found; skipping wasm smoke test"
fi

python3 "${PLUGIN_DIR}/tests/agent_input_editor.test.py"
python3 "${PLUGIN_DIR}/tests/bridge_routes.test.py"
python3 "${PLUGIN_DIR}/tests/image_card_golden.test.py"
python3 "${PLUGIN_DIR}/tests/client_first_cloud.test.py"
python3 "${PLUGIN_DIR}/tests/wis_shared_space.test.py"
python3 "${PLUGIN_DIR}/tests/security_loop_policy.test.py"
python3 "${PLUGIN_DIR}/tests/security_loop_runner.test.py"

if [[ -s "${PID_FILE}" ]]; then
  python3 - "$HOST" "$PORT" <<'PY'
import json
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

host, port = sys.argv[1], sys.argv[2]
try:
    with urlopen(f"http://{host}:{port}/health", timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise SystemExit("health returned ok=false")
    print(f"health ok http://{host}:{port}/health")
except HTTPError as exc:
    payload = json.loads(exc.read().decode("utf-8"))
    code = payload.get("error", {}).get("code")
    if exc.code != 401 or code != "auth_required":
        raise
    print(f"auth gate ok http://{host}:{port}/health returned 401 auth_required")
PY
else
  echo "wasm-agent is not running; static and wasm checks passed"
fi

if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1; then
  echo "chromium available for browser proof"
else
  echo "chromium not found; browser proof requires HERMES_WASM_AGENT_CHROMIUM" >&2
fi
