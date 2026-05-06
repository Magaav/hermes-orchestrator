# WASM Agent Design Contract

This file is required context for frontend changes in `plugins/wasm-agent`.
Read it before changing `public/index.html`, `public/styles.css`, or
`public/app.js`.

## Shell Layout

- The global launcher is always a left rail, including narrow/mobile widths.
- The launcher owns exactly `72px` of width and must sit above the workspace
  canvas with an explicit stacking layer.
- The workspace canvas and any space board content must start after the
  launcher grid column. Do not use negative margins, fixed viewport offsets, or
  absolute positioning that lets the board slide behind the launcher.
- Home and user-created spaces are black canvases with no topbar, command form,
  side panel, dock, or widgets.
- Home-level actions sit on the black homespace itself. The primary action may
  be a wider text button when the action is the main object creation path.
- The launcher lower corner is reserved for account state. Do not put raw
  bridge/WASM status leds back in that slot; system status belongs in the
  topbar or diagnostics surfaces.
- When auth is locked, the main app surface stays hidden behind the admin gate.
  Only the login shell and account control should be usable before the admin
  session is established.
- Space launcher hover/focus affordances must render inside the launcher rail
  without sliding behind the aside surface or the workspace canvas.

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
