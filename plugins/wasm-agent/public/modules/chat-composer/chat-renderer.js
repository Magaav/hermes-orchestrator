import { tokenizeChatMarkdown } from "./chat-tokenizer.js";

const RENDER_CLASS = "chat-rendered-markdown";
const OVERLAY_CLASS = "chat-composer-overlay-content";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeLinkHref(value) {
  const href = String(value ?? "").trim();
  if (!href) return "";
  try {
    const base = globalThis.location?.href || "https://wasm-agent.local/";
    const url = new URL(href, base);
    if (url.protocol === "http:" || url.protocol === "https:") return url.href;
  } catch {
    return "";
  }
  return "";
}

function renderChildrenToHtml(tokens) {
  return renderTokensToHtml(tokens, { fragment: true });
}

function renderTableCellToHtml(cell, tagName, alignment) {
  const align = ["left", "center", "right"].includes(alignment) ? alignment : "left";
  const alignAttribute = align === "left" ? "" : ` style="text-align: ${align}"`;
  const children = Array.isArray(cell?.children)
    ? cell.children
    : [{ type: "text", value: cell?.value || "", raw: cell?.value || "" }];
  return `<${tagName}${alignAttribute}>${renderChildrenToHtml(children)}</${tagName}>`;
}

function renderTableToHtml(token) {
  const headers = Array.isArray(token.headers) ? token.headers : [];
  const rows = Array.isArray(token.rows) ? token.rows : [];
  const alignments = Array.isArray(token.alignments) ? token.alignments : [];
  if (!headers.length) return escapeHtml(token.raw || "");
  const head = headers
    .map((cell, index) => renderTableCellToHtml(cell, "th", alignments[index]))
    .join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell, index) => renderTableCellToHtml(cell, "td", alignments[index])).join("")}</tr>`)
    .join("");
  const bodyHtml = body ? `<tbody>${body}</tbody>` : "";
  return `<div class="agent-markdown-table-wrap"><table><thead><tr>${head}</tr></thead>${bodyHtml}</table></div>`;
}

function isBlockToken(token) {
  return ["code_block", "heading", "table", "quote_line"].includes(token?.type);
}

function renderTokenToHtml(token) {
  if (!token || typeof token !== "object") return "";
  if (token.type === "text") return escapeHtml(token.value);
  if (token.type === "newline") return "<br>";
  if (token.type === "inline_code") return `<code>${escapeHtml(token.value)}</code>`;
  if (token.type === "code_block") return `<pre><code>${escapeHtml(token.value)}</code></pre>`;
  if (token.type === "heading") {
    const level = Math.max(1, Math.min(6, Number(token.level) || 2));
    return `<h${level}>${renderChildrenToHtml(token.children)}</h${level}>`;
  }
  if (token.type === "table") return renderTableToHtml(token);
  if (token.type === "bold") return `<strong>${renderChildrenToHtml(token.children)}</strong>`;
  if (token.type === "italic") return `<em>${renderChildrenToHtml(token.children)}</em>`;
  if (token.type === "strike") return `<s>${renderChildrenToHtml(token.children)}</s>`;
  if (token.type === "link") {
    const href = safeLinkHref(token.href);
    if (!href) return escapeHtml(token.value);
    return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(token.value)}</a>`;
  }
  if (token.type === "quote_line") return renderChildrenToHtml(token.children);
  return escapeHtml(token.raw || token.value || "");
}

function renderQuoteBlock(tokens, startIndex) {
  const lines = [];
  let index = startIndex;
  while (index < tokens.length) {
    const token = tokens[index];
    if (token?.type !== "quote_line") break;
    lines.push(renderChildrenToHtml(token.children));
    index += 1;
    if (tokens[index]?.type === "newline" && tokens[index + 1]?.type === "quote_line") {
      index += 1;
      continue;
    }
    break;
  }
  return {
    html: `<blockquote>${lines.join("<br>") || "<br>"}</blockquote>`,
    nextIndex: index,
  };
}

export function renderTokensToHtml(tokens, options = {}) {
  const items = Array.isArray(tokens) ? tokens : [];
  let html = "";
  for (let index = 0; index < items.length;) {
    const token = items[index];
    if (token?.type === "quote_line") {
      const quote = renderQuoteBlock(items, index);
      html += quote.html;
      index = quote.nextIndex;
      if (items[index]?.type === "newline") index += 1;
      continue;
    }
    html += renderTokenToHtml(token);
    index += 1;
    if (isBlockToken(token) && items[index]?.type === "newline") index += 1;
  }
  if (options.fragment) return html;
  return `<div class="${RENDER_CLASS}">${html}</div>`;
}

function overlaySpan(className, text) {
  return `<span class="${className}">${escapeHtml(text)}</span>`;
}

function renderOverlayToken(token) {
  if (!token || typeof token !== "object") return "";
  if (token.type === "text" || token.type === "newline") return escapeHtml(token.raw || token.value || "");
  if (token.type === "inline_code") {
    if (!token.value) return overlaySpan("chat-md-empty-inline-code", "``");
    return [
      overlaySpan("chat-md-marker", "`"),
      overlaySpan("chat-md-inline-code", token.value),
      overlaySpan("chat-md-marker", "`"),
    ].join("");
  }
  if (token.type === "code_block") {
    return [
      overlaySpan("chat-md-fence", "```"),
      overlaySpan("chat-md-code-block", token.value),
      overlaySpan("chat-md-fence", "```"),
    ].join("");
  }
  if (token.type === "bold") return overlaySpan("chat-md-bold", token.raw);
  if (token.type === "italic") return overlaySpan("chat-md-italic", token.raw);
  if (token.type === "strike") return overlaySpan("chat-md-strike", token.raw);
  if (token.type === "link") return overlaySpan("chat-md-link", token.raw);
  if (token.type === "quote_line") return `${overlaySpan("chat-md-quote-marker", ">")}${escapeHtml(token.raw.startsWith("> ") ? " " : "")}${overlaySpan("chat-md-quote", token.value)}`;
  return escapeHtml(token.raw || token.value || "");
}

export function renderOverlayTokensToHtml(tokens, rawText = "") {
  const raw = String(rawText ?? "");
  const html = (Array.isArray(tokens) ? tokens : []).map(renderOverlayToken).join("");
  const finalPad = raw.endsWith("\n") ? "\n " : "";
  return `<div class="${OVERLAY_CLASS}" aria-hidden="true">${html}${escapeHtml(finalPad)}</div>`;
}

export function renderChatMarkdownTokens(tokens, options = {}) {
  const doc = options.document || document;
  const wrap = doc.createElement("div");
  wrap.className = options.className || RENDER_CLASS;
  wrap.innerHTML = renderTokensToHtml(tokens, { fragment: true });
  return wrap;
}

export function renderChatMarkdown(rawText, options = {}) {
  return renderChatMarkdownTokens(tokenizeChatMarkdown(rawText), options);
}

export function renderChatMarkdownToHtml(rawText) {
  return renderTokensToHtml(tokenizeChatMarkdown(rawText));
}

export function chatTokensToPlainText(tokens) {
  return (Array.isArray(tokens) ? tokens : []).map((token) => {
    if (token.type === "quote_line") return token.raw;
    return token.raw || token.value || "";
  }).join("");
}

export { escapeHtml, safeLinkHref };
