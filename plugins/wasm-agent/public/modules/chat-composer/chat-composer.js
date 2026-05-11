import {
  getSlashCommandContext,
  normalizeChatRawText,
  tokenizeChatMarkdown,
} from "./chat-tokenizer.js";
import {
  renderChatMarkdownTokens,
  renderTokensToHtml,
} from "./chat-renderer.js";
import { createChatOverlay } from "./chat-overlay.js";
import { createCommandPalette, DEFAULT_CHAT_COMMANDS } from "./chat-commands.js";

function clampSelectionIndex(textarea, value) {
  const length = textarea?.value?.length || 0;
  return Math.max(0, Math.min(length, Number(value) || 0));
}

function firstCommandWhitespace(raw, start) {
  for (let index = start; index < raw.length; index += 1) {
    if (/\s/.test(raw[index])) return index;
  }
  return raw.length;
}

function dispatchNativeInput(textarea, inputType = "insertReplacementText") {
  try {
    textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType }));
  } catch {
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

export function createChatComposer(options = {}) {
  const textarea = options.textarea;
  if (!textarea) throw new Error("createChatComposer requires a textarea.");
  const form = options.form || textarea.closest("form");
  const overlay = createChatOverlay({
    textarea,
    overlay: options.overlay,
    disabled: Boolean(options.disableOverlay),
  });
  const paletteFactory = options.createCommandPalette || createCommandPalette;
  const palette = paletteFactory({
    element: options.commandPaletteElement,
    commands: options.commands || DEFAULT_CHAT_COMMANDS,
    onSelect: insertCommand,
    onStateChange: (state) => {
      options.onCommandStateChange?.(state);
      textarea.setAttribute("aria-expanded", state.open ? "true" : "false");
    },
  });
  if (!options.commandPaletteElement && options.commandPaletteMount) {
    options.commandPaletteMount.append(palette.element);
  }

  let tokens = [];
  let renderDurationMs = 0;
  let renderFrame = 0;
  let composing = false;
  let destroyed = false;
  let submitting = false;
  let lastRawValue = textarea.value;

  textarea.classList.add("chat-composer-textarea");
  textarea.autocomplete = textarea.autocomplete || "off";
  textarea.setAttribute("aria-haspopup", "listbox");

  function currentCommandContext() {
    return getSlashCommandContext(textarea.value, textarea.selectionStart, textarea.selectionEnd, {
      composing,
      tokens,
    });
  }

  function updatePreview() {
    if (!options.previewElement) return;
    const rendered = renderChatMarkdownTokens(tokens, {
      className: options.previewClassName || "chat-rendered-markdown",
    });
    options.previewElement.replaceChildren(rendered);
  }

  function update(optionsForUpdate = {}) {
    if (destroyed) return;
    if (renderFrame) {
      cancelAnimationFrame(renderFrame);
      renderFrame = 0;
    }
    const startedAt = performance.now?.() || Date.now();
    const raw = normalizeChatRawText(textarea.value);
    tokens = tokenizeChatMarkdown(raw);
    overlay.render(raw, tokens);
    updatePreview();
    palette.update(currentCommandContext());
    renderDurationMs = (performance.now?.() || Date.now()) - startedAt;
    const rawChangedUnexpectedly = !optionsForUpdate.rawChangeExpected && raw !== lastRawValue;
    lastRawValue = raw;
    options.onUpdate?.({
      raw,
      tokens,
      selectionStart: textarea.selectionStart,
      selectionEnd: textarea.selectionEnd,
      renderDurationMs,
      renderedHtml: renderTokensToHtml(tokens),
      rawChangedUnexpectedly,
      command: palette.state,
    });
  }

  function scheduleUpdate(rawChangeExpected = false) {
    if (destroyed) return;
    if (!globalThis.requestAnimationFrame) {
      update({ rawChangeExpected });
      return;
    }
    if (renderFrame) return;
    renderFrame = requestAnimationFrame(() => {
      renderFrame = 0;
      update({ rawChangeExpected });
    });
  }

  function setValue(value, optionsForSet = {}) {
    const next = String(value ?? "");
    textarea.value = next;
    const selection = clampSelectionIndex(textarea, optionsForSet.selectionStart ?? next.length);
    textarea.setSelectionRange(selection, clampSelectionIndex(textarea, optionsForSet.selectionEnd ?? selection));
    if (optionsForSet.focus) textarea.focus();
    dispatchNativeInput(textarea, optionsForSet.inputType || "insertReplacementText");
    update({ rawChangeExpected: true });
  }

  function clear(optionsForClear = {}) {
    setValue("", { ...optionsForClear, selectionStart: 0, selectionEnd: 0, inputType: "deleteByCut" });
  }

  function insertCommand(command) {
    const raw = textarea.value;
    const insertText = String(command?.insertText || command?.name || "");
    if (!insertText) return;
    const prefixEnd = firstCommandWhitespace(raw, 1);
    const replaceEnd = /\s/.test(raw[prefixEnd] || "") ? prefixEnd + 1 : prefixEnd;
    const next = `${insertText}${raw.slice(replaceEnd)}`;
    textarea.value = next;
    const caret = insertText.length;
    textarea.setSelectionRange(caret, caret);
    textarea.focus();
    dispatchNativeInput(textarea, "insertReplacementText");
    update({ rawChangeExpected: true });
  }

  async function submit() {
    if (submitting) return false;
    const raw = textarea.value;
    const canSubmit = options.canSubmit
      ? Boolean(options.canSubmit(raw))
      : Boolean(raw.trim());
    if (!canSubmit) return false;
    submitting = true;
    try {
      const accepted = await options.onSend?.(raw);
      if (accepted !== false) clear({ focus: true });
      return accepted !== false;
    } finally {
      submitting = false;
    }
  }

  function handleKeyDown(event) {
    options.onKeyState?.(event);
    if (composing || event.isComposing) return;
    if (palette.handleKeyDown(event)) return;
    if (event.key !== "Enter") return;
    if (event.shiftKey) return;
    if (event.altKey) return;
    if (event.ctrlKey || event.metaKey || (!event.ctrlKey && !event.metaKey)) {
      event.preventDefault();
      void submit();
    }
  }

  function handleBeforeInput(event) {
    options.onBeforeInputState?.(event);
  }

  function handleInput(event) {
    options.onInputState?.(event);
    scheduleUpdate(true);
  }

  function handleSelectionChange() {
    if (document.activeElement !== textarea) return;
    palette.update(currentCommandContext());
    options.onSelectionChange?.({
      selectionStart: textarea.selectionStart,
      selectionEnd: textarea.selectionEnd,
      command: palette.state,
    });
  }

  function handleComposition(event) {
    composing = event.type !== "compositionend";
    options.onCompositionState?.(event);
    if (composing) {
      palette.close();
    } else {
      scheduleUpdate(true);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    void submit();
  }

  textarea.addEventListener("keydown", handleKeyDown);
  textarea.addEventListener("beforeinput", handleBeforeInput);
  textarea.addEventListener("input", handleInput);
  textarea.addEventListener("select", handleSelectionChange);
  textarea.addEventListener("click", handleSelectionChange);
  textarea.addEventListener("keyup", handleSelectionChange);
  textarea.addEventListener("compositionstart", handleComposition);
  textarea.addEventListener("compositionupdate", handleComposition);
  textarea.addEventListener("compositionend", handleComposition);
  document.addEventListener("selectionchange", handleSelectionChange);
  form?.addEventListener("submit", handleSubmit);

  update({ rawChangeExpected: true });

  return {
    textarea,
    palette,
    overlay,
    submit,
    update,
    scheduleUpdate,
    setValue,
    clear,
    get value() {
      return textarea.value;
    },
    get tokens() {
      return tokens.slice();
    },
    get renderDurationMs() {
      return renderDurationMs;
    },
    destroy() {
      destroyed = true;
      if (renderFrame) cancelAnimationFrame(renderFrame);
      textarea.removeEventListener("keydown", handleKeyDown);
      textarea.removeEventListener("beforeinput", handleBeforeInput);
      textarea.removeEventListener("input", handleInput);
      textarea.removeEventListener("select", handleSelectionChange);
      textarea.removeEventListener("click", handleSelectionChange);
      textarea.removeEventListener("keyup", handleSelectionChange);
      textarea.removeEventListener("compositionstart", handleComposition);
      textarea.removeEventListener("compositionupdate", handleComposition);
      textarea.removeEventListener("compositionend", handleComposition);
      document.removeEventListener("selectionchange", handleSelectionChange);
      form?.removeEventListener("submit", handleSubmit);
      palette.close();
    },
  };
}

export { DEFAULT_CHAT_COMMANDS };
