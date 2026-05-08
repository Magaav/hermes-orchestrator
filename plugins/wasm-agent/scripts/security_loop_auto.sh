#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAIT_SEC="${HERMES_WASM_AGENT_SECURITY_WAIT_SEC:-300}"
INTERVAL_SEC="${HERMES_WASM_AGENT_SECURITY_INTERVAL_SEC:-300}"
MODE="${HERMES_WASM_AGENT_SECURITY_MODE:-all}"
SURFACES="${HERMES_WASM_AGENT_SECURITY_SURFACES:-auth browser bridge config}"
MAX_CLEAN_REPEAT="${HERMES_WASM_AGENT_SECURITY_MAX_CLEAN_REPEAT:-3}"
APP_URL="${HERMES_WASM_AGENT_SECURITY_APP_URL:-${HERMES_WASM_AGENT_PUBLIC_URL:-}}"
BRIDGE_URL="${HERMES_WASM_AGENT_SECURITY_BRIDGE_URL:-}"

echo "wasm-agent security loop auto runner started wait=${WAIT_SEC}s interval=${INTERVAL_SEC}s mode=${MODE} surfaces=${SURFACES} max_clean_repeat=${MAX_CLEAN_REPEAT} app_url=${APP_URL:-default} bridge_url=${BRIDGE_URL:-default}"

active_pid=""
stop_loop() {
  if [[ -n "${active_pid}" ]] && kill -0 "${active_pid}" 2>/dev/null; then
    kill "${active_pid}" 2>/dev/null || true
    wait "${active_pid}" 2>/dev/null || true
  fi
  echo "wasm-agent security loop auto runner stopped"
  exit 0
}
trap stop_loop TERM INT

while true; do
  args=("${PLUGIN_DIR}/scripts/security_loop_run.py" "--mode" "${MODE}" "--wait-sec" "${WAIT_SEC}" "--max-clean-repeat" "${MAX_CLEAN_REPEAT}")
  if [[ -n "${APP_URL}" ]]; then
    args+=("--app-url" "${APP_URL}")
  fi
  if [[ -n "${BRIDGE_URL}" ]]; then
    args+=("--bridge-url" "${BRIDGE_URL}")
  fi
  for surface in ${SURFACES}; do
    args+=("--surface" "${surface}")
  done
  python3 "${args[@]}" &
  active_pid="$!"
  set +e
  wait "${active_pid}"
  status="$?"
  set -e
  if [[ "${status}" -ne 0 ]]; then
    echo "wasm-agent security loop run failed status=${status}"
  fi
  active_pid=""
  sleep "${INTERVAL_SEC}"
done
