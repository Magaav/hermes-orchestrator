#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_WASM_AGENT_STATE_DIR:-${PLUGIN_DIR}/state}"
RUN_DIR="${STATE_DIR}/security-loop"
PID_FILE="${HERMES_WASM_AGENT_SECURITY_AUTO_PID_FILE:-${RUN_DIR}/security-loop-auto.pid}"
LOG_FILE="${HERMES_WASM_AGENT_SECURITY_AUTO_LOG_FILE:-${RUN_DIR}/security-loop-auto.log}"

mkdir -p "${RUN_DIR}"

if [[ -s "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if kill -0 "${old_pid}" 2>/dev/null; then
    echo "wasm-agent security loop auto already running pid=${old_pid}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if command -v setsid >/dev/null 2>&1; then
  setsid "${PLUGIN_DIR}/scripts/security_loop_auto.sh" >>"${LOG_FILE}" 2>&1 &
else
  nohup "${PLUGIN_DIR}/scripts/security_loop_auto.sh" >>"${LOG_FILE}" 2>&1 &
fi
pid="$!"
echo "${pid}" > "${PID_FILE}"
echo "wasm-agent security loop auto started pid=${pid}"
echo "log: ${LOG_FILE}"
