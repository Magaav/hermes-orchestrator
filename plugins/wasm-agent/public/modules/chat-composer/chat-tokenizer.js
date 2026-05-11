const COMMAND_PREFIX_PATTERN = /^\S*/;
const EXPLICIT_URL_PREFIXES = ["https://", "http://"];
const UNSAFE_PROTOCOL_PATTERN = /^(?:javascript|data|vbscript|file):/i;

function normalizeRawText(value) {
  return String(value ?? "").replace(/\r\n?/g, "\n");
}

function pushText(tokens, value, start, end) {
  if (!value) return;
  const previous = tokens[tokens.length - 1];
  if (previous?.type === "text" && previous.end === start) {
    previous.value += value;
    previous.raw += value;
    previous.end = end;
    return;
  }
  tokens.push({ type: "text", value, raw: value, start, end });
}

function isLineStart(text, index) {
  return index === 0 || text[index - 1] === "\n";
}

function lineEndIndex(text, index) {
  const next = text.indexOf("\n", index);
  return next === -1 ? text.length : next;
}

function isBoundaryBeforeLink(text, index) {
  if (index <= 0) return true;
  const previous = text[index - 1] || "";
  return !/[A-Za-z0-9@._-]/.test(previous);
}

function stripTrailingLinkPunctuation(value) {
  let link = value;
  let trailing = "";
  while (link) {
    const last = link[link.length - 1];
    if (".,;:!?".includes(last)) {
      trailing = last + trailing;
      link = link.slice(0, -1);
      continue;
    }
    if (last === ")" && !link.includes("(")) {
      trailing = last + trailing;
      link = link.slice(0, -1);
      continue;
    }
    if (last === "]" && !link.includes("[")) {
      trailing = last + trailing;
      link = link.slice(0, -1);
      continue;
    }
    break;
  }
  return { link, trailing };
}

function consumeUrlCandidate(text, index, explicit) {
  let end = index;
  const max = text.length;
  while (end < max) {
    const char = text[end];
    if (/\s/.test(char) || char === "<" || char === ">" || char === '"' || char === "'") break;
    end += 1;
  }
  if (end <= index) return null;
  const rawCandidate = text.slice(index, end);
  const { link, trailing } = stripTrailingLinkPunctuation(rawCandidate);
  if (!link || UNSAFE_PROTOCOL_PATTERN.test(link)) return null;
  if (explicit) {
    try {
      const url = new URL(link);
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    } catch {
      return null;
    }
    return {
      raw: link,
      href: link,
      end: index + link.length,
      trailing,
    };
  }
  const href = `https://${link}`;
  try {
    const url = new URL(href);
    if (!isPlausibleBareDomain(url.hostname)) return null;
  } catch {
    return null;
  }
  return {
    raw: link,
    href,
    end: index + link.length,
    trailing,
  };
}

function isPlausibleBareDomain(hostname) {
  const host = String(hostname || "").toLowerCase();
  if (!host || host.includes("@") || host.includes("_")) return false;
  const labels = host.split(".");
  if (labels.length < 2) return false;
  const tld = labels[labels.length - 1];
  if (!/^[a-z]{2,63}$/.test(tld)) return false;
  return labels.every((label) => (
    label.length > 0
    && label.length <= 63
    && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label)
  ));
}

