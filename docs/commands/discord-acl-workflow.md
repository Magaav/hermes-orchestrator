# Discord ACL Operator Workflow

## 1) Role Mapping

1. Run ACL sync:
   - `python3 /local/plugins/public/discord/scripts/discord_role_acl_sync.py`
2. Open `/local/plugins/private/discord/acl/<node>_acl.json`.
3. Confirm hierarchy order (`admin` on top, `@everyone` at bottom).
4. Map commands with `/acl command`.

## 2) Channel Policy Updates

Use `/acl channel`.

- Restrict channel with fixed model + policy:
  - `/acl channel channel:<id> mode:specific model_key:<key> allowed_commands:<csv> allowed_skills:<csv> free_text_policy:strict_item default_action:skill:add label:<text> instructions:<text>`
- Revert channel to default/free mode:
  - `/acl channel channel:<id> mode:default`

Tips:
- Use autocomplete for `model_key`, `allowed_commands`, and `allowed_skills` to avoid typos.
- Use `label` (for example `loja1`) as the channel automation tag; `store` was removed from `/acl channel`.

Policy is persisted in:

- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`

## 3) New Command Onboarding

1. Register/sync the new slash command.
2. Run role ACL sync.
3. Map permission:
   - `/acl command command:<new_command> role:<discord_role>`
4. Validate prestart contract:
   - `python3 /local/plugins/public/discord/scripts/discord_acl_contract_check.py`

## 4) Thread/Channel Block Troubleshooting

If a thread in an allowed parent channel is blocked:

1. Check logs for `origin_channel_id`, `thread_id`, `chat_id_alt`, and resolved parent.
2. Ensure `chat_id_alt` is populated for thread invocations.
3. Ensure parent channel is in `FALTAS_OPERATIONAL_CHANNEL_IDS`.
4. Ensure restricted channel `model_key` exists in:
   - `/local/plugins/private/discord/models/<node>_models.json`
5. Run strict prestart and verify ACL steps pass:
   - `discord_role_acl_sync`
   - `discord_acl_contract_check`
