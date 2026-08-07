import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const root = new URL("./", import.meta.url);
const wasmBytes = await fs.readFile(new URL("./asolaria_tribit.wasm", root));
const manifest = JSON.parse(await fs.readFile(new URL("./artifact.json", root), "utf8"));
const context = vm.createContext({
  Date,
  Math,
  Response,
  TextEncoder,
  TypeError,
  Uint8Array,
  URL,
  WebAssembly,
  crypto: webcrypto,
  fetch: async (url) => {
    const path = String(url);
    if (path.endsWith("artifact.json")) return new Response(JSON.stringify(manifest));
    if (path.endsWith("asolaria_tribit.wasm")) return new Response(wasmBytes);
    return new Response("not found", { status: 404 });
  }
});
const cache = new Map();

async function load(name) {
  if (cache.has(name)) return cache.get(name);
  const source = await fs.readFile(new URL(name, root), "utf8");
  const module = new vm.SourceTextModule(source, {
    context,
    identifier: name,
    initializeImportMeta(meta) {
      meta.url = new URL(name, root).href;
    }
  });
  cache.set(name, module);
  await module.link((specifier) => load(specifier.replace("./", "")));
  await module.evaluate();
  return module;
}

const adapter = (await load("qa-adapter.js")).namespace;
const result = await adapter.evaluateAsolariaBinaryQuestions(
  adapter.arithmeticBinaryBenchmark()
);

assert.equal(result.sampleSize, 360);
assert.equal(result.calibration.train.n, 180);
assert.equal(result.calibration.holdout.n, 180);
assert.equal(result.extractor.id, "receipt-byte-0-lsb-v1");
assert.equal(result.extractor.predeclared, true);
assert.equal(result.calibration.holdout.direct.correct, 99);
assert.equal(result.calibration.holdout.inverted.correct, 81);
assert.equal(result.baselines.majority.correct, 90);
assert.equal(result.decision.addsValue, false);
assert.equal(result.decision.route, "no-added-value");
assert.equal(result.decision.authority, "none");
assert.match(adapter.qaEvaluationProjection(result), /route=no-added-value/);

const receipt = { bytes: new Uint8Array([7]) };
assert.equal(adapter.predictionFromReceipt(receipt), 1);
assert.throws(() => adapter.predictionFromReceipt({ bytes: new Uint8Array() }), /required/);
await assert.rejects(
  adapter.evaluateAsolariaBinaryQuestions([{ id: "missing", expected: 1 }]),
  /question is required/
);

console.log(JSON.stringify({
  schema: result.schema,
  direct: result.calibration.holdout.direct.accuracy,
  inverted: result.calibration.holdout.inverted.accuracy,
  majority: result.baselines.majority.accuracy,
  decision: result.decision
}));
