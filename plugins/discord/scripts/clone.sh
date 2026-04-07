#!/usr/bin/env bash
set -euo pipefail

SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-/local/scripts/clone/clone_manager.py}"
PYTHON_BIN="${HERMES_CLONE_PYTHON_BIN:-/local/hermes-agent/.venv/bin/python3}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "python runtime not found (set HERMES_CLONE_PYTHON_BIN)" >&2
  exit 1
fi
if [[ ! -f "$SCRIPT" ]]; then
  echo "clone manager script not found: $SCRIPT" >&2
  echo "set HERMES_CLONE_MANAGER_SCRIPT to override" >&2
  exit 1
fi

usage() {
  cat <<'EOF'
Usage:
  bash clone.sh add <name> [extra args...]
  bash clone.sh del <name> [extra args...]
  bash clone.sh <name> [action] [extra args...]

Examples:
  bash clone.sh add colmeio
  bash clone.sh del colmeio
  bash clone.sh colmeio status
  bash clone.sh colmeio logs --lines 120
  bash clone.sh colmeio start --image ubuntu:24.04
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

MODE="$1"
shift || true

NAME=""
ACTION=""
PURGE_AGENT_ROOT=0

case "$MODE" in
  add)
    if [[ $# -lt 1 ]]; then
      echo "missing agent name for 'add'" >&2
      usage
      exit 2
    fi
    NAME="$1"
    shift
    ACTION="start"
    ;;
  del)
    if [[ $# -lt 1 ]]; then
      echo "missing agent name for 'del'" >&2
      usage
      exit 2
    fi
    NAME="$1"
    shift
    ACTION="delete"
    PURGE_AGENT_ROOT=1
    ;;
  *)
    # Backward compatible mode:
    #   bash clone.sh <name> [start|status|stop|delete|logs]
    NAME="$MODE"
    ACTION="start"
    if [[ $# -gt 0 ]]; then
      case "${1}" in
        start|status|stop|delete|logs)
          ACTION="$1"
          shift
          ;;
      esac
    fi
    ;;
esac

AGENTS_ROOT="${HERMES_AGENTS_ROOT:-/local/agents}"
LEGACY_AGENTS_ROOT="/local/clones"

if [[ "$ACTION" == "start" ]]; then
  ENV_FILE="${AGENTS_ROOT%/}/${NAME}.env"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "agent env not found: $ENV_FILE" >&2
    echo "create ${NAME}.env in ${AGENTS_ROOT} before running add/start." >&2
    exit 2
  fi
fi

"$PYTHON_BIN" "$SCRIPT" "$ACTION" --name "$NAME" "$@"
RC=$?

if [[ "$RC" -ne 0 ]]; then
  exit "$RC"
fi

if [[ "$PURGE_AGENT_ROOT" -eq 1 ]]; then
  AGENT_ROOT="${AGENTS_ROOT%/}/${NAME}"
  LEGACY_AGENT_ROOT="${LEGACY_AGENTS_ROOT%/}/${NAME}"
  rm -rf "$AGENT_ROOT" "$LEGACY_AGENT_ROOT"
  echo "purged agent data roots: $AGENT_ROOT $LEGACY_AGENT_ROOT" >&2
fi

exit 0
