const NATIVE_COMPANION_QUERY = "overlay";
export const NATIVE_COMPANION_TOPMOST_POLICY = Object.freeze({ enabled: true, interval_ms: 750 });

export function isNativeCompanionWindow(locationLike = globalThis.location) {
  try {
    const url = new URL(String(locationLike?.href || locationLike || ""));
    return url.searchParams.get("native") === "electron"
      && url.searchParams.get("companion") === NATIVE_COMPANION_QUERY;
  } catch {
    return false;
  }
}

export function isAgentCompactViewport(compact, locationLike = globalThis.location) {
  return !isNativeCompanionWindow(locationLike) && Boolean(compact);
}

export function companionWindowMode(open, layout = {}) {
  return {
    mode: open ? "expanded" : "compact",
    panel_width: Math.max(320, Math.min(860, Math.round(Number(layout.panelWidth || layout.width) || 430))),
    panel_height: Math.max(420, Math.min(1200, Math.round(Number(layout.panelHeight || layout.height) || 620))),
  };
}

export function nativeCompanionPanelSize(layout = {}, locationLike = globalThis.location) {
  if (!isNativeCompanionWindow(locationLike)) return null;
  const width = Math.round(Number(layout.panelWidth || layout.width) || 0);
  const height = Math.round(Number(layout.panelHeight || layout.height) || 0);
  const compactClampRegression = width === 320 && height === 420;
  const mode = companionWindowMode(true, compactClampRegression ? {} : layout);
  return { width: mode.panel_width, height: mode.panel_height };
}

export function syncNativeCompanionOpenState(open, layout = {}, root = globalThis.document?.documentElement) {
  if (!isNativeCompanionWindow()) return false;
  if (root?.dataset) root.dataset.wasmAgentCompanion = "true";
  const bridge = globalThis.wasmAgentNative?.companion;
  if (!bridge?.setMode) return false;
  void bridge.setMode(companionWindowMode(open, layout));
  return true;
}

function nativeCompanionBridge() {
  return isNativeCompanionWindow() ? globalThis.wasmAgentNative?.companion : null;
}

export function syncNativeCompanionTopmostPolicy(policy = NATIVE_COMPANION_TOPMOST_POLICY) {
  const bridge = nativeCompanionBridge();
  if (!bridge?.configureTopmost) return false;
  void bridge.configureTopmost(policy);
  return true;
}

const INTERACTIVE_DRAG_SELECTOR = "button,input,textarea,select,s-select,a";
let nativeMoveSequence = 0;

export function installNativeWindowDragging(handle, { body, state, isPrimaryPointer, recordUserEvent, target, shouldStart = () => true }) {
  const bridge = nativeCompanionBridge();
  if (!bridge?.moveBy || !handle) return false;
  let finishActiveMove = null;
  handle.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event) || !shouldStart(event)) return;
    finishActiveMove?.();
    event.preventDefault();
    const startX = Number(event.screenX || 0);
    const startY = Number(event.screenY || 0);
    const pointerId = event.pointerId;
    let previousX = startX;
    let previousY = startY;
    let pendingX = 0;
    let pendingY = 0;
    let frame = 0;
    let moved = false;
    let finished = false;
    const sessionId = `pointer-${++nativeMoveSequence}`;
    const sessionMove = typeof bridge.beginMove === "function" && typeof bridge.updateMove === "function";
    body.classList.add("is-agent-dragging");
    try { handle.setPointerCapture(event.pointerId); } catch { /* Window listeners keep native dragging alive. */ }
    if (sessionMove) bridge.beginMove({ session_id: sessionId, pointer_x: startX, pointer_y: startY });
    const flush = () => {
      frame = 0;
      if (!moved || finished) {
        pendingX = 0;
        pendingY = 0;
        return;
      }
      if (sessionMove) {
        pendingX = 0;
        pendingY = 0;
        bridge.updateMove({ session_id: sessionId, pointer_x: previousX, pointer_y: previousY });
        return;
      }
      const x = Math.round(pendingX);
      const y = Math.round(pendingY);
      pendingX = 0;
      pendingY = 0;
      if (x || y) bridge.moveBy({ x, y });
    };
    const move = (moveEvent) => {
      if (moveEvent.pointerId !== pointerId) return;
      const x = Number(moveEvent.screenX || 0);
      const y = Number(moveEvent.screenY || 0);
      pendingX += x - previousX;
      pendingY += y - previousY;
      previousX = x;
      previousY = y;
      if (Math.hypot(x - startX, y - startY) > 3) moved = true;
      if (!frame) frame = globalThis.requestAnimationFrame(flush);
    };
    const end = (endEvent) => {
      if (endEvent?.pointerId != null && endEvent.pointerId !== pointerId) return;
      if (finished) return;
      finished = true;
      finishActiveMove = null;
      body.classList.remove("is-agent-dragging");
      globalThis.removeEventListener("pointermove", move);
      globalThis.removeEventListener("pointerup", end);
      globalThis.removeEventListener("pointercancel", end);
      globalThis.removeEventListener("blur", end);
      handle.removeEventListener("lostpointercapture", end);
      if (frame) {
        globalThis.cancelAnimationFrame(frame);
        frame = 0;
      }
      if (moved) {
        if (sessionMove) bridge.updateMove({ session_id: sessionId, pointer_x: previousX, pointer_y: previousY });
        else if (pendingX || pendingY) bridge.moveBy({ x: Math.round(pendingX), y: Math.round(pendingY) });
      }
      bridge.endMove?.({ moved, session_id: sessionId, pointer_x: previousX, pointer_y: previousY });
      if (!moved) return;
      state.agentDragSuppressClick = true;
      globalThis.setTimeout(() => { state.agentDragSuppressClick = false; }, 0);
      recordUserEvent("agent.dragged", {
        target,
        summary: "Moved native assistant companion",
        data: { native_window: true },
      });
    };
    finishActiveMove = end;
    globalThis.addEventListener("pointermove", move);
    globalThis.addEventListener("pointerup", end);
    globalThis.addEventListener("pointercancel", end);
    globalThis.addEventListener("blur", end);
    handle.addEventListener("lostpointercapture", end);
  });
  return true;
}

