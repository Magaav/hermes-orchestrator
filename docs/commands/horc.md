# horc Command Reference

`horc` is the Hermes Orchestrator CLI for lifecycle, logs, backup/restore, and simplified fleet updates.

## Defaults

- Default node for most lifecycle commands: `orchestrator`
- Backup destination: `/local/backups`
- Canonical update artifact root: `/local/logs/update`

## Lifecycle Commands

```bash
horc start [name] [--image IMAGE]
horc status [name]
horc stop [name]
horc restart [all|name] [--image IMAGE]
horc delete [name] [--yes]
horc purge-node <name>
horc purge-node confirm <request-id> --token TOKEN
```

`horc delete <name>` asks for confirmation, removes the node container, and deletes
`/local/agents/envs/<name>.env` plus `/local/agents/nodes/<name>/`. Shared node data,
cron, and logs are preserved; use `horc purge-node <name>` for full cleanup.

`horc purge-node <name>` is a destructive two-step cleanup. The first command
creates a purge request; the second confirms it with the request id and token.

## Logs Commands

```bash
horc logs [name] [--lines N]
horc logs clean [name|all]
```

## Backup and Restore

```bash
horc backup all
horc backup node <name>
horc backup <name>
horc space backup
horc restore <path>
```

`horc space backup` is the current wasm-agent-cloud proof-of-concept backup. It
archives the active wasm-agent state root into `/local/backups` with a manifest
under `wasm-agent-cloud/<instance>/backup-manifest.json`. In cloud mode it reads
`<HERMES_WASM_AGENT_CLOUD_STATE_ROOT>/state` when that directory exists; then it
falls back to `HERMES_WASM_AGENT_STATE_DIR`, and finally to the local
development root `/local/plugins/wasm-agent/state`. Browser caches, logs, pid
files, symlinks, and other noisy runtime files are excluded.

## Update Commands

```bash
horc update [help]
horc update all [--force]
horc update node <name> [--force]
```

## Build Commands

```bash
horc build
horc build win-x64-prod
horc build prepare-docker
horc build doctor
horc build --doctor
```

`horc build` builds the Windows 11 x64 wasm-agent Electron/NSIS installer. The
underlying release command still runs from `native/windows/src`:

```bash
npm run release:win:x64:prod
```

The release script cleans stale output, regenerates production native defaults,
builds the Windows x64 NSIS installer, extracts the final artifact, and verifies
that the packaged app is cloud-backed by default. After it returns, `horc build`
checks the unpacked executable, `resources/app.asar`, and the final installer,
prints the first 80 `app.asar` entries, and writes
`/local/native/windows/release/horc-build-manifest.json`.

Build trust lanes:

- Native Windows: preferred production path, marked `trusted_production: true`.
- Linux x86_64 with Wine/NSIS: supported CI cross-build, marked
  `requires_windows_smoke_test: true`.
- Linux aarch64 with Docker `--platform linux/amd64`: supported experimental
  cross-build, marked `requires_windows_smoke_test: true`. If amd64 Docker
  emulation is missing, `horc build` tries to register QEMU binfmt with
  `docker run --privileged --rm tonistiigi/binfmt --install amd64`, then
  re-tests before starting the Wine builder. In `auto` mode, if QEMU can run
  amd64 containers but the amd64 Electron Builder helper crashes under
  emulation, `horc build` falls back to a Linux ARM64 native NSIS build with
  Windows executable resource editing disabled and marks the manifest mode as
  `linux-arm64-native-nsis-no-rcedit`.
- Linux aarch64 direct Wine: debug-only, requires
  `HORC_ALLOW_CROSS_WIN_BUILD=1`, and may hang in Windows resource editing.

For faster repeated Linux ARM64 Docker builds, run the one-time prepared image
step:

```bash
horc build prepare-docker
```

This builds `horc/electron-builder-wine-nsis:jammy` with NSIS and `unar`
preinstalled. Future `horc build` runs auto-use that local image when
`HORC_DOCKER_IMAGE` is unset, avoiding repeated `apt-get update` and package
installs inside each disposable builder container.

`horc build doctor` prints host OS/arch, Docker availability, Docker user
permission, amd64 binfmt status, Wine builder image pullability, expected build
mode, and exact remediation commands for missing prerequisites.

## wasm-agent Space Commands

```bash
horc space start
horc space stop
horc space status
horc space backup
```

`horc space start` starts the wasm-agent PWA on `http://127.0.0.1:8877` and
the wasm-agent-owned Hermes bridge on `http://127.0.0.1:8790`.

## Notes

- `horc restart` with no node restarts all nodes in orchestrator-first order.
- `hord` and `clone.sh` are compatibility aliases for `horc`.
- `horc backup` produces lean archives and includes a shared runtime seed for reseeding nodes during restore.
- `horc space backup` produces a client-first wasm-agent state archive and does not include public repo source.
- `horc restore` stops included running nodes, restores payloads, and restarts nodes that were running.
- Every update refreshes `/local/hermes-agent` as a hard mirror of the configured upstream repo/branch before reseeding nodes.
- `horc update all` reseeds every node and reconciles `/local/agents/registry.json`.
- `horc update node <name>` reseeds only the named node and leaves others untouched.
- Add `--force` to discard local `/local/hermes-agent` checkout changes when the upstream refresh would otherwise fail on a dirty working tree.
- `horc build` is the shortcut for the Windows wasm-agent native release artifact.
- Nodes that were already running are restarted through the normal lifecycle; stopped nodes keep their stopped state.
- `NODE_RESEED=true` in `/local/agents/envs/<node>.env` forces a one-shot reseed from `/local/hermes-agent` on the next start/restart.
- Update reports are written under `/local/logs/update/<run-id>/`.

