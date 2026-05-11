# WASM Agent Parity Spike

Date: 2026-05-04

## Question

Can Hermes Orchestrator build a WASM-first Hermes Agent UI that matches
the useful output of the current JavaScript workspace path before making it the
primary Space OS surface?

## Decision

Proceed with the plugin named `wasm-agent`.

The goal is not to build an arbitrary browser engine first. The goal is to
reproduce the current Hermes Agent UI output through a WASM-first PWA shell
served from a separate port, then let that plugin own the bridge/runtime path
once parity is strong enough.

## Current Scaffold

`/local/plugins/wasm-agent` now owns the shadow implementation:

- local PWA shell: `http://127.0.0.1:8877`
- wasm-agent-owned Hermes bridge: `http://127.0.0.1:8790`
- local state root: `/local/plugins/wasm-agent/state`
- startup: `/local/plugins/wasm-agent/scripts/start_wasm_agent.sh`
- verification: `/local/plugins/wasm-agent/scripts/doctor.sh`

The first scaffold includes an embedded WebAssembly core loaded by the browser,
a WASM-rendered runtime canvas, bridge health probing, node listing, task
submission, task polling, PWA manifest, and service worker.

The second browser-view pass moved the shell closer to the desired Hermes workspace from a
user viewpoint: launcher rail, visible `space-home` and `space-admin` titles,
a hardcoded Admin space, account-owned spaces, scrollable/pannable space boards
with config-controlled space density, app-layer buttons that toggle widgets,
support edit/copy-id context menus, and snap to a non-overlapping `5px` grid
while preserving pixel placement across resize, draggable/resizable widget
windows, resource monitor, topology,
UI Studio prompt surface, Drop to Copy output, inspector surfaces, recent task
list, log tailing, and bridge-described node lifecycle controls. Timeline is a
fixed space-config action instead of an app-layer icon. The old header/status
chrome, canvas label, summary panel, and dock are now removed. Topology exposes
right-click Edit/Restart/Start/Stop/Update actions per node and draggable
node-card placement, plus an Add Node action that calls the documented bridge
`POST /nodes` route.
Connected Devices is Home-only and now records the current browser as an
account device, lets the user switch the account's main device, downloads
device-sync installer manifests, and stores app/widget coordinates plus space
density in browser local storage instead of retaining another screen's
placement server-side by default.

The browser proof pass adds a Host Browser widget that asks the local
`wasm-agent` backend to use host Chromium through CDP, capture a URL, and render
the result as pixels inside the workspace. The next pass keeps that host target
alive and forwards click, type, key, and scroll input from the widget back to
CDP, returning refreshed pixels after each action. This is not arbitrary in-PWA
browser execution and does not use iframe; it is the smallest local
remote-browser-style proof. The browser's network egress is the host running
the CDP/Chromium process, not the user's PWA tab. The capture viewport now
matches the widget's browser surface so the image fills the card and click
coordinates do not need letterbox correction. Live mode keeps requesting fresh
pixels, and Back/Forward/Reload actions are forwarded to CDP. The current
preferred path is `/browser/stream`, a WebSocket that sends CDP screencast
frames into a canvas and receives input over the same connection; the older
request/response screenshot path remains as fallback. The status chip now stays
stable as `stream` or `live` instead of flickering through `screenshot` during
refreshes. Opening a second URL on an active stream now reuses the current host
browser target with a `navigate` action, and frame URL updates no longer clobber
the address field while the user is typing. The stream pauses screencast during
navigation and restarts it afterward; forwarded frames are throttled by default
to keep animated sites from driving CPU continuously. A forced snapshot after
open, navigate, and resize keeps the canvas updated even when a page does not
emit a fresh screencast frame immediately. The address bar now keeps typed
input as a draft separate from incoming stream URL updates, so a second Open or
Enter uses the user's typed domain instead of a late frame URL from the previous
site. Host Browser can be minimized, maximized, dragged, and resized in the
workspace like the other widget windows.

