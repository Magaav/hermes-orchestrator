#!/usr/bin/env node
// Bypass Caddy while preserving the authenticated production Studio handler.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const source = path.resolve(process.argv[2] || "media/visao_before1.jpeg");
const targets = await fetch(`${cdpOrigin}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page" && item.url === "https://visao.colmeio.com/");
if (!target) throw new Error("No authenticated Visão browser target is available.");

const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let requestID = 0;
socket.on("message", (wire) => {
  const message = JSON.parse(String(wire));
  if (!message.id || !pending.has(message.id)) return;
  const current = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) current.reject(new Error(message.error.message || "CDP command failed"));
  else current.resolve(message.result || {});
});
await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

const cookieResult = await command("Network.getAllCookies");
socket.close();
const session = cookieResult.cookies?.find((cookie) =>
  cookie.name === "visao_session" && String(cookie.domain || "").endsWith("visao.colmeio.com")
);
if (!session?.value) throw new Error("The authenticated Visão session cookie is unavailable.");

const image = await fs.readFile(source);
const response = await fetch("http://127.0.0.1:18083/api/studio/clean", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Cookie": `visao_session=${session.value}`,
    "Origin": "http://127.0.0.1:18083",
  },
  body: JSON.stringify({
    wire_version: 2,
    cloud_consent: true,
    watermark_authorized: false,
    media_type: "image/jpeg",
    image_base64: image.toString("base64"),
  }),
});
if (!response.body) throw new Error(`Direct Studio response has no body: HTTP ${response.status}`);

const reader = response.body.getReader();
const decoder = new TextDecoder();
const events = {};
let resultChars = 0;
let terminal = "";
let errorCode = "";
let buffer = "";
while (true) {
  const { value, done } = await reader.read();
  buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
  const lines = buffer.split("\n");
  buffer = done ? "" : lines.pop() || "";
  for (const line of lines) {
    if (!line.trim()) continue;
    const frame = JSON.parse(line);
    const event = String(frame.event || "");
    events[event] = (events[event] || 0) + 1;
    if (event === "result-chunk") resultChars += String(frame.detail?.data || "").length;
    if (event === "complete" || event === "error") terminal = event;
    if (event === "error") errorCode = String(frame.detail?.code || "");
  }
  if (done) break;
}
process.stdout.write(`${JSON.stringify({
  ok: response.ok && terminal === "complete" && resultChars > 0,
  status: response.status,
  contentType: response.headers.get("content-type"),
  events,
  resultChars,
  terminal,
  errorCode,
})}\n`);
if (!response.ok || terminal !== "complete" || !resultChars) process.exitCode = 1;
