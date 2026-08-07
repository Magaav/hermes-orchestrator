export const SHELL_OVERLAY_EVENT = "wasm-agent:shell-overlay";
export const AVATAR_CHAT_OVERLAY_ID = "wasm-agent-avatar-chat";

export function publishAvatarChatLayer(open, target = globalThis.window) {
  if (!target?.dispatchEvent || typeof globalThis.CustomEvent !== "function") return false;
  target.dispatchEvent(new CustomEvent(SHELL_OVERLAY_EVENT, {
    detail: { id: AVATAR_CHAT_OVERLAY_ID, open: Boolean(open), layer: "above-widgets" },
  }));
  return true;
}
