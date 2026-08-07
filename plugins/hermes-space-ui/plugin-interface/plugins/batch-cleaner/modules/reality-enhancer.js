let worker = null;
let nextId = 0;
const pending = new Map();

function ensureWorker() {
  if (worker) return worker;
  worker = new Worker(new URL("../workers/reality-enhancer-worker.js", import.meta.url), { type: "module" });
  worker.addEventListener("message", (event) => {
    const request = pending.get(event.data?.id);
    if (!request) return;
    pending.delete(event.data.id);
    if (event.data.ok) request.resolve(event.data.result);
    else request.reject(new Error(event.data.error || "Reality enhancement failed."));
  });
  worker.addEventListener("error", (event) => {
    const error = new Error(event.message || "Reality enhancement worker stopped.");
    for (const request of pending.values()) request.reject(error);
    pending.clear();
  });
  return worker;
}
export function enhanceReality(blob, options = {}) {
  options.onProgress?.({ stage: "enhancing", current: 0, total: 1 });
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, {
      resolve(result) {
        options.onProgress?.({ stage: "enhanced", current: 1, total: 1 });
        resolve(result);
      },
      reject
    });
    ensureWorker().postMessage({ id, blob });
  });
}

export function disposeRealityEnhancer() {
  worker?.terminate();
  worker = null;
  const error = new DOMException("Reality enhancer disposed.", "AbortError");
  for (const request of pending.values()) request.reject(error);
  pending.clear();
}
