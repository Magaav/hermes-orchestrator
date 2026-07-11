export function agentSessionReference(session = {}) {
  return String(session.id || "").trim();
}

async function copyText(text, documentRef = globalThis.document, navigatorRef = globalThis.navigator) {
  if (navigatorRef?.clipboard?.writeText) {
    await navigatorRef.clipboard.writeText(text);
    return;
  }
  const input = documentRef.createElement("textarea");
  input.value = text;
  input.style.position = "fixed";
  input.style.opacity = "0";
  documentRef.body.append(input);
  input.select();
  const copied = documentRef.execCommand?.("copy");
  input.remove();
  if (!copied) throw new Error("clipboard-write-unavailable");
}

function openSessionMenu(event, reference, options, documentRef) {
  documentRef.querySelector("[data-agent-session-menu]")?.remove();
  const menu = documentRef.createElement("div");
  menu.className = "app-context-menu";
  menu.dataset.agentSessionMenu = "true";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", "Session actions");
  const copyButton = documentRef.createElement("button");
  copyButton.type = "button";
  copyButton.className = "agent-message-menu-item";
  copyButton.setAttribute("role", "menuitem");
  const copyIcon = documentRef.createElement("span");
  copyIcon.className = "agent-icon-copy";
  copyIcon.setAttribute("aria-hidden", "true");
  const copyLabel = documentRef.createElement("span");
  copyLabel.textContent = "Copy session ID";
  copyButton.append(copyIcon, copyLabel);
  menu.append(copyButton);
  documentRef.body.append(menu);

  const gap = 8;
  const rect = menu.getBoundingClientRect();
  const view = documentRef.defaultView || globalThis.window;
  menu.style.left = `${Math.max(gap, Math.min(view.innerWidth - rect.width - gap, event.clientX || gap))}px`;
  menu.style.top = `${Math.max(gap, Math.min(view.innerHeight - rect.height - gap, event.clientY || gap))}px`;
  menu.hidden = false;

  const close = () => {
    menu.remove();
    documentRef.removeEventListener("pointerdown", onPointerDown);
    documentRef.removeEventListener("keydown", onKeyDown);
  };
  const onPointerDown = (pointerEvent) => {
    if (!menu.contains(pointerEvent.target)) close();
  };
  const onKeyDown = (keyEvent) => {
    if (keyEvent.key === "Escape") close();
  };
  copyButton.addEventListener("click", async () => {
    close();
    try {
      await copyText(reference, documentRef, options.navigator || globalThis.navigator);
      options.onCopied?.(reference);
    } catch (error) {
      options.onCopyError?.(error);
    }
  });
  documentRef.addEventListener("pointerdown", onPointerDown);
  documentRef.addEventListener("keydown", onKeyDown);
}

export function createAgentSessionRow(session, options = {}) {
  const documentRef = options.document || globalThis.document;
  const reference = agentSessionReference(session);
  const button = documentRef.createElement("button");
  button.type = "button";
  button.className = "agent-session-row";
  button.classList.toggle("active", Boolean(options.active));
  button.dataset.sessionId = reference;
  button.title = "Right-click to copy session reference";

  const title = documentRef.createElement("strong");
  title.textContent = session.title || "Session";
  const meta = documentRef.createElement("span");
  meta.textContent = options.meta || "0 turns";
  button.append(title, meta);
  button.addEventListener("click", () => options.onOpen?.(reference));
  button.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!reference) return;
    openSessionMenu(event, reference, options, documentRef);
  });
  return button;
}
