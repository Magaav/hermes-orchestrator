#!/usr/bin/env bash
# ============================================================
# restore_hermes_state.sh
# Downloads latest node backup from Google Drive and restores
# .hermes/ state (configs, sessions, memory, hooks, auth).
#
# Does NOT restore: hermes-agent runtime, workspace, logs,
# node metadata (.clone-meta, .config, .runtime) — these are
# rebuilt on node start.
#
# Usage:
#   ./restore_hermes_state.sh                  # restore orchestrator (default)
#   ./restore_hermes_state.sh <node_name>      # restore specific node
#   ./restore_hermes_state.sh --dry-run         # show what would be restored
#   ./restore_hermes_state.sh --verify          # verify latest archive structure
#
# Required env vars (in /local/state/orchestrator/backup_nodes_to_gdrive.env):
#   DAILY_FOLDER_ID, ORCH_FOLDER_ID, BACKUPS_FOLDER_ID
# Credentials loaded from: /local/agents/envs/orchestrator.env
#   GOOGLE_OAuth_CLIENT_ID, GOOGLE_OAuth_CLIENT_SECRET, GOOGLE_OAuth_REFRESH_TOKEN
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BACKUP_CONFIG_FILE:-/local/state/orchestrator/backup_nodes_to_gdrive.env}"
ORCH_ENV_FILE="${ORCHESTRATOR_ENV_FILE:-/local/agents/envs/orchestrator.env}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/backups/orchestrator/daily}"

TARGET_NODE="${1:-orchestrator}"
DRY_RUN="${DRY_RUN:-}"
VERIFY_ONLY="${VERIFY_ONLY:-}"

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOGFILE="/tmp/restore_hermes_${TIMESTAMP}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$CONFIG_FILE"
    else
        echo "ERROR: Config not found: $CONFIG_FILE" >&2
        exit 1
    fi
}

load_credentials() {
    if [[ ! -f "$ORCH_ENV_FILE" ]]; then
        echo "ERROR: Orchestrator env not found: $ORCH_ENV_FILE" >&2
        exit 1
    fi

    GOOGLE_CLIENT_ID="$(grep "^GOOGLE_OAuth_CLIENT_ID=" "$ORCH_ENV_FILE" | cut -d= -f2-)"
    GOOGLE_CLIENT_SECRET="$(grep "^GOOGLE_OAuth_CLIENT_SECRET=" "$ORCH_ENV_FILE" | cut -d= -f2-)"
    GOOGLE_REFRESH_TOKEN="$(grep "^GOOGLE_OAuth_REFRESH_TOKEN=" "$ORCH_ENV_FILE" | cut -d= -f2-)"
    ORCH_DISCORD_BOT_TOKEN="$(grep "^DISCORD_BOT_TOKEN=" "$ORCH_ENV_FILE" | cut -d= -f2-)"

    export GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN
}

get_access_token() {
    curl -s -X POST "https://oauth2.googleapis.com/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "client_id=${GOOGLE_CLIENT_ID}&client_secret=${GOOGLE_CLIENT_SECRET}&refresh_token=${GOOGLE_REFRESH_TOKEN}&grant_type=refresh_token" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token','ERROR:'+str(d)))"
}

gdrive_download() {
    local file_id="$1"
    local dest="$2"
    local access_token="$3"

    log "Downloading $file_id → $dest"
    curl -s "https://www.googleapis.com/drive/v3/files/${file_id}?alt=media" \
        -H "Authorization: Bearer ${access_token}" \
        -o "$dest"
}

gdrive_list_latest() {
    local folder_id="$1"
    local access_token="$2"

    # Use curl -G with --data-urlencode (same pattern that works in backup script's delete function)
    curl -s "https://www.googleapis.com/drive/v3/files" \
        -G \
        --data-urlencode "q='${folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'" \
        --data "fields=files(id,name,size)&pageSize=10" \
        -H "Authorization: Bearer ${access_token}" \
        | python3 -c "
import sys,json
data = json.load(sys.stdin)
files = data.get('files', [])
for f in sorted(files, key=lambda x: x['name'], reverse=True):
    print(f['id'], f['name'], f.get('size','?'), 'bytes')
"
}

verify_archive_structure() {
    local archive="$1"
    log "=== Verifying archive structure ==="

    local structure
    structure=$(tar -tzf "$archive" | head -30)
    echo "$structure" | tee -a "$LOGFILE"

    local has_agents
    has_agents=$(echo "$structure" | grep -c '^agents/' || true)
    local has_hermes
    has_hermes=$(echo "$structure" | grep -c 'agents/nodes/[^/]*/.hermes/' || true)
    local has_registry
    has_registry=$(echo "$structure" | grep -c 'agents/registry.json' || true)

    log "agents/ wrapper present: $has_agents"
    log "agents/nodes/<node>/.hermes/ present: $has_hermes"
    log "agents/registry.json present: $has_registry"

    if [[ "$has_agents" -gt 0 && "$has_hermes" -gt 0 ]]; then
        log "✅ Archive structure is valid for restore"
        return 0
    else
        log "❌ Archive structure is NOT compatible with horc restore"
        return 1
    fi
}

