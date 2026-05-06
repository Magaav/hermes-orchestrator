# wasm-agent

`wasm-agent` is the shadow WASM-first UI plugin for Hermes Orchestrator.

It exists so the team can build a new Hermes Agent UI runtime in parallel with
`hermes-space-ui` without changing the current Space Agent integration. The
first milestone is visual and behavioral parity with the useful Hermes UI
surfaces; after parity, this plugin can become the runtime substrate for
Space OS work that needs GPU-oriented rendering, agent-readable state, and a
cleaner app shell.

## Current Behavior

- Serves a local installable PWA shell on `http://127.0.0.1:8877`.
- Keeps the existing Hermes bridge/API contract as the backend boundary,
  defaulting to `http://127.0.0.1:8790`.
- Loads an embedded WebAssembly core in the browser and uses it as the first
  rendering/runtime handshake for the parity shell.
- Does not start, stop, copy, or patch Space Agent.
- Does not modify `/local/plugins/hermes-space-ui`.

The current app is an early browser-view parity surface, not a full replacement
for `hermes-space-ui`. It now presents a Hermes OS workspace shell with a
launcher rail with a Home target, draggable floating widget cards, an idle black space canvas,
resource monitoring, topology, recent task state, logs, node action controls,
prompt submission, and an Observation inspector through the same documented
bridge endpoints used by Hermes Space UI. Node cards reuse the bridge's allowlisted action descriptors
for inspect, logs, start, stop, and restart; destructive lifecycle actions ask
for browser confirmation before they call the bridge. The launcher mark opens
an intentionally empty black homespace, which is the future starting surface for
new home/workspace experiments. Widget positions are
stored locally in the browser and can be reset by double-clicking the widget
header. Clicking or focusing anywhere inside a widget brings that widget to the
front. A workspace layer dock can also bring any widget above the stack when it
is buried by overlapping cards.

The Host Browser widget is deliberately pixel-based, not iframe-based. It asks
the local `wasm-agent` backend to use host Chromium through CDP, capture a URL,
and return a PNG data URL for display inside the workspace. It keeps the host
browser target alive so the widget can forward click, type, key, and scroll
events and receive refreshed pixels after each action. This proves browser
output and basic input can enter the interface while keeping arbitrary external
browsing outside the PWA's own network and DOM sandbox. If CDP is unavailable,
the backend falls back to a one-shot Chromium screenshot command without
interactive input. The preferred path is now `/browser/stream`: a WebSocket that
pushes CDP screencast frames into a canvas and accepts click/type/key/scroll,
navigation, and resize input over the same connection. Captures use the Browser
Proof pixel surface dimensions so the returned image fits the widget exactly and
input coordinates map cleanly. The status chip stays stable as `stream` or
`live`; refresh details move to the meta line to avoid screenshot/live flicker.
The widget includes Back, Forward, and Reload controls. The Host Browser widget
has a resize grip. Every floating widget has a `Top` control so it can be placed
above overlapping widgets deliberately; the workspace layer dock provides the
same action from outside the widget stack. Submitting another URL while the
stream is open navigates the current host browser target instead of tearing down
the stream, and incoming frame URL updates do not overwrite the address field
while the user is editing it. Stream navigation pauses screencast frames during
the page change and restarts them afterward. The backend also throttles the CDP
screencast before forwarding frames to the PWA so animated pages do not decode
every available browser frame. A snapshot frame is forced after open, navigate,
and resize so pages that do not immediately emit a fresh screencast frame still
update the canvas. The URL bar keeps an edit draft separate from stream URL
updates, so clicking Open or pressing Enter after typing a second domain uses
the typed value even if the previous page is still emitting frames.