The embedded assistant image pass adds the first cheap-eyes harness. Browser
native decode and Canvas pixel sampling build a compact
`hermes.wasm_agent.image_card.v1` for every attached image: dimensions, payload
size, perceptual hash, palette, visual notes, and basic luminance/contrast/edge
metrics. The harness now exposes image-perception module contracts:
`image-card-core` runs as the resident Canvas pass, `barcode-reader` lazily
initializes native `BarcodeDetector` when available and caches the detector
function, `ocr` lazily tries native `TextDetector` and can fall back to a cached
Tesseract.js runtime, and CV/semantic modules are disabled placeholders until
local runtimes are bundled.
The core card now includes text-like stroke/region metrics so text-heavy photos
can be described as likely printed or label-like without inventing exact OCR.
Analyzer evidence is stored on the image card with explicit statuses so model
turns know what was checked, skipped, unsupported, or not loaded. On send, the
local backend stores compacted images under
`/local/plugins/wasm-agent/state/users/<acc_id>/attachments` and returns
same-origin `/agent/attachments/<hash>.<ext>` URLs. The model-facing action
chain now shows: store image assets, decode pixels, analyze image, build image
cards, then ask the selected node. Text-only bridge providers receive the image
cards through `attachment_manifest`; raw `image_url` parts remain opt-in.

## Why This Comes Before Browser Work

The browser feasibility spike remains true for arbitrary external sites:
PWA-only local WASM is not a credible v1 browser-engine path.

This spike is narrower and more reachable:

- copy the useful Hermes UI output first
- keep the backend bridge contract stable
- move rendering/runtime ownership toward WASM incrementally
- use GPU-oriented browser APIs where they help our own app surfaces
- define agent-readable state/action contracts after visible parity exists

## Non-Goals

- Do not reintroduce a separate legacy UI dependency for wasm-agent flows.
- Do not patch Space Agent core.
- Do not patch Hermes Agent core.
- Do not claim arbitrary website browsing inside WASM.
- Do not move cloud/PWA domain routing ahead of local parity.

## Parity Target

The first parity target is the smallest useful Hermes control surface:

- browser-view workspace chrome
- draggable/resizable widget windows with account/space-local layout persistence
  and click-to-front focus behavior
- bridge health
- host resource monitor
- live resource polling with top-down Nodes, Disk, RAM, CPU, Processes, and
  Uptime rows
- scrollable/pannable space board with per-space space density controls that
  preserve current widget dimensions
- account connected-devices widget on Home
- fleet/node list
- selected node state
- prompt submission to a node
- task status/result display
- logs for the selected node
- backend-rendered browser pixels in a draggable widget
- click/type/key/scroll forwarding to the host browser target
- websocket CDP screencast frames rendered into a canvas
- non-overlapping app-layer buttons with 5px-grid snapping and toggle-open
  behavior, widget minimize/maximize controls, and Host Browser resizing
- browser-built image cards and local attachment asset storage for embedded
  assistant turns
- bridge-described start/stop/restart/update node action controls and Add Node
- stable installable PWA shell
- visible WASM runtime indicator

After this works, expand parity toward logs, node actions, activity timelines,
Guard state, and the Hermes workspace output now handled by wasm-agent.

## Runtime Contract Direction

As parity improves, more behavior should move behind explicit contracts:

- render model: layout/state data exposed by WASM rather than DOM-only code
- action ABI: structured commands Hermes can call into the runtime
- observation ABI: structured state snapshots Hermes can read
- persistence ABI: local durable state with export/import rules
- graphics ABI: canvas/WebGPU/WebGL surfaces for high-performance UI regions

Do not hide backend orchestration behind ad hoc browser globals. The Hermes
bridge remains the boundary until a documented replacement exists.

## Stop/Go Criteria

Proceed while the wasm-agent UI and bridge stay directly runnable:

- wasm-agent bridge stays available at `http://127.0.0.1:8790`
- WASM Agent PWA stays available at `http://127.0.0.1:8877`
- docs identify which surfaces are parity, partial, or future work

Stop and update this file if the WASM shell requires backend or Space Agent
changes before it can match the first parity target.

## Next Actions

1. Start both surfaces and compare them side by side.
2. Keep evolving the WASM harness branch: embedded assistant context,
   image-card perception, Timeline checkpoints, and Host Browser stream health
   before returning to broad browser-engine questions.
3. Validate the lazy image-card analyzer modules with real attachments, then
   move hot pixel loops into small WASM modules only after the Canvas analyzer
   proves useful enough to optimize.
4. Define the first structured WASM state/action ABI after the UI can render the
   basic fleet/task flow.
5. Revisit remote browser work only after the WASM UI shell direction is proven
   or explicitly rejected.
