"use strict";
const assert = require("node:assert");
const { classifySignal, powershellSignalScript, run } = require("./windows-audio-signal-probe");
assert.strictEqual(classifySignal({ peak: 0.2, rms: 0.03 }).signalPresent, true);
assert.strictEqual(classifySignal({ peak: 0, rms: 0 }).failureClassification, "audio_loopback_silent");
const script = powershellSignalScript({ phrase: "test", voice: "voice", captureMs: 4000 });
assert(script.includes("waveInOpen")); assert(script.includes("SpeechSynthesizer")); assert(!script.includes("context.args"));
(async()=>{const result=await run({args:{},markPhase(){}},{platform:"win32",execute:async()=>({ok:true,stdout:JSON.stringify({peak:.2,rms:.02,capturedSeconds:2,voice:"David"})})});assert.strictEqual(result.ok,true);console.log("windows audio signal probe tests: PASS")})().catch(e=>{console.error(e);process.exit(1)});
