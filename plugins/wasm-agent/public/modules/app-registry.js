const SPACE_APP_DEFINITIONS = [
  {
    id: "batch-cleaner", label: "Batch Cleaner", icon: "🧹", module: "batch-cleaner",
    entry: "/modules/batch-cleaner/batch-cleaner.entry.js?v=20260806-deeper-clean1",
    minWidth: 250, minHeight: 250,
  },
  {
    id: "asolaria", label: "ASOLARIA", icon: "◇", module: "asolaria",
    entry: "/modules/asolaria/asolaria.entry.js",
  },
  {
    id: "artifact-foundry", label: "Artifact Foundry", icon: "✦", module: "artifact-foundry",
    entry: "/modules/artifact-foundry/artifact-foundry.entry.js",
  },
  {
    id: "property-photo-cleaner", label: "Property Photo Cleaner", icon: "▧", module: "property-photo-cleaner",
    entry: "/modules/property-photo-cleaner/property-photo-cleaner.entry.js",
  },
  {
    id: "browser", label: "Browser", icon: "◎", module: "browser", desktopOnly: true,
    entry: "/modules/browser/browser.entry.js?v=20260822-surface-readiness1",
  },
  {
    id: "anaminese", label: "Anaminese", icon: "🎙️", module: "anaminese",
    entry: "/modules/anaminese-widget.js?v=20260803-anaminese1",
    minWidth: 320, minHeight: 280,
  },
  {
    id: "video-v1", label: "Video V1", icon: "▶", module: "video-v1",
    entry: "/modules/video-v1/video-v1.entry.js?v=17",
    minWidth: 320, minHeight: 360,
  },
  {
    id: "video-v2", label: "Video V2", icon: "▷", module: "video-v2",
    entry: "/modules/video-v2/video-v2.entry.js?v=4",
    minWidth: 320, minHeight: 360,
  },
];

// Historical home mappings retained as migration evidence:
// home: ["asolaria"]
// home: ["asolaria", "artifact-foundry"]
const SPACE_APP_MAPPINGS = {
  home: [],
  admin: ["batch-cleaner", "asolaria", "artifact-foundry", "property-photo-cleaner", "browser"],
  user: ["batch-cleaner", "asolaria", "artifact-foundry", "property-photo-cleaner", "browser", "anaminese", "video-v1", "video-v2"],
};

const mounts = new Map();
let onExternalAppClosed = null;
const INTERACTION_OUTCOME_EVENT = "wasm-agent:interaction-outcome";

function emitInteractionOutcome(detail = {}) {
  if (typeof globalThis.dispatchEvent !== "function" || typeof globalThis.CustomEvent !== "function") return;
  globalThis.dispatchEvent(new CustomEvent(INTERACTION_OUTCOME_EVENT, {
    detail: {
      at: new Date().toISOString(),
      widget: String(detail.widget || "").slice(0, 80),
      action: String(detail.action || "").slice(0, 80),
      outcome: String(detail.outcome || "").slice(0, 80),
      reason: String(detail.reason || "").slice(0, 160),
    },
  }));
}

function installAppClickOutcomeCapture() {
  if (!globalThis.document?.addEventListener) return;
  document.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-widget-app]");
    if (!button) return;
    queueMicrotask(() => emitInteractionOutcome({
      widget: button.dataset.widgetApp,
      action: "icon.click",
      outcome: event.defaultPrevented ? "canceled" : "received",
      reason: event.defaultPrevented ? "default_prevented" : "",
    }));
  }, { capture: true, passive: true });
}

installAppClickOutcomeCapture();

function externalHost(app) {
  const existing = document.querySelector(`[data-external-app-host="${app.id}"]`);
  if (existing) return existing;
  const surface = document.querySelector("#spaceBoard");
  if (!surface) throw new Error("Space board is unavailable.");
  const host = document.createElement("section");
  host.className = "widget external-app-widget";
  host.dataset.widgetId = app.id;
  host.dataset.externalAppHost = app.id;
  host.hidden = true;
  host.innerHTML = `
    <header class="widget-head external-app-widget-header">
      <strong>${app.icon} ${app.label}</strong>
      <div class="external-app-widget-controls">
        <button type="button" data-widget-control="minimize" aria-label="Minimize ${app.label}">−</button>
        <button type="button" data-widget-control="maximize" aria-label="Maximize ${app.label}">□</button>
        <button type="button" data-external-app-close="${app.id}" aria-label="Close ${app.label}">×</button>
      </div>
    </header>
    <div class="external-app-widget-body" data-external-app-mount="${app.id}"></div>`;
  host.querySelector(`[data-external-app-close="${app.id}"]`)?.addEventListener("click", () => {
    void closeExternalApp(app.id);
  });
  surface.append(host);
  return host;
}

