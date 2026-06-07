const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wasmAgentNative", {
  platform: "windows",
  runtime: "electron",
  nativeDesktop: true,
  nativeDiagnostics: {
    run: (operation) => ipcRenderer.invoke("wasm-agent:native-diagnostics-operation", String(operation || "")),
    onEvent: (callback) => {
      if (typeof callback !== "function") return () => {};
      const handler = (_event, payload) => callback(payload || {});
      ipcRenderer.on("wasm-agent:native-diagnostics-event", handler);
      return () => ipcRenderer.removeListener("wasm-agent:native-diagnostics-event", handler);
    },
  },
  config: () => ipcRenderer.invoke("wasm-agent:native-config"),
  configure: (update) => ipcRenderer.invoke("wasm-agent:native-configure", update || {}),
  testBackend: (serverUrl) => ipcRenderer.invoke("wasm-agent:native-test-backend", serverUrl),
  logAuthDiagnostic: (kind, payload) => ipcRenderer.invoke("wasm-agent:native-auth-diagnostic", kind, payload || {}),
  uploadAuthDiagnostics: () => ipcRenderer.invoke("wasm-agent:native-upload-auth-diagnostics"),
  flushAuthCookies: (options) => ipcRenderer.invoke("wasm-agent:native-flush-auth-cookies", options || {}),
  reload: () => ipcRenderer.invoke("wasm-agent:native-reload"),
  status: () => ipcRenderer.invoke("wasm-agent:native-status"),
});

contextBridge.exposeInMainWorld("__wasmAgentDevHmr", {
  requestReload: (paths) => ipcRenderer.invoke("wasm-agent:native-dev-hmr-reload", Array.isArray(paths) ? paths : []),
});
