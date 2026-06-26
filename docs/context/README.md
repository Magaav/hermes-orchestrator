# Context Engine Protocol

`docs/context` is the canonical agent context engine. Its job is to make a
future empty-context agent cheap, fast, and hard to mislead.

## Files

| File | Owns |
| --- | --- |
| `README.md` | Context rules, status enum, conflict law |
| `MAP.md` | Route/topic map, owner, read-first docs, verifier, next action |
| `CLAIMS.md` | Claim registry with proof status and demotions |
| `VERIFY.md` | Exact commands and proof artifacts |
| `REVIEW.md` | Writer/watcher pass, fresh-agent test, scorecard |
| `HARNESS.md` | Self-improving harness contract and promotion rules |
| `HARNESS_PROMISES.json` | Machine-readable deterministic promise registry |

## Status Enum

| Status | Meaning |
| --- | --- |
| `verified` | Named runtime/package/docs proof exists and is listed. |
| `implemented-unverified` | Code/build/docs exist, but required proof has not passed or was not run. |
| `proposal` | Designed, not implemented. |
| `future` | Intended later; no current implementation claim. |
| `stale` | Old claim conflicts with current code, docs, or evidence. |
| `unknown` | No reliable evidence found. |

Rules: missing verification means not verified. Build success alone is not
runtime proof. Roadmap docs cannot upgrade runtime status. Never silently
upgrade a claim.

## Read-Before-Edit

1. Read `/local/AGENTS.md`.
2. Read `/local/README.md`.
3. Read `docs/context/MAP.md` for target routing.
4. Read the nearest child `AGENTS.md` and local README for every path touched.
5. Inspect current code/proof before trusting old docs.

## Update-After-Edit

| Change | Update |
| --- | --- |
| Behavior, workflow, command, API, ownership, artifact, verification, or next action | Nearest owning README or `AGENTS.md` |
| Global guard, context rule, area ownership, status enum, or route | `/local/README.md` and `docs/context/*` |
| Claim proof gained, missing, stale, or contradicted | `docs/context/CLAIMS.md` |
| Verification command changes | `docs/context/VERIFY.md` and nearest owning docs |

## Pre-Code Performance Reflection

Before applying code, agents must ask whether the proposed change can reach the
same correct observable result with fewer lifecycle phases, event listeners,
renders, reflows, recalculations, bridge calls, polling loops, rebuilds, or
runtime cycles. The shortest correct path is the default architecture.

Doing two steps when one step is sufficient is architecture waste. If the
reflection identifies duplicated state, avoidable recalculation, layout thrash,
redundant listeners, bloated control flow, unnecessary abstraction, or delayed
feedback, simplify before editing or include the simplification in the edit.

The simpler path must stay readable, owned, and verifiable. Extra work is valid
only when it is explicitly justified by correctness, safety, compatibility, or
observability that shortens future proof/debug loops.

## Harness Factory Reflection

After intent/context routing and before slow investigation, rebuilds, runtime
control, or source edits, check `HARNESS.md` and prefer an existing deterministic
promise from `HARNESS_PROMISES.json` when it answers the uncertainty. Use
freeform agent reasoning for novel diagnosis, contract design, and promise
promotion, not for repeated checks that already have a bounded command.

Repeated manual inference should be harvested: the second repeat needs a
promise candidate or a reason it cannot be deterministic yet; the third repeat
must be promoted or blocked on a named missing primitive, access, or
observability field.

## Verified Loop-Aware Engineering

Use this doctrine for meaningful native, bridge, wake-word, hot-op,
runtime-control, release, or rebuild-heavy work. The goal is to shorten future
loops without letting a shortcut authorize itself.

| Phase | Required check |
| --- | --- |
| Before patch | Ask whether architecture, live control, HMR, hot-op, config, downloaded runtime/model, feature flag, replay, or diagnostics can avoid or shrink a rebuild. |
| Before rebuild | Check whether logs, counters, state, recent events, permissions, diagnostics, or a status command will explain success/failure without manual inspection. |
| During rebuild | Record command, target, start/end or approximate duration, validation command, evidence inspected, and whether rebuild was avoidable. |
| After rebuild | Note what slowed the loop, whether proof was sufficient, and the next loop-shortening opportunity. |

Rule of Three:

| Role | Responsibility |
| --- | --- |
| Builder | Proposes and implements the patch, shortcut, hot-op, diagnostic, or validation path. |
| Watcher | Independently verifies truth from tests, logs, counters, runtime/app/device state, diagnostics, or reproducible reports. |
| Gatekeeper | Accepts, blocks, rolls back, requires rebuild, or escalates based on Builder intent plus Watcher evidence. |

If one Codex/Frontier instance performs all roles, keep the sections separate in
the report. Prefer three evidence classes whenever possible: static evidence,
runtime evidence, and behavioral evidence. Prime checkpoints must be atomic,
independent, falsifiable, observable, and non-redundant.

## Copilotability Fast Path

Fresh agents should use product/runtime introspection before guessing. When an
app exposes live state, control commands, capability reports, diagnostics, UI
summaries, snapshots, or policy knobs, prefer those channels before asking the
user to narrate state or before proposing slower rebuild/reinstall loops.

| Need | First action |
| --- | --- |
| Know current screen/state | Use the narrowest available runtime snapshot/state endpoint. |
| Know what actions are possible | Read capability reports and visible-action/UI summaries. |
| Change behavior | Prefer live policy/config/control knobs before source/package changes. |
| Need heavier proof | Request explicit diagnostics/export/screenshot through idle-gated paths only. |
| Missing primitive/permission/native dependency | Then consider rebuild/reinstall/package changes. |

Performance guard: remote access is subordinate to UX. Introspection must be
compact by default, idle/debounced for heavy work, capped, redacted, and allowed
to return `{skipped: true, reason}` rather than forcing debug work during active
user interaction.

## Reply Next-Step Phase

Every substantive agent reply should end with a short next-step phase. Keep it
concrete and loop-shortening:

1. Name the immediate next action or command.
2. Say whether it uses live introspection/control, local static checks, or a rebuild/runtime proof.
3. If blocked, name the missing access or proof instead of giving a broad menu.
4. If suggesting rebuild/reinstall/package work, state the missing primitive or proof that makes it necessary.
5. Never claim runtime success from source/static/build checks.

## Conflict Law

1. Production/security guard wins.
2. Current code/runtime evidence beats older docs.
3. Closest child `AGENTS.md` wins for local implementation details.
4. Parent/root wins for global safety and verification standards.
5. Roadmap/future docs never beat implemented runtime docs.
6. If still unclear, demote to `unknown` and write the exact inspection needed.

## Compression Rule

After editing context, compress once:

- Prefer tables over paragraphs.
- Replace vague success words with status enum plus proof.
- Move local details downward.
- Delete repeated philosophy and debugging diary text.
- Keep one durable next action per active area.
- Keep generated/runtime state out of source docs unless it is the proof target.
