# wasm-agent

`wasm-agent` is the shadow WASM-first UI plugin for Hermes Orchestrator.

It exists so the team can build the Hermes Agent UI/runtime shell without
depending on the old Space Agent integration. Its first milestone is visual and
behavioral parity with the useful Hermes UI surfaces; after parity, this plugin
can become the runtime substrate for Space OS work that needs GPU-oriented
rendering, agent-readable state, and a cleaner app shell.

## Current Behavior

- Serves a local installable PWA shell on `http://127.0.0.1:8877`.
- Owns the local Hermes bridge/API contract as the backend boundary, defaulting
  to `http://127.0.0.1:8790`.
- Keeps chat, workspace layout, provider/model preferences, and WIS artifacts
  client-first by default. The Python server is used only for centralized
  account auth, presence/relay, lightweight sync events, optional backup, and
  explicit fleet metadata/provisioning handshakes.
- Supports an open-core cloud state boundary: local development uses
  `state/`, while `HERMES_WASM_AGENT_DEPLOYMENT_MODE=cloud` requires a private
  `HERMES_WASM_AGENT_CLOUD_STATE_ROOT` outside this public repo.
- Loads an embedded WebAssembly core in the browser and uses it as the first
  rendering/runtime handshake for the parity shell.
- Does not start, stop, copy, or patch Space Agent.

## Durable Next Step

This section is the cross-compaction handoff for active `wasm-agent` work. When
the next action changes, update this before ending the turn.

Current next action: reload the real authenticated co-control clients and
confirm the signed-in clients open `/remote-control/live` and Victor Genaro's
interface moves past the controller `Requesting remote viewport` state after the
v128 service worker activates: first by receiving a
compact bootstrap preview or fallback/status event if the relay rejects a full
frame, then by using the receiving-side `Share pixels` button for any
auto-granted co-control session and confirming the controller-side frame status
reads `exact pixels`, and confirm the controller viewport closes when the
receiver presses Stop or ends browser screen sharing, including the duplicate
accepted-grant case where the receiving banner previously stayed on
`Co-controlling with ...` / `Exact pixel viewport sharing active`; also confirm the
controller-side viewport expand button fills `100vw` by `100vh`, verify the
received frame status shows a high-resolution frame up to `1920x1080`, confirm
tap/click actions reach launcher buttons such as `space-home`, `wasm-agent-chat`,
and in-surface widget buttons through the live remote-control channel without
waiting for the social poll, and confirm dragging the remote canvas pans it
through pointer down/move/up, then confirm scrolling the empty remote canvas
changes space distance instead of native-scrolling the space viewport;
then reload two real clients in the same shared space and confirm moving,
pressing, and clicking over the canvas shows each peer's labeled pointer and
click pulse in the other client without opening chat; then reload the real
authenticated Zangao client and confirm `/spaces` no longer returns or renders
`space-home`/`space-admin` as account-owned user spaces; then reload the real
authenticated Asolaria clients and confirm the Asolaria title row shows the shared voice control after
`HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1` and the Asolaria `voice-room`
capability are present, and resume the prior CAM 1 middle-timeline click and
Live return browser verification so the real client matches the headless
acceptance snapshot: `mode: recorded`, `playback_mode: recorded`,
`playback_rate: 1`, `blink_events: 0`, `bad_samples: 0`, and clean return to
live on the Live button.
Current evidence: Remote-control viewport frames now strip URL-backed CSS and
inline snapshot resources before SVG export, and SVG export failures fall back
to a canvas-native DOM renderer that avoids drawing untrusted image resources;
capture errors are relayed to the controller as statused frame events instead
of leaving the preview at its first empty state, and payload-too-large relay
failures lower the client frame budget to a compact bootstrap preview before
retrying. The controller also probes the latest `remote-control-frame` and
`remote-control-stop` rows for the active conversation so a stale global sync
cursor cannot leave it pinned at the empty preview or waiting after the receiver
has closed sharing. Stop events now carry the original request/device context,
and the receiver retires matching sibling grants from the same controller and
conversation so duplicate accepted responses cannot leave a stale co-control
banner after one grant is stopped. The receiving side now remembers handled
remote-control request ids so duplicate sync processing cannot mint sibling
grants, and controller responses/frames carry enough request context for the
viewer to upgrade to the newest accepted grant instead of rejecting all incoming
pixels as a wrong-token stream. Controller viewport clicks now compensate for `object-fit:
contain` letterboxing, carry viewport dimensions with actions, and the receiver
targets consented screen surfaces outside `#app` such as `wasm-agent-chat` while
still blocking secret fields and remote-control chrome; controller viewport taps
now synthesize an explicit remote `click` after pointer capture, and the viewed
browser also converts pointer-only down/up taps into click activation so stale
viewer clients can still press login, space, and launcher buttons instead of
only sending pointer down/up. A headless Chromium
repro with external avatar CSS returned an
exportable `image/webp` frame. The controller viewport now has an expand/restore
toggle that persists across frame refreshes and switches the preview panel to
`100vw` by `100vh`; the frame encoder now captures at source viewport size up
to full HD, and the server gives remote-control frame events a larger payload
budget while pruning old frame events. Visible remote-control accepts now try
browser display capture first so icons/images/video are sent as exact rendered
pixels; auto-granted sessions expose a receiving-side `Share pixels` button for
the required browser gesture, frame export can spend a larger 1.5 MiB client
budget inside a 3 MiB server payload limit, active remote-control sessions poll
sync events every 180 ms, the exact-pixel capture stream emits a normal
remote-control stop when the browser sharing control ends it, and the controller
viewport now streams pointer down/move/up actions so the remote canvas can be
dragged. Remote scroll actions over the unblocked space canvas now reuse the
anchored `setCanvasDistanceAround` zoom path with a `remote-wheel` origin before
falling back to native scroll for scrollable widgets and panels. If the user/browser
denies exact capture, the sanitized DOM snapshot fallback remains available.
Signed-in clients now also keep an authenticated same-origin `/remote-control/live`
WebSocket open. Remote-control appends use that live channel first, still persist
through `sync_event_tb`, and fall back to HTTP `/sync/events` with the same
client event id if the socket is not ready; HTTP sync appends now hand live
broadcast delivery to a background thread after the durable row is written, so a
stale live socket cannot make the sender see `Control request failed`. Connected
live clients still receive the first request, accepted grant, action, and stop
events without waiting for the social or fast poll; the client-first cloud
regression now opens two signed local `/remote-control/live` WebSocket clients
and verifies request broadcast plus ephemeral frame relay without durable frame
rows. Exact-pixel viewport frames now use an ephemeral latest-frame WebSocket
message that bypasses durable
`sync_event_tb` writes on the hot path, sends a higher-quality live frame budget
about every 260 ms while display capture is active, writes only periodic durable
keyframes for fallback/backfill, drops/coalesces stale frame paints on the
controller so old pixels cannot repaint behind current actions, reuses the pixel
capture canvas, encodes exact-pixel frames asynchronously where the browser
supports it, and keeps the controller preview DOM stable across frame refreshes.
Shared spaces now publish lightweight `space-pointer` room events while the
canvas is active, keep a same-origin `/spaces/room/live` WebSocket open for the
active shared space, and retain the room poll as fallback. Connected clients see
peer cursor labels and click pulses in logical canvas coordinates without
waiting for the next room poll, while duplicate durable pointer events are
deduped by client event id, fast pointer-up taps are promoted to explicit
`click` pulses, and each pulse carries a fresh pulse id so repeated quick
clicks/touches restart a larger wave instead of being swallowed by the previous
animation. Pointer motion now streams through a frame-rate, coalesced live-only
path at the cursor cadence limit, writes only periodic durable keyframes for
room-poll fallback, fills longer cursor jumps with short capped fading trace
segments, and softly follows the latest peer cursor when it leaves the
comfortable visible viewport. The follow loop is clamped per frame and pauses
while the local user is actively panning, zooming, or holding a pointer down, so
different zoom/scroll positions still line up without sticky jumps.
Zangao's account state had stale
`spaces/space-home/wis` and `spaces/space-admin/wis` directories; the server now
requires real `space.json` metadata before listing user spaces, reserves
`space-home` and `space-admin` as display-label ids, and canonicalizes WIS
patches using those labels back to `home` and `admin`. The portable focused-camera
artifact factory, slot/focus helpers, push-camera config shape, controller contract, push endpoint
URL generation, default/normalized push config, stream-quality ids, frame
polling cadence, pending timeline seeks, timeline load TTL, frame labels, and
range formatting now live in `public/modules/wis/artifacts/camera.js`; the WIS
engine and app shell import that boundary; and
`window.wasmAgentWis.createCameraArtifact()` exposes the shareable factory. The
active WIS camera artifact is a single-camera `CAM 1`
artifact, `cam-1` is configured as `rtmp-push-ingest`, stale browser-local
snapshot/RTSP credentials no longer mask the artifact RTMP push source, and the
WIS camera now uses retained `/camera/push-frame` polling for the live image,
minimal camera header controls for zoom/snapshot/audio/quality, and a full-width
footer timeline that defaults to the last 10 minutes with a detected
recorded-range mode. The footer is scoped to the active widget and uses robust
pointer capture for scrubbing through the shared camera artifact controller;
`app.js` now only renders the scrubber and attaches it as the controller's
`timelineElement`. Timeline clicks from the last-10-min Live rail now promote the
stream into a recorded/seeking owner state instead of being ignored or leaving
the mode badge live; the app cancels live timers, fences stale live image writes,
sets the playback anchor from the clicked timestamp, and starts a single
generation-owned recorded playback session. A first click while the timeline
range is still loading is remembered and applied as soon as retained frames
arrive. Scrubber clicks no longer trigger a parent footer reload that can
rebuild the control before the seek commits. Controller-owned recorded timeline
seeks now hand the real loaded segment back to the playback controller while the
visible media surface keeps the last good frame frozen until the latest recorded
generation decodes a replacement from `/camera/push-playback`; the archive-frame
URL remains a fallback if the playback stream cannot open. Timeline reads use
the JSON `POST /camera/push-timeline`
path so stale service workers cannot return the app shell HTML in place of
retained-frame metadata, stale in-flight timeline loads are timestamped so the
client can retry instead of leaving the scrubber in a permanent loading state,
and a client-side watchdog actively clears and retries a stalled timeline load
without waiting for a later render or interaction. The server accepts
app-route-prefixed camera push paths from shared-space pages. The recorded
playback image lifecycle, including
the last-good-frame placeholder, fallback archive-frame image, and
`/camera/push-playback` stream handoff, now lives in
`public/modules/wis/artifacts/camera.js`; `app.js` only assembles host URLs and
passes shell callbacks into the camera artifact helper. Recorded timeline seeks
reuse the current media DOM node when possible and seed rebuilt surfaces from
`wisCameraLastGoodFrames`, so seeking and rebuffering overlay status text on top
of the frozen frame instead of clearing, hiding, or remounting a black media
pane. Recorded timeline seeks tag DOM playback segments as media-clocked, so the
camera artifact controller no longer starts a synthetic RAF image-render loop
for playback. It keeps the
desired timeline clock separate from the last displayed frame timestamp, runs a
timeline-only clock loop after the first recorded frame, and treats
`/camera/push-playback` as an imperfect DVR evidence stream: bad timestamps are
normalized, stale queued frames are dropped, burst frames catch up to the clock,
slow/starved streams show catching-up or rebuffering state, and repeated packet
stalls restart from the current desired clock before settling into a stalled/gap
state. Recorded playback also keeps one active stream reader/scheduler per
stream generation, treats repeat same-frame renders as no-ops, diffs playback
status/timeline updates before touching DOM or WIS patch state, and emits one
compact `camera.perf.sample` per second while verbose per-frame camera logging is
off by default. A headless Chromium retained-frame harness for CAM 1 now shows
one stable image node, one active playback loop/reader, zero steady DOM
replacements, and low-cadence source swaps, while the WIS engine regression
covers six rapid seeks settling to the latest generation and live return
clearing playback loops/readers. The DVR
outbound RTMP publisher is active at
`rtmp://147.15.64.233:1935/live/livestream0` after switching Stream Principal
from H.265 to H.264/H.264H; the last checked CAM 1 frames were live
`1280x720` JPEGs. The focused camera WIS chrome hides the sandbox/location
surface, removes the old in-surface action row, keeps a single-row compact
layout, and sizes the widget from the camera frame aspect ratio. This
wasm-agent host remains outside the DVR LAN (`10.0.0.167/24` versus DVR
`192.168.1.78`), so the active path stays DVR-outbound RTMP push instead of
server-side RTSP pull. The MediaMTX RTMP server plus local frame extractor still
need folding into the plugin-owned start/doctor path after the camera controller
boundary is cleaner.