The Observation inspector is the first embedded-agent framework layer. It keeps
a session-only, in-memory ring buffer of app-local semantic events and renders
the current `hermes.space_os.observation.v1` snapshot that an embedded agent
session would receive. It also debounces the latest snapshot to the local
`wasm-agent` backend at `/observation/latest`, which stores only the latest
debug snapshot under `state/observation/latest.json` so the orchestrator side
can inspect the most recent clicked element or UI event. It captures workspace
clicks, widget focus/layer/drag and resize actions, browser navigation and
forwarded input actions, task submits, node action requests, logs loads, bridge
refreshes, stream frame health, timings, and errors. It does not persist a
durable observation history, upload it, capture OS-wide input, or install a
document-level raw key recorder. Typed text forwarded into the Host Browser is
summarized/redacted; submitted Hermes prompts are summarized with length
metadata because the user already submitted them to the bridge.

The embedded assistant now has a global avatar overlay that sits above every
app panel, including Home, OS Space, Fleet, Logs, and Observation. Opening the
avatar reveals a chat panel that sends the user's message plus the current
bounded observation snapshot through the existing Hermes bridge
`/v1/chat/completions` endpoint. The chat header includes a node selector under
the `Chat` title; bridge-backed turns include that `target_node`, so operators
can switch between orchestrator and worker nodes without leaving the panel.
This first inner-agent surface is chat-only: it can see the structured context
sent with the turn, but it does not execute UI, browser, node lifecycle, or
shell actions from the browser. Bridge calls are bounded by a visible timeout
so the overlay reports slow or unavailable agent backends instead of spinning
forever.

The embedded-agent runtime step is now active through the local
`/agent/session/message` adapter. It gathers compact context through
inspect-only tools (`observation_latest`, `read_file`, `search`, `git_status`,
`git_diff_stat`, `timeline_status`, `doctor`, and `app_map`) before asking the
bridge model for a reply. The browser sends only a clipped recent transcript,
not the full local conversation store. When the user asks to evolve the app
from chat, the adapter adds app-map, worktree, and Timeline context so the
in-app assistant can answer with a compact implementation brief while the
selected node remains the execution target. This keeps the avatar aligned with
the project philosophy of
performance, efficiency, and simplicity: small context by default, tools on
demand, visible timeouts, and no mutation actions.

The avatar shows lightweight diagnostics for the last turn: response source,
tools used, estimated context tokens, and duration. It also includes a collapsed
context preview drawer with clipped tool summaries so the user can inspect what
the adapter used without flooding the prompt or UI. These metrics are the first
feedback loop for deciding what should stay as simple Python/JavaScript logic
and what, if anything, deserves a later WASM context engine.

Assistant replies no longer render a separate proposal card. App-change
conversation stays in the normal transcript, while recovery evidence lives in
the Timeline road. The adapter snapshots the worktree before and after each
chat turn; if the turn did not change files, the reply has no changed-files
footer and no automatic Timeline point. If files did change, the adapter creates
a named git-backed Timeline checkpoint using a short subject based on the
target node and the user's prompt.

The avatar mode selector controls how `/agent/session/message` answers:
`Auto` uses local deterministic answers for known cheap resume/readme prompts
and uses the selected node through the bridge model for other turns, `Local`
never calls the model and answers from inspect-only tools, and `Bridge`
explicitly asks the configured bridge model after gathering compact tool
context.

The avatar is draggable and remembers its position in browser local storage.
The chat header is icon-first: a sessions/history button opens a local session
balloon with the New Chat icon action, and a context button opens the latest
tool-context preview in a separate balloon. Transcripts, diagnostics, and
context previews are persisted in browser storage for quick development
continuity. This is local convenience state, not a durable multi-user account
store.

The composer uses a compact 34px send button with a restrained arrow icon.
While an embedded assistant turn is running, the button switches to a
stop-square state and aborts the in-flight `/agent/session/message` request
when clicked.

