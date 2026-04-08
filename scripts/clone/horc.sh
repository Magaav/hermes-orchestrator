#!/usr/bin/env bash
# horc — Hermes Orchestrator CLI wrapper

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_MANAGER="${SCRIPT_DIR}/clone_manager.py"
HERMES_CLONE_MANAGER_SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-${DEFAULT_MANAGER}}"
DEFAULT_NODE="${HERMES_DEFAULT_NODE:-orchestrator}"

if [[ ! -f "${HERMES_CLONE_MANAGER_SCRIPT}" ]]; then
  for path in \
    "/local/scripts/clone/clone_manager.py" \
    "/local/hermes-orchestrator/scripts/clone/clone_manager.py" \
    "$HOME/.hermes/hermes-agent/scripts/clone/clone_manager.py"; do
    if [[ -f "${path}" ]]; then
      HERMES_CLONE_MANAGER_SCRIPT="${path}"
      break
    fi
  done
fi

if [[ ! -f "${HERMES_CLONE_MANAGER_SCRIPT}" ]]; then
  echo "horc: clone_manager.py not found" >&2
  echo "set HERMES_CLONE_MANAGER_SCRIPT to override" >&2
  exit 1
fi

if [[ -n "${HERMES_CLONE_PYTHON_BIN:-}" && -x "${HERMES_CLONE_PYTHON_BIN}" ]]; then
  PYTHON_BIN="${HERMES_CLONE_PYTHON_BIN}"
elif [[ -x "/local/hermes-agent/.venv/bin/python3" ]]; then
  PYTHON_BIN="/local/hermes-agent/.venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "horc: python runtime not found" >&2
  exit 1
fi

usage() {
  cat <<'EOF'
horc — Hermes Orchestrator CLI

Usage:
  horc start [name] [--image IMAGE]
  horc status [name]
  horc stop [name]
  horc delete [name]
  horc logs [name] [--lines N]

Examples:
  horc start
  horc status
  horc start node1
  horc logs node1 --lines 120

Notes:
  - If name is omitted, 'orchestrator' is used.
  - 'horc start' bootstraps host orchestrator from /local/agents/envs/orchestrator.env.
EOF
}

ACTION="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${ACTION}" in
  start|status|stop|delete|logs)
    if [[ "${1:-}" == "--name" ]]; then
      exec "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "${ACTION}" "$@"
    fi

    NAME="${DEFAULT_NODE}"
    if [[ $# -gt 0 && "${1}" != --* ]]; then
      NAME="${1}"
      shift
    fi
    exec "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "${ACTION}" --name "${NAME}" "$@"
    ;;
  help|-h|--help)
    usage
    exit 0
    ;;
  *)
    echo "horc: unknown command '${ACTION}'" >&2
    usage >&2
    exit 2
    ;;
esac