## Architecture Vision

`wasm-agent` should grow as a modular runtime rather than a single tangled app.
The browser shell is the shared mainframe: it owns boot, auth, routing, layout
hydration, the module registry, and stable bridge contracts. Features should be
described as modules wherever possible so all wasm-agent instances can share
core evolution without forcing every instance into the same workspace shape.

Core modules are the non-removable platform layer. Today that includes
`spaces`, `devices`, `artifacts`, `config`, `module-manager`, and
`client-state`. They define how users enter, inspect, configure, sync, back up,
and extend the workspace. Core modules may be visible in the module inventory,
but they should not be user-disabled.

Modules are hierarchical. The `spaces` module owns Home, Admin, and user space
identity. A space can expose child modules as pages, actions, apps, widgets,
analyzers, or widget-internal capabilities. Home presents account-level core
modules as page actions, while Admin maps the built-in working app/widget
modules onto the canvas. User-created spaces start empty and receive apps only
through an explicit later mapping/porting flow. Plugins should extend this tree
through module descriptors, space mappings, local state, and runtime data
instead of patching unrelated core code. That keeps the shared mainframe small
and performance-conscious while leaving each wasm-agent instance free to evolve
its own module tree.

The current app is an early browser-view parity surface. It now presents a workspace shell with a left launcher
rail by default, a visible `space-home` Home space, a hardcoded `space-admin` Admin space
with a crown icon, and account-owned user spaces. The old header/status chrome,
canvas label, summary panel, and dock have been removed from the shell.
`space-home` and `space-admin` are display labels only; the server reserves
those label ids so WIS patches and sync payloads cannot recreate them as
account-owned user spaces. Each
working space now has two visual layers: an app layer with draggable app
buttons, and a widget layer where opened widgets sit above those apps as
draggable, resizable windows with minimize and maximize controls. Apps are
account/user entities mapped into spaces: Home exposes core modules in its
command strip, Admin maps built-in working apps, and user-created spaces stay
empty until apps are explicitly mapped or ported there. Widgets remain hidden
unless their app is mapped into the active space or is later ported into that
space.
App buttons snap to a non-overlapping `5px`
app-layer grid on drop and keep logical pixel placement stable across viewport
resize, while widgets store logical pixel geometry. A newly created space stores
its current viewport as an absolute Space area, then Space config can resize
that per-space area up to `2000 x 2000px` without resizing widgets; shared
spaces carry the same configured area across devices. Changing Space distance scales app icons and
opened widgets visually around those logical positions. On desktop, wheeling over
the empty canvas adjusts Space distance around the cursor point instead of
scrolling the hidden board. Wheel events that start inside opened widgets stay
inside that widget, so inner widget scroll areas can move without panning the
space canvas. Widget bodies reset the canvas grab cursor; only widget headers
and resize handles advertise drag affordances. On mobile, a two-finger pinch adjusts Space distance
around the midpoint between the touches. While wheel or pinch zooming, the
top-right config button fades away and its anchor shows the current zoom value
above the minimap if the minimap is also visible. Pinch updates use a
lightweight visual pass during the gesture and defer the full widget layout/save
pass until the gesture settles.
Clicking an already-open app icon minimizes its widget again, and app
icons and widgets remain draggable on mobile. A small organize button beside
each canvas title rewrites the active space's app icon positions into a tidy
grid starting flush with the current viewport's left canvas edge and below the
title controls. The title itself shares the config button's top edge and lines
up with the app icon's inner-left edge, while the organize and config controls
share the same `34px` square icon-button size. It adds no gaps between icon
boxes; if the apps do not all fit, the grid continues past the viewport in
organized rows. The organizer wraps inside the current area-sized logical
canvas by measuring the packed block before it writes positions, and does not
trigger a canvas-area recalculation. Organized icon positions stay compact until the
user manually drags an app again, and the manual app/widget bounds use the same
flush canvas edge with no hidden inset. Manual app collision checks
also allow icons to sit directly side by side, matching the organizer, and a
plain tap-to-open does not rewrite icon placement. Organized slots keep the
actual app-button pixel width instead of being rounded away from a valid slot by
the visual grid. Empty canvas panning uses the
same one-finger/click-drag gesture on mobile and desktop, but only moves when
space area, space distance, or content makes the board larger than the visible viewport. On
release, recent drag speed launches a short inertial glide so a fast spin keeps
the viewport moving smoothly across the board. The native workspace scrollbars
are hidden; subtle edge glows show when more board content exists to the left,
right, top, or bottom. A temporary minimap appears while direct panning or
inertial motion is active so the user can see the viewport position against the
total board with app and widget miniatures; it takes the top-right config
anchor, stays below open widgets, fades the config button away until viewport
motion stops, keeps the viewport border visible at every board edge, clips
miniatures to the board bounds, and draws open widget footprints with
minimap-namespaced classes so global widget CSS cannot impose real panel
minimum sizes. Opened apps are represented by their widget footprint instead of
also drawing a duplicate app-icon marker; minimized app markers are positioned
from the painted app-icon rectangle after minimized state is confirmed from
layout. Its viewport marker and entity markers both use the scroll container's
logical coordinate space, so space area/distance changes, the launcher, and the
painted board rectangle cannot skew the minimap projection. A fully visible icon
stays inside the viewport marker at every board edge.
On mobile and tablet widths, Home/Admin/User space frames collapse to one actual
canvas row when the side panel is hidden, so minimap viewport height is the
visible canvas height rather than an old inspector-row layout. The minimap uses
the area/distance-sized canvas dimensions, not widget-inflated scroll dimensions, and
open widgets are rerendered back inside that canvas if a saved/default position
would overflow it, using the canvas origin as the initial recovery point rather
than padding away from the edge. On mobile browsers, the shell height is synced
from `window.visualViewport.height` and the outer canvas wrapper reserves the
measured visual-viewport bottom inset, so Android navigation bars or similar
device chrome do not sit on top of draggable widgets. Widget drag and resize
bounds still use the area/distance-sized canvas on mobile and desktop, while the
minimap also reads the board dimensions rather than the padded wrapper.
The app marker is a small symbolic dot, but its size is capped from the icon's
projected footprint and clamped inside the projected viewport whenever the
painted icon is fully visible.
It stays hidden when the board is not larger than the
visible viewport and layers above Home action buttons while active. Per-space
layout is sanitized against the active app mapping so Home-only state cannot
leak into user-created spaces. If a minimized widget opens
outside the visible canvas viewport, it is
moved to the canvas initial point: the top-left beginning of the board. Opened
widgets stay inside the area-sized canvas on mobile while horizontal resizing
can grow past the visible device screen and use the canvas scroll/pan surface.
Height is still constrained to the visible canvas so window controls remain
reachable. Right-clicking an app
icon or widget header, or long-pressing it on mobile, opens an app menu with
Edit and Copy app id. Edit persists title, icon text/image, and min/max
dimensions in the current browser's local device layout. Widget layout is
stored in browser local storage by default; the server does not retain it unless
a future premium sync/backup path is explicitly enabled.
The shareability and marketplace direction is tracked in
[`ARTIFACTS.md`](./ARTIFACTS.md): spaces, apps/widgets, and widget-inner
entities become portable `wasm-artifacts`, while device layout remains local.

