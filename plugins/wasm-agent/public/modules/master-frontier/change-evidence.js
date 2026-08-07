function cleanPath(file) {
  if (file && typeof file === "object") return String(file.full_path || file.path || "").trim();
  return String(file || "").trim();
}

function finiteStat(file, key) {
  return file && typeof file === "object" && Number.isFinite(file[key]) ? file[key] : 0;
}

function diffText(file) {
  if (!file || typeof file !== "object") return "";
  return String(file.diff_patch || file.patch || file.unified_diff || "").trim();
}

function diffLines(patch = "") {
  return String(patch || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => {
      if (line.startsWith("+++") || line.startsWith("---")) return null;
      if (line.startsWith("+")) return { kind: "now", text: line.slice(1) || " " };
      if (line.startsWith("-")) return { kind: "before", text: line.slice(1) || " " };
      return null;
    })
    .filter(Boolean);
}

export function masterFrontierChangeEvidence(message = {}) {
  const changed = Array.isArray(message.changed_files) ? message.changed_files.filter(cleanPath) : [];
  const diagnostics = message.diagnostics && typeof message.diagnostics === "object" ? message.diagnostics : {};
  const changedPaths = new Set(changed.map(cleanPath));
  const observed = diagnostics.diff_seen === true && Array.isArray(diagnostics.observed_changed_files)
    ? diagnostics.observed_changed_files.filter((file) => cleanPath(file) && !changedPaths.has(cleanPath(file)))
    : [];
  return [
    changed.length ? { id: "changed", label: "Changed by this run", files: changed, runOwned: true } : null,
    observed.length ? { id: "observed", label: "Observed worktree changes", files: observed, runOwned: false } : null,
  ].filter(Boolean);
}

export function masterFrontierChangeDiagnostics(diagnostics = {}) {
  const source = diagnostics && typeof diagnostics === "object" ? diagnostics : {};
  return {
    observed_changed_files: Array.isArray(source.observed_changed_files) ? source.observed_changed_files : [],
    observed_changed_files_complete: source.observed_changed_files_complete === true,
    diff_seen: source.diff_seen === true,
  };
}

function statSpan(documentRef, text, kind) {
  const span = documentRef.createElement("span");
  span.className = `agent-diff-${kind}`;
  span.textContent = text;
  return span;
}

function renderDiffBalloon(documentRef, patch) {
  const balloon = documentRef.createElement("div");
  balloon.className = "agent-file-diff-balloon";
  const lines = diffLines(patch);
  if (!lines.length) {
    const empty = documentRef.createElement("div");
    empty.className = "agent-file-diff-empty";
    empty.textContent = "No changed hunks available.";
    balloon.append(empty);
    return balloon;
  }
  const list = documentRef.createElement("div");
  list.className = "agent-file-diff-lines";
  lines.forEach((line) => {
    const row = documentRef.createElement("div");
    const tag = documentRef.createElement("span");
    const code = documentRef.createElement("code");
    row.className = `agent-file-diff-line is-${line.kind}`;
    tag.className = "agent-file-diff-tag";
    tag.textContent = line.kind === "before" ? "was" : "now";
    code.textContent = line.text;
    row.append(tag, code);
    list.append(row);
  });
  balloon.append(list);
  return balloon;
}

function renderGroup(documentRef, group, message, { bindOpenState, onStepback }) {
  const totals = group.files.reduce((sum, file) => ({
    additions: sum.additions + finiteStat(file, "additions"),
    deletions: sum.deletions + finiteStat(file, "deletions"),
  }), { additions: 0, deletions: 0 });
  const details = documentRef.createElement("details");
  const summary = documentRef.createElement("summary");
  details.className = "agent-changed-details";
  bindOpenState?.(details, `${group.id}:${message.id || ""}`);
  summary.className = "agent-changed-summary";
  summary.replaceChildren(
    documentRef.createTextNode(`${group.label}: ${group.files.length} ${group.files.length === 1 ? "file" : "files"} `),
    statSpan(documentRef, `+${totals.additions}`, "add"),
    documentRef.createTextNode(" "),
    statSpan(documentRef, `-${totals.deletions}`, "del")
  );
  const checkpoint = message.diagnostics?.auto_checkpoint || message.diagnostics?.checkpoint || null;
  if (group.runOwned && checkpoint?.ref && onStepback) {
    const stepback = documentRef.createElement("button");
    stepback.type = "button";
    stepback.className = "agent-stepback-button";
    stepback.textContent = "Stepback";
    stepback.title = "Restore the timeline to the point before this run";
    stepback.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onStepback(checkpoint.ref);
    });
    summary.append(stepback);
  }
  const list = documentRef.createElement("div");
  list.className = "agent-file-list";
  list.replaceChildren(...group.files.map((file) => {
    const patch = diffText(file);
    const item = documentRef.createElement(patch ? "details" : "div");
    const row = documentRef.createElement(patch ? "summary" : "div");
    const path = documentRef.createElement("span");
    const stats = documentRef.createElement("span");
    item.className = "agent-file-row";
    row.className = "agent-file-row-summary";
    path.className = "agent-file-path";
    stats.className = "agent-file-diff";
    path.textContent = cleanPath(file);
    path.title = patch ? `Show changed hunks for ${path.textContent}` : path.textContent;
    stats.replaceChildren(
      statSpan(documentRef, `+${finiteStat(file, "additions")}`, "add"),
      documentRef.createTextNode(" "),
      statSpan(documentRef, `-${finiteStat(file, "deletions")}`, "del")
    );
    row.append(path, stats);
    item.append(row);
    if (patch) {
      bindOpenState?.(item, `${group.id}-file:${message.id || ""}:${cleanPath(file)}`);
      item.append(renderDiffBalloon(documentRef, patch));
    }
    return item;
  }));
  details.append(summary, list);
  return details;
}

export function renderMasterFrontierChangeEvidence(message = {}, options = {}) {
  const documentRef = options.documentRef || globalThis.document;
  const groups = masterFrontierChangeEvidence(message);
  if (!documentRef || !groups.length) return null;
  if (groups.length === 1) return renderGroup(documentRef, groups[0], message, options);
  const wrap = documentRef.createElement("div");
  wrap.className = "agent-change-evidence";
  wrap.replaceChildren(...groups.map((group) => renderGroup(documentRef, group, message, options)));
  return wrap;
}
