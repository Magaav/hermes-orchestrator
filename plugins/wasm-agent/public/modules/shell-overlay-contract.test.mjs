import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./shell-overlay-contract.js", import.meta.url), "utf8");
const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const events = [];
globalThis.CustomEvent = class CustomEvent {
  constructor(type, options) { this.type = type; this.detail = options.detail; }
};
assert.equal(module.publishAvatarChatLayer(true, { dispatchEvent: (event) => events.push(event) }), true);
assert.equal(events[0].type, "wasm-agent:shell-overlay");
assert.deepEqual(events[0].detail, { id: "wasm-agent-avatar-chat", open: true, layer: "above-widgets" });
assert.equal(module.publishAvatarChatLayer(false, { dispatchEvent: (event) => events.push(event) }), true);
assert.equal(events[1].detail.open, false);

console.log("shell overlay layer contract tests passed");
