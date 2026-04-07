#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/local/workspace"
ENV_FILE="$PROJECT_DIR/.env"
PAYLOAD_FILE="${1:-$PROJECT_DIR/discord/discord_commands.json}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] .env not found at $ENV_FILE" >&2
  exit 1
fi

if [[ ! -f "$PAYLOAD_FILE" ]]; then
  echo "[error] JSON payload not found at $PAYLOAD_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

APP_ID="${DISCORD_APP_ID:-}"
GUILD_ID="${DISCORD_SERVER_ID:-${DISCORD_GUILD_ID:-}}"
BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"

if [[ -z "$APP_ID" || -z "$GUILD_ID" || -z "$BOT_TOKEN" ]]; then
  echo "[error] missing required .env vars: DISCORD_APP_ID, DISCORD_SERVER_ID (or DISCORD_GUILD_ID), DISCORD_BOT_TOKEN" >&2
  exit 1
fi

URL="https://discord.com/api/v10/applications/$APP_ID/guilds/$GUILD_ID/commands"
RESP_FILE="/tmp/discord_cmds_resp.json"

# Important: do not send a custom User-Agent here (can trigger 40333 in this environment)
HTTP_CODE=$(curl -sS -o "$RESP_FILE" -w "%{http_code}" \
  -X PUT "$URL" \
  -H "Authorization: Bot $BOT_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary "@$PAYLOAD_FILE")

echo "[info] HTTP $HTTP_CODE"
python3 - <<'PY'
from pathlib import Path
p = Path('/tmp/discord_cmds_resp.json')
print(p.read_text(errors='ignore')[:2000])
PY

if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "201" ]]; then
  echo "[error] Failed to register commands." >&2
  exit 1
fi

echo "[ok] Commands registered successfully."
