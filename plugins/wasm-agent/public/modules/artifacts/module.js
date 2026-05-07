export const moduleDefinition = {
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
};
