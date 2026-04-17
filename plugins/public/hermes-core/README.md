# Hermes Core Plugin

Durable core customizations for Hermes gateway behavior, kept outside `hermes-agent/` so they can be re-applied after upstream updates.

## Features

- Per-node followup interval:
  - `NODE_AGENT_FOLLOWUP_ELAPSED` (minutes, default `10`)
- Optional followup summary block:
  - `NODE_AGENT_FOLLOWUP_SUMMARY` (`true/false`, default `false`)
- Optional final response file-change footer:
  - `NODE_AGENT_FINALRESPONSE_ENFORCE_FILES_CHANGED` (`true/false`, default `false`)
  - Footer includes updated, created, and deleted file sections when available
- Shared wiki engine:
  - `NODE_WIKI_ENABLED` (`true/false`, default `false`)
  - private runtime root: `/local/plugins/private/wiki`
  - public reference root: `/local/plugins/public/wiki`
  - node link: `/local/agents/nodes/<node>/wiki`

## Node Env Resolution Order

At runtime, each setting is resolved in this order:

1. Process env var (already exported)
2. `NODE_AGENT_ENV_FILE` (if set)
3. `/local/agents/nodes/<NODE_NAME>.env`
4. `/local/agents/nodes/<NODE_NAME>/.env`
5. `/local/agents/envs/<NODE_NAME>.env`
6. `/local/agents/<NODE_NAME>.env`

## Scripts

- Prestart reapply pipeline (canonical):
  - `bash /local/plugins/public/hermes-core/scripts/prestart_reapply.sh [--strict]`
- Wiki engine CLI:
  - `python3 /local/plugins/public/hermes-core/scripts/wiki_engine.py --help`
- Reapply patch:
  - `python3 /local/plugins/public/hermes-core/scripts/reapply_node_agent_followup_footer.py`
- Verify markers:
  - `python3 /local/plugins/public/hermes-core/scripts/verify_node_agent_followup_footer.py`

## Wiki Engine Notes

- The live wiki content under `/local/plugins/private/wiki` is deployment-local and ignored by git.
- Worker nodes mount the shared wiki at `/local/wiki` only when `NODE_WIKI_ENABLED=true`.
- The prestart pipeline runs wiki bootstrap/self-heal so Hermes updates can be reapplied without copying code into `hermes-agent/`.