## Wrapper Environment

- `HERMES_DEFAULT_NODE`: default node when a command omits a name; default `orchestrator`.
- `HERMES_CLONE_MANAGER_SCRIPT`: override path for `clone_manager.py`.
- `HERMES_CLONE_PYTHON_BIN`: override Python runtime for the wrapper.
- `HERMES_HORC_ASSUME_YES=1`: skip interactive `delete` confirmation.
- `HERMES_WASM_AGENT_STATE_DIR`: local wasm-agent state root for `horc space`
  runtime state and backup fallback.
- `HERMES_WASM_AGENT_BRIDGE_STATE_DIR`: optional bridge state root, default
  `<HERMES_WASM_AGENT_STATE_DIR>/bridge`.
- `HERMES_WASM_AGENT_CLOUD_STATE_ROOT`: private wasm-agent-cloud instance state root used by `horc space backup`.
- `HERMES_WASM_AGENT_CLOUD_INSTANCE_ID`: optional stable id used in wasm-agent-cloud backup archive paths.
- `HORC_WIN_BUILD_MODE`: `auto`, `native`, `wine`, or `docker`; default `auto`.
- `HORC_TARGET_WIN_ARCH`: Windows target architecture; currently only `x64`.
- `HORC_REQUIRE_VERIFIED_INSTALLER=1`: require installer, unpacked exe, and
  app.asar artifact checks; default `1`.
- `HORC_DOCKER_IMAGE`: Docker image for Linux amd64 Wine builds; default
  auto-selects local `horc/electron-builder-wine-nsis:jammy` when present,
  otherwise `electronuserland/builder:wine`.
- `HORC_PREPARED_DOCKER_IMAGE`: local prepared builder image tag created by
  `horc build prepare-docker`; default `horc/electron-builder-wine-nsis:jammy`.
- `HORC_DOCKER_AMD64_PROBE_IMAGE`: small linux/amd64 image used to verify
  Docker/QEMU emulation before pulling the Electron builder; default
  `alpine:3.20`.
- `HORC_AUTO_INSTALL_BINFMT=1`: enable automatic QEMU binfmt registration;
  default on Linux aarch64 in `auto` or `docker` mode.
- `HORC_NO_AUTO_INSTALL_BINFMT=1`: disable automatic QEMU binfmt registration.
- `HORC_ALLOW_CROSS_WIN_BUILD=1`: allow Linux aarch64 direct Wine debug builds.
- `WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1`: internal fallback switch used to skip
  Windows executable resource editing on Linux ARM64 native NSIS builds.

## Governance

Every node receives a generated runtime contract at startup and restart:
- `/local/agents/nodes/<node>/.hermes/NODE_RUNTIME_CONTRACT.md`
- `/local/agents/nodes/<node>/workspace/NODE_RUNTIME_CONTRACT.md`

The clone manager also injects a condensed governance prompt through `HERMES_EPHEMERAL_SYSTEM_PROMPT` so live agent behavior stays aligned with the contract on each start.

Shared framework changes under `/local/plugins` and `/local/scripts` follow this execution discipline:
- Think before acting: inspect current state, state assumptions explicitly, and assess blast radius before editing shared assets.
- Simplicity first: prefer the smallest reversible change that solves the problem.
- Surgical changes: touch only the files required for the task and avoid unrelated refactors in shared infrastructure.
- Goal-driven execution: define success checks up front and require rollout, rollback, and post-restart verification for shared changes.

Operational implication:
- documentation-only changes to the generated contract files are not enough for a running node
- restart the affected node, usually with `horc restart <name>`, to load the updated injected governance prompt

## Source of Truth

- CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Engine: `/local/scripts/public/clone/clone_manager.py`
- Fleet inventory: `/local/agents/registry.json`

## Registry Role

`/local/agents/registry.json` is the canonical operational inventory for orchestrated nodes. It is maintained by the clone manager and is intended for inspection, reconciliation, and version auditing.

Each node entry records:
- topology and identity: `clone_name`, `clone_root`, `env_path`, `state_mode`, `state_code`
- runtime attachment: `container_name`, `container_id`, `runtime_type`, and `host_pid` for bare-metal nodes
- reconciliation timestamp: `updated_at`
- Hermes runtime version metadata under `hermes_agent`

`hermes_agent` includes:
- `package_version`
- `git_commit`
- `git_branch`
- `git_describe`
- `engines_node`

If a node runtime tree does not keep a `.git` directory, the version snapshot falls back to the bootstrap source recorded in `.clone-meta/bootstrap.json`.

Operator guidance:
- treat `registry.json` as derived state, not declarative config
- use it to compare node versions before and after updates
- remove stale entries as part of node cleanup
