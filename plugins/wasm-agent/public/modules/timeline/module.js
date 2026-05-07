export const moduleDefinition = {
  id: "timeline",
  title: "Timeline",
  status: "git-backed",
  detail: "Shows branchable git history, dirty state, and checkpoint refs for safe app evolution.",
  defaultEnabled: true,
  firmware: "/modules/timeline/module.js",
  endpoints: ["/timeline/status", "/timeline/checkpoint"],
  state: {
    runtimeRoot: "state/users/<acc_id>/timelines/<space_id>",
    gitRefs: "refs/wasm-agent-timeline/<acc_id>/<space_id>/*",
  },
};
