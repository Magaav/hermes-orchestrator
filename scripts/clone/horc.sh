#!/bin/bash
# horc — Hermes Orchestrator Clone Manager wrapper
# This script is the CLI entry point for horc commands.
# It delegates to clone_manager.py.

set -e

HERMES_CLONE_MANAGER_SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-$(dirname "$(readlink -f "$0")/../../scripts/clone/clone_manager.py")}"
PYTHON_BIN="${HERMES_CLONE_PYTHON_BIN:-$(command -v python3 || command -v python || true)}"

if [[ -z "$PYTHON_BIN" ]]; then
    echo "horc: python runtime not found" >&2
    exit 1
fi

# Fallback: try standard locations
if [[ ! -f "$HERMES_CLONE_MANAGER_SCRIPT" ]]; then
    for path in \
        "/local/scripts/clone/clone_manager.py" \
        "/local/hermes-orchestrator/scripts/clone/clone_manager.py" \
        "$HOME/.hermes/hermes-agent/scripts/clone/clone_manager.py"; do
        if [[ -f "$path" ]]; then
            HERMES_CLONE_MANAGER_SCRIPT="$path"
            break
        fi
    done
fi

if [[ ! -f "$HERMES_CLONE_MANAGER_SCRIPT" ]]; then
    echo "horc: clone_manager.py not found" >&2
    echo "Set HERMES_CLONE_MANAGER_SCRIPT to override" >&2
    exit 1
fi

exec "$PYTHON_BIN" "$HERMES_CLONE_MANAGER_SCRIPT" "$@"
