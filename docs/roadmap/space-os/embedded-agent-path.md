# Embedded Agent Path

Date: 2026-05-04

## Question

Can Space OS run a configurable embedded agent inside the visual agent surface so
the user can talk to it from there while it observes the user's UI actions,
browser harness state, and workspace context through explicit contracts?

## Decision

Proceed as a parallel roadmap path, separate from the remote-cloud-browser
harness.

The browser harness path proves that the frontend can visualize and control a
host-rendered browser surface. The embedded agent path proves that an agent can
live inside that same product surface with enough observation and action context
to collaborate from inside the workspace, not only from the terminal.

Phase 1 is active in `wasm-agent`: the app has a session-only Observation
inspector that records app-local semantic analytics and renders the structured
snapshot an embedded agent session would receive. Phase 2 has started with a
global avatar overlay that can pop over every app panel and send chat turns
through the existing bridge with the current observation snapshot attached.
Action execution is still a future phase.

## Why This Runs In Parallel

The two tracks answer different questions:

- `wasm-agent` and the browser harness answer: can the frontend see and steer a
  host/browser runtime efficiently?
- Embedded agent answers: can an agent inhabit that frontend, watch the user's
  actions, and reason with the same state the user sees?

The browser harness should keep improving independently until the
remote-cloud-browser-harness is stable. Embedded agent can start with a simpler
local observation stream and grow toward the browser harness once both sides
have explicit state contracts.

## Current Inputs

Already available in this repo:

- Hermes Orchestrator node lifecycle and logs through `horc`.
- Hermes Space UI bridge endpoints on `http://127.0.0.1:8790`.
- `wasm-agent` shadow PWA on `http://127.0.0.1:8877`.
- Host Browser widget pixels and input forwarding through `wasm-agent`.
- Bridge payload contracts for nodes, logs, tasks, resources, and actions.
- Global embedded assistant overlay with local transcript continuity, mode and
  target-node selectors, streaming action chains, compact context previews, and
  automatic Timeline checkpoints when a turn changes files.
- Browser-built `hermes.wasm_agent.image_card.v1` metadata plus a local
  `state/attachments` asset store, so image turns can give text-only providers
  compact visual facts instead of raw data URLs. Image-card perception now has
  module contracts for the resident Canvas pass, lazy native barcode detection,
  lazy native OCR probing, and disabled CV/semantic placeholders with explicit
  evidence statuses.

Missing for this path:

- Durable multi-user conversation storage outside browser local storage.
- A full agent session lifecycle owned by the orchestrator or bridge.
- A backend-delivered durable observation stream from the UI to the agent; the
  current path sends the current compact snapshot per turn and stores only the
  latest debug snapshot.
- A structured action ABI from the agent back to the UI/runtime.
- Policy rules for what the embedded agent may see, click, type, submit, or run.
- Persistent recording/replay of user-visible actions for debugging and trust.

## Target Experience

The user opens Space OS and can talk to the configured agent from inside the agent workspace.
The embedded agent can see the same high-level state the user sees:

- active page/domain in the Host Browser widget
- recent clicks, typed URLs, submitted prompts, and widget focus changes
- selected Hermes node, recent task state, logs, resources, and Guard state
- browser harness status, frame health, navigation status, and errors
- current workspace layout and active panel

The embedded agent can answer from inside the workspace, propose actions, and eventually
request explicit UI actions such as navigate, click, type, run prompt, inspect
node, or tail logs.

## Architecture Direction

```text
wasm-agent PWA
  -> observation/event stream
  -> embedded agent session adapter
  -> Hermes bridge / orchestrator API boundary
  -> Hermes Agent runtime
  -> proposed actions back through policy + UI confirmation
```

The embedded agent must not scrape random DOM as its primary state source.
`wasm-agent` should publish an explicit observation snapshot and event stream.
The agent should use an explicit action ABI rather than ad hoc browser globals.

## Runtime Contract

The embedded agent must follow the root engineering philosophy: performance,
efficiency, and simplicity before autonomy or spectacle.

Default turn shape:

- send a compact observation summary, not the full UI snapshot
- include the latest user message and only the last few relevant transcript
  turns
- expose tools for context lookup instead of stuffing files, logs, screenshots,
  or task history into the prompt
- stream visible progress and return bounded errors when the backend is slow
- keep every expensive operation behind an explicit timeout and budget
- report response source, tools used, context size, and duration after each
  turn so optimization work is driven by measured pressure
