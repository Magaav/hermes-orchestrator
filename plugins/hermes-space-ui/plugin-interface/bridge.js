const DEFAULT_BUNDLE_ID = "hermes/fleet";

function resolveSpaceRuntime(spaceRuntime) {
  const runtime = spaceRuntime || globalThis.space;

  if (!runtime || typeof runtime !== "object" || !runtime.bundles) {
    throw new Error("Hermes Space UI requires Space Agent's space.bundles runtime.");
  }

  return runtime;
}

export function createHermesSpaceBundleBridge(options = {}) {
  const bundleId = String(options.bundleId || DEFAULT_BUNDLE_ID);
  const runtime = resolveSpaceRuntime(options.space);

  function registerAction(action) {
    const source = action && typeof action === "object" ? action : {};

    return runtime.bundles.actions.register({
      bundleId,
      capability: source.capability || "hermes",
      description: source.description || "",
      id: source.id,
      title: source.title || source.name || source.id,
      run: source.run
    });
  }

  function registerStateSync(handler) {
    return runtime.bundles.bridge.registerSync(bundleId, handler);
  }

  function syncState(payload, context = {}) {
    return runtime.bundles.bridge.syncState(bundleId, payload, {
      source: "hermes-space-ui",
      ...context
    });
  }

  return {
    bundleId,
    registerAction,
    registerStateSync,
    syncState
  };
}

export default createHermesSpaceBundleBridge;
