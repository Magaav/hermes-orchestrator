export const moduleDefinition = {
  id: "devices",
  title: "Connected Devices",
  status: "core account",
  detail: "Shows account devices, main-device authority, and sync installer actions for the home space.",
  defaultEnabled: true,
  core: true,
  firmware: "/modules/devices/module.js",
  endpoints: ["/account/devices", "/account/devices/sync", "/account/devices/main"],
  state: {
    runtimeRoot: "state/users/<acc_id>/devices",
    settings: "state/users/<acc_id>/device-settings.json",
    syncRoot: "state/users/<acc_id>/device-sync",
  },
};