function bareDomainCandidateStartsAt(text, index) {
  if (!isBoundaryBeforeLink(text, index)) return false;
  if (!/[A-Za-z0-9]/.test(text[index] || "")) return false;
  const rest = text.slice(index);
  if (/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(rest)) return false;
  const domain = rest.match(/^(?:www\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?=$|[/?#:]|[.,;:!?)\]\s])/);
  return Boolean(domain);
}

function linkTokenAt(text, index) {
  if (!isBoundaryBeforeLink(text, index)) return null;
  const lower = text.slice(index, index + 8).toLowerCase();
  const explicitPrefix = EXPLICIT_URL_PREFIXES.find((prefix) => lower.startsWith(prefix));
  if (explicitPrefix) {
    const explicit = consumeUrlCandidate(text, index, true);
    if (!explicit) return null;
    return {
      type: "link",
      value: explicit.raw,
      raw: explicit.raw,
      href: explicit.href,
      start: index,
      end: explicit.end,
    };
  }
  if (!bareDomainCandidateStartsAt(text, index)) return null;
  const bare = consumeUrlCandidate(text, index, false);
  if (!bare) return null;
  return {
    type: "link",
    value: bare.raw,
    raw: bare.raw,
    href: bare.href,
    start: index,
    end: bare.end,
  };
}

function findClosingMarker(text, marker, start) {
  const end = text.indexOf(marker, start + marker.length);
  return end >= 0 ? end : -1;
}

function tokenizeFormatted(text, offset, marker, type, baseOffset = 0) {
  const close = findClosingMarker(text, marker, offset);
  if (close < 0) return null;
  const contentStart = offset + marker.length;
  const contentEnd = close;
  const end = close + marker.length;
  const value = text.slice(contentStart, contentEnd);
  return {
    type,
    marker,
    value,
    raw: text.slice(offset, end),
    children: tokenizeInline(value, baseOffset + contentStart),
    start: baseOffset + offset,
    end: baseOffset + end,
    contentStart: baseOffset + contentStart,
    contentEnd: baseOffset + contentEnd,
  };
}

function tokenizeInline(text, baseOffset = 0) {
  const tokens = [];
  let index = 0;
  while (index < text.length) {
    const absolute = baseOffset + index;
    const char = text[index];
    if (char === "\n") {
      tokens.push({ type: "newline", value: "\n", raw: "\n", start: absolute, end: absolute + 1 });
      index += 1;
      continue;
    }

    if (char === "`" && !text.startsWith("```", index)) {
      const close = text.indexOf("`", index + 1);
      if (close >= 0) {
        const end = close + 1;
        tokens.push({
          type: "inline_code",
          marker: "`",
          value: text.slice(index + 1, close),
          raw: text.slice(index, end),
          start: absolute,
          end: baseOffset + end,
          contentStart: absolute + 1,
          contentEnd: baseOffset + close,
        });
        index = end;
        continue;
      }
    }

    if (text.startsWith("~~", index)) {
      const token = tokenizeFormatted(text, index, "~~", "strike", baseOffset);
      if (token) {
        tokens.push(token);
        index = token.end - baseOffset;
        continue;
      }
    }

    if (text.startsWith("**", index)) {
      const token = tokenizeFormatted(text, index, "**", "bold", baseOffset);
      if (token) {
        tokens.push(token);
        index = token.end - baseOffset;
        continue;
      }
    }

    if (char === "*" && text[index + 1] !== "*") {
      const token = tokenizeFormatted(text, index, "*", "italic", baseOffset);
      if (token) {
        tokens.push(token);
        index = token.end - baseOffset;
        continue;
      }
    }

    const link = linkTokenAt(text, index);
    if (link) {
      link.start += baseOffset;
      link.end += baseOffset;
      tokens.push(link);
      index = link.end - baseOffset;
      continue;
    }

    pushText(tokens, char, absolute, absolute + 1);
    index += 1;
  }
  return tokens;
}

function tokenizeTopLevel(text) {
  const tokens = [];
  let index = 0;
  while (index < text.length) {
    if (text.startsWith("```", index)) {
      const close = text.indexOf("```", index + 3);
      if (close >= 0) {
        const end = close + 3;
        tokens.push({
          type: "code_block",
          marker: "```",
          value: text.slice(index + 3, close),
          raw: text.slice(index, end),
          start: index,
          end,
          contentStart: index + 3,
          contentEnd: close,
        });
        index = end;
        continue;
      }
      pushText(tokens, text.slice(index), index, text.length);
      break;
    }

    if (isLineStart(text, index) && text[index] === ">") {
      const end = lineEndIndex(text, index);
      const raw = text.slice(index, end);
      const contentOffset = raw[1] === " " ? 2 : 1;
      const value = raw.slice(contentOffset);
      tokens.push({
        type: "quote_line",
        marker: ">",
        value,
        raw,
        children: tokenizeInline(value, index + contentOffset),
        start: index,
        end,
        contentStart: index + contentOffset,
        contentEnd: end,
      });
      index = end;
      continue;
    }

    const nextFence = text.indexOf("```", index + 1);
    const nextQuote = (() => {
      let cursor = index;
      while (cursor < text.length) {
        const found = text.indexOf("\n>", cursor);
        if (found < 0) return -1;
        return found + 1;
      }
      return -1;
    })();
    const candidates = [nextFence, nextQuote].filter((item) => item > index);
    const nextSpecial = candidates.length ? Math.min(...candidates) : text.length;
    tokens.push(...tokenizeInline(text.slice(index, nextSpecial), index));
    index = nextSpecial;
  }
  return mergeAdjacentText(tokens);
}

function mergeAdjacentText(tokens) {
  const merged = [];
  for (const token of tokens) {
    if (token.type === "text") {
      pushText(merged, token.value, token.start, token.end);
    } else {
      merged.push(token);
    }
  }
  return merged;
}

export function tokenizeChatMarkdown(rawText) {
  try {
    return tokenizeTopLevel(normalizeRawText(rawText));
  } catch {
    return [{ type: "text", value: normalizeRawText(rawText), raw: normalizeRawText(rawText), start: 0, end: normalizeRawText(rawText).length }];
  }
}

export function isTokenRangeTypeAt(tokens, position, types = ["inline_code", "code_block"]) {
  const wanted = new Set(types);
  const visit = (items) => {
    for (const token of items || []) {
      if (wanted.has(token.type) && position > token.start && position < token.end) return true;
      if (token.children && visit(token.children)) return true;
    }
    return false;
  };
  return visit(tokens);
}

export function getSlashCommandContext(rawText, selectionStart = 0, selectionEnd = selectionStart, options = {}) {
  const raw = normalizeRawText(rawText);
  const start = Math.max(0, Math.min(raw.length, Number(selectionStart) || 0));
  const end = Math.max(0, Math.min(raw.length, Number(selectionEnd) || start));
  if (options.composing || start !== end || raw[0] !== "/") {
    return { active: false, query: "", rangeStart: 0, rangeEnd: 0 };
  }
  const prefix = raw.match(COMMAND_PREFIX_PATTERN)?.[0] || "";
  const prefixEnd = prefix.length;
  if (start > prefixEnd) return { active: false, query: "", rangeStart: 0, rangeEnd: prefixEnd };
  const tokens = options.tokens || tokenizeChatMarkdown(raw);
  if (isTokenRangeTypeAt(tokens, start)) return { active: false, query: "", rangeStart: 0, rangeEnd: prefixEnd };
  const query = raw.slice(1, start);
  if (/\s/.test(query)) return { active: false, query: "", rangeStart: 0, rangeEnd: prefixEnd };
  return {
    active: true,
    query,
    rangeStart: 0,
    rangeEnd: prefixEnd,
  };
}

export function normalizeChatRawText(value) {
  return normalizeRawText(value);
}
