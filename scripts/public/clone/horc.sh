#!/usr/bin/env bash
# horc — Hermes Orchestrator CLI wrapper

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_MANAGER="${SCRIPT_DIR}/clone_manager.py"
HERMES_CLONE_MANAGER_SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-${DEFAULT_MANAGER}}"
DEFAULT_NODE="${HERMES_DEFAULT_NODE:-orchestrator}"

if [[ ! -f "${HERMES_CLONE_MANAGER_SCRIPT}" ]]; then
  for path in \
    "/local/scripts/public/clone/clone_manager.py" \
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

manager() {
  "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "$@"
}

exec_manager() {
  exec "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "$@"
}

usage() {
  cat <<'TXT'
horc — Hermes Orchestrator CLI

Usage:
  horc start [name] [--image IMAGE]
  horc status [name]
  horc stop [name]
  horc restart [all|name] [--image IMAGE]
  horc delete [name]
  horc purge-node <name>
  horc purge-node confirm <request-id> --token TOKEN
  horc logs [name] [--lines N]
  horc logs clean [name|all]
  horc backup all
  horc backup node <name>
  horc backup <name>
  horc restore <path>
  horc update [help]
  horc update all [--force]
  horc update node <name> [--force]

Examples:
  horc start
  horc restart
  horc restart orchestrator
  horc start node1
  horc logs node1 --lines 120
  horc logs clean
  horc logs clean node1
  horc purge-node node1
  horc purge-node confirm purge-node1-20260418T150000Z-abc123 --token deadbeefcafebabe
  horc backup all
  horc backup node node1
  horc restore /local/backups/horc-backup-node-node1-20260101T000000Z.tar.gz
  horc update help
  horc update all
  horc update all --force
  horc update node orchestrator
  horc update node colmeio --force

Notes:
  - For start/status/stop/delete/logs, if name is omitted, 'orchestrator' is used.
  - 'purge-node' is destructive and always requires an explicit second confirmation step.
  - For restart, omitted name means "restart all nodes".
  - `horc update all` refreshes /local/hermes-agent and reseeds every node.
  - `horc update node <name>` refreshes /local/hermes-agent and reseeds only that node.
  - Add `--force` to discard local `/local/hermes-agent` checkout changes during the refresh.
  - Backups are written under /local/backups.
  - Restore accepts either an absolute path or a filename under /local/backups.
  - Compatibility alias: 'hord' runs the same commands as 'horc'.
TXT
}

update_usage() {
  cat <<'TXT'
horc update — Simplified Hermes fleet update

Usage:
  horc update [help]
  horc update all [--force]
  horc update node <name> [--force]

Examples:
  horc update help
  horc update all
  horc update all --force
  horc update node orchestrator
  horc update node colmeio --force

Behavior:
  - Refreshes /local/hermes-agent from the configured upstream repo/branch.
  - `all` forces a safe reseed on every node.
  - `node <name>` forces a safe reseed only on the named node.
  - `--force` discards local `/local/hermes-agent` checkout changes before mirroring upstream.
  - Registry metadata is reconciled at /local/agents/registry.json.
TXT
}

resolve_name_and_exec() {
  local action="$1"
  shift

  if [[ "${1:-}" == "--name" ]]; then
    exec_manager "${action}" "$@"
  fi

  local name="${DEFAULT_NODE}"
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    name="${1}"
    shift
  fi

  exec_manager "${action}" --name "${name}" "$@"
}

resolve_name_and_run() {
  local action="$1"
  shift

  if [[ "${1:-}" == "--name" ]]; then
    manager "${action}" "$@"
    return
  fi

  local name="${DEFAULT_NODE}"
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    name="${1}"
    shift
  fi

  manager "${action}" --name "${name}" "$@"
}

