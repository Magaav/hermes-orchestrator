import assert from "node:assert/strict";
import fs from "node:fs/promises";
import vm from "node:vm";

const source = await fs.readFile(new URL("./structure.js", import.meta.url), "utf8");
const module = new vm.SourceTextModule(source, {
  context: vm.createContext({ Object }),
  identifier: "asolaria-structure"
});
await module.link(() => {
  throw new Error("ASOLARIA structure module has no imports");
});
await module.evaluate();

const result = module.namespace.inspectAsolariaLattice();
assert.equal(result.states, 81);
assert.equal(result.centre.count, 1);
assert.deepEqual([...result.centre.coordinates], [1, 1, 1, 1]);
assert.equal(result.thirds.ac.states, 27);
assert.equal(result.thirds.ac.fraction, 1 / 3);
assert.equal(result.thirds.spatialCells, 27);
assert.equal(result.thirds.solid.cells, 9);
assert.equal(result.thirds.solid.fraction, 1 / 3);
assert.equal(result.thirds.translucent.cells, 18);
assert.equal(result.thirds.translucent.fraction, 2 / 3);
assert.match(module.namespace.latticeProjection(result), /ac=27/);

console.log("asolaria structure tests passed");
