#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HERMES_SPACE_UI_STATE_DIR:-/local/plugins/hermes-space-ui/state}"
SPACE_AGENT_REPO="${SPACE_AGENT_REPO:-https://github.com/agent0ai/space-agent.git}"
SPACE_AGENT_DIR="${SPACE_AGENT_DIR:-${STATE_DIR}/space-agent}"
CUSTOMWARE_PATH="${SPACE_AGENT_CUSTOMWARE_PATH:-${STATE_DIR}/space-customware}"
NODE_ROOT="${HERMES_SPACE_NODE_ROOT:-${STATE_DIR}/node}"

UI_HOST="${HERMES_SPACE_AGENT_HOST:-127.0.0.1}"
UI_PORT="${HERMES_SPACE_AGENT_PORT:-8787}"
BRIDGE_HOST="${HERMES_SPACE_UI_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${HERMES_SPACE_UI_BRIDGE_PORT:-8790}"

SPACE_PID_FILE="${HERMES_SPACE_AGENT_PID_FILE:-${STATE_DIR}/space-agent.pid}"
BRIDGE_PID_FILE="${HERMES_SPACE_UI_BRIDGE_PID_FILE:-${STATE_DIR}/bridge.pid}"
SPACE_LOG_FILE="${HERMES_SPACE_AGENT_LOG_FILE:-${STATE_DIR}/space-agent.log}"
BRIDGE_LOG_FILE="${HERMES_SPACE_UI_LOG_FILE:-${STATE_DIR}/bridge.log}"
LEGACY_STATE_DIR="/local/plugins/private/hermes-space-ui"

SPACE_URL="http://${UI_HOST}:${UI_PORT}"
HERMES_SPACE_URL="http://${BRIDGE_HOST}:${BRIDGE_PORT}"
HERMES_SPACE_ID="${HERMES_SPACE_ID:-hermes-os}"
HERMES_SPACE_LLM_MODE="${HERMES_SPACE_LLM_MODE:-openrouter}"
HERMES_SPACE_LLM_MAX_TOKENS="${HERMES_SPACE_LLM_MAX_TOKENS:-120000}"
HERMES_SPACE_SEED_HERMES="${HERMES_SPACE_SEED_HERMES:-1}"

read_env_value() {
  local key="$1"
  local path="${2:-/local/agents/envs/orchestrator.env}"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi
  sed -n "s/^${key}=//p" "${path}" | tail -n 1 | sed "s/^['\"]//;s/['\"]$//"
}

if [[ "${HERMES_SPACE_LLM_MODE}" == "hermes" ]]; then
  HERMES_SPACE_LLM_ENDPOINT_DEFAULT="$(
    HERMES_SPACE_URL="${HERMES_SPACE_URL}" python3 - <<'PY'
import os
import urllib.parse

target = os.environ["HERMES_SPACE_URL"].rstrip("/") + "/v1/chat/completions"
print("/api/proxy?url=" + urllib.parse.quote(target, safe=""))
PY
  )"
  HERMES_SPACE_LLM_ENDPOINT="${HERMES_SPACE_LLM_ENDPOINT:-${HERMES_SPACE_LLM_ENDPOINT_DEFAULT}}"
  HERMES_SPACE_LLM_MODEL="${HERMES_SPACE_LLM_MODEL:-hermes-orchestrator}"
  HERMES_SPACE_LLM_API_KEY="${HERMES_SPACE_LLM_API_KEY:-hermes-local}"
  HERMES_SPACE_LLM_PARAMS_TEXT="${HERMES_SPACE_LLM_PARAMS_TEXT:-$(printf 'temperature:0.2\nreasoning:\n  exclude: true')}"
else
  HERMES_SPACE_LLM_ENDPOINT="${HERMES_SPACE_LLM_ENDPOINT:-https://openrouter.ai/api/v1/chat/completions}"
  HERMES_SPACE_LLM_MODEL="${HERMES_SPACE_LLM_MODEL:-}"
  HERMES_SPACE_LLM_API_KEY="${HERMES_SPACE_LLM_API_KEY:-$(read_env_value OPENROUTER_API_KEY)}"
  HERMES_SPACE_LLM_PARAMS_TEXT="${HERMES_SPACE_LLM_PARAMS_TEXT:-temperature:0.2}"
