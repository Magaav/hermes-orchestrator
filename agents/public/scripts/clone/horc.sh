#!/usr/bin/env bash
# horc — Hermes Orchestrator CLI wrapper

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${HORC_REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
DEFAULT_MANAGER="${SCRIPT_DIR}/clone_manager.py"
HERMES_CLONE_MANAGER_SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-${DEFAULT_MANAGER}}"
DEFAULT_NODE="${HERMES_DEFAULT_NODE:-orchestrator}"
HORC_REPO_BRANCH="${HORC_REPO_BRANCH:-main}"

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
  horc logs [name] [--lines N]
  horc logs clean [name|all]
  horc backup all
  horc backup node <name>
  horc backup <name>
  horc restore <path>

  horc update
  horc agent update [name] [--source-branch BRANCH]

Examples:
  horc start
  horc restart
  horc restart orchestrator
  horc start node1
  horc logs node1 --lines 120
  horc logs clean
  horc logs clean node1
  horc backup all
  horc backup node node1
  horc restore /local/backups/horc-backup-node-node1-20260101T000000Z.tar.gz

  horc update
  horc agent update
  horc agent update node1

Notes:
  - For start/status/stop/delete/logs, if name is omitted, 'orchestrator' is used.
  - For restart, omitted name means "restart all nodes".
  - 'horc update' updates this repository (/local) from origin/main.
  - 'horc agent update' updates /local/hermes-agent (template for new nodes).
  - 'horc agent update <node>' also syncs that node's hermes-agent and restarts it if running.
  - Backups are written under /local/backups.
  - Restore accepts either an absolute path or a filename under /local/backups.
  - Compatibility alias: 'hord' runs the same commands as 'horc'.
TXT
}

ensure_repo_clean() {
  if ! git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "horc: ${REPO_ROOT} is not a git repository" >&2
    exit 1
  fi
  if ! git -C "${REPO_ROOT}" diff --quiet || ! git -C "${REPO_ROOT}" diff --cached --quiet; then
    echo "horc: repository has local changes at ${REPO_ROOT}" >&2
    echo "commit/stash/discard changes before running 'horc update'" >&2
    exit 1
  fi
}

self_update() {
  ensure_repo_clean
  git -C "${REPO_ROOT}" fetch origin "${HORC_REPO_BRANCH}"
  git -C "${REPO_ROOT}" checkout "${HORC_REPO_BRANCH}"
  git -C "${REPO_ROOT}" pull --ff-only origin "${HORC_REPO_BRANCH}"
  echo "horc: repository updated at ${REPO_ROOT} (${HORC_REPO_BRANCH})"
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
    if [[ $# -gt 0 && "${1}" != --* ]]; then
      # Compatibility for older docs: `horc update node1`
      NAME="${1}"
      shift
      exec_manager update --name "${NAME}" "$@"
    fi
    self_update
    ;;
  agent)
    SUBACTION="${1:-}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${SUBACTION}" in
      update)
        if [[ "${1:-}" == "--name" ]]; then
          exec_manager update "$@"
        fi
        if [[ $# -gt 0 && "${1}" != --* ]]; then
          NAME="${1}"
          shift
          exec_manager update --name "${NAME}" "$@"
        fi
        exec_manager update "$@"
        ;;
      *)
        echo "horc: unknown agent subcommand '${SUBACTION}'" >&2
        usage >&2
        exit 2
        ;;
    esac
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
