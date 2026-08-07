const BUNDLE_ID = "hermes/property-photo-cleaner";
const ACTION_ID = "hermes.property_photo_cleaner.open";
const RUNTIME_KEY = "propertyPhotoCleaner";

const loadingProof = {
  schema: "hermes.property_photo_cleaner.loading_proof.v1",
  launcherRegistered: true,
  entryLoaded: false,
  liteRtLoaded: false,
  modelLoaded: false,
  fixturesLoaded: false
};

let openPromise = null;
let unregisterAction = null;

async function open(options = {}) {
  if (!openPromise) {
    openPromise = import("./property-photo-cleaner.entry.js?v=0.2.0")
      .then(async (module) => {
        loadingProof.entryLoaded = true;
        return module.mount({ loadingProof, ...options });
      })
      .finally(() => {
        openPromise = null;
      });
  }
  return openPromise;
}

function install() {
  const api = {
    descriptor: Object.freeze({
      widgetId: "property-photo-cleaner",
      displayName: "Property Photo Cleaner",
      icon: new URL("./icon.svg", import.meta.url).href,
      entry: new URL("./property-photo-cleaner.entry.js", import.meta.url).href,
      launchMode: "lazy"
    }),
    inspectLoading: () => ({ ...loadingProof }),
    open
  };

  globalThis[RUNTIME_KEY] = api;
  if (globalThis.space && typeof globalThis.space === "object") {
    globalThis.space[RUNTIME_KEY] = api;
  }
  unregisterAction = globalThis.space?.bundles?.actions?.register?.({
    bundleId: BUNDLE_ID,
    capability: "browser-runtime",
    id: ACTION_ID,
    title: "Open Property Photo Cleaner",
    run: open
  }) || null;
  return api;
}

export function disposePropertyPhotoCleanerLauncher() {
  unregisterAction?.();
  unregisterAction = null;
  delete globalThis[RUNTIME_KEY];
  if (globalThis.space?.[RUNTIME_KEY]) delete globalThis.space[RUNTIME_KEY];
}

export const propertyPhotoCleaner = install();
