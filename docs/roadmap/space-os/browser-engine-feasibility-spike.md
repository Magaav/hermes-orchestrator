# Browser Engine Feasibility Spike

Date: 2026-05-04

## Question

Can Space OS v1 deliver arbitrary browser-inside-browser behavior inside the
PWA, without iframe, using a local WASM widget runtime only?

## Result

No-go for a PWA-only local WASM browser engine in v1.

The product goal remains valid, but the implementation path must change:
iframe-free arbitrary browsing should be delivered through remote browser
infrastructure or the existing native desktop webview path, not by promising a
complete browser engine inside the PWA widget runtime.

## Evidence

Current Space Agent evidence:

- `_core/web_browsing` already has `<x-browser>` and `space.browser` helpers.
- Packaged desktop paths use native/Electron webview-style surfaces and injected
  browser runtime helpers.
- Ordinary browser/PWA sessions fall back to iframe and show the current message
  that embedded browsing works in native desktop apps for now.

Web-platform evidence:

- Browser `fetch()` and XHR are constrained by same-origin/CORS behavior, so a
  PWA cannot freely fetch arbitrary external site resources unless those sites
  opt in or the app uses a proxy/remote browser service.
- WebAssembly does not directly access the DOM by itself; it calls out through
  JavaScript/Web APIs. A WASM browser would need to implement or bridge a full
  browser stack rather than simply "turn on browser APIs" inside a widget.
- Electron/webview-style embedding is a native-app capability, not a normal PWA
  capability.

References:

- MDN CORS: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS
- MDN WebAssembly concepts: https://developer.mozilla.org/en-US/docs/WebAssembly/Concepts
- Electron webview tag: https://www.electronjs.org/docs/api/webview-tag/

## Stop/Go Criteria

| Criterion | PWA-only local WASM result |
| --- | --- |
| navigation and network loading | Fails for arbitrary external sites without proxying because of browser network/security restrictions |
| visual rendering into widget | Not proven; would require a real browser engine renderer, not just WASM glue |
| JavaScript execution | Not viable for arbitrary sites without a full JS engine plus browser API implementation |
| input events | Possible only after rendering/runtime exists |
| agent-readable state | Not available for arbitrary pages in PWA-only path today |
| screenshot/pixel capture | Possible for our own canvas/runtime; not enough for arbitrary external web |
| isolation | Possible in principle, but incomplete without the browser engine |
| performance data | No credible v1 baseline for full arbitrary browsing in local WASM |

The PWA-only local WASM browser path fails this gate.

## Viable Architectures

### Remote Browser Service

Run Chromium/Playwright/CDP under Hermes-controlled backend infrastructure and
stream the visual surface into a Space widget. The widget is not an iframe; it
is a remote browser viewport. Hermes can receive DOM/accessibility snapshots,
screenshots, network state, and input results through the browser service.

This is the strongest match for the goal:

- PWA remains installable from `space.colmeio.com`
- arbitrary external browsing happens outside web-platform CORS limits
- Hermes can inspect and control browser state natively
- the UI can be a canvas/video/WebRTC/WebSocket surface inside Space Agent

### Native Space Agent Desktop

Use the existing Space Agent native/Electron browser path where native embedded
web contents are allowed. This is useful for power users, but it does not solve
the PWA install-from-any-OS goal by itself.

### Generated-App WASM Sandbox

Use WASM widgets for Hermes-generated apps, 3D scenes, simulations, and custom
tools that we own. This remains valuable, but it is not arbitrary web browsing.

## Decision

Do not build a PWA-only local WASM arbitrary browser as the Space OS v1 browser
plan.

Proceed only if the browser-inside-browser requirement is reframed as:

- remote browser execution controlled by Hermes, rendered into a Space widget,
  or
- native desktop browser execution controlled by Space Agent, or
- generated-app-only WASM sandbox for apps we own

## Next Implementation Spike

Build the smallest remote browser proof:

1. backend starts one isolated Chromium page
2. Space widget shows the remote page as pixels, not iframe
3. widget sends click/type/scroll input to backend
4. backend returns screenshot plus DOM/accessibility-like snapshot
5. Hermes bridge exposes one safe endpoint for page state and one for input
6. docs record latency, CPU, memory, and security boundaries

If that proof fails, stop Space OS browser product work again and revisit the
architecture before cloud/PWA rollout.
