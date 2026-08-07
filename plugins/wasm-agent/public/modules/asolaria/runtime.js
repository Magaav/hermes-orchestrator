export const ASOLARIA_RECEIPT_SCHEMA = "hermes.wasm_agent.asolaria.receipt.v1";
export const ASOLARIA_INSPECTION_SCHEMA = "hermes.wasm_agent.asolaria.inspection.v1";

const MANIFEST_URL = new URL("./artifact.json", import.meta.url);
let runtimePromise;

function hex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256(bytes) {
  if (!globalThis.crypto?.subtle) return null;
  return hex(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)));
}

function decodeCount(value) {
  const packed = Number(value) >>> 0;
  return {
    declared: (packed >>> 20) & 0x3ff,
    produced: (packed >>> 10) & 0x3ff,
    withheld: packed & 0x3ff
  };
}

function requireExport(exports, name) {
  if (typeof exports?.[name] !== "function") {
    throw new Error(`ASOLARIA WASM export is missing: ${name}`);
  }
}

async function instantiate() {
  const manifestResponse = await fetch(MANIFEST_URL, { cache: "no-cache" });
  if (!manifestResponse.ok) throw new Error(`ASOLARIA manifest failed: ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  const wasmUrl = new URL(manifest.runtime.wasm, MANIFEST_URL);
  const wasmResponse = await fetch(wasmUrl, { cache: "force-cache" });
  if (!wasmResponse.ok) throw new Error(`ASOLARIA WASM failed: ${wasmResponse.status}`);
  const bytes = new Uint8Array(await wasmResponse.arrayBuffer());
  const actualSha256 = await sha256(bytes);
  if (actualSha256 && actualSha256 !== manifest.runtime.sha256) {
    throw new Error(`ASOLARIA WASM SHA mismatch: ${actualSha256}`);
  }
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const exports = instance.exports;
  [
    "input_ptr",
    "input_capacity",
    "output_ptr",
    "seed_len",
    "make_seed",
    "prism_roundtrip_exact",
    "count_channel",
    "chain_intact",
    "hidden_holes",
    "trit_bits_x10000"
  ].forEach((name) => requireExport(exports, name));
  return { exports, manifest, wasmSha256: actualSha256 || manifest.runtime.sha256 };
}

export function loadAsolariaRuntime() {
  runtimePromise ||= instantiate().catch((error) => {
    runtimePromise = undefined;
    throw error;
  });
  return runtimePromise;
}

export async function inspectAsolaria() {
  const runtime = await loadAsolariaRuntime();
  return {
    schema: ASOLARIA_INSPECTION_SCHEMA,
    status: "ready",
    engine: runtime.manifest.runtime.kind,
    artifact: runtime.manifest.id,
    wasmSha256: runtime.wasmSha256,
    capabilities: runtime.manifest.capabilities.map(({ id, input, output }) => ({ id, input, output })),
    contracts: runtime.manifest.contracts,
    litert: runtime.manifest.litert,
    claims: runtime.manifest.provenance.claims
  };
}

export async function makeAsolariaReceipt(input, metadata = {}) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input || []);
  const runtime = await loadAsolariaRuntime();
  const { exports } = runtime;
  const capacity = Number(exports.input_capacity());
  if (bytes.byteLength > capacity) {
    throw new RangeError(`ASOLARIA input exceeds ${capacity} bytes`);
  }
  const memory = new Uint8Array(exports.memory.buffer);
  memory.set(bytes, Number(exports.input_ptr()));
  const cellsReached = Number(exports.make_seed(bytes.byteLength));
  const receiptLength = Number(exports.seed_len());
  const receiptBytes = memory.slice(Number(exports.output_ptr()), Number(exports.output_ptr()) + receiptLength);
  const count = decodeCount(exports.count_channel());
  const inputSha256 = await sha256(bytes);
  const receiptSha256 = await sha256(receiptBytes);
  return {
    schema: ASOLARIA_RECEIPT_SCHEMA,
    status: "measured",
    createdAt: new Date().toISOString(),
    source: {
      name: String(metadata.name || "input"),
      bytes: bytes.byteLength,
      sha256: inputSha256
    },
    receipt: {
      bytes: receiptLength,
      sha256: receiptSha256,
      cellsReached,
      count,
      chainIntact: Boolean(exports.chain_intact()),
      hiddenHoles: Number(exports.hidden_holes()),
      prismRoundtripExact: Boolean(exports.prism_roundtrip_exact()),
      tritBitsPerSymbol: Number(exports.trit_bits_x10000()) / 10000
    },
    engine: {
      artifact: runtime.manifest.id,
      wasmSha256: runtime.wasmSha256,
      deterministic: true,
      backend: runtime.manifest.runtime.kind,
      litertCompatible: runtime.manifest.litert.compatible
    },
    claims: runtime.manifest.provenance.claims,
    bytes: receiptBytes
  };
}

export function receiptProjection(result) {
  const { receipt, source, engine } = result;
  return [
    `s=${result.status}`,
    `src=${source.bytes}:${source.sha256 || "sha-unavailable"}`,
    `r=${receipt.bytes}:${receipt.sha256 || "sha-unavailable"}`,
    `cells=${receipt.cellsReached}/27`,
    `count=${receipt.count.produced}/${receipt.count.declared}/${receipt.count.withheld}`,
    `chain=${receipt.chainIntact ? 1 : 0}`,
    `hidden=${receipt.hiddenHoles}`,
    `prism=${receipt.prismRoundtripExact ? 1 : 0}`,
    `engine=${engine.backend}`
  ].join("|");
}