fi
HERMES_SPACE_ADMIN_LLM_MODEL="${HERMES_SPACE_ADMIN_LLM_MODEL:-${HERMES_SPACE_LLM_MODEL:-openai/gpt-5.4-mini}}"
HERMES_SPACE_ONSCREEN_LLM_MODEL="${HERMES_SPACE_ONSCREEN_LLM_MODEL:-${HERMES_SPACE_LLM_MODEL:-anthropic/claude-sonnet-4.6}}"

log() {
  printf '[space] %s\n' "$*"
}

fail_legacy_state() {
  printf '[space] %s\n' "$*" >&2
  exit 1
}

canonicalize_legacy_subpath() {
  local path="$1"
  local target_root="$2"
  if [[ -z "${path}" || "${path}" != "${LEGACY_STATE_DIR}"* ]]; then
    printf '%s\n' "${path}"
    return
  fi
  if [[ "${path}" == "${LEGACY_STATE_DIR}" ]]; then
    printf '%s\n' "${target_root}"
    return
  fi
  printf '%s\n' "${target_root}${path#${LEGACY_STATE_DIR}}"
}

if [[ "${STATE_DIR}" == "${LEGACY_STATE_DIR}" ]]; then
  fail_legacy_state "legacy state path is no longer supported: ${LEGACY_STATE_DIR}. Use /local/plugins/hermes-space-ui/state instead."
fi

if [[ -d "${LEGACY_STATE_DIR}" ]] && find "${LEGACY_STATE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  fail_legacy_state "legacy state detected at ${LEGACY_STATE_DIR}. Migrate or delete it before starting Space Agent."
fi

SPACE_AGENT_DIR="$(canonicalize_legacy_subpath "${SPACE_AGENT_DIR}" "${STATE_DIR}")"
CUSTOMWARE_PATH="$(canonicalize_legacy_subpath "${CUSTOMWARE_PATH}" "${STATE_DIR}")"
NODE_ROOT="$(canonicalize_legacy_subpath "${NODE_ROOT}" "${STATE_DIR}")"
SPACE_PID_FILE="$(canonicalize_legacy_subpath "${SPACE_PID_FILE}" "${STATE_DIR}")"
BRIDGE_PID_FILE="$(canonicalize_legacy_subpath "${BRIDGE_PID_FILE}" "${STATE_DIR}")"
SPACE_LOG_FILE="$(canonicalize_legacy_subpath "${SPACE_LOG_FILE}" "${STATE_DIR}")"
BRIDGE_LOG_FILE="$(canonicalize_legacy_subpath "${BRIDGE_LOG_FILE}" "${STATE_DIR}")"

mkdir -p "${STATE_DIR}" "${CUSTOMWARE_PATH}" "${NODE_ROOT}" "$(dirname "${SPACE_PID_FILE}")" "$(dirname "${BRIDGE_PID_FILE}")"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[space] missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

kill_pid_file() {
  local pid_file="$1"
  if [[ ! -s "${pid_file}" ]]; then
    return
  fi
  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    sleep 1
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${pid_file}"
}

kill_port() {
  local port="$1"
  local pids=""

  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return
  fi

  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  fi

  if [[ -n "${pids}" ]]; then
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill "${pid}" 2>/dev/null || true
    done <<< "${pids}"
    sleep 1
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -9 "${pid}" 2>/dev/null || true
    done <<< "${pids}"
  fi
}

node_major() {
  "$1" -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf '0\n'
}

download_file() {
  local url="$1"
  local out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${url}" -o "${out}"
    return
  fi
  python3 - "$url" "$out" <<'PY'
import sys
import urllib.request

url, out = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=60) as response:
    data = response.read()
with open(out, "wb") as handle:
    handle.write(data)
PY
}

resolve_node_platform() {
  case "$(uname -m)" in
    x86_64|amd64) printf 'linux-x64\n' ;;
    aarch64|arm64) printf 'linux-arm64\n' ;;
    *) printf '[space] unsupported Node platform: %s\n' "$(uname -m)" >&2; exit 1 ;;
  esac
}

