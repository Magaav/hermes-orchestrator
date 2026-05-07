# WASM Agent Design Contract

This file is required context for frontend changes in `plugins/wasm-agent`.
Read it before changing `public/index.html`, `public/styles.css`, or
`public/app.js`.

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
  visible viewport. Native workspace scrollbars stay hidden; subtle edge glows
  show when more board content exists in a direction. While the user pans, a
  temporary top-right minimap renders the total board, actual visible board
  rectangle, app icons, and open widget miniatures. The minimap uses the fixed config-button anchor while visible and
  fades the config button away until panning ends. It must stay hidden when the
  board is not actually pannable, keep the viewport border visible at all board
  edges, clip widget/app miniatures to board bounds, and use minimap-namespaced
  classes for open widget footprints so global widget CSS cannot impose real
  panel minimum sizes inside the minimap. Opened apps are represented by their
  widget footprint instead of a duplicate app-icon marker; minimized app markers
  are positioned from the painted app-icon rectangle after minimized state is
  confirmed from layout. The viewport marker and entity markers both use the
  scroll container's logical coordinate space, so space density changes, the
  launcher, and the painted board rectangle cannot skew the minimap projection.
  A fully visible icon remains inside the viewport marker at every board edge.
  On mobile/tablet breakpoints, Home/Admin/User space frames must collapse to
  one actual canvas row whenever the side panel is hidden; hidden inspector rows
  must not inflate the scroll viewport height used by minimap math.
  App markers are symbolic dots, but their
  size is capped from the projected icon footprint and clamped into the
  projected viewport whenever the painted icon is fully visible. The minimap and fixed config button layer above
  Home action buttons while active.
- Home is the account entrance and must show the `space-home` title. It shows
  home-level controls, account storage, modal launch actions, and the
  account-global Timeline access through the fixed config button. Home also
  exposes Artifacts, a local inventory of spaces, mapped apps/widgets, and
  device-local layouts that previews the `wasm-artifact` direction.
- Admin is a fixed launcher space for operational surfaces. It uses the same
  app-layer and widget-layer pattern as other working spaces, has the crown
  launcher icon, shows the `space-admin` title, and must not be stored or
  deleted as a user-created space.
- User-created spaces are account-owned working canvases. They may contain
  draggable app buttons and opened widgets, with widget layout persisted under
  the current account, current device id, and space id.
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
  app-layer icon. Space config also owns a draggable space-density line;
  increasing density expands the scrollable board width and height for that
  space without resizing existing widgets, and the slider knob must remain
  within the line boundaries at minimum and maximum density.
- Apps are account/user entities that are mapped into spaces. Home maps only
  Home-owned apps such as Connected Devices; Admin and user spaces map their
  own working apps. A widget must stay hidden in a space unless that app is
  mapped into the active space or promoted there by a later porting flow.
  Per-space widget layout must be sanitized against that mapping so Home-only
  app state cannot be saved into user-created spaces. Connected Devices is also
  hard-gated to Home in widget availability and CSS transition guards.
- App buttons can be dragged anywhere inside the app layer. Opening an app shows
  its widget above the app layer; minimizing hides only the widget and leaves
  the app button available. App buttons snap to the nearest non-overlapping
  `5px` app-layer grid point on drop and store pixel positions so viewport
  resizing does not drift placement; clicking an open app icon minimizes its
  widget again. App icons and widgets remain draggable on mobile; widgets remain
  free-positioned.
- When a minimized widget opens outside the visible canvas viewport, it is
  moved to the canvas initial point: the top-left beginning of the board.
- Opened widgets must fit the visible canvas viewport on mobile. Space density
  may expand the scrollable board, but it must not make a widget window wider
  than the current device screen.
- Right-clicking an app icon or widget header opens the app menu; mobile uses a
  still long-press. The menu exposes Edit and Copy app id. Editing persists the
  app/widget title, icon text/image, and min/max dimensions in the current
  account/space layout.
- Home includes a Connected Devices app that lists devices seen for the signed
  in account through the local account devices endpoint, with an operating
  system icon per device. The widget can switch the account's main device. If
  the recorded main device is offline, artifact-evolution actions should steer
  the user back to Connected Devices so they can pick a reachable main device.
  The Sync action downloads a device-specific installer manifest that records
  target device, main device, planned tunnel capability, device-local layout
  policy, and shareable artifact policy.
- User-created spaces/apps/widgets/widget-inner-entities should evolve into
  portable `wasm-artifacts`; see `ARTIFACTS.md`. Artifact semantics are
  shareable/backupable/marketplace-ready, but app positions, widget positions,
  sizes, and space density stay device-local.
- The Resources Monitor polls live host resource data while it is open and
  renders one metric row per line in this order: Nodes, Disk, RAM, CPU,
  Processes, Uptime. RAM and Disk use compact `usedGB/totalGB` values.
- Hermes Topology must stay rendered from the current node list. Right-clicking
  or long-pressing a topology node opens a node menu with Edit followed by
  Restart, Start, Stop, Update. Node Edit persists a local model
  `provider/name` override. Individual topology node cards are draggable within
  the topology widget and persist their positions with the widget layout.
- Widget header controls prioritize minimize/maximize at the far right. Status
  chips may be present, but they must sit before the window controls.
- Widgets must remain draggable and resizable on desktop and mobile unless
  maximized. Maximize fills the viewport/workspace rect and must be reversible.
- Backdrop modals close only from a click that starts and ends on the backdrop.
  Pressing inside a modal to select text and releasing outside must not close it.
- In-app navigation owns closeable UI layers. Browser Back, Android Back,
  desktop Escape, and manual minimize/close controls must all close the topmost
  chat, modal, menu, or popover through the same path before normal route
  history is consumed.

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
  needed near edges.
- Opening the avatar opens `wasm-agent-chat` and pushes `?chat=wasm-agent-chat`
  on the current route. The chat header control is a minimize action with a
  single minus glyph, not an `x`; minimizing removes the chat URL state through
  the shared navigation stack.
- Assistant action chains render above the final answer. They stay expanded
  while the turn is running, collapse after completion, and keep the final
  answer text below the chain.
- Action rows must be meaningful: show the action kind, status, concise detail,
  and an expandable arguments/result preview when the adapter has one.
- During active turns, local adapter action events should stream into the open
  chain before the final response collapses the chain.
- Local development HMR must reload the client automatically for JavaScript,
  module descriptor, HTML, manifest, and server-source changes, with reloads
  deferred only while an assistant turn is actively running.
- The composer is bottom anchored: attachment, token usage, and send controls
  live in the row below the text area.
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
  analyze, build image card, and ask node.
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
- This design contract when the visual rule changes
- `plugins/wasm-agent/README.md` when runtime behavior changes
