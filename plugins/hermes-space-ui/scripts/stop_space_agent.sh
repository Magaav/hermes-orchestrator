#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_SPACE_UI_STATE_DIR:-/local/plugins/hermes-space-ui/state}"
SPACE_PID_FILE="${HERMES_SPACE_AGENT_PID_FILE:-${STATE_DIR}/space-agent.pid}"
BRIDGE_PID_FILE="${HERMES_SPACE_UI_BRIDGE_PID_FILE:-${STATE_DIR}/bridge.pid}"
LEGACY_STATE_DIR="/local/plugins/private/hermes-space-ui"

fail_legacy_state() {
  printf '[space] %s\n' "$*" >&2
  exit 1
}

if [[ "${STATE_DIR}" == "${LEGACY_STATE_DIR}" ]]; then
  fail_legacy_state "legacy state path is no longer supported: ${LEGACY_STATE_DIR}. Use /local/plugins/hermes-space-ui/state instead."
fi

if [[ -d "${LEGACY_STATE_DIR}" ]] && find "${LEGACY_STATE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  fail_legacy_state "legacy state detected at ${LEGACY_STATE_DIR}. Stop or migrate it manually before using the new state path."
fi

stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -s "${pid_file}" ]]; then
    echo "${label} is not running"
    return
  fi
  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${pid_file}"
    echo "${label} is not running"
    return
  fi

  kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${pid_file}"
      echo "${label} stopped"
      return
    fi
    sleep 1
  done
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
  echo "${label} stopped with SIGKILL"
}

stop_pid_file "${SPACE_PID_FILE}" "Space Agent"

if [[ -x "${PLUGIN_DIR}/scripts/stop_space_ui.sh" ]]; then
  HERMES_SPACE_UI_STATE_DIR="${STATE_DIR}" \
    HERMES_SPACE_UI_PID_FILE="${BRIDGE_PID_FILE}" \
    "${PLUGIN_DIR}/scripts/stop_space_ui.sh"
else
  stop_pid_file "${BRIDGE_PID_FILE}" "Hermes bridge"
fi
