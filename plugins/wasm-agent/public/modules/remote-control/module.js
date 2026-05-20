export const moduleDefinition = {
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
};
