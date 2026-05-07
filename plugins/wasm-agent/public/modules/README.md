# wasm-agent Modules

This directory contains the versioned module firmware for the `wasm-agent`
PWA runtime.

Each module owns a folder with a small `module.js` descriptor. Runtime and
per-user state stays outside this directory:

- `hmr/`: development hot-reload firmware; no durable runtime state.
- `browser/`: Host Browser firmware contract; runtime browser captures and
  profiles live under `state/browser/`.
- `observation/`: Observation firmware contract; the latest debug snapshot
  lives under `state/users/<acc_id>/observation/latest.json`.
- `timeline/`: Timeline/time-travel firmware contract; checkpoint metadata
  lives under `state/users/<acc_id>/timelines/<space_id>/` and checkpoint
  commits live under `refs/wasm-agent-timeline/<acc_id>/<space_id>/*`.
- `assistant/`: embedded assistant firmware contract; local transcripts and
  settings currently live in browser local storage.
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
