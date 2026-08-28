"use strict";

const assert = require("assert");
const { createCompanionStartup, preferredNativeWindow } = require("./companion-startup");

function setupWindow() {
  const handlers = {};
  return {
    destroyed: false, shown: false,
    webContents: { on: (name, fn) => { handlers[name] = fn; }, removeListener: () => {} },
    destroy() { this.destroyed = true; },
    isDestroyed() { return this.destroyed; },
    show() { this.shown = true; },
    focus() {}, handlers,
  };
}

(async () => {
  const companionWindow = { __wasmAgentCompanionOverlay: true, isDestroyed: () => false };
  const normalWindow = { isDestroyed: () => false };
  assert.strictEqual(preferredNativeWindow([companionWindow, normalWindow]), normalWindow);
  assert.strictEqual(preferredNativeWindow([companionWindow]), companionWindow);
  const authenticatedWindow = setupWindow();
  const authenticatedCompanion = { shown: false, show() { this.shown = true; }, hide() {} };
  const authenticated = createCompanionStartup({
    setupWindow: authenticatedWindow,
    companion: authenticatedCompanion,
    authSessionStatus: async () => ({ authenticated: true }),
  });
  assert.strictEqual((await authenticated.start()).state, "companion");
  assert.strictEqual(authenticatedCompanion.shown, true);
  assert.strictEqual(authenticatedWindow.destroyed, true);

  let authenticatedSetupCreates = 0;
  const lazyAuthenticatedCompanion = { shown: false, show() { this.shown = true; }, hide() {} };
  const lazyAuthenticated = createCompanionStartup({
    createSetupWindow: () => { authenticatedSetupCreates += 1; return setupWindow(); },
    companion: lazyAuthenticatedCompanion,
    authSessionStatus: async () => ({ authenticated: true }),
  });
  assert.strictEqual((await lazyAuthenticated.start()).state, "companion");
  assert.strictEqual(authenticatedSetupCreates, 0, "authenticated startup must not create a hidden full-PWA setup renderer");

  const loginWindow = setupWindow();
  const loginCompanion = { hidden: false, show() {}, hide() { this.hidden = true; } };
  const login = createCompanionStartup({
    setupWindow: loginWindow,
    companion: loginCompanion,
    authSessionStatus: async () => ({ authenticated: false }),
  });
  assert.strictEqual((await login.start()).state, "authentication");
  assert.strictEqual(loginWindow.shown, true);
  assert.strictEqual(loginCompanion.hidden, true);

  let loginSetupCreates = 0;
  const lazyLogin = createCompanionStartup({
    createSetupWindow: () => { loginSetupCreates += 1; return setupWindow(); },
    companion: loginCompanion,
    authSessionStatus: async () => ({ authenticated: false }),
  });
  assert.strictEqual((await lazyLogin.start()).state, "authentication");
  assert.strictEqual(loginSetupCreates, 1);
  console.log("companion startup tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