Admin is the standard operational space for `wasm-agent`, not a custom user
space. `/admin` opens the app-icon workspace for the resource monitor,
topology, Host Browser, Drop to Copy, workspace studio, Observation inspector,
and module-management surfaces using the documented wasm-agent bridge endpoints.
Timeline is not an app icon; it is opened from the fixed
space config button for the current space. Legacy `/space` links land on the
same Admin workspace. Topology reads live nodes through the same-origin
`/bridge/nodes` proxy and exposes only start/stop/restart/update actions per
node; right-clicking a node in the topology widget opens Edit, Restart, Start,
Stop, and Update actions for that node. The Edit form can persist a local model
override as provider/name. Topology node cards can also be dragged inside the
topology widget and persist their positions with the browser-local space
layout.
The Add Node button creates a bridge node profile through `POST /nodes`. The
Resources Monitor polls live bridge resource data while it is open, defaults to
content-fitting height, and renders one metric per row in this order: Nodes,
Disk, RAM, CPU, Processes, Uptime. RAM and Disk use compact `usedGB/totalGB`
values.

Home also has a Connected Devices core module. It is opened from the Home
core-module strip as a page rather than from the app layer. Opening it lists devices recently seen for the
signed-in account through `/account/devices`; the current browser is recorded
from the authenticated request and marked in the widget, and each row shows a
compact operating-system icon, a main-device switch action, and a Sync action.
The backend records one main device for the account; if that main device is
offline, artifact-evolution actions such as creating spaces and importing
storage point the user back to Connected Devices so they can switch main devices
quickly. Sync currently downloads a device-specific installer manifest with
planned tunnel and state-sync capabilities; it does not claim a tunnel is live
yet. On mobile, Home config can switch the launcher from the default left rail
to a top bar so the Home button and account control stay pinned while the space
list scrolls between them.

Home also exposes a Fleet core module for account-owned agent brain metadata.
Opening it reads `/fleet`, shows the account's reserved Hermes node records, and
can explicitly reserve a main node through `/fleet/nodes/ensure-main`. That
reservation does not provision a backend worker by itself; it stores ownership
metadata so premium/heavy provisioning can stay an intentional later action.
Model/provider choices in the embedded chat remain browser-local unless the
user explicitly uses the backend model setup flow for a selected Hermes node.
Embedded chat readiness is now explicit through `/agent/readiness`: the drawer
shows Agent ready, Agent backend unavailable, sandbox lifecycle labels such as
Provisioning sandbox, Sandbox ready, or Provisioning failed, and
WASM runtime blocked/unavailable before a turn becomes an opaque bridge error.
For admin-selected nodes, readiness checks both the wasm-agent bridge and the
selected node card so a stopped orchestrator does not appear ready just because
the bridge process is alive. A browser mini-WASM failure remains a local runtime
warning, but it no longer masks a live agent backend in the chat status chip.
Standard-user chat resolves the internal account-owned agent alias to the
user's deterministic main node and preflights the same readiness helper before
bridge dispatch. If the main agent is missing, the drawer offers either an explicit
OpenAI-compatible node profile stored in client state, or Flux-credit
provisioning of one bounded main node. The provider path is standard-user
node mode: saved provider-backed nodes appear as selectable chat nodes, the node
dropdown can open `> New...` or `> Edit...`, and a main-chat send is blocked
with the setup balloon until the user has selected a configured node. The same
normalized provider, generated provider endpoint, model, API key, optional node
name, optional agent harness, provider metadata, and transport plan feeds the
node form, readiness chip, connectivity probe, and final chat dispatch. Readiness no longer becomes
"ready" just because the three fields exist; `providerTransportPlan()` first chooses browser-direct or
backend-proxy. Known hosted providers such as OpenRouter/OpenAI-compatible
cloud endpoints, plus compact/mobile public endpoints, go through
`/agent/provider/chat` first so mobile turns do not spend a failed browser CORS
probe before answering. Local, private, single-label, or explicitly
browser-direct endpoints still probe the browser first. If that browser request
is blocked by CORS, the origin is remembered for the session and wasm-agent
falls back to `/agent/provider/chat`, where the backend makes the same
non-streaming OpenAI-compatible request without logging the key. OpenRouter image
turns use the same proxy path when CORS requires it, preserving `image_url`
content parts instead of flattening them into text.
Admin/orchestrator chat ignores standard-user provider
state so a saved mobile key cannot hijack Hermes-orchestrator turns. The
node form keeps saved provider-backed nodes as a multi-node list rather than a
single replace-in-place provider slot. Clean "new node" drafts do not overwrite
existing OpenRouter/OpenCode/etc. nodes, saved API keys are masked on mobile, and
the form asks for the node Name before the required Provider dropdown. OpenRouter and OpenCode-Go are
the two exposed providers today; selecting one lazily loads the bundled provider
model snapshot without blocking the auth shell, then refreshes it through
`/agent/provider/models` when the live provider API is reachable. The model
field uses a form-associated `s-select` web component whose dropdown keeps
search sticky at the top and shows both display names and exact model ids. The
dropdown uses the browser top layer when available, opens toward the side of the
viewport with more room, and clamps its width and height to the viewport so
scrollable setup panels and narrow mobile screens do not clip the menu. Large
provider catalogs such as OpenRouter can be filtered before selecting a model.
All shell select controls now use the same `s-select` component, but the
in-menu search only appears for large catalogs or explicitly searchable selects.
The component keeps a `5px` horizontal trigger inset so the selected value and
chevron breathe together. Its dropdown listbox has no outer padding, selected
options carry the full option highlight, and hover/keyboard-active options use a
30% strength version of that highlight unless they are already selected.
The app generates the OpenAI-compatible endpoint URL internally.
Existing saved custom model ids are preserved as dropdown options when editing.
The visible
chat target selector is now the single provider/agent selector: with no
configured target it lists `None` and `> New...`; once provider-backed nodes or
agent harnesses exist it lists real chat targets plus `> Edit...`. Saved model
overrides stay provider/model metadata for the model picker and are not rendered
as editable fleet nodes. The edit path opens the centered `nodesPanel`, which
lists configured nodes and can use, edit, add, or delete saved node entries. Its
`nodeForm` can create a direct browser-provider node, or its optional Agent
harness subform can create a Hermes agent through `Wasm-Agent-Cloud based (10◇)`
infra or a Private bridge URL. Harness Name, Agent, and Infrastructure are
required when enabled; Hermes is the only available agent today, while OpenClaw,
KiloCode, Claude Code, and Pi are listed as unavailable. Existing saved bridge
URLs are still treated as the user's private agent bridge, and the
submit button says `Create node` only for new drafts and `Save configuration`
for existing node/harness edits. The Fleet modal separates user agents from the
deterministic system node metadata returned as `system_nodes`; the normal user
agent list shows real harnesses such as `Test1`, while provider/model choices
are never inserted into the fleet table.
Wasm-Agent-Cloud path uses orchestrator provisioning for the authenticated user's
deterministic main Hermes sandbox at the 10◇ per-harness Flux cost. That cloud
harness path still requires Provider, model, and API key because the spawned
Hermes sandbox receives the generated endpoint plus model/provider values as its runtime
configuration. Authenticated boot now loads `/fleet` before readiness checks so
account fleet nodes are included in `agentNodeSelect`, and ready cloud harnesses
appear as `agent:<Harness Name>` targets wired to their actual Hermes `node_id`.
The selector preserves node metadata in the dropdown, so the backing node such
as `uckk73p34yrk-main` is visible under the friendly target label; a matching
browser-local provider entry is hidden so the paid harness remains the canonical
chat target, and the default `My agent` alias is suppressed once a concrete
fleet node exists. Bridge-created cloud harness nodes enable the node-local
Hermes API server (`API_SERVER_ENABLED`, host, port, model, and key in the node
env), and the bridge resolves container-local API hosts through the node's Docker
address so embedded chat can reach `/v1/runs` instead of failing with an
unconfigured API server. Generated node env files are rendered as Docker
`--env-file` values without outer JSON quotes so provider keys enter the
container as valid bearer tokens. Direct provider node creation and Wasm-Agent-Cloud harness
creation both probe the draft provider config first; the form only closes after
the provider is reachable and, for harnesses, after provisioning is ready. Cloud
harness and main-node creation use a longer browser wait window plus a late-success
recovery pass: if the bridge times out but the deterministic sandbox comes up
immediately after, wasm-agent keeps the Flux debit, marks the harness/provision
ready, and records the bridge result as a recovered node-create. If the
authenticated user's deterministic sandbox is already live, harness creation
binds to that sandbox instead of sending a duplicate node-create request. A live
deterministic sandbox without a paid main provision or ready paid harness is
reported as `sandbox_billing_incomplete` and remains unavailable to chat.
Hermes nodes still keep per-node model overrides through the
backend setup flow. Embedded backend chat sends a sanitized active node config
with each run, including node id, configured name, type, instruction source, and
provider/model source; the backend injects the configured name/instructions into
the system prompt and echoes the same config in diagnostics/action trace without
replaying secret values. Flux credits are an append-only integer ledger exposed by
`/account/credits`; admins can grant credits through
`POST /admin/users/{user_id}/credits/grant`, and users can spend the fixed
DeepSeek v4 Flash profile through `/fleet/nodes/provision-main`. The current
Flux balance is shown in the account popover as `<balance>◇ Flux`, and the agent
setup path warns when the balance is below the provisioning cost. Paid provisioning is
idempotent around an already verified main node and always uses the
authenticated user's deterministic node id.

