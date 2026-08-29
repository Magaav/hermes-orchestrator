const SCHEMA = "hermes.wasm_agent.client_runtime_refresh.v1";

export function refreshTarget(locationRef = globalThis.location, nonce = Date.now()) {
  const target = new URL(locationRef.href);
  target.searchParams.set("module_refresh", String(nonce));
  return target.href;
}

export async function prepareRuntimeRefresh({
  locationRef = globalThis.location,
  navigatorRef = globalThis.navigator,
  schedule = globalThis.setTimeout,
  nonce = Date.now(),
} = {}) {
  if (locationRef?.protocol !== "https:" || locationRef?.hostname !== "wa.colmeio.com") {
    return { ok: false, schema: SCHEMA, error: "production_origin_required" };
  }
  const registrations = typeof navigatorRef?.serviceWorker?.getRegistrations === "function"
    ? await navigatorRef.serviceWorker.getRegistrations().catch(() => [])
    : [];
  const updates = await Promise.all(registrations.slice(0, 8).map(async (registration) => {
    try { await registration.update(); return "updated"; }
    catch { return "failed"; }
  }));
  const target = refreshTarget(locationRef, nonce);
  schedule(() => locationRef.replace(target), 1000);
  return {
    ok: true,
    schema: SCHEMA,
    mode: "cloud_module_reload",
    target,
    service_workers: { checked: updates.length, updated: updates.filter((value) => value === "updated").length },
    proof: ["client.runtime.refresh.scheduled"],
  };
}