restore_node() {
    local node="$1"
    local archive="$2"

    log "=== Restoring .hermes/ state for node: $node ==="

    local stage_dir
    stage_dir="$(mktemp -d)"
    log "Staging at: $stage_dir"

    # Extract archive
    tar -xzf "$archive" -C "$stage_dir" 2>&1 | tee -a "$LOGFILE"

    # Verify structure
    if [[ ! -d "$stage_dir/agents/nodes/$node/.hermes" ]]; then
        log "ERROR: No .hermes/ found for node '$node' in archive"
        log "Available nodes in archive:"
        ls "$stage_dir/agents/nodes/" 2>/dev/null | tee -a "$LOGFILE"
        rm -rf "$stage_dir"
        return 1
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        log "=== DRY RUN — showing what would be restored ==="
        log "Source: $stage_dir/agents/nodes/$node/.hermes/"
        log "Dest:   /local/agents/nodes/$node/.hermes/"
        log ""
        log "Files that would be updated:"
        diff -rq "$stage_dir/agents/nodes/$node/.hermes/" "/local/agents/nodes/$node/.hermes/" 2>/dev/null | head -30 || true
        log ""
        log "Files only in backup (would be added):"
        diff -rq "$stage_dir/agents/nodes/$node/.hermes/" "/local/agents/nodes/$node/.hermes/" 2>/dev/null | grep "Only in" | head -20 || true
        rm -rf "$stage_dir"
        return 0
    fi

    # Backup current state first
    local backup_ts
    backup_ts="$(date '+%Y%m%d_%H%M%S')"
    local pre_backup="/backups/orchestrator/pre-restore-${node}-${backup_ts}.tar.gz"
    log "Backing up current .hermes/ to $pre_backup"
    mkdir -p "$(dirname "$pre_backup")"
    tar -czf "$pre_backup" \
        --exclude='*.db-wal' \
        --exclude='*.db-shm' \
        -C /local/agents/nodes "$node/.hermes" 2>/dev/null || true

    # Stop the node if running
    local was_running=0
    if systemctl is-active "hermes-node@${node}.service" &>/dev/null; then
        log "Stopping hermes-node@${node}.service..."
        systemctl stop "hermes-node@${node}.service" || true
        was_running=1
    fi

    # Restore .hermes/ using rsync (preserves timestamps, handles in-place updates)
    log "Syncing .hermes/ state..."
    rsync -av \
        --exclude='*.db-wal' \
        --exclude='*.db-shm' \
        --exclude='gateway.pid' \
        --exclude='gateway.sock' \
        "$stage_dir/agents/nodes/$node/.hermes/" \
        "/local/agents/nodes/$node/.hermes/" 2>&1 | tee -a "$LOGFILE"

    rm -rf "$stage_dir"

    # Restart node if it was running
    if [[ "$was_running" -eq 1 ]]; then
        log "Restarting hermes-node@${node}.service..."
        systemctl start "hermes-node@${node}.service" || true
    fi

    log "✅ Restore complete for node: $node"
    log "   Pre-restore backup: $pre_backup"
}

main() {
    log "========== restore_hermes_state.sh =========="

    if [[ "$TARGET_NODE" == "--dry-run" ]]; then
        DRY_RUN=1
        TARGET_NODE="orchestrator"
    elif [[ "$TARGET_NODE" == "--verify" ]]; then
        VERIFY_ONLY=1
        TARGET_NODE="orchestrator"
    fi

    load_config
    load_credentials

    log "Config: $CONFIG_FILE"
    log "Target node: $TARGET_NODE"
    mkdir -p "$BACKUP_LOCAL_DIR"

    # Get fresh OAuth token
    log "Fetching OAuth2 access token..."
    ACCESS_TOKEN="$(get_access_token)" || {
        log "ERROR: Failed to get OAuth2 access token"
        exit 1
    }
    if [[ ! "$ACCESS_TOKEN" =~ ^ya29 ]]; then
        log "ERROR: OAuth token invalid: $ACCESS_TOKEN"
        exit 1
    fi
    log "Access token obtained."

    # Find latest backup in Drive
    log "Finding latest backup in DAILY_FOLDER_ID..."
    local latest_info
    latest_info="$(gdrive_list_latest "$DAILY_FOLDER_ID" "$ACCESS_TOKEN" | head -1)" || {
        log "ERROR: Failed to list Drive backups"
        exit 1
    }

    if [[ -z "$latest_info" ]]; then
        log "ERROR: No backups found in Drive DAILY_FOLDER_ID"
        exit 1
    fi

    local file_id file_name file_size
    file_id="$(echo "$latest_info" | cut -d' ' -f1)"
    file_name="$(echo "$latest_info" | cut -d' ' -f2)"
    file_size="$(echo "$latest_info" | cut -d' ' -f3)"
    log "Latest backup: $file_name ($((file_size / 1024 / 1024))MB)"

    local archive_path="$BACKUP_LOCAL_DIR/$file_name"

    # Download (skip if already downloaded and recent)
    if [[ -f "$archive_path" ]]; then
        log "Archive already exists locally: $archive_path"
    else
        gdrive_download "$file_id" "$archive_path" "$ACCESS_TOKEN"
    fi

    # Verify or dry-run
    if [[ "$VERIFY_ONLY" == "1" ]]; then
        verify_archive_structure "$archive_path"
        exit $?
    fi

    verify_archive_structure "$archive_path" || {
        log "WARNING: Archive structure check failed, continuing anyway..."
    }

    restore_node "$TARGET_NODE" "$archive_path"

    log "========== Done =========="
}

main "$@"