export function installAgentDragging({ avatarButton, overlay, body, state, isPrimaryPointer, clampAgentLayout, placeAgentPanel, saveAgentLayout, recordUserEvent }) {
  if (installNativeWindowDragging(avatarButton, { body, state, isPrimaryPointer, recordUserEvent, target: "agent-overlay" })) return;
  avatarButton.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event)) return;
    event.preventDefault();
    const start = overlay.getBoundingClientRect();
    const offsetX = event.clientX - start.left;
    const offsetY = event.clientY - start.top;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    body.classList.add("is-agent-dragging");
    try { avatarButton.setPointerCapture(event.pointerId); } catch { /* Window listeners keep dragging alive. */ }
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 3) moved = true;
      const { left, top } = clampAgentLayout({ left: moveEvent.clientX - offsetX, top: moveEvent.clientY - offsetY });
      Object.assign(overlay.style, { left: `${left}px`, top: `${top}px`, right: "auto", bottom: "auto" });
      state.agentLayout = { left, top };
      placeAgentPanel();
    };
    const end = () => {
      body.classList.remove("is-agent-dragging");
      globalThis.removeEventListener("pointermove", move);
      globalThis.removeEventListener("pointerup", end);
      globalThis.removeEventListener("pointercancel", end);
      state.agentLayout = clampAgentLayout(state.agentLayout);
      Object.assign(overlay.style, { left: `${state.agentLayout.left}px`, top: `${state.agentLayout.top}px` });
      placeAgentPanel();
      saveAgentLayout();
      if (!moved) return;
      state.agentDragSuppressClick = true;
      globalThis.setTimeout(() => { state.agentDragSuppressClick = false; }, 0);
      recordUserEvent("agent.dragged", { target: "agent-overlay", summary: "Moved embedded assistant avatar", data: state.agentLayout });
    };
    globalThis.addEventListener("pointermove", move);
    globalThis.addEventListener("pointerup", end, { once: true });
    globalThis.addEventListener("pointercancel", end, { once: true });
  });
}

export function installAgentPanelDragging({ panel, body, state, isPrimaryPointer, moveAgentGroupFromPanelRect, placeAgentPanel, saveAgentLayout, recordUserEvent }) {
  const handle = panel?.querySelector(".agent-panel-head");
  if (!handle) return;
  if (installNativeWindowDragging(handle, {
    body,
    state,
    isPrimaryPointer,
    recordUserEvent,
    target: "agent-panel",
    shouldStart: (event) => !event.target.closest?.(INTERACTIVE_DRAG_SELECTOR),
  })) return;
  handle.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event) || event.target.closest("button,input,textarea,select,s-select,a")) return;
    event.preventDefault();
    const panelRect = panel.getBoundingClientRect();
    const offsetX = event.clientX - panelRect.left;
    const offsetY = event.clientY - panelRect.top;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    body.classList.add("is-agent-dragging");
    try { handle.setPointerCapture(event.pointerId); } catch { /* Window listeners keep dragging alive. */ }
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 3) moved = true;
      moveAgentGroupFromPanelRect(moveEvent.clientX - offsetX, moveEvent.clientY - offsetY, panel.offsetWidth || 430, panel.offsetHeight || 620);
    };
    const end = () => {
      body.classList.remove("is-agent-dragging");
      globalThis.removeEventListener("pointermove", move);
      globalThis.removeEventListener("pointerup", end);
      globalThis.removeEventListener("pointercancel", end);
      placeAgentPanel();
      saveAgentLayout();
      if (moved) recordUserEvent("agent.dragged", { target: "agent-overlay", summary: "Moved embedded assistant avatar and chat together", data: state.agentLayout });
    };
    globalThis.addEventListener("pointermove", move);
    globalThis.addEventListener("pointerup", end, { once: true });
    globalThis.addEventListener("pointercancel", end, { once: true });
  });
}

if (isNativeCompanionWindow() && globalThis.document?.documentElement?.dataset) {
  globalThis.document.documentElement.dataset.wasmAgentCompanion = "true";
  syncNativeCompanionTopmostPolicy();
}
