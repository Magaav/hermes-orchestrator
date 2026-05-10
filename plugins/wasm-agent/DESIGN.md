# WASM Agent Design Contract

This file is required context for frontend changes in `plugins/wasm-agent`.
Read it before changing `public/index.html`, `public/styles.css`, or
`public/app.js`.

## Module Architecture Vision

- `wasm-agent` should evolve as a small core runtime plus hierarchical modules,
  not as one undifferentiated application file. The app shell is the assembled
  mainframe: it owns boot, auth, routing, layout hydration, module registry
  loading, and stable browser/bridge contracts. Feature behavior should be
  expressed through modules whenever possible.
- Core modules are the non-removable platform layer. `spaces`, `devices`,
  `artifacts`, `config`, and `module-manager` are core because they define how
  users enter, inspect, configure, and extend the workspace. Core modules may be
  listed for visibility, but user controls must not disable them.
- Modules may be hierarchical. The `spaces` module owns Home/Admin/user space
  identity and space routing. A space can expose child modules as pages,
  actions, apps, widgets, or widget-internal capabilities. Admin maps the
  built-in app/widget modules onto the canvas; user-created spaces start empty
  and receive apps only through an explicit later mapping/porting flow. Home
  exposes account-level core modules as page actions instead of canvas apps.
- Module boundaries should prevent accidental breakage across the tree. A
  child module must not assume it can mutate another module's state directly.
  Cross-module behavior should use explicit registry metadata, mapped ids,
  events, bridge endpoints, or documented helper functions.
- Per-instance customization should happen through plugin/module descriptors,
  mappings, local state, and runtime data. The shared core mainframe should stay
  small, performance-conscious, and reusable across all wasm-agent instances,
  while each instance remains free to arrange spaces, plugins, modules, and
  state for its own workflow.
- Runtime and per-user state must stay outside module firmware folders. Module
  code describes capability and UI contracts; browser local storage, `state/`,
  and future sync/export systems own mutable state.

## Shell Layout

- The global launcher is a left rail by default. On narrow/mobile widths, Home
  config may switch it to a top bar preference; either placement must keep the
  Home launcher button and account/login control visible while the space list
  scrolls between them.
- The launcher owns exactly `72px` of width and must sit above the workspace
  canvas with an explicit stacking layer.
- The workspace canvas and any space board content must start after the
  launcher grid column. Do not use negative margins, fixed viewport offsets, or
  absolute positioning that lets the board slide behind the launcher.
- The shell itself must not scroll. The launcher is fixed to the viewport and
  must keep account/login controls in view; the inner space viewport owns
  scrolling and one-finger/click-drag panning when the board is larger than the
  visible viewport. Release velocity from recent drag samples continues the
  pan briefly as inertial motion, bounded by friction, velocity clamps, and
  board edges. Native workspace scrollbars stay hidden; subtle edge glows show
  when more board content exists in a direction. While the user pans or
  inertial motion is still moving the viewport, a temporary top-right minimap
  renders the total board, actual visible board rectangle, app icons, and open
  widget miniatures. The minimap uses the fixed config-button anchor while visible and
  fades the config button away until viewport motion stops. It must stay hidden when the
  board is not actually pannable, keep the viewport border visible at all board
  edges, clip widget/app miniatures to board bounds, and use minimap-namespaced
  classes for open widget footprints so global widget CSS cannot impose real
  panel minimum sizes inside the minimap. Opened apps are represented by their
  widget footprint instead of a duplicate app-icon marker; minimized app markers
  are positioned from the painted app-icon rectangle after minimized state is
  confirmed from layout. The viewport marker and entity markers both use the
  scroll container's logical coordinate space, so space area/distance changes, the
  launcher, and the painted board rectangle cannot skew the minimap projection.
  A fully visible icon remains inside the viewport marker at every board edge.
  On mobile/tablet breakpoints, Home/Admin/User space frames must collapse to
  one actual canvas row whenever the side panel is hidden; hidden inspector rows
  must not inflate the scroll viewport height used by minimap math. The minimap
  must use area/distance-sized board/canvas dimensions, not widget-inflated scroll
  dimensions; overflowing widgets are rerendered back into the canvas bounds
  instead of expanding the canvas. Mobile shell height must follow
  `window.visualViewport.height` when available, and the outer canvas wrapper
  must reserve the measured visual-viewport bottom inset without
  platform-specific guard offsets. Mobile widget dragging and resizing must
  still use the real area/distance-sized canvas bounds, just like desktop, while
  minimap board dimensions also come from the canvas rather than the padded
  wrapper.
  App markers are symbolic dots, but their
  size is capped from the projected icon footprint and clamped into the
  projected viewport whenever the painted icon is fully visible. The minimap and fixed config button layer above
  Home action buttons while active.
