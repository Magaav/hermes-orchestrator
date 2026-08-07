export const moduleDefinition = {
  id: "observation",
  title: "Observation",
  status: "inspect-only",
  detail: "Builds and publishes the bounded workspace snapshot for embedded agent context.",
  defaultEnabled: true,
  firmware: "/modules/observation/module.js",
  endpoints: ["/observation/latest"],
  state: {
    runtimeRoot: "state/observation",
  },
};

export function observationEventCounts(events = []) {
  return events.reduce((counts, event) => {
    const type = String(event?.type || "unknown");
    counts[type] = (counts[type] || 0) + 1;
    return counts;
  }, {});
}

export function latestObservationEvents(events = [], count = 36) {
  return events.slice(-Math.max(0, Number(count) || 0)).reverse();
}

export function observationBrowserProjection({ locationRef = globalThis.location, nativeRuntime = "" } = {}) {
  const runtime = String(nativeRuntime || "").trim().toLowerCase();
  return {
    domain: String(locationRef?.hostname || ""),
    origin: String(locationRef?.origin || ""),
    path: String(locationRef?.pathname || "/"),
    stream_mode: runtime === "electron" ? "electron-webcontents" : runtime.includes("android") ? "android-webview" : "pwa",
  };
}

export function observationBrowserSummary(snapshot = {}) {
  const browser = snapshot?.browser && typeof snapshot.browser === "object" ? snapshot.browser : {};
  return { domain: String(browser.domain || "-"), stream_mode: String(browser.stream_mode || "unknown") };
}
