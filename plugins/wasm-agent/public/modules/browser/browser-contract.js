export const BROWSER_PORTAL_SCHEMA = "wasm-agent.browser-portal.v1";

export const BROWSER_PORTAL_CAPABILITIES = Object.freeze([
  "browser.session.status",
  "browser.navigate",
  "browser.history",
  "browser.native.surface",
  "browser.prove",
]);

export function browserPortalCommand(operation, args = {}) {
  return Object.freeze({
    schema: BROWSER_PORTAL_SCHEMA,
    operation,
    args: Object.freeze({ ...args }),
    requested_at: new Date().toISOString(),
  });
}

export function normalizeBrowserAddress(value) {
  const input = String(value || "").trim();
  if (!input) return "";
  const candidate = /^[a-z][a-z\d+.-]*:/i.test(input) ? input : `https://${input}`;
  const url = new URL(candidate);
  if (url.protocol !== "https:") throw new Error("Only secure HTTPS destinations are supported.");
  return url.href;
}

export const LOCAL_BROWSER_FIXTURE = Object.freeze({
  url: "browser://local/hello",
  html: "<main><h1>WASM Browser</h1><p>Rendered locally by WASM.</p><section><button>Inspect</button><button>Navigate</button></section></main>",
  css: "main { background: #10243a; padding: 28px; gap: 14px; } h1 { color: #eaf4ff; font-size: 30px; } p { color: #91a8bd; } section { display: flex; gap: 12px; padding: 4px; } button { background: #167a9f; color: #ffffff; }",
});
