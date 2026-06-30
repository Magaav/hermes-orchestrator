export const DEFAULT_TRANSCRIPT_DEBOUNCE_MS = 50;

function toRawText(value = "") {
  return String(value ?? "").replace(/\r\n?/g, "\n");
}

export function normalizeTranscriptText(value = "") {
  return toRawText(value)
    .replace(/[ \t\n]+/g, " ")
    .trim();
}

const OR_HOMOPHONE_LEFT_TERMS = [
  "improvements?",
  "regressions?",
  "degradations?",
  "gains?",
  "loss(?:es)?",
  "changes?",
  "progress",
  "quality",
  "accuracy",
  "performance",
  "latency",
  "speed",
].join("|");
const OR_HOMOPHONE_RIGHT_TERMS = [
  "degradations?",
  "regressions?",
  "loss(?:es)?",
  "failures?",
  "errors?",
  "worse",
].join("|");
const OR_HOMOPHONE_PATTERN = new RegExp(
  `\\b(${OR_HOMOPHONE_LEFT_TERMS}),?\\s+our\\s+(${OR_HOMOPHONE_RIGHT_TERMS})(?=\\b)`,
  "gi",
);
const HEAR_YOU_ARE_ME_PATTERN = /\b(hear(?:ing|s|d)?)\s+(?:you['’]?re|you\s+are|your)\s+me\b/gi;
const QUESTION_OR_YOU_ARE_NOT_PATTERN = new RegExp(
  "\\b(can\\s+you\\s+(?:hear|see|read|understand|get)\\b[^.!?]{0,96}?),?\\s+or\\s+(?:you['’]?re|you\\s+are)\\s+not\\b",
  "gi",
);

export function repairTranscriptText(value = "") {
  return normalizeTranscriptText(value)
    .replace(OR_HOMOPHONE_PATTERN, (_match, left, right) => `${left} or ${right}`)
    .replace(HEAR_YOU_ARE_ME_PATTERN, (_match, verb) => `${verb} me`)
    .replace(QUESTION_OR_YOU_ARE_NOT_PATTERN, (_match, question) => `${question} or not`);
}

export function mergeOverlappingTranscriptText(previous = "", nextText = "", maxOverlapWords = 8) {
  const left = normalizeTranscriptText(previous);
  const right = normalizeTranscriptText(nextText);
  if (!left) return right;
  if (!right) return left;
  const leftLower = left.toLowerCase();
  const rightLower = right.toLowerCase();
  if (leftLower === rightLower || leftLower.endsWith(rightLower)) return left;
  if (rightLower.startsWith(leftLower)) return right;
  const leftWords = left.split(/\s+/);
  const rightWords = right.split(/\s+/);
  const leftLowerWords = leftWords.map((word) => word.toLowerCase());
  const rightLowerWords = rightWords.map((word) => word.toLowerCase());
  const maxOverlap = Math.min(
    Math.max(0, Math.floor(Number(maxOverlapWords) || 0)),
    leftWords.length,
    rightWords.length,
  );
  for (let size = maxOverlap; size > 0; size -= 1) {
    const leftTail = leftLowerWords.slice(leftLowerWords.length - size).join(" ");
    const rightHead = rightLowerWords.slice(0, size).join(" ");
    if (leftTail === rightHead) {
      const suffix = rightWords.slice(size).join(" ");
      return suffix ? `${left} ${suffix}` : left;
    }
  }
  return `${left} ${right}`;
}

export function appendTranscriptSegment(segments = [], text = "") {
  const normalized = normalizeTranscriptText(text);
  const next = Array.isArray(segments) ? segments.slice() : [];
  if (!normalized) return next;
  const last = next[next.length - 1] || "";
  if (!last) {
    next.push(normalized);
    return next;
  }
  const lastLower = last.toLowerCase();
  const normalizedLower = normalized.toLowerCase();
  if (lastLower === normalizedLower) return next;
  if (normalizedLower.startsWith(lastLower)) {
    next[next.length - 1] = normalized;
    return next;
  }
  if (lastLower.endsWith(normalizedLower)) return next;
  next.push(normalized);
  return next;
}

export function mergeTranscriptSegments(finalSegments = [], partialText = "") {
  return [...(Array.isArray(finalSegments) ? finalSegments : []), normalizeTranscriptText(partialText)]
    .filter(Boolean)
    .join(" ")
    .replace(/[ \t\n]+/g, " ")
    .trim();
}

export function joinDraftAndTranscript(baseDraft = "", transcriptText = "") {
  const base = toRawText(baseDraft);
  const transcript = normalizeTranscriptText(transcriptText);
  if (!transcript) return base;
  if (!base.trim()) return transcript;
  return `${base}${/\s$/.test(base) ? "" : " "}${transcript}`;
}

export function removePreviousTranscriptFromDraft(currentDraft = "", previousTranscript = "", range = null) {
  const current = toRawText(currentDraft);
  const transcript = normalizeTranscriptText(previousTranscript);
  if (!transcript) return current;
  const start = Number(range?.start);
  const end = Number(range?.end);
  if (
    Number.isInteger(start)
    && Number.isInteger(end)
    && start >= 0
    && end >= start
    && end <= current.length
    && current.slice(start, end) === transcript
  ) {
    return `${current.slice(0, start)}${current.slice(end)}`;
  }
  if (current.endsWith(transcript)) return current.slice(0, current.length - transcript.length);
  const spacedTranscript = ` ${transcript}`;
  if (current.endsWith(spacedTranscript)) return current.slice(0, current.length - spacedTranscript.length);
  return current;
}

function dispatchInput(textarea, inputType = "insertReplacementText") {
  if (!textarea?.dispatchEvent) return;
  try {
    textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType }));
  } catch {
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

export function createTranscriptDraftController(options = {}) {
  const textarea = options.textarea;
  if (!textarea) throw new Error("createTranscriptDraftController requires a textarea.");
  const composer = options.composer || null;
  const debounceMs = Number.isFinite(options.debounceMs)
    ? Math.max(0, options.debounceMs)
    : DEFAULT_TRANSCRIPT_DEBOUNCE_MS;
  const setTimer = options.setTimeout || globalThis.setTimeout?.bind(globalThis);
  const clearTimer = options.clearTimeout || globalThis.clearTimeout?.bind(globalThis);

  let finalSegments = [];
  let partialText = "";
  let baseDraft = toRawText(textarea.value);
  let lastRenderedDraft = baseDraft;
  let lastTranscript = "";
  let transcriptRange = { start: baseDraft.length, end: baseDraft.length };
  let commitTimer = 0;
  let destroyed = false;

  function currentDraft() {
    return toRawText(textarea.value);
  }

  function setDraftValue(value, selectionStart = value.length) {
    if (composer?.setValue) {
      const shouldFocus = globalThis.document?.activeElement === textarea;
      composer.setValue(value, {
        selectionStart,
        selectionEnd: selectionStart,
        focus: shouldFocus,
        inputType: "insertReplacementText",
      });
      return;
    }
    textarea.value = value;
    if (typeof textarea.setSelectionRange === "function") {
      textarea.setSelectionRange(selectionStart, selectionStart);
    }
    dispatchInput(textarea);
  }

  function renderCommit() {
    if (destroyed) return;
    const current = currentDraft();
    if (current !== lastRenderedDraft) {
      baseDraft = removePreviousTranscriptFromDraft(current, lastTranscript, transcriptRange);
    }
    const transcript = mergeTranscriptSegments(finalSegments, partialText);
    const nextDraft = joinDraftAndTranscript(baseDraft, transcript);
    const start = transcript ? Math.max(0, nextDraft.length - transcript.length) : nextDraft.length;
    const end = nextDraft.length;
    if (nextDraft !== current) {
      setDraftValue(nextDraft, end);
    }
    lastRenderedDraft = nextDraft;
    lastTranscript = transcript;
    transcriptRange = { start, end };
    options.onCommit?.({
      baseDraft,
      draft: nextDraft,
      transcript,
      finalSegments: finalSegments.slice(),
      partialText,
      transcriptRange: { ...transcriptRange },
    });
  }

  function clearCommitTimer() {
    if (!commitTimer) return;
    clearTimer?.(commitTimer);
    commitTimer = 0;
  }

  function scheduleCommit(immediate = false) {
    clearCommitTimer();
    if (immediate || debounceMs <= 0 || !setTimer) {
      renderCommit();
      return;
    }
    commitTimer = setTimer(() => {
      commitTimer = 0;
      renderCommit();
    }, debounceMs);
  }

  function applyTranscript(entry = {}) {
    const text = repairTranscriptText(entry.text ?? entry.transcript ?? "");
    if (entry.final || entry.isFinal) {
      finalSegments = appendTranscriptSegment(finalSegments, text);
      partialText = "";
    } else {
      partialText = text;
    }
    scheduleCommit(Boolean(entry.immediate));
    return {
      finalSegments: finalSegments.slice(),
      partialText,
      transcript: mergeTranscriptSegments(finalSegments, partialText),
    };
  }

  function flush() {
    clearCommitTimer();
    renderCommit();
  }

  function reset(optionsForReset = {}) {
    clearCommitTimer();
    finalSegments = [];
    partialText = "";
    baseDraft = toRawText(optionsForReset.baseDraft ?? currentDraft());
    lastRenderedDraft = baseDraft;
    lastTranscript = "";
    transcriptRange = { start: baseDraft.length, end: baseDraft.length };
  }

  function destroy() {
    destroyed = true;
    clearCommitTimer();
  }

  return {
    applyTranscript,
    flush,
    reset,
    destroy,
    get transcript() {
      return mergeTranscriptSegments(finalSegments, partialText);
    },
    get baseDraft() {
      return baseDraft;
    },
    get state() {
      return {
        baseDraft,
        finalSegments: finalSegments.slice(),
        partialText,
        lastRenderedDraft,
        lastTranscript,
        transcriptRange: { ...transcriptRange },
      };
    },
  };
}
