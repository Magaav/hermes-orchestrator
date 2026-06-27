import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname, "..");
const publicRoot = path.join(pluginRoot, "public");
const speechRoot = path.join(publicRoot, "modules", "speech-transcription");
const speechModuleSource = fs.readFileSync(path.join(speechRoot, "speech-transcription.js"), "utf8");

const moduleCache = new Map();
const context = vm.createContext({
  URL,
  console,
  performance,
  setTimeout,
  clearTimeout,
  queueMicrotask,
  Float32Array,
  Date,
  Error,
  Event,
  InputEvent: globalThis.InputEvent,
});

async function loadBrowserModule(filePath) {
  const resolved = path.resolve(filePath);
  const identifier = pathToFileURL(resolved).href;
  if (moduleCache.has(identifier)) return moduleCache.get(identifier);
  if (!vm.SourceTextModule) {
    throw new Error("vm.SourceTextModule is unavailable; run node with --experimental-vm-modules");
  }
  const source = fs.readFileSync(resolved, "utf8");
  const module = new vm.SourceTextModule(source, { context, identifier });
  moduleCache.set(identifier, module);
  await module.link((specifier, referencingModule) => {
    const next = new URL(specifier, referencingModule.identifier);
    return loadBrowserModule(fileURLToPath(next));
  });
  await module.evaluate();
  return module;
}

const draftModule = await loadBrowserModule(path.join(speechRoot, "transcript-draft.js"));
const speechModule = await loadBrowserModule(path.join(speechRoot, "speech-transcription.js"));

const {
  appendTranscriptSegment,
  createTranscriptDraftController,
  joinDraftAndTranscript,
  mergeTranscriptSegments,
} = draftModule.namespace;
const {
  createSpeechTranscriber,
  validateSpeechModelMetadata,
} = speechModule.namespace;

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  toggle(name, force) {
    if (force) this.values.add(name);
    else this.values.delete(name);
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor() {
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.classList = new FakeClassList();
    this.style = {
      values: {},
      setProperty: (name, value) => {
        this.style.values[name] = String(value);
      },
    };
    this.title = "";
  }

  addEventListener(type, listener) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type, listener) {
    this.listeners[type] = (this.listeners[type] || []).filter((entry) => entry !== listener);
  }

  dispatchEvent(event) {
    for (const listener of this.listeners[event.type] || []) listener(event);
    return true;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] || "";
  }
}

class FakeTextarea extends FakeElement {
  constructor(value = "") {
    super();
    this.value = value;
    this.selectionStart = value.length;
    this.selectionEnd = value.length;
  }

  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }

  focus() {
    this.focused = true;
  }
}

function makeComposer(textarea) {
  return {
    setCalls: [],
    setValue(value, options = {}) {
      this.setCalls.push({ value, options });
      textarea.value = String(value);
      const selection = Number(options.selectionStart ?? textarea.value.length);
      textarea.setSelectionRange(selection, Number(options.selectionEnd ?? selection));
      textarea.dispatchEvent({ type: "input" });
    },
  };
}

assert.deepEqual(appendTranscriptSegment(["hello"], "hello"), ["hello"]);
assert.deepEqual(appendTranscriptSegment(["hello"], "hello world"), ["hello world"]);
assert.equal(mergeTranscriptSegments(["hello"], "world"), "hello world");
assert.equal(joinDraftAndTranscript("typed", "hello"), "typed hello");
assert.equal(joinDraftAndTranscript("typed\n", "hello"), "typed\nhello");

{
  const textarea = new FakeTextarea("typed");
  const composer = makeComposer(textarea);
  const controller = createTranscriptDraftController({ textarea, composer, debounceMs: 0 });
  controller.applyTranscript({ text: "hello", final: false, immediate: true });
  assert.equal(textarea.value, "typed hello");
  textarea.value = "typed note hello";
  controller.applyTranscript({ text: "hello world", final: true, immediate: true });
  assert.equal(textarea.value, "typed note hello world");
  controller.applyTranscript({ text: "hello world", final: true, immediate: true });
  assert.equal(textarea.value, "typed note hello world", "duplicate finals must not duplicate active draft text");
  assert(composer.setCalls.length >= 2, "transcript commits must use composer.setValue");
}

