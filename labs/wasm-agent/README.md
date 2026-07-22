# WASM Agent Safe Lab

This lab gives Master:frontier a container-owned writable `/local` without
granting write access to the host workspace. The host creates a reviewed seed
archive; the container imports it once into a named volume and then edits only
that volume.

The fixture profile has no network, no host PID/device namespace, no host
runtime socket, no credentials, a read-only container root, dropped Linux
capabilities, bounded resources, and an external read-only canary mount. It
exports proposed diffs and proof through a separate output volume.

The lab is not the production backend. Production remains cloud-only at
`https://wa.colmeio.com`; localhost inside the lab is development-only.

## Workflow

```bash
python3 labs/wasm-agent/prepare-seed.py
docker compose -f labs/wasm-agent/compose.yml build
docker compose -f labs/wasm-agent/compose.yml run --rm seed
docker compose -f labs/wasm-agent/compose.yml run --rm canary
docker compose -f labs/wasm-agent/compose.yml run --rm frontier
```

`seed` refuses to overwrite a non-empty lab volume. To refresh it, create a
new versioned volume instead of erasing the active one. Do not bind-mount host
`/local` into any lab service. Seeding initializes a local Git repository with
no remote and commits the imported files as the diff baseline.

The canary is a containment proof, not proof against container-runtime or
kernel vulnerabilities. Host audit/snapshot storage must remain outside all
lab mounts.

## Historical fixture bank

`generate-fixture-bank.py` opens the production/local source database read-only
and creates one pending, redacted fixture candidate per avatar-chat run. Raw
run, session, and user identifiers and raw event payloads are not copied. The
host-side database is ignored staging data; copy it into `/lab-output` to make
the safe-lab volume the canonical benchmark input.

## Nine-lane orchestration

`nine-lane-orchestrator.py` is a fixed-authority host coordinator. It launches
nine sibling containers in parallel and never passes the Docker socket into a
lane. Each lane receives read-only source and fixture volumes plus private
writable workspace and result volumes.

```bash
python3 labs/wasm-agent/nine-lane-orchestrator.py \
  --mode benchmark --execution topology-proof --run-id loop3-proof-001
python3 labs/wasm-agent/nine-lane-orchestrator.py \
  --mode improve --execution topology-proof --run-id loop5-proof-001
```

Topology-proof adapters are explicitly simulated and cannot be ranked. Live
mode fails closed until all nine registry entries prove the same GLM-5.2 model
artifact, endpoint, tool authority, fixture snapshot, and budgets.

The genuine Loop 3 benchmark uses one host-owned internal gateway and one
digest-bound task projection, then mounts nine immutable adapters into nine
private writable workspaces. Private scoring and cleanup occur on the host:

```bash
python3 labs/wasm-agent/nine-lane-orchestrator.py \
  --mode benchmark --execution live --run-id loop3-live-nine \
  --fixture-id fx_d3154de08df6150be9c9
python3 labs/wasm-agent/rank-nine-lane-benchmark.py \
  labs/wasm-agent/staging/loop3-live-nine-benchmark-nine-lane.json
```

Ranking requires broker-authenticated `laneId` on every receipt and fails
closed if any lane, semantic score, or attribution is missing. Semantic success
is a mandatory gate; the weighted score compares latency, prompt context,
provider calls, nonterminal tools, and warnings only among passing lanes.

Loop 4 retains one typed outcome for every exact candidate digest. A candidate
regression disqualifies only that variant; a complete matrix may rank the
remaining passing variants and may also terminate cleanly with no winner when
all nine fail. The deterministic policy tests use temporary artifacts only:

```bash
python3 labs/wasm-agent/test_learning_harness.py
```

Every lane now reserves `WASM_AGENT_EVENTS_PATH` for optional adapter-emitted
JSONL. `agent_trajectory.py` maps accepted search/read/edit/command/test/diff,
checkpoint, proof, and terminal events into a compact shared field dictionary,
hashes raw arguments, redacts summaries, drops private-reasoning events, and
caps bytes and event count. The lane always appends its own terminal event.
The deterministic fake adapter proves that boundary without a provider or
container:

```bash
python3 labs/wasm-agent/test_agent_trajectory_fixture.py
```

Current external adapter runners do not yet emit these optional trajectories,
so their lane metadata remains ineligible for strategy mining until a runner is
wired and independently proven.

