export const DEFAULT_CHAT_COMMANDS = Object.freeze([
  { name: "/goal", insertText: "/goal ", description: "Run a long-form agent objective." },
  { name: "/exhaust", insertText: "/exhaust ", description: "Explore alternate paths after failure." },
  { name: "/voice", insertText: "/voice ", description: "Voice room controls." },
  { name: "/share", insertText: "/share ", description: "Share current space." },
  { name: "/provider", insertText: "/provider", description: "Switch verified provider or open provider config." },
  { name: "/model", insertText: "/model", description: "Switch model for the current provider." },
  { name: "/spawn", insertText: "/spawn ", description: "Spawn a new space/app/action." },
  { name: "/help", insertText: "/help ", description: "Show available commands." },
]);

export function filterCommands(commands = DEFAULT_CHAT_COMMANDS, query = "") {
  const q = String(query || "").toLowerCase();
  const list = Array.isArray(commands) ? commands : DEFAULT_CHAT_COMMANDS;
  return list.filter((command) => {
    const name = String(command?.name || "").toLowerCase();
    return name.startsWith(`/${q}`) || name.slice(1).startsWith(q);
  });
}

function commandId(command, index) {
  return `chat-command-${String(command?.name || "command").replace(/[^a-z0-9_-]+/gi, "-")}-${index}`;
}

export function createCommandPalette(options = {}) {
  const commands = Array.isArray(options.commands) ? options.commands : DEFAULT_CHAT_COMMANDS;
  const documentRef = options.document || document;
  const element = options.element || documentRef.createElement("div");
  element.className = options.className || "chat-command-palette";
  element.setAttribute("role", "listbox");
  element.setAttribute("aria-label", options.label || "Chat commands");
  element.hidden = true;

  let open = false;
  let query = "";
  let filtered = [];
  let selectedIndex = 0;
  let onSelect = typeof options.onSelect === "function" ? options.onSelect : () => {};
  let onStateChange = typeof options.onStateChange === "function" ? options.onStateChange : () => {};

  function emitState() {
    onStateChange({
      open,
      query,
      selectedIndex,
      selectedCommand: filtered[selectedIndex] || null,
      commands: filtered.slice(),
    });
  }

  function select(index) {
    if (!filtered.length) {
      selectedIndex = 0;
    } else {
      selectedIndex = (index + filtered.length) % filtered.length;
    }
    render();
    emitState();
  }

  function close() {
    if (!open && element.hidden) return;
    open = false;
    query = "";
    filtered = [];
    selectedIndex = 0;
    element.hidden = true;
    element.replaceChildren();
    element.removeAttribute("aria-activedescendant");
    emitState();
  }

  function choose(command = filtered[selectedIndex]) {
    if (!open || !command) return false;
    onSelect(command);
    close();
    return true;
  }

  function render() {
    element.hidden = !open;
    if (!open) return;
    element.replaceChildren();
    if (!filtered.length) {
      const empty = documentRef.createElement("div");
      empty.className = "chat-command-empty";
      empty.textContent = "No commands";
      element.append(empty);
      element.removeAttribute("aria-activedescendant");
      return;
    }
    filtered.forEach((command, index) => {
      const button = documentRef.createElement("button");
      const id = commandId(command, index);
      button.id = id;
      button.type = "button";
      button.className = "chat-command-option";
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", index === selectedIndex ? "true" : "false");
      if (index === selectedIndex) element.setAttribute("aria-activedescendant", id);
      const name = documentRef.createElement("strong");
      name.textContent = command.name;
      const description = documentRef.createElement("span");
      description.textContent = command.description || "";
      button.append(name, description);
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
      });
      button.addEventListener("click", () => choose(command));
      element.append(button);
    });
  }

  function update(context = {}) {
    if (!context.active) {
      close();
      return;
    }
    const nextQuery = String(context.query || "");
    filtered = filterCommands(commands, nextQuery);
    if (nextQuery !== query) selectedIndex = 0;
    query = nextQuery;
    open = true;
    if (selectedIndex >= filtered.length) selectedIndex = Math.max(0, filtered.length - 1);
    render();
    emitState();
  }

  function handleKeyDown(event) {
    if (!open || event.defaultPrevented) return false;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      select(selectedIndex + 1);
      return true;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      select(selectedIndex - 1);
      return true;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      return choose();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return true;
    }
    return false;
  }

  return {
    element,
    update,
    close,
    choose,
    handleKeyDown,
    setOnSelect(callback) {
      onSelect = typeof callback === "function" ? callback : () => {};
    },
    setOnStateChange(callback) {
      onStateChange = typeof callback === "function" ? callback : () => {};
    },
    get state() {
      return {
        open,
        query,
        selectedIndex,
        selectedCommand: filtered[selectedIndex] || null,
        commands: filtered.slice(),
      };
    },
  };
}
