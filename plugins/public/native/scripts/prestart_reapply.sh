#!/usr/bin/env bash
set -u

STRICT=0
for arg in "$@"; do
  case "$arg" in
    --strict)
      STRICT=1
      ;;
    *)
      echo "[error] unknown argument: $arg" >&2
      echo "usage: $0 [--strict]" >&2
      exit 2
      ;;
  esac
done

case "${NODE_PLUGINS_STRICT:-0}" in
  1|true|TRUE|yes|YES|on|ON)
    STRICT=1
    ;;
esac

if [[ -n "${HERMES_HOME:-}" ]]; then
  LOG_DIR="${HERMES_HOME}/logs"
  case "${HERMES_HOME}" in
    */.hermes)
      export HOME="${HERMES_HOME%/.hermes}"
      ;;
  esac
else
  LOG_DIR="${HOME:-/root}/.hermes/logs"
fi

LOG_FILE="$LOG_DIR/colmeio-prestart.log"
FAILED_MARKER="$LOG_DIR/colmeio-prestart.failed"

mkdir -p "$LOG_DIR"

AGENT_PYTHON="${HERMES_AGENT_ROOT:-/local/hermes-agent}/.venv/bin/python"
PYTHON_BIN=""
FIRST_EXEC=""
for candidate in \
  "$AGENT_PYTHON" \
  "$(command -v python3 || true)"; do
  if [[ -z "${candidate:-}" || ! -x "$candidate" ]]; then
    continue
  fi
  if [[ -z "$FIRST_EXEC" ]]; then
    FIRST_EXEC="$candidate"
  fi
  if "$candidate" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys
sys.exit(0 if importlib.util.find_spec("yaml") else 1)
PY
  then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$FIRST_EXEC"
fi
if [[ -z "${PYTHON_BIN:-}" || ! -x "$PYTHON_BIN" ]]; then
  echo "[error] python runtime not found for native prestart bootstrap" >&2
  exit 1
fi

NATIVE_PLUGIN_ROOT="${HERMES_NATIVE_PLUGIN_DIR:-/local/plugins/public/native}"
NATIVE_PLUGIN_BOOTSTRAP="${HERMES_NATIVE_PLUGIN_BOOTSTRAP:-$NATIVE_PLUGIN_ROOT/bootstrap_native_plugins.py}"
NATIVE_DISCORD_PLUGIN_ROOT="${HERMES_NATIVE_DISCORD_SLASH_COMMANDS_DIR:-$NATIVE_PLUGIN_ROOT/discord-slash-commands}"
NATIVE_DISCORD_COMMAND_REGISTER="${HERMES_NATIVE_DISCORD_COMMAND_REGISTER:-$NATIVE_DISCORD_PLUGIN_ROOT/scripts/register_guild_plugin_commands.py}"
NATIVE_DISCORD_COMMAND_PRUNE="${HERMES_NATIVE_DISCORD_COMMAND_PRUNE:-$NATIVE_DISCORD_PLUGIN_ROOT/scripts/prune_global_plugin_command_overlaps.py}"
LEGACY_RUNTIME_CLEANUP="${HERMES_NATIVE_LEGACY_RUNTIME_CLEANUP:-$NATIVE_PLUGIN_ROOT/scripts/cleanup_legacy_runtime.py}"

if [[ -n "${HERMES_HOME:-}" ]]; then
  HERMES_ENV_FILE="${HERMES_HOME}/.env"
  HERMES_CONFIG_FILE="${HERMES_HOME}/config.yaml"
else
  HERMES_ENV_FILE="${HOME:-/root}/.hermes/.env"
  HERMES_CONFIG_FILE="${HOME:-/root}/.hermes/config.yaml"
fi

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  echo "[$(timestamp)] $*" | tee -a "$LOG_FILE" >/dev/null
}

run_step() {
  local name="$1"
  shift
  log "STEP $name: $*"
  if "$@" >>"$LOG_FILE" 2>&1; then
    log "OK   $name"
    return 0
  fi
  log "FAIL $name"
  return 1
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
  esac
  return 1
}