Nine-lane semantic and efficiency scores remain reportable without strategy
events, but `rank-nine-lane-benchmark.py` fails closed for learning: it emits no
golden-pattern candidates unless the report and every lane are strategy
comparable, every normalized trajectory is admissible, and tool-call counts are
observable rather than inferred as zero. The deterministic regression is:

```bash
python3 labs/wasm-agent/test_strategy_ranking.py
```

Normalized events now cross the lane boundary with explicit `adapter` or
lane-owned provenance and a fail-closed completeness classification. Pure
sequence extraction requires the same observed action motif from at least two
agents across at least three distinct fixture instances; one benchmark run can
never manufacture a golden pattern. Raw prompts, reasoning, arguments, and tool
results remain outside the learning projection.

Multi-turn continuity has a separate twelve-case semantic contract covering
adjacent references, corrections, topic changes, compaction, restart,
interruption, and completed mutation receipts:

```bash
python3 labs/wasm-agent/prove-session-continuity-contract.py
```

This is static fixture/comparability proof. It deliberately reports
`session_comparability_pending` until Master:frontier, Codex, Claude Code, and
Gemini CLI each have an isolated native-session artifact; it is not a live
cross-agent quality score.

Hermes is packaged without host runtime state or credentials:

```bash
python3 labs/wasm-agent/package-hermes-adapter.py
```

The package command copies `hermes-agent/.venv` and Git-tracked Hermes source
into a versioned named volume. It excludes nested Git metadata, runtime state,
configuration, credentials, memory, and environment files.

Master:frontier V5 is packaged as a separate immutable adapter artifact rather
than importing its implementation from the replay source volume:

```bash
python3 labs/wasm-agent/check-master-frontier-v5-adapter.py
python3 labs/wasm-agent/package-master-frontier-v5-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-01 --fixture-id fx_d3154de08df6150be9c9
```

The packager preserves source-relative module depth and runs a no-network
unprivileged import probe on new packages and cache hits. This prevents an
invalid package layout from consuming a provider call.

Codex uses the real packaged CLI with an ephemeral private `CODEX_HOME` and no
host auth/config/session state. Codex custom providers speak the Responses API,
so `responses_bridge.py` translates the bounded Responses request to the same
GLM-5.2 Chat Completions upstream used by every other adapter, then translates
text, function calls, and exact usage back to Responses events:

```bash
PYTHONPATH=labs/wasm-agent python3 labs/wasm-agent/check-responses-bridge.py
python3 labs/wasm-agent/check-codex-adapter.py
python3 labs/wasm-agent/package-codex-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-02 --fixture-id fx_d3154de08df6150be9c9
```

The outer safe-lab container is the security boundary, so Codex runs with its
documented externally-sandboxed automation mode rather than attempting a nested
sandbox. The lane still has no direct internet, host mounts, runtime socket,
device access, provider credential, or write access outside its private volume.

Claude Code uses the real packaged native CLI with an ephemeral home and config,
bare non-persistent execution, and only a run-scoped broker credential. Its
Anthropic Messages and local `count_tokens` surfaces are translated by
`anthropic_bridge.py` into the common GLM-5.2 provider contract:

```bash
python3 labs/wasm-agent/check-anthropic-bridge.py
python3 labs/wasm-agent/check-claude-code-adapter.py
python3 labs/wasm-agent/package-claude-code-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-04 --fixture-id fx_d3154de08df6150be9c9
```

Semantic success and efficiency are separate gates. A self-contained
conversation that succeeds after unnecessary tool calls remains benchmark-ready
but receives `unnecessary_tool_use_for_self_contained_conversation`; the fixture
bank can then test a generic tool-necessity improvement without rewriting the
observed history or silently weakening equal tool authority.

Gemini CLI uses the integrity-pinned official npm distribution and a pinned
Node 22 runtime in an immutable adapter volume. An ephemeral lane-only Gemini
home selects API-key auth because Gemini CLI 0.50.0 rejects its advertised
gateway auth enum in headless validation; the API key is still only the
run-scoped broker token, and `GOOGLE_GEMINI_BASE_URL` still routes Google
GenerateContent traffic exclusively to the private gateway:

