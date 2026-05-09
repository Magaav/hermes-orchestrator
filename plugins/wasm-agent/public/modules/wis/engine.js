export const WIS_SPACE_SCHEMA = "hermes.wasm_agent.wis.space.v1";
export const WIS_SURFACE_STATE_SCHEMA = "hermes.wasm_agent.wis.surface_state.v1";
export const WIS_ACTION_SCHEMA = "hermes.wasm_agent.wis.action.v1";
export const WIS_EVENT_SCHEMA = "hermes.wasm_agent.wis.event.v1";
export const WIS_EXPORT_SCHEMA = "hermes.wasm_agent.wis.export.v1";

export const WIS_EXAMPLE_SPACE_DEFINITION = {
  schema: WIS_SPACE_SCHEMA,
  id: "wis-counter-space",
  title: "WIS Counter Space",
  version: 1,
  entryDocumentId: "counter-app",
  sandbox: {
    network: false,
    iframe: false,
    backend: false,
    externalScripts: false,
  },
  documents: [
    {
      id: "counter-app",
      url: "wis://local/counter-app",
      title: "Counter App",
      state: {
        count: 0,
        draft: "",
        tasks: ["Load document", "Click Add"],
        enabled: true,
      },
      tree: {
        id: "doc",
        type: "document",
        role: "document",
        children: [
          {
            id: "hero",
            type: "section",
            role: "banner",
            props: { className: "wis-app-hero" },
            children: [
              { id: "title", type: "heading", level: 1, text: "Counter App" },
              { id: "status", type: "text", text: "Count: {{count}}" },
            ],
          },
          {
            id: "controls",
            type: "section",
            role: "group",
            props: { className: "wis-app-controls" },
            children: [
              {
                id: "increment",
                type: "button",
                text: "Add",
                action: { type: "increment", key: "count", by: 1 },
              },
              {
                id: "reset-count",
                type: "button",
                text: "Reset",
                action: { type: "set", key: "count", value: 0 },
              },
              {
                id: "toggle-enabled",
                type: "button",
                text: "Toggle",
                action: { type: "toggle", key: "enabled" },
              },
            ],
          },
          {
            id: "task-editor",
            type: "section",
            role: "group",
            props: { className: "wis-task-editor" },
            children: [
              {
                id: "task-input",
                type: "input",
                props: { valueKey: "draft", placeholder: "Task" },
              },
              {
                id: "add-task",
                type: "button",
                text: "Add task",
                action: { type: "appendInputItem", inputKey: "draft", itemsKey: "tasks" },
              },
            ],
          },
          {
            id: "task-list",
            type: "list",
            props: { itemsKey: "tasks" },
          },
        ],
      },
    },
  ],
};

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function nowIso() {
  return new Date().toISOString();
}

function valueAt(data, key) {
  if (!key) return "";
  return String(key).split(".").reduce((current, part) => (
    current && Object.prototype.hasOwnProperty.call(current, part) ? current[part] : ""
  ), data);
}

function setValueAt(data, key, value) {
  const parts = String(key || "").split(".").filter(Boolean);
  if (!parts.length) return;
  let target = data;
  while (parts.length > 1) {
    const part = parts.shift();
    if (!target[part] || typeof target[part] !== "object") target[part] = {};
    target = target[part];
  }
  target[parts[0]] = value;
}

function renderTemplate(text, data) {
  return String(text || "").replace(/\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g, (_match, key) => {
    const value = valueAt(data, key);
    if (value === undefined || value === null) return "";
    return String(value);
  });
}

function documentsById(definition) {
  return new Map((definition.documents || []).map((documentModel) => [documentModel.id, documentModel]));
}

function materializeNode(node, data) {
  const props = { ...(node.props || {}) };
  const materialized = {
    id: node.id,
    type: node.type || "element",
    role: node.role || "",
    text: renderTemplate(node.text || "", data),
    props,
    children: [],
  };

  if (node.level) materialized.level = node.level;
  if (props.valueKey) materialized.props.value = valueAt(data, props.valueKey) || "";
  if (node.type === "list") {
    const items = Array.isArray(valueAt(data, props.itemsKey)) ? valueAt(data, props.itemsKey) : [];
    materialized.children = items.map((item, index) => ({
      id: `${node.id}-${index}`,
      type: "list-item",
      role: "listitem",
      text: String(item),
      props: { index },
      children: [],
    }));
    return materialized;
  }

  materialized.children = (node.children || []).map((child) => materializeNode(child, data));
  return materialized;
}

