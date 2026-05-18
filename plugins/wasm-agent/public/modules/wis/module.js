export const moduleDefinition = {
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
};
