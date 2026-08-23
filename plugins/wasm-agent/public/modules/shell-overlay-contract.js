export const SHELL_OVERLAY_EVENT = "wasm-agent:shell-overlay";
export const AVATAR_CHAT_OVERLAY_ID = "wasm-agent-avatar-chat";

export function unionShellOverlayRects(rects = []) {
  const visible = rects.filter((rect) => rect?.width > 0 && rect?.height > 0);
  if (!visible.length) return null;
  const left = Math.min(...visible.map((rect) => rect.left));
  const top = Math.min(...visible.map((rect) => rect.top));
  const right = Math.max(...visible.map((rect) => rect.right));
  const bottom = Math.max(...visible.map((rect) => rect.bottom));
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

export function shellOverlayOcclusionRect(overlay) {
  if (!overlay?.getBoundingClientRect) return null;
  const occluders = Array.from(overlay.querySelectorAll?.("[data-shell-overlay-occluder]") || []);
  return unionShellOverlayRects([
    overlay.getBoundingClientRect(),
    ...occluders.map((element) => element.getBoundingClientRect()),
  ]);
}

export function publishAvatarChatLayer(open, target = globalThis.window) {
  if (!target?.dispatchEvent || typeof globalThis.CustomEvent !== "function") return false;
  target.dispatchEvent(new CustomEvent(SHELL_OVERLAY_EVENT, {
    detail: { id: AVATAR_CHAT_OVERLAY_ID, open: Boolean(open), layer: "above-widgets" },
  }));
  return true;
}