- show a clipped context preview so the user can inspect what was used without
  sending or rendering unbounded tool output
- keep app-change replies in the normal transcript and let Timeline create
  named git-backed recovery points automatically only when a turn changes files
- expose a simple mode selector (`auto`, `local`, `bridge`) so model-backed
  calls are explicit and measurable
- keep the avatar draggable and persist local session transcripts so short
  development loops survive refreshes without requiring backend account state
- keep the embedded assistant behind the `wasm-agent` Modules panel until
  action execution and backend ownership have clearer contracts
- pair app-evolution chat turns with the Timeline module so risky UI changes
  get automatic, prompt-named recovery points instead of manual proposal cards
- convert image attachments into compact image cards before the model turn:
  browser decode, Canvas pixel stats, palette, perceptual hash, visual notes,
  lazy analyzer evidence, local asset URL, then `attachment_manifest`

Initial tool set should be small and inspect-only:

- `observation_latest`: read the latest local UI snapshot
- `read_file`: read allowlisted repo docs and plugin files with size limits
- `search`: run bounded text search under allowlisted roots
- `git_status`: show local worktree state
- `git_diff_stat`: show the current local diff shape without sending the full
  patch
- `doctor`: run plugin-owned health checks such as `wasm-agent` doctor
- `app_map`: summarize the files and contracts needed for cheap app-evolution
  turns from inside the chat
- `timeline_status`: inspect current branch, head, dirty state, branch lanes,
  and local checkpoint refs before proposing risky changes

Mutation tools come later and must be confirmation-first:

- `apply_patch`
- `restart_wasm_agent`
- timeline branch, merge, and restore actions
- browser actions
- node lifecycle actions
- task submission

Context budget rules:

- prefer summaries under 1,000 tokens
- clip tool output before model input
- keep full transcripts in local state, but send only a short rolling summary
  plus recent turns
- never send secrets, env files, bearer tokens, full private logs, or raw
  screenshots by default
- never require raw image bytes for text-only providers; send image cards first
  and use raw `image_url` forwarding only when explicitly enabled

The first goal is not to make the embedded agent autonomous. The first goal is
to let it answer accurately from inside the app, fetch small context on demand,
propose small app patches from that context, and show exactly what context or
tool result it used.

## Contract Drafts

### Observation Snapshot

Schema name: `hermes.space_os.observation.v1`

Fields:

- `timestamp`
- `workspace`: active panel, selected widget, layout version
- `browser`: URL, domain, status, viewport size, stream mode, last error
- `fleet`: selected node, node summaries, resource summary, Guard summary
- `tasks`: active task, recent tasks, last task output summary
- `logs`: selected node, last loaded log channel, log summary
- `user_events`: recent bounded event list

### User Event

Schema name: `hermes.space_os.user_event.v1`

Event examples:

- `browser.url_submitted`
- `browser.navigation_started`
- `browser.navigation_finished`
- `browser.click`
- `browser.type`
- `workspace.widget_focused`
- `workspace.panel_selected`
- `fleet.node_selected`
- `task.prompt_submitted`
- `logs.loaded`

Events should be compact and agent-readable. They should not contain secrets,
full pages of logs, or unbounded screenshots.

### Agent Action Request

Schema name: `hermes.space_os.agent_action_request.v1`

Action examples:

- `browser.navigate`
- `browser.click`
- `browser.type`
- `browser.scroll`
- `node.inspect`
- `node.tail_logs`
- `task.submit_prompt`
- `workspace.focus_widget`

Each action request must include:

- `action_id`
- `action`
- `arguments`
- `reason`
- `risk`
- `requires_confirmation`
- `rollback_or_stop_hint`

The UI should show requested actions before execution whenever they mutate
browser state, submit prompts, or affect node lifecycle.

## Safety Boundaries

- Do not give the embedded agent raw shell execution from the UI.
- Do not let the embedded agent bypass Hermes bridge allowlists.
- Do not let browser pixels become the only state source; provide structured
  observations and bounded snapshots.
- Do not stream secrets, env files, bearer tokens, or full private logs into the
  observation feed.
- Do not run lifecycle actions without explicit confirmation.
- Do not claim full autonomy until record/replay and stop controls exist.

## Implementation Phases

### Phase 1: Local Observation Panel

Add a read-only observation/debug panel in `wasm-agent` that shows the exact
snapshot the embedded agent would receive.

Deliverables:

