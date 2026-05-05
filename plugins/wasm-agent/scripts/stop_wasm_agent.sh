#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
PID_FILE="${HERMES_WASM_AGENT_PID_FILE:-${STATE_DIR}/wasm-agent.pid}"

if [[ ! -s "${PID_FILE}" ]]; then
  echo "wasm-agent is not running (no pid file)"
  exit 0
fi

pid="$(cat "${PID_FILE}")"
if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
  rm -f "${PID_FILE}"
  echo "wasm-agent is not running"
  exit 0
fi

kill "${pid}"
for _ in 1 2 3 4 5; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "wasm-agent stopped"
    exit 0
  fi
  sleep 1
done

kill -9 "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "wasm-agent stopped with SIGKILL"