{
  const metadata = JSON.parse(fs.readFileSync(path.join(speechRoot, "models", "english-v1", "metadata.json"), "utf8"));
  const validation = validateSpeechModelMetadata(metadata);
  assert.equal(validation.ok, true, validation.errors.join("\n"));
  assert.equal(metadata.networkPolicy.remoteStt, false, "metadata must forbid remote STT");
  assert.equal(metadata.networkPolicy.browserSpeechRecognitionDefault, false, "browser SpeechRecognition must not be default ASR");
  assert.equal(metadata.model.artifactStatus, undefined, "model metadata must not point at a pending placeholder artifact");
  assert(metadata.model.sizeBytes > 0 && /^[a-f0-9]{64}$/i.test(metadata.model.sha256), "model metadata must include positive size and aggregate SHA");
  assert(metadata.engine.runtimeUrl.includes("/runtime/transformers/4.2.0/"), "metadata must point at the versioned local Transformers.js runtime");
  assert(metadata.engine.onnxRuntime.wasmPaths.mjs.startsWith("/modules/speech-transcription/runtime/onnxruntime-web/"), "metadata must point at local ONNX Runtime mjs");
  assert(metadata.engine.onnxRuntime.wasmPaths.wasm.startsWith("/modules/speech-transcription/runtime/onnxruntime-web/"), "metadata must point at local ONNX Runtime wasm");
  for (const asset of metadata.assets) {
    assert(asset.url.startsWith("/modules/speech-transcription/"), `asset must be module-static: ${asset.url}`);
    const assetPath = path.join(publicRoot, asset.url.replace(/^\//, ""));
    assert(fs.existsSync(assetPath), `metadata asset is missing: ${asset.url}`);
    assert.equal(fs.statSync(assetPath).size, asset.sizeBytes, `metadata asset size mismatch: ${asset.url}`);
    const digest = crypto.createHash("sha256").update(fs.readFileSync(assetPath)).digest("hex");
    assert.equal(digest, asset.sha256, `metadata asset SHA mismatch: ${asset.url}`);
  }
  assert(metadata.assets.some((asset) => asset.url.endsWith("encoder_model_fp16.onnx")), "metadata must list Whisper encoder weights");
  assert(metadata.assets.some((asset) => asset.url.endsWith("decoder_model_merged_fp16.onnx")), "metadata must list Whisper decoder weights");
}

{
  const indexHtml = fs.readFileSync(path.join(publicRoot, "index.html"), "utf8");
  const stylesCss = fs.readFileSync(path.join(publicRoot, "styles.css"), "utf8");
  const appJs = fs.readFileSync(path.join(publicRoot, "app.js"), "utf8");
  const swJs = fs.readFileSync(path.join(publicRoot, "sw.js"), "utf8");
  assert(indexHtml.indexOf('id="agentMicButton"') > -1, "agent mic button is missing");
  assert(
    indexHtml.indexOf('id="agentMicButton"') < indexHtml.indexOf('id="agentSendButton"'),
    "agent mic button must sit immediately left of send in DOM order",
  );
  assert(stylesCss.includes("grid-template-columns: 34px minmax(0, 1fr) 34px 34px;"), "composer row must reserve a 34px mic slot");
  assert(stylesCss.includes(".agent-mic-button") && stylesCss.includes("--agent-speech-level"), "mic VAD glow styles are missing");
  assert(appJs.includes('import("./modules/speech-transcription/speech-transcription.js")'), "speech transcriber must lazy-load from mic path");
  assert(!appJs.includes("SpeechRecognition"), "production app must not use browser SpeechRecognition for ASR");
  assert(swJs.includes("/modules/speech-transcription/speech-transcription.js"), "service worker must cache lightweight speech module firmware");
  assert(!swJs.includes("/modules/speech-transcription/runtime/"), "service worker must not startup-cache ASR runtime artifacts");
  assert(!swJs.includes("encoder_model_fp16.onnx") && !swJs.includes("decoder_model_merged_fp16.onnx"), "service worker must not startup-cache ASR model weights");
  const workerJs = fs.readFileSync(path.join(speechRoot, "speech-transcription-worker.js"), "utf8");
  assert(speechModuleSource.includes("partialEveryMs: options.partialEveryMs"), "speech transcriber must pass partial cadence into the worker");
  assert(workerJs.includes("activeTranscription") && workerJs.includes("await activeTranscription"), "worker stop must wait for in-flight final ASR before idle");
  assert(workerJs.includes("if (busy) return;") && workerJs.includes("partial_promoted_to_final"), "worker must avoid overlapping ASR jobs and finalize covered partials on stop");
  assert(workerJs.includes("nextPartialAllowedAt"), "worker must throttle queued partial ASR after a partial completes");
  assert(workerJs.includes("metadata?.engine?.multilingual === true"), "English-only ASR must not force language/task generation options");
  assert(workerJs.includes("runtimeCapabilitySnapshot") && workerJs.includes("likelyAndroidWasmFallback"), "worker must expose Android/mobile ASR runtime capability diagnostics before model init");
  assert(workerJs.includes('event: "pipeline_init_failed"') && workerJs.includes("runtime }"), "worker pipeline failures must include runtime capability details");
  assert(appJs.includes('detail.type === "diagnostic" ? detail.event'), "app must preserve worker diagnostic event names instead of dropping pipeline failure details");
}

{
  let processor = null;
  let stopped = false;
  const messages = [];
  const textarea = new FakeTextarea("typed");
  const composer = makeComposer(textarea);
  const button = new FakeElement();
  const mediaDevices = {
    async getUserMedia() {
      return {
        getTracks() {
          return [{ stop() { stopped = true; } }];
        },
      };
    },
  };

  class FakeAudioNode {
    connect() {}
    disconnect() {}
  }

  class FakeAudioContext {
    constructor() {
      this.sampleRate = 16000;
      this.destination = new FakeAudioNode();
      this.state = "running";
    }

    createMediaStreamSource() {
      return new FakeAudioNode();
    }

    createScriptProcessor() {
      processor = new FakeAudioNode();
      processor.onaudioprocess = null;
      return processor;
    }

    createGain() {
      const node = new FakeAudioNode();
      node.gain = { value: 1 };
      return node;
    }

    async resume() {}

    async close() {
      this.state = "closed";
    }
  }

  class FakeWorker {
    postMessage(message) {
      messages.push(message.type);
      if (message.type === "init") {
        queueMicrotask(() => this.onmessage?.({ data: { type: "state", state: "ready", engine: "fake-local-asr" } }));
      }
      if (message.type === "audio" && !this.sentTranscript) {
        this.sentTranscript = true;
        queueMicrotask(() => this.onmessage?.({ data: { type: "transcript", text: "hello", final: false } }));
        queueMicrotask(() => this.onmessage?.({ data: { type: "transcript", text: "hello there", final: true } }));
      }
    }

    terminate() {
      this.terminated = true;
    }
  }

  const transcriber = createSpeechTranscriber({
    textarea,
    composer,
    button,
    language: "en",
    mediaDevices,
    AudioContextClass: FakeAudioContext,
    workerFactory: () => new FakeWorker(),
    transcriptDebounceMs: 0,
    idleTimeoutMs: 0,
  });
  assert.equal(transcriber.state, "idle");
  await transcriber.start();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(button.dataset.speechState, "quiet");
  processor.onaudioprocess({
    inputBuffer: {
      getChannelData() {
        return new Float32Array([0.2, 0.2, 0.2, 0.2]);
      },
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(textarea.value, "typed hello there");
  assert(messages.includes("audio"), "audio chunks must be sent to the worker");
  await transcriber.stop({ flush: false, reason: "test" });
  assert.equal(transcriber.state, "idle");
  assert.equal(stopped, true, "microphone track must stop");
  assert.equal(button.getAttribute("aria-pressed"), "false");
}

console.log("speech transcription module checks ok");
