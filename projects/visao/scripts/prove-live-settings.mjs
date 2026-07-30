#!/usr/bin/env node
// Authenticated browser proof for workspace settings, inventory, audit, and administration.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = new URL(process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/");
const screenshotPath = path.resolve(process.argv[2] || "/tmp/visao-settings-admin.png");
const actionsScreenshotPath = screenshotPath.replace(/(\.[^.]+)$/, "-actions$1");
appURL.searchParams.set("settings-proof", String(Date.now()));

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const targetResponse = await fetch(`${cdpOrigin}/json/new?${encodeURIComponent(appURL)}`, { method: "PUT" });
if (!targetResponse.ok) throw new Error(`CDP target creation failed: HTTP ${targetResponse.status}`);
const target = await targetResponse.json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let requestID = 0;

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

socket.on("message", (wire) => {
  const message = JSON.parse(String(wire));
  const current = pending.get(message.id);
  if (!current) return;
  pending.delete(message.id);
  if (message.error) current.reject(new Error(message.error.message || "CDP command failed"));
  else current.resolve(message.result || {});
});

await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  return result.result?.value;
}

async function waitFor(expression, timeoutMilliseconds = 45_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await sleep(150);
  }
  throw new Error(`Browser condition timed out: ${expression.slice(0, 140)}`);
}

async function openTab(label) {
  await evaluate(`[...document.querySelectorAll(".settings-tabs button")]
    .find((node) => (node.textContent || "").trim() === ${JSON.stringify(label)})?.click()`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: String(appURL) });
  await waitFor("document.readyState === 'complete' && document.documentElement.classList.contains('app-ready') && !!document.querySelector('.home')");

  const home = await evaluate(`(() => ({
    modules: [...document.querySelectorAll(".module-card strong")].map((node) => (node.textContent || "").trim()),
    count: (document.querySelector(".module-section__heading span")?.textContent || "").trim()
  }))()`);
  await evaluate(`[...document.querySelectorAll(".module-card")]
    .find((node) => /configurações/i.test(node.textContent || ""))?.click()`);
  await waitFor("!!document.querySelector('.settings-workspace')");

  const tabs = await evaluate(`[...document.querySelectorAll(".settings-tabs button")].map((node) => (node.textContent || "").trim())`);
  const initialTheme = await evaluate("document.documentElement.dataset.theme || 'day'");
  await evaluate("document.querySelector('.settings-toggle-card')?.click()");
  const changedTheme = await waitFor(`(() => {
    const theme = document.documentElement.dataset.theme;
    return theme && theme !== ${JSON.stringify(initialTheme)} ? theme : "";
  })()`);
  await waitFor("!document.querySelector('.settings-toggle-card')?.disabled");
  await evaluate("document.querySelector('.settings-toggle-card')?.click()");
  const restoredTheme = await waitFor(`document.documentElement.dataset.theme === ${JSON.stringify(initialTheme)}
    ? document.documentElement.dataset.theme : ""`);

  await openTab("Banco de Dados");
  const inventory = await waitFor(`(() => {
    const storage = document.querySelectorAll(".settings-storage-grid article").length;
    const tables = document.querySelectorAll(".settings-database-card tbody tr").length;
    return storage && tables ? { storage, tables } : null;
  })()`);

  await openTab("Registros");
  const auditRows = await waitFor("document.querySelectorAll('.settings-audit tbody tr').length");

  await openTab("Admin");
  const roles = await waitFor(`(() => {
    const roles = document.querySelectorAll(".settings-role-list article").length;
    return roles ? { roles } : null;
  })()`);
  const subtabs = await evaluate(`[...document.querySelectorAll(".settings-subtabs button")].map((node) => (node.textContent || "").trim())`);
  await evaluate(`[...document.querySelectorAll(".settings-subtabs button")]
    .find((node) => (node.textContent || "").trim() === "Ações")?.click()`);
  const actions = await waitFor(`(() => {
    const capabilities = document.querySelectorAll(".settings-actions__groups input[type=checkbox]").length;
    return capabilities ? { capabilities } : null;
  })()`);
  await evaluate("document.querySelector('.settings-actions .managed-select__trigger')?.click()");
  const actionDropdownOptions = await waitFor("document.querySelectorAll('.managed-select__menu [role=option]').length");
  const actionsCapture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await fs.writeFile(actionsScreenshotPath, Buffer.from(actionsCapture.data, "base64"));
  await evaluate("document.querySelector('.settings-actions .managed-select__trigger')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))");
  await evaluate(`[...document.querySelectorAll(".settings-subtabs button")]
    .find((node) => (node.textContent || "").trim() === "Usuários")?.click()`);
  const users = await waitFor("document.querySelectorAll('.settings-user-list > article').length");
  await evaluate("document.querySelector('.settings-add-user .managed-select__trigger')?.click()");
  const userDropdownOptions = await waitFor("document.querySelectorAll('.managed-select__menu [role=option]').length");
  await evaluate("document.querySelector('.settings-add-user .managed-select__trigger')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))");
  const avatars = await waitFor(`(() => {
    const images = [...document.querySelectorAll(".settings-user-avatar img")];
    if (!images.length || images.some((image) => !image.complete)) return null;
    return {
      provided: images.length,
      loaded: images.filter((image) => image.naturalWidth > 0).length,
      fallbacks: document.querySelectorAll(".settings-user-avatar").length - images.filter((image) => image.naturalWidth > 0).length
    };
  })()`);
  const admin = { ...roles, ...actions, users, subtabs, avatars, dropdowns: { actions: actionDropdownOptions, users: userDropdownOptions } };

  const capture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await fs.writeFile(screenshotPath, Buffer.from(capture.data, "base64"));

  const result = {
    ok: JSON.stringify(home.modules) === JSON.stringify(["Atendimento", "Studio", "Configurações"])
      && home.count === "3 disponíveis"
      && JSON.stringify(tabs) === JSON.stringify(["Configurações", "Banco de Dados", "Registros", "Admin"])
      && changedTheme !== initialTheme
      && restoredTheme === initialTheme
      && inventory.storage >= 7
      && inventory.tables >= 10
      && auditRows >= 1
      && admin.roles >= 2
      && admin.users >= 1
      && admin.capabilities === 20
      && admin.avatars.provided >= 1
      && admin.avatars.loaded >= 1
      && admin.dropdowns.actions === admin.roles
      && admin.dropdowns.users === admin.roles - 1
      && JSON.stringify(admin.subtabs) === JSON.stringify(["Cargos", "Ações", "Usuários"]),
    home,
    tabs,
    theme: { initial: initialTheme, changed: changedTheme, restored: restoredTheme },
    inventory,
    auditRows,
    admin,
    screenshotPath,
    actionsScreenshotPath
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!result.ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