The embedded chat drawer now has a People toggle beside the `Chat` title.
People reads `/account/friends`, combines it with current shared-space members
from `/spaces/room`, and can send friend requests by account id or email.
Pending inbound and outbound requests update through a bounded social sync
poll, and the UI supports accept, decline, cancel, and remove-friend actions.
Accepted friends open a direct chat session in the same drawer with a main-chat
back button, unread indicators, calm toast/ring feedback, emoji insertion,
built-in text stickers, and emoji reactions. Direct chat messages, stickers,
and reactions are client-first and mirrored as bounded `/sync/events` rows for
the accepted friendship conversation; attachments remain local metadata for
this foundation pass. Joined shared spaces also show a Shared chat row in the
People view; opening it creates a group chat session that sends text messages
through `/sync/events?shared_space_id=...`, polls by cursor while the space is
active, and uses the same unread/toast cache path. The browser caches friends,
pending requests, recent direct and shared-space conversations, unread counts,
cursors, and the last 500 messages per conversation in IndexedDB with an
in-memory fallback.

The storage card also exposes encrypted browser-local client-state
export/import. These snapshots cover the IndexedDB-first client stores
(`people`, conversations/messages, brains, sync cursors, and artifacts), use a
passphrase-derived AES-GCM key in the browser, and do not send the passphrase or
snapshot contents to the wasm-agent backend.

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
The widget includes Back, Forward, Reload, minimize, maximize, drag, and resize
controls; maximize becomes a fixed fullscreen layer at `100vw` by the visible
viewport height with no canvas padding, above launcher/app chrome and below the
embedded assistant overlay, and resize remains available on mobile through the corner grip. Clicking,
focusing, or opening a widget brings it above overlapping widgets deliberately.
Submitting another URL while the stream is open navigates
the current host browser target instead of tearing down the stream, and incoming
frame URL updates do not overwrite the address field while the user is editing
it. Stream navigation pauses screencast frames during the page change and
restarts them afterward. The backend also throttles the CDP screencast before
forwarding frames to the PWA so animated pages do not decode every available
browser frame. A snapshot frame is forced after open, navigate, and resize so
pages that do not immediately emit a fresh screencast frame still update the
canvas. The URL bar keeps an edit draft separate from stream URL updates, so
clicking Open or pressing Enter after typing a second domain uses the typed
value even if the previous page is still emitting frames.

The Artifacts widget is powered by WIS, the first client-only browser-substrate slice. It is not a
webview and does not use an iframe. It renders a local `wis://` document model
through wasm-agent itself, keeps DOM-like tree/state, navigation, input events,
rendered nodes, and sandbox permissions in `public/modules/wis/`, and runs a
small embedded `hermes.wasm_agent.wis.wasm_engine.v1` microkernel for
deterministic artifact metrics, layout planning, and media capability planning.
It exposes structured automation through
`window.wasmAgentWis.inspect()`, `window.wasmAgentWis.act(...)`, and
`window.wasmAgentWis.exportSpace()`. The bundled example artifact-space is a
counter/task app that can be clicked, edited, inspected, and exported as
`hermes.wasm_agent.wis.space.v1` without calling the bridge, Host Browser, or
any new backend endpoint.
The widget chrome uses the loaded artifact title, so a camera artifact can read
`CAM 1` while the underlying generic runtime remains WIS. The portable
focused-camera artifact factory, slot/focus helpers, push-camera config shape,
and camera controller contract live in `public/modules/wis/artifacts/camera.js`;
`app.js` imports that module for host rendering and exposes the factory through
`window.wasmAgentWis.createCameraArtifact()`.
Camera-style WIS artifacts are browser-first: a slot can request the current
device camera with `navigator.mediaDevices.getUserMedia`, poll a vendor HTTP
JPEG snapshot endpoint, or render a browser-playable HTTP(S)
MJPEG/image/HLS/video URL directly in the artifact.
The current camera direction is one WIS artifact per physical camera. A focused
camera artifact carries one `webcam_placeholder`, one `state.cameras` entry, and
`state.camera_focus`; the WIS widget hides the inspector side panel for that
artifact, hides the location/status chrome, and gives the camera frame the full
widget width in a single shell row, including compact/narrow layouts. The
focused widget height follows the camera frame aspect ratio,
while zoom, snapshot copy, audio state/toggle, and principal/extra quality live
in the camera header instead of in-surface Open/Capture/Snapshot/Config controls.
RTMP-push camera artifacts render the
live view by preloading `/camera/push-frame` JPEGs and swapping only after the
next frame loads, so transient delivery gaps retain the last good frame instead
of blanking the camera. The footer timeline defaults to the detected retained
frames from the last 10 minutes; its Recorded mode asks `/camera/push-timeline`
for the available retained range instead of assuming a fixed duration. Selecting
a point shows that archived JPEG, and Live 10m returns to the retained live
frame loop. The footer requests timeline data as it renders and again on direct
footer interaction, so a first scrub/click does not depend on a separate widget
focus event. It is visible only while the WIS camera widget is active, and its
scrubber keeps pointer tracking through drag/release transitions so selecting an
earlier retained frame commits reliably without a parent footer reload rebuilding
the scrubber during the click. If a user clicks before the footer has
loaded its frame list, the click position is kept and applied after the timeline
response arrives. The backend marks the feed `stale` when the latest frame is
older than the freshness window.
Artifact-level RTMP push sources take precedence over stale browser-local camera
credentials so a shared/outbound DVR feed can recover even when an older client
had tried snapshot or RTSP settings locally.
For Intelbras DVRs that can initiate outbound RTMP, a slot can also use
`intelbras push`: wasm-agent starts an ffmpeg-backed RTMP listener, returns a
per-stream `rtmp://<host>:<port>/live/<stream-key>` URL for the DVR's custom
RTMP/live-stream setting, and exposes the latest received frame through the
same-origin `/camera/push-frame?stream_id=<id>` endpoint. This uses the DVR as
the always-on bridge, so it does not require the wasm-agent server to reach the
DVR's private `192.168.x.x` LAN address.
When the DVR portal itself works but the CGI stream cannot be embedded, the slot
can use `navigator.mediaDevices.getDisplayMedia` as an explicit user-approved
tab/window capture. The user opens the Intelbras portal, chooses that tab/window
in the browser picker, and the captured pixels render inside the artifact
without a backend relay or cross-origin session scraping. The Intelbras helper
also accepts `intelbras capture 192.168.1.78`, which opens the DVR portal and
starts the browser capture picker as the first-class setup path.
Camera URLs and device streams stay client-local by default under
`wasmAgent.wisCameraConfigs.v1`; the artifact stores only redacted slot metadata
for inspection. RTSP URLs are classified as `rtsp-relay-required` by the WIS
runtime because browsers cannot open RTSP sockets directly, even when WASM is
available. Entering `intelbras` in a camera slot now opens the credentials-first
DVR/NVR profile: the browser asks for host, username, password, channel, and
stream subtype once, keeps those secrets only in
`wasmAgent.wisCameraConfigs.v1`, then defaults to the true Intelbras RTSP
`/cam/realmonitor` feed. The browser creates a short-lived
`/camera/rtsp-frame` polling. New Intelbras RTSP configs default to subtype `0`
(main stream), credential setup asks for the RTSP/tunnel port reachable from
the wasm-agent server, and the backend preflights that RTSP TCP port before
starting `ffmpeg`. The ffmpeg RTSP input uses TCP transport plus the RTSP
demuxer's socket timeout option, so unsupported timeout flags fail tests instead
of being reported as DVR frame timeouts. The recovery panel can also run
`/camera/diagnostics`, a short server-side TCP check for the configured
RTSP/HTTP/HTTPS DVR targets plus a route/source hint for private DVR addresses,
so the operator can verify whether the wasm-agent host can reach the DVR/tunnel
before retrying decode and can distinguish a different private LAN/VPN route
from bad credentials. Diagnostics accept tunnel-style `host:port` values and
split them into a real host plus RTSP port so recovery checks do not add a
bogus hostname failure. The RTSP frame and continuous stream preflight errors
use the same route hint, so the WIS camera card can show the exact
network/tunnel blocker without requiring a separate diagnostics click. Snapshot
fallbacks that auto-promote back to the true RTSP feed preserve the saved
RTSP/tunnel port instead of silently returning to `554`. If the selected
realmonitor subtype fails, the frame proxy also checks the alternate subtype
before giving up. Each successful poll runs
`ffmpeg` against the DVR's RTSP feed and updates the WIS image only after real
JPEG bytes exist. If wasm-agent cannot reach the DVR/tunnel host, the DVR
endpoint times out, auth fails, both channel subtypes are empty, or the frame is
all black, WIS shows that diagnostic instead of leaving a black pane on screen.
The older
`/camera/rtsp-session` stream endpoint remains available for continuous MJPEG
relay, but the WIS card favors verified RTSP frames because HTTP MJPEG and
snapshot CGI endpoints can serve black frames even when the real RTSP feed is
active. Recovery actions can still switch the same saved
credentials to direct snapshot polling, portal capture, HTTP(S) MJPEG, retry
the RTSP probe, configure DVR-outbound RTMP push, check DVR reachability after a
tunnel/network change, or keep the RTSP relay without re-entering the whole
profile.
Existing credential MJPEG/snapshot relay configs auto-migrate to the true RTSP
relay, and direct Intelbras snapshot configs with local credentials promote to
the matching RTSP realmonitor stream so a black still frame is not treated as
success. Snapshot configs without local credentials still auto-promote to the
same-origin snapshot relay on HTTPS pages instead of showing a mixed-content
dead end. Direct snapshot/portal recovery and HTTP/HTTPS portal-open actions
from an RTSP tunnel strip the RTSP port and use HTTP recovery ports, while RTSP
promotion keeps the saved RTSP/tunnel port. Stale saved portal URLs that point
at an RTSP tunnel port are ignored and regenerated as HTTP-safe portal origins.
Its explicit
`snapshot` mode builds
`http://user:pass@host:80/cgi-bin/snapshot.cgi?channel=N` and refreshes the
image in the WIS card, which is the most direct no-backend path when the DVR
HTTP API and browser authentication allow it. Its default `https` mode builds
`https://user:pass@host:443/cgi-bin/mjpg/video.cgi?channel=N&subtype=0|1` for
HTTPS browser playback when the DVR exposes MJPEG and the browser accepts the
DVR certificate. Its `mjpeg` mode builds the same path over HTTP port `80` for
local HTTP wasm-agent pages. Its `rtsp` mode builds
`rtsp://user:pass@host:RTSP_PORT/cam/realmonitor?channel=N&subtype=0|1` and uses the
same `/camera/rtsp-session` ffmpeg relay because the browser/WASM sandbox does
not expose raw RTSP/TCP/UDP sockets. The helper keeps secret URLs on the client and
accepts compact shortcuts such as `intelbras snapshot 192.168.1.78 1`,
`intelbras credentials 192.168.1.78 1 1`, or `intelbras 192.168.1.78 1 1`,
where the numbers are channel and extra stream.
If a direct stream fails because an HTTPS wasm-agent page cannot embed an HTTP
DVR URL, because the DVR refuses the HTTPS CGI endpoint, or because browser
auth blocks cross-origin images, the slot keeps snapshot retry, HTTP/HTTPS DVR
portal buttons, stream retry buttons, Reconfigure, and Clear visible instead of
trapping the user behind the last failed URL.
The server also gives WIS a userland persistence path: chat/model replies can
include a validated `hermes.wasm_agent.wis.patch.v1` block, and the adapter
applies it only to the active account-owned or joined shared-space WIS artifact.
Patch blocks omit `space_id` for the current space; placeholder values such as
`current-space` are normalized to the active wasm-agent space before writing.
The adapter accepts fenced patch blocks, `<wis-patch>` blocks, and raw JSON
objects only when they parse as that exact WIS patch schema; `add_document`
operations may include a sanitized document tree for immediate artifact render.
Direct provider and owned-agent chat paths use the same WIS patch envelope from
the browser: the client strips valid patch blocks from the reply, posts them to
`/wis/artifacts/patch`, then shows the validated apply result in the action
chain. The Artifacts inventory loads account-local and shared-space WIS
artifacts from `/wis/artifacts`, fetches individual definitions through
`/wis/artifacts/<artifact_id>`, and opens them in the WIS widget instead of
leaving generated artifacts as backend-only JSON files.
Space sharing starts with `/spaces/share`, `/spaces/join`, `/spaces/shared`,
and `/wis/artifacts/patch`; a shared space record tracks owner/member identity,
join code, and collaborative capabilities while leaving core wasm-agent firmware
outside userland write scope. In the launcher, right-clicking a user space can
rename it, open a share dialog with a copyable invite URL, use the browser share
sheet, or send the URL through WhatsApp. Space-home exposes Join Space so another
signed-in account can paste either the full invite URL or the raw join code.
Open shared spaces also use `/spaces/room` as the member-gated collaboration
tunnel. The room heartbeat stores short-lived presence, returns online/member
counts for the space title, carries the canonical shared `space_area`, and keeps
a bounded sanitized event feed for future shared chat, WIS co-creation, and
WebRTC signaling. The title displays the active room as `name online/members`,
for example `playground 2/2`.