Image attachments are compressed in the browser before they enter the local
adapter request or transcript cache. The composer also enforces an aggregate raw
attachment budget; extra images stay as attachment summaries instead of making
the local adapter request too large. The backend repeats that budgeting before
calling the Hermes bridge and sends an `attachment_manifest` action to the model.
Raw OpenAI-style `image_url` message parts are disabled by default because some
configured node providers, including DeepSeek-compatible text endpoints, reject
multimodal content variants. Operators can opt in with
`HERMES_WASM_AGENT_FORWARD_IMAGE_URLS=1` only when the selected provider supports
those parts; the backend will still keep the bridge JSON body below its size cap.
The pending attachment strip is cleared as soon as the message is submitted, and
each pending thumbnail or summary chip exposes a visible remove control so
dropped images do not get stuck in the composer.

Image turns now use the browser as the first cheap perception pass. On attach,
the PWA decodes the image with native browser APIs, samples pixels through
Canvas, computes a compact perceptual hash, palette, luminance/contrast/edge
metrics, spatial brightness distribution, center/edge delta, rough gradient
direction, symmetry, sharpness, entropy, saturation, transparency, and builds a
`hermes.wasm_agent.image_card.v1` object. Image-card analyzers are module-backed
lazy singletons: `image-card-core` is resident with the app, `barcode-reader`
initializes native `BarcodeDetector` on first use when the browser supports it,
`ocr` tries native `TextDetector` first and then lazy-loads a cached
Tesseract.js runtime when needed, and planned CV/semantic modules stay disabled
until local runtimes are bundled. Before Tesseract runs, the browser crops the
likely text region, enlarges it, contrast-stretches it, and binarizes it so OCR
spends its bounded budget on readable markings instead of the full photo. The
core card also records text-like stroke/region signals so text-heavy photos can
say "likely printed or label-like markings" even when exact OCR is unavailable.
Loaded analyzer promises/functions remain cached in memory for later turns and
each result is recorded as evidence with a status such as `detected`,
`not_detected`, `unsupported`, `not_loaded`, `timeout`, or `error`. On send, the
local backend stores the compacted image under `state/attachments` and returns a
same-origin `/agent/attachments/<hash>.<ext>` URL plus metadata. The embedded
assistant action chain shows the image path explicitly: store image assets,
decode pixels, analyze image with lazy modules, build image cards, then ask the
selected node. The local attachment store prunes old assets after saves by
bounded byte, file-count, and age limits; it is a development/runtime cache, not
a durable media library.
Image cards include an `analyzer_revision` so stale browser/service-worker
runtimes are visible in model context. When the revision changes, the app
migrates image analyzer module defaults for core, barcode, and OCR back to the
current defaults while preserving deliberate toggles after the migration. The
backend also has a server-side safety net: if an old browser posts an image card
without the current analyzer revision, or a current browser card is missing
server-only scene/shape hints, the attachment store enriches it before sending
the card to the model. Server enrichment adds text-like stroke/region signals,
scene hints that separate likely printed labels or markings on a photographed
physical surface from bright flat documents or screenshots, and conservative
shape hints for rounded or cylindrical container-like surfaces. Shape hints are
used as broad geometry evidence only; the image-card-only bridge prompt should
not narrow them to mug, cup, can, bottle, package, or another object identity
without raw vision or user-provided context. OCR evidence can unlock exact
quoted text, but it does not by itself identify the object carrying that text.
Text-only providers still receive the image card through `attachment_manifest`;
vision-capable providers can opt in to raw `image_url` forwarding separately.
In `Auto` mode, simple attached-image questions such as "what is it?" now use a
bridge model turn over only the compact image-card manifest, with workspace
observation intentionally omitted. That image-card-only bridge payload redacts
attachment names, hashes, and local URLs before the model sees it, so file
bookkeeping cannot steer visual interpretation. The prompt asks the model for
the minimum useful interpretation supported by the card and forbids treating the
file name, local URL, or workspace context as proof that the image is a
wallpaper, object, or UI element. If the bridge is slow or unavailable, the
adapter falls back to a
local image-card summary.