discover_restart_nodes() {
  local env_root="${HERMES_AGENTS_ENVS_ROOT:-/local/agents/envs}"
  local nodes_root="${HERMES_AGENTS_NODES_ROOT:-/local/agents/nodes}"
  declare -A seen=()
  local ordered=()

  if [[ -d "${env_root}" ]]; then
    while IFS= read -r file; do
      local name="${file%.env}"
      [[ -z "${name}" ]] && continue
      if [[ -z "${seen[${name}]:-}" ]]; then
        seen["${name}"]=1
        ordered+=("${name}")
      fi
    done < <(find "${env_root}" -maxdepth 1 -type f -name '*.env' -printf '%f\n' | sort)
  fi

  if [[ -d "${nodes_root}" ]]; then
    while IFS= read -r name; do
      [[ -z "${name}" ]] && continue
      if [[ -z "${seen[${name}]:-}" ]]; then
        seen["${name}"]=1
        ordered+=("${name}")
      fi
    done < <(find "${nodes_root}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  fi

  if [[ ${#ordered[@]} -eq 0 ]]; then
    ordered=("${DEFAULT_NODE}")
  fi

  printf '%s\n' "${ordered[@]}"
}

restart_all_nodes() {
  local -a start_args=("$@")
  local -a nodes=()
  mapfile -t nodes < <(discover_restart_nodes)

  local -a workers=()
  local orchestrator_present=0
  for name in "${nodes[@]}"; do
    if [[ "${name}" == "orchestrator" ]]; then
      orchestrator_present=1
    else
      workers+=("${name}")
    fi
  done

  for name in "${workers[@]}"; do
    manager stop --name "${name}" >/dev/null || true
  done
  if [[ "${orchestrator_present}" -eq 1 ]]; then
    manager stop --name orchestrator >/dev/null || true
  fi

  if [[ "${orchestrator_present}" -eq 1 ]]; then
    manager start --name orchestrator "${start_args[@]}"
  fi
  for name in "${workers[@]}"; do
    manager start --name "${name}" "${start_args[@]}"
  done
}

ACTION="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${ACTION}" in
  start|status|stop|delete)
    resolve_name_and_exec "${ACTION}" "$@"
    ;;
  purge-node)
    SUBACTION="${1:-}"
    if [[ "${SUBACTION}" == "confirm" ]]; then
      if [[ $# -lt 2 ]]; then
        echo "horc: purge-node confirm requires <request-id>" >&2
        usage >&2
        exit 2
      fi
      REQUEST_ID="${2}"
      shift 2
      exec_manager purge-node-confirm --run-id "${REQUEST_ID}" "$@"
    fi
    TARGET_NAME="${1:-}"
    if [[ -z "${TARGET_NAME}" || "${TARGET_NAME}" == --* ]]; then
      echo "horc: purge-node requires <name>" >&2
      usage >&2
      exit 2
    fi
    shift
    exec_manager purge-node-request --name "${TARGET_NAME}" "$@"
    ;;
  logs)
    if [[ "${1:-}" == "clean" ]]; then
      shift
      if [[ $# -eq 0 ]]; then
        exec_manager logs --clean --all
      fi
      if [[ "${1:-}" == "all" || "${1:-}" == "*" ]]; then
        shift
        exec_manager logs --clean --all "$@"
      fi
      if [[ "${1:-}" == --* ]]; then
        exec_manager logs --clean "$@"
      fi
      NAME="${1}"
      shift
      exec_manager logs --clean --name "${NAME}" "$@"
    fi
    resolve_name_and_exec logs "$@"
    ;;
  restart)
    if [[ "${1:-}" == "--name" ]]; then
      resolve_name_and_run stop "$@" >/dev/null
      resolve_name_and_exec start "$@"
    fi
    if [[ $# -eq 0 || "${1:-}" == "all" || "${1:-}" == "--all" || "${1:-}" == --* ]]; then
      if [[ "${1:-}" == "all" || "${1:-}" == "--all" ]]; then
        shift
      fi
      restart_all_nodes "$@"
      exit 0
    fi
    resolve_name_and_run stop "$@" >/dev/null
    resolve_name_and_exec start "$@"
    ;;
  update)
    SUBACTION="${1:-}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    if [[ -z "${SUBACTION}" || "${SUBACTION}" == "help" || "${SUBACTION}" == "--help" || "${SUBACTION}" == "-h" ]]; then
      update_usage
      exit 0
    fi
    case "${SUBACTION}" in
      all)
        exec_manager update-all "$@"
        ;;
      node)
        TARGET_NAME="${1:-}"
        if [[ -z "${TARGET_NAME}" || "${TARGET_NAME}" == --* ]]; then
          echo "horc: update node requires <name>" >&2
          update_usage >&2
          exit 2
        fi
        shift
        exec_manager update-node --name "${TARGET_NAME}" "$@"
        ;;
      *)
        echo "horc: unknown update subcommand '${SUBACTION}'" >&2
        update_usage >&2
        exit 2
        ;;
    esac
    ;;
  agent|test|test-update)
    LEGACY_ACTION="${ACTION}"
    if [[ "${ACTION}" == "agent" || "${ACTION}" == "test" ]]; then
      LEGACY_ACTION+=" ${1:-}"
    fi
    echo "horc: legacy command '${LEGACY_ACTION}' has been removed." >&2
    echo "use 'horc update help' for the supported update commands." >&2
    exit 2
    ;;
  update-all|update-node)
    # Internal actions are intentionally not user-facing through horc.
    echo "horc: use 'horc update help', 'horc update all', or 'horc update node <name>'." >&2
    exit 2
    ;;
  backup)
    MODE="${1:-all}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${MODE}" in
      all)
        exec_manager backup --all "$@"
        ;;
      node)
        NAME="${1:-}"
        if [[ -z "${NAME}" ]]; then
          echo "horc: backup node requires <name>" >&2
          usage >&2
          exit 2
        fi
        shift
        exec_manager backup --name "${NAME}" "$@"
        ;;
      *)
        # Convenience alias: `horc backup <name>`
        exec_manager backup --name "${MODE}" "$@"
        ;;
    esac
    ;;
  restore)
    BACKUP_PATH="${1:-}"
    if [[ -z "${BACKUP_PATH}" ]]; then
      echo "horc: restore requires <path>" >&2
      usage >&2
      exit 2
    fi
    shift
    exec_manager restore --path "${BACKUP_PATH}" "$@"
    ;;
  profile)
    echo "horc: profile clone has been retired from operator use." >&2
    echo "use 'horc update help' for supported fleet update commands." >&2
    exit 2
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