The Observation inspector is the first embedded-agent framework layer. It keeps
a session-only, in-memory ring buffer of app-local semantic events and renders
the current `hermes.space_os.observation.v1` snapshot that an embedded agent
session would receive. It also debounces the latest snapshot to the local
`wasm-agent` backend at `/observation/latest`, which stores only the latest
debug snapshot under `state/users/<acc_id>/observation/latest.json` so the
orchestrator side can inspect the most recent clicked element or UI event for
that account. It captures workspace clicks, widget focus/drag/resize/minimize
and maximize actions, app-button opens, browser navigation and forwarded input
actions, task submits, node action requests, logs loads, bridge refreshes,
stream frame health, timings, and errors. It also stores a bounded,
privacy-safe interaction trace for recent pointer, wheel, Space scroll, and
viewport resize mechanics: coordinates, target summaries, element rectangles,
pointer capture state, durations, and movement distance are kept, but text input
values and OS-wide input are not. It does not persist a durable observation
history, upload it, capture OS-wide input, or install a document-level raw key
recorder. Typed text forwarded into the Host Browser is
summarized/redacted; submitted Hermes prompts are summarized with length
metadata because the user already submitted them to the bridge. Embedded chat
turns receive a clipped copy of the latest interaction trace so UI debugging can
reason about drag/resize mechanics without replaying full browser activity.
For browser-local state that the backend cannot read directly, the backend can
create a `client.snapshot.request` row and each signed-in browser polls
`/client/snapshot/request`, answers through `/client/snapshot/response`, and
stores a bounded `hermes.wasm_agent.client_snapshot.v1` payload. The snapshot
includes the active chat session, recent assistant actions/diagnostics, current
space, local-storage key sizes, WIS surface state, WIS camera runtime status,
and redacted provider/camera metadata. Camera artifact load failures also
publish a silent state snapshot so operator/Codex debugging can read the latest
browser-side failure from `state/users/<acc_id>/client-snapshots/` without a
manual capture button. The WIS surface also stores the last opened artifact and
restores it for the current space; if local camera config exists for an artifact,
that artifact wins over the sample counter surface.

The embedded assistant now has a global avatar overlay that sits above every
app panel, including Home, OS Space, Fleet, Logs, and Observation. Opening the
avatar reveals a chat panel that sends the user's message plus the current
bounded observation snapshot through the existing Hermes bridge
`/v1/chat/completions` endpoint. The panel keeps the same default desktop
footprint, while compact/mobile viewports open `wasm-agent-chat` at the current
visual viewport so the drawer fills the screen normally and shrinks above the
mobile keyboard; it exposes a compact `wa1` client capability map in agent context. Embedded turns
also receive a compact `client_snapshot_latest` tool summary when available, so
WIS/camera debugging can use the last browser-local snapshot stored on the backend. Model replies
can append a hidden `ar W H` op to resize `wasm-agent-chat` without changing the
rest of the workspace. The chat header uses two stacked lines: title/actions
first, then the full-width combined target/model selector and status chip;
bridge-backed turns include that resolved `target_node`, so operators can switch
between orchestrator, worker, and saved node/model targets without leaving the panel.
The token badge in the composer opens the context balloon beside itself. That
balloon shows only exact tokens, transcript turns, and a concatenated context
string so model-context dialect can be inspected without the old diagnostic grid.
Choosing `> New...` or `> Edit...` opens the draggable `nodesPanel` at the
screen center of the chat layer, outside the resizable `wasm-agent-chat` frame.
Its header stays sticky while the setup content scrolls, keeping the drag handle available. Choosing a
saved node/model or agent/model entry uses it from the same selector; adding
or editing a typed model id opens the modal's model setup form
instead of a native browser prompt; the backend
validates the provider/model id, writes it into the target node env and
`.hermes/config.yaml`, updates `API_SERVER_MODEL_NAME`, restarts the node, waits
for the runtime to report the model, and probes `/v1/chat/completions` before
the model is saved in the selector. Failed setup rolls the node env/config back.
The modal can remove the currently selected saved model, leaving the node default intact. Chat model choices are stored in a
small assistant-specific local storage record, separate from topology widget
layout, so adding a model from Home or any user space remains visible after
validation.
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
selected node remains the execution target. Each turn also sends a mutation
policy: admin `orchestrator` turns may discuss global wasm-agent firmware/source
changes, while sandboxed worker nodes are constrained to the current
account-owned wasm-user state root and must delegate core changes back to
orchestrator. Sandboxed/userland turns should emit WIS patch blocks for spaces,
components, automations, dashboards, games, and other portable artifacts instead
of source mutations. Non-admin accounts cannot route embedded chat turns to the global
orchestrator node; they must use an account-owned sandbox node. This keeps the avatar aligned with
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
footer and no automatic Timeline point. If files did change, the adapter reports
the complete changed-file list, creates a before-run Timeline checkpoint, then
creates the named after-run checkpoint using a short subject based on the target
node and the user's prompt. The changed-files footer exposes a Stepback action
that restores the tree to the before-run checkpoint through the Timeline API.

The avatar mode selector controls how `/agent/session/message` answers:
`Auto` uses local deterministic answers for known cheap resume/readme prompts
and uses the selected node through the bridge model for other turns, `Local`
never calls the model and answers from inspect-only tools, and `Bridge`
explicitly asks the configured bridge model after gathering compact tool
context.

The avatar is draggable and remembers its position in browser local storage.
The chat header is icon-first: a sessions/history button opens a local session
balloon with the New Chat icon action, and a context button opens the latest
tool-context preview in a separate balloon. The avatar opens `wasm-agent-chat`
with `?chat=wasm-agent-chat` on the current route, and the header control is a
minus/minimize action rather than a close/destroy action. Browser Back, Android
Back, desktop Escape, and manual minimize/close controls all route through the
same topmost-layer navigation path for chat, modals, menus, and popovers before
normal route history is consumed. Each UI layer remembers the route where it was
opened, so manual chat minimize closes in place after space changes instead of
using browser Back and returning to an older space. Transcripts, diagnostics,
context previews, and the selected chat/session are persisted in browser storage
for quick development continuity and are scoped by signed-in user plus browser
device id. This is local convenience state, not a durable multi-user account
store.

