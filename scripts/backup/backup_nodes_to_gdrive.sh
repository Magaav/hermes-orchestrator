#!/usr/bin/env bash
# ============================================================
# backup_nodes_to_gdrive.sh
# Shared orchestrator entrypoint for node backups to Google Drive.
#
# Deployment-specific values must be set in:
#   /local/state/orchestrator/backup_nodes_to_gdrive.env
# (see .example template under the same directory).
# ============================================================

set -euo pipefail

DEFAULT_CONFIG_FILE="/local/state/orchestrator/backup_nodes_to_gdrive.env"
CONFIG_FILE="${BACKUP_CONFIG_FILE:-$DEFAULT_CONFIG_FILE}"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"

# Defaults can be overridden from config/env.
BACKUP_LOG_ROOT="${BACKUP_LOG_ROOT:-/logs/attention}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/backups/orchestrator/daily}"
BACKUP_NODES_DIR="${BACKUP_NODES_DIR:-/local/agents/nodes}"
ORCHESTRATOR_ENV_FILE="${ORCHESTRATOR_ENV_FILE:-/local/agents/envs/orchestrator.env}"

LOGFILE="${BACKUP_LOG_ROOT}/backup_nodes_${TIMESTAMP}.log"
ERROR_LOG="${BACKUP_LOG_ROOT}/backup_nodes_ERROR.log"

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$CONFIG_FILE"
    fi
}

require_var() {
    local var_name="$1"
    local help_text="$2"
    if [[ -z "${!var_name:-}" ]]; then
        echo "ERROR: Missing required config '${var_name}'. ${help_text}" >&2
        echo "       Config file: ${CONFIG_FILE}" >&2
        exit 2
    fi
}

read_env_value() {
    local env_file="$1"
    local key="$2"
    local value

    value="$(grep -E "^${key}=" "$env_file" | head -n1 | cut -d= -f2- || true)"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    echo "$value"
}

load_orchestrator_credentials() {
    local env_file="$ORCHESTRATOR_ENV_FILE"

    if [[ ! -f "$env_file" ]]; then
        echo "ERROR: Orchestrator env not found at $env_file" >&2
        exit 2
    fi

    DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-$(read_env_value "$env_file" "DISCORD_BOT_TOKEN")}"
    GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-$(read_env_value "$env_file" "GOOGLE_OAuth_CLIENT_ID")}"
    GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-$(read_env_value "$env_file" "GOOGLE_OAuth_CLIENT_SECRET")}"
    GOOGLE_REFRESH_TOKEN="${GOOGLE_REFRESH_TOKEN:-$(read_env_value "$env_file" "GOOGLE_OAuth_REFRESH_TOKEN")}"

    export DISCORD_BOT_TOKEN GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

