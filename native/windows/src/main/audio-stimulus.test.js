"use strict";

const assert = require("node:assert");
const { createAudioStimulus, powershellSingleQuoted, SCHEMA } = require("./audio-stimulus");

assert.strictEqual(powershellSingleQuoted("d'água"), "'d''água'");

const calls = [];
const audio = createAudioStimulus({
  platform: "win32",
  now: (() => { let value = 1000; return () => value += 25; })(),
  execFileBounded: async (_command, args) => {
    calls.push(args.join(" "));
    if (args.join(" ").includes("GetInstalledVoices")) {
      if (args.join(" ").includes("$synth.Speak")) return { ok: true, stdout: '{"voice":"Voice B","culture":"pt-BR","gender":"Male"}', stderr: "", exitCode: 0, timedOut: false };
      return { ok: true, stdout: '{"voices":[{"name":"Voice A","culture":"pt-BR","gender":"Female","age":"Adult"},{"name":"Voice B","culture":"pt-BR","gender":"Male","age":"Adult"}]}', stderr: "", exitCode: 0, timedOut: false };
    }
    return { ok: true, stdout: "", stderr: "", exitCode: 0, timedOut: false };
  },
});

(async () => {
  const inventory = await audio.playAudioStimulus({ kind: "voice_inventory" });
  assert.strictEqual(inventory.ok, true);
  assert.strictEqual(inventory.schema, SCHEMA);
  assert.strictEqual(inventory.voices.length, 2);

  const spoken = await audio.playAudioStimulus({ kind: "speech", phrase: "Olá d'água", voice: "Voice B", rate: 2, volume: 70 });
  assert.strictEqual(spoken.ok, true);
  assert.strictEqual(spoken.selectedVoice, "Voice B");
  assert.strictEqual(spoken.selectedGender, "Male");
  assert.strictEqual(spoken.requestedVoice, "Voice B");
  assert(calls[1].includes("'Olá d''água'"));
  assert(calls[1].includes("'Voice B'"));

  const unavailable = createAudioStimulus({ platform: "linux", execFileBounded: async () => ({ ok: true }) });
  assert.strictEqual((await unavailable.playAudioStimulus({ kind: "speech" })).error, "windows_native_shell_required");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
