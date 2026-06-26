# Self-Improving Harness Contract

The harness exists to make future agent loops cheaper, faster, and harder to
mislead. Its job is to turn repeated inference into deterministic promises with
compact evidence.

This contract does not replace agent reasoning. Agents still explore novel
uncertainty, design probes, interpret contradictions, and promote useful checks.
The harness owns repeated uncertainty that can be answered by a bounded command,
status read, artifact inspection, hot-op, simulator, or proof script.

## Reasoning Chain

Use this order before meaningful investigation, code edits, rebuilds, runtime
control, or release claims:

1. Intent: state the claim that must become true.
2. Context routing: read the owner docs and nearest rules.
3. Harness Factory Reflection: decide whether an existing or new promise can
   answer the uncertainty.
4. Promise lookup: run or compose the smallest valid deterministic promise.
5. Exploration lane: investigate only when no promise answers the uncertainty.
6. Watcher evidence: collect compact static, runtime, behavioral, package, or
   production proof.
7. Gatekeeper decision: mark the claim pass, fail, stale, blocked,
   inconclusive, invalid-environment, or needs-human-proof.
8. Post-loop harvest: promote repeated manual inference into the registry.

The target is not "everything deterministic." The target is to minimize
expensive reasoning by converting recurring uncertainty into durable,
invalidatable, composable proof.

## Harness Factory Reflection

Before paying for a slow loop, fill this mentally or in the task report:

```json
{
  "claim": "what must be proven",
  "uncertainty": "what would otherwise require inference",
  "existingPromise": "promise-id or null",
  "newPromiseCandidate": "promise-id or null",
  "evidenceRequired": ["static", "runtime", "behavioral"],
  "loopShorteningMove": "hot-op/status field/script/log probe/none",
  "decision": "run-existing | compose-promises | add-observability | create-promise | freeform-investigate | stop"
}
```

`stop` is correct when the proof requires installed-app, production, user,
device, or external evidence that is not available in the current environment.

## Promise Result

Every deterministic promise should return or be summarized into this compact
shape:

```json
{
  "status": "pass",
  "promiseId": "context-sync",
  "claim": "Context active-state docs are in sync",
  "durationMs": 1220,
  "evidence": ["reports/context/latest/context-sync-result.json"],
  "summary": "Context sync passed",
  "failureClass": null,
  "nextSuggestedSteps": []
}
```

Allowed statuses:

| Status | Meaning |
| --- | --- |
| `pass` | Predeclared evidence satisfied the claim. |
| `fail` | Evidence falsified the claim. |
| `running` | Bounded async operation is still in progress. |
| `blocked` | Required access or prerequisite is missing. |
| `stale` | Evidence is invalidated by newer source, config, artifact, or runtime state. |
| `inconclusive` | Evidence ran but does not prove or falsify the claim. |
| `invalid-environment` | The command ran where the required platform/device/tooling is absent. |
| `needs-human-proof` | The claim requires a human login, gesture, install, or physical-world check. |

## Promise Registry

Machine-readable promises live in `docs/context/HARNESS_PROMISES.json`.
Validate the registry with:

```bash
python3 tools/context/check-harness-promises.py
```

Each promise must declare:

- stable `id`
- owner
- claim
- bounded command
- timeout
- cost model
- required evidence classes
- pass requirements
- output artifacts
- invalidation triggers
- suggested next steps

Promises should be atomic, idempotent when practical, non-destructive by
default, and small enough that a failure explains the next move.

## Promotion Rule

When the same manual inference appears for the second time, add a promise
candidate or explain why it cannot be deterministic yet. When it appears for the
third time, either promote it into `HARNESS_PROMISES.json` or record the missing
primitive, access, or observability that blocks promotion.

Good candidates:

- repeated docs smell scans
- repeated package/feed consistency checks
- repeated bridge status reads
- repeated installed-runtime status probes
- repeated simulator or hot-op proof loops
- repeated artifact SHA or route checks

Poor candidates:

- novel design judgment
- ambiguous product decisions
- one-off forensic investigation
- proof that requires unavailable human/device/production access

## Invalidation

A passed promise is not permanent. It expires when its declared invalidation
paths or conditions change. Examples:

| Promise type | Common invalidators |
| --- | --- |
| Docs/context proof | `AGENTS.md`, `README.md`, `docs/context/**` |
| Windows installer proof | `native/windows/**`, release feed, installer bytes |
| Android runtime proof | `native/android/**`, installed APK, bridge capability set |
| Auth/session proof | auth code, cookie policy, backend session route, installed app |
| Wake-word proof | model SHA, policy fields, native service, bridge, PWA event path |

When evidence is invalidated, mark the claim `stale` or rerun the promise
before claiming it.

## Cost Order

Run the cheapest falsifying promise first:

1. static/source checks
2. local artifact checks
3. runtime status reads
4. simulator/hot-op checks
5. installed-app or device checks
6. production or human-interactive proof

Compose small promises for large claims. Avoid giant proof scripts unless they
only orchestrate smaller promises and keep each result visible.

## Post-Loop Harvest

After any expensive manual loop, answer:

```text
What uncertainty repeated?
What exact command or status read would have answered it?
What evidence would make pass/fail/inconclusive valid?
What source/runtime changes should invalidate that proof?
Should the registry gain a promise now?
```

If the answer is yes, update `HARNESS_PROMISES.json`, run the validator, and add
the new promise to the nearest verification docs when it changes a workflow.

## Loop Copilot Layer

Use `python3 tools/context/watch-loop-copilot.py` as the thin upper-layer
watcher before slow runtime-control work, rebuild-heavy loops, or final claims.
It is read-only and emits compact signals to:

- identify active Codex/native-control loops from process evidence
- catch production-proof and `win-unpacked` claim risks in the current diff
- require harness registry validity before promise-based steering
- remind the worker to use live introspection/control before rebuilds

The loop copilot does not edit code, authorize success, or replace Builder /
Watcher / Gatekeeper reporting. It writes:

```text
reports/context/latest/loop-copilot-signals.json
reports/context/latest/loop-copilot-signals.jsonl
```

Treat `blocker` signals as Gatekeeper stops until the named proof or demotion is
handled. Treat `warn` signals as edit/final-review friction, not runtime proof.