- Home is the account entrance and must show the `space-home` title. It shows
  home-level controls, account storage, modal launch actions, and the
  account-global Timeline access through the fixed config button. Home also
  exposes Artifacts, a local inventory of spaces, mapped apps/widgets, and
  browser-local layouts that previews the `wasm-artifact` direction.
- The space title sits on the same top edge as the fixed config button and its
  left edge aligns with the inner icon edge used by app buttons. The title-row
  organize control and fixed config control use the same `34px` square
  icon-button size. User-space shells must expose the real active space id in
  `data-panel` and use a separate shell-kind flag for shared layout styling, so
  diagnostics and top-level labels show the space name/id instead of the generic
  `user-space` category.
- Admin is a fixed launcher space for operational surfaces. It uses the same
  app-layer and widget-layer pattern as other working spaces, has the crown
  launcher icon, shows the `space-admin` title, and must not be stored or
  deleted as a user-created space.
- User-created spaces are account-owned working canvases. They may contain
  draggable app buttons and opened widgets, with widget layout persisted in
  browser local storage by default. Do not POST app/widget geometry, area, or
  distance to the server unless a premium sync/backup mode is explicitly
  implemented. Launcher entries for user-created spaces are icon-only; the
  visible rail must not render ordinal labels like `S1`.
- The shell must not reintroduce the removed header/status chrome, command
  form, canvas label, summary panel, or dock.
- Home-level actions sit on the black homespace itself. The primary action may
  be a wider text button when the action is the main object creation path.
- The launcher lower corner is reserved for account state. Do not put raw
  bridge/WASM status leds back in that slot; system status belongs in widgets
  or diagnostics surfaces.
- When auth is locked, the main app surface stays hidden behind the auth gate.
  Only the login shell and account control should be usable before an allowed
  account session is established.
- Space launcher hover/focus affordances must render inside the launcher rail
  without sliding behind the aside surface or the workspace canvas.
- Every space has a fixed top-right config button anchored to the visible
  canvas, not the scrollable board contents. It is layered above app icons and
  below widgets. It opens the space-local Timeline lane; Home uses the
  account-global `home` timeline. Timeline is a fixed config action, not an
  app-layer icon. Timeline stepback is confirmation-gated: chat turns that
  change files record a before-run and after-run checkpoint, and stepback
  restores the before-run ref after first writing a `before_stepback`
  checkpoint of the current tree. Non-admin users may only step back paths
  inside their account-owned sandbox; core firmware/source stepback requires
  admin orchestrator authority. Space config also owns a minimap-style Space
  area map; the white viewport border shows the visible canvas inside the
  configured per-space area. Dragging or typing changes only a draft inside the
  config modal; the actual board geometry and persisted metadata update only
  when Apply is clicked. Applied areas can resize up to `2000 x 2000px` without
  resizing existing logical widget geometry. Space config also owns a draggable
  Space distance line that scales app icons and opened widgets visually without
  rewriting their saved logical positions. Desktop wheel over the empty canvas
  must adjust Space distance around the cursor point rather than native-scrolling
  the hidden board. Wheel input that starts inside a widget must remain local to
  that widget: scrollable widget content may move, but the event must not chain
  into the space viewport. Widget content must reset the board grab cursor;
  only draggable widget chrome and resize handles should use drag/resize
  cursors. Mobile two-finger pinch must adjust Space distance
  around the midpoint between both touches. During wheel or pinch zoom, the top-right
  config button anchor must show the current zoom value. The zoom value may
  appear at the same time as the panning minimap, but it must sit on the higher
  z layer. The pinch hot path must avoid full widget layout, minimap rendering,
  and canvas redraw work on every pointer move; it should update board size,
  distance CSS, and existing app/widget screen positions, then commit the full
  layout/save pass after the gesture settles. Both slider knobs must remain
  within the line boundaries at minimum and maximum values.
