#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HERMES_WASM_AGENT_HOST:-0.0.0.0}"
PORT="${HERMES_WASM_AGENT_PORT:-8877}"
STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
PID_FILE="${HERMES_WASM_AGENT_PID_FILE:-${STATE_DIR}/wasm-agent.pid}"
LOG_FILE="${HERMES_WASM_AGENT_LOG_FILE:-${STATE_DIR}/wasm-agent.log}"
BRIDGE_URL="${HERMES_WASM_AGENT_BRIDGE_URL:-http://127.0.0.1:8790}"
PYTHON_BIN="${PYTHON:-python3}"

mkdir -p "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"

if [[ "${HERMES_WASM_AGENT_START_BRIDGE:-1}" != "0" ]]; then
  "${PLUGIN_DIR}/scripts/start_wasm_bridge.sh"
fi

if [[ -s "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "wasm-agent already running on pid ${old_pid}"
    exit 0
  fi
fi

if command -v setsid >/dev/null 2>&1; then
  setsid "${PYTHON_BIN}" "${PLUGIN_DIR}/server/static_server.py" \
    --host "${HOST}" --port "${PORT}" --bridge-url "${BRIDGE_URL}" \
    >"${LOG_FILE}" 2>&1 &
else
  nohup "${PYTHON_BIN}" "${PLUGIN_DIR}/server/static_server.py" \
    --host "${HOST}" --port "${PORT}" --bridge-url "${BRIDGE_URL}" \
    >"${LOG_FILE}" 2>&1 &
fi

pid="$!"
echo "${pid}" > "${PID_FILE}"
echo "wasm-agent started on http://${HOST}:${PORT} pid=${pid}"
echo "bridge: ${BRIDGE_URL}"
echo "log: ${LOG_FILE}"
