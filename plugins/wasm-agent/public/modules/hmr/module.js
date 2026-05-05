export const moduleDefinition = {
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
};
