export const moduleDefinition = {
  id: "config",
  title: "Config",
  status: "core space",
  detail: "Owns space settings such as storage, density, timeline access, and launcher preference.",
  defaultEnabled: true,
  core: true,
  firmware: "/modules/config/module.js",
  endpoints: ["/config.json", "/storage/export", "/storage/import", "/timeline/status"],
  state: {
    browserStorage: "wasmAgent.spaceWidgetLayouts.v2",
    runtimeConfig: "conf/wa.env",
  },
};
