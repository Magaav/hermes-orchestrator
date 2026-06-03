const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wasmAgentNative", {
  platform: "windows",
  runtime: "electron",
  nativeDesktop: true,
  config: () => ipcRenderer.invoke("wasm-agent:native-config"),
  configure: (update) => ipcRenderer.invoke("wasm-agent:native-configure", update || {}),
  testBackend: (serverUrl) => ipcRenderer.invoke("wasm-agent:native-test-backend", serverUrl),
  reload: () => ipcRenderer.invoke("wasm-agent:native-reload"),
  status: () => ipcRenderer.invoke("wasm-agent:native-status"),
});

contextBridge.exposeInMainWorld("__wasmAgentDevHmr", {
  requestReload: (paths) => ipcRenderer.invoke("wasm-agent:native-dev-hmr-reload", Array.isArray(paths) ? paths : []),
});
