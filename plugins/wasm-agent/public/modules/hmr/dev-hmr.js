const HMR_CLIENT_REVISION = "dev-hmr-v2";
const HMR_REVISION_STORAGE_KEY = "wasmAgent.devHmr.revision.v1";
const HMR_ENDPOINT = `/modules/hmr/events?client=${encodeURIComponent(HMR_CLIENT_REVISION)}`;
let hmrSource = null;

function readStoredRevision() {
  try {
    return localStorage.getItem(HMR_REVISION_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeStoredRevision(revision) {
  if (!revision) return;
  try {
    localStorage.setItem(HMR_REVISION_STORAGE_KEY, revision);
  } catch {
    // HMR remains useful without persistent revision storage.
  }
}

function reloadStylesheets() {
  const stamp = Date.now().toString(36);
  document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
    const url = new URL(link.href, window.location.href);
    url.searchParams.set("hmr", stamp);
    link.href = url.toString();
  });
}

function shouldReloadPage(paths) {
  return paths.some((path) => !path.endsWith(".css"));
}

function reloadPage(paths, revision = "") {
  writeStoredRevision(revision);
  const hmrBridge = window.__wasmAgentAppDevHmr || window.__wasmAgentNativeDevHmr || window.__wasmAgentDevHmr;
  if (hmrBridge?.requestReload?.(paths)) return;
  window.location.reload();
}

export function startDevHmr() {
  if (hmrSource) return;
  if (!("EventSource" in window)) return;
  const source = new EventSource(HMR_ENDPOINT);
  hmrSource = source;
  source.addEventListener("ready", (event) => {
    let payload = {};
    try {
      payload = JSON.parse(event.data || "{}");
    } catch {
      return;
    }
    const revision = String(payload.revision || "");
    const previous = readStoredRevision();
    if (revision && previous && previous !== revision) {
      reloadPage(["dev-hmr:revision"], revision);
      return;
    }
    writeStoredRevision(revision);
  });
  source.addEventListener("change", (event) => {
    let payload = {};
    try {
      payload = JSON.parse(event.data || "{}");
    } catch {
      return;
    }
    const paths = [...(payload.changed || []), ...(payload.removed || [])];
    if (!paths.length) return;
    if (shouldReloadPage(paths)) {
      reloadPage(paths, String(payload.revision || ""));
      return;
    }
    writeStoredRevision(String(payload.revision || ""));
    reloadStylesheets();
  });
  source.addEventListener("error", () => {
    hmrSource = null;
  });
}