- Apps are account/user entities that are mapped into spaces. Home lists core
  modules in its command strip; Admin maps its working apps; user-created spaces
  map no Admin apps by default, even for admin accounts. A widget must stay
  hidden in a space unless that app is mapped into the active space or is
  promoted there by a later porting flow. Per-space widget layout must be
  sanitized against that mapping so Admin/Home-only state cannot be saved into
  user-created spaces. Connected Devices is a core module page, not a canvas app
  or widget.
- App buttons can be dragged anywhere inside the app layer. Opening an app shows
  its widget above the app layer; minimizing hides only the widget and leaves
  the app button available. App buttons snap to the nearest non-overlapping
  `5px` app-layer grid point on drop and store pixel positions so viewport
  resizing does not drift placement; clicking an open app icon minimizes its
  widget again. The title-row organize control resets mapped app positions into
  a predictable grid starting flush with the current visible canvas edge, with
  no added gaps between icon boxes, and overflowing downward in rows only when
  the mapped app count cannot fit. It must measure the packed block, place that
  block inside the current area-sized logical canvas, and avoid forcing
  canvas-area recomputation. Organized positions are authoritative until a
  user manually drags an app again. App icons and widgets remain draggable on
  mobile; widgets remain free-positioned.
- When a minimized widget opens outside the visible canvas viewport, it is
  moved to the canvas initial point: the top-left beginning of the board.
- Opened widgets must stay bounded by the area-sized canvas on mobile. Space
  area may expand the scrollable board, and widget resize may grow a window
  horizontally beyond the current device screen so operators can pan across it;
  height still fits the visible canvas so the header and controls remain
  reachable.
- Right-clicking an app icon or widget header opens the app menu; mobile uses a
  still long-press. The menu exposes Edit and Copy app id. Editing persists the
  app/widget title, icon text/image, and min/max dimensions in the current
  browser-local space layout.
- Home includes a Connected Devices core module that lists devices seen for the
  signed in account through the local account devices endpoint, with an
  operating system icon per device. The page can switch the account's main device. If
  the recorded main device is offline, artifact-evolution actions should steer
  the user back to Connected Devices so they can pick a reachable main device.
  The Sync action downloads a device-specific installer manifest that records
  target device, main device, planned tunnel capability, client-local layout
  policy, and shareable artifact policy.
- User-created spaces/apps/widgets/widget-inner-entities should evolve into
  portable `wasm-artifacts`; see `ARTIFACTS.md`. Artifact semantics are
  shareable/backupable/marketplace-ready. App positions, widget positions,
  sizes, and Space distance stay client-local unless premium sync is explicit;
  user-space area is per-space metadata so shared spaces keep the same board
  size across devices.
- The Resources Monitor polls live host resource data while it is open and
  renders one metric row per line in this order: Nodes, Disk, RAM, CPU,
  Processes, Uptime. RAM and Disk use compact `usedGB/totalGB` values.
