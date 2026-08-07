import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./route-proof.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { masterFrontierRouteProofFromFinal } = await import(moduleUrl);

const proof = masterFrontierRouteProofFromFinal({
  route_id: "wasm-agent.avatar-chat.ui",
  evidence: [{
    id: "ev:route", kind: "route.contract", subject: "route:wasm-agent.avatar-chat.ui",
    summary: "Route resolved by the server.", detail_ref: "ev:route:detail",
  }],
  diagnostics: { performance: { schema: "master.frontier.v6.performance.v1", total_ms: 10 } },
});

assert.equal(proof.source, "server-final");
assert.equal(proof.route_id, "wasm-agent.avatar-chat.ui");
assert.equal(proof.evidence.id, "ev:route");
assert.equal(proof.performance.total_ms, 10);
assert.equal(masterFrontierRouteProofFromFinal({}), null);
