export const moduleDefinition = {
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
};
