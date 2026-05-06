const CACHE_NAME = "wasm-agent-v19";
const ASSETS = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/modules/index.js",
  "/modules/hmr/dev-hmr.js",
  "/modules/hmr/module.js",
  "/modules/browser/module.js",
  "/modules/observation/module.js",
  "/modules/timeline/module.js",
  "/modules/assistant/module.js",
  "/modules/image-card-core/module.js",
  "/modules/barcode-reader/module.js",
  "/modules/ocr/module.js",
  "/modules/cv-shapes/module.js",
  "/modules/semantic-vision/module.js",
  "/manifest.webmanifest",
  "/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (
    url.pathname === "/config.json" ||
    url.pathname === "/auth/session" ||
    url.pathname === "/health" ||
    url.pathname === "/observation/latest" ||
    url.pathname === "/modules/hmr/events"
  ) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match("/index.html")))
  );
});
