import { renderOverlayTokensToHtml } from "./chat-renderer.js";

const MIRRORED_STYLE_KEYS = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "fontStyle",
  "lineHeight",
  "letterSpacing",
  "textTransform",
  "textIndent",
  "textAlign",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "boxSizing",
  "whiteSpace",
  "wordBreak",
  "overflowWrap",
  "tabSize",
];

function cssPixelValue(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function applyMirroredStyles(textarea, overlay) {
  if (!textarea || !overlay || !globalThis.getComputedStyle) return;
  const computed = getComputedStyle(textarea);
  for (const key of MIRRORED_STYLE_KEYS) {
    overlay.style[key] = computed[key];
  }
  overlay.style.borderStyle = "solid";
  overlay.style.borderColor = "transparent";
  overlay.style.overflow = "hidden";
  overlay.style.scrollbarWidth = "none";
  const borderX = cssPixelValue(computed.borderLeftWidth) + cssPixelValue(computed.borderRightWidth);
  const borderY = cssPixelValue(computed.borderTopWidth) + cssPixelValue(computed.borderBottomWidth);
  overlay.style.width = `${textarea.clientWidth + borderX}px`;
  overlay.style.minHeight = `${textarea.clientHeight + borderY}px`;
}

export function createChatOverlay(options = {}) {
  const textarea = options.textarea;
  const overlay = options.overlay;
  let disabled = Boolean(options.disabled);
  let lastRaw = "";
  let lastTokens = [];

  function syncMetrics() {
    if (!textarea || !overlay || disabled) return;
    applyMirroredStyles(textarea, overlay);
    syncScroll();
  }

  function syncScroll() {
    if (!textarea || !overlay) return;
    overlay.scrollTop = textarea.scrollTop;
    overlay.scrollLeft = textarea.scrollLeft;
  }

  function render(rawText = lastRaw, tokens = lastTokens) {
    lastRaw = String(rawText ?? "");
    lastTokens = Array.isArray(tokens) ? tokens : [];
    if (!overlay) return;
    overlay.hidden = disabled;
    overlay.setAttribute("aria-hidden", "true");
    overlay.tabIndex = -1;
    if (disabled) {
      overlay.replaceChildren();
      return;
    }
    overlay.innerHTML = renderOverlayTokensToHtml(lastTokens, lastRaw);
    syncMetrics();
  }

  function setDisabled(nextDisabled) {
    disabled = Boolean(nextDisabled);
    render(lastRaw, lastTokens);
  }

  textarea?.addEventListener("scroll", syncScroll, { passive: true });
  if (globalThis.ResizeObserver && textarea && overlay) {
    const observer = new ResizeObserver(syncMetrics);
    observer.observe(textarea);
  }
  syncMetrics();

  return {
    render,
    syncMetrics,
    syncScroll,
    setDisabled,
    get disabled() {
      return disabled;
    },
  };
}
