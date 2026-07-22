#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "${ROOT}/plugins/wasm-agent/scripts/deployment_env.sh"

fixture="${ROOT}/plugins/wasm-agent/tests/fixtures/wasm_agent_deployment_env.txt"

unset HERMES_WASM_AGENT_ENV_PATH HERMES_WASM_AGENT_DEPLOYMENT_MODE
unset HERMES_WASM_AGENT_CLOUD_STATE_ROOT HERMES_WASM_AGENT_CLOUD_INSTANCE_ID
unset HERMES_WASM_AGENT_PUBLIC_ORIGIN OPENAI_API_KEY
wasm_agent_load_deployment_env "${fixture}"

[[ "${HERMES_WASM_AGENT_DEPLOYMENT_MODE}" == "cloud" ]]
[[ "${HERMES_WASM_AGENT_CLOUD_STATE_ROOT}" == "/srv/private/wasm-agent" ]]
[[ "${HERMES_WASM_AGENT_CLOUD_INSTANCE_ID}" == "production" ]]
[[ "${HERMES_WASM_AGENT_PUBLIC_ORIGIN}" == "https://wa.colmeio.com" ]]
[[ -z "${HERMES_WASM_AGENT_ENV_PATH:-}" ]]
[[ -z "${OPENAI_API_KEY:-}" ]]

HERMES_WASM_AGENT_DEPLOYMENT_MODE=local
export HERMES_WASM_AGENT_DEPLOYMENT_MODE
wasm_agent_load_deployment_env "${fixture}"
[[ "${HERMES_WASM_AGENT_DEPLOYMENT_MODE}" == "local" ]]
[[ "${HERMES_WASM_AGENT_ENV_PATH}" == "${fixture}" ]]
