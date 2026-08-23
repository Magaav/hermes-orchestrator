export const moduleDefinition = {
  id: "browser",
  title: "Browser",
  status: "native Chromium",
  detail: "Electron WebContentsView portal with persistent isolated sessions and bounded navigation proof.",
  defaultEnabled: true,
  firmware: "/modules/browser/browser.entry.js?v=20260822-surface-readiness1",
  capabilities: ["browser.session.status", "browser.navigate", "browser.history", "browser.native.surface", "browser.prove"],
  state: {
    browserStorage: "wasmAgent.browserPortal.v2",
    layoutRoot: "state/users/<acc_id>/spaces/<space_id>/widget-layout.json",
  },
};