function flattenTree(node, items = []) {
  if (!node) return items;
  items.push({
    id: node.id,
    type: node.type,
    role: node.role || "",
    text: node.text || "",
    child_count: node.children?.length || 0,
  });
  for (const child of node.children || []) flattenTree(child, items);
  return items;
}

function findNode(node, id) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const match = findNode(child, id);
    if (match) return match;
  }
  return null;
}

function createEvent(seq, type, target, summary, data = {}) {
  return {
    schema: WIS_EVENT_SCHEMA,
    id: `wis_evt_${seq.toString(36)}`,
    timestamp: nowIso(),
    type,
    target: target || "",
    summary,
    data,
  };
}

function availableActions(modelNode) {
  const actions = [];
  const visit = (node) => {
    if (!node) return;
    if (node.type === "button") {
      actions.push({
        schema: WIS_ACTION_SCHEMA,
        type: "click",
        targetId: node.id,
        label: node.text || node.id,
      });
    }
    if (node.type === "input") {
      actions.push({
        schema: WIS_ACTION_SCHEMA,
        type: "input",
        targetId: node.id,
        value: "",
      });
    }
    for (const child of node.children || []) visit(child);
  };
  visit(modelNode);
  return actions;
}

export function createWisSandbox(definition = WIS_EXAMPLE_SPACE_DEFINITION) {
  const source = clone(definition);
  const docs = documentsById(source);
  let seq = 0;
  const subscribers = new Set();
  const state = {
    sandboxId: `wis_${source.id || "local"}`,
    status: "isolated",
    definition: source,
    documentStates: {},
    navigation: {
      url: "",
      documentId: "",
      history: [],
      index: -1,
    },
    data: {},
    events: [],
    frame: 0,
  };

  function emit(type, target, summary, data = {}) {
    seq += 1;
    state.events.push(createEvent(seq, type, target, summary, data));
    if (state.events.length > 32) state.events.splice(0, state.events.length - 32);
  }

  function notify() {
    state.frame += 1;
    for (const subscriber of subscribers) subscriber(inspect());
  }

  function currentDocument() {
    return docs.get(state.navigation.documentId) || null;
  }

  function load(documentId, options = {}) {
    const documentModel = docs.get(documentId);
    if (!documentModel) {
      emit("wis.navigation_denied", documentId, `Document ${documentId} was not found`);
      notify();
      return { ok: false, error: "document_not_found" };
    }
    state.navigation.documentId = documentModel.id;
    state.navigation.url = documentModel.url || `wis://local/${documentModel.id}`;
    if (!state.documentStates[documentModel.id]) {
      state.documentStates[documentModel.id] = clone(documentModel.state || {});
    }
    state.data = state.documentStates[documentModel.id];
    if (options.replaceHistory && state.navigation.index >= 0) {
      state.navigation.history[state.navigation.index] = state.navigation.url;
    } else {
      state.navigation.history = state.navigation.history.slice(0, state.navigation.index + 1);
      state.navigation.history.push(state.navigation.url);
      state.navigation.index = state.navigation.history.length - 1;
    }
    emit("wis.document_loaded", documentModel.id, `Loaded ${documentModel.id}`, {
      url: state.navigation.url,
      node_count: flattenTree(materializeNode(documentModel.tree, state.data)).length,
    });
    notify();
    return { ok: true, documentId: documentModel.id, url: state.navigation.url };
  }

  function invokeNode(modelNode) {
    const action = modelNode?.action;
    if (!action) {
      emit("wis.node_clicked", modelNode?.id || "", `Clicked ${modelNode?.id || "node"}`);
      return { ok: true, changed: false };
    }

    if (action.type === "increment") {
      const current = Number(valueAt(state.data, action.key)) || 0;
      const next = current + (Number(action.by) || 1);
      setValueAt(state.data, action.key, next);
      emit("wis.state_changed", modelNode.id, `${action.key} changed to ${next}`, { key: action.key, value: next });
      return { ok: true, changed: true };
    }
    if (action.type === "set") {
      setValueAt(state.data, action.key, clone(action.value));
      emit("wis.state_changed", modelNode.id, `${action.key} changed`, { key: action.key, value: action.value });
      return { ok: true, changed: true };
    }
    if (action.type === "toggle") {
      const next = !Boolean(valueAt(state.data, action.key));
      setValueAt(state.data, action.key, next);
      emit("wis.state_changed", modelNode.id, `${action.key} changed to ${next}`, { key: action.key, value: next });
      return { ok: true, changed: true };
    }
    if (action.type === "appendInputItem") {
      const value = String(valueAt(state.data, action.inputKey) || "").trim();
      if (!value) {
        emit("wis.input_ignored", modelNode.id, "Empty input ignored", { inputKey: action.inputKey });
        return { ok: true, changed: false };
      }
      const items = Array.isArray(valueAt(state.data, action.itemsKey)) ? valueAt(state.data, action.itemsKey) : [];
      items.push(value);
      setValueAt(state.data, action.itemsKey, items);
      setValueAt(state.data, action.inputKey, "");
      emit("wis.state_changed", modelNode.id, `Added ${value}`, { itemsKey: action.itemsKey, count: items.length });
      return { ok: true, changed: true };
    }
    if (action.type === "navigate") return load(action.documentId);

    emit("wis.action_ignored", modelNode.id, `Unsupported action ${action.type}`, { action: action.type });
    return { ok: false, error: "unsupported_action" };
  }

  function act(action = {}) {
    const documentModel = currentDocument();
    if (!documentModel) return { ok: false, error: "no_document" };
    if (action.type === "load" || action.type === "navigate") return load(action.documentId || action.targetId);
    if (action.type === "input") {
      const modelNode = findNode(documentModel.tree, action.targetId);
      const key = modelNode?.props?.valueKey;
      if (!key) return { ok: false, error: "target_not_input" };
      setValueAt(state.data, key, String(action.value ?? ""));
      emit("wis.input", action.targetId, `Input ${action.targetId}`, { value_length: String(action.value ?? "").length });
      notify();
      return { ok: true, changed: true };
    }
    if (action.type === "click" || action.type === "invoke") {
      const modelNode = findNode(documentModel.tree, action.targetId);
      if (!modelNode) return { ok: false, error: "target_not_found" };
      const result = invokeNode(modelNode);
      notify();
      return result;
    }
    return { ok: false, error: "unsupported_action" };
  }

  function inspect() {
    const documentModel = currentDocument();
    const tree = documentModel ? materializeNode(documentModel.tree, state.data) : null;
    const nodes = flattenTree(tree);
    const elements = nodes.filter((node) => !["text", "list-item"].includes(node.type));
    return {
      schema: WIS_SURFACE_STATE_SCHEMA,
      timestamp: nowIso(),
      sandbox: {
        id: state.sandboxId,
        status: state.status,
        permissions: clone(source.sandbox || {}),
        noBackend: true,
        noIframe: true,
      },
      navigation: clone(state.navigation),
      document: documentModel ? {
        id: documentModel.id,
        title: documentModel.title || documentModel.id,
        url: documentModel.url || state.navigation.url,
      } : null,
      tree,
      nodes,
      elements,
      nodeCount: nodes.length,
      elementCount: elements.length,
      state: clone(state.data),
      recentEvents: state.events.slice(-10).reverse(),
      automation: {
        inspect: "window.wasmAgentWis.inspect()",
        act: "window.wasmAgentWis.act({ type, targetId, value })",
        actions: documentModel ? availableActions(documentModel.tree) : [],
      },
      frame: state.frame,
    };
  }

  function exportSpace() {
    return {
      schema: WIS_EXPORT_SCHEMA,
      exportedAt: nowIso(),
      space: clone(source),
      runtime: {
        navigation: clone(state.navigation),
        documentStates: clone(state.documentStates),
      },
      guarantees: {
        backendDependency: false,
        iframePrimaryArchitecture: false,
        portableArtifactDefinition: true,
      },
    };
  }

  function subscribe(callback) {
    subscribers.add(callback);
    return () => subscribers.delete(callback);
  }

  load(source.entryDocumentId || source.documents?.[0]?.id || "", { replaceHistory: true });

  return {
    inspect,
    act,
    load,
    exportSpace,
    subscribe,
  };
}
