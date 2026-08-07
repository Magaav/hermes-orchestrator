let runtime = null;
let loadedRuntime = null;
let initialized = false;

export async function loadVerifiedLiteRt(manifest, loadingProof) {
  if (!manifest?.runtime?.url || !manifest.runtime.integrity || !manifest.runtime.version || !manifest.runtime.wasmBase) {
    throw new Error("AI runtime is unavailable: a pinned URL, version, integrity, and WASM base are required.");
  }
  const moduleUrl = new URL(manifest.runtime.url, import.meta.url).href;
  const wasmBase = new URL(manifest.runtime.wasmBase, import.meta.url).href;
  runtime ||= import(moduleUrl);
  const loaded = await runtime;
  loadedRuntime = loaded;
  if (!initialized) {
    await loaded.loadLiteRt(wasmBase);
    initialized = true;
  }
  loadingProof.liteRtLoaded = true;
  return loaded;
}

export function disposeRuntime() {
  loadedRuntime?.unloadLiteRt?.();
  loadedRuntime = null;
  runtime = null;
  initialized = false;
}
