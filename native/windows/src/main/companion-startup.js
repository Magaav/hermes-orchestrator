"use strict";

function preferredNativeWindow(windows = []) {
  const live = windows.filter((window) => window && !window.isDestroyed());
  return live.find((window) => window.__wasmAgentCompanionOverlay !== true) || live[0] || null;
}

function createCompanionStartup({ setupWindow = null, createSetupWindow = () => setupWindow, companion, authSessionStatus, onStatus = () => {} } = {}) {
  let disposed = false;
  let checking = false;
  let authenticationWindow = setupWindow;

  const emit = (state, extra = {}) => {
    const value = { schema: "hermes.wasm_agent.companion_startup.v1", state, ...extra };
    onStatus(value);
    return value;
  };

  const didFinishLoad = () => void sync("setup-did-finish-load");
  const currentSetupWindow = () => (authenticationWindow && !authenticationWindow.isDestroyed() ? authenticationWindow : null);
  const ensureSetupWindow = () => {
    const current = currentSetupWindow();
    if (current) return current;
    authenticationWindow = createSetupWindow();
    authenticationWindow?.webContents?.on?.("did-finish-load", didFinishLoad);
    return authenticationWindow;
  };

  if (authenticationWindow) authenticationWindow.webContents?.on?.("did-finish-load", didFinishLoad);

  const sync = async (reason = "startup") => {
    if (disposed || checking) return emit(disposed ? "disposed" : "checking", { reason });
    checking = true;
    let auth = { authenticated: false };
    try {
      auth = await authSessionStatus();
    } catch (error) {
      auth = { authenticated: false, error: String(error?.message || error) };
    } finally {
      checking = false;
    }
    if (disposed) return emit("disposed", { reason });
    if (auth.authenticated === true) {
      companion.show();
      const setup = currentSetupWindow();
      if (setup) {
        setup.webContents?.removeListener?.("did-finish-load", didFinishLoad);
        setup.destroy();
      }
      authenticationWindow = null;
      return emit("companion", { reason, authenticated: true });
    }
    companion.hide();
    const setup = ensureSetupWindow();
    if (setup && !setup.isDestroyed()) {
      setup.show();
      setup.focus();
    }
    return emit("authentication", { reason, authenticated: false, auth_error: String(auth.error || "") });
  };

  const dispose = () => {
    disposed = true;
    currentSetupWindow()?.webContents?.removeListener?.("did-finish-load", didFinishLoad);
  };

  return { dispose, start: () => sync("startup"), sync };
}

module.exports = { createCompanionStartup, preferredNativeWindow };
