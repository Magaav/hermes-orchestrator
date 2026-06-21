# Clone Manager And horc

`scripts/public/clone` owns the primary Hermes Orchestrator lifecycle engine and
CLI wrappers.

## Current Entry Points

- `horc.sh`: primary operator CLI wrapper.
- `hord.sh`: compatibility alias for `horc`.
- `clone.sh`: compatibility alias for `horc`.
- `clone_manager.py`: lifecycle engine for start, stop, status, logs, backup,
  restore, update, governance prompt generation, and wasm-agent helper
  commands.
- `tests/`: focused tests for governance prompt and gateway-state behavior.

## Wrapper Behavior

- Omitted node names default to `orchestrator` unless `HERMES_DEFAULT_NODE` is
  set.
- `hord.sh` and `clone.sh` are compatibility aliases that exec `horc.sh`.
- `horc space start|stop|status` is implemented in the wrapper and delegates to
  `/local/plugins/wasm-agent/scripts/*`.
- `horc build android` clears inherited Android build identity variables by
  default so each release-promotion rebuild publishes a fresh update identity
  into the native release feed; use `HORC_ANDROID_PRESERVE_BUILD_ID=1` only for
  intentional reproducible rebuilds.
- `horc build android-fast` is the debug APK inner-loop lane. It uses the same
  Android toolchain selection as the release lane, then skips release signing,
  promotion, package proof, and native feed publication.
- `horc build win-fast` is the Windows native inner-loop lane. It runs local
  Node checks and optional `win-unpacked` packaging, then skips the NSIS
  installer, installer verification, installed-app proof, and native feed
  publication. On Linux aarch64 it also skips Wine resource editing unless
  `HORC_WIN_FAST_RESOURCE_EDIT=1` is set.
- `delete` prompts interactively unless `--yes` or `HERMES_HORC_ASSUME_YES=1`
  is used.
- `purge-node` is intentionally two-step: request first, then confirm with the
  generated request id and token.

## Documentation Sync

When CLI behavior, node lifecycle semantics, env handling, plugin bootstrap, or
wasm-agent helper commands change, update `/local/docs/commands/horc.md`, the
root README, and nearby plugin/feature docs as needed.

`horc` remains the canonical operational control plane. UI and plugin surfaces
should call into this boundary rather than inventing parallel lifecycle rules.
