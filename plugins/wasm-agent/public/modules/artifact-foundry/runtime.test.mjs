import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const root = new URL("./", import.meta.url);
const wasm = await fs.readFile(new URL("./artifact_generator.wasm", root));
const context = vm.createContext({
  ArrayBuffer,
  DataView,
  Error,
  Map,
  Math,
  RangeError,
  Response,
  Set,
  TextEncoder,
  TypeError,
  Uint8Array,
  Uint32Array,
  URL,
  WebAssembly,
  crypto: webcrypto,
  performance,
  fetch: async (url) => String(url).includes("artifact_generator.wasm")
    ? new Response(wasm, { headers: { "content-type": "application/wasm" } })
    : new Response("not found", { status: 404 })
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

const runtime = (await load("runtime.js")).namespace;
const recipe = (await load("recipe.js")).namespace;
const seed = new Uint8Array(await fs.readFile(new URL("./stars-shells.seed.txt", import.meta.url))).slice();

assert.equal(recipe.estimateRecipe({ generator: recipe.STARS_SHELLS_GENERATOR, seed }).bounded, true);
const result = await runtime.generateArtifact({
  generator: recipe.STARS_SHELLS_GENERATOR,
  seed,
  parameters: { maxRounds: 8 }
});
assert.equal(result.receipt.outputBytes, 4596880);
assert.equal(result.receipt.outputSha256, "ae23392ad473718e2196e525a4355af20cdbd57bbb5dc3e85a8719b62552784d");
assert.equal(result.receipt.verified, true);
await fs.mkdir(new URL("../../../../../reports/context/latest/", import.meta.url), { recursive: true });
await fs.writeFile(
  new URL("../../../../../reports/context/latest/artifact-recipe-result.json", import.meta.url),
  `${JSON.stringify({
    status: "pass",
    promiseId: "artifact-recipe-exact-vector",
    claim: "The pinned browser-WASM recipe regenerates the canonical Stars/Shells artifact byte-exactly.",
    durationMs: result.receipt.durationMs,
    evidence: ["plugins/wasm-agent/public/modules/artifact-foundry/artifact.json"],
    summary: `${result.receipt.outputBytes} bytes sha256=${result.receipt.outputSha256}`,
    failureClass: null,
    nextSuggestedSteps: []
  }, null, 2)}\n`
);
console.log(JSON.stringify(result.receipt));
