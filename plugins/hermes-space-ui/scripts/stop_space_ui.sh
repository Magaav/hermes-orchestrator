#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HERMES_SPACE_UI_STATE_DIR:-/local/plugins/hermes-space-ui/state}"
PID_FILE="${HERMES_SPACE_UI_PID_FILE:-${STATE_DIR}/bridge.pid}"
LEGACY_STATE_DIR="/local/plugins/private/hermes-space-ui"

fail_legacy_state() {
  printf 'hermes-space-ui error: %s\n' "$1" >&2
  exit 1
}

if [[ "${STATE_DIR}" == "${LEGACY_STATE_DIR}" ]]; then
  fail_legacy_state "legacy state path is no longer supported: ${LEGACY_STATE_DIR}. Use /local/plugins/hermes-space-ui/state instead."
fi

if [[ -d "${LEGACY_STATE_DIR}" ]] && find "${LEGACY_STATE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  fail_legacy_state "legacy state detected at ${LEGACY_STATE_DIR}. Stop or migrate it manually before using the new state path."
fi

if [[ ! -s "${PID_FILE}" ]]; then
  echo "hermes-space-ui bridge is not running (no pid file)"
  exit 0
fi

pid="$(cat "${PID_FILE}")"
if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
  rm -f "${PID_FILE}"
  echo "hermes-space-ui bridge is not running"
  exit 0
fi

kill "${pid}"
for _ in 1 2 3 4 5; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "hermes-space-ui bridge stopped"
    exit 0
  fi
  sleep 1
done

kill -9 "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "hermes-space-ui bridge stopped with SIGKILL"