latest_lts_node_version() {
  local platform="$1"
  python3 - "$platform" <<'PY'
import json
import sys
import urllib.request

platform = sys.argv[1]
with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=30) as response:
    rows = json.load(response)
for row in rows:
    version = str(row.get("version", ""))
    try:
        major = int(version.lstrip("v").split(".", 1)[0])
    except Exception:
        continue
    if major >= 20 and row.get("lts") and platform in row.get("files", []):
        print(version)
        raise SystemExit(0)
raise SystemExit("no supported Node LTS version found")
PY
}

ensure_node() {
  local system_node
  system_node="$(command -v node || true)"
  if [[ -n "${system_node}" ]] && [[ "$(node_major "${system_node}")" -ge 20 ]]; then
    NODE_BIN="${system_node}"
    NPM_BIN="$(command -v npm || true)"
    if [[ -z "${NPM_BIN}" ]]; then
      printf '[space] npm not found next to system node\n' >&2
      exit 1
    fi
    return
  fi

  local platform version node_dir archive url
  platform="$(resolve_node_platform)"
  version="${HERMES_SPACE_NODE_VERSION:-}"
  if [[ -z "${version}" ]]; then
    version="$(latest_lts_node_version "${platform}")"
  fi
  node_dir="${NODE_ROOT}/node-${version}-${platform}"
  archive="${NODE_ROOT}/node-${version}-${platform}.tar.xz"

  if [[ ! -x "${node_dir}/bin/node" ]]; then
    url="https://nodejs.org/dist/${version}/node-${version}-${platform}.tar.xz"
    log "installing portable Node ${version} (${platform})"
    download_file "${url}" "${archive}"
    tar -xJf "${archive}" -C "${NODE_ROOT}"
  fi

  NODE_BIN="${node_dir}/bin/node"
  NPM_BIN="${node_dir}/bin/npm"
}

ensure_space_agent_checkout() {
  need_cmd git

  if [[ ! -d "${SPACE_AGENT_DIR}/.git" ]]; then
    log "cloning Space Agent from ${SPACE_AGENT_REPO}"
    git clone "${SPACE_AGENT_REPO}" "${SPACE_AGENT_DIR}"
  elif [[ "${SPACE_AGENT_UPDATE:-1}" != "0" ]]; then
    log "updating Space Agent checkout"
    git -C "${SPACE_AGENT_DIR}" pull --ff-only
  fi
}

ensure_space_agent_deps() {
  if [[ "${SPACE_AGENT_NPM_INSTALL:-auto}" == "skip" ]]; then
    return
  fi

  if [[ ! -d "${SPACE_AGENT_DIR}/node_modules" || "${SPACE_AGENT_NPM_INSTALL:-auto}" == "always" ]]; then
    log "installing Space Agent npm dependencies"
    (cd "${SPACE_AGENT_DIR}" && PATH="$(dirname "${NODE_BIN}"):${PATH}" "${NPM_BIN}" ci --omit=optional)
  fi
}

sync_customware_bundle() {
  local source_dir="$1"
  local destination_dir="$2"

  if [[ ! -d "${source_dir}" ]]; then
    log "customware bundle source missing: ${source_dir}"
    return
  fi

  mkdir -p "$(dirname "${destination_dir}")"
  rm -rf "${destination_dir}"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "${source_dir}/" "${destination_dir}/"
    return
  fi

  mkdir -p "${destination_dir}"
  cp -a "${source_dir}/." "${destination_dir}/"
}

