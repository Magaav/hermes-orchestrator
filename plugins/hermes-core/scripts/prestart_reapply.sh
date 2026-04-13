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

# Prefer explicit HERMES_HOME when available (clone containers), otherwise
# fallback to the legacy HOME/.hermes location.
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
  echo "[error] python runtime not found for prestart reapply" >&2
  exit 1
fi

# Shared plugin root (new default) with legacy fallback.
DISCORD_PLUGIN_ROOT="${HERMES_DISCORD_PLUGIN_DIR:-/local/plugins/discord}"
if [[ ! -d "$DISCORD_PLUGIN_ROOT" && -d "/local/workspace/discord" ]]; then
  DISCORD_PLUGIN_ROOT="/local/workspace/discord"
fi

# Optional Hermes-core plugin root (followup summary + final footer patching).
HERMES_CORE_PLUGIN_ROOT="${HERMES_CORE_PLUGIN_DIR:-/local/plugins/hermes-core}"
if [[ ! -d "$HERMES_CORE_PLUGIN_ROOT" && -d "/local/workspace/hermes-core" ]]; then
  HERMES_CORE_PLUGIN_ROOT="/local/workspace/hermes-core"
fi

# Explicitly expose clone code root for patch scripts.
export HERMES_AGENT_ROOT="${HERMES_AGENT_ROOT:-/local/hermes-agent}"

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

FAILED=0
rm -f "$FAILED_MARKER"
log "using python runtime: $PYTHON_BIN"
log "using discord plugin root: $DISCORD_PLUGIN_ROOT"
log "using hermes-core plugin root: $HERMES_CORE_PLUGIN_ROOT"

CAMOFOX_BOOTSTRAP="$DISCORD_PLUGIN_ROOT/scripts/camofox_env_bootstrap.py"
OPENVIKING_BOOTSTRAP="$DISCORD_PLUGIN_ROOT/scripts/openviking_env_bootstrap.py"
MODEL_BOOTSTRAP="$DISCORD_PLUGIN_ROOT/scripts/model_env_bootstrap.py"
SST_BOOTSTRAP="$DISCORD_PLUGIN_ROOT/scripts/stt_env_bootstrap.py"
if [[ -n "${HERMES_HOME:-}" ]]; then
  HERMES_ENV_FILE="${HERMES_HOME}/.env"
  HERMES_CONFIG_FILE="${HERMES_HOME}/config.yaml"
else
  HERMES_ENV_FILE="${HOME:-/root}/.hermes/.env"
  HERMES_CONFIG_FILE="${HOME:-/root}/.hermes/config.yaml"
fi
if [[ -f "/.dockerenv" ]]; then
  CAMOFOX_DEFAULT_URL="http://host.docker.internal:9377"
  OPENVIKING_DEFAULT_ENDPOINT="http://host.docker.internal:1933"
else
  CAMOFOX_DEFAULT_URL="http://127.0.0.1:9377"
  OPENVIKING_DEFAULT_ENDPOINT="http://127.0.0.1:1933"
fi

CAMOFOX_ENSURE_RAW="${CAMOFOX_ENSURE_SERVICE:-${BROWSER_CAMOFOX_ENSURE_SERVICE:-0}}"
CAMOFOX_ENSURE_ARGS=()
case "${CAMOFOX_ENSURE_RAW,,}" in
  1|true|yes|on)
    CAMOFOX_ENSURE_ARGS+=(--ensure-service)
    ;;
esac

if [[ -f "$CAMOFOX_BOOTSTRAP" ]]; then
  run_step "camofox_bootstrap" \
    "$PYTHON_BIN" "$CAMOFOX_BOOTSTRAP" \
      --env-file "$HERMES_ENV_FILE" \
      --default-url "$CAMOFOX_DEFAULT_URL" \
      "${CAMOFOX_ENSURE_ARGS[@]}" || FAILED=1
fi

OPENVIKING_DEFAULT_ACCOUNT="${OPENVIKING_ACCOUNT_DEFAULT:-}"
OPENVIKING_DEFAULT_USER="${OPENVIKING_USER_DEFAULT:-}"

if [[ -z "$OPENVIKING_DEFAULT_ACCOUNT" && -z "$OPENVIKING_DEFAULT_USER" ]]; then
  NODE_IDENTITY="${NODE_NAME:-}"
  if [[ -n "$NODE_IDENTITY" ]]; then
    OPENVIKING_DEFAULT_ACCOUNT="$NODE_IDENTITY"
    OPENVIKING_DEFAULT_USER="$NODE_IDENTITY"
  else
    OPENVIKING_DEFAULT_ACCOUNT="default"
    OPENVIKING_DEFAULT_USER="default"
  fi
