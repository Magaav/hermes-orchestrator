# Discord ACL v2

## Overview

Discord ACL is fail-closed and node-scoped.

- Public logic/scripts:
  - `/local/plugins/public/discord/hooks/discord_slash_bridge/role_acl.py`
  - `/local/plugins/public/discord/scripts/discord_role_acl_sync.py`
  - `/local/plugins/public/discord/scripts/discord_acl_contract_check.py`
- Private runtime state:
  - `/local/plugins/private/discord/acl/<node>_acl.json`
  - `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
  - `/local/plugins/private/discord/models/<node>_models.json`

Defaults:

- All slash commands are ACL-controlled.
- Unmapped slash commands are denied.
- `admin` bypasses role-based slash ACL, but restricted channel ACL still applies.

## Slash Commands

Legacy `/acl comando:<...> discord_role:<...>` was removed.

Use:

```text
/acl command command:<slash_command> role:<discord_role>
/acl channel channel:<channel_id> mode:<default|specific> model_key:<key?> instructions:<text?> label:<text?> ...
```

Examples:

- `/acl command command:metricas role:gerente`
- `/acl channel channel:1487099467726328038 mode:specific model_key:nemotron120b allowed_commands:faltas,clean allowed_skills:colmeio-lista-de-faltas free_text_policy:strict_item default_action:skill:add label:loja1`
- `/acl channel channel:1487099467726328038 mode:default`

`/acl channel` behavior:

- Writes channel policy in `/local/plugins/private/discord/hooks/channel_acl/config.yaml`.
- `mode:specific` requires valid `model_key` from `/local/plugins/private/discord/models/<node>_models.json`.
- Invalid/missing `model_key` is fail-closed.
- `label` is the per-channel automation tag used by normalized restricted-channel flows.
- `/acl` now exposes autocomplete for `command`, `role`, `model_key`, `allowed_commands`, and `allowed_skills`.

Admin bypass source of truth:

- Role-ACL admin bypass is resolved from live Discord guild roles (`admin` role in ACL hierarchy).
- Optional emergency override: `DISCORD_ADMIN_USER_IDS`.
- Local `discord_users.json` is used only as last-resort fallback when live Discord member lookup is unavailable.

## Prestart / Update Gates

Prestart now runs:

1. `discord_role_acl_sync`
2. `discord_acl_contract_check`

`update-test` and `update-apply` are blocked when these checks fail.

## Troubleshooting

If thread/channel execution is blocked unexpectedly:

1. Confirm `origin_channel_id` and `chat_id_alt` are both being passed.
2. Confirm parent channel is in `FALTAS_OPERATIONAL_CHANNEL_IDS` (legacy `DISCORD_ALLOWED_THREADS` is deprecated/ignored).
3. Confirm channel `mode:specific` has valid `model_key` in private models file.
4. Re-run prestart in strict mode and inspect `colmeio-prestart.log` for ACL step failures.
