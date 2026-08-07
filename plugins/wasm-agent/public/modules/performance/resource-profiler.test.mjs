import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./resource-profiler.js", import.meta.url), "utf8");
const { installResourceProfiler } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    if (this === null || (typeof this !== "object" && typeof this !== "function")) return `native:${this}`;
    this.listeners.set(type, listener);
    return undefined;
  }

  removeEventListener(type, listener) {
    if (this === null || (typeof this !== "object" && typeof this !== "function")) return `native:${this}`;
    if (this.listeners.get(type) === listener) this.listeners.delete(type);
    return undefined;
  }
}

const windowRef = {
  setTimeout() { return 1; },
  setInterval() { return 2; },
  requestAnimationFrame() { return 3; },
};
let clock = 0;
const profiler = installResourceProfiler({
  windowRef,
  documentRef: {},
  EventTargetCtor: FakeEventTarget,
  performanceRef: { now: () => ++clock },
});

const target = new FakeEventTarget();
let calls = 0;
function listener() { calls += 1; }
target.addEventListener("open", listener);
target.listeners.get("open")();
assert.equal(calls, 1);
assert.equal(profiler.snapshot().entry_count, 1);
target.removeEventListener("open", listener);
assert.equal(target.listeners.has("open"), false);

assert.equal(FakeEventTarget.prototype.addEventListener.call(7, "open", listener), "native:7");
assert.equal(FakeEventTarget.prototype.removeEventListener.call(7, "open", listener), "native:7");
assert.equal(installResourceProfiler({ windowRef, EventTargetCtor: FakeEventTarget }), profiler);

console.log("resource profiler listener contract tests passed");
