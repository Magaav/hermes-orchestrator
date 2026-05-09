export const moduleDefinition = {
  id: "wis",
  title: "WIS",
  status: "client sandbox",
  detail: "Renders a local browser-like interaction surface from portable DOM-like state without a backend or iframe.",
  defaultEnabled: true,
  firmware: "/modules/wis/module.js",
  runtime: "/modules/wis/engine.js",
  endpoints: [],
  state: {
    artifactSchema: "hermes.wasm_agent.wis.space.v1",
    browserStorage: "session-local runtime state",
  },
};
