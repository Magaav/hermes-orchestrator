export const WIS_SPACE_SCHEMA = "hermes.wasm_agent.wis.space.v1";
export const WIS_SURFACE_STATE_SCHEMA = "hermes.wasm_agent.wis.surface_state.v1";
export const WIS_ACTION_SCHEMA = "hermes.wasm_agent.wis.action.v1";
export const WIS_EVENT_SCHEMA = "hermes.wasm_agent.wis.event.v1";
export const WIS_EXPORT_SCHEMA = "hermes.wasm_agent.wis.export.v1";
export const WIS_WASM_ENGINE_SCHEMA = "hermes.wasm_agent.wis.wasm_engine.v1";

export const WIS_WASM_ENGINE_BASE64 = "AGFzbQEAAAABEwNgAAF/YAR/f39/AX9gAn9/AX8DBgUAAAECAgdEBQd2ZXJzaW9uAAAMY2FwYWJpbGl0aWVzAAEJbm9kZV9jb3N0AAIObGF5b3V0X2NvbHVtbnMAAwptZWRpYV9tb2RlAAQKZAUEAEEBCwQAQR8LHgAgASACQSBuaiADQQJsaiAAQQhGBH9BCAVBAQtqCyAAIAFBAUgEf0EBBSAAIAFuQQFJBH9BAQUgACABbgsLCxgAIABBAUYEf0EBBSABRQR/QQAFQQILCws=";
const WIS_WASM_CAPABILITY_FLAGS = {
  treeMetrics: 1,
  stateActions: 2,
  layoutPlanning: 4,
  mediaPlanning: 8,
  artifactRuntime: 16,
};
const WIS_NODE_TYPE_IDS = new Map([
  ["document", 1],
  ["section", 2],
  ["container", 3],
  ["heading", 4],
  ["text", 5],
  ["paragraph", 5],
  ["button", 6],
  ["input", 7],
  ["webcam_placeholder", 8],
  ["video", 9],
  ["card", 10],
  ["list", 11],
  ["list-item", 12],
  ["divider", 13],
]);
const WIS_MEDIA_PROTOCOL_IDS = new Map([
  ["rtsp:", 1],
  ["http:", 2],
  ["https:", 2],
  ["hls:", 3],
]);

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

function bytesFromBase64(base64) {
  if (typeof atob === "function") {
    return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  }
  if (typeof Buffer !== "undefined") return Uint8Array.from(Buffer.from(base64, "base64"));
  throw new Error("base64 decoder unavailable");
}

function decodeWasmCapabilities(flags = 0) {
  return Object.fromEntries(
    Object.entries(WIS_WASM_CAPABILITY_FLAGS).map(([key, bit]) => [key, Boolean(flags & bit)])
  );
}

function fallbackWisWasmExports() {
  return {
    version: () => 0,
    capabilities: () => 0,
    node_cost: (typeId, childCount, textLength, propCount) => (
      Number(childCount || 0) + Math.floor(Number(textLength || 0) / 32) + (Number(propCount || 0) * 2) + (Number(typeId) === 8 ? 8 : 1)
    ),
    layout_columns: (width, minTile) => Math.max(1, Math.floor(Number(width || 0) / Math.max(1, Number(minTile || 1)))),
    media_mode: (protocolId, browserNative) => (Number(protocolId) === 1 ? 1 : (browserNative ? 2 : 0)),
  };
}

function createWisWasmEngine() {
  try {
    if (typeof WebAssembly !== "object" || typeof WebAssembly.Module !== "function") {
      throw new Error("WebAssembly unavailable");
    }
    const module = new WebAssembly.Module(bytesFromBase64(WIS_WASM_ENGINE_BASE64));
    const instance = new WebAssembly.Instance(module, {});
    const exports = instance.exports || {};
    if (typeof exports.version !== "function" || typeof exports.node_cost !== "function") {
      throw new Error("WIS WASM exports unavailable");
    }
    const flags = Number(exports.capabilities?.() || 0);
    return {
      schema: WIS_WASM_ENGINE_SCHEMA,
      status: "ready",
      version: Number(exports.version()),
      capabilityFlags: flags,
      capabilities: decodeWasmCapabilities(flags),
      exports,
    };
  } catch (error) {
    return {
      schema: WIS_WASM_ENGINE_SCHEMA,
      status: "fallback-js",
      version: 0,
      capabilityFlags: 0,
      capabilities: decodeWasmCapabilities(0),
      error: String(error?.message || error),
      exports: fallbackWisWasmExports(),
    };
  }
}

const WIS_WASM_ENGINE = createWisWasmEngine();

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

