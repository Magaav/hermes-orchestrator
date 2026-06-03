export const moduleDefinition = {
  id: "native-standby",
  title: "Native Standby",
  status: "native companion",
  detail: "Tracks the native companion contract for wake phrase standby, live transcription, device presence, and platform-specific installer delivery.",
  defaultEnabled: false,
  firmware: "/modules/native-standby/module.js",
  endpoints: ["/native/resolve", "/native/download", "/account/devices/native", "/account/devices/native/download"],
  state: {
    runtimeRoot: "state/users/<acc_id>/native-companion",
    browserStorage: "wasmAgent.modules.v1:native-standby",
    wakePhrase: "hi wasm",
  },
};
