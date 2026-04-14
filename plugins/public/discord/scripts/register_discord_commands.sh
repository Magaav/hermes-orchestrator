#!/usr/bin/env bash
set -euo pipefail

# Canonical topology defaults to /local with Discord assets split across:
# - public code:  /local/plugins/public/discord
# - private data: /local/plugins/private/discord
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

DISCORD_PRIVATE_ROOT="${HERMES_DISCORD_PRIVATE_DIR:-/local/plugins/private/discord}"
NODE_COMMANDS_DIR="${DISCORD_PRIVATE_ROOT}/commands"

PAYLOAD_FILE="${1:-${DISCORD_COMMANDS_FILE:-}}"
if [[ -z "${1:-}" && -z "${DISCORD_COMMANDS_FILE:-}" ]]; then
  PROFILE_NAME="${NODE_NAME:-}"
  if [[ -z "$PROFILE_NAME" && -n "$ENV_FILE" ]]; then
    PROFILE_NAME="$(basename "$ENV_FILE" .env)"
  fi
  PROFILE_NAME="${PROFILE_NAME%.json}"
  if [[ -n "$PROFILE_NAME" ]]; then
    CANDIDATE="${NODE_COMMANDS_DIR}/${PROFILE_NAME}.json"
    if [[ -f "$CANDIDATE" ]]; then
      PAYLOAD_FILE="$CANDIDATE"
    fi
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] .env not found (checked HERMES_HOME/.env, /local/.env legacy fallbacks)" >&2
  exit 1
fi

if [[ ! -f "$PAYLOAD_FILE" ]]; then
  echo "[error] node payload not found." >&2
  echo "        expected one of:" >&2
  if [[ -n "${DISCORD_COMMANDS_FILE:-}" ]]; then
    echo "        - DISCORD_COMMANDS_FILE=${DISCORD_COMMANDS_FILE}" >&2
  fi
  if [[ -n "${NODE_NAME:-}" ]]; then
    echo "        - ${NODE_COMMANDS_DIR}/${NODE_NAME}.json" >&2
  fi
  if [[ -n "$ENV_FILE" ]]; then
    echo "        - ${NODE_COMMANDS_DIR}/$(basename "$ENV_FILE" .env).json" >&2
  fi
  echo "        no legacy fallback is used." >&2
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
