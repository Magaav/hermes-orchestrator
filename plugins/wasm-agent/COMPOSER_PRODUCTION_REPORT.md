# Chat Composer Production Report

## Root Cause

The previous production composer used a `contenteditable` element as both the
input surface and the rendered Markdown surface. It rendered editable DOM nodes
for inline code, serialized that DOM back to Markdown on send, inserted
zero-width boundary text around code spans, restored the caret manually, and
intercepted `beforeinput`, Backspace, Delete, ArrowLeft, and copy behavior.

That made the rendered DOM, not the raw string, part of the editing model.
Backticks and repeated spans could become DOM boundaries instead of ordinary
characters, so native browser editing no longer had a stable source of truth.
The observed failures followed from that: closing backticks needed later input
to settle, cursor movement around code spans could move text, and deletion could
unwrap or delete rendered structures instead of one raw character.

## Replacement

The production composer is now a decorated plain-text textarea subsystem:

- `textarea` owns raw text, caret, selection, paste, copy, undo, redo, IME, and mobile editing.
- `tokenizeChatMarkdown(rawText)` reads the raw string and never mutates it.
- `renderChatMarkdownTokens(tokens)` renders safe preview/sent-message HTML.
- `createChatComposer(options)` wires textarea, overlay, Enter/Shift+Enter/Ctrl/Cmd+Enter, and send behavior.
- `createCommandPalette(options)` handles data-driven slash commands without mutating text until selection.
- `/composer-lab` exercises the same subsystem with debug state, live preview, sent preview, edge-case buttons, diagnostics export, and a test runner.

Keyboard behavior:

- Enter sends when the command palette is closed.
- Shift+Enter inserts a newline.
- Ctrl/Cmd+Enter sends as an explicit equivalent.
- Enter selects the highlighted command only while the command palette is open.
- IME composition does not send while composition is active.

## Production Files Changed

- `public/app.js`: imports and consumes the new tokenizer, renderer, composer, and command palette; production send flow stores raw text; old contenteditable handlers are removed/bypassed.
- `public/index.html`: replaces the contenteditable composer with textarea, overlay, accessible label, and command palette mount.
- `public/styles.css`: adapts production composer sizing/background/focus styles to the textarea-overlay structure.
- `public/modules/chat-composer/chat-tokenizer.js`: deterministic V1 tokenizer.
- `public/modules/chat-composer/chat-renderer.js`: safe token renderer and overlay HTML renderer.
- `public/modules/chat-composer/chat-overlay.js`: pointer-transparent textarea mirror.
- `public/modules/chat-composer/chat-commands.js`: data-driven slash command registry/palette.
- `public/modules/chat-composer/chat-composer.js`: reusable composer controller.
- `public/modules/chat-composer/chat-composer.css`: shared production/lab styles.
- `public/modules/chat-composer/chat-composer.test.js`: browser-shareable tokenizer/renderer/command tests.
- `public/composer-lab.html` and `public/composer-lab.js`: production lab.
- `public/sw.js`: caches the lab and composer modules.
- `server/static_server.py`: routes `/composer-lab` and allows composer module CSS.
- `tests/chat_composer_modules.test.mjs`: Node VM module regression tests.
- `tests/agent_input_editor.test.py`: browser editing regression tests for the textarea composer.
- `tests/wasm_agent_smoke.test.js`: static production integration assertions.
- `README.md` and `DESIGN.md`: updated composer contract.

## Verification

Automated checks run:

- `node --experimental-vm-modules plugins/wasm-agent/tests/chat_composer_modules.test.mjs`
- `node plugins/wasm-agent/tests/wasm_agent_smoke.test.js`
- `python3 plugins/wasm-agent/tests/agent_input_editor.test.py`
- `python3 -m py_compile plugins/wasm-agent/server/static_server.py`

Live static checks run on `http://127.0.0.1:8878`:

- `/composer-lab` served successfully.
- `/modules/chat-composer/chat-composer.css` served successfully.
- `/` served production markup with textarea, overlay, and command palette, and without `contenteditable`.
- Headless Chromium loaded `/composer-lab` and the lab test panel reported `32/32 passed`.

## Critical Matrix Status

Passed by automated coverage or production browser smoke:

- Inline code closes and decorates immediately without a trailing space.
- Backspace after final backtick deletes one raw character.
- Arrow movement does not mutate raw value.
- Adjacent inline code spans preserve raw source.
- Code blocks, quotes, bold, italic, strike, Unicode, fuzz strings, long messages, and unsafe HTML are tokenized/rendered safely.
- Explicit and bare links linkify safely outside code, strip trailing punctuation, and use safe `target`/`rel`.
- Unsafe protocols are not clickable.
- Slash command palette opens only for leading prefixes, filters `/g` to `/goal`, and inserts `/goal ` with the caret after the trailing space.
- Text paste remains native; image paste still routes to the existing attachment flow.
- Sent messages render from the same safe token renderer used by preview/lab.

## Removed Or Bypassed Old Hacks

- Removed production `contenteditable` composer markup.
- Removed active DOM-based composer source serialization.
- Removed active zero-width boundary character logic.
- Removed active manual inline-code caret navigation and backspace/delete hacks.
- Removed active Markdown-trigger mutation/rendering of the editable input DOM.
- Removed text paste interception that rewrote pasted text through `execCommand`.

## Remaining Limitations

V1 intentionally supports only the requested chat syntax: inline code, triple
backtick code blocks, bold, italic, strike, line-start quotes, links, line
breaks, and slash command prefix detection. Tables, headings, lists, mentions,
agent routing, and richer command arguments are left for later modules on top
of the same raw-text contract.
