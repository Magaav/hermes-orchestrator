export const moduleDefinition = {
  id: "host-browser",
  title: "Host Browser",
  status: "pixel stream",
  detail: "Renders host Chromium pixels and forwards confirmed browser input from the widget.",
  defaultEnabled: true,
  firmware: "/modules/browser/module.js",
  endpoints: ["/browser/stream", "/browser/open", "/browser/input", "/browser/close"],
  state: {
    runtimeRoot: "state/browser",
    browserStorage: "wasmAgent.widgetLayout.v1",
  },
};
