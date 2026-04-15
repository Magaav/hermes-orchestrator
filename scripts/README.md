# Scripts

`/local/scripts` is the script feature root of Hermes Orchestrator.

## Why This Exists

The orchestrator separates reusable framework logic from deployment-local operational state. This keeps public automation code easy to review while protecting instance-specific runtime data.

## Directory Segregation

- `public/`: git-tracked orchestrator tooling and command entrypoints.
- `private/`: local-only scripts/config for this deployment.

## Related Roots

- Cron runtime state is now canonical at `/local/crons` (mounted into nodes at `nodes/<node>/cron`).
- Plugin capabilities that consume scripts live under `/local/plugins`.

## Read Next

- [`public/README.md`](public/README.md)
- [`private/README.md`](private/README.md)
- [`../docs/features/scripts.md`](../docs/features/scripts.md)
- [`../docs/commands/horc.md`](../docs/commands/horc.md)
