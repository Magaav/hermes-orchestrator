import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./target.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const {
  defaultAgentSelectionTarget,
  normalizeAgentSelectionPreference,
} = await import(moduleUrl);

const contract = {
  masterTargetId: "__target:master_frontier__",
  frontierNodeId: "frontier",
};

assert.equal(defaultAgentSelectionTarget({ ...contract, isAdmin: true }), contract.masterTargetId);
assert.equal(defaultAgentSelectionTarget({ ...contract, isAdmin: false }), contract.frontierNodeId);
assert.equal(normalizeAgentSelectionPreference("frontier", { ...contract, isAdmin: true }), contract.masterTargetId);
assert.equal(normalizeAgentSelectionPreference("frontier", { ...contract, isAdmin: false }), contract.frontierNodeId);
assert.equal(normalizeAgentSelectionPreference("custom-node", { ...contract, isAdmin: true }), "custom-node");
