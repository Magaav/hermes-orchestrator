(function () {
  function clean(value) {
    return String(value || "").trim();
  }

  function scrubAuthCode() {
    try {
      var url = new URL(window.location.href);
      url.searchParams.delete("auth_code");
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    } catch (_) {
      // Keep boot moving even if history replacement is unavailable.
    }
  }

  function diagnostic(kind, payload) {
    try {
      if (window.wasmAgentNative && window.wasmAgentNative.logAuthDiagnostic) {
        window.wasmAgentNative.logAuthDiagnostic(kind, payload || {});
      }
      fetch("/native/diagnostics", {
        method: "POST",
        cache: "no-store",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          schema: "hermes.wasm_agent.auth_redirect_preload.v1",
          reason: kind,
          href: window.location.href,
          renderer_auth_diagnostics_tail: JSON.stringify({
            timestamp: new Date().toISOString(),
            kind: kind,
            payload: payload || {},
          }),
        }),
      }).catch(function () {});
    } catch (_) {
      // Diagnostics are best-effort.
    }
  }

  var code = "";
  try {
    code = clean(new URL(window.location.href).searchParams.get("auth_code"));
  } catch (_) {
    code = "";
  }

  if (!code) {
    window.__WASM_AGENT_AUTH_REDIRECT_PROMISE__ = Promise.resolve(null);
    return;
  }

  diagnostic("auth_redirect_preload_started", { has_code: true });
  window.__WASM_AGENT_AUTH_REDIRECT_PROMISE__ = fetch("/auth/redeem", {
    method: "POST",
    cache: "no-store",
    credentials: "include",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code: code }),
  })
    .then(function (response) {
      return response.text().then(function (text) {
        var payload = {};
        try {
          payload = text ? JSON.parse(text) : {};
        } catch (_) {
          payload = { ok: false, error: { message: text.slice(0, 500) } };
        }
        if (!response.ok || payload.ok === false) {
          throw new Error((payload.error && payload.error.message) || "Auth redirect redeem failed");
        }
        window.__WASM_AGENT_AUTH_REDIRECT_USER__ = payload.user || null;
        return Promise.resolve()
          .then(function () {
            if (window.wasmAgentNative && window.wasmAgentNative.flushAuthCookies) {
              return window.wasmAgentNative.flushAuthCookies({ reason: "auth_redirect_preload" });
            }
            return null;
          })
          .catch(function (flushError) {
            diagnostic("auth_redirect_preload_cookie_flush_error", {
              message: String((flushError && flushError.message) || flushError || "cookie flush failed"),
            });
            return null;
          })
          .then(function () {
            scrubAuthCode();
            diagnostic("auth_redirect_preload_finished", { authenticated: Boolean(payload.user) });
            return payload;
          });
      });
    })
    .catch(function (error) {
      scrubAuthCode();
      window.__WASM_AGENT_AUTH_REDIRECT_ERROR__ = String((error && error.message) || error || "Auth redirect redeem failed");
      diagnostic("auth_redirect_preload_error", { message: window.__WASM_AGENT_AUTH_REDIRECT_ERROR__ });
      return null;
    });
})();
