import { createChatComposer } from "./modules/chat-composer/chat-composer.js";
import { renderChatMarkdownTokens } from "./modules/chat-composer/chat-renderer.js";
import { runChatComposerTests } from "./modules/chat-composer/chat-composer.test.js";

const textarea = document.querySelector("#composerLabTextarea");
const overlay = document.querySelector("#composerLabOverlay");
const palette = document.querySelector("#composerLabPalette");
const preview = document.querySelector("#composerLabPreview");
const sent = document.querySelector("#composerLabSent");
const debug = document.querySelector("#composerLabDebug");
const testSummary = document.querySelector("#composerLabTestSummary");
const testList = document.querySelector("#composerLabTestList");

const diagnostics = {
  raw: "",
  selectionStart: 0,
  selectionEnd: 0,
  lastKey: "",
  lastInputType: "",
  lastBeforeInput: "",
  lastComposition: "",
  tokens: [],
  activeCommandQuery: "",
  selectedCommand: "",
  renderedHtml: "",
  renderedText: "",
  renderDurationMs: 0,
  rawChangedUnexpectedly: false,
};

const injectCases = [
  ["Inline", "`test`"],
  ["Adjacent", "`test``hello`"],
  ["Two spans", "`test` `hello`"],
  ["Block", "```test```"],
  ["Multiline block", "```\n  const x = 1;\n\n  console.log(x);\n```"],
  ["Mixed", "hello `code` **bold** *italic* ~~strike~~"],
  ["Quote", "> quote\n> `code` inside quote"],
  ["Links", "https://blablabla.com. blablabla.com, (www.blablabla.com)"],
  ["Unsafe HTML", "<img src=x onerror=alert(1)>\n<script>alert(1)</script>"],
  ["Slash", "/g"],
  ["Sentence slash", "look at /tmp/file"],
  ["Unicode", "`áéíçã 日本語 emoji 🚀`"],
  ["Long", `${"hello example.com ".repeat(180)}\n\`done\``],
];

function updateDebug() {
  debug.textContent = JSON.stringify({
    rawValue: diagnostics.raw,
    selectionStart: diagnostics.selectionStart,
    selectionEnd: diagnostics.selectionEnd,
    lastKey: diagnostics.lastKey,
    lastInputType: diagnostics.lastInputType,
    lastBeforeinputEvent: diagnostics.lastBeforeInput,
    lastCompositionEvent: diagnostics.lastComposition,
    parsedTokens: diagnostics.tokens,
    activeCommandQuery: diagnostics.activeCommandQuery,
    selectedCommand: diagnostics.selectedCommand,
    renderedHtml: diagnostics.renderedHtml,
    renderedText: diagnostics.renderedText,
    renderDurationMs: Number(diagnostics.renderDurationMs.toFixed(3)),
    rawValueChangedUnexpectedly: diagnostics.rawChangedUnexpectedly,
  }, null, 2);
}

const composer = createChatComposer({
  textarea,
  overlay,
  commandPaletteElement: palette,
  previewElement: preview,
  onSend(raw) {
    const message = renderChatMarkdownTokens(composer.tokens, { className: "chat-rendered-markdown" });
    message.dataset.raw = raw;
    sent.prepend(message);
    return true;
  },
  onUpdate(state) {
    diagnostics.raw = state.raw;
    diagnostics.selectionStart = state.selectionStart;
    diagnostics.selectionEnd = state.selectionEnd;
    diagnostics.tokens = state.tokens;
    diagnostics.renderedHtml = state.renderedHtml;
    diagnostics.renderedText = preview.textContent || "";
    diagnostics.renderDurationMs = state.renderDurationMs;
    diagnostics.rawChangedUnexpectedly = state.rawChangedUnexpectedly;
    diagnostics.activeCommandQuery = state.command.query || "";
    diagnostics.selectedCommand = state.command.selectedCommand?.name || "";
    updateDebug();
  },
  onCommandStateChange(state) {
    diagnostics.activeCommandQuery = state.query || "";
    diagnostics.selectedCommand = state.selectedCommand?.name || "";
    updateDebug();
  },
  onKeyState(event) {
    diagnostics.lastKey = [
      event.key,
      event.shiftKey ? "Shift" : "",
      event.ctrlKey ? "Ctrl" : "",
      event.metaKey ? "Meta" : "",
    ].filter(Boolean).join("+");
    updateDebug();
  },
  onInputState(event) {
    diagnostics.lastInputType = event.inputType || "";
    updateDebug();
  },
  onBeforeInputState(event) {
    diagnostics.lastBeforeInput = JSON.stringify({
      inputType: event.inputType || "",
      data: event.data || "",
      isComposing: Boolean(event.isComposing),
    });
    updateDebug();
  },
  onCompositionState(event) {
    diagnostics.lastComposition = JSON.stringify({
      type: event.type,
      data: event.data || "",
    });
    updateDebug();
  },
  onSelectionChange(selection) {
    diagnostics.selectionStart = selection.selectionStart;
    diagnostics.selectionEnd = selection.selectionEnd;
    diagnostics.activeCommandQuery = selection.command.query || "";
    diagnostics.selectedCommand = selection.command.selectedCommand?.name || "";
    updateDebug();
  },
});

document.querySelector("#composerLabInject").replaceChildren(
  ...injectCases.map(([label, value]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => composer.setValue(value, { focus: true }));
    return button;
  })
);

document.querySelectorAll("[data-caret]").forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.caret;
    const value = textarea.value;
    const position = mode === "end" ? value.length : mode === "middle" ? Math.floor(value.length / 2) : 0;
    textarea.focus();
    textarea.setSelectionRange(position, position);
    composer.update();
  });
});

document.querySelector("#composerLabToggleOverlay").addEventListener("click", () => {
  composer.overlay.setDisabled(!composer.overlay.disabled);
});

document.querySelector("#composerLabExport").addEventListener("click", () => {
  const report = {
    generatedAt: new Date().toISOString(),
    diagnostics,
    userAgent: navigator.userAgent,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `composer-diagnostics-${Date.now()}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});

function renderTests() {
  const results = runChatComposerTests();
  const passed = results.filter((result) => result.ok).length;
  testSummary.textContent = `${passed}/${results.length} passed`;
  testList.replaceChildren(
    ...results.map((result) => {
      const row = document.createElement("div");
      row.className = `composer-lab-test ${result.ok ? "pass" : "fail"}`;
      const status = document.createElement("span");
      status.textContent = result.ok ? "PASS" : "FAIL";
      const name = document.createElement("span");
      name.textContent = result.ok
        ? result.name
        : `${result.name}: ${result.error}`;
      row.append(status, name);
      return row;
    })
  );
}

document.querySelector("#composerLabRunTests").addEventListener("click", renderTests);
renderTests();
textarea.focus();
