#!/usr/bin/env node
"use strict";

const http = require("http");
const WebSocket = require("ws");
const { execFile } = require("child_process");
const { promisify } = require("util");
const execFileAsync = promisify(execFile);

const endpoint = String(process.argv[2] || "http://127.0.0.1:9222").replace(/\/$/, "");
const targetId = String(process.argv[3] || "");
const action = String(process.argv[4] || "status");

function getJson(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 5000 }, (response) => {
      let body = "";
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => { try { resolve(JSON.parse(body)); } catch (error) { reject(error); } });
    });
    request.on("timeout", () => request.destroy(new Error("cdp_timeout")));
    request.on("error", reject);
  });
}

async function run() {
  const targets = await getJson(`${endpoint}/json/list`);
  const page = targets.find((item) => item.id === targetId && item.type === "page");
  if (!page) throw new Error("target_missing");
  const socket = new WebSocket(page.webSocketDebuggerUrl, { handshakeTimeout: 5000 });
  let sequence = 0;
  const pending = new Map();
  socket.on("message", (raw) => {
    const message = JSON.parse(String(raw));
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    if (message.error) waiter.reject(new Error(message.error.message));
    else waiter.resolve(message.result);
  });
  await new Promise((resolve, reject) => { socket.once("open", resolve); socket.once("error", reject); });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  if (["direct-start", "prove-two-voices"].includes(action)) {
    await call("Browser.setPermission", { origin: "https://wa.colmeio.com", permission: { name: "microphone" }, setting: "granted" });
    const startExpression = `(async()=>{document.querySelector('#agentAvatarButton')?.click();const {createSpeechTranscriber}=await import('/modules/speech-transcription/speech-transcription.js');await window.__anamnesiaProofTranscriber?.destroy?.();const proof=window.__anamnesiaSpeechProof={state:'created',transcripts:[],diagnostics:[],errors:[]};const t=createSpeechTranscriber({textarea:document.querySelector('#agentInput'),button:document.querySelector('#agentMicButton'),language:'en',autoBindButton:false,audioConstraints:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},onStateChange:x=>{proof.state=x.state;proof.stateDetail=x},onTranscript:x=>{proof.transcripts.push(x);proof.lastTranscript=x},onDiagnostic:x=>proof.diagnostics.push(x),onError:x=>proof.errors.push(String(x?.error||x))});window.__anamnesiaProofTranscriber=t;proof.started=await t.start();return proof})()`;
    await call("Runtime.evaluate", { expression: startExpression, awaitPromise: true, returnByValue: true, userGesture: true });
    if (action === "prove-two-voices") {
      const snapshotExpression = `(()=>{const p=window.__anamnesiaSpeechProof,i=document.querySelector('#agentInput');return {state:p?.state||'',input:String(i?.value||''),lastTranscript:p?.lastTranscript||null,transcripts:p?.transcripts||[],diagnostics:p?.diagnostics?.slice(-20)||[],errors:p?.errors||[]}})()`;
      const waitReady = async () => {
        for (let attempt = 0; attempt < 60; attempt += 1) {
          const ready = await call("Runtime.evaluate", { expression: `Boolean(window.__anamnesiaSpeechProof?.diagnostics?.some(x=>x.type==='ready'))`, returnByValue: true });
          if (ready?.result?.value === true) return;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        throw new Error("speech_pipeline_ready_timeout");
      };
      const play = async (voice, label, phrase) => execFileAsync("python3", ["tools/windows/play-audio-stimulus.py", "--origin", "https://wa.colmeio.com", "--kind", "speech", "--voice", voice, "--rate", "-1", "--label", label, "--phrase", phrase], { cwd: process.cwd(), timeout: 60000, maxBuffer: 1024 * 1024 });
      const fixtures = [];
      const davidPhrase = "Anamnesia voice one remembers the silver river.";
      await waitReady();
      const david = await play("Microsoft David Desktop", "anamnesia-v1-david", davidPhrase);
      await new Promise((resolve) => setTimeout(resolve, 9000));
      const davidState = await call("Runtime.evaluate", { expression: snapshotExpression, returnByValue: true });
      fixtures.push({ voice: "Microsoft David Desktop", expected: davidPhrase, stimulus: JSON.parse(david.stdout), observed: davidState?.result?.value || null });
      await call("Runtime.evaluate", { expression: startExpression, awaitPromise: true, returnByValue: true, userGesture: true });
      await waitReady();
      const ziraPhrase = "Anamnesia voice two remembers the golden forest.";
      const zira = await play("Microsoft Zira Desktop", "anamnesia-v1-zira", ziraPhrase);
      await new Promise((resolve) => setTimeout(resolve, 9000));
      const ziraState = await call("Runtime.evaluate", { expression: snapshotExpression, returnByValue: true });
      fixtures.push({ voice: "Microsoft Zira Desktop", expected: ziraPhrase, stimulus: JSON.parse(zira.stdout), observed: ziraState?.result?.value || null });
      await call("Runtime.evaluate", { expression: `(async()=>{await window.__anamnesiaProofTranscriber?.stop?.();return true})()`, awaitPromise: true });
      socket.close();
      process.stdout.write(`${JSON.stringify({ ok: true, action, fixtures }, null, 2)}\n`);
      return;
    }
  }
  if (action === "direct-stop") {
    await call("Runtime.evaluate", { expression: `(async()=>{await window.__anamnesiaProofTranscriber?.stop?.();return true})()`, awaitPromise: true, userGesture: true });
  }
  if (action === "click") {
    await call("Browser.setPermission", { origin: "https://wa.colmeio.com", permission: { name: "microphone" }, setting: "granted" });
    await call("Runtime.evaluate", { expression: `(()=>{const m=document.querySelector('#agentMicButton'),r=m?.getBoundingClientRect();if(!(r?.width&&r?.height))document.querySelector('#agentAvatarButton')?.click();return true})()`, userGesture: true });
    await new Promise((resolve) => setTimeout(resolve, 250));
    await call("Runtime.evaluate", { expression: "document.querySelector('#agentMicButton')?.click()", userGesture: true });
  }
  const expression = `(async()=>{const m=document.querySelector('#agentMicButton'),i=document.querySelector('#agentInput'),s=m?getComputedStyle(m):null,r=m?.getBoundingClientRect(),p=await navigator.permissions.query({name:'microphone'}),d=await navigator.mediaDevices.enumerateDevices(),proof=window.__anamnesiaSpeechProof;return {href:location.href,visible:!!(m&&s.display!=='none'&&s.visibility!=='hidden'&&r.width&&r.height),mic:{aria:m?.getAttribute('aria-label')||'',title:m?.title||'',className:m?.className||'',disabled:!!m?.disabled},input:String(i?.value||''),permission:p.state,audioInputs:d.filter(x=>x.kind==='audioinput').map(x=>({label:x.label,deviceId:x.deviceId?'present':''})),proof:proof?{state:proof.state,started:proof.started,lastTranscript:proof.lastTranscript||null,transcriptCount:proof.transcripts.length,diagnostics:proof.diagnostics.slice(-12),errors:proof.errors.slice(-6)}:null}})()`;
  let state = null;
  for (let attempt = 0; attempt < (["click", "direct-start"].includes(action) ? 120 : 1); attempt += 1) {
    const evaluated = await call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    state = evaluated?.result?.value || null;
    if (!["click", "direct-start"].includes(action) || /stop voice|listening|transcribing/i.test(`${state?.mic?.aria} ${state?.mic?.title} ${state?.mic?.className}`) || ["listening", "quiet", "transcribing"].includes(state?.proof?.state)) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  socket.close();
  process.stdout.write(`${JSON.stringify({ ok: true, action, state }, null, 2)}\n`);
}

run().catch((error) => { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 2; });
