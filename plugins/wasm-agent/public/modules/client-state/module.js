export const moduleDefinition = {
  id: "client-state",
  title: "Client State",
  status: "client-first runtime",
  detail: "Owns browser-local chat, WIS, attachment, brain, and sync cursor storage contracts.",
  defaultEnabled: true,
  core: true,
  firmware: "/modules/client-state/module.js",
  endpoints: ["/account/friends", "/spaces/room", "/sync/events", "/fleet"],
  state: {
    indexedDb: "wasmAgent.clientFirst.v1",
    fallback: "memory",
    serverRole: "auth-sync-relay-backup-fleet",
  },
};