export function installExternalAppHosts(onClose) {
  onExternalAppClosed = typeof onClose === "function" ? onClose : null;
  for (const app of SPACE_APP_DEFINITIONS.filter((item) => item.entry)) externalHost(app);
}

export async function ensureExternalAppMounted(app) {
  if (!app?.entry) return null;
  if (mounts.has(app.id)) return mounts.get(app.id);
  const host = externalHost(app);
  const mountRoot = host.querySelector(`[data-external-app-mount="${app.id}"]`);
  try {
    const module = await import(app.entry);
    if (typeof module.mount !== "function") throw new Error(`${app.id} has no mount export`);
    const api = await module.mount({
      host,
      mountRoot,
      onClose: () => closeExternalApp(app.id),
    });
    mounts.set(app.id, api || {});
    host.dispatchEvent(new CustomEvent("external-app-mounted", { bubbles: true, detail: { appId: app.id } }));
    return api;
  } catch (error) {
    host.dataset.mountError = String(error?.message || error).slice(0, 240);
    host.hidden = true;
    throw error;
  }
}

export async function closeExternalApp(appId) {
  const app = SPACE_APP_DEFINITIONS.find((item) => item.id === appId);
  if (!app) return false;
  const host = document.querySelector(`[data-external-app-host="${app.id}"]`);
  const api = mounts.get(app.id);
  if (typeof api?.close === "function") await api.close();
  else if (typeof api?.destroy === "function") await api.destroy();
  mounts.delete(app.id);
  host?.querySelector(`[data-external-app-mount="${app.id}"]`)?.replaceChildren();
  if (host) host.hidden = true;
  host?.dispatchEvent(new CustomEvent("external-app-unmounted", { bubbles: true, detail: { appId } }));
  onExternalAppClosed?.(appId);
  return true;
}

export function externalAppsToHydrate(apps = [], layout = {}) {
  return apps.filter((app) => Boolean(app?.entry) && layout?.[app.id]?.minimized === false);
}

export async function hydrateOpenExternalApps(apps = [], layout = {}) {
  return Promise.allSettled(externalAppsToHydrate(apps, layout).map(async (app) => {
    await ensureExternalAppMounted(app);
    const host = externalHost(app);
    host.hidden = false;
    return app.id;
  }));
}

export async function openExternalAppFromIcon(app, currentMinimized, onMinimizedChange) {
  if (!app?.entry) return false;
  const host = externalHost(app);
  const nextMinimized = !Boolean(currentMinimized);
  emitInteractionOutcome({ widget: app.id, action: "widget.toggle", outcome: "started", reason: nextMinimized ? "minimize" : "open" });
  try {
    if (!nextMinimized) await ensureExternalAppMounted(app);
    host.hidden = nextMinimized;
    onMinimizedChange?.(nextMinimized);
    emitInteractionOutcome({ widget: app.id, action: "widget.toggle", outcome: nextMinimized ? "minimized" : "opened" });
    return !nextMinimized;
  } catch (error) {
    emitInteractionOutcome({ widget: app.id, action: "widget.toggle", outcome: "failed", reason: error?.message || error });
    throw error;
  }
}

export async function ensureExternalAppOpen(app, currentMinimized, onMinimizedChange) {
  if (!app?.entry) return { opened: false, alreadyOpen: false };
  const host = externalHost(app);
  const alreadyOpen = currentMinimized === false && mounts.has(app.id) && host.hidden === false;
  emitInteractionOutcome({ widget: app.id, action: "widget.open", outcome: "started", reason: alreadyOpen ? "already_open" : "ensure_open" });
  try {
    await ensureExternalAppMounted(app);
    host.hidden = false;
    if (!alreadyOpen) onMinimizedChange?.(false);
    emitInteractionOutcome({ widget: app.id, action: "widget.open", outcome: alreadyOpen ? "already_open" : "opened" });
    return { opened: true, alreadyOpen };
  } catch (error) {
    emitInteractionOutcome({ widget: app.id, action: "widget.open", outcome: "failed", reason: error?.message || error });
    throw error;
  }
}

export { INTERACTION_OUTCOME_EVENT, SPACE_APP_DEFINITIONS, SPACE_APP_MAPPINGS };
