const STORAGE_KEY = "hermes.performanceHud.enabled";
const HUD_ID = "hermes-performance-hud";
const TOGGLE_ATTRIBUTE = "data-hermes-performance-hud-toggle";
const DEFAULT_ENABLED = true;
const SAMPLE_WINDOW_MS = 500;
const ADMIN_ATTACH_INTERVAL_MS = 1000;

let installed = false;
let hudElement = null;
let fpsValueElement = null;
let memoryValueElement = null;
let frameCount = 0;
let sampleStartedAt = 0;
let rafId = 0;
let adminObserver = null;
let adminAttachInterval = 0;

function readEnabledPreference() {
  try {
    const value = globalThis.localStorage?.getItem?.(STORAGE_KEY);
    if (value === "1") {
      return true;
    }
    if (value === "0") {
      return false;
    }
  } catch {
    return DEFAULT_ENABLED;
  }

  return DEFAULT_ENABLED;
}

function writeEnabledPreference(enabled) {
  try {
    globalThis.localStorage?.setItem?.(STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // Preference persistence is best-effort.
  }
}

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) {
    return "n/a";
  }

  const mib = value / 1024 / 1024;
  if (mib < 1024) {
    return `${Math.round(mib)} MB`;
  }

  return `${(mib / 1024).toFixed(1)} GB`;
}

function readMemoryText() {
  const memory = globalThis.performance?.memory;
  if (!memory || typeof memory !== "object") {
    return "n/a";
  }

  return formatBytes(memory.usedJSHeapSize);
}

function createMetric(label, valueId) {
  const item = document.createElement("span");
  item.className = "hermes-performance-hud__item";

  const labelElement = document.createElement("span");
  labelElement.className = "hermes-performance-hud__label";
  labelElement.textContent = label;

  const valueElement = document.createElement("span");
  valueElement.className = "hermes-performance-hud__value";
  valueElement.id = valueId;
  valueElement.textContent = "...";

  item.append(labelElement, valueElement);
  return { item, valueElement };
}

function ensureHud() {
  if (hudElement?.isConnected) {
    return hudElement;
  }

  const hud = document.createElement("div");
  hud.id = HUD_ID;
  hud.className = "hermes-performance-hud";
  hud.setAttribute("aria-label", "Hermes runtime performance");

  const fpsMetric = createMetric("fps", "hermes-performance-hud-fps");
  const memoryMetric = createMetric("mem", "hermes-performance-hud-memory");
  hud.append(fpsMetric.item, memoryMetric.item);

  fpsValueElement = fpsMetric.valueElement;
  memoryValueElement = memoryMetric.valueElement;
  document.body.appendChild(hud);
  hudElement = hud;
  return hud;
}

function setHudEnabled(enabled) {
  writeEnabledPreference(enabled);
  ensureHud().hidden = !enabled;
  syncToggleInputs(enabled);
}

function publishRuntimeApi() {
  const api = {
    isEnabled() {
      return readEnabledPreference();
    },
    setEnabled(value) {
      setHudEnabled(Boolean(value));
      return readEnabledPreference();
    },
    toggle() {
      setHudEnabled(!readEnabledPreference());
      return readEnabledPreference();
    }
  };

  globalThis.hermesPerformanceHud = api;

  if (globalThis.space && typeof globalThis.space === "object") {
    globalThis.space.hermesPerformanceHud = api;
  }
}

function syncToggleInputs(enabled = readEnabledPreference()) {
  document
    .querySelectorAll(`input[${TOGGLE_ATTRIBUTE}]`)
    .forEach((input) => {
      input.checked = enabled;
    });
}

function sampleFrame(timestamp) {
  const enabled = readEnabledPreference();
  if (enabled) {
    ensureHud().hidden = false;
    frameCount += 1;

    if (!sampleStartedAt) {
      sampleStartedAt = timestamp;
    }

    const elapsed = timestamp - sampleStartedAt;
    if (elapsed >= SAMPLE_WINDOW_MS) {
      const fps = Math.round((frameCount * 1000) / elapsed);
      if (fpsValueElement) {
        fpsValueElement.textContent = String(fps);
      }
      if (memoryValueElement) {
        memoryValueElement.textContent = readMemoryText();
      }
      frameCount = 0;
      sampleStartedAt = timestamp;
    }
  } else if (hudElement) {
    hudElement.hidden = true;
    frameCount = 0;
    sampleStartedAt = 0;
  }

  rafId = globalThis.requestAnimationFrame(sampleFrame);
}

function startSampling() {
  if (rafId) {
    return;
  }

  rafId = globalThis.requestAnimationFrame(sampleFrame);
}

function createAdminToggle() {
  const label = document.createElement("label");
  label.className = "hermes-performance-hud-toggle";
  label.title = "Toggle Hermes performance HUD";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.setAttribute(TOGGLE_ATTRIBUTE, "true");
  input.checked = readEnabledPreference();
  input.addEventListener("change", () => {
    setHudEnabled(input.checked);
  });

  const text = document.createElement("span");
  text.textContent = "Perf";

  label.append(input, text);
  return label;
}

function attachAdminModulesToggle() {
  const controls = document.querySelector(".admin-modules-header .admin-modules-controls");
  if (!controls || controls.querySelector(`[${TOGGLE_ATTRIBUTE}]`)) {
    return;
  }

  controls.insertBefore(createAdminToggle(), controls.firstChild);
}

function startAdminToggleObserver() {
  attachAdminModulesToggle();

  if (!adminObserver && typeof MutationObserver === "function") {
    adminObserver = new MutationObserver(() => {
      attachAdminModulesToggle();
    });
    adminObserver.observe(document.documentElement, {
      childList: true,
      subtree: true
    });
  }

  if (!adminAttachInterval) {
    adminAttachInterval = globalThis.setInterval(
      attachAdminModulesToggle,
      ADMIN_ATTACH_INTERVAL_MS
    );
  }
}

export function installHermesPerformanceHud() {
  if (installed || typeof document === "undefined" || !document.body) {
    return;
  }

  installed = true;
  publishRuntimeApi();
  ensureHud().hidden = !readEnabledPreference();
  startSampling();
  startAdminToggleObserver();
}