- Hermes Topology must stay rendered from the current node list. Right-clicking
  or long-pressing a topology node opens a node menu with Edit followed by
  Restart, Start, Stop, Update. Node Edit persists a local model
  `provider/name` override. Individual topology node cards are draggable within
  the topology widget and persist their positions with the widget layout. The
  node statistics balloon opens from that menu, remains open while changing
  `hour`/`daily`/`weekly`/`monthly`, and can be moved by dragging its header.
  Working state must combine embedded-chat run hints, fresh active bridge tasks,
  security-loop tasks, token deltas, and fresh node-reported `llm_active` so
  orchestrator work is visible even when it starts from chat, cron, or another
  client. Stale bridge activity or days-old `running` tasks must age out before
  painting a node yellow.
- Admin includes the Security Loop widget and Security side-panel view for the
  platform-level `hermes-attack` / `hermes-defense` loop. It must show concise
  chronological findings sorted by score, compact evidence previews, status and
  severity chips, and human-gated decisions. The canvas Security Loop widget is
  desktop-only; mobile access belongs in the Admin Security side panel. Run
  history/logs inside the widget must stay in a scrollable run-log topic. Raw
  logs stay behind evidence, task, or log drill-ins rather than in the main queue.
- Widget header controls prioritize minimize/maximize at the far right. Status
  chips may be present, but they must sit before the window controls.
- Widgets must remain draggable and resizable on desktop and mobile unless
  maximized. Maximize becomes a fixed fullscreen layer at the viewport origin,
  fills `100vw` by the visible viewport height without canvas padding, sits
  above launcher/app chrome and below the embedded assistant overlay, and must
  be reversible.
- Backdrop modals close only from a click that starts and ends on the backdrop.
  Pressing inside a modal to select text and releasing outside must not close it.
- In-app navigation owns closeable UI layers. Browser Back, Android Back,
  desktop Escape, and manual minimize/close controls must all close the topmost
  chat, modal, menu, or popover through the same path before normal route
  history is consumed.

## WIS Surface

- WIS is a wasm-agent module and widget, not a Host Browser mode and not an
  iframe/webview. It must stay under `plugins/wasm-agent/public/modules/wis/`
  plus shell wiring inside `plugins/wasm-agent`.
- The first WIS slice is allowed to simulate a tiny browser-like engine, but it
  must label that boundary honestly: DOM-like tree/state, navigation, events,
  render loop, sandbox permissions, and agent-readable surface state are real;
  network loading, HTML/CSS parsing, JavaScript execution, layout engines, and
  security origins are not real browser implementations yet.
- WIS automation must use structured state and actions. The supported hook is
  `window.wasmAgentWis.inspect()`, `window.wasmAgentWis.act(...)`, and
  `window.wasmAgentWis.exportSpace()`, and the Observation snapshot should carry
  the same surface state so embedded agents do not guess from pixels.
- Userland WIS evolution must use validated `hermes.wasm_agent.wis.patch.v1`
  payloads, not raw source writes. The server-side patcher may update
  account-owned or joined shared-space WIS artifacts, while core wasm-agent
  firmware/source remains protected unless the active chat turn has admin
  orchestrator authority.
- Shared spaces must have explicit owner/member records and join codes under
  wasm-agent state. Joining a space should create a local launcher entry and
  allow collaborative WIS/component/automation evolution without granting access
  to protected core source.
- Shared-space voice belongs to the room surface, not the assistant chat. The
  room endpoint is the signaling channel for WebRTC offer/answer/ICE events,
  live presence supplies target devices, and browser media must flow
  peer-to-peer with microphone echo cancellation/noise suppression enabled.
  The voice button joins a room-level voice session, publishes a `join` event,
  and only calls peers that also joined voice instead of merely being present in
  the shared space. A present peer may auto-join once when another room device
  joins voice, while explicit Leave starts a short cooldown so the browser does
  not immediately rejoin. When both peers join at the same time, deterministic
  device-id ordering chooses one caller so the other side waits and answers
  instead of both browsers publishing unresolved offers. ICE candidates can
  arrive before the offer/answer event in the room log, so the client buffers
  them until the peer connection has a remote description. SDP and ICE
  candidate text is stored verbatim, and answer SDP is published even when a
  browser stalls while settling its local description. Deployments may configure
  TURN/STUN servers through wasm-agent config; the UI should make join, waiting,
  mute, and leave states visible inside the active shared space.
