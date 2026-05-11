#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
BRIDGE_STATE_DIR="${HERMES_WASM_AGENT_BRIDGE_STATE_DIR:-${STATE_DIR}/bridge}"
PID_FILE="${HERMES_WASM_AGENT_BRIDGE_PID_FILE:-${BRIDGE_STATE_DIR}/bridge.pid}"

if [[ ! -s "${PID_FILE}" ]]; then
  echo "wasm-agent bridge is not running (no pid file)"
  exit 0
fi

pid="$(cat "${PID_FILE}")"
if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
  rm -f "${PID_FILE}"
  echo "wasm-agent bridge is not running"
  exit 0
fi

kill "${pid}"
for _ in 1 2 3 4 5; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "wasm-agent bridge stopped"
    exit 0
  fi
  sleep 1
done

kill -9 "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "wasm-agent bridge stopped with SIGKILL"
