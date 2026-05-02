#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HERMES_SPACE_UI_HOST:-127.0.0.1}"
PORT="${HERMES_SPACE_UI_PORT:-8790}"
STATE_DIR="${HERMES_SPACE_UI_STATE_DIR:-/local/plugins/hermes-space-ui/state}"
PID_FILE="${HERMES_SPACE_UI_PID_FILE:-${STATE_DIR}/bridge.pid}"
LOG_FILE="${HERMES_SPACE_UI_LOG_FILE:-${STATE_DIR}/bridge.log}"
PYTHON_BIN="${PYTHON:-python3}"
LEGACY_STATE_DIR="/local/plugins/private/hermes-space-ui"

fail_legacy_state() {
  printf 'hermes-space-ui error: %s\n' "$1" >&2
  exit 1
}

if [[ "${STATE_DIR}" == "${LEGACY_STATE_DIR}" ]]; then
  fail_legacy_state "legacy state path is no longer supported: ${LEGACY_STATE_DIR}. Use /local/plugins/hermes-space-ui/state instead."
fi

if [[ -d "${LEGACY_STATE_DIR}" ]] && find "${LEGACY_STATE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  fail_legacy_state "legacy state detected at ${LEGACY_STATE_DIR}. Migrate or delete it before starting the bridge."
fi

mkdir -p "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"

if [[ -s "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "hermes-space-ui already running on pid ${old_pid}"
    exit 0
  fi
fi

export PYTHONPATH="${PLUGIN_DIR}/server${PYTHONPATH:+:${PYTHONPATH}}"
export HERMES_SPACE_UI_HOST="${HOST}"
export HERMES_SPACE_UI_PORT="${PORT}"
export HERMES_SPACE_UI_STATE_DIR="${STATE_DIR}"
export HERMES_SPACE_UI_TOKEN="${HERMES_SPACE_UI_TOKEN:-}"

if command -v setsid >/dev/null 2>&1; then
  setsid "${PYTHON_BIN}" "${PLUGIN_DIR}/server/bridge.py" --host "${HOST}" --port "${PORT}" \
    >"${LOG_FILE}" 2>&1 &
else
  nohup "${PYTHON_BIN}" "${PLUGIN_DIR}/server/bridge.py" --host "${HOST}" --port "${PORT}" \
    >"${LOG_FILE}" 2>&1 &
fi

pid="$!"
echo "${pid}" > "${PID_FILE}"
echo "hermes-space-ui bridge started on http://${HOST}:${PORT} pid=${pid}"
echo "log: ${LOG_FILE}"
