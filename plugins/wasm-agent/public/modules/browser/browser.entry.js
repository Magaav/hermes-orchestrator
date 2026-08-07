import { BROWSER_PORTAL_CAPABILITIES, browserPortalCommand, normalizeBrowserAddress } from "./browser-contract.js";
import { AVATAR_CHAT_OVERLAY_ID, SHELL_OVERLAY_EVENT } from "../shell-overlay-contract.js?v=20260802-avatar-layer1";

const STYLE_ID = "wasm-agent-browser-portal-style";
const STORAGE_KEY = "wasmAgent.browserPortal.v2";
const SURFACE_ID = "browser";
const DEFAULT_URL = "https://web.whatsapp.com/";

function installStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = "/modules/browser/browser.css?v=20260802-windows-resize2";
  document.head.append(link);
}

function emit(host, operation, args = {}) {
  const command = browserPortalCommand(operation, args);
  host.dispatchEvent(new CustomEvent("wasm-agent:browser-command", { bubbles: true, composed: true, detail: command }));
  return command;
}

function savedAddress() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")?.address || DEFAULT_URL; }
  catch { return DEFAULT_URL; }
}

function surfaceBounds(element) {
  const rect = element.getBoundingClientRect();
  return {
    x: Math.max(0, Math.round(rect.left)),
    y: Math.max(0, Math.round(rect.top)),
    width: Math.max(1, Math.round(rect.width)),
    height: Math.max(1, Math.round(rect.height)),
  };
}