- The launcher owns shared-space entry UX: right-click a user space to rename,
  share, copy its id, or delete it; Space-home owns Join Space and must accept a
  pasted invite URL as well as a raw join code. Closing context menus must not
  drive browser history back to Space-home.
- The initial artifact-space should remain local and portable. It must export a
  `hermes.wasm_agent.wis.space.v1` definition with explicit no-backend and
  no-iframe guarantees, and it must not add server endpoints or patch
  `hermes-space-ui`.

## Button Icons

- Icon buttons must be stable squares using the app button pattern, usually
  `34px` by `34px` for compact controls.
- Icons must be centered by layout or CSS geometry, not by text glyph metrics.
- For simple plus, close, copy, arrow, and menu icons, prefer CSS-drawn strokes
  or an existing icon system over visible text characters.
- Button text may be present for accessibility or fallback, but the visual icon
  itself must be centered in the exact button box.

## Chat Chrome

- Assistant response headers show only elapsed time on the left and message
  actions on the right.
- The assistant avatar and chat panel are one anchored group. Dragging either
  the avatar core or the chat header must move the same saved avatar anchor;
  the panel must not keep an independent manual position. Avatar-core dragging
  may keep the avatar as the primary anchor and swap the panel side. Chat-header
  dragging treats the chat rectangle as primary and swaps the avatar side when
  needed near edges. The avatar keeps its viewport inset, while the chat panel
  may clamp directly to the app viewport edge on narrow screens; the
  panel-to-avatar spacing follows the avatar inset. When edge-to-edge chat
  overlaps the avatar, the chat panel layers above the avatar.
- Opening the avatar opens `wasm-agent-chat` and pushes `?chat=wasm-agent-chat`
  on the current route. The chat header control is a minimize action with a
  single minus glyph, not an `x`; minimizing removes the chat URL state through
  the shared navigation stack. If the user changes spaces while chat is open,
  manual minimize must close chat in place instead of navigating back to the
  space where chat was opened.
- Assistant action chains render above the final answer. They stay expanded
  while the turn is running, collapse after completion, and keep the final
  answer text below the chain.
- Action rows must be meaningful: show the action kind, status, concise detail,
  and an expandable arguments/result preview when the adapter has one.
  Do not render empty media rows on text-only turns. Bridge/provider traces may
  add live Hermes Runs API event and tool-call rows; hidden raw reasoning should
  be summarized as availability/provenance, not replayed verbatim. Each row
  should carry a compact visual icon. Completed topic sections should close, and
  `tool.started` / `tool.completed` must update one tool row's state rather than
  rendering as two separate rows. Tool rows should show the tool name once; do
  not repeat `Tool:` plus a `tool` badge plus raw lifecycle text such as
  `tool.completed`.
- During active turns, local adapter action events should stream into the open
  chain before the final response collapses the chain. Stream heartbeats count
  as activity and should keep long Hermes/model waits visible rather than
  letting the browser apply a total wall-clock timeout. Heartbeats should name
  the current/latest Hermes step instead of showing only a generic waiting
  message.
- Assistant transcript auto-scroll is pinned-bottom only. Live updates may
  grow the chat, but if the user has scrolled upward to inspect a topic or diff,
  that manual viewport position wins until they scroll back to the bottom.
- Changed-file rows should expose the exact per-file changed hunks inside an
  inner diff balloon opened from the file path, not a whole-file dump, raw git
  metadata, or an ambient worktree diff. The balloon should show only visible
  `was` / `now` lines with red/green contrast.
- Source mutation blocks must be exact and small. `replace` uses `find` and
  `replace`; `append` requires a non-empty `insert` string and may use an
  `after` anchor. Invalid append blocks should be denied with a visible policy
  reason, not silently ignored.
- Local development HMR must reload the client automatically for JavaScript,
  module descriptor, HTML, manifest, and server-source changes, with reloads
  deferred only while an assistant turn is actively running.