The composer uses a compact 34px send button with a restrained arrow icon.
While an embedded assistant turn is running, the button switches to a
stop-square state and aborts the in-flight `/agent/session/message` request
when clicked. The composer is now a decorated plain-text textarea composer:
the textarea value is the only source of truth, the browser owns caret,
selection, copy, paste, undo, redo, IME, and mobile editing, and a
pointer-transparent overlay mirrors the text with inline decorations. Raw
Markdown delimiters stay visible while composing, sent user messages render
through the same safe tokenizer/renderer path as assistant replies, and the
slash command palette reads the raw value without mutating it until a command
is explicitly selected. Enter sends, Shift+Enter inserts a newline, and
Ctrl/Cmd+Enter sends as an explicit keyboard equivalent.

Image attachments are compressed in the browser before they enter the local
adapter request or transcript cache. The composer also enforces an aggregate raw
attachment budget; extra images stay as attachment summaries instead of making
the local adapter request too large. The backend repeats that budgeting before
calling the Hermes bridge and sends an `attachment_manifest` action to the model.
Dropped files reserve square preview slots immediately while the browser reads,
compresses, and analyzes them, so a slow OCR/runtime path no longer leaves the
composer visually empty. The `Image scan` toggle now lives inside the attachment
preview strip and appears only while pending image attachments can use local
image-card analysis. Its `i` button opens an inline explanation balloon that
closes on outside interaction. Turning
the scan off affects new image drops while keeping resize/compression and basic
metadata intact. Direct-provider turns do not call the local attachment store;
they mark the browser media prep complete, append the local media manifest, and,
for OpenRouter provider configs, try OpenAI-compatible `image_url` content parts
with local image data and `video_url` parts for small local MP4/video files
before falling back to the manifest-only request. This
keeps vision-capable OpenRouter models testable without leaving a `run-wasm` row running
forever.
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
local backend stores the compacted image under
`state/users/<acc_id>/attachments` and returns a same-origin
`/agent/attachments/<hash>.<ext>` URL plus metadata. The embedded assistant
action chain shows the image path explicitly: store image assets, decode pixels,
analyze image with lazy modules, build image cards, then ask the selected node.
The local attachment store prunes old assets after saves by bounded byte,
file-count, and age limits; it is a development/runtime cache, not a durable
media library.
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
long turns. The browser timeout is stream-inactivity based: it resets whenever
the backend sends an action, heartbeat, or final payload. The backend owns the
bridge/model timeout and emits heartbeat rows while Hermes is still working, so
slow active turns stay visible instead of being mistaken for a dead request.

Assistant turns also render a compact action chain. While a turn is running the
chain stays open and grows with the visible client-side phases; when the adapter
returns, backend tool/action events are folded into the same chain and collapsed
above the final reply text. Each action carries a kind badge, status, focused
detail text, and an expandable arguments/result preview so inspect tools feel
closer to Discord's tool-call trail instead of generic progress rows. This
keeps the final answer at the bottom of the assistant bubble while preserving
the action trail. Empty media actions are omitted when no files are attached,
and bridge responses can add live Hermes Runs API event/tool-call trace rows
plus a reasoning availability summary without replaying raw hidden reasoning.
Run lifecycle rows are deduplicated and labelled by layer, for example
`bridge.run.started`, `backend.run.started`, `model.reasoning.available`,
`backend.run.completed`, and `bridge.run.completed`, so status polling and event
stream records do not appear as indistinguishable duplicate `run.started` or
`run.completed` rows.
Rows carry a small visual icon, completed `run-wasm` / `run-hermes` topic
sections collapse by default, and `tool.started` / `tool.completed` update one
tool row from running to done instead of rendering as duplicate rows. Tool rows
show the tool name once, keep the `tool` kind badge, and hide raw lifecycle
metadata such as `tool.completed` unless that metadata is the only useful
status signal.

The browser prefers `/agent/session/message/stream` for embedded chat turns.
That endpoint returns newline-delimited JSON action events as local adapter
tools finish, sends periodic heartbeat rows while waiting for Hermes/model
output, then sends a final agent payload; older browsers can still fall back to
the non-streaming `/agent/session/message` route.
Long bridge waits keep updating the running action row with a `Hermes bridge
active` heartbeat that names the latest completed step rather than reducing the
turn to a generic waiting state.
Streaming updates only auto-scroll the transcript when the user is already at
the bottom. When the user has scrolled away from the latest message, a small
sticky down-arrow appears and scrolls the drawer fully back to the latest
message. Scrollable wasm-agent surfaces share the same thin dark scrollbar
styling as `s-select` instead of browser-default scrollbars. Opening or creating
a session renders the transcript at the bottom, and
message action menus are available on assistant and user bubbles. Copy uses the
original message markdown source, so inline code spans such as
`` `agentStatus` `` remain intact.
If the user scrolls upward to inspect an earlier topic, new action events still
render but the viewport stays on the inspected content until the user returns to
the bottom.

Admin orchestrator source mutations use the `hermes.wasm_agent.mutation.v1`
block. `replace` operations require exact `find`/`replace` text. `append`
operations require a non-empty `insert` string and may include an `after`
anchor; append blocks without insert text are denied and surfaced in the
action row.

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
avatar is dragged, and clamps inside the visible viewport. Dragging the chat
header moves the same avatar anchor instead of giving the panel an independent
manual position, so the avatar core and chat stay bound together. Avatar-core
dragging keeps the avatar as the primary object and may swap the panel side;
chat-header dragging keeps the chat rectangle as the primary object and swaps
the avatar side when needed near edges. The avatar keeps its edge inset, but
the chat panel can clamp directly to the app edge, including its narrow-screen
width and height clamps. The chat-to-avatar gap follows the avatar inset, and
the avatar is layered behind the panel if the full-width chat reaches over it.
Avatar drag bounds also use `window.visualViewport` when available, so
mobile scroll areas and browser chrome do not let the icon escape the visible
rectangle; viewport resize resets the avatar to the visible bottom-right corner.

Assistant replies can include a Codex-style changed-files footer sourced from a
before/after worktree tree diff for that single request. Ambient dirty worktree
state is not shown as if the chat turn created it. The footer lives inside the
assistant message instead of the modal chrome, shows one collapsed summary row
by default, and expands to one full-path row per changed file with `+/-` counts.
Clicking a changed file path opens a compact inner diff balloon for that file's
changed hunks only. The balloon hides git metadata and shows only `was` and
`now` lines with red/green contrast, so the user can inspect the before/after
patch without leaving the chat. The expanded list stays scroll limited, so
changed-file reporting does not steal the main chat area.

The Modules panel is a local module management surface for the shadow PWA. It
shows locked core modules plus optional development, runtime, and
image-perception modules: Dev HMR, Observation, Host Browser, Embedded
Assistant, Timeline, Image Card Core, Barcode Reader, OCR, CV Shapes, and
Semantic Vision. Optional toggles store enable/disable state in browser local
storage. Toggling a module only changes local UI or analyzer
availability in `wasm-agent`; it does not install, remove, patch, or restart
backend components. The versioned module firmware lives under `public/modules/`
with `public/modules/index.js` as the app-facing registry. Per-user and runtime
state stays under `state/` or browser local storage, never inside the module
firmware folders.

The Timeline module is the first time-travel surface for cheap app evolution.
It reads git branch, head, dirty status, recent commits, local branches, and
`refs/wasm-agent-timeline/<acc_id>/<space_id>/*` checkpoints through the local
backend. Each space has its own fixed Timeline view through the top-right
config button; Home uses the `home` timeline as the account-level/global lane,
Admin uses `admin`, and user-created spaces use their own space id. Timeline
points are created automatically after chat turns that actually change the
worktree, using a temporary git index so tracked and untracked non-ignored files
can be captured without changing the real index or moving the current worktree.
Stepback is confirmation-gated and active for Timeline checkpoints; it restores
the selected run's before-ref and first writes a `before_stepback` checkpoint of
the current tree. Non-admin users can only step back paths inside their
account-owned sandbox, while core firmware/source paths require admin
orchestrator authority. Branch and merge actions remain planned until the UI can
preview exact file effects and stop/rollback behavior.
Timeline metadata is local runtime state under
`state/users/<acc_id>/timelines/<space_id>/` and is gitignored.

The backend fingerprints the temporary-index tree in
`state/users/<acc_id>/timelines/<space_id>/auto-latest.json`, so repeated runs
with identical files do not create duplicate refs, while new source changes get
a new recovery point without relying on the user to click a manual checkpoint
button.

