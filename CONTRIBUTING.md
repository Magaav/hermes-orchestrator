# Contributing

Thanks for helping improve Hermes Orchestrator.

## Getting Started

1. Fork and clone the repository.
2. Create a branch from `main`.
3. Make focused changes with clear commit messages.
4. Open a pull request with context, rationale, and rollback notes when relevant.

## Local Sanity Checks

Run these before opening a PR:

```bash
bash -n scripts/install.sh scripts/clone/clone.sh scripts/clone/hord.sh scripts/clone/horc.sh docker/entrypoint.sh docker/dockerfiles/openviking-entrypoint.sh
python3 -m compileall -q scripts plugins/discord
```

## Security And Secrets

- Never commit runtime env files, logs, or node state.
- Use tracked templates only (`*.env.example`).
- Keep API keys/tokens out of commits and PR descriptions.

## Documentation Expectations

- Update docs when behavior changes.
- Prefer canonical paths under `/local/plugins/discord/*` for Discord assets.
- Keep examples tenant-neutral when possible.
