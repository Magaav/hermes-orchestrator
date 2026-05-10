#!/usr/bin/env bash
set -u -o pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${PLUGIN_DIR}/../.." && pwd)"
PUBLIC_URL="${HERMES_WASM_AGENT_PUBLIC_URL:-}"
LOCAL_URL="${HERMES_WASM_AGENT_LOCAL_URL:-http://${HERMES_WASM_AGENT_HOST:-127.0.0.1}:${HERMES_WASM_AGENT_PORT:-8877}}"
TARGET_URL="${PUBLIC_URL:-${LOCAL_URL}}"

pass_count=0
warn_count=0
fail_count=0

section() {
  printf '\n== %s ==\n' "$1"
}

pass() {
  pass_count=$((pass_count + 1))
  printf 'PASS %s\n' "$1"
}

warn() {
  warn_count=$((warn_count + 1))
  printf 'WARN %s\n' "$1"
}

fail() {
  fail_count=$((fail_count + 1))
  printf 'FAIL %s\n' "$1"
}

run_check() {
  local label="$1"
  shift
  if "$@"; then
    pass "${label}"
  else
    fail "${label}"
  fi
}

have() {
  command -v "$1" >/dev/null 2>&1
}

http_status() {
  local method="$1"
  local url="$2"
  local origin="${3:-}"
  if [[ -n "${origin}" ]]; then
    curl -ksS -o /tmp/wasm-agent-security-body.$$ -w '%{http_code}' -X "${method}" -H "Origin: ${origin}" "${url}" 2>/dev/null
  else
    curl -ksS -o /tmp/wasm-agent-security-body.$$ -w '%{http_code}' -X "${method}" "${url}" 2>/dev/null
  fi
}

expect_status() {
  local label="$1"
  local method="$2"
  local path="$3"
  local expected="$4"
  local status
  status="$(http_status "${method}" "${TARGET_URL}${path}")"
  rm -f /tmp/wasm-agent-security-body.$$
  if [[ "${status}" == "${expected}" ]]; then
    pass "${label} returned ${expected}"
  else
    fail "${label} returned ${status}, expected ${expected}"
  fi
}

expect_status_any() {
  local label="$1"
  local method="$2"
  local path="$3"
  shift 3
  local status expected
  status="$(http_status "${method}" "${TARGET_URL}${path}")"
  rm -f /tmp/wasm-agent-security-body.$$
  for expected in "$@"; do
    if [[ "${status}" == "${expected}" ]]; then
      pass "${label} returned ${status}"
      return 0
    fi
  done
  fail "${label} returned ${status}, expected one of: $*"
}

section "wasm-agent public launch security gate"
printf 'Plugin: %s\n' "${PLUGIN_DIR}"
printf 'Target: %s\n' "${TARGET_URL}"
if [[ -z "${PUBLIC_URL}" ]]; then
  warn "HERMES_WASM_AGENT_PUBLIC_URL is not set; running HTTP route checks against local URL"