The Home route is the app entrance: `/` and `/home` open the account home
space and show the `space-home` title. Home exposes a wider `New Space` action,
`Artifacts`, `Config`, and `Modules` modal actions, and the current account
storage badge.
Standard users are limited to 1 GB under their `state/users/<acc_id>/` root;
admins are shown as unlimited. Home's config button opens the account-global
`home` Timeline lane. The launcher also has a fixed `space-admin` space with a
crown icon. New spaces are persisted under
`state/users/<acc_id>/spaces/<space_id>/` and appear in the left global rail
below Admin. Admin space widgets start minimized as app icons; clicking an app
opens the widget above the app layer, except Timeline, which stays fixed behind
the space config flow. User-created spaces start without Admin apps or opened
widgets. Connected Devices is a Home core module page, so it does
not appear in Admin or user spaces unless a later porting flow maps it there. The
config modal header identifies the current space while the options list omits a
duplicate Space card. Each space config includes a minimap-style Space area map:
the white border shows the current viewport within the configured area, and
dragging the map edits only a draft area until Apply is clicked; Apply resizes
that space's absolute area up to `2000 x 2000px` without changing current
logical widget width/height. Space distance remains a line control that scales
app icons and opened widgets between `0.5x` and `2x`.
Area-map drags redraw at animation-frame cadence and hold the viewport marker in
the active visual state until the pointer is released. The white viewport border
is drawn as a full-map overlay from the currently applied viewport rather than
as a child of the resizing draft rectangle, so it stays steady while resizing
the draft.
App positions, widget geometry, topology card positions, and distance are saved
only in browser local storage by default, while user-space area is stored with
the space metadata so joined/shared spaces open with the same area on every
device. Open clients refresh that shared space metadata on focus, during the
regular workspace refresh loop, and through a focused `2.5s` active shared-space
room heartbeat. Production shared-space voice is currently disabled by default
while `/voice-lab` remains the recovery proof surface. When explicitly enabled,
shared-space voice uses that room heartbeat for presence and WebRTC signaling.
Voice presence is deliberately separate from shared-space
presence: seeing another device in a space never starts the local microphone or
creates a peer connection. The in-room voice button is the only local join path;
it requests microphone access, creates a device-local membership epoch, publishes
that epoch to the room, and maintains a short heartbeat while the local device
remains joined. The WebRTC mesh connects only after local membership exists and
only to other current voice memberships in the same room. Offers, answers, ICE,
mute, and leave messages carry the sender epoch plus the target epoch; clients
ignore retained or mismatched signals from previous memberships. A device that
leaves removes only its own membership and peer tracks, while the other joined
devices stay in voice. The detailed root-cause report, state machine, and manual
voice checklist live in [`VOICE_ROOM_LIFECYCLE.md`](./VOICE_ROOM_LIFECYCLE.md).
The isolated `/voice-lab` route is the current recovery proof surface for
two-client voice behavior; production shared-space voice is off unless
`HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1` is set, and should not receive more
lifecycle changes until that lab passes the manual matrix. The staged production
port now separates voice participant identity from account/browser device
identity: each page gets a voice-local client/device id, while the account
device id is carried only as metadata. Production peer discovery reads explicit
voice memberships rather than ordinary shared-space presence.
Space config keeps remote area applies paused so local drafts are left untouched
until Apply or Revert while presence still updates. Config
storage shows account usage plus local
disk availability and exposes Export/Import buttons for portable local backups;
exports include the browser-local layout payload, while imports restore that
payload back into the current browser. It also exposes encrypted client-state
export/import for the IndexedDB-first browser cache; importing an encrypted
snapshot replaces the local client-state stores and then reconciles through the
backend sync APIs.
The shell stays fixed while the
inner board can be scrolled or one-finger/click-drag panned. Mouse-wheel input
over the canvas changes Space distance instead of native-scrolling the board,
and widget-local wheel input is contained before it can reach the board. Home config also
includes a mobile launcher preference that can put the launcher on the top edge on narrow
screens. Right-clicking a user-created space opens a local menu for copying the
space id or deleting the space; the delete modal requires the exact
`DELETE <space name>` phrase before `OK` is enabled. Modal backdrops close only
when the click starts and ends on the backdrop, so selecting modal text and
releasing outside does not close the modal. The old fixed
OS/Fleet/Run/Logs/Observation/Modules shortcuts are no longer separate global
space buttons; those views remain internal Admin panels/modules. The launcher
defaults to a left rail; when the mobile top preference is enabled, Home stays
pinned at one end and the account button at the other while spaces scroll
between them.

The launcher's lower corner is reserved for account state. The compact account
button opens a Google Identity login popover when `GOOGLE_LOGIN_CLIENT_ID` is
available in `conf/wa.env`. Google sign-in uses same-window redirect mode and
posts the credential to the server-reported Google login URI, normally
`<origin>/auth/google/callback`. `HERMES_WASM_AGENT_PUBLIC_ORIGIN` is honored
from either the process environment or `conf/wa.env`, so deployments behind an
HTTPS reverse proxy can publish the exact redirect URI registered in Google
Cloud even if the Python process is bound to loopback. The login card renders
Google's own button as the visible clickable target, and callback failures are
reported in the login card after redirect. wasm-agent is account-gated: unauthenticated
requests can load only the login shell/static assets and auth endpoints, while
bridge, browser, timeline, agent, attachment, health, observation, and user
space services require an authenticated session. Admin accounts must be listed
with `ADMIN_EMAIL`; standard accounts must be listed with `USER_EMAILS`, or
`USER_EMAILS` must stay empty for an admin-only deployment. Non-admin sessions
must never route embedded chat turns to the global orchestrator target; they are
kept on the account-owned agent target and core/source changes must be delegated to
admin. If both lists are empty, every Google account is rejected. Other verified Google
accounts are rejected before a row is created. The local backend verifies Google
ID tokens through Google's token verification endpoint and stores allowed
accounts in `/local/plugins/wasm-agent/state/db/sqlite/wa_db.sqlite3` under
`user_tb`. `user_tb.id` is a Snowflake-style integer id so timestamp and
uniqueness stay inside one compact primary-key column.

## Public web security

`wa.colmeio.com` makes wasm-agent a world-reachable web service, so the server
must fail closed:

- Keep `plugins/wasm-agent/conf/wa.env` machine-local and untracked.
- Set exactly the intended admin with `ADMIN_EMAIL=<google-account>`.
- Leave `USER_EMAILS=` empty for admin-only access, or list standard accounts
  explicitly with `USER_EMAILS=<account>,<account>`; do not use a broad
  Google-login policy until tenant isolation is reviewed.
- Keep `GOOGLE_LOGIN_CLIENT_ID` configured in `conf/wa.env` for the same Google OAuth client
  whose authorized JavaScript origins include the production origin and whose
  authorized redirect URIs include `<origin>/auth/google/callback`.
- Do not expose the app port directly; public traffic should terminate at the
  HTTPS reverse proxy and reach wasm-agent on `127.0.0.1`.
- Protected routes must continue returning `401 auth_required` until a signed
  allowed-account session cookie is present.
- Host Browser WebSocket streams must reject missing or cross-origin `Origin`
  headers before the upgrade.
- Host Browser is disabled by default when
  `HERMES_WASM_AGENT_PUBLIC_ORIGIN` is an HTTPS origin. Keep it disabled for
  public launch unless CDP and private-network isolation have been reviewed;
  explicit opt-in uses `HERMES_WASM_AGENT_BROWSER_ENABLED=1`.

Public deployment on this host terminates TLS at Caddy for
`https://wa.colmeio.com`, then reverse-proxies to the Python server on
`127.0.0.1:8877`. The cloud ingress and host firewall should expose only the
public HTTPS edge, not the raw app port. The app port remains loopback-only so
the account gate is the only web entry point into local bridge, browser,
timeline, agent, attachment, health, observation, and user-space services.

The private-beta launch runbook lives in `LAUNCH.md`. It covers Caddy/HTTPS,
Google allowlist setup, backup/rollback, the Admin-only security-loop
dashboard, and the platform-level `hermes-attack` / `hermes-defense` loop.

