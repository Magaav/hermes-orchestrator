export const moduleDefinition = {
  id: "observation",
  title: "Observation",
  status: "inspect-only",
  detail: "Builds and publishes the bounded workspace snapshot for embedded agent context.",
  defaultEnabled: true,
  firmware: "/modules/observation/module.js",
  endpoints: ["/observation/latest"],
  state: {
    runtimeRoot: "state/observation",
  },
};
