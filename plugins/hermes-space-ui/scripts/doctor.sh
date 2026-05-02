#!/usr/bin/env bash
set -u

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HERMES_SPACE_UI_HOST:-127.0.0.1}"
PORT="${HERMES_SPACE_UI_PORT:-8790}"
HERMES_ROOT="${HERMES_ORCHESTRATOR_ROOT:-/local}"
HORC="${HERMES_SPACE_UI_HORC:-${HERMES_ROOT}/scripts/public/clone/horc.sh}"
SPACE_AGENT_REPO="${SPACE_AGENT_REPO:-https://github.com/agent0ai/space-agent}"
LEGACY_STATE_DIR="/local/plugins/private/hermes-space-ui"

failures=0
warnings=0

pass() {
  printf 'PASS %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf 'WARN %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf 'FAIL %s\n' "$1"
}

[[ -d "${PLUGIN_DIR}" ]] && pass "plugin directory exists: ${PLUGIN_DIR}" || fail "plugin directory missing: ${PLUGIN_DIR}"
[[ -f "${PLUGIN_DIR}/plugin.yaml" ]] && pass "plugin manifest exists" || fail "plugin.yaml missing"
[[ -f "${PLUGIN_DIR}/server/bridge.py" ]] && pass "bridge server exists" || fail "server/bridge.py missing"
[[ -f "${PLUGIN_DIR}/server/routes.py" ]] && pass "routes module exists" || fail "server/routes.py missing"
[[ -f "${PLUGIN_DIR}/server/schemas.py" ]] && pass "schemas module exists" || fail "server/schemas.py missing"
[[ -f "${PLUGIN_DIR}/server/auth.py" ]] && pass "auth module exists" || fail "server/auth.py missing"

if [[ -n "${HERMES_SPACE_UI_TOKEN:-}" ]]; then
  pass "HERMES_SPACE_UI_TOKEN is set"
else
  warn "HERMES_SPACE_UI_TOKEN is not set; bridge will run in local development mode"
fi

if command -v python3 >/dev/null 2>&1; then
  pass "python3 is available"
else
  fail "python3 is not available"
fi

if PYTHONPATH="${PLUGIN_DIR}/server${PYTHONPATH:+:${PYTHONPATH}}" python3 -m py_compile \
  "${PLUGIN_DIR}/server/bridge.py" \
  "${PLUGIN_DIR}/server/routes.py" \
  "${PLUGIN_DIR}/server/schemas.py" \
  "${PLUGIN_DIR}/server/auth.py" >/dev/null 2>&1; then
  pass "bridge server Python modules compile"
else
  fail "bridge server Python modules do not compile"
fi

if [[ -f "${HORC}" || -n "$(command -v "${HORC}" 2>/dev/null)" ]]; then
  pass "orchestrator CLI available: ${HORC}"
else
  fail "orchestrator CLI not found: ${HORC}"
fi

if [[ -d "${LEGACY_STATE_DIR}" ]] && find "${LEGACY_STATE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  fail "legacy hermes-space-ui state detected at ${LEGACY_STATE_DIR}; migrate or delete it before using /local/plugins/hermes-space-ui/state"
else
  pass "no legacy hermes-space-ui state detected at ${LEGACY_STATE_DIR}"
fi

if [[ -n "${SPACE_AGENT_URL:-}" ]]; then
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 "${SPACE_AGENT_URL}" >/dev/null 2>&1; then
      pass "Space Agent URL reachable: ${SPACE_AGENT_URL}"
    else
      warn "Space Agent URL configured but not reachable: ${SPACE_AGENT_URL}"
    fi
  else
    warn "curl missing; cannot probe SPACE_AGENT_URL"
  fi
else
  warn "SPACE_AGENT_URL not configured"
fi

if [[ "${SPACE_AGENT_REPO}" == "https://github.com/agent0ai/space-agent" ]]; then
  pass "Space Agent upstream repo is set: ${SPACE_AGENT_REPO}"
else
  warn "SPACE_AGENT_REPO is overridden: ${SPACE_AGENT_REPO}"
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 3 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    pass "bridge /health endpoint reachable at http://${HOST}:${PORT}/health"
  else
    warn "bridge /health endpoint is not reachable at http://${HOST}:${PORT}/health"
  fi
else
  warn "curl missing; cannot probe bridge /health"
fi

printf 'doctor complete: failures=%s warnings=%s\n' "${failures}" "${warnings}"
if [[ "${failures}" -gt 0 ]]; then
  exit 1
fi
exit 0
