#!/usr/bin/env bash
# Load only non-secret wasm-agent deployment coordinates from wa.env.

wasm_agent_env_value() {
  local name="${1}"
  local path="${2}"
  [[ -f "${path}" ]] || return 1
  awk -v key="${name}" '
    $0 ~ "^[[:space:]]*" key "=" {
      value = $0
      sub("^[[:space:]]*" key "=[[:space:]]*", "", value)
      sub("[[:space:]]*$", "", value)
      if (value ~ /^\047.*\047$/ || value ~ /^\".*\"$/) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "${path}"
}

wasm_agent_load_deployment_env() {
  local path="${HERMES_WASM_AGENT_ENV_PATH:-${1}}"
  local name value
  for name in \
    HERMES_WASM_AGENT_DEPLOYMENT_MODE \
    HERMES_WASM_AGENT_CLOUD_STATE_ROOT \
    HERMES_WASM_AGENT_CLOUD_INSTANCE_ID \
    HERMES_WASM_AGENT_PUBLIC_ORIGIN; do
    [[ -n "${!name:-}" ]] && continue
    value="$(wasm_agent_env_value "${name}" "${path}" || true)"
    [[ -z "${value}" ]] && continue
    printf -v "${name}" '%s' "${value}"
    export "${name}"
  done
  if [[ -z "${HERMES_WASM_AGENT_ENV_PATH:-}" \
    && "${HERMES_WASM_AGENT_DEPLOYMENT_MODE:-local}" != "cloud" \
    && -f "${path}" ]]; then
    export HERMES_WASM_AGENT_ENV_PATH="${path}"
  fi
}
