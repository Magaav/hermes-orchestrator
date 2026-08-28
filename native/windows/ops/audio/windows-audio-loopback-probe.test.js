"use strict";

const assert = require("node:assert");
const {
  MAX_ENDPOINTS,
  classifyInventory,
  powershellInventoryScript,
  run,
} = require("./windows-audio-loopback-probe");

const ready = classifyInventory({
  source: "fixture",
  defaultRecordingEndpointId: "{0.0.1.00000000}.y",
  endpoints: [
    { name: "Speakers", status: "OK", flow: "render", instanceId: "SWD\\MMDEVAPI\\{0.0.0.00000000}.x" },
    { name: "Stereo Mix (Realtek(R) Audio)", status: "OK", flow: "capture", instanceId: "SWD\\MMDEVAPI\\{0.0.1.00000000}.y" },
  ],
});
assert.strictEqual(ready.ok, true);
assert.strictEqual(ready.failureClassification, "pass");
assert.strictEqual(ready.defaultMatchesLoopback, true);
assert.strictEqual(ready.readyLoopbackCount, 1);

const availableNotDefault = classifyInventory({
  legacyDefaultRecordingDevice: "Microphone Array",
  endpoints: [
    { name: "Microphone Array", status: "OK", flow: "capture" },
    { name: "CABLE Output (VB-Audio Virtual Cable)", status: "OK", flow: "capture" },
    { name: "CABLE Input (VB-Audio Virtual Cable)", status: "OK", flow: "render" },
  ],
});
assert.strictEqual(availableNotDefault.ok, false);
assert.strictEqual(availableNotDefault.failureClassification, "audio_loopback_not_default");
assert.strictEqual(availableNotDefault.loopbackCandidateCount, 1, "render-side CABLE Input must not be classified as a capture loopback");

const disabled = classifyInventory({
  endpoints: [{ name: "Mixagem estéreo", status: "Error", flow: "capture" }],
});
assert.strictEqual(disabled.failureClassification, "audio_loopback_device_disabled");

const missing = classifyInventory({
  endpoints: Array.from({ length: MAX_ENDPOINTS + 5 }, (_, index) => ({ name: `Microphone ${index}`, status: "OK", flow: "capture" })),
});
assert.strictEqual(missing.failureClassification, "audio_loopback_device_missing");
assert.strictEqual(missing.endpointCount, MAX_ENDPOINTS, "inventory output must stay bounded");

const script = powershellInventoryScript();
assert(script.includes("Get-PnpDevice -Class AudioEndpoint"));
assert(script.includes("Get-CimInstance Win32_PnPEntity"));
assert(script.includes("GetDefaultAudioEndpoint"));
assert(script.includes("$defaultRenderEndpointId = [AudioDefaultReader]::GetId(0)"));
assert(script.includes("$coreAudio = @'\nusing System;"));
assert(script.includes(`Select-Object -First ${MAX_ENDPOINTS}`));
assert(!script.includes("context.args"), "the fixed PowerShell query must not interpolate operation inputs");

(async () => {
  const phases = [];
  const live = await run({ markPhase: (phase) => phases.push(phase) }, {
    platform: "win32",
    executeInventory: async () => ({ ok: true, stdout: JSON.stringify({ endpoints: [{ name: "Stereo Mix", status: "OK", flow: "capture", instanceId: "SWD\\MMDEVAPI\\{0.0.1.00000000}.y" }], defaultRecordingEndpointId: "{0.0.1.00000000}.y" }) }),
  });
  assert.strictEqual(live.ok, true);
  assert.deepStrictEqual(phases, ["audio_endpoint_inventory_started", "audio_endpoint_inventory_complete"]);
  console.log("windows audio loopback probe tests: PASS");
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
