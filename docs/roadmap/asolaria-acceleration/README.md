# Asolaria Acceleration Track

This track absorbs useful patterns from the public
`JesseBrown1980/what-is-asolaria---how-do-we-get-reductions-in-everything`
repository into Hermes Orchestrator planning.

Status: `proposal`. This is a pattern source, not a code import and not runtime
proof for this repo.

## Source Boundary

Inspected source:
`JesseBrown1980/what-is-asolaria---how-do-we-get-reductions-in-everything`
at commit `3ac52c0f5c386ddd83572054b3279f55f742bf04` on 2026-06-18.
Local static verification in that inspection was limited to SHA manifests,
JavaScript syntax checks, and rerunning the included micro-kernel descriptor
measurement script against the included sample. Those checks prove only the
public repo artifacts inspected in that pass; they do not prove Hermes
Orchestrator runtime behavior.

The Asolaria repo is useful as an acceleration grammar:

| Pattern | Adopt here as |
| --- | --- |
| Stable five-primitive kernel framing | Keep native shells as stable capability kernels; evolve behavior through downloaded runtime, hot-op bundles, config, model metadata, and server UI. |
| Tuple/hash identity doctrine | Use byte-stable tuple hashes for proof receipts and operation identity instead of scalar or display-only identifiers. |
| Sparse materialization | Keep possible work as descriptors/handles until a bounded operation is explicitly run. |
| HBP-style descriptor rows | Prefer compact, append-only proof rows for receipts, manifests, diagnostics summaries, and release evidence. |
| EXISTS/NEW proof tags | Map every claim to this repo's statuses: `verified`, `implemented-unverified`, `proposal`, `future`, `stale`, or `unknown`. |

Do not import Asolaria runtime claims, private-path assumptions, USB/raw-disk
tooling, or roadmap language as current Hermes Orchestrator behavior.

## Application To WASM Agent Native

The near-term target is the native evolution lane already described in
`native/NATIVE_EVOLUTION_CONTRACT.md`:

| WASM Agent object | Descriptor/proof identity |
| --- | --- |
| Installed shell | `H(platform, installedNativeBuildId, shellProtocolVersion, capabilityManifestSha)` |
| Downloaded runtime | `H(runtimeId, bundleSha, manifestSha, fileSetSha)` |
| Hot operation | `H(operationId, activeHotOpBundleId, activeHotOpSha, requiredCapabilitiesSha)` |
| Proof run | `H(deviceId, operationId, buildId, bundleSha, startedAt, proofSchema)` |
| Wake classification | `H(proofRunId, thresholdPolicy, wakeEventState, transcriptState, routingState)` |

These identifiers are routing and dedup aids. They do not prove runtime success
unless the owning verifier passes.

## Proof Receipt Shape

Prototype a small `hermes.wasm_agent.receipt.v1` row format before adding any
new product behavior:

```text
WAPROOF|schema=hermes.wasm_agent.receipt.v1|kind=<package|runtime|hot_op|auth|wake>|claim_status=<verified|implemented-unverified|proposal|future|stale|unknown>|proof_result=<pass|fail|missing|not_run>|subject=<tuple-hash>|proof=<command-or-report-id>|sha256=<artifact-sha-or-empty>|next=<next-action-id>|json=0
```

Rules:

- One row names one claim and one proof boundary.
- `claim_status` uses only the canonical status enum from `docs/context`.
- `proof_result` records what happened in the named proof attempt without
  adding a new claim-status value.
- `verified` requires `proof_result=pass` from the exact verifier named by the
  owning docs.
- Source tests, build success, release feed presence, and `win-unpacked` never
  become installed Windows proof.
- Android package proof never becomes OAuth/runtime proof.
- A failed or missing proof demotes the row to `implemented-unverified`,
  `stale`, or `unknown`, depending on the owning claim boundary.
- Prototype rows must be byte-stable: ASCII only, single-line pipe tokens,
  lowercase field names, no raw `|` or newlines in values, and IDs instead of
  free-text where the value may contain spaces or punctuation.

## Faster Agent Loop

Before rebuilding or asking the user to narrate runtime state, agents should:

1. Read the native kernel/capability status.
2. List downloaded runtime and hot-operation state.
3. Use the narrowest runtime snapshot or diagnostics endpoint available.
4. Try live policy/config/control knobs when the native primitive already
   exists.
5. Rebuild only for missing OS permission, manifest/service changes, native
   libraries, package identity, signing, or a broken native capability contract.

## Durable Next Step

The first static receipt generator exists at
`tools/windows/emit-waproof-receipts.py`. It reads existing Windows proof
reports and emits `WAPROOF` rows without changing release feed behavior or
upgrading runtime claims.

Next: run it after the Windows proof sequence, inspect whether the receipt rows
make agent handoff faster, and only then consider wiring it into a broader
proof summary command.