Known security risks to target are tracked in
`/local/docs/roadmap/space-os/README.md`. The current high-risk areas are the
same-origin `/bridge/*` proxy to local orchestrator operations, host Chromium
CDP control, per-user filesystem isolation and quota enforcement, attachment
serving, git-backed Timeline refs and object growth, future node creation and
main-agent mounts, OAuth/cookie deployment configuration, service-worker cache
staleness, and model-context leakage from observations, transcripts, image
cards, logs, or file reads.

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
  -> same-origin /bridge/* proxy
  -> wasm-agent-owned Hermes bridge contract :8790
  -> Hermes Orchestrator CLI/API boundary
  -> Hermes Agent nodes
```

## Setup

Start the workspace and bridge:

```bash
horc space start
```

Start only the PWA script directly:

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

The doctor runs the source smoke test, wasm-agent bridge route coverage,
the auth-shell boot regression that keeps optional root assets from freezing
login, image-card golden coverage, client-first cloud contracts, client-state storage
coverage, client snapshot relay coverage, WIS camera HTTP/RTSP relay coverage
including a live loopback RTSP frame-decode fixture, security-loop
policy/runner tests, and the UI navigation history regression that keeps chat
minimize from navigating back to an older space after the user changes spaces
with chat open.

Every wasm-agent code commit must add or update a fast regression test that
would fail if that commit's smallest user-visible behavior regressed. Put the
check in `wasm_agent_smoke.test.js` or another focused test under `tests/`, wire
it into `scripts/doctor.sh` when it belongs in the default gate, and keep it
fast enough to run before every local checkpoint. The auth/login shell is guarded
by `tests/auth_shell_boot_regression.test.js`; any auth-shell or top-level module
change must keep that test green.

The heavier private-cloud People/DM/shared-chat acceptance pass is
`python3 plugins/wasm-agent/tests/people_chat_browser_acceptance.test.py`. It
starts a temporary cloud-mode server, drives two isolated Chromium profiles, and
verifies live friendship lifecycle, direct messages, stickers, reactions,
shared-space chat, unread/toast state, encrypted client-state roundtrip, and
refresh recovery without writing private cloud data into the repo.

Run the public-launch security gate before exposing the app outside a trusted
local network:

```bash
/local/plugins/wasm-agent/scripts/public_launch_security_check.sh
```

Use [`PUBLIC_LAUNCH_SECURITY.md`](./PUBLIC_LAUNCH_SECURITY.md) as the full
checklist and evidence template. For staging, set
`HERMES_WASM_AGENT_PUBLIC_URL=https://...` so the route and header probes hit
the deployed origin.

Run a bounded security-loop audit:

```bash
/local/plugins/wasm-agent/scripts/security_loop_run.py
```

The runner performs cheap local probes against `http://127.0.0.1:8877`, writes
failed probes into the Admin security dashboard, submits a bounded
`hermes-attack` audit directly to that node's Hermes Runs API, and asks
`hermes-defense` for mitigation plans when deterministic findings exist. It
does not silently apply fixes. Add `--wait-sec 120` when you want the runner to
poll node task output and ingest any JSON findings returned by `hermes-attack`;
if the native node run is still active at the deadline, the runner records
`timeout` and requests `/v1/runs/{run_id}/stop`. Native delivery reads
`API_SERVER_*` from `/local/agents/envs/<node>.env`; `--delivery bridge` is kept
only as a legacy compatibility path.

Keep bounded audits running sequentially:

```bash
/local/plugins/wasm-agent/scripts/security_loop_auto_start.sh
```

The loop executes `security_loop_run.py`, waits for that pass to finish, then
sleeps before the next pass. It uses a lock file under `state/security-loop/` so
manual and automatic runs do not overlap. Defaults are `all` mode, 300 seconds
of node polling, and a 300 second interval; override them with
`HERMES_WASM_AGENT_SECURITY_MODE`, `HERMES_WASM_AGENT_SECURITY_WAIT_SEC`,
`HERMES_WASM_AGENT_SECURITY_INTERVAL_SEC`, and
`HERMES_WASM_AGENT_SECURITY_SURFACES`. Identical clean node audits are capped by
`HERMES_WASM_AGENT_SECURITY_MAX_CLEAN_REPEAT`, default `3`, so the loop turns
repeated clean coverage into launch-readiness evidence instead of spending tokens
forever. Use `--force-node-task` for a one-off manual override. Stop the loop with
`/local/plugins/wasm-agent/scripts/security_loop_auto_stop.sh`.

The Admin `Security Loop` widget and the Admin `Security` side panel show two
separate things. The canvas widget is desktop-only; mobile operators should use
the Admin `Security` side panel instead of opening the widget from the app
layer.

- Latest runner execution: mode, delivery backend, probe counts, node task ids,
  and whether `hermes-attack` is running, completed, failed, timed out, or was
  stopped. The widget keeps this run history inside a scrollable run-log topic.
- Findings queue: actionable `hermes.security_loop.finding.v1` records that
  failed deterministic probes or `hermes-attack` returned as JSON. Clean runs
  can have a visible latest execution with zero findings.

The Topology widget also exposes live node runtime value. Node cards display the
working engine state, provider/model label, token deltas, and current token
total. It marks a node as working from embedded-chat run hints, bridge task
status, security-loop runs, token deltas, and node-reported `llm_active` state,
so orchestrator activity is visible even when the work started outside the
Topology widget. Right-click a node and choose `Statistics` to open a polling balloon for
token consumption, sessions, cost, activity, tool calls, warnings/errors, an
`hour` window, a smoothed token chart, and the latest activity log. The
statistics balloon can be moved by dragging its header, and changing time
windows keeps the balloon open. For the
security-loop pair,
`hermes-attack` and `hermes-defense` should be configured as
`opencode-go/deepseek-v4-flash` in their local env files.

Run history is available through `GET /security-loop/runs` and is rendered in the
Security Loop widget and Security panel. The runner includes a host-collected
authenticated route map in the `hermes-attack` prompt so it can reason about
logged-in platform paths without receiving cookies or tokens.

For useful node audits, prefer focused runs over broad sweeps:

```bash
/local/plugins/wasm-agent/scripts/security_loop_run.py --mode all --surface auth --surface browser --wait-sec 300
```

If a run times out, check the latest-run card in the Security panel, narrow the
surface list, or increase `--wait-sec`. Defense planning starts only after a
concrete finding exists; until then, `hermes-defense` stays idle by design.

## Environment

- `HERMES_WASM_AGENT_HOST`: bind host, default `127.0.0.1`.
- `HERMES_WASM_AGENT_PORT`: app port, default `8877`.
- `HERMES_WASM_AGENT_STATE_DIR`: state/log root, default
  `/local/plugins/wasm-agent/state`.
- `HERMES_WASM_AGENT_DEPLOYMENT_MODE`: `local` by default. Set to `cloud` for a
  private wasm-agent-cloud instance; cloud mode rejects public-repo state paths.
- `HERMES_WASM_AGENT_CLOUD_STATE_ROOT`: required in cloud mode. This private
  root owns `state/`, `conf/wa.env`, SQLite metadata, sync events, secrets, and
  user data outside the public repo.
- `HERMES_WASM_AGENT_CLOUD_INSTANCE_ID`: optional stable id used in public config
  and `horc space backup` manifests.
- `HERMES_WASM_AGENT_BRIDGE_URL`: Hermes bridge URL used by the PWA, default
  `http://127.0.0.1:8790`.
- `HERMES_WASM_AGENT_START_BRIDGE`: set to `0` to start only the PWA process.
- `HERMES_WASM_AGENT_BRIDGE_HOST`: bridge bind host, default `127.0.0.1`.
- `HERMES_WASM_AGENT_BRIDGE_PORT`: bridge port, default `8790`.
- `HERMES_WASM_AGENT_BRIDGE_STATE_DIR`: bridge pid/log/task state root, default
  `<HERMES_WASM_AGENT_STATE_DIR>/bridge`.
- `HERMES_WASM_AGENT_PID_FILE`: optional pid file override.
- `HERMES_WASM_AGENT_LOG_FILE`: optional server log override.
- `GOOGLE_LOGIN_CLIENT_ID`: required Google Identity Services client id in
  `conf/wa.env`.
- `ADMIN_EMAIL`: comma-separated Google admin email allowlist in `conf/wa.env`.
  Admin accounts receive the hardcoded Admin space and unlimited account
  storage.
- `USER_EMAILS`: optional comma-separated Google standard-user allowlist in
  `conf/wa.env`. Standard users receive isolated state under
  `state/users/<acc_id>/` and a 1 GB account storage quota.
- `HERMES_WASM_AGENT_ENV_PATH`: optional path override for the private
  wasm-agent env file, default `plugins/wasm-agent/conf/wa.env` in local mode
  and `<cloud-root>/conf/wa.env` in cloud mode.
- `HERMES_WASM_AGENT_DB_PATH`: optional account SQLite path override, default
  `plugins/wasm-agent/state/db/sqlite/wa_db.sqlite3` in local mode and
  `<cloud-root>/state/db/sqlite/wa_db.sqlite3` in cloud mode.
- `HERMES_WASM_AGENT_AUTH_SECRET_PATH`: optional signed-cookie secret path
  override, default `plugins/wasm-agent/state/db/sqlite/wa_auth_secret` in local
  mode and `<cloud-root>/state/db/sqlite/wa_auth_secret` in cloud mode.
- `HERMES_WASM_AGENT_CHAT_TIMEOUT_SEC`: embedded assistant bridge/model turn
  timeout, default `1800`, clamped between 30 seconds and 6 hours. The browser
  treats this as a stream-inactivity budget, not a total wall-clock limit.
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
- `HERMES_WASM_AGENT_FFMPEG`: optional `ffmpeg` binary override for the WIS
  true RTSP camera relay, default `ffmpeg` on `PATH`.
- `HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT`: test/diagnostic escape hatch for the
  WIS RTSP TCP reachability preflight, default `0`.
- `HERMES_WASM_AGENT_RTMP_INGEST_PORT`: base port for DVR-outbound RTMP push
  listeners, default `1935`. `cam-2` maps to the next port by default.
- `HERMES_WASM_AGENT_RTMP_BIND_HOST`: bind host for RTMP push listeners,
  default `0.0.0.0`.
- `HERMES_WASM_AGENT_RTMP_PUBLIC_HOST` / `HERMES_WASM_AGENT_RTMP_PUBLIC_PORT`:
  optional public host/port advertised in the DVR RTMP push URL.
- `HERMES_WASM_AGENT_CHROMIUM`: optional Chromium/Chrome binary override.
- `HERMES_WASM_AGENT_BROWSER_ENABLED`: opt in/out of the Host Browser backend.
  When unset, local HTTP development enables it and public HTTPS deployment
  disables it. Set to `1` on public hosts only after CDP/private-network
  isolation is reviewed.
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
- `HERMES_WASM_AGENT_SHARED_VOICE_ENABLED`: set to `1` to expose the production
  shared-space voice controls. Disabled by default during `/voice-lab` recovery.
- `HERMES_WASM_AGENT_VOICE_STUN_URLS`: comma-separated STUN URLs exposed to
  shared-space WebRTC clients, default `stun:stun.l.google.com:19302`.
- `HERMES_WASM_AGENT_VOICE_ICE_SERVERS_JSON`: JSON array of full WebRTC ICE
  server objects, including TURN credentials when needed. When set, it takes
  precedence over `HERMES_WASM_AGENT_VOICE_STUN_URLS`.
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
    modules/client-state/     # IndexedDB-first browser storage helpers
  scripts/
    start_wasm_agent.sh
    stop_wasm_agent.sh
    doctor.sh
  server/
    static_server.py
  state/
    README.md
    .gitignore
    db/sqlite/                # local account/friend/sync/fleet database and auth secret
    users/<acc_id>/
      spaces/<space_id>/      # account-owned space metadata
      device-settings.json    # account main-device pointer
      timelines/<space_id>/   # account/space timeline metadata
      devices/                # recently seen account devices
      device-sync/            # downloaded sync-installer manifests
      observation/latest.json  # latest account-local observation snapshot
      client-snapshots/        # latest/recent browser-local debug snapshots
      attachments/            # account-local image asset cache
  tests/
    wasm_agent_smoke.test.js
    ui_navigation_history.test.js
    image_card_golden.test.py
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
7. When parity is proven, document the migration plan for retiring remaining
   historical legacy UI notes and compatibility artifacts.
8. Use the Observation inspector as the foundation for embedded agent chat and
   suggest-only action proposals.

## Documentation Boundary

Docs must describe `wasm-agent` as the active parity/runtime plugin while
remaining honest about incomplete surfaces. Future Space OS, cloud domain, GPU
runtime, browser, or replacement claims belong in
`/local/docs/roadmap/space-os/wasm-agent-parity-spike.md` until implemented.

Any code change in this plugin must update this README or the roadmap when it
changes startup, ports, bridge endpoints, runtime state, or parity status.
