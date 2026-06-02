export const moduleDefinition = {
  id: "native-standby",
  title: "Native Standby",
  status: "native companion",
  detail: "Tracks the go-native companion contract for wake phrase standby, live transcription, and device presence.",
  defaultEnabled: false,
  firmware: "/modules/native-standby/module.js",
  endpoints: ["/account/devices/native", "/account/devices/native/download"],
  state: {
    runtimeRoot: "state/users/<acc_id>/native-companion",
    browserStorage: "wasmAgent.modules.v1:native-standby",
    wakePhrase: "hi wasm",
  },
};