elif [[ -n "$OPENVIKING_DEFAULT_ACCOUNT" && -z "$OPENVIKING_DEFAULT_USER" ]]; then
  OPENVIKING_DEFAULT_USER="$OPENVIKING_DEFAULT_ACCOUNT"
elif [[ -z "$OPENVIKING_DEFAULT_ACCOUNT" && -n "$OPENVIKING_DEFAULT_USER" ]]; then
  OPENVIKING_DEFAULT_ACCOUNT="$OPENVIKING_DEFAULT_USER"
fi

if [[ -f "$OPENVIKING_BOOTSTRAP" ]]; then
  run_step "openviking_bootstrap" \
    "$PYTHON_BIN" "$OPENVIKING_BOOTSTRAP" \
      --env-file "$HERMES_ENV_FILE" \
      --config-file "$HERMES_CONFIG_FILE" \
      --default-endpoint "$OPENVIKING_DEFAULT_ENDPOINT" \
      --default-account "$OPENVIKING_DEFAULT_ACCOUNT" \
      --default-user "$OPENVIKING_DEFAULT_USER" || FAILED=1
fi

if [[ -f "$MODEL_BOOTSTRAP" ]]; then
  run_step "model_bootstrap" \
    "$PYTHON_BIN" "$MODEL_BOOTSTRAP" \
      --env-file "$HERMES_ENV_FILE" \
      --config-file "$HERMES_CONFIG_FILE" || FAILED=1
fi

if [[ -f "$SST_BOOTSTRAP" ]]; then
  run_step "stt_bootstrap" \
    "$PYTHON_BIN" "$SST_BOOTSTRAP" \
      --env-file "$HERMES_ENV_FILE" \
      --config-file "$HERMES_CONFIG_FILE" || FAILED=1
fi

run_step "channel_acl" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/hooks/apply_channel_acl_run_py.py" || FAILED=1
run_step "gateway_fifo_queue" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_gateway_queue_fifo.py" || FAILED=1
run_step "session_info" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_session_info_hook.py" || FAILED=1
run_step "discord_thread_parent" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_discord_thread_parent_context.py" || FAILED=1
run_step "discord_auto_thread_ignore_channels" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_discord_auto_thread_ignore_channels.py" || FAILED=1
run_step "discord_guild_sync" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_discord_guild_sync.py" || FAILED=1
run_step "discord_command_bootstrap" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_discord_command_bootstrap.py" || FAILED=1
run_step "faltas_confirmation_view" \
  "$PYTHON_BIN" "$DISCORD_PLUGIN_ROOT/scripts/reapply_faltas_confirmation_view.py" || FAILED=1

NODE_AGENT_PATCH_SCRIPT="$HERMES_CORE_PLUGIN_ROOT/scripts/reapply_node_agent_followup_footer.py"
if [[ -f "$NODE_AGENT_PATCH_SCRIPT" ]]; then
  run_step "node_agent_followup_footer" \
    "$PYTHON_BIN" "$NODE_AGENT_PATCH_SCRIPT" || FAILED=1
fi

VERIFY_SCRIPT="$DISCORD_PLUGIN_ROOT/scripts/verify_discord_customizations.py"
if [[ -f "$VERIFY_SCRIPT" ]]; then
  run_step "verify_customizations" \
    "$PYTHON_BIN" "$VERIFY_SCRIPT" || FAILED=1
fi

NODE_AGENT_VERIFY_SCRIPT="$HERMES_CORE_PLUGIN_ROOT/scripts/verify_node_agent_followup_footer.py"
if [[ -f "$NODE_AGENT_VERIFY_SCRIPT" ]]; then
  run_step "verify_node_agent_followup_footer" \
    "$PYTHON_BIN" "$NODE_AGENT_VERIFY_SCRIPT" || FAILED=1
fi

if [[ "$FAILED" -ne 0 ]]; then
  log "WARN one or more prestart patch steps failed; gateway will still start"
  printf "%s\n" "failed at $(timestamp)" >"$FAILED_MARKER"
  if [[ "$STRICT" -eq 1 ]]; then
    exit 1
  fi
else
  log "DONE all prestart patch steps succeeded"
fi

# Do not block gateway startup if a patch step fails.
exit 0
