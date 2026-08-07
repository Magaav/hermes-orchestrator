#!/usr/bin/env node
"use strict";

const http = require("http");
const WebSocket = require("ws");

const endpoint = String(process.argv[2] || "http://127.0.0.1:9222").replace(/\/$/, "");
const input = JSON.parse(process.argv[3] || "{}");

function getJson(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 3000 }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    });
    request.on("timeout", () => request.destroy(new Error("cdp_timeout")));
    request.on("error", reject);
  });
}

function expressionFor(command) {
  const operation = String(command.operation || "snapshot");
  const ref = Number(command.ref || 0);
  const value = JSON.stringify(String(command.value || ""));
  const key = JSON.stringify(String(command.key || ""));
  return `(() => {
    const operation = ${JSON.stringify(operation)};
    const candidates = [...document.querySelectorAll('a,button,input,textarea,select,[role],[tabindex]')]
      .filter((node) => node.getClientRects().length && !node.disabled).slice(0, 160);
    const node = candidates[${Math.max(0, ref - 1)}] || null;
    if (operation === 'click') { if (!node) return {ok:false,code:'browser_ref_missing'}; node.click(); }
    if (operation === 'type') {
      if (!node || !('value' in node)) return {ok:false,code:'browser_ref_not_editable'};
      node.focus(); node.value = ${value}; node.dispatchEvent(new Event('input',{bubbles:true})); node.dispatchEvent(new Event('change',{bubbles:true}));
    }
    if (operation === 'key') {
      const target = node || document.activeElement || document.body; target.focus?.();
      target.dispatchEvent(new KeyboardEvent('keydown',{key:${key},bubbles:true}));
      target.dispatchEvent(new KeyboardEvent('keyup',{key:${key},bubbles:true}));
    }
    const items = candidates.slice(0, 80).map((item, index) => ({
      ref:index+1, role:item.getAttribute('role') || item.tagName.toLowerCase(),
      name:String(item.getAttribute('aria-label') || item.innerText || item.value || item.getAttribute('title') || '').trim().replace(/\\s+/g,' ').slice(0,180),
      href:item.href ? String(item.href).slice(0,500) : undefined
    }));
    return {ok:true,title:document.title.slice(0,240),url:location.href,items,text:String(document.body?.innerText || '').trim().replace(/\\n{3,}/g,'\\n\\n').slice(0,12000)};
  })()`;
}

async function run() {
  const targets = await getJson(`${endpoint}/json/list`);
  const pages = targets.filter((target) => target.type === "page" && target.webSocketDebuggerUrl);
  const targetUrl = String(input.target_url || "");
  const page = (targetUrl && pages.find((target) => String(target.url || "").startsWith(targetUrl)))
    || pages.find((target) => !/^(?:devtools|chrome|edge):/.test(String(target.url || "")))
    || pages[0];
  if (!page) return { ok: false, code: "browser_page_missing" };
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(page.webSocketDebuggerUrl, { handshakeTimeout: 3000 });
    const timer = setTimeout(() => { socket.terminate(); reject(new Error("cdp_operation_timeout")); }, 6000);
    let nextId = 1;
    const pending = new Map();
    const eventWaiters = new Map();
    const send = (method, params = {}) => new Promise((res, rej) => {
      const id = nextId++; pending.set(id, { res, rej }); socket.send(JSON.stringify({ id, method, params }));
    });
    socket.on("message", (raw) => {
      const message = JSON.parse(String(raw));
      if (message.method && eventWaiters.has(message.method)) {
        const waiter = eventWaiters.get(message.method); eventWaiters.delete(message.method); waiter(message.params || {}); return;
      }
      const entry = pending.get(message.id); if (!entry) return;
      pending.delete(message.id); message.error ? entry.rej(new Error(message.error.message)) : entry.res(message.result || {});
    });
    socket.on("open", async () => {
      try {
        if (input.operation === "navigate") {
          await send("Page.enable");
          const loaded = new Promise((res) => eventWaiters.set("Page.loadEventFired", res));
          await send("Page.navigate", { url: String(input.url || "") });
          await loaded;
        }
        const result = await send("Runtime.evaluate", { expression: expressionFor(input), returnByValue: true, awaitPromise: true });
        clearTimeout(timer); socket.close(); resolve(result.result?.value || { ok:false, code:"browser_snapshot_missing" });
      } catch (error) { clearTimeout(timer); socket.close(); reject(error); }
    });
    socket.on("error", (error) => { clearTimeout(timer); reject(error); });
  });
}

run().then((value) => process.stdout.write(`${JSON.stringify(value)}\n`)).catch((error) => {
  process.stdout.write(`${JSON.stringify({ok:false,code:'browser_cdp_unavailable',message:String(error.message || error)})}\n`); process.exitCode = 2;
});