OCR remains evidence-gated. The browser OCR analyzer first tries native
`TextDetector`; when that is unavailable or cannot read text, it loads
Tesseract.js from `window.__WASM_AGENT_TESSERACT_URL__` or the default
jsDelivr URL, caches the loaded script/worker function, and reports exact text
only through OCR evidence with `detected` status. Set
`window.__WASM_AGENT_TESSERACT_URL__ = ""` before app startup to disable the
remote runtime, or point it at a local `tesseract.min.js` bundle.

Each in-flight assistant reply now appears immediately as a response bubble with
a small header. The header shows that Hermes is thinking, the current phase,
and an elapsed counter that rolls from seconds to minutes and then hours for
long turns. The frontend and backend share the same configured turn timeout, so
slow bridge/model calls are visible instead of looking idle.

Assistant turns also render a compact action chain. While a turn is running the
chain stays open and grows with the visible client-side phases; when the adapter
returns, backend tool/action events are folded into the same chain and collapsed
above the final reply text. Each action carries a kind badge, status, focused
detail text, and an expandable arguments/result preview so inspect tools feel
closer to Discord's tool-call trail instead of generic progress rows. This
keeps the final answer at the bottom of the assistant bubble while preserving
the action trail.

The browser prefers `/agent/session/message/stream` for embedded chat turns.
That endpoint returns newline-delimited JSON action events as local adapter
tools finish, then a final agent payload; older browsers can still fall back to
the non-streaming `/agent/session/message` route.

The transcript sent to `/agent/session/message` is intentionally pre-turn
context only: it excludes the current user message, pending assistant bubble,
and default seed greeting. The current message is sent once in the explicit
`message` field so bridge-backed turns do not see duplicated short prompts.

User image messages render an expandable image-card panel below the thumbnail or
summary chip. This panel shows the same compact facts the adapter can send to
the model: dimensions, palette, visual notes, gradient/composition, key numeric
metrics, and the local asset URL. It is the human-facing audit trail for image
questions, separate from the raw JSON action preview.

The assistant panel stays anchored beside the draggable avatar. Panel placement
is side-first, uses a side latch so it does not chatter left/right while the
avatar is dragged, and clamps inside the visible viewport. Avatar drag bounds
also use `window.visualViewport` when available, so mobile scroll areas and
browser chrome do not let the icon escape the visible rectangle; viewport
resize resets the avatar to the visible bottom-right corner.

Assistant replies can include a Codex-style changed-files footer sourced from a
before/after worktree tree diff for that single request. Ambient dirty worktree
state is not shown as if the chat turn created it. The footer lives inside the
assistant message instead of the modal chrome, shows one collapsed summary row
by default, and expands to one full-path row per changed file with `+/-` counts.
The expanded list stays scroll limited after roughly four rows, so changed-file
reporting does not steal the main chat area.

The Modules panel is a local module management surface for the shadow PWA. It
stores enable/disable state in browser local storage for development and
image-perception modules: Dev HMR, Observation, Host Browser, Embedded
Assistant, Timeline, Image Card Core, Barcode Reader, OCR, CV Shapes, and
Semantic Vision. Toggling a module only changes local UI or analyzer
availability in `wasm-agent`; it does not install, remove, patch, or restart
backend components. The versioned module firmware lives under `public/modules/`
with `public/modules/index.js` as the app-facing registry. Per-user and runtime
state stays under `state/` or browser local storage, never inside the module
firmware folders.

The Timeline module is the first time-travel surface for cheap app evolution.
It reads git branch, head, dirty status, recent commits, local branches, and
`refs/wasm-agent-timeline/*` checkpoints through the local backend. Timeline
points are created automatically after chat turns that actually change the
worktree, using a temporary git index so tracked and untracked non-ignored
files can be captured without changing the real index or moving the current
worktree. Branch, merge, and restore actions are shown as planned
confirmation-gated actions until the UI can preview exact file effects and
stop/rollback behavior. Timeline metadata is local runtime state under
`state/timeline` and is gitignored.

The backend fingerprints the temporary-index tree in
`state/timeline/auto-latest.json`, so repeated runs with identical files do not
create duplicate refs, while new source changes get a new recovery point
without relying on the user to click a manual checkpoint button.

