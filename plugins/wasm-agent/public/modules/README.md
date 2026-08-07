# wasm-agent Modules

This directory contains the versioned module firmware for the `wasm-agent`
PWA runtime.

External app widgets are created by `app-registry.js`. Every external widget
exposes minimize, maximize/restore, and close controls; close delegates to the
mounted module's lifecycle API so background work and object URLs can be
disposed before the host is hidden. Persisted open widgets remain hidden while
their lazy module remounts after navigation or reload; failed mounts stay hidden
and retain a bounded diagnostic on the host.

`widget-window-state.js` is the single visibility boundary for widget window
chrome. A disabled module remains hidden even when stale layout state says its
widget was open.

`widget-dimensions.js` owns shared resize limits. External apps may declare
their minimum width and height in `app-registry.js`; Batch Cleaner declares a
250px square minimum and adapts its contents with container queries.

Each module owns a folder with a small `module.js` descriptor. Runtime and
per-user state stays outside this directory:

## Architecture

`wasm-agent` uses modules as a hierarchy, not just a flat feature list. The
browser shell is the shared mainframe that loads the registry, keeps boot/auth
and layout contracts stable, and lets all wasm-agent instances share core
evolution. Core modules describe the non-removable platform layer. Other
modules can be mapped into spaces as pages, actions, apps, widgets, analyzers,
or widget-internal capabilities.

The `spaces` core module is the parent for Home, Admin, and user spaces. Home
shows account-level core modules as page actions. Admin and user spaces map
working app/widget modules onto the canvas. This keeps module boundaries clear:
child modules should communicate through registry metadata, mapped ids, events,
documented helpers, or bridge endpoints rather than mutating each other
directly.

Plugins should extend the system by adding module descriptors, mappings, and
runtime state instead of forking the shared shell. That keeps the core fast and
portable while allowing each wasm-agent instance to customize its own module
tree and workflow.

- `hmr/`: development hot-reload firmware; no durable runtime state.
- `spaces/`: core workspace contract for `space-home`, `space-admin`, user
  spaces, and space creation/deletion. Core modules are listed in the Modules
  panel but cannot be disabled.
- `devices/`: core account-device contract for the home Connected Devices page;
  device records live under `state/users/<acc_id>/devices/` and main-device
  settings live in `state/users/<acc_id>/device-settings.json`.
- `native-standby/`: optional native companion contract for screen-off wake
  phrase and live transcription behavior. Home's Native action resolves
  platform-specific installers through `/native/resolve` and downloads only
  existing native artifacts through `/native/download`; generic ZIP packages are
  developer/debug compatibility only. Request records live under
  `state/users/<acc_id>/native-companion/`.
- `artifacts/`: core artifact/storage inventory contract for the home Artifacts
  action and storage import/export boundaries.
- `config/`: core space configuration contract for the top-right space gear. It
  is intentionally not listed in the home command strip.
- `module-manager/`: core module inventory contract for the home Modules action
  and local enablement controls.
- `browser/`: Electron-native Chromium portal using one `WebContentsView` per
  active surface. The PWA owns browser chrome and sends geometry, visibility,
  navigation, history, and proof operations through the bounded preload bridge;
  Electron owns isolated persistent sessions. Browser/PWA-only clients report
  the missing native capability instead of using iframe, canvas emulation, or
  an extension fetch bridge.
- `wis/`: browser-local WIS artifact runtime and embedded WASM microkernel.
  `wis/artifacts/camera.js` owns the portable focused-camera artifact factory,
  slot/focus helpers, push-camera config shape, and camera controller contract;
  the shell imports it for host rendering instead of defining that artifact
  shape inside `app.js`.
- `observation/`: Observation firmware contract; the latest debug snapshot
  lives under `state/users/<acc_id>/observation/latest.json`.
- `timeline/`: Timeline/time-travel firmware contract; checkpoint metadata
  lives under `state/users/<acc_id>/timelines/<space_id>/` and checkpoint
  commits live under `refs/wasm-agent-timeline/<acc_id>/<space_id>/*`.
- `assistant/`: embedded assistant firmware contract; local transcripts and
  settings currently live in browser local storage.
- `remote-control/`: consented co-control firmware contract; it owns low-bandwidth
  viewport frame capture and the controller preview surface while the shell
  handles auth, sync-event transport, and grant lifecycle.
- `image-card-core/`: built-in browser image-card analyzer contract; the runtime
  uses native image decode plus Canvas sampling and stays resident with the app.
- `barcode-reader/`: lazy image evidence contract; it initializes native
  `BarcodeDetector` on first image turn when the browser supports it and reuses
  the detector function afterward.
- `ocr/`: lazy OCR evidence contract; it tries native `TextDetector` first,
  then lazy-loads and caches a Tesseract.js runtime when needed. The default
  runtime URL is configurable through `window.__WASM_AGENT_TESSERACT_URL__`.
- `speech-transcription/`: lazy embedded-chat microphone transcription
  contract. It starts only from the mic button, uses `getUserMedia` plus Web
  Audio for local capture/VAD glow, and hands audio to a worker-owned local ASR
  pipeline. English v1 metadata lives under static module paths with immutable
  version/SHA cache policy and pins Transformers.js, ONNX Runtime WASM, and
  Whisper tiny English fp16 assets. Mic click warms the local ASR worker while
  permission is pending, and the worker reuses same-SHA assets across speech
  cache versions plus stores tiny SHA cache markers so immutable
  runtime/model assets are not rehashed on every load. Capture prefers
  frame-batched AudioWorklet with ScriptProcessor fallback, then speech-gates
  with a short pre-roll, noise-adaptive VAD thresholds, enforced adaptive
  rolling partials, partial token streaming, duration-capped decode, ONNX graph
  optimization, and deterministic beam final decode; replacing runtime/model
  artifacts or tuning decode/VAD metadata is a shared web update, not a native
  rebuild.
- `video-v1/`: lazy browser-local video range editor. It accepts formats and
  codecs the current browser can decode, then decodes the chosen file
  once through the browser, scales frames into the bounded output canvas,
  records at no more than 30 fps as WebM AV1 with at most one Opus track, and
  creates the poster through the shared single-thread AVIF WASM encoder. Source
  media stays in ephemeral browser memory; only the user-triggered WebM, AVIF,
  and compact manifest downloads persist.
- `video-v2/`: comparison editor using pinned Mediabunny 1.52.3 for container
  inspection, primary-track selection, trimming, forced AV1/Opus WebCodecs
  transcoding, WebM muxing, metadata stripping, progress, and post-output
  verification. It lazy-loads the permitted runtime only after video intent,
  retries once at 700 kbps when the 900 kbps result exceeds 3 MB, and keeps
  selected media bytes local.
- `cv-shapes/`: lazy planned contour/layout evidence contract; disabled by
  default until a CV runtime is bundled.
- `semantic-vision/`: lazy planned semantic label/embedding contract; disabled
  by default until a small local vision runtime is bundled.
- `asolaria/`: lazy browser-local ASOLARIA receipt engine. It runs the pinned
  deterministic Rust/WASM ABI, keeps input bytes local, exports 3,078-byte
  receipts, calibrates imported binary function results on train/holdout
  splits, and reports the GGUF/LiteRT/ASI boundary explicitly rather than
  presenting catalog tensors as an executable model.

`index.js` is the app-facing registry. Add modules there when they should show
up in the in-app Modules panel.
