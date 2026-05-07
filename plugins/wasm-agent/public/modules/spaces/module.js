export const moduleDefinition = {
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
};