The Home route is the app entrance: `/` and `/home` open the intentionally
empty black homespace with no topbar or command form. Home exposes a compact
`+` control for creating local spaces; each new space is persisted in browser
storage and appears in the left global rail. The old fixed OS/Fleet/Run/Logs/
Observation/Modules shortcuts are no longer global space buttons; those views
remain internal panels/modules. The launcher stays a left rail across desktop
and narrow/mobile breakpoints so Home and user-created spaces keep the same
spatial position.

Frontend changes in this plugin must also read `DESIGN.md`. That design
contract records the current shell layout, centered icon-button rules, chat
message chrome, and the smoke-test checks that keep these details from
regressing.

The app also includes a small dev-only HMR module at
`public/modules/hmr/dev-hmr.js`. The local server exposes
`/modules/hmr/events` as a Server-Sent Events stream that watches
`public/` and `server/` source files. CSS changes are applied by reloading
stylesheet links with a cache-busting query string; JavaScript, HTML,
manifest, module descriptors, and server-source changes trigger a page reload.
The local dev runtime starts this HMR channel automatically whenever service
workers are disabled, even if the Dev HMR module was toggled off in older local
settings. The HMR handshake carries a source fingerprint; if the browser missed
an update while disconnected or an old client connects without the current HMR
revision, it receives a one-shot reload into the current client. This is a
developer convenience module for the local shadow PWA, not a production
synchronization contract. While this module is active, the app disables and
clears the service worker cache on load so stale cached JavaScript cannot trap
the PWA in an old broken build.

If a JavaScript, HTML, manifest, or server-source change arrives while an
embedded assistant turn is in flight, the HMR module now queues the page reload
until the turn finishes. The current session is saved before the deferred reload
is applied, so development-time UI edits no longer interrupt the active chat
request or resend oversized conversation payloads.

## Architecture

```text
wasm-agent PWA :8877
  -> WebAssembly runtime handshake
  -> Hermes bridge contract :8790
  -> Hermes Orchestrator CLI/API boundary
  -> Hermes Agent nodes
```

`hermes-space-ui` remains available separately:

```text
Space Agent PWA      http://127.0.0.1:8787
Hermes bridge        http://127.0.0.1:8790
wasm-agent shadow UI http://127.0.0.1:8877
```

## Setup

Start the current Space UI/bridge when you want live fleet data:

```bash
horc space start
```

Start the shadow WASM UI:

```bash
/local/plugins/wasm-agent/scripts/start_wasm_agent.sh
```

In remote IDE or container-backed workspaces, bind outward and use the IDE's
forwarded port URL:

```bash
HERMES_WASM_AGENT_HOST=0.0.0.0 /local/plugins/wasm-agent/scripts/start_wasm_agent.sh
```

If `http://127.0.0.1:8877` refuses from your desktop browser while the server is
healthy inside `/local`, your browser's loopback is not the same loopback as the
workspace. Forward port `8877` or use the workspace-provided forwarded URL.

Open:

```text
http://127.0.0.1:8877
```

Stop it:

```bash
/local/plugins/wasm-agent/scripts/stop_wasm_agent.sh
```

Run checks:

```bash
/local/plugins/wasm-agent/scripts/doctor.sh
```

## Environment

- `HERMES_WASM_AGENT_HOST`: bind host, default `127.0.0.1`.
- `HERMES_WASM_AGENT_PORT`: app port, default `8877`.
- `HERMES_WASM_AGENT_STATE_DIR`: state/log root, default
  `/local/plugins/wasm-agent/state`.
- `HERMES_WASM_AGENT_BRIDGE_URL`: Hermes bridge URL used by the PWA, default
  `http://127.0.0.1:8790`.
- `HERMES_WASM_AGENT_PID_FILE`: optional pid file override.
- `HERMES_WASM_AGENT_LOG_FILE`: optional server log override.
- `HERMES_WASM_AGENT_CHAT_TIMEOUT_SEC`: embedded assistant bridge/model turn
  timeout, default `300`, clamped between 30 seconds and 6 hours.
