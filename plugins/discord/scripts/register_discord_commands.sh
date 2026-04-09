#!/usr/bin/env bash
set -euo pipefail

# Canonical topology defaults to /local with Discord assets under /local/plugins/discord.
PROJECT_DIR="${COLMEIO_PROJECT_DIR:-/local/workspace}"
if [ ! -d "${PROJECT_DIR}" ] && [ -d "/local/workspace" ]; then
  PROJECT_DIR="/local/workspace"
fi
if [ ! -d "${PROJECT_DIR}" ]; then
  PROJECT_DIR="/local"
fi
HERMES_HOME_DIR="${HERMES_HOME:-${PROJECT_DIR}/.hermes}"

ENV_FILE="${DISCORD_ENV_FILE:-}"
if [[ -z "$ENV_FILE" ]]; then
  for candidate in \
    "${HERMES_HOME_DIR}/.env" \
    "${PROJECT_DIR}/.env" \
    "/local/.env" \
    "/local/workspace/.env"; do
    if [[ -f "$candidate" ]]; then
      ENV_FILE="$candidate"
      break
    fi
  done
fi

NODE_COMMANDS_DIR="${PROJECT_DIR}/plugins/discord/commands"
if [[ ! -d "$NODE_COMMANDS_DIR" && -d "/local/plugins/discord/commands" ]]; then
  NODE_COMMANDS_DIR="/local/plugins/discord/commands"
fi

PAYLOAD_FILE="${1:-${DISCORD_COMMANDS_FILE:-${PROJECT_DIR}/plugins/discord/discord_commands.json}}"
if [[ -z "${1:-}" && -z "${DISCORD_COMMANDS_FILE:-}" ]]; then
  PROFILE_NAME="${DISCORD_COMMANDS_PROFILE:-${COLMEIO_CLONE_NAME:-}}"
  if [[ -z "$PROFILE_NAME" && -n "$ENV_FILE" ]]; then
    PROFILE_NAME="$(basename "$ENV_FILE" .env)"
  fi
  PROFILE_NAME="${PROFILE_NAME%.json}"
  if [[ -n "$PROFILE_NAME" && -f "${NODE_COMMANDS_DIR}/${PROFILE_NAME}.json" ]]; then
    PAYLOAD_FILE="${NODE_COMMANDS_DIR}/${PROFILE_NAME}.json"
  fi
fi
if [[ ! -f "$PAYLOAD_FILE" && -f "/local/plugins/discord/discord_commands.json" ]]; then
  PAYLOAD_FILE="/local/plugins/discord/discord_commands.json"
fi
if [[ ! -f "$PAYLOAD_FILE" && -f "/local/workspace/discord/discord_commands.json" ]]; then
  PAYLOAD_FILE="/local/workspace/discord/discord_commands.json"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] .env not found (checked HERMES_HOME/.env, /local/.env legacy fallbacks)" >&2
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
head -c 2000 "$RESP_FILE" || true
echo

if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "201" ]]; then
  echo "[error] Failed to register commands." >&2
  exit 1
fi

echo "[ok] Commands registered successfully."
