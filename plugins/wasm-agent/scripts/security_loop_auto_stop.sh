#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-${PLUGIN_DIR}/state}"
PID_FILE="${HERMES_WASM_AGENT_SECURITY_AUTO_PID_FILE:-${STATE_DIR}/security-loop/security-loop-auto.pid}"

if [[ ! -s "${PID_FILE}" ]]; then
  echo "wasm-agent security loop auto is not running (no pid file)"
  exit 0
fi

pid="$(cat "${PID_FILE}")"
if ! kill -0 "${pid}" 2>/dev/null; then
  rm -f "${PID_FILE}"
  echo "wasm-agent security loop auto is not running"
  exit 0
fi

kill "${pid}" 2>/dev/null || true
for _ in $(seq 1 20); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "wasm-agent security loop auto stopped"
    exit 0
  fi
  sleep 0.2
done

kill -9 "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "wasm-agent security loop auto stopped with SIGKILL"
