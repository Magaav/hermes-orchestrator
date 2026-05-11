#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HERMES_WASM_AGENT_BRIDGE_HOST:-127.0.0.1}"
PORT="${HERMES_WASM_AGENT_BRIDGE_PORT:-8790}"
STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
BRIDGE_STATE_DIR="${HERMES_WASM_AGENT_BRIDGE_STATE_DIR:-${STATE_DIR}/bridge}"
PID_FILE="${HERMES_WASM_AGENT_BRIDGE_PID_FILE:-${BRIDGE_STATE_DIR}/bridge.pid}"
LOG_FILE="${HERMES_WASM_AGENT_BRIDGE_LOG_FILE:-${BRIDGE_STATE_DIR}/bridge.log}"
PYTHON_BIN="${PYTHON:-python3}"

mkdir -p "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"

if [[ -s "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "wasm-agent bridge already running on pid ${old_pid}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :${PORT}" | grep -q ":${PORT}"; then
  echo "wasm-agent bridge port ${PORT} is already listening"
  exit 0
fi

export PYTHONPATH="${PLUGIN_DIR}/server${PYTHONPATH:+:${PYTHONPATH}}"
export HERMES_WASM_AGENT_BRIDGE_HOST="${HOST}"
export HERMES_WASM_AGENT_BRIDGE_PORT="${PORT}"
export HERMES_WASM_AGENT_BRIDGE_STATE_DIR="${BRIDGE_STATE_DIR}"
export HERMES_WASM_AGENT_BRIDGE_TOKEN="${HERMES_WASM_AGENT_BRIDGE_TOKEN:-}"

if command -v setsid >/dev/null 2>&1; then
  setsid "${PYTHON_BIN}" "${PLUGIN_DIR}/server/bridge.py" --host "${HOST}" --port "${PORT}" \
    >"${LOG_FILE}" 2>&1 &
else
  nohup "${PYTHON_BIN}" "${PLUGIN_DIR}/server/bridge.py" --host "${HOST}" --port "${PORT}" \
    >"${LOG_FILE}" 2>&1 &
fi

pid="$!"
echo "${pid}" > "${PID_FILE}"
echo "wasm-agent bridge started on http://${HOST}:${PORT} pid=${pid}"
echo "log: ${LOG_FILE}"