elif [[ ! "${PUBLIC_URL}" =~ ^https:// ]]; then
  fail "public URL is not HTTPS: ${PUBLIC_URL}"
else
  pass "public URL uses HTTPS"
fi

section "local correctness checks"
if have node; then
  run_check "public/app.js parses as an ES module" bash -c "node --input-type=module --check < '${PLUGIN_DIR}/public/app.js'"
  run_check "shared voice room module parses as an ES module" bash -c "node --input-type=module --check < '${PLUGIN_DIR}/public/modules/spaces/shared-voice-room.js'"
  run_check "wasm smoke test" node "${PLUGIN_DIR}/tests/wasm_agent_smoke.test.js"
  run_check "shared voice room logic test" node "${PLUGIN_DIR}/tests/shared_voice_room.test.mjs"
  run_check "UI navigation history test" node "${PLUGIN_DIR}/tests/ui_navigation_history.test.js"
  run_check "WIS engine test" node "${PLUGIN_DIR}/tests/wis_engine.test.js"
else
  fail "node is required for frontend launch checks"
fi

if have python3; then
  run_check "image card golden test" python3 "${PLUGIN_DIR}/tests/image_card_golden.test.py"
  run_check "WIS shared-space behavior test" python3 "${PLUGIN_DIR}/tests/wis_shared_space.test.py"
  run_check "security loop policy test" python3 "${PLUGIN_DIR}/tests/security_loop_policy.test.py"
  run_check "security loop runner test" python3 "${PLUGIN_DIR}/tests/security_loop_runner.test.py"
else
  fail "python3 is required for backend launch checks"
fi

section "route exposure checks"
if have curl; then
  expect_status_any "public shell" GET "/" 200 401
  expect_status_any "session bootstrap" GET "/auth/session" 200
  expect_status_any "bridge nodes unauthenticated" GET "/bridge/nodes" 401 403
  expect_status_any "security loop unauthenticated" GET "/security-loop/status" 401 403
  expect_status_any "timeline unauthenticated" GET "/timeline/status" 401 403
  expect_status_any "shared room unauthenticated" GET "/spaces/room?shared_space_id=probe" 401 403
  expect_status_any "browser open unauthenticated" POST "/browser/open" 401 403
  expect_status_any "agent attachment unauthenticated" GET "/agent/attachments/probe" 401 403

  if [[ -n "${PUBLIC_URL}" ]]; then
    config_body="$(curl -ksS "${TARGET_URL}/config.json" 2>/dev/null || true)"
    if printf '%s\n' "${config_body}" | grep -q '"hostBrowser"' && printf '%s\n' "${config_body}" | grep -q '"enabled"[[:space:]]*:[[:space:]]*false'; then
      pass "public config reports Host Browser disabled by default"
    elif [[ "${HERMES_WASM_AGENT_BROWSER_ENABLED:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
      warn "public config reports Host Browser enabled by explicit opt-in; attach CDP/private-network isolation review"
    else
      fail "public config does not report Host Browser disabled"
    fi
  fi

  cross_status="$(http_status POST "${TARGET_URL}/spaces" "https://evil.example")"
  rm -f /tmp/wasm-agent-security-body.$$
  if [[ "${cross_status}" == "401" || "${cross_status}" == "403" ]]; then
    pass "cross-origin non-public POST rejected before mutation"
  else
    fail "cross-origin non-public POST returned ${cross_status}, expected 401 or 403"
  fi

  room_cross_status="$(http_status POST "${TARGET_URL}/spaces/room" "https://evil.example")"
  rm -f /tmp/wasm-agent-security-body.$$
  if [[ "${room_cross_status}" == "401" || "${room_cross_status}" == "403" ]]; then
    pass "cross-origin shared room POST rejected before mutation"
  else
    fail "cross-origin shared room POST returned ${room_cross_status}, expected 401 or 403"
  fi

  cors_headers="$(curl -ksSI "${TARGET_URL}/" 2>/dev/null || true)"
  if printf '%s\n' "${cors_headers}" | grep -qi '^Access-Control-Allow-Origin: \*'; then
    fail "wildcard Access-Control-Allow-Origin is present on public responses"
  else
    pass "public response does not advertise wildcard CORS"
  fi

  if printf '%s\n' "${cors_headers}" | grep -qi '^Cross-Origin-Opener-Policy:'; then
    pass "Cross-Origin-Opener-Policy header is present"
  else
    warn "Cross-Origin-Opener-Policy header was not observed"
  fi

  for header in \
    "Strict-Transport-Security" \
    "Content-Security-Policy" \
    "X-Content-Type-Options" \
    "Referrer-Policy" \
    "Permissions-Policy" \
    "Cross-Origin-Resource-Policy" \
    "X-Frame-Options"; do
    if printf '%s\n' "${cors_headers}" | grep -qi "^${header}:"; then
      pass "${header} header is present"
    else
      warn "${header} header is missing"
    fi
  done
else
  fail "curl is required for route exposure checks"
fi

section "static policy checks"
if grep -q 'Access-Control-Allow-Origin", "\*"' "${PLUGIN_DIR}/server/static_server.py"; then
  fail "server code still emits wildcard CORS"
else
  pass "server code does not emit wildcard CORS"
fi

if grep -q 'HttpOnly' "${PLUGIN_DIR}/server/static_server.py" && grep -q 'SameSite=Lax' "${PLUGIN_DIR}/server/static_server.py"; then
  pass "auth cookie is HttpOnly and SameSite=Lax"
else
  fail "auth cookie is missing HttpOnly or SameSite=Lax"
fi

if grep -q 'same_origin_websocket' "${PLUGIN_DIR}/server/static_server.py"; then
  pass "browser WebSocket same-origin guard exists"
else
  fail "browser WebSocket same-origin guard is missing"
fi

if grep -q 'HERMES_WASM_AGENT_BROWSER_ENABLED' "${PLUGIN_DIR}/server/static_server.py" \
  && grep -q 'require_browser_feature_enabled' "${PLUGIN_DIR}/server/static_server.py"; then
  pass "Host Browser has a server-side public opt-in gate"
else
  fail "Host Browser public opt-in gate is missing"
fi

if grep -q 'bridge_route_allowed' "${PLUGIN_DIR}/server/static_server.py"; then
  pass "bridge proxy allowlist exists"
else
  fail "bridge proxy allowlist is missing"
fi

if grep -q 'url.pathname.startsWith("/security-loop/")' "${PLUGIN_DIR}/public/sw.js"; then
  pass "service worker bypasses security-loop routes"
else
  fail "service worker security-loop bypass is missing"
fi

section "secret scanning"
if have gitleaks; then
  run_check "gitleaks wasm-agent history scan" gitleaks detect --source "${REPO_ROOT}" --log-opts="-- plugins/wasm-agent" --redact --no-banner
  run_check "gitleaks wasm-agent worktree scan" gitleaks dir "${PLUGIN_DIR}" --redact --no-banner
elif have trufflehog; then
  run_check "trufflehog wasm-agent filesystem scan" trufflehog filesystem --no-update --fail "${PLUGIN_DIR}"
else
  warn "gitleaks/trufflehog not installed; run an independent secret scan before launch"
  if have git && have rg; then
    if git -C "${REPO_ROOT}" ls-files "plugins/wasm-agent" | xargs -r -I{} rg -n --no-heading -i '(api[_-]?key|secret|token|password).{0,24}[:=].{0,4}["'\''][A-Za-z0-9_./+=:-]{16,}' "${REPO_ROOT}/{}" >/tmp/wasm-agent-secret-scan.$$ 2>/dev/null; then
      warn "fallback keyword secret scan found candidates; review /tmp/wasm-agent-secret-scan.$$"
    else
      pass "fallback keyword secret scan found no tracked wasm-agent candidates"
      rm -f /tmp/wasm-agent-secret-scan.$$
    fi
  fi
fi

section "static analysis and dependencies"
if have bandit; then
  run_check "bandit scan" bandit -q -r "${PLUGIN_DIR}/server" "${PLUGIN_DIR}/scripts"
else
  warn "bandit not installed; run Python security static analysis before launch"
fi

if have semgrep; then
  run_check "semgrep scan" semgrep --quiet --config auto "${PLUGIN_DIR}"
else
  warn "semgrep not installed; run Semgrep before launch"
fi

if have pip-audit; then
  run_check "pip-audit scan" pip-audit
else
  warn "pip-audit not installed; run Python dependency audit before launch"
fi

if have osv-scanner; then
  osv_output="$(mktemp /tmp/wasm-agent-osv.XXXXXX)"
  if osv-scanner scan source -r "${PLUGIN_DIR}" >"${osv_output}" 2>&1; then
    pass "osv-scanner recursive scan"
  elif grep -qi "No package sources found" "${osv_output}"; then
    warn "osv-scanner found no package sources under wasm-agent"
  else
    fail "osv-scanner recursive scan failed"
    sed -n '1,80p' "${osv_output}"
  fi
  rm -f "${osv_output}"
else
  warn "osv-scanner not installed; run OSV/dependency scan before launch"
fi

section "external staging checks"
if [[ -n "${PUBLIC_URL}" ]] && { have zap-baseline.py || have docker; }; then
  zap_status=127
  if have zap-baseline.py; then
    zap-baseline.py -t "${PUBLIC_URL}" -m 5
    zap_status=$?
  else
    zap_dir="${HERMES_WASM_AGENT_ZAP_DIR:-${PLUGIN_DIR}/state/launch-security/zap-latest}"
    mkdir -p "${zap_dir}"
    chmod 777 "${zap_dir}" 2>/dev/null || true
    docker run --rm -v "${zap_dir}:/zap/wrk:rw" ghcr.io/zaproxy/zaproxy:stable \
      zap-baseline.py -t "${PUBLIC_URL}" -m 5 \
      -J zap-baseline.json -r zap-baseline.html -w zap-baseline.md
    zap_status=$?
  fi
  if [[ "${zap_status}" -eq 0 ]]; then
    pass "OWASP ZAP baseline found no warnings"
  elif [[ "${zap_status}" -eq 2 ]]; then
    warn "OWASP ZAP baseline completed with warnings; review the ZAP report"
  else
    fail "OWASP ZAP baseline failed with exit ${zap_status}"
  fi
else
  warn "OWASP ZAP baseline not run; run it against staging before launch"
fi

if [[ -n "${PUBLIC_URL}" ]]; then
  warn "Run an external TLS/header scan against ${PUBLIC_URL} and attach the report"
else
  warn "Set HERMES_WASM_AGENT_PUBLIC_URL to enable staging route checks"
fi

section "summary"
printf 'PASS %s\nWARN %s\nFAIL %s\n' "${pass_count}" "${warn_count}" "${fail_count}"

if [[ "${fail_count}" -gt 0 ]]; then
  printf '\nLaunch gate result: BLOCKED\n'
  exit 1
fi

printf '\nLaunch gate result: LOCAL CHECKS PASSED WITH %s WARNING(S)\n' "${warn_count}"