- The composer is bottom anchored: attachment, model selector, token usage, and
  send controls live in the row below the text area. The model selector is the
  one-place control for choosing default/current, selecting a saved model,
  adding a model id, or removing the active saved model from the chat list.
  It should render compactly at about half of its track width. Chat model state
  must use assistant-owned local storage, not a widget layout key that can be
  sanitized away when another space is active.
- Composer Markdown uses the editable composer as the rendered input surface.
  Typing or pasting Markdown should render in place with the
  `agent-message-body agent-markdown` path on the next animation frame, then
  serialize that editable DOM back to Markdown when sending so the backend
  still receives text. Keep this lightweight and avoid introducing a separate
  Markdown editor dependency until the local renderer proves insufficient.
  Inline code must render only when there is content between the backticks; an
  empty pair must stay as literal editable backticks, and deleting through that
  pair must leave one visible backtick rather than clearing both. Rendered
  inline code must still provide a typing escape after the closing backtick
  instead of trapping the caret inside the `<code>` span. Copying selected
  composer content must serialize the rendered DOM back to Markdown so inline
  code keeps its backticks in the clipboard.
- Do not reintroduce status labels like "Hermes responded" or "Complete" into
  each message card.
- The token display beside Send must reflect exact model token usage returned
  by the adapter. Local deterministic turns show `0` tokens; unknown usage shows
  `Tokens -`.
- Image attachments must be compressed before request/persistence, must stay
  under the aggregate raw request budget, and must expose a visible remove
  control while pending. Images that cannot fit the budget should remain visible
  as summary chips and reach the adapter as metadata, not raw data URLs.
- Image attachments must produce a compact `hermes.wasm_agent.image_card.v1`
  before the model turn: browser decode, Canvas pixel analysis, palette,
  perceptual hash, visual notes, spatial brightness distribution, gradient,
  symmetry, sharpness/entropy metrics, lazy analyzer evidence, and local asset
  URL when storage succeeds. Analyzer modules must load on demand, cache their
  loaded promise/function in memory, and report provenance statuses instead of
  implying unavailable OCR, barcode, CV, or semantic evidence exists. Text-like
  stroke/region metrics may support "printed or label-like markings" claims, but
  exact text requires detected OCR evidence. Browser OCR may use native
  `TextDetector` or a lazy cached Tesseract.js runtime; Tesseract input should
  be cropped to likely text regions, contrast-stretched, and binarized before
  recognition. Either OCR path must remain timeout bounded and evidence-gated.
  The action chain for image turns must keep the path visible as store, decode,
  analyze, build image card, and ask node; text-only turns must skip those media
  rows entirely.
  Image cards must include an analyzer revision so stale PWA runtimes can be
  diagnosed from the same compact context the model sees. The backend attachment
  store should enrich stale browser cards, and current browser cards missing
  server-only hints, with server-side text-like signals, physical-scene hints,
  and conservative rounded/cylindrical shape hints before model inference
  instead of trusting incomplete client metadata. Shape hints are broad geometry
  evidence and must not be presented as exact object identity without raw
  vision or user-provided context; OCR itself only supports quoted readable
  text, not the object identity of the surface carrying that text.
- User messages with image cards should render an expandable compact card below
  the thumbnail/summary chip so the user can inspect the same visual facts the
  model saw without opening raw JSON previews.
- Raw `image_url` bridge forwarding must stay opt-in because the selected node
  provider may be text-only even when the OpenAI-compatible bridge accepts the
  top-level chat-completions shape.
- Image-card-only bridge prompts must redact attachment names, hashes, and local
  URLs before model inference so filename hints cannot become visual evidence.

## Change Gate

Every frontend change should update or verify:

- `plugins/wasm-agent/tests/wasm_agent_smoke.test.js`
- `plugins/wasm-agent/tests/ui_navigation_history.test.js` for chat/history
  navigation behavior
- This design contract when the visual rule changes
- `plugins/wasm-agent/README.md` when runtime behavior changes
