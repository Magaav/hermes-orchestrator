const CACHE_NAME = "wasm-agent-v171-route-contracts";
const ASSETS = [
  "/android-app.js",
  "/app-loader.js",
  "/auth-redirect.js",
  "/composer-lab",
  "/composer-lab.html",
  "/composer-lab.js",
  "/voice-lab",
  "/voice-lab.html",
  "/voice-lab.css",
  "/voice-lab.js",
  "/provider-model-catalog.js",
  "/modules/chat-composer/chat-composer.css",
  "/modules/chat-composer/chat-composer.js",
  "/modules/chat-composer/chat-commands.js",
  "/modules/chat-composer/chat-overlay.js",
  "/modules/chat-composer/chat-renderer.js",
  "/modules/chat-composer/chat-tokenizer.js",
  "/modules/chat-composer/chat-composer.test.js",
  "/modules/speech-transcription/module.js",
  "/modules/speech-transcription/speech-transcription.js",
  "/modules/speech-transcription/transcript-draft.js",
  "/modules/speech-transcription/speech-transcription-worker.js",
  "/modules/speech-transcription/speech-capture-worklet.js",
  "/modules/index.js",
  "/modules/hmr/dev-hmr.js",
  "/modules/hmr/module.js",
  "/modules/spaces/module.js",
  "/modules/spaces/shared-pointer-renderer.js",
  "/modules/spaces/shared-voice-room.js",
  "/modules/browser/module.js",
  "/modules/wis/module.js",
  "/modules/wis/engine.js",
  "/modules/wis/artifacts/camera.js",
  "/modules/client-state/module.js",
  "/modules/client-state/client-store.js",
  "/modules/observation/module.js",
  "/modules/devices/module.js",
  "/modules/native-standby/module.js",
  "/modules/artifacts/module.js",
  "/modules/config/module.js",
  "/modules/module-manager/module.js",
  "/modules/timeline/module.js",
  "/modules/assistant/module.js",
  "/modules/remote-control/module.js",
  "/modules/remote-control/viewport.js",
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
    url.pathname === "/" ||
    url.pathname === "/home" ||
    url.pathname === "/index.html" ||
    url.pathname === "/boot.js" ||
    url.pathname === "/app-loader.js" ||
    url.pathname === "/android-app.js" ||
    url.pathname === "/app.js" ||
    url.pathname === "/styles.css" ||
    url.pathname === "/sw.js" ||
    url.pathname === "/config.json" ||
    url.pathname === "/auth/session" ||
    url.pathname === "/app/bootstrap" ||
    url.pathname === "/account/friends" ||
    url.pathname === "/account/users/lookup" ||
    url.pathname === "/sync/events" ||
    url.pathname === "/fleet" ||
    url.pathname === "/health" ||
    url.pathname === "/camera/push/status" ||
    url.pathname === "/camera/push-frame" ||
    url.pathname === "/camera/push-stream" ||
    url.pathname === "/camera/push-playback" ||
    url.pathname === "/camera/push-replay" ||
    url.pathname === "/camera/push-timeline" ||
    url.pathname === "/camera/push-archive-frame" ||
    url.pathname === "/agent/provider/models" ||
    url.pathname === "/observation/latest" ||
    url.pathname === "/voice-lab/room" ||
    url.pathname.startsWith("/security-loop/") ||
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
