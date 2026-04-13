#!/usr/bin/env bash
set -euo pipefail

SKIP_SYNC=0
SKIP_RESTART=0

for arg in "$@"; do
  case "$arg" in
    --skip-sync)
      SKIP_SYNC=1
      ;;
    --skip-restart)
      SKIP_RESTART=1
      ;;
    *)
      echo "[error] unknown argument: $arg" >&2
      echo "usage: $0 [--skip-sync] [--skip-restart]" >&2
      exit 2
      ;;
  esac
done

HERMES_REPO="/home/ubuntu/.hermes/hermes-agent"
REAPPLY_SCRIPT="/local/plugins/hermes-core/scripts/prestart_reapply.sh"
VERIFY_SCRIPT="/local/plugins/discord/scripts/verify_discord_customizations.py"
if [[ ! -x "$REAPPLY_SCRIPT" && -x "/local/plugins/discord/scripts/prestart_reapply.sh" ]]; then
  REAPPLY_SCRIPT="/local/plugins/discord/scripts/prestart_reapply.sh"
fi
if [[ ! -x "$REAPPLY_SCRIPT" && -x "/local/workspace/discord/scripts/prestart_reapply.sh" ]]; then
  REAPPLY_SCRIPT="/local/workspace/discord/scripts/prestart_reapply.sh"
fi
if [[ ! -f "$VERIFY_SCRIPT" && -f "/local/workspace/discord/scripts/verify_discord_customizations.py" ]]; then
  VERIFY_SCRIPT="/local/workspace/discord/scripts/verify_discord_customizations.py"
fi
LOG_DIR="/home/ubuntu/.hermes/logs"
LOG_FILE="$LOG_DIR/colmeio-update-and-repatch.log"

mkdir -p "$LOG_DIR"

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
  else
    local rc=$?
    log "FAIL $name (exit=$rc)"
    return "$rc"
  fi
}

if [[ ! -d "$HERMES_REPO/.git" ]]; then
  echo "[error] hermes-agent git repo not found: $HERMES_REPO" >&2
  exit 1
fi
if [[ ! -x "$REAPPLY_SCRIPT" ]]; then
  echo "[error] reapply script not executable: $REAPPLY_SCRIPT" >&2
  exit 1
fi
if [[ ! -f "$VERIFY_SCRIPT" ]]; then
  echo "[error] verify script missing: $VERIFY_SCRIPT" >&2
  exit 1
fi

before_commit="$(git -C "$HERMES_REPO" rev-parse --short HEAD)"
after_commit="$before_commit"

log "START force-sync + repatch flow"
log "Hermes repo: $HERMES_REPO"
log "Commit before sync: $before_commit"

if [[ "$SKIP_SYNC" -eq 0 ]]; then
  run_step "fetch_main" git -C "$HERMES_REPO" fetch --prune origin main
  run_step "checkout_main" git -C "$HERMES_REPO" checkout -f main
  run_step "reset_hard_main" git -C "$HERMES_REPO" reset --hard origin/main
  run_step "clean_untracked" git -C "$HERMES_REPO" clean -fd
  after_commit="$(git -C "$HERMES_REPO" rev-parse --short HEAD)"
  log "Commit after sync: $after_commit"
else
  log "SKIP sync requested; keeping commit: $before_commit"
fi

run_step "reapply_colmeio_patches" /bin/bash "$REAPPLY_SCRIPT" --strict
run_step "verify_customizations" /usr/bin/python3 "$VERIFY_SCRIPT"

if [[ "$SKIP_RESTART" -eq 0 ]]; then
  run_step "restart_gateway" sudo hermes gateway restart --system
  run_step "gateway_service_active" systemctl is-active --quiet hermes-gateway.service
else
  log "SKIP restart requested."
fi

log "DONE force-sync + repatch flow"
echo "[ok] Hermes synced and Colmeio Discord customizations reapplied."
echo "[ok] Commit: ${before_commit} -> ${after_commit}"
echo "[ok] Log: $LOG_FILE"