```bash
PYTHONPATH=labs/wasm-agent python3 labs/wasm-agent/check-gemini-bridge.py
python3 labs/wasm-agent/check-gemini-cli-adapter.py
python3 labs/wasm-agent/package-gemini-cli-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-05 --fixture-id fx_d3154de08df6150be9c9
```

The bridge handles `generateContent`, streaming GenerateContent, local
`countTokens`, tools, and function responses while retaining common provider
and duplicate budgets. Excessive prompt context on self-contained conversation
fixtures remains successful but emits
`excessive_prompt_context_for_self_contained_conversation` for Loop 2/3 cost
adjudication.

Aider uses the official `aider-chat` distribution in an immutable isolated
Python venv and its documented OpenAI-compatible endpoint. One-shot message
mode disables git integration, commits, analytics, update checks, browser
tooling, streaming, and interactive confirmations. Config and histories exist
only inside the lane's private workspace:

```bash
python3 labs/wasm-agent/check-aider-adapter.py
python3 labs/wasm-agent/package-aider-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-06 --fixture-id fx_d3154de08df6150be9c9
```

Aider CLI stdout contains banners and status text, so the adapter uses Aider's
owned chat-history parser and emits only the final assistant role. Missing final
assistant evidence fails closed; semantic answer limits are never expanded to
accommodate CLI noise.

OpenCode uses the official integrity-pinned Linux ARM64 native artifact directly
rather than running npm lifecycle scripts. Pure one-shot JSON mode receives an
ephemeral inline custom provider using `@ai-sdk/openai-compatible`; completed
text events alone become the benchmark answer:

```bash
python3 labs/wasm-agent/check-opencode-adapter.py
python3 labs/wasm-agent/package-opencode-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-07 --fixture-id fx_d3154de08df6150be9c9
```

Remote model fetches, plugins, Claude state, LSP downloads, updates, sharing,
and internet tools are disabled. Multiple distinct provider calls on a
self-contained task without a tool loop remain successful but emit
`unnecessary_auxiliary_provider_call_for_self_contained_conversation`.

Goose uses the official integrity-pinned 1.41.0 Linux ARM64 GNU release. Its
native quiet, text-output, no-session run surface provides the final answer;
default extensions, session naming, tool-call summaries, keyring state, and
host configuration are disabled:

```bash
python3 labs/wasm-agent/check-goose-adapter.py
python3 labs/wasm-agent/package-goose-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-08 --fixture-id fx_d3154de08df6150be9c9 \
  --report reports/context/latest/live-fixture-goose-semantic-result.json
```

The brokered live proof validates the exact model, private-network isolation,
canonical tool authority, and an agent-created workspace artifact. It consumes
provider tokens and keeps Hermes non-rankable until the generic fixture-task
runner is wired:

```bash
python3 labs/wasm-agent/prove-hermes-live-adapter.py
```

OpenHands uses the official 1.16.0 PyPI CLI resolved with its documented `uv`
installation path. Headless JSONL runs with environment-only model overrides;
its process runtime is contained inside the lane and receives neither Docker
authority nor host state:

```bash
python3 labs/wasm-agent/check-openhands-adapter.py
python3 labs/wasm-agent/package-openhands-adapter.py
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-09 --fixture-id fx_d3154de08df6150be9c9 \
  --report reports/context/latest/live-fixture-openhands-semantic-result.json
```

One real SQL fixture can be materialized and executed through the same generic
lane contract used by future adapters:

```bash
python3 labs/wasm-agent/live-fixture-orchestrator.py \
  --slot harness-03 --fixture-id fx_d3154de08df6150be9c9
python3 labs/wasm-agent/check-live-fixture-result.py \
  reports/context/latest/live-fixture-hermes-result.json \
  --fixture-id fx_d3154de08df6150be9c9
```

Technical `liveReady` does not authorize ranking. A fixture with unresolved
semantic correctness remains non-rankable, and the nine-lane benchmark gate
also requires `benchmarkReady` for every adapter.

## Private semantic adjudication

The 400-candidate SQL bank remains immutable and pending. A separate overlay
admits a deduplicated semantic slice only when two independent checks agree:
bounded source evidence and a stable, self-contained task contract. Expected
properties and holdout membership stay in `private_evaluator/`, which the seed
manifest excludes from lane `/source` snapshots. The materialized task exposes
only contract and overlay digests; trusted host scoring happens after the lane
has finished.
