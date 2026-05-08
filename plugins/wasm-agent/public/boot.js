window.__WASM_AGENT_DISABLE_SW__ = true;

if ("serviceWorker" in navigator) {
  const resetKey = "wasmAgent.swReset.v2";
  Promise.all([
    navigator.serviceWorker.getRegistrations().then((items) => Promise.all(items.map((item) => item.unregister()))),
    "caches" in window ? caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key)))) : Promise.resolve(),
  ]).then(() => {
    if (!sessionStorage.getItem(resetKey) && navigator.serviceWorker.controller) {
      sessionStorage.setItem(resetKey, "1");
      window.location.reload();
    }
  }).catch(() => {});
}