read_env_value() {
  local key="$1"
  "$PYTHON_BIN" - "$HERMES_ENV_FILE" "$key" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = sys.argv[2]
pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
value = ""
if path.exists():
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw)
        if not match or match.group(1) != target:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        break
print(value)
PY
}

FAILED=0
rm -f "$FAILED_MARKER"
log "using python runtime: $PYTHON_BIN"
log "using native plugin root: $NATIVE_PLUGIN_ROOT"

if [[ -f "$LEGACY_RUNTIME_CLEANUP" ]]; then
  run_step "legacy_runtime_cleanup" \
    "$PYTHON_BIN" "$LEGACY_RUNTIME_CLEANUP" \
      --hermes-home "${HERMES_HOME:-${HOME:-/root}/.hermes}" || FAILED=1
fi

if [[ -f "$NATIVE_PLUGIN_BOOTSTRAP" ]]; then
  run_step "native_plugin_bootstrap" \
    "$PYTHON_BIN" "$NATIVE_PLUGIN_BOOTSTRAP" \
      --env-file "$HERMES_ENV_FILE" \
      --config-file "$HERMES_CONFIG_FILE" || FAILED=1
else
  log "FAIL native_plugin_bootstrap (missing script: $NATIVE_PLUGIN_BOOTSTRAP)"
  FAILED=1
fi

PLUGIN_DISCORD_SLASH_COMMANDS_ENABLED=0
if is_truthy "$(read_env_value "PLUGIN_DISCORD_SLASH_COMMANDS")"; then
  PLUGIN_DISCORD_SLASH_COMMANDS_ENABLED=1
fi

DISCORD_COMMAND_SYNC_POLICY_VALUE="$(read_env_value "DISCORD_COMMAND_SYNC_POLICY")"
DISCORD_COMMAND_SYNC_POLICY_VALUE="${DISCORD_COMMAND_SYNC_POLICY_VALUE,,}"
DISCORD_APP_ID_VALUE="$(read_env_value "DISCORD_APP_ID")"
DISCORD_SERVER_ID_VALUE="$(read_env_value "DISCORD_SERVER_ID")"
DISCORD_BOT_TOKEN_VALUE="$(read_env_value "DISCORD_BOT_TOKEN")"

if [[ "$PLUGIN_DISCORD_SLASH_COMMANDS_ENABLED" -eq 1 && -f "$NATIVE_DISCORD_COMMAND_REGISTER" ]]; then
  if [[ -n "$DISCORD_APP_ID_VALUE" && -n "$DISCORD_SERVER_ID_VALUE" && -n "$DISCORD_BOT_TOKEN_VALUE" ]]; then
    run_step "discord_plugin_command_sync" \
      "$PYTHON_BIN" "$NATIVE_DISCORD_COMMAND_REGISTER" \
        --env-file "$HERMES_ENV_FILE" \
        --mode safe \
        --scope guild || FAILED=1
    if [[ -f "$NATIVE_DISCORD_COMMAND_PRUNE" ]]; then
      nohup "$PYTHON_BIN" "$NATIVE_DISCORD_COMMAND_PRUNE" \
        --env-file "$HERMES_ENV_FILE" \
        --delay 12 >>"$LOG_FILE" 2>&1 &
      log "spawned discord_plugin_command_prune background helper"
    else
      log "skip discord_plugin_command_prune (missing script: $NATIVE_DISCORD_COMMAND_PRUNE)"
    fi
  else
    log "skip discord_plugin_command_sync (missing Discord env for structured guild overlay; policy=${DISCORD_COMMAND_SYNC_POLICY_VALUE:-safe})"
  fi
elif [[ "$PLUGIN_DISCORD_SLASH_COMMANDS_ENABLED" -eq 1 ]]; then
  log "skip discord_plugin_command_sync (missing script: $NATIVE_DISCORD_COMMAND_REGISTER)"
fi

if [[ "$FAILED" -ne 0 ]]; then
  log "WARN one or more native prestart steps failed; gateway will still start"
  printf "%s\n" "failed at $(timestamp)" >"$FAILED_MARKER"
  if [[ "$STRICT" -eq 1 ]]; then
    exit 1
  fi
else
  log "DONE all native prestart steps succeeded"
fi

exit 0