notify_discord() {
    local msg="$1"

    if [[ -z "${DISCORD_USER_ID:-}" || -z "${DISCORD_BOT_TOKEN:-}" ]]; then
        log "Discord notification skipped (DISCORD_USER_ID or DISCORD_BOT_TOKEN missing)."
        return 0
    fi

    local dm_payload
    dm_payload="$(python3 -c 'import json,sys; print(json.dumps({"recipients":[sys.argv[1]]}))' "$DISCORD_USER_ID")"

    local dm_channel_id
    dm_channel_id=$(curl -s -X POST "https://discord.com/api/v10/users/${DISCORD_USER_ID}/channels" \
        -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$dm_payload" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

    if [[ -z "$dm_channel_id" ]]; then
        log "WARNING: Could not create/open Discord DM channel"
        return 1
    fi

    local message_payload
    message_payload="$(python3 -c 'import json,sys; print(json.dumps({"content":sys.argv[1]}))' "$msg")"

    local response
    local http_code
    response=$(curl -s -w "%{http_code}" -X POST "https://discord.com/api/v10/channels/${dm_channel_id}/messages" \
        -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$message_payload" 2>&1)
    http_code="${response: -3}"

    if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
        log "Discord DM sent successfully"
    else
        log "WARNING: Failed to send Discord DM: $response"
    fi
}

get_access_token() {
    curl -s -X POST "https://oauth2.googleapis.com/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "client_id=${GOOGLE_CLIENT_ID}&client_secret=${GOOGLE_CLIENT_SECRET}&refresh_token=${GOOGLE_REFRESH_TOKEN}&grant_type=refresh_token" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null
}

gdrive_upload() {
    local file_path="$1"
    local remote_parent_id="$2"
    local access_token="$3"
    local filename

    filename="$(basename "$file_path")"
    curl -s -X POST "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart" \
        -H "Authorization: Bearer ${access_token}" \
        -F "metadata={\"name\":\"${filename}\",\"parents\":[\"${remote_parent_id}\"]};type=application/json;charset=UTF-8" \
        -F "file=@${file_path};type=application/octet-stream" \
        | python3 -c "import sys,json; r=json.load(sys.stdin); print('OK' if 'id' in r else 'FAIL: '+str(r))" 2>/dev/null
}

gdrive_verify_folder() {
    local folder_id="$1"
    local access_token="$2"
    local mime

    mime=$(curl -s "https://www.googleapis.com/drive/v3/files/${folder_id}?fields=mimeType" \
        -H "Authorization: Bearer ${access_token}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('mimeType',''))" 2>/dev/null)

    if [[ "$mime" == "application/vnd.google-apps.folder" ]]; then
        echo "ok"
    else
        echo "missing"
    fi
}

gdrive_delete_all_backups() {
    local folder_id="$1"
    local access_token="$2"
    local query
    local all_files

    query="$(python3 -c "import urllib.parse; print(urllib.parse.quote(\"'${folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'\", safe=''))")"
    all_files=$(curl -s "https://www.googleapis.com/drive/v3/files?q=${query}&fields=files(id,name)&pageSize=100" \
        -H "Authorization: Bearer ${access_token}" \
        | python3 -c "import sys,json; [print(f['id']) for f in json.load(sys.stdin).get('files',[])]" 2>/dev/null) || return 0

    if [[ -z "$all_files" ]]; then
        log "No previous backups to remove."
        return 0
    fi

    for file_id in $all_files; do
        log "Deleting previous backup in Drive: $file_id"
        curl -s -X DELETE "https://www.googleapis.com/drive/v3/files/${file_id}" \
            -H "Authorization: Bearer ${access_token}" > /dev/null 2>&1 || true
    done
}

discover_backup_nodes() {
    if [[ -n "${BACKUP_NODE_LIST:-}" ]]; then
        # Comma/space-separated list.
        read -r -a REQUESTED_NODES <<< "${BACKUP_NODE_LIST//,/ }"
    else
        mapfile -t REQUESTED_NODES < <(find "$BACKUP_NODES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
    fi

    BACKUP_NODES=()
    for node in "${REQUESTED_NODES[@]:-}"; do
        [[ -z "$node" ]] && continue
        if [[ -d "${BACKUP_NODES_DIR}/${node}" ]]; then
            BACKUP_NODES+=("$node")
        else
            log "WARNING: Node '${node}' not found at ${BACKUP_NODES_DIR}/${node}; skipping."
        fi
    done

    if [[ "${#BACKUP_NODES[@]}" -eq 0 ]]; then
        log "ERROR: No nodes available to backup."
        exit 1
    fi
}

on_error() {
    local exit_code=$?
    log "ERROR: Backup failed with exit code ${exit_code}"
    echo "FAIL $(date) exit=${exit_code}" >> "$ERROR_LOG"
    notify_discord "Backup FAILED at ${TIMESTAMP}. Exit code: ${exit_code}. Check logs: ${LOGFILE}"
    exit "$exit_code"
}
trap on_error ERR

main() {
    load_config

    BACKUP_LOG_ROOT="${BACKUP_LOG_ROOT:-/logs/attention}"
    BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/backups/orchestrator/daily}"
    BACKUP_NODES_DIR="${BACKUP_NODES_DIR:-/local/agents/nodes}"
    ORCHESTRATOR_ENV_FILE="${ORCHESTRATOR_ENV_FILE:-/local/agents/envs/orchestrator.env}"

    LOGFILE="${BACKUP_LOG_ROOT}/backup_nodes_${TIMESTAMP}.log"
    ERROR_LOG="${BACKUP_LOG_ROOT}/backup_nodes_ERROR.log"

    mkdir -p "$BACKUP_LOG_ROOT" "$BACKUP_LOCAL_DIR"

    require_var "BACKUPS_FOLDER_ID" "Set Drive folder id for /backups root in state config."
    require_var "ORCH_FOLDER_ID" "Set Drive folder id for /backups/orchestrator in state config."
    require_var "DAILY_FOLDER_ID" "Set Drive folder id for /backups/orchestrator/daily in state config."

    log "========== Starting node backup to Google Drive =========="
    log "Using config: ${CONFIG_FILE}"

    load_orchestrator_credentials

    # Step 1: Get fresh access token.
    log "Fetching OAuth2 access token..."
    ACCESS_TOKEN="$(get_access_token)" || {
        log "ERROR: Failed to get OAuth2 access token"
        echo "FAIL get_access_token $(date)" >> "$ERROR_LOG"
        notify_discord "Backup FAILED at ${TIMESTAMP}. Failed to authenticate with Google OAuth2."
        exit 1
    }

    if [[ -z "$ACCESS_TOKEN" ]]; then
        log "ERROR: OAuth2 access token is empty"
        exit 1
    fi
    log "Access token obtained."

    # Step 2: Verify all configured folder IDs still exist in Drive.
    log "Verifying Drive folder anchors..."
    for folder_info in "BACKUPS_FOLDER_ID:${BACKUPS_FOLDER_ID}" "ORCH_FOLDER_ID:${ORCH_FOLDER_ID}" "DAILY_FOLDER_ID:${DAILY_FOLDER_ID}"; do
        key="${folder_info%%:*}"
        fid="${folder_info##*:}"
        result="$(gdrive_verify_folder "$fid" "$ACCESS_TOKEN")"
        if [[ "$result" != "ok" ]]; then
            log "ERROR: ${key} (${fid}) not found in Drive"
            log "       Aborting to prevent duplicate folder creation"
            echo "FAIL folder_missing ${key} $(date)" >> "$ERROR_LOG"
            notify_discord "Backup FAILED at ${TIMESTAMP}. Drive folder ${key} not found."
            exit 1
        fi
        log "  + ${key}: ${fid} verified"
    done
    log "All Drive folder anchors verified."

    # Step 3: Resolve node set.
    discover_backup_nodes

    # Step 4: Create tarball.
    ARCHIVE_NAME="nodes_backup_${TIMESTAMP}.tar.gz"
    ARCHIVE_PATH="${BACKUP_LOCAL_DIR}/${ARCHIVE_NAME}"

    log "Creating archive at ${ARCHIVE_PATH}"
    for node in "${BACKUP_NODES[@]}"; do
        node_path="${BACKUP_NODES_DIR}/${node}"
        log "  + ${node} ($(du -sh "$node_path" 2>/dev/null | cut -f1))"
    done

    tar -czf "$ARCHIVE_PATH" \
        --exclude='*.tar.gz' \
        --exclude='__pycache__' \
        --exclude='.pyc' \
        --exclude='.git' \
        --exclude='.pytest_cache' \
        --exclude='node_modules' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='.npm' \
        --exclude='.hermes/sessions/*.json' \
        --exclude='.hermes/*.db-wal' \
        --exclude='.hermes/*.db-shm' \
        -C "$BACKUP_NODES_DIR" \
        "${BACKUP_NODES[@]}" \
        2>&1 | tee -a "$LOGFILE"

    if [[ ! -f "$ARCHIVE_PATH" ]]; then
        log "ERROR: Archive was not created"
        exit 1
    fi

    ARCHIVE_SIZE="$(du -sh "$ARCHIVE_PATH" | cut -f1)"
    log "Archive created: ${ARCHIVE_SIZE}"

    # Step 5: Delete prior daily backups in Drive (keep only latest).
    log "Removing previous daily backups in Drive..."
    gdrive_delete_all_backups "$DAILY_FOLDER_ID" "$ACCESS_TOKEN"

    # Step 6: Upload new backup.
    log "Uploading archive to Google Drive..."
    UPLOAD_RESULT="$(gdrive_upload "$ARCHIVE_PATH" "$DAILY_FOLDER_ID" "$ACCESS_TOKEN")"
    if [[ "$UPLOAD_RESULT" == "OK" ]]; then
        log "Upload successful"
    else
        log "ERROR: Upload failed: $UPLOAD_RESULT"
        notify_discord "Backup FAILED at ${TIMESTAMP}. Upload to Google Drive failed: ${UPLOAD_RESULT}"
        exit 1
    fi

    # Step 7: Delete local archive to avoid disk bloat.
    log "Removing local archive..."
    rm -f "$ARCHIVE_PATH"
    if [[ ! -f "$ARCHIVE_PATH" ]]; then
        log "Local archive removed successfully"
    else
        log "WARNING: Failed to remove archive at ${ARCHIVE_PATH}"
    fi

    # Step 8: Prune old backup logs (keep latest 7 timestamped files).
    find "$BACKUP_LOG_ROOT" -name "backup_nodes_[0-9]*.log" -type f | sort -r | tail -n +8 | xargs -r rm -f

    log "========== Backup completed successfully =========="
}

main "$@"