- `HERMES_WASM_AGENT_FORWARD_IMAGE_URLS`: opt in to forwarding raw `image_url`
  chat content parts to the bridge, default `0`. Leave disabled for text-only
  providers such as DeepSeek-compatible endpoints; the adapter still forwards
  attachment metadata through `attachment_manifest`.
- `HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_BYTES`: maximum local attachment
  cache size before old image assets are pruned, default `67108864`.
- `HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_FILES`: maximum local attachment
  cache file count before old image assets are pruned, default `240`.
- `HERMES_WASM_AGENT_ATTACHMENT_MAX_AGE_SEC`: maximum local attachment asset
  age before old image assets are pruned, default `1209600`.
- `HERMES_WASM_AGENT_CHROMIUM`: optional Chromium/Chrome binary override.
- `HERMES_WASM_AGENT_BROWSER_CDP_URL`: host Chromium DevTools endpoint, default
  `http://127.0.0.1:9233`. Set to an empty value to skip CDP and use the
  one-shot Chromium fallback.
- `HERMES_WASM_AGENT_BROWSER_TIMEOUT_SEC`: browser capture/stream timeout, default
  `20`.
- `HERMES_WASM_AGENT_BROWSER_STREAM_FPS`: max forwarded browser stream frames
  per second, default `4`.
- `HERMES_WASM_AGENT_BROWSER_STREAM_QUALITY`: CDP JPEG stream quality,
  default `62`.
- `HERMES_WASM_AGENT_BROWSER_STREAM_EVERY_NTH_FRAME`: CDP screencast source
  frame sampling, default `3`.
- `HERMES_WASM_AGENT_BROWSER_SESSION_TTL_SEC`: maximum idle age for
  request/response CDP browser targets before cleanup, default `1800`
  seconds.
- `HERMES_WASM_AGENT_BROWSER_ALLOW_PRIVATE`: set to `1` to allow localhost,
  private, link-local, or reserved browser targets. Disabled by default.
- `PYTHON`: Python executable used by startup scripts, default `python3`.

## File Layout

```text
/local/plugins/wasm-agent/
  README.md
  plugin.yaml
  public/
    index.html
    app.js
    styles.css
    manifest.webmanifest
    sw.js
  scripts/
    start_wasm_agent.sh
    stop_wasm_agent.sh
    doctor.sh
  server/
    static_server.py
  state/
    README.md
    .gitignore
    attachments/              # local image asset store; gitignored runtime state
  tests/
    wasm_agent_smoke.test.js
```

## Parity Ladder

1. Match the smallest useful Hermes browser-view surface using the current
   bridge contract: workspace chrome, health, resources, nodes, task prompt,
   task status, logs, and bridge-described node actions.
2. Move more visible state and layout decisions behind the WASM runtime
   boundary while preserving the same backend contract.
3. Prove browser output and input can enter the workspace as backend-rendered
   pixels without iframe.
4. Add a structured state/action ABI so Hermes can inspect and manipulate the
   WASM app without DOM scraping.
5. Keep validating lazy image-card modules with real attachments, then move hot
   pixel work behind WASM only after the Canvas analyzer has proven useful
   enough to optimize.
6. Add GPU-oriented surfaces only after the parity shell is stable.
7. When parity is proven, document the migration plan for placing `wasm-agent`
   above or in front of `hermes-space-ui`.
8. Use the Observation inspector as the foundation for embedded agent chat and
   suggest-only action proposals.

## Documentation Boundary

Docs must describe `wasm-agent` as a shadow parity plugin until it has verified
parity with the current Hermes Space UI workflow. Future Space OS, cloud domain,
GPU runtime, browser, or replacement claims belong in
`/local/docs/roadmap/space-os/wasm-agent-parity-spike.md` until implemented.

Any code change in this plugin must update this README or the roadmap when it
changes startup, ports, bridge endpoints, runtime state, or parity status.
