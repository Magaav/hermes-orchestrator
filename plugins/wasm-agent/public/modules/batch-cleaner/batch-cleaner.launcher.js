const BUNDLE_ID = "hermes/batch-cleaner";
const ACTION_ID = "hermes.batch_cleaner.open";
let openPromise = null;
let unregisterAction = null;

async function open(options = {}) {
  if (!openPromise) {
    openPromise = import("./batch-cleaner.entry.js?v=1.1.0-codex-scene")
      .then((module) => module.mount(options))
      .finally(() => { openPromise = null; });
  }
  return openPromise;
}

export const batchCleaner = {
  descriptor: Object.freeze({
    widgetId: "batch-cleaner",
    displayName: "Batch Cleaner",
    icon: new URL("./icon.svg", import.meta.url).href,
    entry: new URL("./batch-cleaner.entry.js", import.meta.url).href,
    launchMode: "lazy"
  }),
  open
};

globalThis.batchCleaner = batchCleaner;
unregisterAction = globalThis.space?.bundles?.actions?.register?.({
  bundleId: BUNDLE_ID,
  capability: "browser-runtime",
  id: ACTION_ID,
  title: "Open Batch Cleaner",
  run: open
}) || null;

export function disposeBatchCleanerLauncher() {
  unregisterAction?.();
  unregisterAction = null;
  delete globalThis.batchCleaner;
}
