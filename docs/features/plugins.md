# Plugins Feature

The plugins feature is the extensibility and runtime integration layer of Hermes Orchestrator.

## Canonical Roots

- Public plugins: `/local/plugins/public`
- Private plugins: `/local/plugins/private`

## Why It Is Segregated

- Public plugins hold reusable hook/runtime code and remain fully versioned.
- Private plugins hold mutable runtime payloads, memory/wiki data, and deployment-local command/config state.

## How Hermes-Orchestrator Uses It

- Prestart patch pipeline executes from `/local/plugins/public/hermes-core/scripts/prestart_reapply.sh`.
- Discord bridge/runtime integrations live in `/local/plugins/public/discord`.
- Node command payloads and private Discord state are stored under `/local/plugins/private/discord`.
- Shared wiki runtime lives under `/local/plugins/private/wiki`.

## Synergy With Other Modules

- Scripts in `/local/scripts/public` orchestrate plugin startup, lifecycle, and backup flows.
- `horc` backup/restore keeps private plugin runtime state restorable across VM rebuilds.
- Worker nodes consume public/private plugin mounts according to orchestrator topology.

## Related Docs

- [`../../plugins/README.md`](../../plugins/README.md)
- [`scripts.md`](scripts.md)
- [`../commands/horc.md`](../commands/horc.md)