export async function mount({ host, mountRoot, onClose } = {}) {
  if (!host || !mountRoot) throw new Error("Browser portal host is unavailable.");
  installStyles();
  host.classList.add("browser-portal-widget");
  host.dataset.browserSession = "starting";
  host.dataset.browserGeometryContract = "serialized-latest-v2";
  mountRoot.innerHTML = `
    <main class="browser-portal" aria-label="Native browser">
      <form class="browser-portal-toolbar" data-browser-address-form autocomplete="off">
        <div class="browser-portal-nav" aria-label="Navigation actions">
          <button type="button" data-browser-action="back" aria-label="Back">&#8592;</button>
          <button type="button" data-browser-action="forward" aria-label="Forward">&#8594;</button>
          <button type="button" data-browser-action="reload" aria-label="Reload">&#8635;</button>
        </div>
        <label class="browser-portal-address">
          <span class="browser-portal-lock" aria-hidden="true">&#9671;</span>
          <input type="text" inputmode="url" aria-label="Web address" placeholder="Enter a secure web address">
        </label>
        <button class="browser-portal-go" type="submit">Go</button>
        <button class="browser-portal-agent" type="button" data-browser-agent aria-pressed="false">Agent</button>
      </form>
      <section class="browser-portal-stage" data-browser-native-viewport>
        <div class="browser-portal-native-placeholder" data-browser-placeholder>
          <p>Connecting to the native Chromium surface…</p>
        </div>
      </section>
      <footer class="browser-portal-footer">
        <div class="browser-portal-session">
          <span class="browser-portal-state-dot"></span>
          <span data-browser-session-label>Starting</span>
          <small data-browser-renderer>electron-chromium</small>
        </div>
        <div class="browser-portal-capabilities"><span>native</span><span>persistent</span><span>isolated</span></div>
        <button type="button" data-browser-proof>Proof</button>
      </footer>
    </main>`;

  const native = window.wasmAgentNative?.webSurfaces;
  const input = mountRoot.querySelector("input");
  const viewport = mountRoot.querySelector("[data-browser-native-viewport]");
  const placeholder = mountRoot.querySelector("[data-browser-placeholder]");
  const sessionLabel = mountRoot.querySelector("[data-browser-session-label]");
  const agentButton = mountRoot.querySelector("[data-browser-agent]");
  const abort = new AbortController();
  let closed = false;
  let lastBounds = "";
  let lastVisible = null;
  let frame = 0;
  let geometryBusy = false;
  let geometryQueued = false;
  let shellOverlayOpen = document.querySelector("#agentOverlay")?.dataset.open === "true";
  host.dataset.nativeSurfaceSuppressed = String(shellOverlayOpen);
  let state = null;

  input.value = savedAddress();
  const invoke = (operation, args = {}) => native.invoke(operation, { id: SURFACE_ID, ...args });

  function renderState(next) {
    if (!next || next.id !== SURFACE_ID) return;
    state = next;
    host.dataset.browserSession = next.status === "error" ? "error" : (next.loading ? "starting" : "ready");
    sessionLabel.textContent = next.error || (next.loading ? "Loading" : "Native Chromium ready");
    if (next.url) input.value = next.url;
    placeholder.hidden = next.status !== "error";
    if (next.error) placeholder.firstElementChild.textContent = next.error;
  }

  async function syncGeometry() {
    frame = 0;
    if (closed) return;
    if (geometryBusy) {
      geometryQueued = true;
      return;
    }
    geometryBusy = true;
    try {
      do {
        geometryQueued = false;
        await syncLatestGeometry();
      } while (geometryQueued && !closed);
    } finally {
      geometryBusy = false;
    }
  }

  async function syncLatestGeometry() {
    const rect = viewport.getBoundingClientRect();
    const visible = !shellOverlayOpen && !document.hidden && !host.hidden && rect.width > 1 && rect.height > 1
      && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    if (visible) {
      const bounds = surfaceBounds(viewport);
      const key = JSON.stringify(bounds);
      if (key !== lastBounds) {
        lastBounds = key;
        renderState(await invoke("bounds", { bounds }));
      }
    }
    if (visible !== lastVisible) {
      lastVisible = visible;
      renderState(await invoke("visibility", { visible }));
    }
  }

  function scheduleGeometry() {
    if (!frame && !closed) frame = requestAnimationFrame(() => void syncGeometry().catch(showError));
  }

  function showError(error) {
    host.dataset.browserSession = "error";
    sessionLabel.textContent = String(error?.message || error);
    placeholder.hidden = false;
    placeholder.firstElementChild.textContent = String(error?.message || error);
  }

  if (!native?.invoke) {
    showError(new Error("Native Chromium is available in the Electron build only."));
  } else {
    const offEvent = native.onEvent(({ surface }) => renderState(surface));
    abort.signal.addEventListener("abort", offEvent, { once: true });
    try {
      const capabilities = await native.invoke("capabilities");
      emit(host, "browser.capabilities", capabilities);
      state = await invoke("create", { url: input.value, bounds: surfaceBounds(viewport) });
      renderState(state);
      scheduleGeometry();
    } catch (error) { showError(error); }
  }

  mountRoot.querySelector("[data-browser-address-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const url = normalizeBrowserAddress(input.value);
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ address: url }));
      renderState(await invoke("navigate", { url }));
      emit(host, "browser.navigate", { url });
    } catch (error) { showError(error); }
  }, { signal: abort.signal });

  mountRoot.querySelectorAll("[data-browser-action]").forEach((button) => button.addEventListener("click", async () => {
    try {
      renderState(await invoke("action", { action: button.dataset.browserAction }));
      emit(host, `browser.${button.dataset.browserAction}`);
    } catch (error) { showError(error); }
  }, { signal: abort.signal }));

  agentButton.addEventListener("click", () => {
    const enabled = agentButton.getAttribute("aria-pressed") !== "true";
    agentButton.setAttribute("aria-pressed", String(enabled));
    agentButton.classList.toggle("is-active", enabled);
    emit(host, "browser.agent.set", { enabled });
  }, { signal: abort.signal });

  mountRoot.querySelector("[data-browser-proof]").addEventListener("click", async () => {
    try { emit(host, "browser.prove", await invoke("status")); }
    catch (error) { showError(error); }
  }, { signal: abort.signal });

  const resizeObserver = new ResizeObserver(scheduleGeometry);
  const mutationObserver = new MutationObserver(scheduleGeometry);
  resizeObserver.observe(viewport);
  mutationObserver.observe(host, { attributes: true, attributeFilter: ["class", "hidden", "style"] });
  addEventListener("scroll", scheduleGeometry, { capture: true, passive: true, signal: abort.signal });
  addEventListener("resize", scheduleGeometry, { passive: true, signal: abort.signal });
  document.addEventListener("visibilitychange", scheduleGeometry, { signal: abort.signal });
  host.addEventListener("wasm-agent:widget-resize-frame", scheduleGeometry, { signal: abort.signal });
  addEventListener(SHELL_OVERLAY_EVENT, (event) => {
    if (event.detail?.id !== AVATAR_CHAT_OVERLAY_ID) return;
    shellOverlayOpen = Boolean(event.detail.open);
    host.dataset.nativeSurfaceSuppressed = String(shellOverlayOpen);
    scheduleGeometry();
  }, { signal: abort.signal });

  return {
    capabilities: BROWSER_PORTAL_CAPABILITIES,
    async close() {
      closed = true;
      if (frame) cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
      abort.abort();
      if (native?.invoke) await invoke("close").catch(() => {});
      mountRoot.replaceChildren();
      host.classList.remove("browser-portal-widget");
      onClose?.();
    },
  };
}

export { surfaceBounds };
