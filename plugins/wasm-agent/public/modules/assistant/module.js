export const moduleDefinition = {
  id: "embedded-assistant",
  title: "Embedded Assistant",
  status: "chat-only",
  detail: "Shows the global avatar, local sessions, diagnostics, and inspect-only adapter.",
  defaultEnabled: true,
  firmware: "/modules/assistant/module.js",
  endpoints: ["/agent/session/message"],
  state: {
    browserStorage: "wasmAgent.agentSessions.v1",
  },
};