seed_customware() {
  local spaces_root="${CUSTOMWARE_PATH}/L2/user/spaces"
  local legacy_space_id="${HERMES_SPACE_LEGACY_ID:-hermes-fleet}"
  local legacy_space_root="${spaces_root}/${legacy_space_id}"
  local space_root="${spaces_root}/${HERMES_SPACE_ID}"

  if [[ "${HERMES_SPACE_ID}" != "${legacy_space_id}" && -d "${legacy_space_root}" && ! -e "${space_root}" ]]; then
    log "migrating Hermes OS space ${legacy_space_id} -> ${HERMES_SPACE_ID}"
    mkdir -p "${spaces_root}"
    mv "${legacy_space_root}" "${space_root}"
    python3 - "${space_root}/space.yaml" "${HERMES_SPACE_ID}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
space_id = sys.argv[2]
if path.exists():
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^id:\s*.*$", f"id: {space_id}", text, count=1)
    path.write_text(text, encoding="utf-8")
PY
  fi

  local widget_root="${space_root}/widgets"
  local conf_root="${CUSTOMWARE_PATH}/L2/user/conf"
  local skill_root="${CUSTOMWARE_PATH}/L1/_all/mod/hermes/space_ui/ext/skills/hermes-space-ui"
  local brand_bundle_root="${CUSTOMWARE_PATH}/L1/_all/mod/hermes/space-agent-brand"
  local component_context_menu_bundle_root="${CUSTOMWARE_PATH}/L1/_all/mod/space/component-context-menu"
  local fleet_bundle_root="${CUSTOMWARE_PATH}/L1/_all/mod/hermes/fleet"
  local performance_hud_bundle_root="${CUSTOMWARE_PATH}/L1/_all/mod/hermes/performance-hud"
  local fleet_seed_root="${PLUGIN_DIR}/plugin-interface/plugins/hermes-fleet/space-seed/hermes-fleet"
  mkdir -p "${widget_root}" "${conf_root}" "${skill_root}"

  sync_customware_bundle \
    "${PLUGIN_DIR}/plugin-interface/plugins/space-agent-brand" \
    "${brand_bundle_root}"

  sync_customware_bundle \
    "${PLUGIN_DIR}/plugin-interface/plugins/component-context-menu" \
    "${component_context_menu_bundle_root}"

  sync_customware_bundle \
    "${PLUGIN_DIR}/plugin-interface/plugins/hermes-fleet" \
    "${fleet_bundle_root}"

  sync_customware_bundle \
    "${PLUGIN_DIR}/plugin-interface/plugins/hermes-performance-hud" \
    "${performance_hud_bundle_root}"

  should_seed_llm_config() {
    local path="$1"
    [[ ! -f "${path}" ]] && return 0
    [[ "${HERMES_SPACE_SEED_FORCE:-0}" == "1" ]] && return 0
    [[ "${HERMES_SPACE_LLM_MODE}" == "openrouter" ]] || return 1
    if grep -Eq 'hermes-orchestrator|127\.0\.0\.1%3A8790|hermes-local' "${path}"; then
      return 0
    fi
    return 1
  }

  should_seed_hermes_fleet_space() {
    local manifest_path="${space_root}/space.yaml"
    local resources_widget_path="${widget_root}/hermes-os.yaml"
    local topology_widget_path="${widget_root}/hermes-topology.yaml"
    local drop_widget_path="${widget_root}/drop-to-copy.yaml"
    [[ ! -f "${manifest_path}" ]] && return 0
    [[ ! -f "${resources_widget_path}" ]] && return 0
    [[ ! -f "${topology_widget_path}" ]] && return 0
    [[ ! -f "${drop_widget_path}" ]] && return 0
    [[ "${HERMES_SPACE_SEED_FORCE:-0}" == "1" ]] && return 0

    if ! grep -Eq '^[[:space:]]*-[[:space:]]*hermes-os[[:space:]]*$' "${manifest_path}"; then
      return 0
    fi

    if ! grep -Eq '^[[:space:]]*-[[:space:]]*hermes-topology[[:space:]]*$' "${manifest_path}"; then
      return 0
    fi

    if ! grep -Eq '^[[:space:]]*-[[:space:]]*drop-to-copy[[:space:]]*$' "${manifest_path}"; then
      return 0
    fi

    if grep -Eq 'name:[[:space:]]*Hermes OS|24h 12m|System dashboard|Total: 16 GB|Total: 256 GB' "${resources_widget_path}"; then
      return 0
    fi

    if grep -Eq 'Add Node|Delete Node|hermes-topology-state|node-0|Node 0' "${topology_widget_path}"; then
      return 0
    fi

    if ! grep -Eq 'stream_events|ht-run-events|data-role=.run-events.|data-role=.run-stop.|/tasks/.+\}/stop|Message modal closed' "${topology_widget_path}"; then
      return 0
    fi

    if grep -Eq 'Bridge:|<label>Wish</label>|data-role=.wish.' "${drop_widget_path}"; then
      return 0
    fi

    return 1
  }

  copy_seed_template() {
    local source_path="$1"
    local destination_path="$2"
    mkdir -p "$(dirname "${destination_path}")"
    python3 - "${source_path}" "${destination_path}" "${HERMES_SPACE_URL}" "${HERMES_SPACE_ID}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
bridge_url = sys.argv[3]
space_id = sys.argv[4]
text = source.read_text(encoding="utf-8")
text = text.replace("__HERMES_SPACE_URL__", bridge_url)
text = text.replace("__HERMES_SPACE_ID__", space_id)
destination.write_text(text, encoding="utf-8")
PY
  }

  if should_seed_llm_config "${conf_root}/admin-chat.yaml"; then
    cat > "${conf_root}/admin-chat.yaml" <<YAML
llm_provider: api
api_endpoint: ${HERMES_SPACE_LLM_ENDPOINT}
api_key: ${HERMES_SPACE_LLM_API_KEY}
model: ${HERMES_SPACE_ADMIN_LLM_MODEL}
max_tokens: ${HERMES_SPACE_LLM_MAX_TOKENS}
params: |-
$(printf '%s\n' "${HERMES_SPACE_LLM_PARAMS_TEXT}" | sed 's/^/  /')
prompt_budget_ratios:
  system: 0.30
  history: 0.45
  transient: 0.15
  single_message: 0.10
YAML
  fi

  if should_seed_llm_config "${conf_root}/onscreen-agent.yaml"; then
    cat > "${conf_root}/onscreen-agent.yaml" <<YAML
llm_provider: api
api_endpoint: ${HERMES_SPACE_LLM_ENDPOINT}
api_key: ${HERMES_SPACE_LLM_API_KEY}
model: ${HERMES_SPACE_ONSCREEN_LLM_MODEL}
max_tokens: ${HERMES_SPACE_LLM_MAX_TOKENS}
params: |-
$(printf '%s\n' "${HERMES_SPACE_LLM_PARAMS_TEXT}" | sed 's/^/  /')
prompt_budget_ratios:
  system: 0.30
  history: 0.45
  transient: 0.15
  single_message: 0.10
YAML
  fi

  if [[ "${HERMES_SPACE_SEED_HERMES}" != "1" ]]; then
    return
  fi

  if should_seed_hermes_fleet_space; then
    if [[ ! -d "${fleet_seed_root}" ]]; then
      log "Hermes Fleet seed source missing: ${fleet_seed_root}"
    else
      copy_seed_template "${fleet_seed_root}/space.yaml" "${space_root}/space.yaml"
      copy_seed_template "${fleet_seed_root}/widgets/hermes-os.yaml" "${widget_root}/hermes-os.yaml"
      copy_seed_template "${fleet_seed_root}/widgets/hermes-topology.yaml" "${widget_root}/hermes-topology.yaml"
      copy_seed_template "${fleet_seed_root}/widgets/drop-to-copy.yaml" "${widget_root}/drop-to-copy.yaml"
      rm -f "${widget_root}/hermes-dashboard.yaml"
    fi
  fi

  cat > "${skill_root}/SKILL.md" <<MD
---
name: Hermes Space UI
description: Visualize and safely control Hermes Orchestrator fleets from Space Agent.
metadata:
  placement: system
---

Use the Hermes Fleet space and widgets when the user asks to inspect Hermes,
show host resources, show fleet topology, show fleet status, tail node logs,
or start/stop/restart nodes.

The Hermes bridge is available to the Space Agent server at:

\`\`\`text
${HERMES_SPACE_URL}
\`\`\`

Use \`space.fetchExternal(...)\` for calls so Space Agent can proxy localhost
requests through its Node server over the SSH tunnel.

Safe endpoints:

- \`GET /nodes\`
- \`GET /nodes/{node_id}\`
- \`GET /nodes/{node_id}/logs?lines=120\`
- \`GET /nodes/{node_id}/stats?bucket=daily&days=30\`
- \`GET /resources\`
- \`POST /nodes\`
- \`POST /nodes/{node_id}/action\`
- \`POST /nodes/{node_id}/prompt\`
- \`GET /capabilities\`

Do not use raw shell execution. Unknown actions must be rejected by the bridge.
\`run_prompt\` is routed through the official Hermes API server Runs API
(\`POST /v1/runs\` and \`GET /v1/runs/{run_id}\`) rather than direct Hermes
Python imports.
MD
}

start_bridge() {
  log "starting private Hermes bridge on ${HERMES_SPACE_URL}"
  kill_pid_file "${BRIDGE_PID_FILE}"
  kill_port "${BRIDGE_PORT}"
  HERMES_SPACE_UI_TOKEN="" \
    HERMES_SPACE_UI_HOST="${BRIDGE_HOST}" \
    HERMES_SPACE_UI_PORT="${BRIDGE_PORT}" \
    HERMES_SPACE_UI_STATE_DIR="${STATE_DIR}" \
    HERMES_SPACE_UI_PID_FILE="${BRIDGE_PID_FILE}" \
    HERMES_SPACE_UI_LOG_FILE="${BRIDGE_LOG_FILE}" \
    "${PLUGIN_DIR}/scripts/start_space_ui.sh"
}

start_space_agent() {
  log "starting Space Agent PWA on ${SPACE_URL}"
  kill_pid_file "${SPACE_PID_FILE}"
  kill_port "${UI_PORT}"

  export CUSTOMWARE_PATH
  if command -v setsid >/dev/null 2>&1; then
    (
      cd "${SPACE_AGENT_DIR}"
      export PATH="$(dirname "${NODE_BIN}"):${PATH}"
      setsid "${NODE_BIN}" space serve \
        "HOST=${UI_HOST}" \
        "PORT=${UI_PORT}" \
        "CUSTOMWARE_PATH=${CUSTOMWARE_PATH}" \
        "SINGLE_USER_APP=true" \
        "LOGIN_ALLOWED=false" \
        >"${SPACE_LOG_FILE}" 2>&1 &
      echo "$!" > "${SPACE_PID_FILE}"
    )
  else
    (
      cd "${SPACE_AGENT_DIR}"
      export PATH="$(dirname "${NODE_BIN}"):${PATH}"
      nohup "${NODE_BIN}" space serve \
        "HOST=${UI_HOST}" \
        "PORT=${UI_PORT}" \
        "CUSTOMWARE_PATH=${CUSTOMWARE_PATH}" \
        "SINGLE_USER_APP=true" \
        "LOGIN_ALLOWED=false" \
        >"${SPACE_LOG_FILE}" 2>&1 &
      echo "$!" > "${SPACE_PID_FILE}"
    )
  fi
}

wait_for_space_agent() {
  local health_url="${SPACE_URL}/api/health"
  for _ in $(seq 1 30); do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "${health_url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

need_cmd python3
need_cmd tar
ensure_node
log "using node: $("${NODE_BIN}" --version)"
ensure_space_agent_checkout
ensure_space_agent_deps
seed_customware
start_bridge
start_space_agent

if wait_for_space_agent; then
  log "Space Agent is ready"
else
  log "Space Agent did not pass health check yet; inspect ${SPACE_LOG_FILE}"
fi

cat <<TXT
Space Agent PWA:
  ${SPACE_URL}

Hermes Fleet space:
  ${SPACE_URL}/#/spaces?id=${HERMES_SPACE_ID}

Hermes bridge (VM-local, reached by Space Agent proxy):
  ${HERMES_SPACE_URL}

Space Agent LLM mode:
  ${HERMES_SPACE_LLM_MODE}

Space Agent max_tokens:
  ${HERMES_SPACE_LLM_MAX_TOKENS}

Hermes seed:
  ${HERMES_SPACE_SEED_HERMES}

SSH tunnel from Windows should forward:
  localhost:${UI_PORT} -> hermes-agent VM 127.0.0.1:${UI_PORT}

Logs:
  Space Agent: ${SPACE_LOG_FILE}
  Hermes bridge: ${BRIDGE_LOG_FILE}
TXT
