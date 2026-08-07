// Descriptor sources kept as plain metadata to avoid eager Android boot imports:
// from "./hmr/module.js"
// from "./spaces/module.js"
// from "./observation/module.js"
// from "./devices/module.js"
// from "./native-standby/module.js"
// from "./artifacts/module.js"
// from "./config/module.js"
// from "./module-manager/module.js"
// from "./browser/module.js"
// from "./wis/module.js"
// from "./client-state/module.js"
// from "./assistant/module.js"
// from "./remote-control/module.js"
// from "./timeline/module.js"
// from "./image-card-core/module.js"
// from "./barcode-reader/module.js"
// from "./ocr/module.js"
// from "./speech-transcription/module.js"
// from "./cv-shapes/module.js"
// from "./semantic-vision/module.js"
// from "./asolaria/module.js"
// from "./artifact-foundry/module.js"
// from "./video-v1/module.js"
// from "./video-v2/module.js"
const moduleDefinition = (definition) => Object.freeze(definition);

export const MODULE_DEFINITIONS = Object.freeze([
  moduleDefinition({
    id: "dev-hmr",
    title: "Dev HMR",
    status: "development",
    detail: "Reloads local source edits while the shadow PWA is running.",
    defaultEnabled: true,
    firmware: "/modules/hmr/dev-hmr.js",
    endpoints: ["/modules/hmr/events"],
    state: {
      browserStorage: "wasmAgent.modules.v1",
    },
  }),
  moduleDefinition({
    id: "spaces",
    title: "Spaces",
    status: "core workspace",
    detail: "Owns the home, admin, and user space launcher plus space creation and deletion.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/spaces/module.js",
    endpoints: ["/spaces"],
    state: {
      runtimeRoot: "state/users/<acc_id>/spaces",
      layoutRoot: "browser local wasmAgent.spaceWidgetLayouts.v2",
    },
  }),
  moduleDefinition({
    id: "observation",
    title: "Observation",
    status: "inspect-only",
    detail: "Builds and publishes the bounded workspace snapshot for embedded agent context.",
    defaultEnabled: true,
    firmware: "/modules/observation/module.js",
    endpoints: ["/observation/latest"],
    state: {
      runtimeRoot: "state/observation",
    },
  }),
  moduleDefinition({
    id: "devices",
    title: "Connected Devices",
    status: "core account",
    detail: "Shows account devices, main-device authority, and sync installer actions for the home space.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/devices/module.js",
    endpoints: ["/account/devices", "/account/devices/sync", "/account/devices/main"],
    state: {
      runtimeRoot: "state/users/<acc_id>/devices",
      settings: "state/users/<acc_id>/device-settings.json",
      syncRoot: "state/users/<acc_id>/device-sync",
    },
  }),
  moduleDefinition({
    id: "native-standby",
    title: "Native Standby",
    status: "native companion",
    detail: "Tracks the native companion contract for wake phrase standby, live transcription, device presence, and platform-specific installer delivery.",
    defaultEnabled: true,
    firmware: "/modules/native-standby/module.js",
    endpoints: ["/native/resolve", "/native/download", "/account/devices/native", "/account/devices/native/download"],
    state: {
      runtimeRoot: "state/users/<acc_id>/native-companion",
      browserStorage: "wasmAgent.modules.v1:native-standby",
      wakePhrase: "hi wasm",
    },
  }),
  moduleDefinition({
    id: "artifacts",
    title: "Artifacts",
    status: "core inventory",
    detail: "Lists local workspace artifacts and exposes storage import/export boundaries.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/artifacts/module.js",
    endpoints: ["/storage/export", "/storage/import"],
    state: {
      runtimeRoot: "state/users/<acc_id>",
      browserStorage: "wasmAgent.spaceWidgetLayouts.v2",
    },
  }),
  moduleDefinition({
    id: "config",
    title: "Config",
    status: "core space",
    detail: "Owns space settings such as storage, area, distance, timeline access, and launcher preference.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/config/module.js",
    endpoints: ["/config.json", "/storage/export", "/storage/import", "/timeline/status"],
    state: {
      browserStorage: "wasmAgent.spaceWidgetLayouts.v2",
      runtimeConfig: "conf/wa.env",
    },
  }),
  moduleDefinition({
    id: "module-manager",
    title: "Modules",
    status: "core controls",
    detail: "Renders the module inventory and local enablement controls for optional modules.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/module-manager/module.js",
    state: {
      browserStorage: "wasmAgent.modules.v1",
    },
  }),
  moduleDefinition({
    id: "browser",
    title: "Browser",
    status: "native Chromium",
    detail: "Owns an Electron WebContentsView portal with persistent isolated sessions and bounded navigation proof.",
    defaultEnabled: true,
    firmware: "/modules/browser/browser.entry.js",
    capabilities: ["browser.session.status", "browser.navigate", "browser.history", "browser.native.surface", "browser.prove"],
    state: {
      browserStorage: "wasmAgent.browserPortal.v2",
      layoutRoot: "state/users/<acc_id>/spaces/<space_id>/widget-layout.json",
    },
  }),
  moduleDefinition({
    id: "wis",
    title: "Artifacts",
    status: "wasm-backed client sandbox",
    detail: "Runs portable WIS artifacts through a browser-local JS shell plus an embedded WASM microkernel for deterministic artifact metrics, layout, and media capability planning.",
    defaultEnabled: true,
    firmware: "/modules/wis/module.js",
    runtime: "/modules/wis/engine.js",
    cameraArtifact: "/modules/wis/artifacts/camera.js",
    wasmRuntime: "hermes.wasm_agent.wis.wasm_engine.v1",
    artifactSchemas: [
      "hermes.wasm_agent.wis.space.v1",
      "hermes.wasm_agent.wis.camera_artifact.v1",
    ],
    controllerSchemas: [
      "hermes.wasm_agent.wis.camera_controller.v1",
    ],
    endpoints: [],
    state: {
      artifactSchema: "hermes.wasm_agent.wis.space.v1",
      browserStorage: "session-local runtime state",
    },
  }),
  moduleDefinition({
    id: "property-photo-cleaner",
    title: "Property Photo Cleaner",
    status: "browser-local LiteRT",
    detail: "Cleans property photos locally with lazy-loaded correction and inpainting assets.",
    defaultEnabled: true,
    firmware: "/modules/property-photo-cleaner/property-photo-cleaner.entry.js",
    endpoints: [],
    state: {
      browserStorage: "hermes.property-photo-cleaner.models",
      networkPolicy: "photo-bytes-local",
    },
  }),
  moduleDefinition({
    id: "batch-cleaner",
    title: "Batch Cleaner",
    status: "browser-local batch pipeline",
    detail: "Detects and cleans objects across up to 30 property photos with observable sequential queues.",
    defaultEnabled: true,
    firmware: "/modules/batch-cleaner/batch-cleaner.entry.js",
    endpoints: [],
    state: {
      browserStorage: "session-local runtime state",
      networkPolicy: "photo-bytes-local",
    },
  }),
  moduleDefinition({
    id: "asolaria",
    title: "ASOLARIA Drills",
    status: "experimental; no decision authority",
    detail: "Browser-local receipt and lattice research artifact. Its tested binary predictor adds no value and must not alter agent answers.",
    defaultEnabled: true,
    firmware: "/modules/asolaria/asolaria.entry.js",
    runtime: "/modules/asolaria/runtime.js",
    artifact: "/modules/asolaria/artifact.json",
    artifactSchema: "hermes.wasm_agent.asolaria.artifact.v1",
    receiptSchema: "hermes.wasm_agent.asolaria.receipt.v1",
    calibrationSchema: "hermes.wasm_agent.asolaria.calibration.v1",
    endpoints: [],
    state: {
      runtime: "lazy browser singleton",
      input: "ephemeral browser memory",
      output: "operator-exported receipt only",
      networkPolicy: "no input upload",
      decisionAuthority: "none",
    },
  }),
  moduleDefinition({
    id: "artifact-foundry",
    title: "Artifact Foundry",
    status: "candidate deterministic generator",
    detail: "Generates content-addressed structured artifacts from bounded recipes with a WASM transform core and explicit verification receipts.",
    defaultEnabled: true,
    firmware: "/modules/artifact-foundry/runtime.js",
    artifact: "/modules/artifact-foundry/artifact.json",
    recipeSchema: "hermes.wasm_agent.artifact.recipe.v1",
    receiptSchema: "hermes.wasm_agent.artifact.receipt.v1",
    endpoints: [],
    state: {
      input: "ephemeral browser memory",
      output: "operator-exported artifact",
      networkPolicy: "generator-network-denied",
    },
  }),
  moduleDefinition({
    id: "client-state",
    title: "Client State",
    status: "client-first runtime",
    detail: "Owns browser-local chat, WIS, attachment, brain, and sync cursor storage contracts.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/client-state/module.js",
    endpoints: ["/account/friends", "/spaces/room", "/sync/events", "/fleet"],
    state: {
      indexedDb: "wasmAgent.clientFirst.v1",
      fallback: "memory",
      serverRole: "auth-sync-relay-backup-fleet",
    },
  }),
  moduleDefinition({
    id: "embedded-assistant",
    title: "Embedded Assistant",
    status: "chat-only",
    detail: "Shows the global avatar, local sessions, diagnostics, and inspect-only adapter.",
    defaultEnabled: true,
    firmware: "/modules/assistant/module.js",
    endpoints: ["/agent/session/message"],
    state: {
      browserStorage: "wasmAgent.agentSessions.v1",
    },
  }),
  moduleDefinition({
    id: "remote-control",
    title: "Remote Control",
    status: "consented viewport",
    detail: "Owns consented co-control viewport frames and the controller preview surface.",
    defaultEnabled: true,
    core: true,
    firmware: "/modules/remote-control/module.js",
    endpoints: ["/remote-control/live", "/sync/events"],
    state: {
      transport: "/remote-control/live WebSocket with sync_event_tb fallback",
      browserStorage: "wasmAgent.remoteControl.adminCoControlSession.v1",
    },
  }),
  moduleDefinition({
    id: "timeline",
    title: "Timeline",
    status: "git-backed",
    detail: "Shows branchable git history, dirty state, and checkpoint refs for safe app evolution.",
    defaultEnabled: true,
    firmware: "/modules/timeline/module.js",
    endpoints: ["/timeline/status", "/timeline/checkpoint"],
    state: {
      runtimeRoot: "state/users/<acc_id>/timelines/<space_id>",
      gitRefs: "refs/wasm-agent-timeline/<acc_id>/<space_id>/*",
    },
  }),
  moduleDefinition({
    id: "image-card-core",
    title: "Image Card Core",
    status: "browser pixels",
    detail: "Builds compact image-card facts with native decode, Canvas sampling, palette, hash, and layout metrics.",
    defaultEnabled: true,
    firmware: "/modules/image-card-core/module.js",
    analyzer: {
      kind: "image",
      mode: "built-in",
      cache: "always resident with app runtime",
      evidence: "pixel_stats",
    },
  }),
  moduleDefinition({
    id: "barcode-reader",
    title: "Barcode Reader",
    status: "lazy evidence",
    detail: "Checks attached images for QR/barcodes on demand, then keeps the detector function cached in memory.",
    defaultEnabled: true,
    firmware: "/modules/barcode-reader/module.js",
    analyzer: {
      kind: "image",
      mode: "lazy-singleton",
      cache: "promise + detector function",
      evidence: "barcode",
      native_api: "BarcodeDetector",
    },
  }),
  moduleDefinition({
    id: "ocr",
    title: "OCR",
    status: "lazy OCR",
    detail: "Tries native TextDetector first, then lazy-loads and caches a Tesseract.js OCR runtime when needed.",
    defaultEnabled: true,
    firmware: "/modules/ocr/module.js",
    analyzer: {
      kind: "image",
      mode: "lazy-singleton",
      cache: "promise + detector/worker function",
      evidence: "text",
      native_api: "TextDetector",
      fallback_library: "tesseract.js",
      default_runtime_url: "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js",
    },
  }),
  moduleDefinition({
    id: "speech-transcription",
    title: "Speech Transcription",
    status: "lazy local ASR",
    detail: "Adds on-demand embedded-chat microphone transcription through a worker-owned local Transformers.js/WebGPU/WASM pipeline.",
    defaultEnabled: true,
    firmware: "/modules/speech-transcription/speech-transcription.js",
    worker: "/modules/speech-transcription/speech-transcription-worker.js",
    metadata: "/modules/speech-transcription/models/english-v1/metadata.json",
    analyzer: {
      kind: "audio",
      mode: "lazy-worker",
      cache: "immutable versioned SHA assets",
      evidence: "transcript",
      default_engine: "transformers.js",
      acceleration: ["webgpu", "wasm"],
      browser_speech_recognition: "disabled",
    },
  }),
  moduleDefinition({
    id: "cv-shapes",
    title: "CV Shapes",
    status: "lazy planned",
    detail: "Reserved for on-demand contour, layout, and region evidence beyond the core Canvas metrics.",
    defaultEnabled: false,
    firmware: "/modules/cv-shapes/module.js",
    analyzer: {
      kind: "image",
      mode: "lazy-singleton",
      cache: "promise + cv function",
      evidence: "regions",
      candidate_library: "opencv.js or small WASM CV kernels",
    },
  }),
  moduleDefinition({
    id: "semantic-vision",
    title: "Semantic Vision",
    status: "lazy planned",
    detail: "Reserved for optional embedding or classifier evidence when a small local vision runtime is available.",
    defaultEnabled: false,
    firmware: "/modules/semantic-vision/module.js",
    analyzer: {
      kind: "image",
      mode: "lazy-singleton",
      cache: "promise + model function",
      evidence: "semantic_labels",
      candidate_library: "onnxruntime-web or WebNN/WebGPU model",
    },
  }),
  moduleDefinition({
    id: "video-v1",
    title: "Video V1",
    status: "browser-local media editor",
    detail: "Trims local MP4 files and exports bounded WebM AV1/Opus modules with an AVIF poster.",
    defaultEnabled: true,
    firmware: "/modules/video-v1/video-v1.entry.js",
    artifact: "/modules/video-v1/artifact.json",
    endpoints: [],
    state: {
      input: "ephemeral browser file",
      output: "operator-exported media",
      networkPolicy: "media-bytes-local",
    },
  }),
  moduleDefinition({
    id: "video-v2",
    title: "Video V2",
    status: "Mediabunny WebCodecs comparison",
    detail: "Trims and transcodes local video through pinned Mediabunny demux/mux plus WebCodecs AV1/Opus, then inspects the produced bytes.",
    defaultEnabled: true,
    firmware: "/modules/video-v2/video-v2.entry.js",
    artifact: "/modules/video-v2/artifact.json",
    endpoints: [],
    state: { input: "ephemeral browser file", output: "operator download", networkPolicy: "media-local; pinned runtime CDN" },
  }),
]);
