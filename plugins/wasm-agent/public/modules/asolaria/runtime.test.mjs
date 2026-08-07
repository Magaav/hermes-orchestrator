import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { createHash, webcrypto } from "node:crypto";
import vm from "node:vm";

const wasmBytes = await fs.readFile(new URL("./asolaria_tribit.wasm", import.meta.url));
const { instance } = await WebAssembly.instantiate(wasmBytes, {});
const exports = instance.exports;
const input = new TextEncoder().encode("same input");
new Uint8Array(exports.memory.buffer).set(input, exports.input_ptr());
assert.equal(exports.make_seed(input.length), 27);
const first = new Uint8Array(
  exports.memory.buffer,
  exports.output_ptr(),
  exports.seed_len()
).slice();
assert.equal(exports.make_seed(input.length), 27);
const second = new Uint8Array(
  exports.memory.buffer,
  exports.output_ptr(),
  exports.seed_len()
).slice();
assert.deepEqual(first, second, "same input must produce the same receipt");
assert.equal(first.length, 3078);
assert.equal(exports.chain_intact(), 1);
assert.equal(exports.hidden_holes(), 0);
assert.equal(exports.prism_roundtrip_exact(), 1);

const manifest = JSON.parse(await fs.readFile(new URL("./artifact.json", import.meta.url), "utf8"));
assert.equal(manifest.runtime.receiptBytes, first.length);
assert.equal(manifest.litert.compatible, false);
assert.equal(manifest.runtime.kind, "deterministic-wasm");
assert.equal(createHash("sha256").update(wasmBytes).digest("hex"), manifest.runtime.sha256);

const runtimeSource = await fs.readFile(new URL("./runtime.js", import.meta.url), "utf8");
const browserFetch = async (url) => {
  const path = String(url);
  if (path.endsWith("artifact.json")) {
    return new Response(JSON.stringify(manifest), {
      headers: { "content-type": "application/json" }
    });
  }
  if (path.endsWith("asolaria_tribit.wasm")) return new Response(wasmBytes);
  return new Response("not found", { status: 404 });
};
const runtimeModule = new vm.SourceTextModule(runtimeSource, {
  context: vm.createContext({
    Uint8Array,
    WebAssembly,
    URL,
    Response,
    fetch: browserFetch,
    crypto: webcrypto
  }),
  identifier: "asolaria-runtime",
  initializeImportMeta(meta) {
    meta.url = new URL("./runtime.js", import.meta.url).href;
  }
});
await runtimeModule.link(() => {
  throw new Error("ASOLARIA runtime has no module imports");
});
await runtimeModule.evaluate();
const runtime = runtimeModule.namespace;
const wrapped = await runtime.makeAsolariaReceipt(input, { name: "same-input.txt" });
assert.equal(wrapped.receipt.bytes, 3078);
assert.equal(wrapped.receipt.cellsReached, 27);
assert.equal(wrapped.receipt.chainIntact, true);
assert.equal(wrapped.receipt.hiddenHoles, 0);
assert.equal(wrapped.receipt.prismRoundtripExact, true);
assert.equal(wrapped.engine.litertCompatible, false);
assert.match(runtime.receiptProjection(wrapped), /cells=27\/27/);

const receiptVectors = [
  ["", "a91acae4ae2d1418db50095702096f5c81761fc422637972942f325465b2e730"],
  ["a", "2b467e4cca4db694b9e172ea2346da8c873f501227dd9cb8c3b8234622d40530"],
  ["abc", "907d5cec4b56072e7612b7834b377d8d4e2c9d0c4d44b2aac2b1ce379112f2c6"],
  ["the quick brown fox", "839a079a56bb7a6db742180520cbe36fb9afafe6d4ad1e4e4f9313588c0807a6"],
  ["ASOLARIA", "27d7eddf5c216f289ee6416ca29285e67b5f3424650fe84cbaecb0c7c2202c87"],
  [new Uint8Array(256).map((_, index) => index), "fe0797f2a33dc5d4256588b04a12ed9e83252f51f5216712beb2bb0a9d7df3f7"]
];
for (const [fixture, expectedReceiptSha] of receiptVectors) {
  const fixtureBytes = fixture instanceof Uint8Array ? fixture : new TextEncoder().encode(fixture);
  const measured = await runtime.makeAsolariaReceipt(fixtureBytes, { name: "upstream-vector" });
  assert.equal(createHash("sha256").update(measured.bytes).digest("hex"), expectedReceiptSha);
  assert.equal(measured.receipt.cellsReached, 27);
  assert.equal(measured.receipt.count.declared, 38);
  assert.equal(measured.receipt.count.produced, 38);
  assert.equal(measured.receipt.count.withheld, 0);
}

const registry = await fs.readFile(new URL("../app-registry.js", import.meta.url), "utf8");
const moduleIndex = await fs.readFile(new URL("../index.js", import.meta.url), "utf8");
const entry = await fs.readFile(new URL("./asolaria.entry.js", import.meta.url), "utf8");
const styles = await fs.readFile(new URL("./asolaria.css", import.meta.url), "utf8");
assert.match(registry, /id: "asolaria"/);
assert.match(registry, /home:\s*\["asolaria"\]/);
assert.match(registry, /"batch-cleaner", "asolaria"/);
assert.match(moduleIndex, /artifactSchema: "hermes\.wasm_agent\.asolaria\.artifact\.v1"/);
assert.match(moduleIndex, /status: "experimental; no decision authority"/);
assert.match(entry, /classList\.add\("asolaria-scroll-host"\)/);
assert.match(entry, /classList\.add\("asolaria-widget"\)/);
assert.match(styles, /\.asolaria-scroll-host[\s\S]*overflow:\s*auto/);

console.log("asolaria runtime tests passed");
