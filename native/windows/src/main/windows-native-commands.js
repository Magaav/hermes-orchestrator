"use strict";

function createWindowsNativeCommands({ companion = () => null, desktop } = {}) {
  const operations = Object.freeze(["show_companion_overlay", "run_notepad_uia_canary", ...(desktop?.operations || [])]);

  const execute = async (type, payload = {}, commandId = "") => {
    if (type === "show_companion_overlay") {
      const overlay = companion();
      return { handled: true, result: overlay ? overlay.show() : { ok: false, error: "companion_overlay_unavailable" } };
    }
    if (type === "run_notepad_uia_canary") {
      return { handled: true, result: await desktop.control.runNotepadCanary(payload, commandId) };
    }
    if (desktop.operations.includes(type)) {
      return { handled: true, result: await desktop.control.execute(type, payload, commandId) };
    }
    return { handled: false, result: null };
  };

  return { execute, operations };
}

module.exports = { createWindowsNativeCommands };