- local `hermes.space_os.observation.v1` snapshot builder: implemented
- recent user-event ring buffer in the PWA: implemented
- visible observation JSON/debug view: implemented as the Observation inspector
- docs naming every observed field: implemented at plugin and roadmap level

Current v1 boundaries:

- app-local semantic analytics only
- session-only browser memory
- no OS-wide capture
- no raw document-level key recorder
- global embedded chat overlay exists, but no agent action execution yet

### Phase 2: Local Chat Surface

Add a global chat overlay that can talk to a configured Hermes-compatible backend
without giving it write actions.

Deliverables:

- global avatar/chat overlay in `wasm-agent`: implemented
- session id and transcript state: partial, browser-memory transcript only
- observation snapshot attached to each turn: implemented
- streaming action chain: implemented
- compact image-card context for attachments: implemented
- lazy image-card analyzer module cache and evidence statuses: implemented
- lazy OCR fallback using native `TextDetector` plus cached Tesseract.js runtime:
  implemented
- image-card analyzer revision marker for stale browser/runtime diagnosis:
  implemented
- server-side stale image-card enrichment before model inference: implemented
- local attachment asset store under `state/attachments`: implemented
- attachment store byte/file/age retention pruning after saves: implemented
- same-origin wasm-agent `/bridge` proxy for PWA bridge calls: implemented
- no UI action execution yet: implemented

### Phase 3: Inspect-Only Adapter Hardening

The local `/agent/session/message` adapter exists and remains inspect-only. It
can gather observation, file, search, worktree, doctor, app-map, Timeline, and
attachment-manifest context before asking the selected node or answering
locally. The next hardening work is reliability and context quality, not write
actions.

Deliverables:

- verify image-card quality against real screenshots and user images
- keep action chains accurate across slow bridge calls, aborts, and HMR reloads
- improve local deterministic resume/harness answers from the updated roadmap
- keep attachment storage bounded, same-origin, and gitignored: implemented for
  the local asset cache; continue watching real-use retention pressure

### Phase 4: Proposed Actions

After the inspect-only adapter is stable, let the embedded agent propose
structured actions. Mutation actions remain disabled until the user can see and
approve the exact requested operation in the UI.

Deliverables:

- action request schema
- pending action queue
- approve/reject controls
- execution through existing bridge/browser functions only
- action result events returned to the agent

### Phase 5: Full Harness Integration

Connect the embedded agent to the remote-cloud-browser-harness once the browser
path has stable state/action contracts.

Deliverables:

- browser observation beyond pixels
- DOM/accessibility-like snapshot when available
- frame health and latency data
- safe remote browser lifecycle controls

## Stop/Go Criteria

Proceed only if the path can show:

- the agent receives a faithful structured snapshot of what the user sees
- the user can inspect what the agent observed
- proposed actions are bounded and confirmable
- browser and node actions route through existing safe boundaries
- CPU/memory overhead stays acceptable while the agent watches
- transcripts and action events can be replayed for debugging

Stop and revisit architecture if the first implementation requires DOM scraping,
unbounded screenshots, raw shell access, or direct Space Agent/Hermes core
patches.

## Open Questions

- Should the bridge-mediated `/agent/session/message` adapter stay plugin-local
  or graduate into an orchestrator-owned session service?
- Should observations remain pulled per turn, become a durable stream, or use
  both patterns?
- How much browser state can be represented safely before the remote browser
  harness has DOM/accessibility snapshots?
- Where should durable transcripts live beyond browser local storage:
  `wasm-agent/state`, node-local workspace plugin cache, or Hermes Agent state?
- What is the minimal UI affordance for "Agent saw this, the agent wants to do
  that, approve?"
- Which image-card metrics or lazy analyzer modules are useful enough to move
  from Canvas JavaScript/native browser APIs into small WASM pixel modules?

## Next Actions

1. Treat the WASM harness as the active resume branch; keep browser harness
   hardening parallel but secondary.
2. Validate the cheap-eyes image cards and lazy analyzer evidence with real
   screenshots and user images, then decide whether any hot pixel work deserves
   a small WASM module.
3. Harden the embedded avatar chat lifecycle: transcript storage policy,
   retry/error states, visible context preview, and exact action-chain status.
4. Keep Observation and the Embedded Assistant inspect-only and locally
   switchable through the Modules panel.
5. Add proposed action execution only after the chat surface can show exactly
   what context was sent to the agent and what action would run.
