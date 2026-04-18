# Node Env Contract (`/local/agents/envs/<node>.env`)

This document defines the bootstrap contract for node profiles used by `horc`.

## Hard Requirements (bootstrap will fail without these)

| Variable | Required | Why |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | `horc start <node>` fails fast if missing. |
| `DISCORD_SERVER_ID` or `DISCORD_GUILD_ID` | Yes for Discord role ACL | Role ACL bootstrap (`discord_role_acl_sync.py`) requires a canonical guild ID. |
| `NODE_STATE` | Conditionally required | If set, it must be one of `1`, `2`, `3`, `4`. Invalid values fail bootstrap. |
| `NODE_STATE_FROM_BACKUP_PATH` | Required when `NODE_STATE=3` | Backup-seed mode requires a restore archive path. |

Notes:
- `NODE_STATE` defaults to `1` when omitted.
- For non-orchestrator nodes, `/local/agents/envs/<node>.env` must exist before start.

## Minimum Operational Set (node starts and can answer)

These are the minimum practical values for a usable node profile.

### Identity and mode
- `NODE_AGENT_DEFAULT_MODEL_PROVIDER`
- `NODE_AGENT_DEFAULT_MODEL`
- `NODE_AGENT_FALLBACK_MODEL_PROVIDER`
- `NODE_AGENT_FALLBACK_MODEL`
- `NODE_TIME_ZONE`

### Discord transport
- `DISCORD_BOT_TOKEN`
- `DISCORD_APP_ID`
- `DISCORD_SERVER_ID`
- `DISCORD_ALLOWED_USERS` (recommended; if omitted, allowlist is open)

### Discord role ACL (slash command authorization)
- `DISCORD_SERVER_ID` (preferred) or `DISCORD_GUILD_ID`
- Optional: `DISCORD_ROLE_ACL_SAFE_COMMANDS` (CSV, default `status,help,usage,provider`)
- Optional: `DISCORD_ROLE_ACL_FALLBACK_HIERARCHY` (CSV role-name fallback when live role fetch is unavailable)
- Required contract file: `/local/plugins/private/discord/acl/<node>_acl.json`

### Discord channel ACL + private model catalog
- Required contract file: `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- Required contract file: `/local/plugins/private/discord/models/<node>_models.json`
- `mode:specific` channel policies must reference a valid `model_key` from the private models file.
- Channel policies may set `label` (for example `loja1`) for deterministic per-channel automation tagging.
- Prestart validates this contract via `discord_acl_contract_check`; failure blocks update promotion.

### LLM credentials (pick at least one provider path)
| Provider path | Minimum variables |
|---|---|
| MiniMax | `MINIMAX_API_KEY`, `MINIMAX_GROUP_ID` |
| OpenRouter | `OPENROUTER_API_KEY` |
| NVIDIA | `NVIDIA_API_KEY` |

If provider credentials are missing, the node may boot but fail at first model call.

## Discord Mention Routing Controls

### `DISCORD_REQUIRE_MENTION_CHANNELS`

New behavior variable:

```bash
DISCORD_REQUIRE_MENTION_CHANNELS=321321,3821312,534534
```

Behavior:
- If this variable key is present in env (even empty), it becomes authoritative.
- Only listed channels require `@mention`.
- All other channels become free-response automatically.
- Parent channel IDs are considered for thread messages.
- This controls **normal message** routing (`on_message`), not native Discord slash-command interactions.

Important Discord UX note:
- A message starting with `/` may be treated by Discord as an app command interaction, not chat text.
- In that case, mention gating variables (including `DISCORD_REQUIRE_MENTION_CHANNELS`) do not apply.
- For mention-free chat behavior tests, send plain text without a leading `/`.

### Related variables
- `DISCORD_REQUIRE_MENTION=true|false`
- `DISCORD_FREE_RESPONSE_CHANNELS=<csv>`
- `DISCORD_IGNORED_CHANNELS=<csv>`
- `DISCORD_AUTO_THREAD=true|false`
- `DISCORD_AUTO_THREAD_IGNORE_CHANNELS=<csv>`

### Effective precedence
1. `DISCORD_IGNORED_CHANNELS`: always ignored, even with mention.
2. `DISCORD_REQUIRE_MENTION_CHANNELS` (if set): listed channels require mention, others do not.
3. Otherwise: `DISCORD_REQUIRE_MENTION` + `DISCORD_FREE_RESPONSE_CHANNELS` control mention gating.
4. Messages in threads where the bot has already participated bypass mention gating.

## Example: selective mention requirement

```bash
DISCORD_REQUIRE_MENTION=true
DISCORD_REQUIRE_MENTION_CHANNELS=1487073289137553581,1487099467726328038
```

Result:
- In those two channels, users must `@mention` the bot.
- In every other channel, the bot responds to normal messages.