function artifactSlotFromNode(node = {}, fallback = "slot") {
  const props = node?.props && typeof node.props === "object" ? node.props : {};
  const direct = String(props.slot || props.data?.slot || node?.slot || "").trim();
  if (direct) return direct;
  const id = String(node?.id || "").trim();
  const numbered = id.match(/^([A-Za-z]+)-?(\d+)/);
  if (numbered) return `${numbered[1].toLowerCase()}-${numbered[2]}`;
  return id.replace(/-(preview|config|button)$/i, "") || fallback;
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
  if (node.type === "webcam_placeholder" || node.type === "video") {
    const slot = artifactSlotFromNode(node, "camera");
    const camera = valueAt(data, `cameras.${slot}`);
    materialized.props.slot = slot;
    materialized.props.camera = camera && typeof camera === "object" ? clone(camera) : {};
  }
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

function nodeTypeId(node) {
  return WIS_NODE_TYPE_IDS.get(String(node?.type || "").toLowerCase()) || 0;
}

function nodePropCount(node) {
  const props = node?.props;
  return props && typeof props === "object" ? Object.keys(props).length : 0;
}

function mediaProtocolId(url = "") {
  const raw = String(url || "").trim().toLowerCase();
  if (raw.endsWith(".m3u8")) return 3;
  const match = raw.match(/^[a-z][a-z0-9+.-]*:/);
  return WIS_MEDIA_PROTOCOL_IDS.get(match?.[0] || "") || 0;
}

function browserNativeMedia(protocolId) {
  return protocolId === 2 || protocolId === 3;
}

function collectWasmArtifactMetrics(tree, options = {}) {
  const wasm = WIS_WASM_ENGINE.exports;
  const sample = [];
  const media = {
    relayRequired: 0,
    browserNative: 0,
    unsupported: 0,
  };
  let nodeCost = 0;
  const visit = (node) => {
    if (!node) return;
    const typeId = nodeTypeId(node);
    const childCount = Array.isArray(node.children) ? node.children.length : 0;
    const textLength = String(node.text || "").length;
    const propCount = nodePropCount(node);
    const cost = Number(wasm.node_cost(typeId, childCount, textLength, propCount));
    nodeCost += cost;
    if (sample.length < 24) sample.push({ id: node.id || "", type: node.type || "", cost });
    if (typeId === 8 || typeId === 9) {
      const protocolId = mediaProtocolId(node.props?.url || node.props?.src || "");
      const mode = Number(wasm.media_mode(protocolId, browserNativeMedia(protocolId) ? 1 : 0));
      if (mode === 1) media.relayRequired += 1;
      else if (mode === 2) media.browserNative += 1;
      else media.unsupported += 1;
    }
    for (const child of node.children || []) visit(child);
  };
  visit(tree);
  const viewportWidth = Math.max(1, Number(options.viewportWidth || 640));
  return {
    schema: WIS_WASM_ENGINE_SCHEMA,
    status: WIS_WASM_ENGINE.status,
    version: WIS_WASM_ENGINE.version,
    capabilities: clone(WIS_WASM_ENGINE.capabilities),
    layoutColumns: Number(wasm.layout_columns(viewportWidth, 180)),
    nodeCost,
    sample,
    media,
  };
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
    if (action.type === "configureCamera") {
      const slot = String(action.slot || action.targetId || "").trim();
      if (!slot) return { ok: false, error: "camera_slot_required" };
      const config = action.config && typeof action.config === "object" ? clone(action.config) : {};
      setValueAt(state.data, `cameras.${slot}`, config);
      emit("wis.camera_configured", slot, `Configured ${slot}`, {
        slot,
        kind: config.kind || "",
        media_mode: config.mediaMode || "",
        client_local: Boolean(config.clientLocal),
      });
      notify();
      return { ok: true, changed: true, slot, camera: clone(config) };
    }
    if (action.type === "clearCamera") {
      const slot = String(action.slot || action.targetId || "").trim();
      if (!slot) return { ok: false, error: "camera_slot_required" };
      setValueAt(state.data, `cameras.${slot}`, {});
      emit("wis.camera_cleared", slot, `Cleared ${slot}`, { slot });
      notify();
      return { ok: true, changed: true, slot };
    }
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
    const wasm = collectWasmArtifactMetrics(tree);
    return {
      schema: WIS_SURFACE_STATE_SCHEMA,
      timestamp: nowIso(),
      sandbox: {
        id: state.sandboxId,
        status: state.status,
        permissions: clone(source.sandbox || {}),
        noBackend: true,
        noIframe: true,
        wasmEngine: {
          schema: WIS_WASM_ENGINE.schema,
          status: WIS_WASM_ENGINE.status,
          version: WIS_WASM_ENGINE.version,
          capabilities: clone(WIS_WASM_ENGINE.capabilities),
        },
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
      wasm,
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
        wasmEngine: WIS_WASM_ENGINE.status === "ready",
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
