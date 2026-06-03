# wasm-agent Modules

This directory contains the versioned module firmware for the `wasm-agent`
PWA runtime.

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
  phrase and live transcription behavior. Home's Go Native action resolves
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
- `browser/`: Host Browser firmware contract; runtime browser captures and
  profiles live under `state/browser/`.
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
- `cv-shapes/`: lazy planned contour/layout evidence contract; disabled by
  default until a CV runtime is bundled.
- `semantic-vision/`: lazy planned semantic label/embedding contract; disabled
  by default until a small local vision runtime is bundled.

`index.js` is the app-facing registry. Add modules there when they should show
up in the in-app Modules panel.
