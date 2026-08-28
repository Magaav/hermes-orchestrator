"use strict";

const assert = require("node:assert");
const { normalizeEndpointId, powershellSetDefaultScript, run, validEndpointId } = require("./windows-audio-default");

const pnpId = "SWD\\MMDEVAPI\\{0.0.1.00000000}.{5E237FF3-E2F8-470F-A426-0BB191EDEF9A}";
const endpointId = "{0.0.1.00000000}.{5E237FF3-E2F8-470F-A426-0BB191EDEF9A}";
assert.strictEqual(normalizeEndpointId(pnpId), endpointId);
assert.strictEqual(validEndpointId(pnpId, "capture"), true);
assert.strictEqual(validEndpointId("{0.0.0.00000000}.{5E237FF3-E2F8-470F-A426-0BB191EDEF9A}", "render"), true);

const script = powershellSetDefaultScript({ instanceId: pnpId, expectedName: "CABLE Output (VB-Audio Virtual Cable)", dryRun: false });
assert(script.includes("SetDefaultEndpoint"));
assert(script.includes("F8679F50-850A-41CF-9C72-430F290290C8"));
assert(script.includes("audio_default_verification_failed"));
assert(script.includes("Get-PnpDevice -InstanceId"));
assert(script.includes("audio_endpoint_name_mismatch"));
assert(script.includes("$dryRun = $false"));
assert(script.includes("$source = @'\nusing System;"), "PowerShell here-string header must end its line");

(async () => {
  const phases = [];
  const result = await run({ args: { instanceId: pnpId, expectedName: "CABLE Output" }, markPhase: (phase) => phases.push(phase) }, {
    platform: "win32",
    executeSetDefault: async () => ({ ok: true, stdout: JSON.stringify({ endpointId, observedEndpointId: endpointId, name: "CABLE Output", status: "OK", changed: true, roles: ["console", "multimedia", "communications"] }) }),
  });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.changed, true);
  assert.deepStrictEqual(phases, ["audio_default_precondition_started", "audio_default_change_complete"]);
  const invalid = await run({ args: { instanceId: "render-device" } }, { platform: "win32", executeSetDefault: async () => { throw new Error("must not execute"); } });
  assert.strictEqual(invalid.failureClassification, "invalid_capture_endpoint_id");
  console.log("windows audio default tests: PASS");
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
