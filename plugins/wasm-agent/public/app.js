import { MODULE_DEFINITIONS } from "./modules/index.js";
import { startDevHmr } from "./modules/hmr/dev-hmr.js";

const CORE_WASM_BASE64 = "AGFzbQEAAAABBwFgAn9/AX8DAgEABwcBA2FkZAAACgkBBwAgACABags=";
const SPACE_LAYOUT_SCHEMA = "hermes.wasm_agent.space_layout.v1";
const SPACE_WIDGET_LAYOUTS_STORAGE_KEY = "wasmAgent.spaceWidgetLayouts.v2";
const AGENT_SESSIONS_STORAGE_KEY = "wasmAgent.agentSessions.v1";
const AGENT_LAYOUT_STORAGE_KEY = "wasmAgent.agentLayout.v1";
const MODULE_SETTINGS_STORAGE_KEY = "wasmAgent.modules.v1";
const LAUNCHER_PREF_STORAGE_KEY = "wasmAgent.launcherPreference.v1";
const CLIENT_DEVICE_STORAGE_KEY = "wasmAgent.clientDevice.v1";
const CHAT_QUERY_KEY = "chat";
const CHAT_QUERY_VALUE = "wasm-agent-chat";
const WIDGET_Z_BASE = 20;
const WIDGET_Z_LIMIT = 9000;
const APP_ICON_GRID_PX = 5;
const APP_ICON_COLLISION_TOLERANCE_PX = Math.ceil(APP_ICON_GRID_PX / 2);
const APP_ORGANIZER_TOP_INSET_PX = 30;
const SPACE_CANVAS_EDGE_INSET_PX = 0;
const SPACE_MINIMAP_HIDE_MS = 180;
const SPACE_MINIMAP_PADDING_PX = 0;
const SPACE_PAN_MOMENTUM_FRICTION = 0.92;
const SPACE_PAN_MOMENTUM_MIN_VELOCITY = 0.04;
const SPACE_PAN_MOMENTUM_MAX_VELOCITY = 2.4;
const SPACE_PAN_MOMENTUM_SAMPLE_MS = 120;
const SPACE_PAN_MOMENTUM_LAUNCH_MULTIPLIER = 1.08;
const SPACE_PAN_MOMENTUM_FRAME_MS = 1000 / 60;
const SPACE_PAN_MOMENTUM_MAX_MS = 1200;
const CANVAS_DENSITY_MAX = 10;
const RESOURCE_POLL_MS = 2500;
const SECURITY_POLL_MS = 5000;
const USER_EVENT_LIMIT = 160;
const DEFAULT_AGENT_TURN_TIMEOUT_MS = 5 * 60 * 1000;
const AGENT_MAX_IMAGES = 8;
const AGENT_AVATAR_VIEWPORT_GAP_PX = 14;
const AGENT_PANEL_VIEWPORT_GAP_PX = 0;
const AGENT_PANEL_AVATAR_GAP_PX = AGENT_AVATAR_VIEWPORT_GAP_PX;
const AGENT_IMAGE_MAX_EDGE = 1280;
const AGENT_IMAGE_MAX_BYTES = 384 * 1024;
const AGENT_IMAGE_TOTAL_MAX_BYTES = 1400 * 1024;
const AGENT_IMAGE_QUALITY = 0.78;
const AGENT_IMAGE_SAMPLE_EDGE = 128;
const IMAGE_CARD_ANALYZER_REVISION = "image-card-text-v2";
const IMAGE_ANALYZER_TIMEOUT_MS = 1800;
const OCR_ANALYZER_TIMEOUT_MS = 45000;
const OCR_PREPROCESS_MAX_WIDTH = 1600;
const OCR_TEXT_SCORE_THRESHOLD = 0.18;
const OCR_TESSERACT_DEFAULT_URL = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
const OCR_TESSERACT_LANGUAGE = "eng";
const IMAGE_ANALYZER_CACHE = new Map();
const SCRIPT_RUNTIME_CACHE = new Map();
const AGENT_DEFAULT_MESSAGE_CONTENT = "I can see this workspace snapshot and help evolve the app from here.";
const ADMIN_PANEL_IDS = new Set(["admin", "fleet", "tasks", "logs", "observe", "timeline", "modules", "security"]);
const SECURITY_FINDING_STATUSES = ["new", "triaged", "accepted", "rejected", "mitigating", "resolved", "watching"];
const SPACE_APP_DEFINITIONS = [
  { id: "resources", label: "Resources", short: "Res" },
  { id: "topology", label: "Topology", short: "Topo" },
  { id: "studio", label: "Studio", short: "Studio" },
  { id: "browser-proof", label: "Browser", short: "Web", module: "host-browser" },
  { id: "drop-to-copy", label: "Drop", short: "Drop" },
  { id: "security-loop", label: "Security", short: "Sec" },
];
const SPACE_APP_MAPPINGS = {
  home: [],
  admin: ["resources", "topology", "studio", "browser-proof", "drop-to-copy", "security-loop"],
  user: ["resources", "topology", "studio", "browser-proof", "drop-to-copy"],
};
const FIXED_WIDGET_LAYOUT = {
  timeline: { minimized: true },
};

const els = {
  app: document.querySelector("#app"),
  authGate: document.querySelector("#authGate"),
  authGateCopy: document.querySelector("#authGateCopy"),
  authGateLoginButton: document.querySelector("#authGateLoginButton"),
  authGateGoogleSignInButton: document.querySelector("#authGateGoogleSignInButton"),
  authGateMessage: document.querySelector("#authGateMessage"),
  promptInput: document.querySelector("#promptInput"),
  promptSendButton: document.querySelector("#promptSendButton"),
  clearButton: document.querySelector("#clearButton"),
  browserForm: document.querySelector("#browserForm"),
  browserUrlInput: document.querySelector("#browserUrlInput"),
  browserBackButton: document.querySelector("#browserBackButton"),
  browserForwardButton: document.querySelector("#browserForwardButton"),
  browserReloadButton: document.querySelector("#browserReloadButton"),
  browserLiveButton: document.querySelector("#browserLiveButton"),
  browserOpenButton: document.querySelector("#browserOpenButton"),
  browserStatus: document.querySelector("#browserStatus"),
  browserScreen: document.querySelector("#browserScreen"),
  browserCanvas: document.querySelector("#browserCanvas"),
  browserImage: document.querySelector("#browserImage"),
  browserEmpty: document.querySelector("#browserEmpty"),
  browserMeta: document.querySelector("#browserMeta"),
  spaceViewport: document.querySelector(".space-viewport"),
  spaceBoard: document.querySelector("#spaceBoard"),
  appLayer: document.querySelector("#appLayer"),
  spaceMiniMap: document.querySelector("#spaceMiniMap"),
  spaceLabel: document.querySelector("#spaceLabel"),
  spaceOrganizeButton: document.querySelector("#spaceOrganizeButton"),
  spaceConfigButton: document.querySelector("#spaceConfigButton"),
  spaceLauncherList: document.querySelector("#spaceLauncherList"),
  addNodeButton: document.querySelector("#addNodeButton"),
  addSpaceButton: document.querySelector("#addSpaceButton"),
  homeDevicesButton: document.querySelector("#homeDevicesButton"),
  homeModulesButton: document.querySelector("#homeModulesButton"),
  spaceContextMenu: document.querySelector("#spaceContextMenu"),
  nodeContextMenu: document.querySelector("#nodeContextMenu"),
  appContextMenu: document.querySelector("#appContextMenu"),
  editAppButton: document.querySelector("#editAppButton"),
  copyAppIdButton: document.querySelector("#copyAppIdButton"),
  copySpaceIdButton: document.querySelector("#copySpaceIdButton"),
  deleteSpaceButton: document.querySelector("#deleteSpaceButton"),
  deleteSpaceModal: document.querySelector("#deleteSpaceModal"),
  deleteSpaceName: document.querySelector("#deleteSpaceName"),
  deleteSpacePrompt: document.querySelector("#deleteSpacePrompt"),
  deleteSpaceConfirmInput: document.querySelector("#deleteSpaceConfirmInput"),
  confirmDeleteSpaceButton: document.querySelector("#confirmDeleteSpaceButton"),
  cancelDeleteSpaceButton: document.querySelector("#cancelDeleteSpaceButton"),
  closeDeleteSpaceButton: document.querySelector("#closeDeleteSpaceButton"),
  configModal: document.querySelector("#configModal"),
  configDetails: document.querySelector("#configDetails"),
  configModalSpaceName: document.querySelector("#configModalSpaceName"),
  closeConfigModalButton: document.querySelector("#closeConfigModalButton"),
  appEditModal: document.querySelector("#appEditModal"),
  appEditModalTitle: document.querySelector("#appEditModalTitle"),
  appEditModalMeta: document.querySelector("#appEditModalMeta"),
  appEditForm: document.querySelector("#appEditForm"),
  appEditNameInput: document.querySelector("#appEditNameInput"),
  appEditIconInput: document.querySelector("#appEditIconInput"),
  appEditImageInput: document.querySelector("#appEditImageInput"),
  appEditMinWidthInput: document.querySelector("#appEditMinWidthInput"),
  appEditMaxWidthInput: document.querySelector("#appEditMaxWidthInput"),
  appEditMinHeightInput: document.querySelector("#appEditMinHeightInput"),
  appEditMaxHeightInput: document.querySelector("#appEditMaxHeightInput"),
  resetAppEditButton: document.querySelector("#resetAppEditButton"),
  saveAppEditButton: document.querySelector("#saveAppEditButton"),
  closeAppEditModalButton: document.querySelector("#closeAppEditModalButton"),
  nodeEditModal: document.querySelector("#nodeEditModal"),
  nodeEditModalTitle: document.querySelector("#nodeEditModalTitle"),
  nodeEditModalMeta: document.querySelector("#nodeEditModalMeta"),
  nodeEditForm: document.querySelector("#nodeEditForm"),
  nodeEditModelNameInput: document.querySelector("#nodeEditModelNameInput"),
  nodeEditModelProviderInput: document.querySelector("#nodeEditModelProviderInput"),
  resetNodeEditButton: document.querySelector("#resetNodeEditButton"),
  saveNodeEditButton: document.querySelector("#saveNodeEditButton"),
  closeNodeEditModalButton: document.querySelector("#closeNodeEditModalButton"),
  securityEvidenceModal: document.querySelector("#securityEvidenceModal"),
  securityEvidenceTitle: document.querySelector("#securityEvidenceTitle"),
  securityEvidenceMeta: document.querySelector("#securityEvidenceMeta"),
  securityEvidenceBody: document.querySelector("#securityEvidenceBody"),
  closeSecurityEvidenceButton: document.querySelector("#closeSecurityEvidenceButton"),
  homeModulesModal: document.querySelector("#homeModulesModal"),
  homeModuleList: document.querySelector("#homeModuleList"),
  closeHomeModulesModalButton: document.querySelector("#closeHomeModulesModalButton"),
  mainStage: document.querySelector(".main-stage"),
  spaceCanvas: document.querySelector("#spaceCanvas"),
  selectedNode: document.querySelector("#selectedNode"),
  runtimeLabel: document.querySelector("#runtimeLabel"),
  resourceFreshness: document.querySelector("#resourceFreshness"),
  resourceGrid: document.querySelector("#resourceGrid"),
  topologyNodes: document.querySelector("#topologyNodes"),
  devicesList: document.querySelector("#devicesList"),
  devicesStatus: document.querySelector("#devicesStatus"),
  devicesSyncButton: document.querySelector("#devicesSyncButton"),
  homeArtifactsButton: document.querySelector("#homeArtifactsButton"),
  artifactsModal: document.querySelector("#artifactsModal"),
  artifactList: document.querySelector("#artifactList"),
  closeArtifactsModalButton: document.querySelector("#closeArtifactsModalButton"),
  devicesModal: document.querySelector("#devicesModal"),
  closeDevicesModalButton: document.querySelector("#closeDevicesModalButton"),
  taskOutput: document.querySelector("#taskOutput"),
  nodeList: document.querySelector("#nodeList"),
  taskList: document.querySelector("#taskList"),
  logsButton: document.querySelector("#logsButton"),
  logsOutput: document.querySelector("#logsOutput"),
  timelineStatus: document.querySelector("#timelineStatus"),
  timelineGraph: document.querySelector("#timelineGraph"),
  timelineRefreshButton: document.querySelector("#timelineRefreshButton"),
  timelineBranch: document.querySelector("#timelineBranch"),
  timelineDetails: document.querySelector("#timelineDetails"),
  observationCount: document.querySelector("#observationCount"),
  observationStats: document.querySelector("#observationStats"),
  observationTimeline: document.querySelector("#observationTimeline"),
  observationSnapshot: document.querySelector("#observationSnapshot"),
  moduleList: document.querySelector("#moduleList"),
  securityRefreshButton: document.querySelector("#securityRefreshButton"),
  securityLoopStatus: document.querySelector("#securityLoopStatus"),
  securityLoopSummary: document.querySelector("#securityLoopSummary"),
  securityFindingQueue: document.querySelector("#securityFindingQueue"),
  securityPanelStatus: document.querySelector("#securityPanelStatus"),
  securityPanelSummary: document.querySelector("#securityPanelSummary"),
  securityPanelFindingQueue: document.querySelector("#securityPanelFindingQueue"),
  agentOverlay: document.querySelector("#agentOverlay"),
  agentAvatarButton: document.querySelector("#agentAvatarButton"),
  agentPanel: document.querySelector("#agentPanel"),
  agentCloseButton: document.querySelector("#agentCloseButton"),
  agentStatus: document.querySelector("#agentStatus"),
  agentSessionsButton: document.querySelector("#agentSessionsButton"),
  agentSessionsBalloon: document.querySelector("#agentSessionsBalloon"),
  agentSessionList: document.querySelector("#agentSessionList"),
  agentNewSessionButton: document.querySelector("#agentNewSessionButton"),
  agentContextButton: document.querySelector("#agentContextButton"),
  agentContextBalloon: document.querySelector("#agentContextBalloon"),
  agentSettingsButton: document.querySelector("#agentSettingsButton"),
  agentSettingsBalloon: document.querySelector("#agentSettingsBalloon"),
  agentMessages: document.querySelector("#agentMessages"),
  agentDiagnostics: document.querySelector("#agentDiagnostics"),
  agentContextPreview: document.querySelector("#agentContextPreview"),
  agentForm: document.querySelector("#agentForm"),
  agentModeSelect: document.querySelector("#agentModeSelect"),
  agentNodeSelect: document.querySelector("#agentNodeSelect"),
  agentInput: document.querySelector("#agentInput"),
  agentTokenUsage: document.querySelector("#agentTokenUsage"),
  agentSendButton: document.querySelector("#agentSendButton"),
  agentImageInput: document.querySelector("#agentImageInput"),
  agentAttachButton: document.querySelector("#agentAttachButton"),
  agentImagePreview: document.querySelector("#agentImagePreview"),
  launcherLogin: document.querySelector("#launcherLogin"),
  loginButton: document.querySelector("#loginButton"),
  loginAvatar: document.querySelector("#loginAvatar"),
  loginPopover: document.querySelector("#loginPopover"),
  loginTitle: document.querySelector("#loginTitle"),
  loginMeta: document.querySelector("#loginMeta"),
  googleSignInButton: document.querySelector("#googleSignInButton"),
  loginMessage: document.querySelector("#loginMessage"),
  logoutButton: document.querySelector("#logoutButton"),
  panelButtons: document.querySelectorAll("[data-panel]"),
  panelTabs: document.querySelectorAll(".panel-tab"),
  panelViews: document.querySelectorAll(".panel-view"),
};

const INITIAL_SPACE_WIDGET_LAYOUTS = readLocalSpaceWidgetLayouts();

const state = {
  bridgeUrl: "http://127.0.0.1:8790",
  config: null,
  googleClientId: "",
  adminEmail: "",
  googleButtonRenderedFor: "",
  authUser: null,
  authChecked: false,
  loginOpen: false,
  loginMessage: "",
  authenticatedBootstrapped: false,
  refreshInterval: 0,
  wasm: null,
  wasmReady: false,
  bridgeReady: false,
  resources: null,
  resourceInterval: 0,
  devices: [],
  deviceAuthority: null,
  devicesBusy: false,
  deviceSyncBusy: "",
  deviceMainBusy: "",
  devicesLoadedAt: "",
  nodes: [],
  tasks: [],
  securityLoop: null,
  securityFindings: [],
  securityBusy: false,
  securityInterval: 0,
  securityEvidenceId: "",
  selectedNode: "orchestrator",
  activePanel: "home",
  taskId: "",
  taskTimer: 0,
  actionBusy: "",
  lastError: "",
  widgetLayout: INITIAL_SPACE_WIDGET_LAYOUTS.home || {},
  widgetZ: WIDGET_Z_BASE,
  activeWidgetId: "",
  browserCapture: null,
  browserSessionId: "",
  browserBusy: false,
  browserQueue: Promise.resolve(),
  browserLive: false,
  browserLiveTimer: 0,
  browserSocket: null,
  browserStreamToken: 0,
  browserFrameCount: 0,
  browserResizeTimer: 0,
  browserUrlDraft: "",
  browserUrlDirty: false,
  browserPendingUrl: "",
  userEvents: [],
  eventSeq: 0,
  lastLogSummary: null,
  timeline: null,
  timelineBusy: false,
  observationSnapshot: null,
  observationRenderTimer: 0,
  observationPublishTimer: 0,
  observationPublishBusy: false,
  moduleSettings: readModuleSettings(),
  userSpaces: [],
  userStorage: null,
  localStorageEstimate: null,
  spaceWidgetLayouts: INITIAL_SPACE_WIDGET_LAYOUTS,
  activeSpaceMenuId: "",
  activeNodeMenuId: "",
  activeAppMenuId: "",
  activeAppMenuKind: "",
  activeNodeEditId: "",
  mobileLauncherTop: readLauncherPreference(),
  deleteSpaceTargetId: "",
  uiNavigationStack: [],
  uiNavigationSeq: 0,
  agentOpen: false,
  agentDragSuppressClick: false,
  agentBusy: false,
  agentAbortController: null,
  agentStopRequested: false,
  agentTurnTimer: 0,
  agentThinkingMessageId: "",
  agentTurnTimeoutMs: DEFAULT_AGENT_TURN_TIMEOUT_MS,
  agentTokenUsage: null,
  agentPendingImages: [],
  agentPendingAttachmentSummaries: [],
  agentOpenMessageMenuId: "",
  agentDeferredHmrReload: null,
  agentSessions: readAgentSessions(),
  activeAgentSessionId: "",
  agentTargetNode: "orchestrator",
  agentLayout: readAgentLayout(),
  agentPanelSide: "",
  appButtonCache: new Map(),
  spaceMiniMapVisible: false,
  spaceMiniMapHideTimer: 0,
  spacePanMomentumFrame: 0,
  spacePanMomentumActive: false,
};

function bytesFromBase64(value) {
  const bin = atob(value);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

function cleanText(value, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function truncateText(value, max = 180) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function formatTurnElapsed(ms) {
  const totalSeconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (totalMinutes < 60) return `${totalMinutes}m ${String(seconds).padStart(2, "0")}s`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${String(minutes).padStart(2, "0")}m`;
}

function redactValue(value) {
  if (value == null) return value;
  if (typeof value === "string") {
    if (/bearer\s+[a-z0-9._-]+/i.test(value)) return "[redacted bearer token]";
    if (value.length > 260) return truncateText(value, 260);
  }
  if (Array.isArray(value)) return value.map(redactValue);
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => {
        if (/password|token|secret|api[_-]?key|authorization/i.test(key)) return [key, "[redacted]"];
        return [key, redactValue(item)];
      })
    );
  }
  return value;
}

function summarizeEventTarget(target) {
  if (!target) return "unknown";
  const element = target.closest?.("button,input,textarea,select,a,[data-panel],[data-widget-id],[data-widget-app]");
  if (!element) return target.tagName ? target.tagName.toLowerCase() : "unknown";
  if (element.dataset?.widgetId) return `widget:${element.dataset.widgetId}`;
  if (element.dataset?.widgetApp) return `app:${element.dataset.widgetApp}`;
  if (element.dataset?.panel) return `panel:${element.dataset.panel}`;
  if (element.id) return `#${element.id}`;
  const label = element.getAttribute("aria-label") || element.getAttribute("title") || element.textContent || element.tagName;
  return truncateText(label, 48);
}

function describeEventTarget(target) {
  if (!target || !target.tagName) return { tag: "unknown" };
  const element = target;
  const closestWidget = element.closest?.("[data-widget-id]");
  const closestPanel = element.closest?.("[data-panel]");
  const classes = Array.from(element.classList || []).slice(0, 8);
  const path = [];
  let current = element;
  while (current && current !== els.app && path.length < 5) {
    const tag = current.tagName ? current.tagName.toLowerCase() : "";
    if (!tag) break;
    const id = current.id ? `#${current.id}` : "";
    const className = current.classList?.[0] ? `.${current.classList[0]}` : "";
    path.push(`${tag}${id}${className}`);
    current = current.parentElement;
  }
  return {
    tag: element.tagName.toLowerCase(),
    id: element.id || "",
    classes,
    role: element.getAttribute("role") || "",
    aria_label: element.getAttribute("aria-label") || "",
    title: truncateText(element.getAttribute("title") || "", 80),
    data_panel: element.dataset?.panel || closestPanel?.dataset?.panel || "",
    data_widget_id: element.dataset?.widgetId || closestWidget?.dataset?.widgetId || "",
    path,
  };
}

function recordUserEvent(type, options = {}) {
  const event = {
    schema: "hermes.space_os.user_event.v1",
    id: `evt_${Date.now().toString(36)}_${(state.eventSeq += 1).toString(36)}`,
    timestamp: new Date().toISOString(),
    type,
    source: options.source || "wasm-agent",
    target: options.target || "",
    summary: truncateText(options.summary || type, 160),
    data: redactValue(options.data || {}),
    redacted: Boolean(options.redacted),
    duration_ms: Number.isFinite(options.duration_ms) ? Math.round(options.duration_ms) : null,
  };
  state.userEvents.push(event);
  if (state.userEvents.length > USER_EVENT_LIMIT) {
    state.userEvents.splice(0, state.userEvents.length - USER_EVENT_LIMIT);
  }
  scheduleObservationRender();
  scheduleObservationPublish();
  return event;
}

function eventCounts() {
  return state.userEvents.reduce((counts, event) => {
    counts[event.type] = (counts[event.type] || 0) + 1;
    return counts;
  }, {});
}

function latestEvents(count = 36) {
  return state.userEvents.slice(-count).reverse();
}

function latestNonAgentClick() {
  return [...state.userEvents].reverse().find((event) => {
    if (!["workspace.click", "workspace.context_menu_requested"].includes(event.type)) return false;
    const target = String(event.target || "");
    const path = event.data?.target?.path || [];
    const id = event.data?.target?.id || "";
    return !target.includes("agent") && id !== "agentSendButton" && !path.some((item) => String(item).includes("agent-"));
  }) || null;
}

function buildObservationSnapshot() {
  const viewportRect = els.spaceViewport?.getBoundingClientRect?.() || { width: 0, height: 0 };
  const usableViewportRect = spaceViewportUsableRect() || viewportRect;
  const visualViewport = window.visualViewport;
  const browserRect = els.browserScreen?.getBoundingClientRect?.() || { width: 0, height: 0 };
  const recentErrors = state.userEvents
    .filter((event) => event.type.endsWith(".error") || event.data?.error)
    .slice(-8);
  const snapshot = {
    schema: "hermes.space_os.observation.v1",
    timestamp: new Date().toISOString(),
    workspace: {
      active_panel: state.activePanel,
      active_widget: state.activeWidgetId || "",
      layout_version: SPACE_LAYOUT_SCHEMA,
      modules: MODULE_DEFINITIONS.map((module) => ({
        id: module.id,
        title: module.title,
        enabled: isModuleEnabled(module.id),
        status: module.status,
      })),
      timeline: state.timeline ? {
        branch: state.timeline.branch,
        head: state.timeline.head,
        dirty: state.timeline.dirty,
        dirty_count: state.timeline.dirty_count,
        checkpoint_count: state.timeline.checkpoints?.length || 0,
      } : null,
      widget_count: document.querySelectorAll(".widget[data-widget-id]").length,
      viewport: { width: Math.round(viewportRect.width || 0), height: Math.round(viewportRect.height || 0) },
      viewport_diagnostics: {
        visual: visualViewport ? {
          width: Math.round(visualViewport.width || 0),
          height: Math.round(visualViewport.height || 0),
          offset_top: Math.round(visualViewport.offsetTop || 0),
          offset_left: Math.round(visualViewport.offsetLeft || 0),
        } : null,
        layout: {
          width: Math.round(window.innerWidth || 0),
          height: Math.round(window.innerHeight || 0),
        },
        space_viewport: {
          width: Math.round(viewportRect.width || 0),
          height: Math.round(viewportRect.height || 0),
        },
        usable_canvas: {
          width: Math.round(usableViewportRect.width || 0),
          height: Math.round(usableViewportRect.height || 0),
        },
        bottom_inset_px: viewportBottomInsetPx(),
        applied_canvas_padding_bottom_px: Math.round(appliedCanvasBottomPaddingPx()),
      },
    },
    browser: {
      url: state.browserCapture?.url || els.browserUrlInput?.value || "",
      domain: browserUrlHost(state.browserCapture?.url || els.browserUrlInput?.value || ""),
      status: els.browserStatus?.textContent || "",
      stream_mode: isBrowserStreamOpen() ? "websocket" : state.browserLive ? "polling" : "idle",
      live: Boolean(state.browserLive),
      busy: Boolean(state.browserBusy),
      pending_url: state.browserPendingUrl,
      frame_count: state.browserFrameCount,
      session_id: state.browserSessionId ? "present" : "",
      viewport: { width: Math.round(browserRect.width || 0), height: Math.round(browserRect.height || 0) },
      last_error: state.browserCapture?.status === "error" ? state.browserCapture.meta : "",
    },
    fleet: {
      bridge_ready: state.bridgeReady,
      bridge_url: state.bridgeUrl,
      selected_node: state.selectedNode,
      node_count: state.nodes.length,
      nodes: state.nodes.slice(0, 12).map((node) => ({
        id: node.id,
        status: node.status,
        runtime: node.runtime,
        running: node.running,
        model: node.model,
      })),
      resources: state.resources ? {
        cpu_percent: state.resources.cpu?.percent,
        memory_percent: state.resources.memory?.percent,
        disk_percent: state.resources.disk?.percent,
        uptime: state.resources.uptime?.display,
      } : null,
      last_error: state.lastError,
    },
    tasks: {
      active_task_id: state.taskId,
      status: state.taskId ? "running" : state.bridgeReady ? "idle" : "offline",
      recent: state.tasks.slice(0, 8).map((task) => ({
        id: task.task_id || task.id || "",
        status: task.status || "",
        target_node: task.target_node || "",
        preview: taskPreview(task),
      })),
      last_output_summary: truncateText(els.taskOutput?.textContent || "", 240),
    },
    logs: {
      selected_node: state.selectedNode,
      last_loaded: state.lastLogSummary,
      visible_summary: truncateText(els.logsOutput?.textContent || "", 240),
    },
    analytics: {
      event_count: state.userEvents.length,
      event_limit: USER_EVENT_LIMIT,
      counts: eventCounts(),
      recent_errors: recentErrors,
      last_interaction_at: state.userEvents.at(-1)?.timestamp || "",
      last_non_agent_click: latestNonAgentClick(),
    },
    user_events: latestEvents(40),
  };
  state.observationSnapshot = snapshot;
  return snapshot;
}

function scheduleObservationRender() {
  window.clearTimeout(state.observationRenderTimer);
  state.observationRenderTimer = window.setTimeout(renderObservation, 80);
}

function scheduleObservationPublish() {
  window.clearTimeout(state.observationPublishTimer);
  state.observationPublishTimer = window.setTimeout(publishObservationSnapshot, 250);
}

async function publishObservationSnapshot() {
  if (state.observationPublishBusy) {
    scheduleObservationPublish();
    return;
  }
  state.observationPublishBusy = true;
  try {
    await fetch("/observation/latest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildObservationSnapshot()),
    });
  } catch {
    // Observation publishing is a local debug affordance; UI behavior should not depend on it.
  } finally {
    state.observationPublishBusy = false;
  }
}

function renderObservation() {
  if (!els.observationSnapshot) return;
  if (!isModuleEnabled("observation")) {
    els.observationCount.textContent = "off";
    els.observationStats.replaceChildren(metric("Module", "Disabled"));
    els.observationTimeline.replaceChildren();
    els.observationSnapshot.textContent = "";
    return;
  }
  const snapshot = buildObservationSnapshot();
  els.observationCount.textContent = `${state.userEvents.length} events`;
  const counts = snapshot.analytics.counts;
  const topCounts = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  els.observationStats.replaceChildren(
    ...[
      ["Panel", snapshot.workspace.active_panel],
      ["Widget", snapshot.workspace.active_widget || "-"],
      ["Browser", snapshot.browser.domain || "-"],
      ["Stream", snapshot.browser.stream_mode],
      ["Events", String(snapshot.analytics.event_count)],
      ["Errors", String(snapshot.analytics.recent_errors.length)],
      ...topCounts.map(([type, count]) => [type, String(count)]),
    ].map(([label, value]) => metric(label, value))
  );
  els.observationTimeline.replaceChildren(
    ...latestEvents(18).map((event) => {
      const item = document.createElement("div");
      item.className = "observation-event";
      const title = document.createElement("strong");
      title.textContent = event.type;
      const meta = document.createElement("div");
      meta.className = "node-meta";
      meta.textContent = `${new Date(event.timestamp).toLocaleTimeString()} / ${event.target || event.source}`;
      const summary = document.createElement("div");
      summary.className = "observation-summary";
      summary.textContent = event.summary;
      item.append(title, meta, summary);
      return item;
    })
  );
  els.observationSnapshot.textContent = JSON.stringify(snapshot, null, 2);
}

function moduleCard(module) {
  const enabled = isModuleEnabled(module.id);
  const core = Boolean(module.core);
  const card = document.createElement("article");
  card.className = `module-card${enabled ? " enabled" : ""}${core ? " core" : ""}`;

  const copy = document.createElement("div");
  copy.className = "module-copy";
  const title = document.createElement("strong");
  title.textContent = module.title;
  const detail = document.createElement("p");
  detail.textContent = module.detail;
  const meta = document.createElement("span");
  meta.textContent = module.status;
  copy.append(title, detail, meta);

  const label = document.createElement("label");
  label.className = "module-toggle";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = enabled;
  input.disabled = core;
  input.setAttribute("aria-label", `${enabled ? "Disable" : "Enable"} ${module.title}`);
  const control = document.createElement("span");
  control.textContent = core ? "Core" : (enabled ? "On" : "Off");
  input.addEventListener("change", () => {
    setModuleEnabled(module.id, input.checked);
  });
  label.append(input, control);

  card.append(copy, label);
  return card;
}

function renderModuleList(container) {
  if (!container) return;
  container.replaceChildren(...MODULE_DEFINITIONS.map(moduleCard));
}

function renderModules() {
  renderModuleList(els.moduleList);
  renderModuleList(els.homeModuleList);
}

function renderTimeline() {
  if (!els.timelineGraph || !els.timelineDetails) return;
  const timeline = state.timeline;
  if (!isModuleEnabled("timeline")) {
    els.timelineStatus.textContent = "off";
    els.timelineGraph.replaceChildren();
    els.timelineDetails.replaceChildren(metric("Module", "Disabled"));
    return;
  }
  if (!timeline) {
    els.timelineStatus.textContent = "pending";
    els.timelineGraph.replaceChildren(metric("Timeline", "Not loaded"));
    els.timelineDetails.replaceChildren(metric("Status", "Refresh timeline"));
    return;
  }
  els.timelineStatus.textContent = timeline.dirty ? `${timeline.dirty_count} dirty` : "clean";
  els.timelineStatus.className = `widget-chip ${timeline.dirty ? "" : "ok"}`;
  els.timelineBranch.textContent = timeline.branch || "branch";
  const recent = (timeline.recent || []).slice(0, 5);
  const checkpoints = (timeline.checkpoints || []).slice(0, 5);
  els.timelineGraph.replaceChildren(
    ...[
      ...checkpoints.map((checkpoint) => ({ kind: "checkpoint", label: checkpoint.name, meta: checkpoint.head })),
      ...recent.map((line) => ({ kind: "commit", label: line, meta: "" })),
    ].slice(0, 7).map((item) => {
      const row = document.createElement("div");
      row.className = `timeline-node ${item.kind}`;
      const dot = document.createElement("span");
      dot.className = "timeline-dot";
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.label;
      const meta = document.createElement("span");
      meta.textContent = item.meta || item.kind;
      copy.append(title, meta);
      row.append(dot, copy);
      return row;
    })
  );
  const actionRows = (timeline.actions || []).map((action) => [
    action.label,
    action.enabled ? action.description : `${action.description} (planned)`,
  ]);
  els.timelineDetails.replaceChildren(
    metric("Branch", `${timeline.branch} @ ${timeline.head}`),
    metric("Worktree", timeline.dirty ? `${timeline.dirty_count} changed paths` : "Clean"),
    metric("Checkpoints", String(timeline.checkpoints?.length || 0)),
    ...actionRows.map(([label, value]) => metric(label, value))
  );
}

async function loadTimeline(origin = "auto") {
  if (!isModuleEnabled("timeline") || state.timelineBusy) return;
  state.timelineBusy = true;
  if (els.timelineRefreshButton) els.timelineRefreshButton.disabled = true;
  const startedAt = performance.now();
  try {
    const payload = await fetchJson(`/timeline/status?space=${encodeURIComponent(activeSpaceStorageId())}`, { timeoutMs: 10000 });
    state.timeline = payload.timeline || null;
    renderTimeline();
    if (origin !== "auto") {
      recordUserEvent("timeline.loaded", {
        target: "timeline",
        summary: `Loaded ${state.timeline?.branch || "timeline"} at ${state.timeline?.head || "head"}`,
        data: { dirty: state.timeline?.dirty, dirty_count: state.timeline?.dirty_count },
        duration_ms: performance.now() - startedAt,
      });
    }
  } catch (error) {
    state.lastError = error.message;
    if (els.timelineStatus) {
      els.timelineStatus.textContent = "error";
      els.timelineStatus.className = "widget-chip err";
    }
    recordUserEvent("timeline.load_error", {
      target: "timeline",
      summary: error.message,
      data: { error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    state.timelineBusy = false;
    if (els.timelineRefreshButton) els.timelineRefreshButton.disabled = false;
  }
}

function applyModuleVisibility() {
  document.querySelectorAll("[data-module-target]").forEach((element) => {
    const moduleId = element.dataset.moduleTarget;
    const enabled = isModuleEnabled(moduleId);
    element.hidden = !enabled;
    element.classList.toggle("module-disabled", !enabled);
  });
  if (!isModuleEnabled("embedded-assistant")) setAgentOpen(false);
  if (!isModuleEnabled("host-browser")) {
    if (isBrowserStreamOpen() || state.browserLive) stopBrowserLive();
    els.browserScreen.classList.remove("is-busy");
  }
  if (!isPanelAvailable(state.activePanel)) setPanel("modules");
}

function setModuleEnabled(moduleId, enabled) {
  if (moduleDefinitionById(moduleId)?.core) {
    state.moduleSettings[moduleId] = true;
    renderModules();
    return;
  }
  const previous = isModuleEnabled(moduleId);
  state.moduleSettings[moduleId] = Boolean(enabled);
  saveModuleSettings();
  applyModuleVisibility();
  renderModules();
  renderObservation();
  if (previous !== Boolean(enabled)) {
    recordUserEvent("modules.setting_changed", {
      target: `module:${moduleId}`,
      summary: `${enabled ? "Enabled" : "Disabled"} ${moduleId}`,
      data: { module_id: moduleId, enabled: Boolean(enabled) },
    });
  }
}

function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

function bytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = number;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}

function compactGb(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "-";
  const gb = number / (1024 ** 3);
  return `${gb.toFixed(1).replace(".", ",")}GB`;
}

function activeSpaceStorageId(panel = state.activePanel) {
  if (isUserSpacePanel(panel)) return panel;
  if (isAdminPanel(panel)) return "admin";
  return "home";
}

function defaultWidgetLayoutForPanel(panel = state.activePanel) {
  return {
    ...Object.fromEntries(spaceApps(panel).map((app) => [app.id, { minimized: true }])),
    ...FIXED_WIDGET_LAYOUT,
  };
}

function layoutKeysForPanel(panel = state.activePanel) {
  return new Set([
    "__canvas",
    ...spaceApps(panel).map((app) => app.id),
    ...Object.keys(FIXED_WIDGET_LAYOUT),
  ]);
}

function sanitizeWidgetLayoutForPanel(layout, panel = state.activePanel) {
  if (!layout || typeof layout !== "object") return {};
  const allowedKeys = layoutKeysForPanel(panel);
  return Object.fromEntries(
    Object.entries(layout).filter(([key]) => allowedKeys.has(key))
  );
}

function saveWidgetLayout() {
  const spaceId = activeSpaceStorageId();
  state.widgetLayout = sanitizeWidgetLayoutForPanel(state.widgetLayout);
  state.spaceWidgetLayouts[spaceId] = state.widgetLayout;
  saveLocalSpaceWidgetLayouts();
}

function applySpaceWidgetLayout(panel = state.activePanel) {
  const spaceId = activeSpaceStorageId(panel);
  const layout = state.spaceWidgetLayouts[spaceId];
  state.widgetLayout = {
    ...defaultWidgetLayoutForPanel(panel),
    ...sanitizeWidgetLayoutForPanel(layout, panel),
  };
  applyCanvasDensity({ renderMiniMap: false });
  applyWidgetLayout();
  renderSpaceMiniMap();
}

function defaultModuleSettings() {
  return {
    ...Object.fromEntries(MODULE_DEFINITIONS.map((module) => [module.id, module.defaultEnabled !== false])),
    __imageAnalyzerRevision: IMAGE_CARD_ANALYZER_REVISION,
  };
}

function readModuleSettings() {
  const defaults = defaultModuleSettings();
  try {
    const raw = JSON.parse(localStorage.getItem(MODULE_SETTINGS_STORAGE_KEY) || "{}");
    if (!raw || typeof raw !== "object") return defaults;
    const knownModuleIds = new Set(MODULE_DEFINITIONS.map((module) => module.id));
    const stored = Object.fromEntries(
      Object.entries(raw)
        .filter(([key]) => knownModuleIds.has(key))
        .map(([key, value]) => [key, Boolean(value)])
    );
    for (const module of MODULE_DEFINITIONS) {
      if (module.core) stored[module.id] = true;
    }
    const settings = { ...defaults, ...stored };
    if (raw.__imageAnalyzerRevision !== IMAGE_CARD_ANALYZER_REVISION) {
      for (const moduleId of ["image-card-core", "barcode-reader", "ocr"]) {
        settings[moduleId] = defaults[moduleId] !== false;
      }
    }
    settings.__imageAnalyzerRevision = IMAGE_CARD_ANALYZER_REVISION;
    return settings;
  } catch {
    return defaults;
  }
}

function saveModuleSettings() {
  try {
    localStorage.setItem(MODULE_SETTINGS_STORAGE_KEY, JSON.stringify({
      ...state.moduleSettings,
      __imageAnalyzerRevision: IMAGE_CARD_ANALYZER_REVISION,
    }));
  } catch {
    // Module settings are local convenience state; defaults keep the app usable.
  }
}

function readLauncherPreference() {
  try {
    const raw = JSON.parse(localStorage.getItem(LAUNCHER_PREF_STORAGE_KEY) || "{}");
    return Boolean(raw?.mobileTop);
  } catch {
    return false;
  }
}

function saveLauncherPreference() {
  try {
    localStorage.setItem(LAUNCHER_PREF_STORAGE_KEY, JSON.stringify({ mobileTop: Boolean(state.mobileLauncherTop) }));
  } catch {
    // Launcher placement is local UI preference; defaults keep navigation available.
  }
}

function readLocalSpaceWidgetLayouts() {
  try {
    const raw = JSON.parse(localStorage.getItem(SPACE_WIDGET_LAYOUTS_STORAGE_KEY) || "{}");
    if (!raw || typeof raw !== "object") return {};
    return Object.fromEntries(
      Object.entries(raw).filter(([, layout]) => layout && typeof layout === "object")
    );
  } catch {
    return {};
  }
}

function saveLocalSpaceWidgetLayouts() {
  try {
    localStorage.setItem(SPACE_WIDGET_LAYOUTS_STORAGE_KEY, JSON.stringify(state.spaceWidgetLayouts || {}));
  } catch {
    // Device layout is ephemeral and client-local by default.
  }
}

function applyLauncherPreference() {
  if (!els.app) return;
  els.app.dataset.mobileLauncher = state.mobileLauncherTop ? "top" : "left";
}

function saveUserSpaces() {
  if (state.authUser) {
    void fetchJson("/spaces", {
      method: "POST",
      timeoutMs: 8000,
      body: { action: "replace", spaces: state.userSpaces },
    }).catch((error) => {
      recordUserEvent("workspace.spaces_save_error", {
        target: "spaces",
        summary: error.message,
        data: { error: error.message },
      });
    });
  }
}

async function loadUserSpaces() {
  if (!state.authUser) return;
  try {
    const payload = await fetchJson("/spaces", { timeoutMs: 8000 });
    state.userSpaces = Array.isArray(payload.spaces) ? payload.spaces : [];
    state.userStorage = payload.storage || null;
    state.spaceWidgetLayouts = readLocalSpaceWidgetLayouts();
    applySpaceWidgetLayout(state.activePanel);
    renderSpaceLauncher();
  } catch (error) {
    recordUserEvent("workspace.spaces_load_error", {
      target: "spaces",
      summary: error.message,
      data: { error: error.message },
    });
  }
}

async function loadLocalStorageEstimate() {
  if (!navigator.storage?.estimate) {
    state.localStorageEstimate = { usage: 0, quota: 0 };
    return;
  }
  try {
    state.localStorageEstimate = await navigator.storage.estimate();
  } catch {
    state.localStorageEstimate = { usage: 0, quota: 0 };
  }
  if (els.configModal && !els.configModal.hidden) renderConfigModal();
}

function isUserSpacePanel(panel) {
  return state.userSpaces.some((space) => space.id === panel);
}

function normalizePanel(panel) {
  const value = cleanText(panel, "home");
  return value === "space" ? "admin" : value;
}

function isAdminPanel(panel) {
  return ADMIN_PANEL_IDS.has(normalizePanel(panel));
}

function moduleDefinitionById(moduleId) {
  return MODULE_DEFINITIONS.find((module) => module.id === moduleId) || null;
}

function isModuleEnabled(moduleId) {
  if (moduleDefinitionById(moduleId)?.core) return true;
  if (Object.prototype.hasOwnProperty.call(state.moduleSettings, moduleId)) {
    return state.moduleSettings[moduleId] !== false;
  }
  return moduleDefinitionById(moduleId)?.defaultEnabled !== false;
}

function isPanelAvailable(panel) {
  panel = normalizePanel(panel);
  if (panel === "home" || isUserSpacePanel(panel)) return true;
  if (isAdminPanel(panel) && !isAdminUser()) return false;
  if (panel === "observe") return isModuleEnabled("observation");
  return true;
}

function defaultAgentMessage() {
  return {
    role: "assistant",
    content: AGENT_DEFAULT_MESSAGE_CONTENT,
  };
}

function createAgentSession(title = "New session") {
  return {
    id: `agent_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    title,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [defaultAgentMessage()],
    diagnostics: null,
    changed_files: [],
    context_preview: [],
  };
}

function normalizeStoredImage(image) {
  const source = image && typeof image === "object" ? image : { data_url: image };
  const dataUrl = String(source.data_url || "");
  if (!dataUrl.startsWith("data:image/")) return null;
  if (dataUrlByteLength(dataUrl) > AGENT_IMAGE_MAX_BYTES * 2) return null;
  return {
    data_url: dataUrl,
    name: cleanText(source.name, "Attached image"),
    type: cleanText(source.type, ""),
    size: Number.isFinite(source.size) ? source.size : dataUrlByteLength(dataUrl),
    width: Number.isFinite(source.width) ? source.width : undefined,
    height: Number.isFinite(source.height) ? source.height : undefined,
    image_card: source.image_card && typeof source.image_card === "object" ? source.image_card : undefined,
    asset: source.asset && typeof source.asset === "object" ? source.asset : undefined,
  };
}

function normalizeStoredMessage(message) {
  const source = message && typeof message === "object" ? message : defaultAgentMessage();
  const normalized = {
    ...source,
    role: source.role === "user" ? "user" : "assistant",
    content: String(source.content || ""),
    images: Array.isArray(source.images)
      ? source.images.map(normalizeStoredImage).filter(Boolean).slice(0, AGENT_MAX_IMAGES)
      : undefined,
    attachments: Array.isArray(source.attachments)
      ? source.attachments.filter((item) => item && typeof item === "object").slice(0, AGENT_MAX_IMAGES)
      : undefined,
  };
  if (normalized.pending) {
    normalized.pending = false;
    normalized.phase = "Reloaded";
    normalized.content = normalized.content || "This assistant turn was interrupted by a page reload.";
    normalized.duration_ms = Number.isFinite(normalized.duration_ms)
      ? normalized.duration_ms
      : Date.now() - Number(normalized.turn_started_at || Date.now());
    normalized.actions = (Array.isArray(normalized.actions) ? normalized.actions : []).map((action) => (
      action.status === "running" ? { ...action, status: "error", detail: "Interrupted by reload" } : action
    ));
  }
  if (!normalized.images?.length) delete normalized.images;
  if (!normalized.attachments?.length) delete normalized.attachments;
  return normalized;
}

function normalizeStoredSession(session) {
  const source = session && typeof session === "object" ? session : createAgentSession("Main session");
  const messages = Array.isArray(source.messages) && source.messages.length
    ? source.messages.map(normalizeStoredMessage)
    : [defaultAgentMessage()];
  return {
    ...source,
    messages,
    diagnostics: source.diagnostics || null,
    changed_files: Array.isArray(source.changed_files) ? source.changed_files : [],
    context_preview: Array.isArray(source.context_preview) ? source.context_preview : [],
  };
}

function readAgentSessions() {
  try {
    const raw = JSON.parse(localStorage.getItem(AGENT_SESSIONS_STORAGE_KEY) || "[]");
    if (Array.isArray(raw) && raw.length) return raw.map(normalizeStoredSession);
  } catch {
    // A missing or corrupt transcript cache should never block the app.
  }
  return [createAgentSession("Main session")];
}

function saveAgentSessions() {
  try {
    localStorage.setItem(AGENT_SESSIONS_STORAGE_KEY, JSON.stringify(state.agentSessions.slice(0, 20)));
  } catch {
    // Session persistence is a convenience; chat should still work without it.
  }
}

function agentTranscriptForRequest() {
  return activeAgentSession().messages
    .filter((message) => !message.pending && message.content !== AGENT_DEFAULT_MESSAGE_CONTENT)
    .slice(-6)
    .map((message) => ({
      role: message.role,
      content: truncateText(message.content, 600),
    }));
}

function readAgentLayout() {
  try {
    const raw = JSON.parse(localStorage.getItem(AGENT_LAYOUT_STORAGE_KEY) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

function saveAgentLayout() {
  try {
    localStorage.setItem(AGENT_LAYOUT_STORAGE_KEY, JSON.stringify(state.agentLayout));
  } catch {
    // Layout persistence is best effort.
  }
}

function activeAgentSession() {
  let session = state.agentSessions.find((item) => item.id === state.activeAgentSessionId);
  if (!session) {
    session = state.agentSessions[0] || createAgentSession("Main session");
    if (!state.agentSessions.length) state.agentSessions.push(session);
    state.activeAgentSessionId = session.id;
  }
  return session;
}

function agentTargetNode() {
  return cleanText(state.agentTargetNode || state.selectedNode || "orchestrator", "orchestrator");
}

function availableAgentNodes() {
  const ids = new Set(["orchestrator"]);
  if (state.selectedNode) ids.add(state.selectedNode);
  state.nodes.forEach((node) => {
    if (node.id) ids.add(node.id);
  });
  return Array.from(ids);
}

function renderAgentNodeSelect() {
  if (!els.agentNodeSelect) return;
  const nodes = availableAgentNodes();
  const current = nodes.includes(agentTargetNode()) ? agentTargetNode() : nodes[0];
  state.agentTargetNode = current;
  els.agentNodeSelect.replaceChildren(
    ...nodes.map((nodeId) => {
      const option = document.createElement("option");
      option.value = nodeId;
      option.textContent = nodeId;
      return option;
    })
  );
  els.agentNodeSelect.value = current;
}

function setAgentTargetNode(nodeId) {
  const next = cleanText(nodeId, "orchestrator");
  const previous = state.agentTargetNode;
  state.agentTargetNode = next;
  renderAgentNodeSelect();
  if (previous !== next) {
    recordUserEvent("agent.target_node_selected", {
      target: `node:${next}`,
      summary: `Chat target node changed to ${next}`,
      data: { node_id: next, previous_node_id: previous || "" },
    });
  }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function isCompactViewport() {
  return window.matchMedia("(max-width: 820px)").matches;
}

function isPrimaryPointer(event) {
  return event?.isPrimary !== false && (event?.pointerType !== "mouse" || event.button === 0);
}

function visualViewportHeight() {
  const height = Number(window.visualViewport?.height || window.innerHeight || 0);
  if (!Number.isFinite(height) || height <= 0) return 0;
  return Math.floor(height);
}

function viewportBottomInsetPx() {
  const viewport = window.visualViewport;
  const layoutHeight = Math.max(
    Number(document.documentElement?.clientHeight || 0),
    Number(window.innerHeight || 0)
  );
  if (!viewport || !layoutHeight) return 0;
  const visualBottom = Number(viewport.offsetTop || 0) + Number(viewport.height || 0);
  const visualInset = Math.max(0, layoutHeight - visualBottom);
  const appRect = els.app?.getBoundingClientRect?.();
  const appInset = appRect ? Math.max(0, appRect.bottom - visualBottom) : 0;
  const inset = Math.max(visualInset, appInset);
  const keyboardSized = inset > Math.max(96, layoutHeight * 0.18);
  return keyboardSized ? 0 : Math.round(inset);
}

function syncVisualViewportSize() {
  const height = visualViewportHeight();
  if (!height) return;
  document.documentElement.style.setProperty("--wasm-visual-height", `${height}px`);
  document.documentElement.style.setProperty("--wasm-viewport-bottom-inset", `${viewportBottomInsetPx()}px`);
}

function spaceSurface() {
  return els.spaceBoard || els.spaceViewport;
}

function appliedCanvasBottomPaddingPx() {
  const value = parseFloat(getComputedStyle(els.mainStage || document.documentElement).paddingBottom);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function spaceViewportUsableRect() {
  const rect = els.spaceViewport?.getBoundingClientRect?.();
  if (!rect) return null;
  const unappliedInset = isCompactViewport()
    ? Math.max(0, viewportBottomInsetPx() - appliedCanvasBottomPaddingPx())
    : 0;
  const bottom = Math.max(rect.top, rect.bottom - unappliedInset);
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom,
    width: rect.width,
    height: Math.max(1, bottom - rect.top),
  };
}

function widgetCanvasMovementBounds(widget) {
  const board = spaceSurface();
  const boardRect = board?.getBoundingClientRect?.();
  if (!widget || !boardRect?.width || !boardRect?.height) return null;
  return {
    minLeft: SPACE_CANVAS_EDGE_INSET_PX,
    minTop: SPACE_CANVAS_EDGE_INSET_PX,
    maxLeft: Math.max(SPACE_CANVAS_EDGE_INSET_PX, boardRect.width - widget.offsetWidth - SPACE_CANVAS_EDGE_INSET_PX),
    maxTop: Math.max(SPACE_CANVAS_EDGE_INSET_PX, boardRect.height - widget.offsetHeight - SPACE_CANVAS_EDGE_INSET_PX),
    width: boardRect.width,
    height: boardRect.height,
  };
}

function canvasLayout() {
  state.widgetLayout.__canvas = state.widgetLayout.__canvas && typeof state.widgetLayout.__canvas === "object"
    ? state.widgetLayout.__canvas
    : {};
  return state.widgetLayout.__canvas;
}

function canvasDensity() {
  const density = Number(canvasLayout().density || 1);
  return clamp(Number.isFinite(density) ? density : 1, 1, CANVAS_DENSITY_MAX);
}

function canvasContentExtent() {
  return Object.entries(state.widgetLayout || {}).reduce((current, [key, layout]) => {
    if (key === "__canvas" || !layout || typeof layout !== "object") return current;
    const appLeft = Number(layout.appLeftPx);
    const appTop = Number(layout.appTopPx);
    if (Number.isFinite(appLeft)) current.width = Math.max(current.width, appLeft + 96);
    if (Number.isFinite(appTop)) current.height = Math.max(current.height, appTop + 104);
    return current;
  }, { width: 0, height: 0 });
}

function applyCanvasDensity(options = {}) {
  const board = spaceSurface();
  const viewport = els.spaceViewport;
  if (!board || !viewport) return;
  const rect = spaceViewportUsableRect() || viewport.getBoundingClientRect();
  const density = canvasDensity();
  const extent = canvasContentExtent();
  board.style.width = `${Math.max(rect.width, Math.round(rect.width * density), extent.width)}px`;
  board.style.height = `${Math.max(rect.height, Math.round(rect.height * density), extent.height)}px`;
  drawCanvas();
  updateSpaceNavigationHints();
  if (options.renderMiniMap !== false) renderSpaceMiniMap();
}

function spaceMapMetrics() {
  const board = spaceSurface();
  const viewport = els.spaceViewport;
  if (!board || !viewport) return null;
  const boardRect = board.getBoundingClientRect();
  const viewportRect = viewport.getBoundingClientRect();
  return {
    board,
    viewport,
    boardRect,
    viewportRect,
    width: Math.max(viewport.clientWidth, board.offsetWidth, boardRect.width),
    height: Math.max(viewport.clientHeight, board.offsetHeight, boardRect.height),
  };
}

function visibleBoardRect(metrics) {
  const left = clamp(metrics.viewport.scrollLeft, 0, metrics.width);
  const top = clamp(metrics.viewport.scrollTop, 0, metrics.height);
  const right = clamp(left + metrics.viewport.clientWidth, left, metrics.width);
  const visibleHeight = (spaceViewportUsableRect()?.height || metrics.viewport.clientHeight);
  const bottom = clamp(top + visibleHeight, top, metrics.height);
  return {
    left,
    top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top),
  };
}

function miniMapPlotMetrics(metrics, mapWidth, mapHeight) {
  const padding = SPACE_MINIMAP_PADDING_PX;
  const availableWidth = Math.max(1, mapWidth - padding * 2);
  const availableHeight = Math.max(1, mapHeight - padding * 2);
  const scale = Math.min(availableWidth / Math.max(1, metrics.width), availableHeight / Math.max(1, metrics.height));
  const boardWidth = Math.max(1, Math.round(metrics.width * scale));
  const boardHeight = Math.max(1, Math.round(metrics.height * scale));
  const width = Math.max(1, boardWidth);
  const height = Math.max(1, boardHeight);
  return {
    boardWidth,
    boardHeight,
    mapWidth: boardWidth + padding * 2,
    mapHeight: boardHeight + padding * 2,
    width,
    height,
    left: padding,
    top: padding,
    scaleX: width / Math.max(1, metrics.width),
    scaleY: height / Math.max(1, metrics.height),
  };
}

function cssPixelValue(element, name, fallback) {
  const value = parseFloat(getComputedStyle(element).getPropertyValue(name));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function miniMapProjectRect(rect, plot, minWidth = 1, minHeight = 1) {
  const width = clamp(rect.width * plot.scaleX, minWidth, plot.width);
  const height = clamp(rect.height * plot.scaleY, minHeight, plot.height);
  return {
    left: clamp(rect.left * plot.scaleX, 0, Math.max(0, plot.width - width)),
    top: clamp(rect.top * plot.scaleY, 0, Math.max(0, plot.height - height)),
    width,
    height,
  };
}

function miniMapPixelRect(rect, plot) {
  const maxWidth = Math.max(1, Math.round(plot.width));
  const maxHeight = Math.max(1, Math.round(plot.height));
  const left = clamp(Math.floor(rect.left), 0, Math.max(0, maxWidth - 1));
  const top = clamp(Math.floor(rect.top), 0, Math.max(0, maxHeight - 1));
  const right = clamp(Math.ceil(rect.left + rect.width), left + 1, maxWidth);
  const bottom = clamp(Math.ceil(rect.top + rect.height), top + 1, maxHeight);
  return {
    left,
    top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top),
  };
}

function applyMiniMapPixelRect(element, rect, plot) {
  const pixels = miniMapPixelRect(rect, plot);
  element.style.left = `${pixels.left}px`;
  element.style.top = `${pixels.top}px`;
  element.style.width = `${pixels.width}px`;
  element.style.height = `${pixels.height}px`;
}

function boardRectContains(outer, inner, tolerance = 0.75) {
  return inner.left >= outer.left - tolerance
    && inner.top >= outer.top - tolerance
    && inner.left + inner.width <= outer.left + outer.width + tolerance
    && inner.top + inner.height <= outer.top + outer.height + tolerance;
}

function miniMapProjectAppMarker(entity, plot, visibleRect) {
  const footprintSize = Math.max(entity.width * plot.scaleX, entity.height * plot.scaleY);
  const size = clamp(footprintSize, 2, 6);
  const visibleBounds = boardRectContains(visibleRect, entity)
    ? miniMapProjectRect(visibleRect, plot)
    : { left: 0, top: 0, width: plot.width, height: plot.height };
  const width = Math.min(size, visibleBounds.width);
  const height = Math.min(size, visibleBounds.height);
  const centerX = (entity.left + entity.width / 2) * plot.scaleX;
  const centerY = (entity.top + entity.height / 2) * plot.scaleY;
  return {
    left: clamp(centerX - width / 2, visibleBounds.left, visibleBounds.left + Math.max(0, visibleBounds.width - width)),
    top: clamp(centerY - height / 2, visibleBounds.top, visibleBounds.top + Math.max(0, visibleBounds.height - height)),
    width,
    height,
  };
}

function miniMapEntityFromElement(element, metrics, kind, boardBounds) {
  const rect = element?.getBoundingClientRect?.();
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  const rawLeft = rect.left - metrics.viewportRect.left + metrics.viewport.scrollLeft;
  const rawTop = rect.top - metrics.viewportRect.top + metrics.viewport.scrollTop;
  const left = clamp(rawLeft, 0, Math.max(0, boardBounds.width));
  const top = clamp(rawTop, 0, Math.max(0, boardBounds.height));
  const right = clamp(rawLeft + rect.width, 0, Math.max(0, boardBounds.width));
  const bottom = clamp(rawTop + rect.height, 0, Math.max(0, boardBounds.height));
  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0) return null;
  return {
    kind,
    left,
    top,
    width,
    height,
  };
}

function miniMapEntityFromRect(rect, kind, boardBounds) {
  const left = clamp(rect.left, 0, Math.max(0, boardBounds.width));
  const top = clamp(rect.top, 0, Math.max(0, boardBounds.height));
  const right = clamp(rect.left + rect.width, 0, Math.max(0, boardBounds.width));
  const bottom = clamp(rect.top + rect.height, 0, Math.max(0, boardBounds.height));
  if (right <= left || bottom <= top) return null;
  return {
    kind,
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}

function miniMapAppEntityFromButton(button, metrics, boardBounds) {
  const appId = button?.dataset?.widgetApp || "";
  const layout = appId ? state.widgetLayout[appId] || {} : {};
  if (!appId || layout.minimized === false) return null;
  const icon = button.querySelector?.(".space-app-icon");
  const iconEntity = miniMapEntityFromElement(icon || button, metrics, "app", boardBounds);
  if (iconEntity) return iconEntity;
  const width = icon?.offsetWidth || button.offsetWidth || 40;
  const height = icon?.offsetHeight || button.offsetHeight || 40;
  const styleLeft = parseFloat(button.style.left || "");
  const styleTop = parseFloat(button.style.top || "");
  const rawButtonLeft = Number.isFinite(Number(layout.appLeftPx))
    ? Number(layout.appLeftPx)
    : (Number.isFinite(styleLeft) ? styleLeft : 0);
  const rawButtonTop = Number.isFinite(Number(layout.appTopPx))
    ? Number(layout.appTopPx)
    : (Number.isFinite(styleTop) ? styleTop : 0);
  const rawLeft = rawButtonLeft + Math.max(0, ((button.offsetWidth || 62) - width) / 2);
  const rawTop = rawButtonTop + 6;
  return miniMapEntityFromRect({ left: rawLeft, top: rawTop, width, height }, "app", boardBounds);
}

function spaceMiniMapEntities(metrics) {
  const boardBounds = { width: metrics.width, height: metrics.height };
  const apps = Array.from(els.appLayer?.querySelectorAll?.(".space-app-button") || [])
    .map((button) => miniMapAppEntityFromButton(button, metrics, boardBounds))
    .filter(Boolean);
  const widgets = Array.from(document.querySelectorAll(".widget[data-widget-id]"))
    .filter((widget) => !widget.hidden && !widget.classList.contains("is-minimized") && !widget.classList.contains("is-maximized"))
    .map((widget) => miniMapEntityFromElement(widget, metrics, "widget", boardBounds))
    .filter(Boolean);
  return [...apps, ...widgets];
}

function miniMapEntityClassName(entity) {
  const classes = ["space-minimap-entity"];
  if (entity.kind.includes("app")) classes.push("is-app");
  if (entity.kind.includes("open")) classes.push("is-open");
  if (entity.kind === "widget") classes.push("is-widget");
  return classes.join(" ");
}

function renderSpaceMiniMap() {
  const map = els.spaceMiniMap;
  const metrics = spaceMapMetrics();
  if (!map || !metrics) return;
  if (!spaceMiniMapCanRender(metrics)) {
    map.replaceChildren();
    return;
  }
  const mapWidth = cssPixelValue(map, "--space-minimap-max-width", 184);
  const mapHeight = cssPixelValue(map, "--space-minimap-max-height", 112);
  const plot = miniMapPlotMetrics(metrics, mapWidth, mapHeight);
  map.style.width = `${Math.round(plot.mapWidth)}px`;
  map.style.height = `${Math.round(plot.mapHeight)}px`;
  const boardLayer = document.createElement("div");
  boardLayer.className = "space-minimap-board";
  boardLayer.style.left = `${plot.left}px`;
  boardLayer.style.top = `${plot.top}px`;
  boardLayer.style.width = `${plot.boardWidth}px`;
  boardLayer.style.height = `${plot.boardHeight}px`;
  const visibleRect = visibleBoardRect(metrics);

  spaceMiniMapEntities(metrics).forEach((entity) => {
    const item = document.createElement("span");
    item.className = miniMapEntityClassName(entity);
    const projected = entity.kind.includes("app")
      ? miniMapProjectAppMarker(entity, plot, visibleRect)
      : miniMapProjectRect(entity, plot, 5, 4);
    applyMiniMapPixelRect(item, projected, plot);
    boardLayer.append(item);
  });

  const viewportBox = document.createElement("span");
  viewportBox.className = "space-minimap-viewport";
  const viewportRect = miniMapProjectRect(visibleRect, plot);
  applyMiniMapPixelRect(viewportBox, viewportRect, plot);
  boardLayer.append(viewportBox);
  map.replaceChildren(boardLayer);
}

function updateSpaceNavigationHints() {
  const viewport = els.spaceViewport;
  if (!viewport) return;
  const canLeft = viewport.scrollLeft > 1;
  const canRight = viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1;
  const canUp = viewport.scrollTop > 1;
  const canDown = viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1;
  viewport.classList.toggle("can-scroll-left", canLeft);
  viewport.classList.toggle("can-scroll-right", canRight);
  viewport.classList.toggle("can-scroll-up", canUp);
  viewport.classList.toggle("can-scroll-down", canDown);
}

function stopSpacePanMomentum() {
  if (state.spacePanMomentumFrame) cancelAnimationFrame(state.spacePanMomentumFrame);
  state.spacePanMomentumFrame = 0;
  state.spacePanMomentumActive = false;
  els.spaceViewport?.classList.remove("is-momentum");
}

function weightedSpacePanVelocity(samples) {
  const recent = samples.filter((sample) => sample.dt > 0);
  const totalMs = recent.reduce((total, sample) => total + sample.dt, 0);
  if (!totalMs) return { x: 0, y: 0 };
  const weighted = recent.reduce((velocity, sample) => {
    const weight = sample.dt / totalMs;
    velocity.x += sample.vx * weight;
    velocity.y += sample.vy * weight;
    return velocity;
  }, { x: 0, y: 0 });
  return {
    x: clamp(weighted.x * SPACE_PAN_MOMENTUM_LAUNCH_MULTIPLIER, -SPACE_PAN_MOMENTUM_MAX_VELOCITY, SPACE_PAN_MOMENTUM_MAX_VELOCITY),
    y: clamp(weighted.y * SPACE_PAN_MOMENTUM_LAUNCH_MULTIPLIER, -SPACE_PAN_MOMENTUM_MAX_VELOCITY, SPACE_PAN_MOMENTUM_MAX_VELOCITY),
  };
}

function startSpacePanMomentum(viewport, velocityX, velocityY, canPanX, canPanY) {
  stopSpacePanMomentum();
  let vx = Number.isFinite(velocityX) ? velocityX : 0;
  let vy = Number.isFinite(velocityY) ? velocityY : 0;
  if (!canPanX) vx = 0;
  if (!canPanY) vy = 0;
  let previous = performance.now();
  const started = previous;
  const tick = (now) => {
    const dt = Math.min(32, Math.max(1, now - previous));
    previous = now;
    const previousLeft = viewport.scrollLeft;
    const previousTop = viewport.scrollTop;
    if (canPanX) viewport.scrollLeft -= vx * dt;
    if (canPanY) viewport.scrollTop -= vy * dt;
    updateSpaceNavigationHints();
    renderSpaceMiniMap();
    const atHorizontalEdge = !canPanX || viewport.scrollLeft <= 0 || viewport.scrollLeft + viewport.clientWidth >= viewport.scrollWidth - 1;
    const atVerticalEdge = !canPanY || viewport.scrollTop <= 0 || viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 1;
    const movedX = !canPanX || Math.abs(viewport.scrollLeft - previousLeft) > 0.2;
    const movedY = !canPanY || Math.abs(viewport.scrollTop - previousTop) > 0.2;
    const decay = Math.pow(SPACE_PAN_MOMENTUM_FRICTION, dt / SPACE_PAN_MOMENTUM_FRAME_MS);
    vx *= decay;
    vy *= decay;
    const speed = Math.hypot(canPanX && !atHorizontalEdge ? vx : 0, canPanY && !atVerticalEdge ? vy : 0);
    if (speed < SPACE_PAN_MOMENTUM_MIN_VELOCITY || now - started > SPACE_PAN_MOMENTUM_MAX_MS || (!movedX && !movedY)) {
      state.spacePanMomentumFrame = 0;
      state.spacePanMomentumActive = false;
      viewport.classList.remove("is-momentum");
      setSpaceMiniMapVisible(false);
      return;
    }
    state.spacePanMomentumFrame = requestAnimationFrame(tick);
  };
  if (Math.hypot(vx, vy) < SPACE_PAN_MOMENTUM_MIN_VELOCITY) {
    setSpaceMiniMapVisible(false);
    return;
  }
  state.spacePanMomentumActive = true;
  viewport.classList.add("is-momentum");
  setSpaceMiniMapVisible(true);
  state.spacePanMomentumFrame = requestAnimationFrame(tick);
}

function spaceMiniMapCanRender(metrics = spaceMapMetrics()) {
  if (!metrics) return false;
  return metrics.width > metrics.viewport.clientWidth + 1
    || metrics.height > metrics.viewport.clientHeight + 1;
}

function setSpaceMiniMapVisible(visible) {
  const map = els.spaceMiniMap;
  if (!map) return;
  window.clearTimeout(state.spaceMiniMapHideTimer);
  state.spaceMiniMapHideTimer = 0;
  const nextVisible = Boolean(visible && spaceMiniMapCanRender());
  els.spaceConfigButton?.classList.toggle("is-minimap-suppressed", nextVisible);
  if (nextVisible) {
    state.spaceMiniMapVisible = true;
    map.hidden = false;
    renderSpaceMiniMap();
    window.requestAnimationFrame(() => {
      if (state.spaceMiniMapVisible) map.classList.add("is-visible");
    });
    return;
  }
  state.spaceMiniMapVisible = false;
  map.classList.remove("is-visible");
  state.spaceMiniMapHideTimer = window.setTimeout(() => {
    if (!state.spaceMiniMapVisible) map.hidden = true;
  }, SPACE_MINIMAP_HIDE_MS);
}

function freezeWidgetPixelLayout() {
  const surface = spaceSurface();
  if (!surface) return;
  const surfaceRect = surface.getBoundingClientRect();
  document.querySelectorAll(".widget[data-widget-id]").forEach((widget) => {
    const id = widget.dataset.widgetId;
    if (!id || widget.hidden || widget.classList.contains("is-minimized") || widget.classList.contains("is-maximized")) return;
    const rect = widget.getBoundingClientRect();
    const layout = widgetLayout(id);
    const left = rect.left - surfaceRect.left;
    const top = rect.top - surfaceRect.top;
    layout.leftPx = Math.round(left);
    layout.topPx = Math.round(top);
    layout.widthPx = Math.round(rect.width);
    layout.heightPx = Math.round(rect.height);
    layout.leftPct = left / Math.max(1, surfaceRect.width);
    layout.topPct = top / Math.max(1, surfaceRect.height);
    layout.widthPct = rect.width / Math.max(1, surfaceRect.width);
    layout.heightPct = rect.height / Math.max(1, surfaceRect.height);
  });
}

function normalizedCanvasDensity(value) {
  const number = Number(value);
  return clamp(Math.round((Number.isFinite(number) ? number : 1) * 4) / 4, 1, CANVAS_DENSITY_MAX);
}

function commitCanvasDensityChange(origin = "control") {
  saveWidgetLayout();
  recordUserEvent("workspace.space_density_changed", {
    target: `space:${activeSpaceStorageId()}`,
    summary: `Space density ${canvasDensity()}x`,
    data: { space_id: activeSpaceStorageId(), density: canvasDensity(), origin },
  });
}

function setCanvasDensityValue(value, options = {}) {
  const layout = canvasLayout();
  const next = normalizedCanvasDensity(value);
  const previous = canvasDensity();
  if (next === previous && !options.force) return next;
  layout.density = next;
  applyCanvasDensity();
  applyWidgetLayout();
  updateDensityDial(options.control);
  if (options.persist !== false) {
    commitCanvasDensityChange(options.origin || "control");
  }
  if (options.render !== false) renderConfigModal();
  return next;
}

function setCanvasDensity(delta) {
  freezeWidgetPixelLayout();
  return setCanvasDensityValue(canvasDensity() + delta, { origin: "step" });
}

function resetWidgetPosition(widget) {
  const id = widget.dataset.widgetId;
  if (id) {
    const previous = state.widgetLayout[id] || {};
    state.widgetLayout[id] = {
      minimized: Boolean(previous.minimized),
      maximized: Boolean(previous.maximized),
      appLeftPx: previous.appLeftPx,
      appTopPx: previous.appTopPx,
      appLeftPct: previous.appLeftPct,
      appTopPct: previous.appTopPct,
      meta: previous.meta,
      nodePositions: previous.nodePositions,
    };
    saveWidgetLayout();
  }
  widget.style.left = "";
  widget.style.top = "";
  widget.style.right = "";
  widget.style.bottom = "";
  widget.style.zIndex = "";
  widget.style.width = "";
  widget.style.height = "";
  widget.style.aspectRatio = "";
}

function widgetById(widgetId) {
  return document.querySelector(`.widget[data-widget-id="${CSS.escape(widgetId)}"]`);
}

function widgetLayout(widgetId) {
  state.widgetLayout[widgetId] = state.widgetLayout[widgetId] || {};
  return state.widgetLayout[widgetId];
}

function appDefinitionById(widgetId) {
  return SPACE_APP_DEFINITIONS.find((app) => app.id === widgetId) || null;
}

function spaceAppScope(panel = state.activePanel) {
  const spaceId = activeSpaceStorageId(panel);
  if (spaceId === "home") return "home";
  if (spaceId === "admin") return "admin";
  return "user";
}

function mappedAppIdsForPanel(panel = state.activePanel) {
  return new Set(SPACE_APP_MAPPINGS[spaceAppScope(panel)] || []);
}

function widgetAvailableInPanel(widgetId, panel = state.activePanel) {
  if (Object.prototype.hasOwnProperty.call(FIXED_WIDGET_LAYOUT, widgetId)) return true;
  return mappedAppIdsForPanel(panel).has(widgetId);
}

function widgetMeta(widgetId) {
  const layout = widgetLayout(widgetId);
  layout.meta = layout.meta && typeof layout.meta === "object" ? layout.meta : {};
  return layout.meta;
}

function widgetDefaultLabel(widgetId) {
  const definition = appDefinitionById(widgetId);
  if (definition?.label) return definition.label;
  const widget = widgetById(widgetId);
  const title = widget?.querySelector(".widget-head > span:first-child")?.textContent?.trim();
  return title || widgetId;
}

function widgetDefaultShort(widgetId) {
  const definition = appDefinitionById(widgetId);
  if (definition?.short) return definition.short;
  return widgetDefaultLabel(widgetId).slice(0, 4);
}

function widgetTitle(widgetId) {
  return cleanText(widgetMeta(widgetId).title, widgetDefaultLabel(widgetId));
}

function widgetShort(widgetId) {
  return cleanText(widgetMeta(widgetId).iconText, widgetDefaultShort(widgetId)).slice(0, 8);
}

function widgetImage(widgetId) {
  const image = String(widgetMeta(widgetId).image || "").trim();
  return image.startsWith("data:image/") ? image : "";
}

function normalizeDimension(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.round(clamp(number, min, max));
}

function widgetDimensionBounds(widgetId, surfaceRect = null) {
  const meta = widgetMeta(widgetId);
  const maxSurfaceWidth = Math.max(240, Math.round((surfaceRect?.width || 1800) - 16));
  const maxSurfaceHeight = Math.max(180, Math.round((surfaceRect?.height || 1200) - 16));
  const minWidth = normalizeDimension(meta.minWidth, 320, 180, maxSurfaceWidth);
  const minHeight = normalizeDimension(meta.minHeight, 220, 120, maxSurfaceHeight);
  const maxWidth = Math.max(minWidth, normalizeDimension(meta.maxWidth, maxSurfaceWidth, minWidth, Math.max(minWidth, 4000)));
  const maxHeight = Math.max(minHeight, normalizeDimension(meta.maxHeight, maxSurfaceHeight, minHeight, Math.max(minHeight, 3000)));
  return {
    minWidth,
    minHeight,
    maxWidth: Math.min(maxWidth, maxSurfaceWidth),
    maxHeight: Math.min(maxHeight, maxSurfaceHeight),
  };
}

function applyWidgetChrome(widget) {
  const id = widget?.dataset?.widgetId || "";
  if (!id) return;
  const title = widget.querySelector(".widget-head > span:first-child");
  if (title) title.textContent = widgetTitle(id);
  widget.querySelectorAll("[data-widget-control='minimize']").forEach((button) => {
    button.setAttribute("aria-label", `Minimize ${widgetTitle(id)}`);
  });
  widget.querySelectorAll("[data-widget-control='maximize']").forEach((button) => {
    button.setAttribute("aria-label", `${widget.classList.contains("is-maximized") ? "Restore" : "Maximize"} ${widgetTitle(id)}`);
  });
}

function applyWidgetChromeAll() {
  document.querySelectorAll(".widget[data-widget-id]").forEach((widget) => applyWidgetChrome(widget));
}

function setWidgetMinimized(widgetId, minimized) {
  if (!widgetAvailableInPanel(widgetId)) return;
  const widget = widgetById(widgetId);
  if (!widget) return;
  const layout = widgetLayout(widgetId);
  layout.minimized = Boolean(minimized);
  if (minimized) layout.maximized = false;
  saveWidgetLayout();
  applyWidgetState(widget);
  if (!minimized) {
    applyWidgetLayout();
    ensureOpenedWidgetContained(widget, widgetId);
  }
  renderAppLayer();
  syncResourcePolling();
  recordUserEvent(minimized ? "workspace.widget_minimized" : "workspace.widget_opened", {
    target: `widget:${widgetId}`,
    summary: `${minimized ? "Minimized" : "Opened"} ${widgetId}`,
    data: { widget_id: widgetId },
  });
  if (!minimized) bringWidgetForward(widget);
}

function toggleWidgetMaximized(widgetId) {
  const widget = widgetById(widgetId);
  if (!widget) return;
  const layout = widgetLayout(widgetId);
  layout.maximized = !layout.maximized;
  if (layout.maximized) layout.minimized = false;
  saveWidgetLayout();
  applyWidgetLayout();
  renderAppLayer();
  bringWidgetForward(widget);
  if (widgetId === "browser-proof") scheduleBrowserResizeSync();
  recordUserEvent("workspace.widget_maximize_toggled", {
    target: `widget:${widgetId}`,
    summary: `${layout.maximized ? "Maximized" : "Restored"} ${widgetId}`,
    data: { widget_id: widgetId, maximized: layout.maximized },
  });
}

function clearWidgetGeometryStyle(widget) {
  widget.style.left = "";
  widget.style.top = "";
  widget.style.right = "";
  widget.style.bottom = "";
  widget.style.width = "";
  widget.style.height = "";
  widget.style.aspectRatio = "";
}

function applyMaximizedWidgetLayout(widget) {
  if (!widget) return false;
  widget.style.left = "";
  widget.style.top = "";
  widget.style.right = "auto";
  widget.style.bottom = "auto";
  widget.style.width = "";
  widget.style.height = "";
  widget.style.aspectRatio = "auto";
  widget.style.zIndex = "";
  return true;
}

function applyMaximizedWidgetLayouts() {
  document.querySelectorAll(".widget.is-maximized[data-widget-id]").forEach((widget) => {
    applyMaximizedWidgetLayout(widget);
  });
  syncMaximizedShellState();
}

function syncMaximizedShellState() {
  const hasMaximizedWidget = Boolean(document.querySelector(".widget.is-maximized[data-widget-id]:not([hidden])"));
  els.app?.classList.toggle("has-maximized-widget", hasMaximizedWidget);
}

function applyWidgetState(widget) {
  const id = widget.dataset.widgetId;
  const layout = id ? state.widgetLayout[id] || {} : {};
  widget.classList.toggle("is-minimized", Boolean(layout.minimized));
  widget.classList.toggle("is-maximized", Boolean(layout.maximized));
  widget.hidden = Boolean(layout.minimized);
  widget.querySelectorAll("[data-widget-control='maximize']").forEach((button) => {
    button.classList.toggle("active", Boolean(layout.maximized));
    button.title = layout.maximized ? "Restore" : "Maximize";
    button.setAttribute("aria-label", layout.maximized ? `Restore ${id}` : `Maximize ${id}`);
  });
}

function spaceApps(panel = state.activePanel) {
  if (!isAdminUser() && isAdminPanel(panel)) return [];
  if (!isAdminUser() && isUserSpacePanel(panel)) return [];
  const mappedIds = mappedAppIdsForPanel(panel);
  const spaceId = activeSpaceStorageId(panel);
  return SPACE_APP_DEFINITIONS.filter((app) => {
    if (!mappedIds.has(app.id)) return false;
    if (app.home && spaceId !== "home") return false;
    return !app.module || isModuleEnabled(app.module);
  });
}

function snapToAppGrid(value) {
  return Math.round(Number(value || 0) / APP_ICON_GRID_PX) * APP_ICON_GRID_PX;
}

function appRect(left, top, width, height) {
  return { left, top, right: left + width, bottom: top + height };
}

function appRectsOverlap(a, b) {
  const gap = 0;
  const tolerance = APP_ICON_COLLISION_TOLERANCE_PX;
  return a.left < b.right + gap - tolerance
    && a.right + gap > b.left + tolerance
    && a.top < b.bottom + gap - tolerance
    && a.bottom + gap > b.top + tolerance;
}

function appPositionFits(left, top, width, height, occupied) {
  const rect = appRect(left, top, width, height);
  return !occupied.some((item) => appRectsOverlap(rect, item));
}

function nearestOpenAppPosition(desiredLeft, desiredTop, width, height, maxLeft, maxTop, occupied) {
  const startLeft = clamp(Math.round(Number(desiredLeft || 0)), SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
  const startTop = clamp(Math.round(Number(desiredTop || 0)), SPACE_CANVAS_EDGE_INSET_PX, maxTop);
  if (appPositionFits(startLeft, startTop, width, height, occupied)) return { left: startLeft, top: startTop };
  const maxRadius = Math.max(maxLeft, maxTop) + width + height;
  for (let radius = APP_ICON_GRID_PX; radius <= maxRadius; radius += APP_ICON_GRID_PX) {
    for (let dx = -radius; dx <= radius; dx += APP_ICON_GRID_PX) {
      for (const dy of [-radius, radius]) {
        const left = clamp(snapToAppGrid(startLeft + dx), SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
        const top = clamp(snapToAppGrid(startTop + dy), SPACE_CANVAS_EDGE_INSET_PX, maxTop);
        if (appPositionFits(left, top, width, height, occupied)) return { left, top };
      }
    }
    for (let dy = -radius + APP_ICON_GRID_PX; dy <= radius - APP_ICON_GRID_PX; dy += APP_ICON_GRID_PX) {
      for (const dx of [-radius, radius]) {
        const left = clamp(snapToAppGrid(startLeft + dx), SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
        const top = clamp(snapToAppGrid(startTop + dy), SPACE_CANVAS_EDGE_INSET_PX, maxTop);
        if (appPositionFits(left, top, width, height, occupied)) return { left, top };
      }
    }
  }
  return { left: startLeft, top: startTop };
}

function createSpaceAppButton(app) {
  const button = document.createElement("button");
  button.className = "space-app-button";
  button.type = "button";
  button.dataset.widgetApp = app.id;
  button.title = widgetTitle(app.id);
  button.setAttribute("aria-label", widgetTitle(app.id));

  const icon = document.createElement("span");
  icon.className = "space-app-icon";
  icon.textContent = widgetShort(app.id).slice(0, 2);
  const label = document.createElement("span");
  label.textContent = widgetShort(app.id);
  button.append(icon, label);
  button.addEventListener("click", (event) => {
    if (button.dataset.dragMoved === "true") {
      button.dataset.dragMoved = "";
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const layout = widgetLayout(app.id);
    setWidgetMinimized(app.id, !layout.minimized);
  });
  button.addEventListener("contextmenu", (event) => showAppContextMenu(app.id, "app", event));
  installLongPressMenu(button, (event) => showAppContextMenu(app.id, "app", event));
  installAppButtonDragging(button, app.id);
  return button;
}

function positionSpaceAppButton(button, app, index, occupied = []) {
  const layout = widgetLayout(app.id);
  button.title = widgetTitle(app.id);
  button.setAttribute("aria-label", widgetTitle(app.id));
  button.classList.toggle("open", !layout.minimized);
  const icon = button.querySelector(".space-app-icon");
  const image = widgetImage(app.id);
  if (icon) {
    icon.textContent = image ? "" : widgetShort(app.id).slice(0, 2);
    icon.style.backgroundImage = image ? `url("${image}")` : "";
    icon.classList.toggle("has-image", Boolean(image));
  }
  const label = button.querySelector(".space-app-icon + span");
  if (label) label.textContent = widgetShort(app.id);
  const viewportRect = spaceSurface()?.getBoundingClientRect?.() || { width: 1, height: 1 };
  const defaultLeftPct = 0.04 + (index % 3) * 0.088;
  const defaultTopPct = 0.12 + Math.floor(index / 3) * 0.14;
  const buttonWidth = button.offsetWidth || 62;
  const buttonHeight = button.offsetHeight || 70;
  const maxLeftStable = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.width - buttonWidth - SPACE_CANVAS_EDGE_INSET_PX);
  const maxTopStable = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.height - buttonHeight - SPACE_CANVAS_EDGE_INSET_PX);
  const hasSavedPixelPosition = Number.isFinite(layout.appLeftPx) && Number.isFinite(layout.appTopPx);
  const desiredLeft = Number.isFinite(layout.appLeftPx)
    ? layout.appLeftPx
    : (Number.isFinite(layout.appLeftPct) ? layout.appLeftPct : defaultLeftPct) * viewportRect.width;
  const desiredTop = Number.isFinite(layout.appTopPx)
    ? layout.appTopPx
    : (Number.isFinite(layout.appTopPct) ? layout.appTopPct : defaultTopPct) * viewportRect.height;
  if (layout.appOrganized === true || hasSavedPixelPosition) {
    const left = clamp(Math.round(Number(desiredLeft || 0)), 0, Math.max(0, viewportRect.width - buttonWidth));
    const top = clamp(Math.round(Number(desiredTop || 0)), 0, Math.max(0, viewportRect.height - buttonHeight));
    layout.appLeftPx = left;
    layout.appTopPx = top;
    layout.appLeftPct = left / Math.max(1, viewportRect.width);
    layout.appTopPct = top / Math.max(1, viewportRect.height);
    button.style.left = `${left}px`;
    button.style.top = `${top}px`;
    occupied.push(appRect(left, top, buttonWidth, buttonHeight));
    return;
  }
  const { left, top } = nearestOpenAppPosition(desiredLeft, desiredTop, buttonWidth, buttonHeight, maxLeftStable, maxTopStable, occupied);
  layout.appLeftPx = left;
  layout.appTopPx = top;
  layout.appLeftPct = left / Math.max(1, viewportRect.width);
  layout.appTopPct = top / Math.max(1, viewportRect.height);
  button.style.left = `${left}px`;
  button.style.top = `${top}px`;
  occupied.push(appRect(left, top, buttonWidth, buttonHeight));
}

function renderAppLayer() {
  if (!els.appLayer) return;
  const apps = spaceApps();
  const occupied = [];
  const nodes = apps.map((app, index) => {
    let button = state.appButtonCache.get(app.id);
    if (!button) {
      button = createSpaceAppButton(app);
      state.appButtonCache.set(app.id, button);
    }
    positionSpaceAppButton(button, app, index, occupied);
    return button;
  });
  els.appLayer.replaceChildren(...nodes);
}

function organizerTopInsetPx(board) {
  const boardRect = board?.getBoundingClientRect?.();
  const title = els.spaceOrganizeButton?.closest?.(".space-title") || els.spaceLabel?.closest?.(".space-title");
  const titleRect = title?.getBoundingClientRect?.();
  if (!boardRect || !titleRect) return APP_ORGANIZER_TOP_INSET_PX;
  const titleBottom = Math.ceil(titleRect.bottom - boardRect.top + 4);
  const homeCoreModuleList = activeSpaceStorageId() === "home" ? board.querySelector(".home-actions") : null;
  const homeCoreModuleRect = homeCoreModuleList?.getBoundingClientRect?.();
  const homeCoreModuleBottom = homeCoreModuleRect && homeCoreModuleRect.width && homeCoreModuleRect.height
    ? Math.ceil(homeCoreModuleRect.bottom - boardRect.top + 4)
    : 0;
  return Math.max(APP_ORGANIZER_TOP_INSET_PX, titleBottom, homeCoreModuleBottom);
}

function organizeSpaceAppsInViewport() {
  const viewport = els.spaceViewport;
  const board = spaceSurface();
  if (!viewport || !board || !els.appLayer) return;
  const apps = spaceApps();
  if (!apps.length) return;
  const buttonWidth = 62;
  const buttonHeight = 70;
  const gapX = 0;
  const gapY = 0;
  const leftInset = 0;
  const topInset = organizerTopInsetPx(board);
  const boardWidth = Math.max(buttonWidth, board.offsetWidth || viewport.clientWidth);
  const boardHeight = Math.max(buttonHeight, board.offsetHeight || viewport.clientHeight);
  const visibleColumns = Math.max(1, Math.floor((Math.max(buttonWidth, viewport.clientWidth - leftInset) + gapX) / (buttonWidth + gapX)));
  const boardColumns = Math.max(1, Math.floor((boardWidth + gapX) / (buttonWidth + gapX)));
  const columns = Math.min(apps.length, visibleColumns, boardColumns);
  const rows = Math.ceil(apps.length / columns);
  const blockWidth = columns * buttonWidth + Math.max(0, columns - 1) * gapX;
  const blockHeight = rows * buttonHeight + Math.max(0, rows - 1) * gapY;
  const rawStartLeft = snapToAppGrid(viewport.scrollLeft + leftInset);
  const startLeft = clamp(rawStartLeft, 0, Math.max(0, boardWidth - blockWidth));
  const rawStartTop = snapToAppGrid(viewport.scrollTop + topInset);
  const startTop = clamp(rawStartTop, 0, Math.max(0, boardHeight - blockHeight));
  apps.forEach((app, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const layout = widgetLayout(app.id);
    const left = Math.round(startLeft + column * (buttonWidth + gapX));
    const top = Math.round(startTop + row * (buttonHeight + gapY));
    layout.appLeftPx = left;
    layout.appTopPx = top;
    layout.appOrganized = true;
    layout.appLeftPct = left / Math.max(1, board.offsetWidth || viewport.scrollWidth || viewport.clientWidth);
    layout.appTopPct = top / Math.max(1, board.offsetHeight || viewport.scrollHeight || viewport.clientHeight);
  });
  const overflowRows = Math.max(0, rows - Math.max(1, Math.floor((viewport.clientHeight - topInset + gapY) / (buttonHeight + gapY))));
  renderAppLayer();
  renderSpaceMiniMap();
  saveWidgetLayout();
  recordUserEvent("workspace.apps_organized", {
    target: `space:${activeSpaceStorageId()}`,
    summary: `Organized ${activeSpaceStorageId()} apps`,
    data: {
      space_id: activeSpaceStorageId(),
      app_count: apps.length,
      columns,
      overflow_rows: overflowRows,
      scroll_left: viewport.scrollLeft,
      scroll_top: viewport.scrollTop,
    },
  });
}

function installAppButtonDragging(button, appId) {
  const viewport = spaceSurface();
  if (!viewport) return;
  button.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event)) return;
    const startRect = button.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const startLeft = startRect.left - viewportRect.left;
    const startTop = startRect.top - viewportRect.top;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    button.classList.add("is-dragging");
    document.body.classList.add("is-app-dragging");
    try {
      button.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture can be unavailable during rapid touch/context transitions.
    }
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 4) moved = true;
      const maxLeft = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.width - button.offsetWidth - SPACE_CANVAS_EDGE_INSET_PX);
      const maxTop = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.height - button.offsetHeight - SPACE_CANVAS_EDGE_INSET_PX);
      const left = clamp(startLeft + moveEvent.clientX - startX, SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
      const top = clamp(startTop + moveEvent.clientY - startY, SPACE_CANVAS_EDGE_INSET_PX, maxTop);
      button.style.left = `${left}px`;
      button.style.top = `${top}px`;
    };
    const end = (endEvent) => {
      button.classList.remove("is-dragging");
      document.body.classList.remove("is-app-dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      try {
        button.releasePointerCapture(event.pointerId);
      } catch {
        // Capture may already be released by the browser.
      }
      if (!moved) {
        button.style.left = `${startLeft}px`;
        button.style.top = `${startTop}px`;
        return;
      }
      const layout = widgetLayout(appId);
      const maxLeft = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.width - button.offsetWidth - SPACE_CANVAS_EDGE_INSET_PX);
      const maxTop = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.height - button.offsetHeight - SPACE_CANVAS_EDGE_INSET_PX);
      const occupied = Array.from(els.appLayer.querySelectorAll(".space-app-button"))
        .filter((item) => item !== button)
        .map((item) => {
          const rect = item.getBoundingClientRect();
          return appRect(rect.left - viewportRect.left, rect.top - viewportRect.top, rect.width, rect.height);
        });
      const { left, top } = nearestOpenAppPosition(
        parseFloat(button.style.left || "0"),
        parseFloat(button.style.top || "0"),
        button.offsetWidth,
        button.offsetHeight,
        maxLeft,
        maxTop,
        occupied
      );
      button.style.left = `${left}px`;
      button.style.top = `${top}px`;
      layout.appLeftPx = left;
      layout.appTopPx = top;
      layout.appOrganized = false;
      layout.appLeftPct = left / Math.max(1, viewportRect.width);
      layout.appTopPct = top / Math.max(1, viewportRect.height);
      saveWidgetLayout();
      button.dataset.dragMoved = "true";
      window.setTimeout(() => {
        button.dataset.dragMoved = "";
      }, 0);
      endEvent.preventDefault();
      endEvent.stopPropagation();
      recordUserEvent("workspace.app_moved", {
        target: `app:${appId}`,
        summary: `Moved app ${appId}`,
        data: { app_id: appId, left_pct: layout.appLeftPct, top_pct: layout.appTopPct },
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  });
}

function installLongPressMenu(target, openMenu) {
  if (!target) return;
  let timer = 0;
  let startX = 0;
  let startY = 0;
  const clear = () => {
    window.clearTimeout(timer);
    timer = 0;
  };
  target.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || event.button !== 0) return;
    startX = event.clientX;
    startY = event.clientY;
    clear();
    timer = window.setTimeout(() => {
      timer = 0;
      openMenu(event);
    }, 560);
  });
  target.addEventListener("pointermove", (event) => {
    if (!timer) return;
    if (Math.hypot(event.clientX - startX, event.clientY - startY) > 8) clear();
  });
  target.addEventListener("pointerup", clear);
  target.addEventListener("pointercancel", clear);
  target.addEventListener("lostpointercapture", clear);
}

function applyWidgetLayout() {
  const viewport = spaceSurface();
  if (!viewport) return;
  applyWidgetChromeAll();
  const viewportRect = viewport.getBoundingClientRect();
  let maxZ = state.widgetZ;
  let containedAny = false;
  document.querySelectorAll(".widget[data-widget-id]").forEach((widget) => {
    const id = widget.dataset.widgetId;
    if (!widgetAvailableInPanel(id)) {
      widget.hidden = true;
      widget.classList.add("is-minimized");
      widget.classList.remove("is-maximized");
      return;
    }
    const layout = widgetLayout(id);
    applyWidgetState(widget);
    applyWidgetChrome(widget);
    if (layout?.maximized) {
      applyMaximizedWidgetLayout(widget);
      maxZ = Math.max(maxZ, Number(layout?.z || widget.style.zIndex || 4));
      return;
    }
    if (layout?.minimized) {
      maxZ = Math.max(maxZ, Number(layout?.z || widget.style.zIndex || 4));
      return;
    }
    clearWidgetGeometryStyle(widget);
    const bounds = widgetDimensionBounds(id, viewportRect);
    const widthPx = Number(layout?.widthPx);
    const heightPx = Number(layout?.heightPx);
    const widthPct = Number(layout?.widthPct);
    const heightPct = Number(layout?.heightPct);
    if (Number.isFinite(widthPx) || Number.isFinite(widthPct)) {
      const width = clamp(
        Number.isFinite(widthPx) ? widthPx : widthPct * viewportRect.width,
        bounds.minWidth,
        bounds.maxWidth
      );
      widget.style.width = `${width}px`;
      layout.widthPx = Math.round(width);
      widget.style.aspectRatio = "auto";
    }
    if (Number.isFinite(heightPx) || Number.isFinite(heightPct)) {
      const height = clamp(
        Number.isFinite(heightPx) ? heightPx : heightPct * viewportRect.height,
        bounds.minHeight,
        bounds.maxHeight
      );
      widget.style.height = `${height}px`;
      layout.heightPx = Math.round(height);
      widget.style.aspectRatio = "auto";
    }
    fitWidgetToVisibleViewport(widget, id, { updateLayout: false });
    const leftPx = Number(layout?.leftPx);
    const topPx = Number(layout?.topPx);
    const leftPct = Number(layout?.leftPct);
    const topPct = Number(layout?.topPct);
    if ((Number.isFinite(leftPx) || Number.isFinite(leftPct)) && (Number.isFinite(topPx) || Number.isFinite(topPct))) {
      const maxLeft = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.width - widget.offsetWidth - SPACE_CANVAS_EDGE_INSET_PX);
      const maxTop = Math.max(SPACE_CANVAS_EDGE_INSET_PX, viewportRect.height - widget.offsetHeight - SPACE_CANVAS_EDGE_INSET_PX);
      const left = clamp(Number.isFinite(leftPx) ? leftPx : leftPct * viewportRect.width, SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
      const top = clamp(Number.isFinite(topPx) ? topPx : topPct * viewportRect.height, SPACE_CANVAS_EDGE_INSET_PX, maxTop);
      widget.style.left = `${left}px`;
      widget.style.top = `${top}px`;
      widget.style.right = "auto";
      widget.style.bottom = "auto";
      layout.leftPx = Math.round(left);
      layout.topPx = Math.round(top);
      layout.leftPct = left / Math.max(1, viewportRect.width);
      layout.topPct = top / Math.max(1, viewportRect.height);
    }
    const contained = containWidgetInCanvasBounds(widget, id);
    containedAny = containedAny || contained.changed;
    const restoredZ = clamp(Number(layout?.z || widget.style.zIndex || 4), 4, WIDGET_Z_LIMIT);
    if (layout?.z || widget.style.zIndex) widget.style.zIndex = String(restoredZ);
    maxZ = Math.max(maxZ, restoredZ);
  });
  state.widgetZ = maxZ;
  if (containedAny) saveWidgetLayout();
  syncMaximizedShellState();
  renderAppLayer();
  syncResourcePolling();
}

function fitWidgetToVisibleViewport(widget, widgetId, options = {}) {
  const visibleRect = spaceViewportUsableRect();
  if (!widget || !visibleRect?.width || !visibleRect?.height) return { changed: false };
  const bounds = widgetDimensionBounds(widgetId, visibleRect);
  const rect = widget.getBoundingClientRect();
  const width = Math.round(rect.width);
  const height = Math.round(rect.height);
  const nextWidth = Math.round(clamp(width, 1, bounds.maxWidth));
  const nextHeight = Math.round(clamp(height, 1, bounds.maxHeight));
  const updateLayout = options.updateLayout !== false;
  const layout = updateLayout ? widgetLayout(widgetId) : null;
  let changed = false;
  if (width > nextWidth) {
    widget.style.width = `${nextWidth}px`;
    widget.style.right = "auto";
    widget.style.aspectRatio = "auto";
    if (layout) {
      layout.widthPx = nextWidth;
      layout.widthPct = nextWidth / Math.max(1, visibleRect.width);
    }
    changed = true;
  }
  if (height > nextHeight) {
    widget.style.height = `${nextHeight}px`;
    widget.style.bottom = "auto";
    widget.style.aspectRatio = "auto";
    if (layout) {
      layout.heightPx = nextHeight;
      layout.heightPct = nextHeight / Math.max(1, visibleRect.height);
    }
    changed = true;
  }
  return { changed, height: nextHeight, width: nextWidth };
}

function containWidgetInCanvasBounds(widget, widgetId, options = {}) {
  const board = spaceSurface();
  const boardRect = board?.getBoundingClientRect?.();
  if (!widget || !boardRect?.width || !boardRect?.height) return { changed: false };
  const rect = widget.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return { changed: false };
  const updateLayout = options.updateLayout !== false;
  const layout = updateLayout ? widgetLayout(widgetId) : null;
  const left = rect.left - boardRect.left;
  const top = rect.top - boardRect.top;
  const maxLeft = Math.max(SPACE_CANVAS_EDGE_INSET_PX, boardRect.width - rect.width - SPACE_CANVAS_EDGE_INSET_PX);
  const maxTop = Math.max(SPACE_CANVAS_EDGE_INSET_PX, boardRect.height - rect.height - SPACE_CANVAS_EDGE_INSET_PX);
  const nextLeft = clamp(left, SPACE_CANVAS_EDGE_INSET_PX, maxLeft);
  const nextTop = clamp(top, SPACE_CANVAS_EDGE_INSET_PX, maxTop);
  const changed = Math.abs(nextLeft - left) > 0.5 || Math.abs(nextTop - top) > 0.5;
  if (!changed) return { changed: false, left: Math.round(left), top: Math.round(top) };
  widget.style.left = `${Math.round(nextLeft)}px`;
  widget.style.top = `${Math.round(nextTop)}px`;
  widget.style.right = "auto";
  widget.style.bottom = "auto";
  if (layout) {
    layout.leftPx = Math.round(nextLeft);
    layout.topPx = Math.round(nextTop);
    layout.leftPct = nextLeft / Math.max(1, boardRect.width);
    layout.topPct = nextTop / Math.max(1, boardRect.height);
  }
  return { changed: true, left: Math.round(nextLeft), top: Math.round(nextTop) };
}

function ensureOpenedWidgetContained(widget, widgetId) {
  if (!widget || widget.hidden || widget.classList.contains("is-minimized") || widget.classList.contains("is-maximized")) return;
  const visibleRect = spaceViewportUsableRect();
  if (!visibleRect) return;
  const fit = fitWidgetToVisibleViewport(widget, widgetId);
  const rect = widget.getBoundingClientRect();
  const fullyVisible = rect.left >= visibleRect.left
    && rect.top >= visibleRect.top
    && rect.right <= visibleRect.right
    && rect.bottom <= visibleRect.bottom;
  if (fullyVisible) {
    if (fit.changed) {
      saveWidgetLayout();
      recordUserEvent("workspace.widget_visible_bounds_applied", {
        target: `widget:${widgetId}`,
        summary: `Fit ${widgetId} to the visible canvas`,
        data: { widget_id: widgetId, width_px: fit.width, height_px: fit.height },
      });
    }
    return;
  }
  const layout = widgetLayout(widgetId);
  layout.leftPx = SPACE_CANVAS_EDGE_INSET_PX;
  layout.topPx = SPACE_CANVAS_EDGE_INSET_PX;
  layout.leftPct = 0;
  layout.topPct = 0;
  widget.style.left = `${SPACE_CANVAS_EDGE_INSET_PX}px`;
  widget.style.top = `${SPACE_CANVAS_EDGE_INSET_PX}px`;
  widget.style.right = "auto";
  widget.style.bottom = "auto";
  els.spaceViewport.scrollLeft = 0;
  els.spaceViewport.scrollTop = 0;
  saveWidgetLayout();
  recordUserEvent("workspace.widget_initial_point_applied", {
    target: `widget:${widgetId}`,
    summary: `Moved ${widgetId} to the canvas initial point`,
    data: { widget_id: widgetId, left_px: SPACE_CANVAS_EDGE_INSET_PX, top_px: SPACE_CANVAS_EDGE_INSET_PX, width_px: fit.changed ? fit.width : Math.round(rect.width), height_px: fit.changed ? fit.height : Math.round(rect.height) },
  });
}

function normalizeWidgetStack() {
  const widgets = Array.from(document.querySelectorAll(".widget[data-widget-id]"))
    .sort((a, b) => Number(a.style.zIndex || 4) - Number(b.style.zIndex || 4));
  widgets.forEach((widget, index) => {
    const z = WIDGET_Z_BASE + index;
    widget.style.zIndex = String(z);
    const id = widget.dataset.widgetId;
    if (id && state.widgetLayout[id]) state.widgetLayout[id].z = z;
  });
  state.widgetZ = WIDGET_Z_BASE + widgets.length;
  saveWidgetLayout();
}

function bringWidgetForward(widget) {
  if (state.widgetZ >= WIDGET_Z_LIMIT) normalizeWidgetStack();
  state.widgetZ += 1;
  widget.style.zIndex = String(state.widgetZ);
  const id = widget.dataset.widgetId;
  if (id) {
    const previous = state.activeWidgetId;
    state.widgetLayout[id] = state.widgetLayout[id] || {};
    state.widgetLayout[id].z = state.widgetZ;
    saveWidgetLayout();
    state.activeWidgetId = id;
    if (previous !== id) {
      recordUserEvent("workspace.widget_focused", {
        target: `widget:${id}`,
        summary: `Focused ${id}`,
        data: { widget_id: id, z: state.widgetZ },
      });
    }
  }
}

function installWidgetDragging() {
  const viewport = spaceSurface();
  if (!viewport) return;

  document.querySelectorAll(".widget[data-widget-id]").forEach((widget) => {
    const handle = widget.querySelector(".widget-head");
    if (!handle) return;

    widget.addEventListener("pointerdown", () => bringWidgetForward(widget));
    widget.addEventListener("focusin", () => bringWidgetForward(widget));

    handle.addEventListener("dblclick", (event) => {
      event.preventDefault();
      resetWidgetPosition(widget);
      recordUserEvent("workspace.widget_reset", {
        target: `widget:${widget.dataset.widgetId}`,
        summary: `Reset ${widget.dataset.widgetId} layout`,
        data: { widget_id: widget.dataset.widgetId },
      });
    });
    handle.addEventListener("contextmenu", (event) => showAppContextMenu(widget.dataset.widgetId, "widget", event));
    installLongPressMenu(handle, (event) => showAppContextMenu(widget.dataset.widgetId, "widget", event));

    handle.addEventListener("pointerdown", (event) => {
      if (!isPrimaryPointer(event)) return;
      if (event.target.closest("button,input,textarea,select,a")) return;
      if (widget.classList.contains("is-maximized")) return;
      event.preventDefault();

      const viewportRect = viewport.getBoundingClientRect();
      const widgetRect = widget.getBoundingClientRect();
      const startLeft = widgetRect.left - viewportRect.left;
      const startTop = widgetRect.top - viewportRect.top;
      const startX = event.clientX;
      const startY = event.clientY;

      widget.style.left = `${startLeft}px`;
      widget.style.top = `${startTop}px`;
      widget.style.right = "auto";
      widget.style.bottom = "auto";
      widget.style.transform = "none";
      widget.classList.add("is-dragging");
      document.body.classList.add("is-widget-dragging");
      bringWidgetForward(widget);
      try {
        handle.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture can be unavailable during rapid touch/context transitions.
      }
      const startedAt = performance.now();
      recordUserEvent("workspace.widget_drag_started", {
        target: `widget:${widget.dataset.widgetId}`,
        summary: `Started dragging ${widget.dataset.widgetId}`,
        data: { widget_id: widget.dataset.widgetId, x: Math.round(startLeft), y: Math.round(startTop) },
      });

      const move = (moveEvent) => {
        const bounds = widgetCanvasMovementBounds(widget);
        if (!bounds) return;
        const left = clamp(startLeft + moveEvent.clientX - startX, bounds.minLeft, bounds.maxLeft);
        const top = clamp(startTop + moveEvent.clientY - startY, bounds.minTop, bounds.maxTop);
        widget.style.left = `${left}px`;
        widget.style.top = `${top}px`;
      };

      const end = () => {
        widget.classList.remove("is-dragging");
        document.body.classList.remove("is-widget-dragging");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
        try {
          handle.releasePointerCapture(event.pointerId);
        } catch {
          // Capture may already be released by the browser.
        }
        const finalLeft = parseFloat(widget.style.left || "0");
        const finalTop = parseFloat(widget.style.top || "0");
        const bounds = widgetCanvasMovementBounds(widget) || { width: viewportRect.width, height: viewportRect.height };
        state.widgetLayout[widget.dataset.widgetId] = {
          ...(state.widgetLayout[widget.dataset.widgetId] || {}),
          leftPx: Math.round(finalLeft),
          topPx: Math.round(finalTop),
          leftPct: finalLeft / Math.max(1, bounds.width),
          topPct: finalTop / Math.max(1, bounds.height),
          z: Number(widget.style.zIndex || 4),
        };
        saveWidgetLayout();
        recordUserEvent("workspace.widget_drag_finished", {
          target: `widget:${widget.dataset.widgetId}`,
          summary: `Finished dragging ${widget.dataset.widgetId}`,
          data: {
            widget_id: widget.dataset.widgetId,
            left_pct: state.widgetLayout[widget.dataset.widgetId].leftPct,
            top_pct: state.widgetLayout[widget.dataset.widgetId].topPct,
          },
          duration_ms: performance.now() - startedAt,
        });
      };

      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end, { once: true });
      window.addEventListener("pointercancel", end, { once: true });
    });
  });

  window.addEventListener("resize", applyWidgetLayout);
  applyWidgetLayout();
}

function installWidgetWindowControls() {
  document.querySelectorAll("[data-widget-control='minimize']").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const widget = button.closest(".widget[data-widget-id]");
      if (widget?.dataset.widgetId) setWidgetMinimized(widget.dataset.widgetId, true);
    });
  });
  document.querySelectorAll("[data-widget-control='maximize']").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const widget = button.closest(".widget[data-widget-id]");
      if (widget?.dataset.widgetId) toggleWidgetMaximized(widget.dataset.widgetId);
    });
  });
}

function installWidgetResizing() {
  const viewport = spaceSurface();
  if (!viewport) return;
  document.querySelectorAll(".widget-resize-handle").forEach((handle) => {
    const widget = handle.closest(".widget[data-widget-id]");
    if (!widget) return;
    handle.addEventListener("pointerdown", (event) => {
      if (!isPrimaryPointer(event)) return;
      if (widget.classList.contains("is-maximized")) return;
      event.preventDefault();
      event.stopPropagation();

      const viewportRect = viewport.getBoundingClientRect();
      const boardRect = viewportRect;
      const widgetRect = widget.getBoundingClientRect();
      const startLeft = widgetRect.left - boardRect.left;
      const startTop = widgetRect.top - boardRect.top;
      const startWidth = widgetRect.width;
      const startHeight = widgetRect.height;
      const startX = event.clientX;
      const startY = event.clientY;
      const bounds = widgetDimensionBounds(widget.dataset.widgetId, viewportRect);
      const minWidth = bounds.minWidth;
      const minHeight = bounds.minHeight;
      let finished = false;

      widget.style.left = `${startLeft}px`;
      widget.style.top = `${startTop}px`;
      widget.style.right = "auto";
      widget.style.bottom = "auto";
      widget.style.width = `${startWidth}px`;
      widget.style.height = `${startHeight}px`;
      widget.style.aspectRatio = "auto";
      widget.classList.add("is-resizing");
      document.body.classList.add("is-widget-resizing");
      bringWidgetForward(widget);
      try {
        handle.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture can be unavailable during rapid touch/context transitions.
      }
      const startedAt = performance.now();
      recordUserEvent("workspace.widget_resize_started", {
        target: `widget:${widget.dataset.widgetId}`,
        summary: `Started resizing ${widget.dataset.widgetId}`,
        data: { widget_id: widget.dataset.widgetId, width: Math.round(startWidth), height: Math.round(startHeight) },
      });

      const move = (moveEvent) => {
        moveEvent.preventDefault();
        const movementBounds = widgetCanvasMovementBounds(widget);
        const maxWidth = Math.min(bounds.maxWidth, Math.max(minWidth, (movementBounds?.maxLeft || viewportRect.width) - startLeft + widget.offsetWidth));
        const maxHeight = Math.min(bounds.maxHeight, Math.max(minHeight, (movementBounds?.maxTop || viewportRect.height) - startTop + widget.offsetHeight));
        const width = clamp(startWidth + moveEvent.clientX - startX, minWidth, maxWidth);
        const height = clamp(startHeight + moveEvent.clientY - startY, minHeight, maxHeight);
        widget.style.width = `${width}px`;
        widget.style.height = `${height}px`;
      };

      const end = () => {
        if (finished) return;
        finished = true;
        widget.classList.remove("is-resizing");
        document.body.classList.remove("is-widget-resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", end);
        handle.removeEventListener("pointercancel", end);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
        try {
          handle.releasePointerCapture(event.pointerId);
        } catch {
          // Capture may already be released by the browser.
        }
        state.widgetLayout[widget.dataset.widgetId] = {
          ...(state.widgetLayout[widget.dataset.widgetId] || {}),
          leftPx: Math.round(parseFloat(widget.style.left || "0")),
          topPx: Math.round(parseFloat(widget.style.top || "0")),
          widthPx: Math.round(widget.offsetWidth),
          heightPx: Math.round(widget.offsetHeight),
          leftPct: parseFloat(widget.style.left || "0") / Math.max(1, viewportRect.width),
          topPct: parseFloat(widget.style.top || "0") / Math.max(1, viewportRect.height),
          widthPct: widget.offsetWidth / Math.max(1, viewportRect.width),
          heightPct: widget.offsetHeight / Math.max(1, viewportRect.height),
          z: Number(widget.style.zIndex || 4),
        };
        saveWidgetLayout();
        if (widget.dataset.widgetId === "browser-proof") scheduleBrowserResizeSync();
        recordUserEvent("workspace.widget_resize_finished", {
          target: `widget:${widget.dataset.widgetId}`,
          summary: `Finished resizing ${widget.dataset.widgetId}`,
          data: {
            widget_id: widget.dataset.widgetId,
            width: widget.offsetWidth,
            height: widget.offsetHeight,
          },
          duration_ms: performance.now() - startedAt,
        });
      };

      handle.addEventListener("pointermove", move, { passive: false });
      handle.addEventListener("pointerup", end, { once: true });
      handle.addEventListener("pointercancel", end, { once: true });
      window.addEventListener("pointermove", move, { passive: false });
      window.addEventListener("pointerup", end, { once: true });
      window.addEventListener("pointercancel", end, { once: true });
    });
  });
}

async function loadConfig() {
  try {
    const response = await fetch("/config.json", { cache: "no-store" });
    if (response.ok) {
      const config = await response.json();
      state.config = config;
      if (config.bridgeUrl) state.bridgeUrl = String(config.bridgeUrl).replace(/\/$/, "");
      state.googleClientId = String(config.auth?.googleClientId || "").trim();
      state.adminEmail = cleanText(config.auth?.adminEmail, state.adminEmail);
      const timeoutSec = Number(config.agentTurnTimeoutSec);
      if (Number.isFinite(timeoutSec) && timeoutSec >= 30) {
        state.agentTurnTimeoutMs = timeoutSec * 1000;
      }
    }
  } catch {
    // Keep the local default when the config route is unavailable.
  }
  renderLogin();
}

function publicUserLabel(user) {
  return cleanText(user?.name || user?.email, "Guest");
}

function publicUserInitial(user) {
  const label = publicUserLabel(user);
  return label.slice(0, 1).toUpperCase();
}

function isAdminUser(user = state.authUser) {
  return String(user?.role || "").toLowerCase() === "admin";
}

function setLoginOpen(open) {
  const nextOpen = Boolean(open);
  if (!nextOpen && closeUiNavigationLayer("login-popover")) return;
  state.loginOpen = nextOpen;
  if (!els.loginPopover || !els.loginButton) return;
  els.loginPopover.hidden = !state.loginOpen;
  els.loginButton.setAttribute("aria-expanded", state.loginOpen ? "true" : "false");
  if (state.loginOpen) {
    renderLogin();
    void renderGoogleSignInButton();
    pushUiNavigationLayer("login-popover", () => {
      state.loginOpen = false;
      if (els.loginPopover) els.loginPopover.hidden = true;
      els.loginButton?.setAttribute("aria-expanded", "false");
    });
  }
}

function renderAuthGate() {
  if (!els.app) return;
  const authenticated = Boolean(state.authUser);
  els.app.dataset.auth = authenticated ? "ready" : state.authChecked && state.googleClientId ? "locked" : "checking";
  if (els.authGateCopy) {
    els.authGateCopy.textContent = state.googleClientId
      ? "Sign in with an allowlisted Google account to open wasm-agent."
      : "Google login is not configured on this server yet.";
  }
  if (els.authGateMessage) {
    els.authGateMessage.textContent = authenticated
      ? ""
      : state.authChecked ? state.loginMessage || (state.googleClientId ? "" : "Missing GOOGLE_LOGIN_CLIENT_ID") : "";
  }
}

function renderLogin() {
  if (!els.launcherLogin) return;
  const user = state.authUser;
  els.launcherLogin.classList.toggle("signed-in", Boolean(user));
  els.launcherLogin.classList.toggle("needs-config", !state.googleClientId && !user);
  els.launcherLogin.classList.toggle("error", Boolean(state.loginMessage) && !user && Boolean(state.googleClientId));
  if (els.loginAvatar) {
    if (user?.picture_url) els.loginAvatar.replaceChildren();
    else if (user) els.loginAvatar.textContent = publicUserInitial(user);
    else if (!els.loginAvatar.querySelector(".google-logo")) {
      const logo = document.createElement("img");
      logo.className = "google-logo";
      logo.src = "/icons/google-logo.svg";
      logo.alt = "";
      els.loginAvatar.replaceChildren(logo);
    }
    els.loginAvatar.style.backgroundImage = user?.picture_url ? `url("${user.picture_url}")` : "";
  }
  if (els.loginButton) {
    els.loginButton.title = user ? publicUserLabel(user) : "Sign in with Google";
    els.loginButton.setAttribute("aria-label", user ? `Account ${publicUserLabel(user)}` : "Sign in with Google");
  }
  if (els.loginTitle) els.loginTitle.textContent = user ? publicUserLabel(user) : "Sign in";
  if (els.loginMeta) els.loginMeta.textContent = user ? cleanText(user.email, "Google account") : "Google";
  if (els.googleSignInButton) {
    els.googleSignInButton.hidden = Boolean(user);
    if (user) els.googleSignInButton.replaceChildren();
  }
  if (els.authGateGoogleSignInButton) {
    els.authGateGoogleSignInButton.hidden = Boolean(user) || !state.googleClientId;
    if (user) els.authGateGoogleSignInButton.replaceChildren();
  }
  if (els.authGateLoginButton) {
    els.authGateLoginButton.hidden = Boolean(user) || !state.authChecked || (
      Boolean(state.googleClientId) && Boolean(els.authGateGoogleSignInButton?.childElementCount)
    );
  }
  if (els.logoutButton) els.logoutButton.hidden = !user;
  if (els.loginMessage) {
    els.loginMessage.textContent = user
      ? `${cleanText(user.role, "user")} account ${user.id}`
      : state.loginMessage || (state.googleClientId ? "Only allowlisted accounts can enter." : "Google client ID missing");
  }
  renderAuthGate();
}

function loadGoogleIdentityScript() {
  if (!state.googleClientId) return Promise.reject(new Error("Google client ID missing"));
  if (window.google?.accounts?.id) {
    installGoogleStyleOverrides();
    return Promise.resolve();
  }
  if (window.__wasmAgentGoogleIdentityPromise) return window.__wasmAgentGoogleIdentityPromise;
  window.__wasmAgentGoogleIdentityPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      installGoogleStyleOverrides();
      resolve();
    };
    script.onerror = () => reject(new Error("Google Identity failed to load"));
    document.head.append(script);
  });
  return window.__wasmAgentGoogleIdentityPromise;
}

function installGoogleStyleOverrides() {
  const id = "wasmAgentGoogleStyleOverrides";
  document.querySelector(`#${id}`)?.remove();
  const style = document.createElement("style");
  style.id = id;
  style.textContent = `
    .google-signin-slot .nsm7Bb-HzV7m-LgbsSe-Bz112c-haAclf,
    .google-signin-slot [id="container-div"] {
      background: transparent !important;
      background-color: transparent !important;
      box-shadow: none !important;
    }
    .google-signin-slot .nsm7Bb-HzV7m-LgbsSe-Bz112c-haAclf {
      min-width: 28px !important;
      width: 28px !important;
      height: 28px !important;
      margin-left: -4px !important;
      margin-right: 10px !important;
    }
    .google-signin-slot .nsm7Bb-HzV7m-LgbsSe {
      background: rgba(10, 18, 30, 0.96) !important;
      border-color: rgba(147, 170, 203, 0.18) !important;
      color: #e8eef7 !important;
    }
  `;
  document.head.append(style);
}

function renderGoogleLoginFace(slot) {
  const shell = document.createElement("div");
  shell.className = "google-login-shell";

  const face = document.createElement("div");
  face.className = "google-login-face";
  face.setAttribute("aria-hidden", "true");

  const logo = document.createElement("img");
  logo.className = "google-login-face-logo";
  logo.src = "/icons/google-logo.svg";
  logo.alt = "";

  const label = document.createElement("span");
  label.textContent = "Google Login";

  const clickLayer = document.createElement("div");
  clickLayer.className = "google-login-click-layer";

  face.append(logo, label);
  shell.append(face, clickLayer);
  slot.replaceChildren(shell);
  return clickLayer;
}

async function renderGoogleSignInButton() {
  const shouldRender = state.loginOpen || (!state.authUser && els.app?.dataset.auth === "locked");
  const slots = [els.googleSignInButton, els.authGateGoogleSignInButton].filter(Boolean);
  if (!state.authChecked || !shouldRender || state.authUser || !slots.length) return;
  if (!state.googleClientId) {
    slots.forEach((slot) => slot.replaceChildren());
    state.loginMessage = "Set GOOGLE_LOGIN_CLIENT_ID";
    renderLogin();
    return;
  }
  if (state.googleButtonRenderedFor === state.googleClientId && slots.every((slot) => slot.childElementCount)) return;
  state.loginMessage = "";
  renderLogin();
  try {
    await loadGoogleIdentityScript();
    window.google.accounts.id.initialize({
      client_id: state.googleClientId,
      callback: handleGoogleCredential,
      ux_mode: "popup",
    });
    slots.forEach((slot) => {
      const clickLayer = renderGoogleLoginFace(slot);
      window.google.accounts.id.renderButton(clickLayer, {
        type: "standard",
        theme: "filled_black",
        size: "large",
        text: "signin_with",
        shape: "rectangular",
        logo_alignment: "left",
        width: 500,
      });
    });
    installGoogleStyleOverrides();
    state.googleButtonRenderedFor = state.googleClientId;
    if (els.authGateLoginButton && els.authGateGoogleSignInButton?.childElementCount) {
      els.authGateLoginButton.hidden = true;
    }
  } catch (error) {
    state.loginMessage = error.message;
    renderLogin();
  }
}

async function loadAuthSession() {
  try {
    const payload = await fetchJson("/auth/session", { timeoutMs: 8000 });
    state.authUser = payload.user || null;
    state.loginMessage = "";
  } catch (error) {
    state.authUser = null;
    state.loginMessage = error.message;
  }
  state.authChecked = true;
  renderLogin();
}

async function handleGoogleCredential(response) {
  const credential = String(response?.credential || "");
  if (!credential) return;
  state.loginMessage = "Signing in...";
  renderLogin();
  try {
    const payload = await fetchJson("/auth/google", {
      method: "POST",
      body: { credential },
      timeoutMs: 15000,
    });
    state.authUser = payload.user || null;
    state.loginMessage = "";
    setLoginOpen(false);
    await bootstrapAuthenticatedApp();
    recordUserEvent("auth.google_login_finished", {
      target: "account",
      summary: `Signed in ${publicUserLabel(state.authUser)}`,
      data: { user_id: state.authUser?.id || "", email: state.authUser?.email || "" },
      redacted: true,
    });
  } catch (error) {
    state.loginMessage = error.message;
  }
  renderLogin();
}

async function logout() {
  try {
    await fetchJson("/auth/logout", { method: "POST", timeoutMs: 8000 });
  } catch {
    // Clearing local session state keeps the UI honest even if the server is restarting.
  }
  state.authUser = null;
  state.loginMessage = "";
  state.googleButtonRenderedFor = "";
  renderLogin();
  if (state.loginOpen) void renderGoogleSignInButton();
  if (state.refreshInterval) {
    window.clearInterval(state.refreshInterval);
    state.refreshInterval = 0;
  }
  if (state.resourceInterval) {
    window.clearInterval(state.resourceInterval);
    state.resourceInterval = 0;
  }
  if (state.securityInterval) {
    window.clearInterval(state.securityInterval);
    state.securityInterval = 0;
  }
  if (isBrowserStreamOpen() || state.browserLive) stopBrowserLive();
  state.authenticatedBootstrapped = false;
  renderAuthGate();
  recordUserEvent("auth.logout_finished", {
    target: "account",
    summary: "Signed out",
  });
}

async function loadWasm() {
  try {
    const bytes = bytesFromBase64(CORE_WASM_BASE64);
    const result = await WebAssembly.instantiate(bytes);
    state.wasm = result.instance.exports;
    state.wasmReady = typeof state.wasm.add === "function";
  } catch (error) {
    state.wasmReady = false;
    state.lastError = `WASM load error: ${error.message}`;
  }
}

function clientDeviceId() {
  try {
    const raw = JSON.parse(localStorage.getItem(CLIENT_DEVICE_STORAGE_KEY) || "{}");
    if (raw?.id && /^[a-z0-9_-]{8,96}$/i.test(raw.id)) return raw.id;
  } catch {
    // Device identity is local convenience state; a fresh id is safe.
  }
  const id = `dev_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
  try {
    localStorage.setItem(CLIENT_DEVICE_STORAGE_KEY, JSON.stringify({ id, created_at: new Date().toISOString() }));
  } catch {
    // The backend can fall back to user-agent/IP if local storage is blocked.
  }
  return id;
}

async function fetchJson(path, options = {}) {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  if (options.signal) options.signal.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutMs = Number(options.timeoutMs || 30000);
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Device-Id": clientDeviceId(),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { ok: false, error: { message: text.slice(0, 600) } };
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload?.error?.message || `HTTP ${response.status}`);
    }
    return payload;
  } finally {
    window.clearTimeout(timeout);
    if (options.signal) options.signal.removeEventListener("abort", abortFromCaller);
  }
}

async function bridgeJson(path, options = {}) {
  return fetchJson(`/bridge${path}`, options);
}

async function postAgentMessage(body, pendingMessage, options = {}) {
  if (!("ReadableStream" in window) || !("TextDecoder" in window)) {
    return fetchJson("/agent/session/message", { ...options, method: "POST", body });
  }
  return streamAgentMessage(body, pendingMessage, options);
}

async function streamAgentMessage(body, pendingMessage, options = {}) {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  if (options.signal) options.signal.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), Number(options.timeoutMs || 30000));
  try {
    const response = await fetch("/agent/session/message/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalPayload = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        const payload = handleAgentStreamLine(line, pendingMessage);
        if (payload?.type === "final") finalPayload = { ok: true, agent: payload.agent };
      }
    }
    if (buffer.trim()) {
      const payload = handleAgentStreamLine(buffer, pendingMessage);
      if (payload?.type === "final") finalPayload = { ok: true, agent: payload.agent };
    }
    if (!finalPayload) throw new Error("The embedded chat stream ended without a final response.");
    return finalPayload;
  } finally {
    window.clearTimeout(timeout);
    if (options.signal) options.signal.removeEventListener("abort", abortFromCaller);
  }
}

function handleAgentStreamLine(line, pendingMessage) {
  const text = String(line || "").trim();
  if (!text) return null;
  let payload = {};
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  if (payload.type === "action" && payload.action) {
    mergeAgentAction(pendingMessage, payload.action);
  }
  if (payload.type === "error") {
    throw new Error(payload.error?.message || "Embedded chat stream failed.");
  }
  return payload;
}

function setAgentOpen(open, options = {}) {
  const nextOpen = Boolean(open);
  const changed = state.agentOpen !== nextOpen;
  state.agentOpen = nextOpen;
  els.agentOverlay.dataset.open = nextOpen ? "true" : "false";
  els.agentAvatarButton.setAttribute("aria-expanded", nextOpen ? "true" : "false");
  if (nextOpen) {
    placeAgentPanel();
    window.setTimeout(() => {
      placeAgentPanel();
      els.agentInput.focus();
    }, 0);
  } else {
    setAgentBalloon("");
  }
  if (!changed && !options.forceEvent) return;
  recordUserEvent(nextOpen ? "agent.opened" : "agent.closed", {
    target: "agent-overlay",
    summary: nextOpen ? "Opened embedded assistant" : "Minimized embedded assistant",
    data: { panel: state.activePanel },
  });
}

function chatQueryIsOpen() {
  return new URLSearchParams(window.location.search).get(CHAT_QUERY_KEY) === CHAT_QUERY_VALUE;
}

function uiNavigationId() {
  const raw = window.history.state;
  return raw && typeof raw === "object" ? String(raw.uiLayerId || "") : "";
}

function uiNavigationLocationKey(url = window.location.href) {
  const nextUrl = url instanceof URL ? url : new URL(url, window.location.href);
  return `${nextUrl.pathname}${nextUrl.search}`;
}

function uiNavigationState(entry = state.uiNavigationStack.at(-1) || null) {
  const raw = window.history.state && typeof window.history.state === "object" ? window.history.state : {};
  return {
    ...raw,
    panel: state.activePanel,
    uiLayer: entry?.layer || "",
    uiLayerId: entry?.id || "",
    uiLayerLocationKey: entry?.locationKey || "",
  };
}

function uiNavigationUrl() {
  const url = new URL(window.location.href);
  if (state.agentOpen) {
    url.searchParams.set(CHAT_QUERY_KEY, CHAT_QUERY_VALUE);
  } else if (url.searchParams.get(CHAT_QUERY_KEY) === CHAT_QUERY_VALUE) {
    url.searchParams.delete(CHAT_QUERY_KEY);
  }
  return url;
}

function replaceCurrentUiNavigationState() {
  window.history.replaceState(uiNavigationState(), "", uiNavigationUrl());
}

function closeUiNavigationEntry(entry, options = {}) {
  if (!entry) return false;
  state.uiNavigationStack = state.uiNavigationStack.filter((item) => item.id !== entry.id);
  if (options.invoke !== false) entry.close?.({ skipHistory: true, skipStack: true });
  return true;
}

function pushUiNavigationLayer(layer, close, options = {}) {
  if (!layer) return null;
  state.uiNavigationStack
    .filter((entry) => entry.layer === layer)
    .forEach((entry) => closeUiNavigationEntry(entry, { invoke: false }));
  const url = uiNavigationUrl();
  if (options.chat) url.searchParams.set(CHAT_QUERY_KEY, CHAT_QUERY_VALUE);
  const entry = {
    id: `${layer}:${++state.uiNavigationSeq}`,
    layer,
    close,
    locationKey: uiNavigationLocationKey(url),
  };
  state.uiNavigationStack.push(entry);
  window.history.pushState(uiNavigationState(entry), "", url);
  return entry;
}

function closeUiNavigationLayer(layer, options = {}) {
  const entry = [...state.uiNavigationStack].reverse().find((item) => item.layer === layer);
  if (!entry) return false;
  const currentEntryIsLayer = uiNavigationId() === entry.id;
  const currentEntryIsOriginalLayerUrl = currentEntryIsLayer && entry.locationKey === uiNavigationLocationKey();
  if (!options.skipHistory && currentEntryIsOriginalLayerUrl) {
    window.history.back();
    return true;
  }
  closeUiNavigationEntry(entry);
  if (options.replaceHistory || currentEntryIsLayer) replaceCurrentUiNavigationState();
  return true;
}

function closeTopUiNavigationLayer() {
  const entry = state.uiNavigationStack.at(-1);
  if (!entry) return false;
  return closeUiNavigationLayer(entry.layer);
}

function syncUiNavigationWithHistory() {
  const targetId = uiNavigationId();
  while (state.uiNavigationStack.length && state.uiNavigationStack.at(-1).id !== targetId) {
    closeUiNavigationEntry(state.uiNavigationStack.at(-1));
  }
  if (targetId && !state.uiNavigationStack.some((entry) => entry.id === targetId)) {
    const raw = window.history.state && typeof window.history.state === "object" ? window.history.state : {};
    if (raw.uiLayer === "agent-chat") {
      const entry = {
        id: targetId,
        layer: "agent-chat",
        close: () => setAgentOpen(false),
        locationKey: String(raw.uiLayerLocationKey || uiNavigationLocationKey()),
      };
      state.uiNavigationStack.push(entry);
      setAgentOpen(true);
    }
  }
  if (!targetId && !chatQueryIsOpen() && state.agentOpen) {
    setAgentOpen(false);
  }
}

function initializeUiNavigationFromUrl() {
  state.uiNavigationStack = [];
  if (chatQueryIsOpen()) {
    const baseUrl = new URL(window.location.href);
    baseUrl.searchParams.delete(CHAT_QUERY_KEY);
    window.history.replaceState(uiNavigationState(null), "", baseUrl);
    setAgentOpen(true);
    pushUiNavigationLayer("agent-chat", () => setAgentOpen(false), { chat: true });
    return;
  }
  window.history.replaceState(uiNavigationState(null), "", window.location.href);
}

function openAgentChat() {
  setAgentOpen(true);
  pushUiNavigationLayer("agent-chat", () => setAgentOpen(false), { chat: true });
}

function closeAgentChat() {
  if (!closeUiNavigationLayer("agent-chat")) setAgentOpen(false);
}

function appendAgentMessage(role, content, extra = {}) {
  const session = activeAgentSession();
  const message = {
    id: `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    role,
    content,
    timestamp: new Date().toISOString(),
    ...extra,
  };
  session.messages.push(message);
  session.updated_at = new Date().toISOString();
  if (role === "user") session.title = truncateText(content, 42) || session.title;
  saveAgentSessions();
  renderAgentSessions();
  els.agentMessages.append(renderAgentMessage(message));
  els.agentMessages.scrollTop = els.agentMessages.scrollHeight;
  return message;
}

function renderAgentMessage(message) {
  const wrap = document.createElement("div");
  wrap.className = `agent-message ${message.role}`;
  wrap.dataset.messageId = message.id || "";
  if (message.pending) wrap.classList.add("is-thinking");
  const header = message.role === "assistant" && (message.pending || Number.isFinite(message.duration_ms))
    ? agentTurnHeader(message)
    : null;
  const body = document.createElement("div");
  body.className = "agent-message-body";
  body.textContent = message.content;
  if (message.images && message.images.length > 0) {
    const grid = document.createElement("div");
    grid.className = "agent-message-images";
    for (const imgData of message.images) {
      const img = document.createElement("img");
      img.src = imgData.data_url || imgData;
      img.alt = imgData.name || "Attached image";
      img.loading = "lazy";
      grid.append(img);
    }
    wrap.append(grid);
  }
  const imageCards = renderAgentImageCards(message);
  if (imageCards) wrap.append(imageCards);
  if (header) wrap.append(header);
  const actions = message.role === "assistant" ? agentActionsChain(message) : null;
  if (actions) wrap.append(actions);
  wrap.append(body);
  const changedFiles = message.role === "assistant" ? changedFilesFooter(message.changed_files || []) : null;
  if (changedFiles) wrap.append(changedFiles);
  return wrap;
}

function renderAgentImageCards(message) {
  const entries = [
    ...(Array.isArray(message.images) ? message.images : []),
    ...(Array.isArray(message.attachments) ? message.attachments : []),
  ].filter((item) => item?.image_card);
  if (!entries.length) return null;
  const details = document.createElement("details");
  details.className = "agent-image-card";
  const summary = document.createElement("summary");
  summary.className = "agent-image-card-summary";
  const first = imageCardSummary(entries[0]);
  summary.textContent = entries.length === 1
    ? `Image card: ${imageCardOneLine(first)}`
    : `${entries.length} image cards`;
  const list = document.createElement("div");
  list.className = "agent-image-card-list";
  list.replaceChildren(...entries.map(renderAgentImageCard));
  details.append(summary, list);
  return details;
}

function imageCardOneLine(card) {
  const palette = Array.isArray(card.palette) && card.palette.length ? card.palette.slice(0, 3).join(", ") : "palette unknown";
  const gradient = card.composition?.gradient?.kind || "";
  return [card.dimensions, palette, gradient].filter(Boolean).join(" / ");
}

function metricText(value) {
  return Number.isFinite(value) ? String(value) : "-";
}

function renderAgentImageCard(entry) {
  const card = imageCardSummary(entry);
  const article = document.createElement("article");
  article.className = "agent-image-card-item";
  const title = document.createElement("div");
  title.className = "agent-image-card-title";
  const name = document.createElement("strong");
  const dims = document.createElement("span");
  name.textContent = card.name;
  dims.textContent = [card.dimensions, card.size ? `${Math.round(card.size / 1024)} KB` : ""].filter(Boolean).join(" / ");
  title.append(name, dims);
  const tags = document.createElement("div");
  tags.className = "agent-image-card-tags";
  const tagValues = [
    ...(Array.isArray(card.palette) ? card.palette.slice(0, 4) : []),
    card.composition?.gradient?.kind,
  ].filter(Boolean);
  tags.replaceChildren(...tagValues.map((value) => {
    const tag = document.createElement("span");
    tag.textContent = value;
    return tag;
  }));
  const notes = document.createElement("p");
  notes.className = "agent-image-card-notes";
  notes.textContent = Array.isArray(card.visual_notes) && card.visual_notes.length
    ? card.visual_notes.slice(0, 8).join(", ")
    : "No visual notes.";
  const evidence = document.createElement("ul");
  evidence.className = "agent-image-card-evidence";
  const evidenceRows = Array.isArray(card.evidence) ? card.evidence.slice(0, 5) : [];
  evidence.replaceChildren(...evidenceRows.map((item) => {
    const row = document.createElement("li");
    const label = item.title || item.module || "Analyzer";
    const detail = [item.status, item.summary].filter(Boolean).join(" / ");
    row.textContent = `${label}: ${detail}`;
    return row;
  }));
  const metrics = document.createElement("dl");
  metrics.className = "agent-image-card-metrics";
  const analysis = card.analysis || {};
  const gradient = card.composition?.gradient || {};
  const symmetry = card.composition?.symmetry || {};
  const rows = [
    ["Luma", metricText(analysis.average_luminance)],
    ["Contrast", metricText(analysis.contrast)],
    ["Edges", metricText(analysis.edge_density)],
    ["Sharp", metricText(analysis.sharpness)],
    ["Gradient", metricText(gradient.strength)],
    ["Sym", [metricText(symmetry.horizontal), metricText(symmetry.vertical)].join(" / ")],
  ];
  for (const [labelText, valueText] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = labelText;
    dd.textContent = valueText;
    metrics.append(dt, dd);
  }
  article.append(title);
  if (tagValues.length) article.append(tags);
  article.append(notes);
  if (evidenceRows.length) article.append(evidence);
  article.append(metrics);
  if (card.local_url && card.local_url !== "-") {
    const local = document.createElement("code");
    local.className = "agent-image-card-url";
    local.textContent = card.local_url;
    article.append(local);
  }
  return article;
}

function agentTurnHeader(message) {
  const header = document.createElement("div");
  header.className = "agent-turn-header";
  const elapsed = document.createElement("span");
  elapsed.className = "agent-turn-elapsed";
  elapsed.dataset.messageId = message.id || "";
  const elapsedMs = Number.isFinite(message.duration_ms)
    ? message.duration_ms
    : Date.now() - Number(message.turn_started_at || Date.now());
  elapsed.textContent = formatTurnElapsed(elapsedMs);
  const menuButton = document.createElement("button");
  menuButton.className = "agent-message-menu-button";
  menuButton.type = "button";
  menuButton.title = "Message actions";
  menuButton.setAttribute("aria-label", "Message actions");
  menuButton.dataset.messageId = message.id || "";
  menuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    state.agentOpenMessageMenuId = state.agentOpenMessageMenuId === message.id ? "" : message.id;
    renderAgentMessages();
  });
  const arrow = document.createElement("span");
  arrow.className = "agent-menu-arrow";
  arrow.setAttribute("aria-hidden", "true");
  menuButton.append(arrow);
  header.append(elapsed, menuButton);
  if (state.agentOpenMessageMenuId === message.id) header.append(agentMessageMenu(message));
  return header;
}

function agentMessageMenu(message) {
  const menu = document.createElement("div");
  menu.className = "agent-message-menu";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "agent-message-menu-item";
  copy.addEventListener("click", (event) => {
    event.stopPropagation();
    copyAgentMessageText(message);
    state.agentOpenMessageMenuId = "";
    renderAgentMessages();
  });
  const icon = document.createElement("span");
  icon.className = "agent-icon-copy";
  icon.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.textContent = "Copy text";
  copy.append(icon, label);
  menu.append(copy);
  return menu;
}

function copyAgentMessageText(message) {
  const text = message.content || "";
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  recordUserEvent("agent.message_copied", {
    target: `message:${message.id || "unknown"}`,
    summary: "Copied assistant message text",
    data: { message_id: message.id || "", text_length: text.length },
  });
}

function renderAgentMessages() {
  const session = activeAgentSession();
  const prevScrollTop = els.agentMessages.scrollTop;
  // Snapshot which messages have their actions-chain details open
  const openChains = new Map();
  for (const child of els.agentMessages.querySelectorAll(".agent-message")) {
    const mid = child.dataset.messageId;
    const chain = child.querySelector(".agent-actions-chain");
    if (mid && chain) openChains.set(mid, chain.open);
  }
  els.agentMessages.replaceChildren();
  for (const message of session.messages) {
    els.agentMessages.append(renderAgentMessage(message));
  }
  // Restore open state for actions-chain details that were open before
  for (const child of els.agentMessages.querySelectorAll(".agent-message")) {
    const mid = child.dataset.messageId;
    if (openChains.get(mid)) {
      const chain = child.querySelector(".agent-actions-chain");
      if (chain) chain.open = true;
    }
  }
  renderAgentDiagnostics(session.diagnostics || {});
  renderAgentContextPreview(session.context_preview || []);
  els.agentMessages.scrollTop = prevScrollTop;
}

function renderAgentSessions() {
  if (!els.agentSessionList) return;
  els.agentSessionList.replaceChildren(
    ...state.agentSessions.map((session) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "agent-session-row";
      button.classList.toggle("active", session.id === state.activeAgentSessionId);
      button.dataset.sessionId = session.id;
      const title = document.createElement("strong");
      const meta = document.createElement("span");
      title.textContent = session.title || "Session";
      meta.textContent = `${session.messages?.length || 0} turns`;
      button.append(title, meta);
      button.addEventListener("click", () => {
        switchAgentSession(session.id);
        setAgentBalloon("");
      });
      return button;
    })
  );
}

function switchAgentSession(sessionId) {
  state.activeAgentSessionId = sessionId;
  renderAgentSessions();
  renderAgentMessages();
}

function newAgentSession() {
  const session = createAgentSession(`Session ${state.agentSessions.length + 1}`);
  state.agentSessions.unshift(session);
  state.activeAgentSessionId = session.id;
  saveAgentSessions();
  renderAgentSessions();
  renderAgentMessages();
  setAgentOpen(true);
  window.setTimeout(() => els.agentInput.focus(), 0);
  recordUserEvent("agent.session_created", {
    target: "agent-overlay",
    summary: "Created embedded assistant session",
    data: { session_id: session.id },
  });
}

function renderAgentDiagnostics(diagnostics = {}) {
  if (!els.agentDiagnostics) return;
  updateAgentTokenUsage(diagnostics.token_usage || null);
  const rows = [
    ["Mode", diagnostics.mode || els.agentModeSelect?.value || "-"],
    ["Node", diagnostics.target_node || agentTargetNode()],
    ["Source", diagnostics.source || "-"],
    ["Tools", diagnostics.tools?.join(", ") || "-"],
    ["Context", diagnostics.context_estimated_tokens ? `~${diagnostics.context_estimated_tokens} tokens` : "-"],
    ["Turns", Number.isFinite(diagnostics.transcript_turns) ? String(diagnostics.transcript_turns) : "-"],
    ["Time", Number.isFinite(diagnostics.duration_ms) ? `${diagnostics.duration_ms} ms` : "-"],
  ];
  els.agentDiagnostics.replaceChildren(
    ...rows.map(([label, value]) => {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      const desc = document.createElement("dd");
      term.textContent = label;
      desc.textContent = value;
      row.append(term, desc);
      return row;
    })
  );
}

function fmtCompactToken(n) {
  if (n == null || !Number.isFinite(n)) return "\u25c8 -";
  if (n < 1000) return `\u25c8 ${n}`;
  const abs = n;
  const [v, unit] = abs >= 1_000_000
    ? [Math.floor(abs / 10_000) / 100, 'M']
    : [Math.floor(abs / 10) / 100, 'K'];
  let s = v.toFixed(2).replace('.', ',');
  s = s.replace(/0$/, ''); // strip trailing zero, keep at least one decimal
  return `\u25c8 ${s}${unit}`;
}
function updateAgentTokenUsage(usage = state.agentTokenUsage) {
  state.agentTokenUsage = usage || null;
  if (!els.agentTokenUsage) return;
  const total = usage && Number.isFinite(usage.total_tokens) ? usage.total_tokens : null;
  els.agentTokenUsage.textContent = fmtCompactToken(total);
  els.agentTokenUsage.title = usage
    ? `Exact model tokens: input ${usage.prompt_tokens || 0}, output ${usage.completion_tokens || 0}, total ${total || 0}`
    : "Exact model token usage for the last turn";
}

function changedFilesFooter(files = []) {
  if (!files.length) return null;
  const totals = files.reduce(
    (sum, file) => ({
      additions: sum.additions + (Number.isFinite(file.additions) ? file.additions : 0),
      deletions: sum.deletions + (Number.isFinite(file.deletions) ? file.deletions : 0),
    }),
    { additions: 0, deletions: 0 }
  );
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  details.className = "agent-changed-details";
  summary.className = "agent-changed-summary";
  summary.replaceChildren(
    document.createTextNode(`${files.length} files changed `),
    statSpan(`+${totals.additions}`, "add"),
    document.createTextNode(" "),
    statSpan(`-${totals.deletions}`, "del")
  );
  const list = document.createElement("div");
  list.className = "agent-file-list";
  list.replaceChildren(
    ...files.map((file) => {
      const item = document.createElement("div");
      item.className = "agent-file-row";
      const path = document.createElement("span");
      const stats = document.createElement("span");
      path.className = "agent-file-path";
      stats.className = "agent-file-diff";
      path.textContent = file.full_path || file.path || String(file);
      path.title = file.full_path || file.path || String(file);
      stats.replaceChildren(
        statSpan(`+${Number.isFinite(file.additions) ? file.additions : 0}`, "add"),
        document.createTextNode(" "),
        statSpan(`-${Number.isFinite(file.deletions) ? file.deletions : 0}`, "del")
      );
      item.append(path, stats);
      return item;
    })
  );
  details.append(summary, list);
  return details;
}

function agentActionsChain(message) {
  const actions = Array.isArray(message.actions) ? message.actions : [];
  if (!actions.length) return null;
  const details = document.createElement("details");
  details.className = "agent-actions-chain";
  details.open = Boolean(message.pending);
  const summary = document.createElement("summary");
  summary.className = "agent-actions-summary";
  const running = actions.find((action) => action.status === "running");
  const failed = actions.find((action) => action.status === "error");
  const label = message.pending
    ? running?.label || message.phase || "Working"
    : failed
      ? "Actions need attention"
      : `${actions.length} actions completed`;
  const summaryLabel = document.createElement("span");
  const summaryMeta = document.createElement("span");
  summaryLabel.textContent = label;
  summaryMeta.className = "agent-actions-count";
  summaryMeta.textContent = `${actions.length}`;
  summary.append(summaryLabel, summaryMeta);
  const list = document.createElement("div");
  list.className = "agent-actions-list";
  list.replaceChildren(...actions.map(renderAgentActionRow));
  details.append(summary, list);
  return details;
}

function renderAgentActionRow(action) {
  const hasPreview = Boolean(action.preview || action.arguments);
  const row = document.createElement(hasPreview ? "details" : "div");
  const status = cleanText(action.status, "done");
  const kind = cleanText(action.kind, "step");
  row.className = `agent-action-row ${status} kind-${kind}`;
  if (hasPreview && action.open) row.open = true;
  const head = document.createElement(hasPreview ? "summary" : "div");
  head.className = "agent-action-row-summary";
  const dot = document.createElement("span");
  dot.className = "agent-action-dot";
  dot.setAttribute("aria-hidden", "true");
  const main = document.createElement("span");
  main.className = "agent-action-main";
  const label = document.createElement("strong");
  const detail = document.createElement("span");
  const badge = document.createElement("span");
  const meta = document.createElement("span");
  badge.className = "agent-action-kind";
  meta.className = "agent-action-meta";
  badge.textContent = kind;
  meta.textContent = cleanText(action.meta, status);
  label.textContent = cleanText(action.label, "Action");
  detail.textContent = cleanText(action.detail, "");
  main.append(label);
  if (detail.textContent) main.append(detail);
  head.append(dot, main, badge, meta);
  row.append(head);
  if (hasPreview) {
    const preview = document.createElement("pre");
    preview.className = "agent-action-preview";
    const args = action.arguments ? `args\n${JSON.stringify(action.arguments, null, 2)}` : "";
    const result = action.preview ? `result\n${action.preview}` : "";
    preview.textContent = [args, result].filter(Boolean).join("\n\n");
    row.append(preview);
  }
  return row;
}

function agentAction(label, status = "done", detail = "", extra = {}) {
  return {
    id: `act_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    kind: "client",
    label,
    status,
    detail,
    ...extra,
  };
}

function mergeAgentAction(message, nextAction) {
  if (!message || !nextAction) return;
  const actions = Array.isArray(message.actions) ? [...message.actions] : [];
  const actionId = nextAction.id || `act_${actions.length + 1}`;
  const index = actions.findIndex((action) => action.id === actionId);
  const normalized = { ...nextAction, id: actionId };
  if (index >= 0) {
    actions[index] = { ...actions[index], ...normalized };
  } else {
    actions.push(normalized);
  }
  updateAgentPendingMessage(message, { actions });
}

function agentActionRowsFromPayload(agent, fallbackActions = []) {
  const actions = Array.isArray(agent?.actions) ? agent.actions : [];
  if (actions.length) return actions;
  const rows = fallbackActions.map((action) => ({ ...action, status: action.status === "running" ? "done" : action.status }));
  const previews = Array.isArray(agent?.context_preview) ? agent.context_preview : [];
  previews.forEach((item) => {
    rows.push(agentAction(`Tool: ${cleanText(item.tool, "context")}`, "done", cleanText(item.path || item.query || item.preview, "")));
  });
  const diagnostics = agent?.diagnostics || {};
  rows.push(agentAction("Node reply", "done", `${diagnostics.source || "adapter"} / ${agent?.duration_ms || diagnostics.duration_ms || 0} ms`));
  if (diagnostics.auto_checkpoint?.ref) {
    rows.push(agentAction("Timeline checkpoint", "done", `${diagnostics.auto_checkpoint.label || "auto"} ${diagnostics.auto_checkpoint.sha || ""}`.trim()));
  }
  const changed = Array.isArray(agent?.changed_files) ? agent.changed_files.length : 0;
  if (changed) rows.push(agentAction("Changed files", "done", `${changed} paths`));
  return rows;
}

function statSpan(text, kind) {
  const span = document.createElement("span");
  span.className = `agent-diff-${kind}`;
  span.textContent = text;
  return span;
}

function dataUrlByteLength(dataUrl) {
  const encoded = String(dataUrl || "").split(",", 2)[1] || "";
  return Math.floor((encoded.length * 3) / 4);
}

function agentImagePayloadBytes(image) {
  const declared = Number(image?.size);
  if (Number.isFinite(declared) && declared > 0) return declared;
  return dataUrlByteLength(image?.data_url || "");
}

function agentPendingImageBytes() {
  return state.agentPendingImages.reduce((sum, image) => sum + agentImagePayloadBytes(image), 0);
}

function agentAttachmentSummary(image, reason) {
  return {
    data_url: image?.data_url,
    name: cleanText(image?.name, "Attached image"),
    type: cleanText(image?.type || image?.original_type, "image"),
    size: agentImagePayloadBytes(image),
    width: Number.isFinite(image?.width) ? image.width : undefined,
    height: Number.isFinite(image?.height) ? image.height : undefined,
    original_type: cleanText(image?.original_type, ""),
    original_size: Number.isFinite(image?.original_size) ? image.original_size : undefined,
    image_card: image?.image_card,
    asset: image?.asset,
    reason,
  };
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

function loadDataUrlImage(dataUrl, name) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Could not decode ${name}`));
    img.src = dataUrl;
  });
}

function roundedMetric(value, digits = 3) {
  if (!Number.isFinite(value)) return 0;
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function rgbToHex(r, g, b) {
  return `#${[r, g, b].map((value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, "0")).join("")}`;
}

function rgbToHsl(r, g, b) {
  const red = r / 255;
  const green = g / 255;
  const blue = b / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const lightness = (max + min) / 2;
  if (max === min) return { hue: 0, saturation: 0, lightness };
  const delta = max - min;
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  let hue = 0;
  if (max === red) hue = (green - blue) / delta + (green < blue ? 6 : 0);
  if (max === green) hue = (blue - red) / delta + 2;
  if (max === blue) hue = (red - green) / delta + 4;
  return { hue: hue * 60, saturation, lightness };
}

function colorName(r, g, b) {
  const { hue, saturation, lightness } = rgbToHsl(r, g, b);
  if (lightness < 0.12) return "black";
  if (lightness > 0.9 && saturation < 0.2) return "white";
  if (saturation < 0.12) {
    if (lightness < 0.32) return "charcoal";
    if (lightness > 0.72) return "silver";
    return "gray";
  }
  const hueName = hue < 12 || hue >= 345 ? "red"
    : hue < 34 ? "orange"
      : hue < 55 ? "yellow"
        : hue < 86 ? "lime"
          : hue < 145 ? "green"
            : hue < 174 ? "teal"
              : hue < 196 ? "cyan"
                : hue < 232 ? "blue"
                  : hue < 264 ? "indigo"
                    : hue < 292 ? "purple"
                      : hue < 326 ? "magenta"
                        : "pink";
  if (lightness < 0.24) return `dark ${hueName}`;
  if (lightness > 0.78) return `pale ${hueName}`;
  return hueName;
}

function averageHash(image) {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 8;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return "";
  ctx.drawImage(image, 0, 0, 8, 8);
  const { data } = ctx.getImageData(0, 0, 8, 8);
  const luma = [];
  for (let i = 0; i < data.length; i += 4) {
    luma.push((data[i] * 0.299) + (data[i + 1] * 0.587) + (data[i + 2] * 0.114));
  }
  const avg = luma.reduce((sum, value) => sum + value, 0) / luma.length;
  let hex = "";
  for (let i = 0; i < luma.length; i += 4) {
    let nibble = 0;
    for (let bit = 0; bit < 4; bit += 1) {
      if (luma[i + bit] >= avg) nibble |= 1 << (3 - bit);
    }
    hex += nibble.toString(16);
  }
  return `ahash:${hex}`;
}

function luminanceWord(value) {
  if (value < 0.12) return "very dark";
  if (value < 0.28) return "dark";
  if (value < 0.45) return "dim";
  if (value < 0.65) return "medium";
  if (value < 0.82) return "bright";
  return "very bright";
}

function gradientDirection(horizontalDelta, verticalDelta) {
  const absH = Math.abs(horizontalDelta);
  const absV = Math.abs(verticalDelta);
  if (Math.max(absH, absV) < 0.025) return "centered or even";
  if (absH > absV * 1.35) return horizontalDelta > 0 ? "brighter on right" : "brighter on left";
  if (absV > absH * 1.35) return verticalDelta > 0 ? "brighter at bottom" : "brighter at top";
  const vertical = verticalDelta > 0 ? "bottom" : "top";
  const horizontal = horizontalDelta > 0 ? "right" : "left";
  return `brighter toward ${vertical}-${horizontal}`;
}

function textLikeRegionSignals(luma, mask, width, height, avgLuma) {
  const rows = 6;
  const cols = 4;
  const cells = Array.from({ length: rows * cols }, (_, index) => ({
    index,
    row: Math.floor(index / cols),
    col: index % cols,
    count: 0,
    dark: 0,
    bright: 0,
    transitions: 0,
    comparisons: 0,
  }));
  const darkThreshold = Math.max(42, Math.min(125, avgLuma * 0.78));
  const brightThreshold = Math.max(darkThreshold + 28, Math.min(210, avgLuma + 24));
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = y * width + x;
      if (!mask[index]) continue;
      const cellCol = Math.min(cols - 1, Math.floor((x / width) * cols));
      const cellRow = Math.min(rows - 1, Math.floor((y / height) * rows));
      const cell = cells[cellRow * cols + cellCol];
      const lum = luma[index];
      cell.count += 1;
      if (lum <= darkThreshold) cell.dark += 1;
      if (lum >= brightThreshold) cell.bright += 1;
      if (x > 0) {
        const previous = index - 1;
        if (mask[previous]) {
          cell.comparisons += 1;
          if (Math.abs(lum - luma[previous]) > 18) cell.transitions += 1;
        }
      }
      if (y > 0) {
        const previous = index - width;
        if (mask[previous]) {
          cell.comparisons += 1;
          if (Math.abs(lum - luma[previous]) > 18) cell.transitions += 1;
        }
      }
    }
  }
  const scored = cells.map((cell) => {
    const darkRatio = cell.dark / Math.max(1, cell.count);
    const brightRatio = cell.bright / Math.max(1, cell.count);
    const transitionDensity = cell.transitions / Math.max(1, cell.comparisons);
    const hasInkAndSurface = darkRatio > 0.035 && darkRatio < 0.62 && brightRatio > 0.08;
    const centerBias = cell.col > 0 && cell.col < cols - 1 && cell.row > 0 && cell.row < rows - 1 ? 1.18 : 1;
    const score = Math.min(1, (transitionDensity * 2.2 + Math.min(darkRatio, 0.34) * 0.9 + Math.min(brightRatio, 0.5) * 0.2) * centerBias * (hasInkAndSurface ? 1 : 0.45));
    return {
      ...cell,
      dark_ratio: roundedMetric(darkRatio),
      bright_ratio: roundedMetric(brightRatio),
      transition_density: roundedMetric(transitionDensity),
      score: roundedMetric(score),
    };
  }).sort((a, b) => b.score - a.score);
  const active = scored.filter((cell) => cell.score > 0.18);
  const activeRows = new Set(active.map((cell) => cell.row));
  const activeCols = new Set(active.map((cell) => cell.col));
  const horizontalBands = activeRows.size;
  const regionLabels = [];
  if (active.length) {
    const rowAvg = active.reduce((sum, cell) => sum + cell.row, 0) / active.length;
    const colAvg = active.reduce((sum, cell) => sum + cell.col, 0) / active.length;
    const vertical = rowAvg < 1.8 ? "upper" : rowAvg > 3.8 ? "lower" : "middle";
    const horizontal = colAvg < 1.1 ? "left" : colAvg > 1.9 ? "right" : "center";
    regionLabels.push(`${vertical} ${horizontal}`.trim());
  }
  const topScore = scored.slice(0, 4).reduce((sum, cell) => sum + cell.score, 0) / Math.max(1, Math.min(4, scored.length));
  return {
    score: roundedMetric(topScore),
    horizontal_band_estimate: horizontalBands,
    active_cell_count: active.length,
    active_row_count: activeRows.size,
    active_col_count: activeCols.size,
    regions: regionLabels,
    cells: scored.slice(0, 5).map((cell) => ({
      row: cell.row,
      col: cell.col,
      score: cell.score,
      dark_ratio: cell.dark_ratio,
      bright_ratio: cell.bright_ratio,
      transition_density: cell.transition_density,
    })),
  };
}

function imageAnalyzerModules() {
  return MODULE_DEFINITIONS.filter((module) => module.analyzer?.kind === "image");
}

function imageAnalyzerModuleStates() {
  return imageAnalyzerModules().map((module) => ({
    id: module.id,
    title: module.title,
    enabled: isModuleEnabled(module.id),
    status: module.status,
    mode: module.analyzer?.mode || "",
    evidence: module.analyzer?.evidence || "",
    cached: IMAGE_ANALYZER_CACHE.has(module.id),
  }));
}

function imageAnalyzerEvidence(moduleId, status, summary, extra = {}) {
  const module = moduleDefinitionById(moduleId);
  const confidence = Number(extra.confidence);
  const durationMs = Number(extra.duration_ms);
  return {
    module: moduleId,
    title: module?.title || moduleId,
    status,
    summary: cleanText(summary, ""),
    confidence: Number.isFinite(confidence) ? roundedMetric(confidence) : undefined,
    facts: Array.isArray(extra.facts)
      ? extra.facts.map((item) => truncateText(item, 120)).filter(Boolean).slice(0, 8)
      : [],
    values: extra.values && typeof extra.values === "object" ? extra.values : undefined,
    reason: extra.reason ? truncateText(extra.reason, 160) : undefined,
    duration_ms: Number.isFinite(durationMs) ? Math.round(durationMs) : undefined,
    cached: Boolean(extra.cached),
  };
}

function addImageAnalyzerResult(card, result) {
  const evidence = Array.isArray(card.evidence) ? [...card.evidence] : [];
  const moduleResults = card.module_results && typeof card.module_results === "object" ? { ...card.module_results } : {};
  evidence.push(result);
  moduleResults[result.module] = result;
  return {
    ...card,
    evidence,
    module_results: moduleResults,
    analyzer_modules: imageAnalyzerModuleStates(),
  };
}

function createUnavailableImageAnalyzer(module, reason) {
  return async () => imageAnalyzerEvidence(
    module.id,
    "not_loaded",
    `${module.title} runtime is not bundled yet.`,
    {
      reason,
      facts: [`${module.title} was enabled, but no local runtime has been installed for this module.`],
      confidence: 0,
    }
  );
}

async function imageBitmapFromDataUrl(dataUrl) {
  if (!String(dataUrl || "").startsWith("data:image/")) return null;
  if (typeof createImageBitmap !== "function") return loadDataUrlImage(dataUrl, "barcode source");
  const response = await fetch(dataUrl);
  const blob = await response.blob();
  return createImageBitmap(blob);
}

function loadScriptOnce(url) {
  const source = String(url || "").trim();
  if (!source) return Promise.reject(new Error("script URL is empty"));
  if (SCRIPT_RUNTIME_CACHE.has(source)) return SCRIPT_RUNTIME_CACHE.get(source);
  const promise = new Promise((resolve, reject) => {
    const existing = Array.from(document.querySelectorAll("script[data-wasm-agent-runtime]"))
      .find((script) => script.dataset.wasmAgentRuntime === source);
    if (existing) {
      existing.addEventListener("load", () => resolve(existing), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Could not load ${source}`)), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = source;
    script.async = true;
    script.crossOrigin = "anonymous";
    script.dataset.wasmAgentRuntime = source;
    script.onload = () => resolve(script);
    script.onerror = () => reject(new Error(`Could not load ${source}`));
    document.head.append(script);
  });
  SCRIPT_RUNTIME_CACHE.set(source, promise);
  return promise;
}

function tesseractRuntimeUrl() {
  if (Object.prototype.hasOwnProperty.call(window, "__WASM_AGENT_TESSERACT_URL__")) {
    return String(window.__WASM_AGENT_TESSERACT_URL__ || "").trim();
  }
  return OCR_TESSERACT_DEFAULT_URL;
}

function normalizeOcrLines(text) {
  return String(text || "")
    .split(/\r?\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter((line) => line.length >= 2)
    .slice(0, 8);
}

function ocrTextSignals(context) {
  const card = context?.card && typeof context.card === "object" ? context.card : {};
  const composition = card.composition && typeof card.composition === "object" ? card.composition : {};
  const signals = context?.textSignals || composition.text_regions;
  return signals && typeof signals === "object" ? signals : {};
}

function shouldRunTesseractOcr(context) {
  const card = context?.card && typeof context.card === "object" ? context.card : {};
  const analysis = card.analysis && typeof card.analysis === "object" ? card.analysis : {};
  const signals = ocrTextSignals(context);
  const score = Number(analysis.text_like_score ?? signals.score ?? 0);
  const bands = Number(analysis.text_band_estimate ?? signals.horizontal_band_estimate ?? 0);
  return score >= OCR_TEXT_SCORE_THRESHOLD || bands >= 2;
}

function ocrCropBox(context, source) {
  const sourceWidth = Math.max(1, source.naturalWidth || source.videoWidth || source.width || context.width || 1);
  const sourceHeight = Math.max(1, source.naturalHeight || source.videoHeight || source.height || context.height || 1);
  const aspect = sourceWidth / sourceHeight;
  const signals = ocrTextSignals(context);
  const cells = Array.isArray(signals.cells) ? signals.cells : [];
  const scoredCells = cells.filter((cell) => Number(cell.score) >= OCR_TEXT_SCORE_THRESHOLD);
  if (scoredCells.length && Number(signals.active_row_count || 0) < 6 && Number(signals.active_col_count || 0) < 4) {
    const minCol = Math.max(0, Math.min(...scoredCells.map((cell) => Number(cell.col) || 0)) - 1);
    const maxCol = Math.min(3, Math.max(...scoredCells.map((cell) => Number(cell.col) || 0)) + 1);
    const minRow = Math.max(0, Math.min(...scoredCells.map((cell) => Number(cell.row) || 0)) - 1);
    const maxRow = Math.min(5, Math.max(...scoredCells.map((cell) => Number(cell.row) || 0)) + 1);
    const x = Math.floor((minCol / 4) * sourceWidth);
    const y = Math.floor((minRow / 6) * sourceHeight);
    const right = Math.ceil(((maxCol + 1) / 4) * sourceWidth);
    const bottom = Math.ceil(((maxRow + 1) / 6) * sourceHeight);
    return {
      x,
      y,
      width: Math.max(1, right - x),
      height: Math.max(1, bottom - y),
      reason: "text_like_grid",
    };
  }
  if (aspect <= 0.84) {
    return {
      x: Math.floor(sourceWidth * 0.04),
      y: Math.floor(sourceHeight * 0.12),
      width: Math.ceil(sourceWidth * 0.92),
      height: Math.ceil(sourceHeight * 0.68),
      reason: "portrait_text_window",
    };
  }
  if (aspect >= 1.2) {
    return {
      x: Math.floor(sourceWidth * 0.04),
      y: Math.floor(sourceHeight * 0.08),
      width: Math.ceil(sourceWidth * 0.92),
      height: Math.ceil(sourceHeight * 0.84),
      reason: "landscape_text_window",
    };
  }
  return {
    x: Math.floor(sourceWidth * 0.05),
    y: Math.floor(sourceHeight * 0.08),
    width: Math.ceil(sourceWidth * 0.9),
    height: Math.ceil(sourceHeight * 0.84),
    reason: "square_text_window",
  };
}

function histogramPercentile(histogram, total, percentile) {
  const target = Math.max(0, Math.min(total - 1, Math.round(total * percentile)));
  let seen = 0;
  for (let index = 0; index < histogram.length; index += 1) {
    seen += histogram[index];
    if (seen >= target) return index;
  }
  return histogram.length - 1;
}

function otsuThreshold(histogram, total) {
  let sum = 0;
  for (let index = 0; index < histogram.length; index += 1) sum += index * histogram[index];
  let sumBackground = 0;
  let weightBackground = 0;
  let bestVariance = -1;
  let threshold = 128;
  for (let index = 0; index < histogram.length; index += 1) {
    weightBackground += histogram[index];
    if (!weightBackground) continue;
    const weightForeground = total - weightBackground;
    if (!weightForeground) break;
    sumBackground += index * histogram[index];
    const meanBackground = sumBackground / weightBackground;
    const meanForeground = (sum - sumBackground) / weightForeground;
    const variance = weightBackground * weightForeground * (meanBackground - meanForeground) ** 2;
    if (variance > bestVariance) {
      bestVariance = variance;
      threshold = index;
    }
  }
  return threshold;
}

function clampByte(value) {
  return Math.max(0, Math.min(255, Math.round(value)));
}

async function prepareOcrInput(context) {
  const source = context.image || await imageBitmapFromDataUrl(context.dataUrl);
  if (!source) return null;
  let closeSource = false;
  if (source !== context.image) closeSource = true;
  try {
    const crop = ocrCropBox(context, source);
    const scale = Math.min(3, OCR_PREPROCESS_MAX_WIDTH / Math.max(1, crop.width));
    const outputWidth = Math.max(320, Math.round(crop.width * scale));
    const outputHeight = Math.max(120, Math.round(crop.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, outputWidth, outputHeight);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(source, crop.x, crop.y, crop.width, crop.height, 0, 0, outputWidth, outputHeight);
    const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
    const data = imageData.data;
    const histogram = new Array(256).fill(0);
    const luma = new Uint8Array(outputWidth * outputHeight);
    for (let pixel = 0; pixel < luma.length; pixel += 1) {
      const offset = pixel * 4;
      const value = clampByte((data[offset] * 0.299) + (data[offset + 1] * 0.587) + (data[offset + 2] * 0.114));
      luma[pixel] = value;
      histogram[value] += 1;
    }
    const low = histogramPercentile(histogram, luma.length, 0.05);
    const high = Math.max(low + 24, histogramPercentile(histogram, luma.length, 0.95));
    const stretchedHistogram = new Array(256).fill(0);
    const stretched = new Uint8Array(luma.length);
    for (let pixel = 0; pixel < luma.length; pixel += 1) {
      const value = clampByte(((luma[pixel] - low) / (high - low)) * 255);
      stretched[pixel] = value;
      stretchedHistogram[value] += 1;
    }
    const threshold = Math.max(92, Math.min(196, otsuThreshold(stretchedHistogram, stretched.length)));
    for (let pixel = 0; pixel < stretched.length; pixel += 1) {
      const offset = pixel * 4;
      const value = stretched[pixel] < threshold ? 0 : 255;
      data[offset] = value;
      data[offset + 1] = value;
      data[offset + 2] = value;
      data[offset + 3] = 255;
    }
    ctx.putImageData(imageData, 0, 0);
    return {
      dataUrl: canvas.toDataURL("image/png"),
      width: outputWidth,
      height: outputHeight,
      crop: {
        x: crop.x,
        y: crop.y,
        width: crop.width,
        height: crop.height,
        reason: crop.reason,
      },
      threshold,
      contrast_window: [low, high],
      preprocessed: true,
    };
  } finally {
    if (closeSource) source.close?.();
  }
}

async function configureTesseractWorker(worker, tesseract) {
  if (typeof worker?.setParameters !== "function") return;
  const pageSegMode = tesseract?.PSM?.SINGLE_BLOCK || "6";
  try {
    await worker.setParameters({
      tessedit_pageseg_mode: pageSegMode,
      preserve_interword_spaces: "1",
      user_defined_dpi: "180",
    });
  } catch {
    // Some Tesseract.js builds reject optional tuning parameters.
  }
}

function ocrEvidenceFromResult(module, engine, result, input) {
  const data = result?.data && typeof result.data === "object" ? result.data : {};
  const rawText = String(data.text || result?.text || "").trim();
  const lines = normalizeOcrLines(rawText);
  const words = Array.isArray(data.words)
    ? data.words.map((word) => cleanText(word.text || word.rawValue, "")).filter(Boolean).slice(0, 12)
    : [];
  const facts = lines.length ? lines : words.length ? words : [`${engine} found no readable text.`];
  const confidence = Number.isFinite(Number(data.confidence)) ? Number(data.confidence) / 100 : (lines.length ? 0.72 : 0.5);
  return imageAnalyzerEvidence(
    module.id,
    lines.length || words.length ? "detected" : "not_detected",
    lines.length || words.length
      ? `${engine} detected ${lines.length || words.length} text snippet${(lines.length || words.length) === 1 ? "" : "s"}.`
      : `${engine} did not detect readable text.`,
    {
      facts,
      values: {
        engine,
        text: truncateText(rawText, 600),
        lines,
        words,
        input: input ? {
          preprocessed: Boolean(input.preprocessed),
          width: input.width,
          height: input.height,
          crop: input.crop,
          threshold: input.threshold,
          contrast_window: input.contrast_window,
        } : undefined,
      },
      confidence: Math.max(0, Math.min(1, confidence)),
    }
  );
}

async function createBarcodeReaderAnalyzer(module) {
  const Detector = window.BarcodeDetector;
  if (typeof Detector !== "function") {
    return async () => imageAnalyzerEvidence(
      module.id,
      "unsupported",
      "This browser does not expose BarcodeDetector.",
      {
        reason: "BarcodeDetector API unavailable",
        facts: ["No local barcode runtime was available for this turn."],
        confidence: 0,
      }
    );
  }
  const preferredFormats = [
    "qr_code",
    "aztec",
    "data_matrix",
    "pdf417",
    "ean_13",
    "ean_8",
    "code_128",
    "code_39",
    "upc_a",
    "upc_e",
  ];
  let formats = preferredFormats;
  try {
    if (typeof Detector.getSupportedFormats === "function") {
      const supported = await Detector.getSupportedFormats();
      formats = preferredFormats.filter((format) => supported.includes(format));
    }
  } catch {
    formats = preferredFormats;
  }
  let detector = null;
  try {
    detector = formats.length ? new Detector({ formats }) : new Detector();
  } catch (error) {
    return async () => imageAnalyzerEvidence(
      module.id,
      "unsupported",
      "BarcodeDetector could not be initialized.",
      {
        reason: error.message,
        facts: ["Native barcode detection was present but failed during setup."],
        confidence: 0,
      }
    );
  }
  return async (context) => {
    const source = context.image || await imageBitmapFromDataUrl(context.dataUrl);
    if (!source) {
      return imageAnalyzerEvidence(
        module.id,
        "skipped",
        "No image bitmap source was available.",
        { reason: "missing_data_url", confidence: 0 }
      );
    }
    try {
      const codes = await detector.detect(source);
      const facts = codes.slice(0, 6).map((code) => {
        const format = cleanText(code.format, "barcode");
        const value = truncateText(code.rawValue || "", 96);
        return value ? `${format}: ${value}` : format;
      });
      return imageAnalyzerEvidence(
        module.id,
        codes.length ? "detected" : "not_detected",
        codes.length ? `${codes.length} barcode value${codes.length === 1 ? "" : "s"} detected.` : "No supported QR/barcode detected.",
        {
          facts: facts.length ? facts : ["No supported QR/barcode detected."],
          values: {
            count: codes.length,
            formats: [...new Set(codes.map((code) => code.format).filter(Boolean))].slice(0, 8),
            supported_formats: formats.slice(0, 12),
          },
          confidence: codes.length ? 1 : 0.82,
        }
      );
    } finally {
      if (source !== context.image) source.close?.();
    }
  };
}

async function createNativeOcrAnalyzer(module) {
  const Detector = window.TextDetector;
  if (typeof Detector !== "function") {
    return async () => imageAnalyzerEvidence(
      module.id,
      "unsupported",
      "This browser does not expose native TextDetector OCR.",
      {
        reason: "TextDetector API unavailable",
        facts: ["No local OCR runtime was available for this turn."],
        confidence: 0,
      }
    );
  }
  let detector = null;
  try {
    detector = new Detector();
  } catch (error) {
    return async () => imageAnalyzerEvidence(
      module.id,
      "unsupported",
      "Native TextDetector could not be initialized.",
      {
        reason: error.message,
        facts: ["Native OCR was present but failed during setup."],
        confidence: 0,
      }
    );
  }
  return async (context) => {
    const source = context.image || await imageBitmapFromDataUrl(context.dataUrl);
    if (!source) {
      return imageAnalyzerEvidence(
        module.id,
        "skipped",
        "No image source was available for OCR.",
        { reason: "missing_data_url", confidence: 0 }
      );
    }
    try {
      const detections = await detector.detect(source);
      const texts = detections
        .map((item) => cleanText(item.rawValue || item.text || "", ""))
        .filter(Boolean)
        .slice(0, 8);
      return imageAnalyzerEvidence(
        module.id,
        texts.length ? "detected" : "not_detected",
        texts.length ? `${texts.length} text region${texts.length === 1 ? "" : "s"} detected by native OCR.` : "No text detected by native OCR.",
        {
          facts: texts.length ? texts : ["No text detected by native OCR."],
          values: {
            text_region_count: detections.length,
            texts,
          },
          confidence: texts.length ? 0.86 : 0.72,
        }
      );
    } finally {
      if (source !== context.image) source.close?.();
    }
  };
}

async function createTesseractOcrAnalyzer(module) {
  const runtimeUrl = tesseractRuntimeUrl();
  if (!runtimeUrl) {
    return async () => imageAnalyzerEvidence(
      module.id,
      "not_loaded",
      "Tesseract OCR runtime is disabled.",
      {
        reason: "window.__WASM_AGENT_TESSERACT_URL__ is empty",
        facts: ["No native OCR or Tesseract runtime was available for this turn."],
        confidence: 0,
      }
    );
  }
  try {
    if (!window.Tesseract) await loadScriptOnce(runtimeUrl);
  } catch (error) {
    return async () => imageAnalyzerEvidence(
      module.id,
      "not_loaded",
      "Tesseract OCR runtime could not be loaded.",
      {
        reason: error.message,
        facts: [`Tesseract runtime URL failed: ${runtimeUrl}`],
        confidence: 0,
      }
    );
  }
  const tesseract = window.Tesseract;
  if (!tesseract || (typeof tesseract.createWorker !== "function" && typeof tesseract.recognize !== "function")) {
    return async () => imageAnalyzerEvidence(
      module.id,
      "not_loaded",
      "Tesseract OCR API was not found after loading the runtime.",
      {
        reason: "window.Tesseract missing createWorker/recognize",
        facts: ["The OCR runtime loaded but did not expose a compatible API."],
        confidence: 0,
      }
    );
  }
  if (typeof tesseract.createWorker === "function") {
    try {
      const worker = await tesseract.createWorker(OCR_TESSERACT_LANGUAGE, 1, {
        logger: () => {},
      });
      if (typeof worker.load === "function") {
        try {
          await worker.load();
        } catch {
          // Newer Tesseract.js workers may already be loaded.
        }
      }
      if (typeof worker.loadLanguage === "function") {
        try {
          await worker.loadLanguage(OCR_TESSERACT_LANGUAGE);
        } catch {
          // Newer Tesseract.js workers may load language during createWorker.
        }
      }
      if (typeof worker.initialize === "function") {
        try {
          await worker.initialize(OCR_TESSERACT_LANGUAGE);
        } catch {
          // Newer Tesseract.js workers may initialize during createWorker.
        }
      }
      await configureTesseractWorker(worker, tesseract);
      return async (context) => {
        if (!context.dataUrl && !context.image) {
          return imageAnalyzerEvidence(module.id, "skipped", "No data URL was available for Tesseract OCR.", {
            reason: "missing_data_url",
            confidence: 0,
          });
        }
        if (!shouldRunTesseractOcr(context)) {
          return imageAnalyzerEvidence(module.id, "not_detected", "Tesseract OCR skipped because the image card did not find text-like regions.", {
            reason: "low_text_like_score",
            facts: ["No strong local text-like signal was available for OCR."],
            confidence: 0.72,
          });
        }
        const input = await prepareOcrInput(context);
        const result = await worker.recognize(input?.dataUrl || context.dataUrl);
        return ocrEvidenceFromResult(module, "tesseract.js", result, input);
      };
    } catch (error) {
      return async () => imageAnalyzerEvidence(
        module.id,
        "error",
        "Tesseract OCR worker could not be initialized.",
        {
          reason: error.message,
          facts: ["The Tesseract runtime loaded but worker setup failed."],
          confidence: 0,
        }
      );
    }
  }
  return async (context) => {
    if (!context.dataUrl && !context.image) {
      return imageAnalyzerEvidence(module.id, "skipped", "No data URL was available for Tesseract OCR.", {
        reason: "missing_data_url",
        confidence: 0,
      });
    }
    if (!shouldRunTesseractOcr(context)) {
      return imageAnalyzerEvidence(module.id, "not_detected", "Tesseract OCR skipped because the image card did not find text-like regions.", {
        reason: "low_text_like_score",
        facts: ["No strong local text-like signal was available for OCR."],
        confidence: 0.72,
      });
    }
    const input = await prepareOcrInput(context);
    const result = await tesseract.recognize(input?.dataUrl || context.dataUrl, OCR_TESSERACT_LANGUAGE, { logger: () => {} });
    return ocrEvidenceFromResult(module, "tesseract.js", result, input);
  };
}

async function createOcrAnalyzer(module) {
  const nativeAnalyzer = await createNativeOcrAnalyzer(module);
  let tesseractAnalyzerPromise = null;
  return async (context) => {
    const nativeResult = await nativeAnalyzer(context);
    if (nativeResult.status === "detected") return nativeResult;
    if (!tesseractAnalyzerPromise) tesseractAnalyzerPromise = createTesseractOcrAnalyzer(module);
    const tesseractAnalyzer = await tesseractAnalyzerPromise;
    const tesseractResult = await tesseractAnalyzer(context);
    if (tesseractResult.status === "detected") return tesseractResult;
    if (nativeResult.status !== "unsupported" && nativeResult.status !== "not_detected") return nativeResult;
    return {
      ...tesseractResult,
      facts: [
        ...(Array.isArray(tesseractResult.facts) ? tesseractResult.facts : []),
        `Native OCR status: ${nativeResult.status}`,
      ].slice(0, 8),
    };
  };
}

async function createImageAnalyzer(module) {
  if (module.id === "barcode-reader") return createBarcodeReaderAnalyzer(module);
  if (module.id === "ocr") return createOcrAnalyzer(module);
  if (module.id === "cv-shapes") return createUnavailableImageAnalyzer(module, "CV shape runtime not bundled");
  if (module.id === "semantic-vision") return createUnavailableImageAnalyzer(module, "Semantic vision runtime not bundled");
  return createUnavailableImageAnalyzer(module, "No lazy analyzer loader is registered");
}

async function loadImageAnalyzer(module) {
  const cached = IMAGE_ANALYZER_CACHE.has(module.id);
  if (!cached) {
    IMAGE_ANALYZER_CACHE.set(module.id, Promise.resolve(createImageAnalyzer(module)));
  }
  const analyzer = await IMAGE_ANALYZER_CACHE.get(module.id);
  return { analyzer, cached };
}

function withImageAnalyzerTimeout(promise, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("image analyzer timed out")), timeoutMs);
    Promise.resolve(promise).then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      }
    );
  });
}

async function runImageAnalyzer(module, context) {
  const startedAt = performance.now();
  try {
    const { analyzer, cached } = await loadImageAnalyzer(module);
    const timeoutMs = module.id === "ocr" ? OCR_ANALYZER_TIMEOUT_MS : IMAGE_ANALYZER_TIMEOUT_MS;
    const result = await withImageAnalyzerTimeout(analyzer(context), timeoutMs);
    return {
      ...result,
      duration_ms: result.duration_ms ?? Math.round(performance.now() - startedAt),
      cached,
    };
  } catch (error) {
    return imageAnalyzerEvidence(
      module.id,
      error.message === "image analyzer timed out" ? "timeout" : "error",
      `${module.title} did not produce evidence.`,
      {
        reason: error.message,
        facts: [`${module.title} failed locally before the model turn.`],
        duration_ms: performance.now() - startedAt,
        confidence: 0,
      }
    );
  }
}

async function enrichImageCardWithModules(card, context) {
  const modules = imageAnalyzerModules()
    .filter((module) => module.id !== "image-card-core" && isModuleEnabled(module.id));
  const moduleContext = {
    ...context,
    card,
    imageCard: card,
    textSignals: card?.composition?.text_regions,
  };
  const results = await Promise.all(modules.map((module) => runImageAnalyzer(module, moduleContext)));
  return results.reduce((nextCard, result) => addImageAnalyzerResult(nextCard, result), {
    ...card,
    analyzer_modules: imageAnalyzerModuleStates(),
  });
}

async function analyzeImageElement(image, file, rawBytes, dataUrl) {
  const sourceWidth = Math.max(1, image.naturalWidth || image.width || AGENT_IMAGE_MAX_EDGE);
  const sourceHeight = Math.max(1, image.naturalHeight || image.height || AGENT_IMAGE_MAX_EDGE);
  const fallback = {
    schema: "hermes.wasm_agent.image_card.v1",
    analyzer_revision: IMAGE_CARD_ANALYZER_REVISION,
    name: file.name || "image",
    size: rawBytes,
    dimensions: `${sourceWidth}x${sourceHeight}`,
    width: sourceWidth,
    height: sourceHeight,
    palette: [],
    visual_notes: ["browser decoded image"],
    analyzer_modules: imageAnalyzerModuleStates(),
    evidence: [
      imageAnalyzerEvidence("image-card-core", isModuleEnabled("image-card-core") ? "active" : "disabled", "Browser decoded the image before the model turn.", {
        facts: isModuleEnabled("image-card-core")
          ? ["Core Canvas analyzer is available."]
          : ["Image Card Core module is disabled; only file metadata is available."],
        confidence: isModuleEnabled("image-card-core") ? 0.7 : 0,
      }),
    ],
  };
  fallback.module_results = { "image-card-core": fallback.evidence[0] };
  const context = { image, file, rawBytes, dataUrl, width: sourceWidth, height: sourceHeight };
  if (!isModuleEnabled("image-card-core")) return enrichImageCardWithModules(fallback, context);
  try {
    const scale = Math.min(1, AGENT_IMAGE_SAMPLE_EDGE / Math.max(sourceWidth, sourceHeight));
    const width = Math.max(1, Math.round(sourceWidth * scale));
    const height = Math.max(1, Math.round(sourceHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return enrichImageCardWithModules(fallback, context);
    ctx.drawImage(image, 0, 0, width, height);
    const { data } = ctx.getImageData(0, 0, width, height);
    const bins = new Map();
    const luma = new Float32Array(width * height);
    const mask = new Uint8Array(width * height);
    const lumaHistogram = new Array(16).fill(0);
    const regionStats = {
      center: { sum: 0, count: 0 },
      edges: { sum: 0, count: 0 },
      top_left: { sum: 0, count: 0 },
      top_right: { sum: 0, count: 0 },
      bottom_left: { sum: 0, count: 0 },
      bottom_right: { sum: 0, count: 0 },
      left: { sum: 0, count: 0 },
      right: { sum: 0, count: 0 },
      top: { sum: 0, count: 0 },
      bottom: { sum: 0, count: 0 },
    };
    let count = 0;
    let transparentCount = 0;
    let lumaSum = 0;
    let lumaSq = 0;
    let saturationSum = 0;
    let centerSum = 0;
    let centerCount = 0;
    let outerSum = 0;
    let outerCount = 0;
    let edgeCount = 0;
    let gradientSum = 0;
    let gradientComparisons = 0;
    const centerLeft = width * 0.3;
    const centerRight = width * 0.7;
    const centerTop = height * 0.3;
    const centerBottom = height * 0.7;

    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const offset = (y * width + x) * 4;
        const alpha = data[offset + 3];
        if (alpha < 16) {
          transparentCount += 1;
          continue;
        }
        const red = data[offset];
        const green = data[offset + 1];
        const blue = data[offset + 2];
        const lum = (red * 0.299) + (green * 0.587) + (blue * 0.114);
        const index = y * width + x;
        luma[index] = lum;
        mask[index] = 1;
        lumaSum += lum;
        lumaSq += lum * lum;
        saturationSum += rgbToHsl(red, green, blue).saturation;
        lumaHistogram[Math.max(0, Math.min(15, Math.floor((lum / 256) * 16)))] += 1;
        count += 1;
        const key = `${red >> 5},${green >> 5},${blue >> 5}`;
        const bin = bins.get(key) || { count: 0, red: 0, green: 0, blue: 0 };
        bin.count += 1;
        bin.red += red;
        bin.green += green;
        bin.blue += blue;
        bins.set(key, bin);
        if (x >= centerLeft && x <= centerRight && y >= centerTop && y <= centerBottom) {
          centerSum += lum;
          centerCount += 1;
          regionStats.center.sum += lum;
          regionStats.center.count += 1;
        } else {
          outerSum += lum;
          outerCount += 1;
          regionStats.edges.sum += lum;
          regionStats.edges.count += 1;
        }
        const quadrant = y < height / 2
          ? (x < width / 2 ? "top_left" : "top_right")
          : (x < width / 2 ? "bottom_left" : "bottom_right");
        regionStats[quadrant].sum += lum;
        regionStats[quadrant].count += 1;
        const horizontalRegion = x < width / 2 ? "left" : "right";
        const verticalRegion = y < height / 2 ? "top" : "bottom";
        regionStats[horizontalRegion].sum += lum;
        regionStats[horizontalRegion].count += 1;
        regionStats[verticalRegion].sum += lum;
        regionStats[verticalRegion].count += 1;
        if (x > 0) {
          const previous = y * width + x - 1;
          if (mask[previous]) {
            const diff = Math.abs(lum - luma[previous]);
            gradientSum += diff;
            gradientComparisons += 1;
            if (diff > 32) edgeCount += 1;
          }
        }
        if (y > 0) {
          const previous = (y - 1) * width + x;
          if (mask[previous]) {
            const diff = Math.abs(lum - luma[previous]);
            gradientSum += diff;
            gradientComparisons += 1;
            if (diff > 32) edgeCount += 1;
          }
        }
      }
    }
    if (!count) return enrichImageCardWithModules(fallback, context);
    let mirrorPairs = 0;
    let horizontalMirrorDiff = 0;
    let verticalMirrorDiff = 0;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < Math.floor(width / 2); x += 1) {
        const left = y * width + x;
        const right = y * width + (width - 1 - x);
        if (mask[left] && mask[right]) {
          horizontalMirrorDiff += Math.abs(luma[left] - luma[right]);
          mirrorPairs += 1;
        }
      }
    }
    let verticalPairs = 0;
    for (let y = 0; y < Math.floor(height / 2); y += 1) {
      for (let x = 0; x < width; x += 1) {
        const top = y * width + x;
        const bottom = (height - 1 - y) * width + x;
        if (mask[top] && mask[bottom]) {
          verticalMirrorDiff += Math.abs(luma[top] - luma[bottom]);
          verticalPairs += 1;
        }
      }
    }
    const palette = [];
    const paletteHex = [];
    for (const bin of Array.from(bins.values()).sort((a, b) => b.count - a.count)) {
      const red = bin.red / bin.count;
      const green = bin.green / bin.count;
      const blue = bin.blue / bin.count;
      const name = colorName(red, green, blue);
      if (!palette.includes(name)) palette.push(name);
      const hex = rgbToHex(red, green, blue);
      if (!paletteHex.includes(hex)) paletteHex.push(hex);
      if (palette.length >= 5 && paletteHex.length >= 5) break;
    }
    const avgLuma = lumaSum / count;
    const contrast = Math.sqrt(Math.max(0, (lumaSq / count) - (avgLuma * avgLuma)));
    const edgeDensity = edgeCount / Math.max(1, (width - 1) * height + (height - 1) * width);
    const centerLuma = centerCount ? centerSum / centerCount : avgLuma;
    const outerLuma = outerCount ? outerSum / outerCount : avgLuma;
    const regionLuma = Object.fromEntries(
      Object.entries(regionStats).map(([key, stat]) => [key, stat.count ? stat.sum / stat.count : avgLuma])
    );
    const normalizedRegions = Object.fromEntries(
      Object.entries(regionLuma).map(([key, value]) => [key, roundedMetric(value / 255)])
    );
    const horizontalDelta = (regionLuma.right - regionLuma.left) / 255;
    const verticalDelta = (regionLuma.bottom - regionLuma.top) / 255;
    const centerEdgeDelta = (centerLuma - outerLuma) / 255;
    const entropy = lumaHistogram.reduce((sum, bin) => {
      if (!bin) return sum;
      const p = bin / count;
      return sum - (p * Math.log2(p));
    }, 0) / 4;
    const sharpness = gradientSum / Math.max(1, gradientComparisons) / 255;
    const horizontalSymmetry = 1 - Math.min(1, (horizontalMirrorDiff / Math.max(1, mirrorPairs)) / 255);
    const verticalSymmetry = 1 - Math.min(1, (verticalMirrorDiff / Math.max(1, verticalPairs)) / 255);
    const gradientStrength = Math.max(Math.abs(horizontalDelta), Math.abs(verticalDelta), Math.abs(centerEdgeDelta));
    const gradientKind = Math.abs(centerEdgeDelta) > Math.max(Math.abs(horizontalDelta), Math.abs(verticalDelta)) * 1.3
      ? (centerEdgeDelta > 0 ? "radial center glow" : "radial edge glow")
      : gradientDirection(horizontalDelta, verticalDelta);
    const textSignals = textLikeRegionSignals(luma, mask, width, height, avgLuma);
    const notes = [];
    const aspect = sourceWidth / sourceHeight;
    if (aspect >= 1.2) notes.push("landscape layout");
    else if (aspect <= 0.84) notes.push("portrait layout");
    else if (aspect >= 0.92 && aspect <= 1.08) notes.push("near-square layout");
    else notes.push("slightly rectangular layout");
    if (avgLuma < 72) notes.push("dark overall");
    else if (avgLuma > 182) notes.push("bright overall");
    if (contrast > 62) notes.push("high contrast");
    else if (contrast < 26) notes.push("low contrast");
    if (centerEdgeDelta > 0.11) notes.push("bright center");
    else if (centerEdgeDelta > 0.025) notes.push("center slightly brighter than edges");
    else if (centerEdgeDelta < -0.11) notes.push("brighter edges");
    else if (centerEdgeDelta < -0.025) notes.push("edges slightly brighter than center");
    if (edgeDensity > 0.2) notes.push("dense edge detail");
    else if (edgeDensity < 0.015) notes.push("almost no hard edges");
    else if (edgeDensity < 0.055) notes.push("soft or low-detail image");
    if (sharpness < 0.018 && edgeDensity < 0.03) notes.push("smooth gradient-like surface");
    if (textSignals.score > 0.32) notes.push("strong text-like dark strokes on lighter regions");
    else if (textSignals.score > 0.2) notes.push("possible printed text or label-like markings");
    if (textSignals.horizontal_band_estimate >= 2) notes.push(`${textSignals.horizontal_band_estimate} horizontal text-like bands`);
    if (textSignals.regions.length && textSignals.score > 0.2) notes.push(`text-like detail strongest near ${textSignals.regions[0]}`);
    if (gradientKind.includes("radial")) notes.push(gradientKind);
    if (horizontalSymmetry > 0.94 && verticalSymmetry > 0.94) notes.push("highly symmetrical brightness");
    if (saturationSum / count < 0.16) notes.push("mostly desaturated colors");
    else if (saturationSum / count > 0.55) notes.push("saturated colors");
    if (transparentCount / (width * height) > 0.05) notes.push("contains transparent regions");
    if (palette.length) notes.push(`dominant ${palette.slice(0, 3).join(", ")} palette`);
    const card = {
      ...fallback,
      analyzer_revision: IMAGE_CARD_ANALYZER_REVISION,
      palette,
      palette_hex: paletteHex.slice(0, 5),
      visual_notes: notes.slice(0, 12),
      perceptual_hash: averageHash(image),
      analysis: {
        average_luminance: roundedMetric(avgLuma / 255),
        contrast: roundedMetric(contrast / 255),
        edge_density: roundedMetric(edgeDensity),
        center_luminance: roundedMetric(centerLuma / 255),
        edge_luminance: roundedMetric(outerLuma / 255),
        center_edge_delta: roundedMetric(centerEdgeDelta),
        average_saturation: roundedMetric(saturationSum / count),
        sharpness: roundedMetric(sharpness),
        entropy: roundedMetric(entropy),
        transparency: roundedMetric(transparentCount / (width * height)),
        text_like_score: textSignals.score,
        text_band_estimate: textSignals.horizontal_band_estimate,
        text_active_cell_count: textSignals.active_cell_count,
        sample_size: `${width}x${height}`,
      },
      composition: {
        brightness_distribution: {
          ...normalizedRegions,
          center_label: luminanceWord(centerLuma / 255),
          edge_label: luminanceWord(outerLuma / 255),
        },
        gradient: {
          kind: gradientKind,
          strength: roundedMetric(gradientStrength),
          horizontal_delta: roundedMetric(horizontalDelta),
          vertical_delta: roundedMetric(verticalDelta),
          center_edge_delta: roundedMetric(centerEdgeDelta),
        },
        symmetry: {
          horizontal: roundedMetric(horizontalSymmetry),
          vertical: roundedMetric(verticalSymmetry),
        },
        text_regions: textSignals,
      },
    };
    card.evidence = [
      imageAnalyzerEvidence("image-card-core", "active", "Canvas pixel metrics computed locally.", {
        facts: [
          `${width}x${height} sample`,
          `${notes.length} visual notes`,
          `${palette.length} palette names`,
          `edge density ${roundedMetric(edgeDensity)}`,
          `text-like score ${textSignals.score}`,
        ],
        values: {
          sample_size: `${width}x${height}`,
          palette_count: palette.length,
          note_count: notes.length,
          text_like_score: textSignals.score,
          text_band_estimate: textSignals.horizontal_band_estimate,
        },
        confidence: 0.9,
      }),
    ];
    card.module_results = { "image-card-core": card.evidence[0] };
    card.analyzer_modules = imageAnalyzerModuleStates();
    return enrichImageCardWithModules(card, context);
  } catch {
    return enrichImageCardWithModules(fallback, context);
  }
}

async function readFileDataUrl(file) {
  const rawDataUrl = await readFileAsDataUrl(file);
  const rawBytes = dataUrlByteLength(rawDataUrl);
  const base = {
    name: file.name || "image",
    original_type: file.type || "",
    original_size: file.size || rawBytes,
  };
  const image = await loadDataUrlImage(rawDataUrl, file.name || "image");
  const sourceWidth = Math.max(1, image.naturalWidth || image.width || AGENT_IMAGE_MAX_EDGE);
  const sourceHeight = Math.max(1, image.naturalHeight || image.height || AGENT_IMAGE_MAX_EDGE);
  const imageCard = await analyzeImageElement(image, file, rawBytes, rawDataUrl);
  if (rawBytes <= AGENT_IMAGE_MAX_BYTES && file.type !== "image/svg+xml") {
    return {
      ...base,
      data_url: rawDataUrl,
      type: file.type || "image/png",
      size: rawBytes,
      width: sourceWidth,
      height: sourceHeight,
      image_card: imageCard,
    };
  }

  const scale = Math.min(1, AGENT_IMAGE_MAX_EDGE / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));
  const canvas = document.createElement("canvas");
  let targetWidth = width;
  let targetHeight = height;
  canvas.width = targetWidth;
  canvas.height = targetHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error(`Could not prepare ${file.name || "image"} for upload`);
  ctx.fillStyle = "#090f1b";
  ctx.fillRect(0, 0, targetWidth, targetHeight);
  ctx.drawImage(image, 0, 0, targetWidth, targetHeight);

  let dataUrl = "";
  for (let resizeAttempt = 0; resizeAttempt < 4; resizeAttempt += 1) {
    let quality = AGENT_IMAGE_QUALITY;
    for (let qualityAttempt = 0; qualityAttempt < 5; qualityAttempt += 1) {
      dataUrl = canvas.toDataURL("image/jpeg", quality);
      if (dataUrlByteLength(dataUrl) <= AGENT_IMAGE_MAX_BYTES || quality <= 0.42) break;
      quality -= 0.12;
    }
    if (dataUrlByteLength(dataUrl) <= AGENT_IMAGE_MAX_BYTES) break;
    targetWidth = Math.max(360, Math.round(targetWidth * 0.82));
    targetHeight = Math.max(240, Math.round(targetHeight * 0.82));
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    ctx.fillStyle = "#090f1b";
    ctx.fillRect(0, 0, targetWidth, targetHeight);
    ctx.drawImage(image, 0, 0, targetWidth, targetHeight);
  }
  return {
    ...base,
    data_url: dataUrl,
    type: "image/jpeg",
    size: dataUrlByteLength(dataUrl),
    width: targetWidth,
    height: targetHeight,
    image_card: {
      ...imageCard,
      size: dataUrlByteLength(dataUrl),
      rendered_dimensions: `${targetWidth}x${targetHeight}`,
    },
  };
}

function handleAgentFiles(fileList) {
  const files = Array.from(fileList).filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  const pendingCount = state.agentPendingImages.length + state.agentPendingAttachmentSummaries.length;
  const slots = Math.max(0, AGENT_MAX_IMAGES - pendingCount);
  const selected = files.slice(0, slots);
  if (!selected.length) return;
  Promise.allSettled(selected.map(readFileDataUrl)).then((results) => {
    const entries = results.filter((item) => item.status === "fulfilled").map((item) => item.value);
    let nextBytes = agentPendingImageBytes();
    const accepted = [];
    const summarized = [];
    for (const entry of entries) {
      const bytes = agentImagePayloadBytes(entry);
      if (bytes > AGENT_IMAGE_MAX_BYTES || nextBytes + bytes > AGENT_IMAGE_TOTAL_MAX_BYTES) {
        summarized.push(agentAttachmentSummary(entry, "summarized_to_fit_request_budget"));
        continue;
      }
      nextBytes += bytes;
      accepted.push(entry);
    }
    state.agentPendingImages.push(...accepted);
    state.agentPendingAttachmentSummaries.push(...summarized);
    renderPendingPreviews();
    const rejected = results.filter((item) => item.status === "rejected");
    if (rejected.length || summarized.length) {
      const skippedCount = rejected.length + summarized.length;
      els.agentStatus.textContent = summarized.length ? "Attachments summarized" : "Attachment failed";
      recordUserEvent("agent.image_attach_error", {
        target: "agent-form",
        summary: `Could not attach ${skippedCount} image${skippedCount === 1 ? "" : "s"} as raw payload`,
        data: {
          error: rejected[0]?.reason?.message || "",
          summarized_count: summarized.length,
          raw_budget_bytes: AGENT_IMAGE_TOTAL_MAX_BYTES,
        },
      });
    }
  });
}

function removePendingImage(index) {
  state.agentPendingImages.splice(index, 1);
  renderPendingPreviews();
}

function removePendingAttachmentSummary(index) {
  state.agentPendingAttachmentSummaries.splice(index, 1);
  renderPendingPreviews();
}

function clearAgentPendingImages() {
  state.agentPendingImages = [];
  state.agentPendingAttachmentSummaries = [];
  renderPendingPreviews();
}

function renderPendingPreviews() {
  const preview = els.agentImagePreview;
  if (!preview) return;
  const summaryEntries = state.agentPendingAttachmentSummaries;
  if (!state.agentPendingImages.length && !summaryEntries.length) {
    preview.replaceChildren();
    preview.hidden = true;
    return;
  }
  preview.hidden = false;
  const rawItems = state.agentPendingImages.map((entry, i) => {
    const item = document.createElement("div");
    item.className = "agent-image-preview-item";
    const img = document.createElement("img");
    img.src = entry.data_url;
    img.alt = entry.name;
    const remove = document.createElement("button");
    remove.className = "agent-image-preview-remove";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${entry.name}`);
    remove.innerHTML = '<svg viewBox="0 0 10 10"><path d="M2 2l6 6M8 2l-6 6"/></svg>';
    remove.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removePendingImage(i);
    });
    item.append(img, remove);
    return item;
  });
  const summaryItems = summaryEntries.map((entry, i) => {
    const item = document.createElement("div");
    item.className = "agent-image-preview-item is-summary";
    const label = document.createElement("span");
    label.className = "agent-image-preview-file";
    label.textContent = entry.name;
    const meta = document.createElement("span");
    meta.className = "agent-image-preview-file-meta";
    meta.textContent = "summarized";
    const remove = document.createElement("button");
    remove.className = "agent-image-preview-remove";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${entry.name}`);
    remove.innerHTML = '<svg viewBox="0 0 10 10"><path d="M2 2l6 6M8 2l-6 6"/></svg>';
    remove.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removePendingAttachmentSummary(i);
    });
    item.append(label, meta, remove);
    return item;
  });
  preview.replaceChildren(...rawItems, ...summaryItems);
}

function imageCardSummary(image) {
  const card = image?.image_card && typeof image.image_card === "object" ? image.image_card : {};
  const evidence = Array.isArray(card.evidence) ? card.evidence.slice(0, 8) : [];
  const moduleResults = card.module_results && typeof card.module_results === "object" ? card.module_results : undefined;
  const analyzerModules = Array.isArray(card.analyzer_modules) ? card.analyzer_modules.slice(0, 8) : [];
  return {
    analyzer_revision: cleanText(card.analyzer_revision, ""),
    name: cleanText(card.name || image?.name, "image"),
    size: Number.isFinite(card.size) ? card.size : agentImagePayloadBytes(image),
    dimensions: cleanText(card.dimensions || (image?.width && image?.height ? `${image.width}x${image.height}` : ""), ""),
    palette: Array.isArray(card.palette) ? card.palette.slice(0, 5) : [],
    visual_notes: Array.isArray(card.visual_notes) ? card.visual_notes.slice(0, 10) : [],
    composition: card.composition && typeof card.composition === "object" ? card.composition : undefined,
    analysis: card.analysis && typeof card.analysis === "object" ? card.analysis : undefined,
    evidence,
    module_results: moduleResults,
    analyzer_modules: analyzerModules,
    local_url: String(card.local_url || image?.asset?.local_url || "").trim(),
    hash: String(card.hash || image?.asset?.hash || card.perceptual_hash || "").trim(),
  };
}

function agentImageCardPreview(images, attachments) {
  return JSON.stringify([...images, ...attachments].map(imageCardSummary), null, 2);
}

async function storeAgentImageAsset(entry, signal) {
  if (!entry?.data_url || entry.asset?.local_url) return entry;
  const payload = await fetchJson("/agent/attachments", {
    method: "POST",
    timeoutMs: 45000,
    signal,
    body: {
      image: {
        data_url: entry.data_url,
        name: entry.name,
        type: entry.type,
        size: entry.size,
        width: entry.width,
        height: entry.height,
        original_type: entry.original_type,
        original_size: entry.original_size,
        image_card: entry.image_card,
      },
    },
  });
  if (payload.asset) {
    entry.asset = payload.asset;
    entry.image_card = payload.asset.image_card || entry.image_card;
  }
  return entry;
}

async function storeAgentAttachmentAssets(images, attachments, pendingMessage) {
  const entries = [...images, ...attachments].filter((entry) => entry?.data_url);
  if (!entries.length) return { stored: 0, failed: 0 };
  let stored = 0;
  let failed = 0;
  for (const entry of entries) {
    try {
      await storeAgentImageAsset(entry, state.agentAbortController?.signal);
      stored += 1;
    } catch (error) {
      failed += 1;
      recordUserEvent("agent.image_store_error", {
        target: "agent-overlay",
        summary: `Could not store ${entry.name || "image"} locally`,
        data: { error: error.message },
      });
    }
    mergeAgentAction(pendingMessage, {
      id: "client_store_image_assets",
      kind: "media",
      label: "Store image assets",
      status: failed ? "error" : "running",
      detail: `${stored}/${entries.length} stored${failed ? ` / ${failed} failed` : ""}`,
      meta: "local store",
      preview: agentImageCardPreview(images, attachments),
    });
  }
  mergeAgentAction(pendingMessage, {
    id: "client_store_image_assets",
    kind: "media",
    label: "Store image assets",
    status: failed ? "error" : "done",
    detail: `${stored}/${entries.length} stored${failed ? ` / ${failed} failed` : ""}`,
    meta: "local store",
    preview: agentImageCardPreview(images, attachments),
  });
  return { stored, failed };
}

function updateAgentSendButton() {
  if (!els.agentSendButton) return;
  els.agentSendButton.classList.toggle("is-busy", state.agentBusy);
  els.agentSendButton.setAttribute("aria-label", state.agentBusy ? "Stop response" : "Send message");
  els.agentSendButton.title = state.agentBusy ? "Stop" : "Send";
}

function updateAgentTurnTimer() {
  if (!state.agentThinkingMessageId) return;
  const session = activeAgentSession();
  const message = session.messages.find((item) => item.id === state.agentThinkingMessageId);
  if (!message?.pending) return;
  const elapsed = Date.now() - Number(message.turn_started_at || Date.now());
  document.querySelectorAll(`.agent-turn-elapsed[data-message-id="${message.id}"]`).forEach((element) => {
    element.textContent = formatTurnElapsed(elapsed);
  });
}

function startAgentTurnTimer(message) {
  window.clearInterval(state.agentTurnTimer);
  state.agentThinkingMessageId = message?.id || "";
  updateAgentTurnTimer();
  state.agentTurnTimer = window.setInterval(updateAgentTurnTimer, 1000);
}

function stopAgentTurnTimer() {
  window.clearInterval(state.agentTurnTimer);
  state.agentTurnTimer = 0;
  state.agentThinkingMessageId = "";
}

function updateAgentPendingMessage(message, updates = {}) {
  if (!message) return;
  Object.assign(message, updates);
  saveAgentSessions();
  renderAgentMessages();
  els.agentMessages.scrollTop = els.agentMessages.scrollHeight;
}

function stopAgentMessage() {
  if (!state.agentBusy) return;
  state.agentStopRequested = true;
  state.agentAbortController?.abort();
}

function installDevHmrBridge() {
  window.__wasmAgentDevHmr = {
    requestReload(paths = []) {
      if (!state.agentBusy) return false;
      state.agentDeferredHmrReload = {
        paths: Array.isArray(paths) ? paths : [],
        requested_at: Date.now(),
      };
      const pendingMessage = activeAgentSession().messages.find((item) => item.id === state.agentThinkingMessageId);
      if (pendingMessage) {
        const actions = Array.isArray(pendingMessage.actions) ? [...pendingMessage.actions] : [];
        if (!actions.some((action) => action.id === "dev_hmr_deferred")) {
          const changedCount = state.agentDeferredHmrReload.paths.length || 1;
          actions.push({
            id: "dev_hmr_deferred",
            kind: "hmr",
            label: "Dev HMR update queued",
            status: "running",
            detail: `${changedCount} source change${changedCount === 1 ? "" : "s"}`,
            meta: "deferred",
            preview: state.agentDeferredHmrReload.paths.slice(0, 20).join("\n"),
          });
        }
        updateAgentPendingMessage(pendingMessage, { actions });
      }
      recordUserEvent("agent.hmr_deferred", {
        target: "agent-overlay",
        summary: "Deferred dev HMR until the embedded assistant turn finishes",
        data: { paths: state.agentDeferredHmrReload.paths.slice(0, 12) },
      });
      return true;
    },
  };
}

function flushDeferredHmrReload() {
  if (!state.agentDeferredHmrReload || state.agentBusy) return;
  const deferred = state.agentDeferredHmrReload;
  state.agentDeferredHmrReload = null;
  saveAgentSessions();
  window.setTimeout(() => {
    recordUserEvent("agent.hmr_reloading", {
      target: "agent-overlay",
      summary: "Applying deferred dev HMR reload",
      data: { paths: deferred.paths.slice(0, 12) },
    });
    window.location.reload();
  }, 240);
}

function shouldStartDevHmr() {
  return !window.__WASM_AGENT_DISABLE_HMR__ && (window.__WASM_AGENT_DISABLE_SW__ || isModuleEnabled("dev-hmr"));
}

function renderAgentContextPreview(items = []) {
  if (!els.agentContextPreview) return;
  if (!items.length) {
    els.agentContextPreview.textContent = "No context tools used yet.";
    return;
  }
  els.agentContextPreview.replaceChildren(
    ...items.map((item) => {
      const block = document.createElement("article");
      const title = document.createElement("strong");
      const meta = document.createElement("div");
      const preview = document.createElement("pre");
      title.textContent = item.tool || "tool";
      meta.className = "agent-context-meta";
      meta.textContent = [item.path, item.query ? `query: ${item.query}` : "", Number.isFinite(item.bytes) ? `${item.bytes} bytes` : ""]
        .filter(Boolean)
        .join(" / ");
      preview.textContent = item.preview || "";
      block.append(title, meta, preview);
      return block;
    })
  );
}

function setAgentBalloon(kind) {
  const sessionsOpen = kind === "sessions";
  const contextOpen = kind === "context";
  const settingsOpen = kind === "settings";
  if (els.agentSessionsBalloon) els.agentSessionsBalloon.hidden = !sessionsOpen;
  if (els.agentContextBalloon) els.agentContextBalloon.hidden = !contextOpen;
  if (els.agentSettingsBalloon) els.agentSettingsBalloon.hidden = !settingsOpen;
  els.agentSessionsButton?.setAttribute("aria-expanded", sessionsOpen ? "true" : "false");
  els.agentContextButton?.setAttribute("aria-expanded", contextOpen ? "true" : "false");
  els.agentSettingsButton?.setAttribute("aria-expanded", settingsOpen ? "true" : "false");
}

function toggleAgentBalloon(kind) {
  const target = kind === "sessions"
    ? els.agentSessionsBalloon
    : kind === "settings"
      ? els.agentSettingsBalloon
      : els.agentContextBalloon;
  setAgentBalloon(target?.hidden ? kind : "");
}

function applyAgentLayout() {
  state.agentLayout = clampAgentLayout(state.agentLayout);
  const { left, top } = state.agentLayout;
  if (Number.isFinite(left) && Number.isFinite(top)) {
    els.agentOverlay.style.left = `${left}px`;
    els.agentOverlay.style.top = `${top}px`;
    els.agentOverlay.style.right = "auto";
    els.agentOverlay.style.bottom = "auto";
  }
  placeAgentPanel();
}

function appViewportRect() {
  const viewport = window.visualViewport;
  if (viewport) {
    return {
      left: viewport.offsetLeft,
      top: viewport.offsetTop,
      right: viewport.offsetLeft + viewport.width,
      bottom: viewport.offsetTop + viewport.height,
      width: viewport.width,
      height: viewport.height,
    };
  }
  return els.app?.getBoundingClientRect?.() || {
    left: 0,
    top: 0,
    right: window.innerWidth,
    bottom: window.innerHeight,
    width: window.innerWidth,
    height: window.innerHeight,
  };
}

function defaultAgentLayout() {
  const appRect = appViewportRect();
  const { width, height } = agentAvatarSize();
  return {
    left: appRect.right - width - AGENT_AVATAR_VIEWPORT_GAP_PX,
    top: appRect.bottom - height - AGENT_AVATAR_VIEWPORT_GAP_PX,
  };
}

function agentAvatarSize() {
  const rect = els.agentAvatarButton?.getBoundingClientRect?.();
  return {
    width: Math.max(58, rect?.width || els.agentAvatarButton?.offsetWidth || 58),
    height: Math.max(58, rect?.height || els.agentAvatarButton?.offsetHeight || 58),
  };
}

function clampAgentLayout(layout) {
  const appRect = appViewportRect();
  const { width, height } = agentAvatarSize();
  const gap = AGENT_AVATAR_VIEWPORT_GAP_PX;
  const fallback = defaultAgentLayout();
  const fallbackLeft = fallback.left;
  const fallbackTop = fallback.top;
  const rawLeft = Number.isFinite(layout?.left) ? layout.left : fallbackLeft;
  const rawTop = Number.isFinite(layout?.top) ? layout.top : fallbackTop;
  const minLeft = appRect.left + gap;
  const maxLeft = Math.max(minLeft, appRect.right - width - gap);
  const minTop = appRect.top + gap;
  const maxTop = Math.max(minTop, appRect.bottom - height - gap);
  return {
    left: Math.max(minLeft, Math.min(maxLeft, rawLeft)),
    top: Math.max(minTop, Math.min(maxTop, rawTop)),
  };
}

function resetAgentToViewportCorner() {
  state.agentLayout = clampAgentLayout(defaultAgentLayout());
  els.agentOverlay.style.left = `${state.agentLayout.left}px`;
  els.agentOverlay.style.top = `${state.agentLayout.top}px`;
  els.agentOverlay.style.right = "auto";
  els.agentOverlay.style.bottom = "auto";
  state.agentPanelSide = "";
  placeAgentPanel();
}

function syncAgentAppBounds() {
  const rect = appViewportRect();
  els.agentOverlay.style.setProperty("--agent-app-width", `${Math.max(320, rect.width)}px`);
  els.agentOverlay.style.setProperty("--agent-app-height", `${Math.max(320, rect.height)}px`);
}

function placeAgentPanel() {
  const overlay = els.agentOverlay;
  const panel = els.agentPanel;
  if (!overlay || !panel) return;
  syncAgentAppBounds();
  if (!state.agentOpen) return;
  const gap = AGENT_PANEL_VIEWPORT_GAP_PX;
  const avatarGap = AGENT_PANEL_AVATAR_GAP_PX;
  const appRect = appViewportRect();
  const overlayRect = overlay.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const panelWidth = panelRect.width || 430;
  const panelHeight = panelRect.height || 620;
  const minLeft = appRect.left + gap;
  const maxLeft = Math.max(minLeft, appRect.right - panelWidth - gap);
  const minTop = appRect.top + gap;
  const maxTop = Math.max(minTop, appRect.bottom - panelHeight - gap);
  const leftSideLeft = overlayRect.left - panelWidth - avatarGap;
  const rightSideLeft = overlayRect.right + avatarGap;
  const leftFits = leftSideLeft >= minLeft;
  const rightFits = rightSideLeft <= maxLeft;
  let side = state.agentPanelSide || "left";
  if (side === "left" && !leftFits && rightFits) side = "right";
  if (side === "right" && !rightFits && leftFits) side = "left";
  if (!leftFits && !rightFits) side = overlayRect.left > appRect.left + appRect.width / 2 ? "left" : "right";
  state.agentPanelSide = side;
  const rawLeft = side === "right" ? rightSideLeft : leftSideLeft;
  const preferredTop = overlayRect.top + overlayRect.height / 2 - panelHeight / 2;
  const left = Math.max(minLeft, Math.min(maxLeft, rawLeft));
  const top = Math.max(minTop, Math.min(maxTop, preferredTop));
  panel.style.left = `${left - overlayRect.left}px`;
  panel.style.top = `${top - overlayRect.top}px`;
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  panel.dataset.y = top > preferredTop + 1 ? "lower" : top < preferredTop - 1 ? "upper" : "center";
  panel.dataset.x = side;
}

function moveAgentGroupFromPanelRect(panelLeft, panelTop, panelWidth, panelHeight) {
  const appRect = appViewportRect();
  const avatar = agentAvatarSize();
  const gap = AGENT_PANEL_AVATAR_GAP_PX;
  const minPanelLeft = appRect.left + AGENT_PANEL_VIEWPORT_GAP_PX;
  const maxPanelLeft = Math.max(minPanelLeft, appRect.right - panelWidth - AGENT_PANEL_VIEWPORT_GAP_PX);
  const minPanelTop = appRect.top + AGENT_PANEL_VIEWPORT_GAP_PX;
  const maxPanelTop = Math.max(minPanelTop, appRect.bottom - panelHeight - AGENT_PANEL_VIEWPORT_GAP_PX);
  const left = clamp(panelLeft, minPanelLeft, maxPanelLeft);
  const top = clamp(panelTop, minPanelTop, maxPanelTop);
  const avatarOnRight = left + panelWidth / 2 < appRect.left + appRect.width / 2;
  state.agentPanelSide = avatarOnRight ? "left" : "right";
  const overlayLeft = avatarOnRight ? left + panelWidth + gap : left - avatar.width - gap;
  const overlayTop = top + panelHeight / 2 - avatar.height / 2;
  state.agentLayout = clampAgentLayout({ left: overlayLeft, top: overlayTop });
  els.agentOverlay.style.left = `${state.agentLayout.left}px`;
  els.agentOverlay.style.top = `${state.agentLayout.top}px`;
  els.agentOverlay.style.right = "auto";
  els.agentOverlay.style.bottom = "auto";
  placeAgentPanel();
}

function installAgentDragging() {
  els.agentAvatarButton.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const start = els.agentOverlay.getBoundingClientRect();
    const offsetX = event.clientX - start.left;
    const offsetY = event.clientY - start.top;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    document.body.classList.add("is-agent-dragging");
    try {
      els.agentAvatarButton.setPointerCapture(event.pointerId);
    } catch {
      // Some browser/devtool reload states can drop capture; window listeners still carry the drag.
    }
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 3) moved = true;
      const { left, top } = clampAgentLayout({
        left: moveEvent.clientX - offsetX,
        top: moveEvent.clientY - offsetY,
      });
      els.agentOverlay.style.left = `${left}px`;
      els.agentOverlay.style.top = `${top}px`;
      els.agentOverlay.style.right = "auto";
      els.agentOverlay.style.bottom = "auto";
      state.agentLayout = { left, top };
      placeAgentPanel();
    };
    const end = () => {
      document.body.classList.remove("is-agent-dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      state.agentLayout = clampAgentLayout(state.agentLayout);
      els.agentOverlay.style.left = `${state.agentLayout.left}px`;
      els.agentOverlay.style.top = `${state.agentLayout.top}px`;
      placeAgentPanel();
      saveAgentLayout();
      if (moved) {
        state.agentDragSuppressClick = true;
        window.setTimeout(() => {
          state.agentDragSuppressClick = false;
        }, 0);
        recordUserEvent("agent.dragged", {
          target: "agent-overlay",
          summary: "Moved embedded assistant avatar",
          data: state.agentLayout,
        });
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  });
}

function installAgentPanelDragging() {
  const handle = els.agentPanel?.querySelector(".agent-panel-head");
  if (!handle) return;
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (event.target.closest("button,input,textarea,select,a")) return;
    event.preventDefault();
    const panelRect = els.agentPanel.getBoundingClientRect();
    const offsetX = event.clientX - panelRect.left;
    const offsetY = event.clientY - panelRect.top;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    document.body.classList.add("is-agent-dragging");
    try {
      handle.setPointerCapture(event.pointerId);
    } catch {
      // Window listeners below keep the drag alive if capture is interrupted.
    }
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 3) moved = true;
      moveAgentGroupFromPanelRect(
        moveEvent.clientX - offsetX,
        moveEvent.clientY - offsetY,
        els.agentPanel.offsetWidth || 430,
        els.agentPanel.offsetHeight || 620
      );
    };
    const end = () => {
      document.body.classList.remove("is-agent-dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      placeAgentPanel();
      saveAgentLayout();
      if (moved) {
        recordUserEvent("agent.dragged", {
          target: "agent-overlay",
          summary: "Moved embedded assistant avatar and chat together",
          data: state.agentLayout,
        });
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  });
}

async function sendAgentMessage(text) {
  if (state.agentBusy) {
    stopAgentMessage();
    return;
  }
  const content = cleanText(text, "");
  const attachmentCount = state.agentPendingImages.length + state.agentPendingAttachmentSummaries.length;
  if (!content && !attachmentCount) return;
  const userMessageContent = content || `Attached ${attachmentCount} image${attachmentCount === 1 ? "" : "s"}.`;
  state.agentBusy = true;
  state.agentStopRequested = false;
  state.agentAbortController = new AbortController();
  updateAgentTokenUsage(null);
  updateAgentSendButton();
  els.agentStatus.textContent = "Thinking";
  const targetNode = agentTargetNode();
  const turnStartedAt = Date.now();
  const mode = els.agentModeSelect.value;
  const userImages = state.agentPendingImages.map((image) => ({
    data_url: image.data_url,
    name: image.name,
    type: image.type,
    size: image.size,
    width: image.width,
    height: image.height,
    original_type: image.original_type,
    original_size: image.original_size,
    image_card: image.image_card,
    asset: image.asset,
  }));
  const userAttachments = state.agentPendingAttachmentSummaries.map((attachment) => ({
    data_url: attachment.data_url,
    name: attachment.name,
    type: attachment.type,
    size: attachment.size,
    width: attachment.width,
    height: attachment.height,
    original_type: attachment.original_type,
    original_size: attachment.original_size,
    image_card: attachment.image_card,
    asset: attachment.asset,
    reason: attachment.reason,
  }));
  const requestTranscript = agentTranscriptForRequest();
  clearAgentPendingImages();
  appendAgentMessage("user", userMessageContent, {
    images: userImages,
    attachments: userAttachments.map((attachment) => ({
      name: attachment.name,
      type: attachment.type,
      size: attachment.size,
      width: attachment.width,
      height: attachment.height,
      original_type: attachment.original_type,
      original_size: attachment.original_size,
      image_card: attachment.image_card,
      asset: attachment.asset,
      reason: attachment.reason,
    })),
  });
  els.agentInput.value = "";
  recordUserEvent("agent.message_submitted", {
    target: `node:${targetNode}`,
    summary: `Submitted embedded assistant message to ${targetNode}`,
    data: {
      message_length: userMessageContent.length,
      image_count: userImages.length,
      summarized_attachment_count: userAttachments.length,
      image_bytes: userImages.reduce((sum, image) => sum + (Number.isFinite(image.size) ? image.size : 0), 0),
      panel: state.activePanel,
      target_node: targetNode,
    },
    redacted: true,
  });
  try {
    const observation = buildObservationSnapshot();
    const compactObservation = {
      timestamp: observation.timestamp,
      workspace: observation.workspace,
      browser: observation.browser,
      fleet: {
        bridge_ready: observation.fleet.bridge_ready,
        selected_node: observation.fleet.selected_node,
        chat_target_node: targetNode,
        node_count: observation.fleet.node_count,
        last_error: observation.fleet.last_error,
      },
      tasks: {
        active_task_id: observation.tasks.active_task_id,
        status: observation.tasks.status,
        last_output_summary: observation.tasks.last_output_summary,
      },
      logs: observation.logs,
      requested_click_context: {
        last_non_agent_click: observation.analytics.last_non_agent_click,
        note: "Use last_non_agent_click, not chat open/send events, when the user asks what UI button they clicked last.",
      },
      recent_events: observation.user_events.slice(0, 12),
    };
    const transcript = requestTranscript;
    const imageBytes = userImages.reduce((sum, image) => sum + (Number.isFinite(image.size) ? image.size : 0), 0);
    const summarizedCount = userAttachments.length;
    const imageCards = [...userImages, ...userAttachments].map(imageCardSummary);
    const analyzerModules = Object.values(Object.fromEntries(
      imageCards
        .flatMap((card) => Array.isArray(card.analyzer_modules) ? card.analyzer_modules : [])
        .map((module) => [module.id, module])
    ));
    const initialActions = [
      agentAction("Prepare compact context", "done", `${transcript.length} transcript turns / ${compactObservation.recent_events.length} UI events`, {
        kind: "context",
        meta: "snapshot",
        arguments: {
          transcript_turns: transcript.length,
          recent_events: compactObservation.recent_events.length,
          active_panel: compactObservation.workspace?.active_panel,
          target_node: targetNode,
        },
        preview: JSON.stringify({
          workspace: compactObservation.workspace,
          requested_click_context: compactObservation.requested_click_context,
          recent_events: compactObservation.recent_events.slice(0, 3),
        }, null, 2),
      }),
      agentAction("Store image assets", attachmentCount ? "running" : "done", attachmentCount ? `${attachmentCount} queued` : "none", {
        id: "client_store_image_assets",
        kind: "media",
        meta: attachmentCount ? "local store" : "empty",
        arguments: attachmentCount ? { endpoint: "/agent/attachments", count: attachmentCount } : undefined,
      }),
      agentAction("Decode pixels", "done", attachmentCount ? `${imageCards.filter((card) => card.dimensions).length}/${attachmentCount} decoded` : "none", {
        id: "client_decode_pixels",
        kind: "media",
        meta: "Canvas",
      }),
      agentAction("Analyze image", "done", attachmentCount ? `${imageCards.length} local image cards` : "none", {
        id: "client_analyze_image",
        kind: "media",
        meta: "browser + lazy modules",
        arguments: attachmentCount
          ? {
              raw_images: userImages.length,
              summarized: summarizedCount,
              raw_budget_bytes: AGENT_IMAGE_TOTAL_MAX_BYTES,
              raw_bytes: imageBytes,
              analyzer_modules: analyzerModules,
            }
          : undefined,
      }),
      agentAction("Build image cards", "done", attachmentCount ? `${imageCards.length} cards` : "none", {
        id: "client_build_image_cards",
        kind: "media",
        meta: attachmentCount ? `${Math.round(imageBytes / 1024)} KB raw` : "empty",
        preview: attachmentCount ? JSON.stringify(imageCards, null, 2) : "",
      }),
      agentAction(`Ask ${targetNode}`, "running", "POST /agent/session/message", {
        id: "client_ask_orchestrator",
        kind: "model",
        meta: mode,
        arguments: { endpoint: "/agent/session/message", mode, target_node: targetNode },
      }),
    ];
    const pendingMessage = appendAgentMessage("assistant", `Waiting for ${targetNode}...`, {
      pending: true,
      phase: "Inspecting context",
      target_node: targetNode,
      mode,
      turn_started_at: turnStartedAt,
      actions: initialActions,
    });
    startAgentTurnTimer(pendingMessage);
    await storeAgentAttachmentAssets(userImages, userAttachments, pendingMessage);
    els.agentStatus.textContent = "Inspecting context";
    updateAgentPendingMessage(pendingMessage, {
      phase: "Waiting for node",
      content: `Waiting for ${targetNode}...`,
      actions: (pendingMessage.actions || initialActions).map((action) => action.id === "client_ask_orchestrator" ? { ...action, status: "running" } : action),
    });
    const payloadAttachments = userAttachments.map((attachment) => ({
      name: attachment.name,
      type: attachment.type,
      size: attachment.size,
      width: attachment.width,
      height: attachment.height,
      original_type: attachment.original_type,
      original_size: attachment.original_size,
      image_card: attachment.image_card,
      asset: attachment.asset,
      reason: attachment.reason,
    }));
    const payload = await postAgentMessage({
      session_id: activeAgentSession().id,
      message: userMessageContent,
      images: userImages.length ? userImages : undefined,
      attachments: payloadAttachments.length ? payloadAttachments : undefined,
      mode,
      target_node: targetNode,
      space_id: activeSpaceStorageId(),
      observation: compactObservation,
      transcript,
    }, pendingMessage, {
      timeoutMs: state.agentTurnTimeoutMs + 5000,
      signal: state.agentAbortController.signal,
    });
    const reply = payload.agent?.reply || "I did not receive a response from the embedded agent adapter.";
    const session = activeAgentSession();
    const changedFiles = payload.agent?.changed_files || [];
    pendingMessage.content = reply;
    pendingMessage.pending = false;
    pendingMessage.phase = "";
    pendingMessage.duration_ms = payload.agent?.duration_ms || Date.now() - turnStartedAt;
    pendingMessage.changed_files = changedFiles;
    pendingMessage.actions = agentActionRowsFromPayload(payload.agent, initialActions);
    session.diagnostics = payload.agent?.diagnostics || {};
    updateAgentTokenUsage(payload.agent?.diagnostics?.token_usage || null);
    session.changed_files = changedFiles;
    session.context_preview = payload.agent?.context_preview || [];
    saveAgentSessions();
    renderAgentDiagnostics(payload.agent?.diagnostics || {});
    renderAgentContextPreview(payload.agent?.context_preview || []);
    renderAgentMessages();
    els.agentMessages.scrollTop = els.agentMessages.scrollHeight;
    recordUserEvent("agent.message_finished", {
      target: "agent-overlay",
      summary: "Embedded assistant replied",
      data: { reply_length: reply.length, diagnostics: payload.agent?.diagnostics || {} },
    });
  } catch (error) {
    const timeoutSeconds = Math.round(state.agentTurnTimeoutMs / 1000);
    const message = error.name === "AbortError"
      ? state.agentStopRequested
        ? "Stopped the embedded assistant turn."
        : `The selected node did not answer within ${formatTurnElapsed(timeoutSeconds * 1000)}. I received your message, but the bridge-backed path was too slow for this turn. You can switch to Local mode for quick workspace inspection, choose another node, or check the bridge/model backend.`
      : `I could not reach the embedded chat adapter yet: ${error.message}`;
    const pendingMessage = activeAgentSession().messages.find((item) => item.id === state.agentThinkingMessageId);
    if (pendingMessage) {
      pendingMessage.content = message;
      pendingMessage.pending = false;
      pendingMessage.phase = state.agentStopRequested ? "Stopped" : "Timed out";
      pendingMessage.duration_ms = Date.now() - Number(pendingMessage.turn_started_at || turnStartedAt);
      pendingMessage.actions = (pendingMessage.actions || []).map((action) => (
        action.status === "running" ? { ...action, status: state.agentStopRequested ? "done" : "error", detail: error.message } : action
      ));
      saveAgentSessions();
      renderAgentMessages();
    } else {
      appendAgentMessage("assistant", message, {
        phase: state.agentStopRequested ? "Stopped" : "Error",
        duration_ms: Date.now() - turnStartedAt,
        actions: [agentAction("Adapter request", state.agentStopRequested ? "done" : "error", error.message, {
          kind: "error",
          meta: error.name || "request",
        })],
      });
    }
    renderAgentDiagnostics({ source: "error", target_node: targetNode, duration_ms: null, tools: [], context_estimated_tokens: 0 });
    recordUserEvent("agent.message_error", {
      target: "agent-overlay",
      summary: "Embedded assistant message failed",
      data: { error: error.message },
    });
  } finally {
    state.agentBusy = false;
    state.agentAbortController = null;
    state.agentStopRequested = false;
    stopAgentTurnTimer();
    updateAgentSendButton();
    els.agentStatus.textContent = "Ready";
    flushDeferredHmrReload();
  }
}

function normalizeNode(raw) {
  const id = cleanText(raw.id || raw.node_id || raw.title, "unknown");
  const activity = raw.activity || {};
  const running = Boolean(raw.running || raw.status === "running" || raw.status === "working");
  const status = cleanText(activity.state || raw.status || (running ? "running" : "stopped"), "unknown");
  const statusKey = status.toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  const statusClass = /error|fail|missing|unhealthy/.test(statusKey)
    ? "error"
    : /stop|exit|down|offline/.test(statusKey)
      ? "stopped"
      : running || /work|run|active|ready|idle|online|healthy/.test(statusKey)
        ? statusKey || "running"
        : "unknown";
  const runtime = cleanText(raw.runtime?.type || raw.raw?.runtime_type, "runtime");
  const modelOverride = nodeModelOverride(id);
  const overriddenModel = formatNodeModel(modelOverride.name, modelOverride.provider);
  return {
    raw,
    id,
    title: cleanText(raw.title || id, id),
    running,
    status,
    statusClass,
    runtime,
    model: cleanText(overriddenModel || activity.model, ""),
    modelOverride,
    taskPreview: cleanText(activity.task_preview, ""),
    actions: Array.isArray(raw.actions) ? raw.actions : [],
  };
}

function taskPreview(task) {
  const response = task?.result?.response || task?.error?.message || task?.prompt || "";
  return String(response).replace(/\s+/g, " ").slice(0, 150);
}

async function refresh(origin = "auto") {
  if (!isAdminUser()) {
    state.bridgeReady = false;
    state.nodes = [];
    state.tasks = [];
    state.securityLoop = null;
    state.securityFindings = [];
    renderAll();
    return;
  }
  const startedAt = performance.now();
  try {
    await bridgeJson("/health");
    state.bridgeReady = true;
    state.lastError = "";

    const [nodes, tasks] = await Promise.all([
      bridgeJson("/nodes").catch(() => ({ nodes: [] })),
      bridgeJson("/tasks").catch(() => ({ tasks: [] })),
    ]);
    state.nodes = (nodes.nodes || []).map(normalizeNode);
    state.tasks = tasks.tasks || [];
    if (!state.resourceInterval && (resourcesWidgetIsOpen() || !["auto", "startup"].includes(origin))) {
      await loadResources(origin).catch(() => {});
    }
    if (state.nodes.length && !state.nodes.some((node) => node.id === state.selectedNode)) {
      state.selectedNode = state.nodes[0].id;
    }
    await loadSecurityLoop(origin).catch(() => {});
    renderAll();
    if (origin !== "auto") {
      recordUserEvent("workspace.refresh_finished", {
        target: "bridge",
        summary: `Refreshed ${state.nodes.length} nodes and ${state.tasks.length} tasks`,
        data: { origin, node_count: state.nodes.length, task_count: state.tasks.length, bridge_ready: state.bridgeReady },
        duration_ms: performance.now() - startedAt,
      });
    }
  } catch (error) {
    state.bridgeReady = false;
    state.lastError = error.message;
    await loadSecurityLoop(origin).catch(() => {});
    renderAll();
    recordUserEvent("workspace.refresh_error", {
      target: "bridge",
      summary: error.message,
      data: { origin, error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    renderAppLayer();
    syncResourcePolling();
    syncSecurityPolling();
  }
}

async function loadResources(origin = "auto") {
  try {
    const payload = await bridgeJson("/resources");
    state.resources = payload.resources || null;
    renderResources();
    if (origin !== "poll") {
      recordUserEvent("resources.loaded", {
        target: "resources",
        summary: state.resources?.timestamp ? `Loaded resources ${state.resources.timestamp}` : "Loaded resources",
        data: { origin, timestamp: state.resources?.timestamp || "" },
      });
    }
  } catch (error) {
    state.lastError = error.message;
    if (!state.resources) renderResources();
    if (origin !== "poll") {
      recordUserEvent("resources.load_error", {
        target: "resources",
        summary: error.message,
        data: { origin, error: error.message },
      });
    }
    throw error;
  }
}

function resourcesWidgetIsOpen() {
  const widget = widgetById("resources");
  return Boolean(state.authUser && widget && !widget.hidden && !widget.classList.contains("is-minimized"));
}

function securityLoopIsOpen() {
  const widget = widgetById("security-loop");
  return Boolean(isAdminUser() && (
    state.activePanel === "security"
    || (widget && !widget.hidden && !widget.classList.contains("is-minimized"))
  ));
}

function syncSecurityPolling() {
  if (securityLoopIsOpen()) {
    if (!state.securityInterval) {
      state.securityInterval = window.setInterval(() => void loadSecurityLoop("poll").catch(() => {}), SECURITY_POLL_MS);
      void loadSecurityLoop("open").catch(() => {});
    }
    return;
  }
  if (state.securityInterval) {
    window.clearInterval(state.securityInterval);
    state.securityInterval = 0;
  }
}

function syncResourcePolling() {
  if (resourcesWidgetIsOpen()) {
    if (!state.resourceInterval) {
      state.resourceInterval = window.setInterval(() => void loadResources("poll").catch(() => {}), RESOURCE_POLL_MS);
      void loadResources("open").catch(() => {});
    }
    return;
  }
  if (state.resourceInterval) {
    window.clearInterval(state.resourceInterval);
    state.resourceInterval = 0;
  }
}

function devicesPageIsOpen() {
  return Boolean(els.devicesModal && !els.devicesModal.hidden);
}

async function loadDevices(origin = "auto") {
  if (state.devicesBusy) return;
  state.devicesBusy = true;
  renderDevices();
  try {
    const payload = await fetchJson("/account/devices", { timeoutMs: 8000 });
    state.devices = Array.isArray(payload.devices) ? payload.devices : [];
    state.deviceAuthority = {
      current_device_id: payload.current_device_id || "",
      main_device_id: payload.main_device_id || "",
      main_device_online: Boolean(payload.main_device_online),
      layout_policy: "client-local",
    };
    state.devicesLoadedAt = payload.timestamp || new Date().toISOString();
    renderDevices();
    if (origin !== "poll") {
      recordUserEvent("account.devices_loaded", {
        target: "devices",
        summary: `Loaded ${state.devices.length} connected devices`,
        data: { origin, count: state.devices.length },
      });
    }
  } catch (error) {
    if (els.devicesStatus) {
      els.devicesStatus.textContent = "offline";
      els.devicesStatus.className = "widget-chip err";
    }
    recordUserEvent("account.devices_load_error", {
      target: "devices",
      summary: error.message,
      data: { origin, error: error.message },
    });
  } finally {
    state.devicesBusy = false;
    renderDevices();
  }
}

function renderDevices() {
  if (!els.devicesList || !els.devicesStatus) return;
  if (els.devicesSyncButton) {
    els.devicesSyncButton.disabled = !state.authUser || Boolean(state.deviceSyncBusy);
    els.devicesSyncButton.classList.toggle("is-busy", Boolean(state.deviceSyncBusy));
  }
  if (state.devicesBusy && !state.devices.length) {
    els.devicesStatus.textContent = "loading";
    els.devicesStatus.className = "widget-chip";
    els.devicesList.replaceChildren(metric("Devices", "Loading"));
    return;
  }
  els.devicesStatus.textContent = state.devices.length ? `${state.devices.length}` : "account";
  els.devicesStatus.className = `widget-chip ${state.devices.length ? "ok" : ""}`;
  if (!state.devices.length) {
    els.devicesList.replaceChildren(metric("Devices", state.authUser ? "No devices yet" : "Sign in required"));
    return;
  }
  els.devicesList.replaceChildren(
    ...state.devices.map((device) => {
      const card = document.createElement("article");
      card.className = `device-card${device.current ? " current" : ""}`;
      const icon = document.createElement("span");
      icon.className = `device-os-icon ${deviceOsClass(device)}`;
      icon.textContent = deviceOsGlyph(device);
      icon.title = deviceOsLabel(device);
      icon.setAttribute("aria-hidden", "true");
      const copy = document.createElement("div");
      copy.className = "device-card-copy";
      const title = document.createElement("strong");
      title.textContent = cleanText(device.label, "Device");
      const meta = document.createElement("span");
      const flags = [
        device.current ? "Current" : "",
        device.main ? "Main" : "",
        cleanText(device.reachability, ""),
      ].filter(Boolean);
      meta.textContent = flags.length ? flags.join(" / ") : cleanText(device.last_seen_display, device.last_seen || "");
      const detail = document.createElement("p");
      detail.textContent = cleanText(device.user_agent, device.id);
      const main = document.createElement("button");
      main.className = "device-main-button icon-button";
      main.type = "button";
      main.title = device.main ? "Main device" : `Make ${cleanText(device.label, "device")} the main device`;
      main.setAttribute("aria-label", main.title);
      main.disabled = !state.authUser || Boolean(device.main) || state.deviceMainBusy === device.id;
      main.classList.toggle("active", Boolean(device.main));
      main.classList.toggle("is-busy", state.deviceMainBusy === device.id);
      main.addEventListener("click", (event) => {
        event.stopPropagation();
        void setMainDevice(device);
      });
      const sync = document.createElement("button");
      sync.className = "device-sync-button icon-button";
      sync.type = "button";
      sync.title = `Download sync installer for ${cleanText(device.label, "device")}`;
      sync.setAttribute("aria-label", `Download sync installer for ${cleanText(device.label, "device")}`);
      sync.disabled = !state.authUser || state.deviceSyncBusy === device.id;
      sync.addEventListener("click", (event) => {
        event.stopPropagation();
        void syncDevice(device);
      });
      copy.append(title, meta, detail);
      card.append(icon, copy, main, sync);
      return card;
    })
  );
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function syncDevice(device = null) {
  const target = device || state.devices.find((item) => item.current) || state.devices[0] || null;
  if (!target || state.deviceSyncBusy) return;
  state.deviceSyncBusy = target.id;
  renderDevices();
  try {
    const payload = await fetchJson("/account/devices/sync", {
      method: "POST",
      timeoutMs: 8000,
      body: { device_id: target.id },
    });
    downloadJson(`wasm-agent-sync-${target.id}.json`, payload.package || payload);
    recordUserEvent("account.device_sync_package_downloaded", {
      target: `device:${target.id}`,
      summary: `Downloaded sync installer for ${cleanText(target.label, "device")}`,
      data: { device_id: target.id, current: Boolean(target.current), package_schema: payload.package?.schema || "" },
    });
    void loadDevices("sync").catch(() => {});
  } catch (error) {
    recordUserEvent("account.device_sync_error", {
      target: `device:${target.id}`,
      summary: error.message,
      data: { device_id: target.id, error: error.message },
    });
  } finally {
    state.deviceSyncBusy = "";
    renderDevices();
  }
}

async function setMainDevice(device = null) {
  if (!device || !device.id || state.deviceMainBusy) return;
  state.deviceMainBusy = device.id;
  renderDevices();
  try {
    const payload = await fetchJson("/account/devices/main", {
      method: "POST",
      timeoutMs: 8000,
      body: { device_id: device.id },
    });
    state.devices = Array.isArray(payload.devices) ? payload.devices : state.devices;
    state.deviceAuthority = {
      current_device_id: payload.current_device_id || "",
      main_device_id: payload.main_device_id || device.id,
      main_device_online: Boolean(payload.main_device_online),
      layout_policy: "client-local",
    };
    recordUserEvent("account.main_device_changed", {
      target: `device:${device.id}`,
      summary: `Main device switched to ${cleanText(device.label, "device")}`,
      data: { device_id: device.id, current: Boolean(device.current) },
    });
  } catch (error) {
    recordUserEvent("account.main_device_error", {
      target: `device:${device.id}`,
      summary: error.message,
      data: { device_id: device.id, error: error.message },
    });
  } finally {
    state.deviceMainBusy = "";
    renderDevices();
  }
}

function deviceOsLabel(device) {
  const text = `${device?.label || ""} ${device?.user_agent || ""}`.toLowerCase();
  if (text.includes("android")) return "Android";
  if (text.includes("iphone") || text.includes("ipad") || text.includes(" ios")) return "iOS";
  if (text.includes("mac os") || text.includes("macintosh") || text.includes("macos")) return "macOS";
  if (text.includes("windows")) return "Windows";
  if (text.includes("linux")) return "Linux";
  return "Device";
}

function deviceOsClass(device) {
  return `os-${deviceOsLabel(device).toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function deviceOsGlyph(device) {
  return {
    Android: "An",
    iOS: "iO",
    macOS: "Ma",
    Windows: "Wi",
    Linux: "Li",
    Device: "De",
  }[deviceOsLabel(device)] || "De";
}

function metric(label, value, barValue = null) {
  const item = document.createElement("div");
  item.className = "metric";
  const labelEl = document.createElement("div");
  labelEl.className = "metric-label";
  labelEl.textContent = label;
  const valueEl = document.createElement("div");
  valueEl.className = "metric-value";
  valueEl.textContent = value;
  item.append(labelEl, valueEl);
  if (barValue !== null) {
    const bar = document.createElement("div");
    bar.className = "metric-bar";
    const fill = document.createElement("span");
    fill.style.width = `${percent(barValue)}%`;
    bar.append(fill);
    item.append(bar);
  }
  return item;
}

function renderResources() {
  const res = state.resources;
  els.resourceGrid.replaceChildren();
  if (!res) {
    els.resourceFreshness.textContent = state.bridgeReady ? "partial" : "offline";
    els.resourceFreshness.title = "";
    els.resourceFreshness.className = `widget-chip ${state.bridgeReady ? "" : "err"}`;
    els.resourceGrid.append(
      metric("Bridge", state.bridgeReady ? "Online" : "Offline"),
      metric("WASM", state.wasmReady ? "Ready" : "Pending"),
      metric("Host", "No data"),
      metric("Runtime", "Shadow")
    );
    return;
  }

  els.resourceFreshness.textContent = "live";
  els.resourceFreshness.title = cleanText(res.timestamp, "live").replace("T", " ").replace("Z", "");
  els.resourceFreshness.className = "widget-chip ok";
  const totalNodes = state.nodes.length;
  const runningNodes = state.nodes.filter((node) => node.running).length;
  const memoryTotal = Number(res.memory?.total_bytes || 0);
  const memoryUsed = Number(res.memory?.used_bytes || 0);
  const diskTotal = Number(res.disk?.total_bytes || 0);
  const diskUsed = Number(res.disk?.used_bytes || 0);
  els.resourceGrid.append(
    metric("Nodes", `${runningNodes}/${totalNodes}`, totalNodes ? (runningNodes / totalNodes) * 100 : 0),
    metric("Disk", `${compactGb(diskUsed)}/${compactGb(diskTotal)}`, res.disk?.percent),
    metric("RAM", `${compactGb(memoryUsed)}/${compactGb(memoryTotal)}`, res.memory?.percent),
    metric("CPU", `${cleanText(res.cpu?.percent, "0")}%`, res.cpu?.percent),
    metric("Processes", cleanText(res.processes?.count, "0")),
    metric("Uptime", cleanText(res.uptime?.display, "-"))
  );
}

function topologyNodePositions() {
  const layout = widgetLayout("topology");
  layout.nodePositions = layout.nodePositions && typeof layout.nodePositions === "object" ? layout.nodePositions : {};
  return layout.nodePositions;
}

function nodePosition(node, index, total) {
  const saved = topologyNodePositions()[node.id];
  if (saved && Number.isFinite(saved.leftPct) && Number.isFinite(saved.topPct)) {
    return { left: `${saved.leftPct * 100}%`, top: `${saved.topPct * 100}%`, transform: "translate(-50%, -50%)" };
  }
  if (index === 0) return { left: "50%", top: "48%", transform: "translate(-50%, -50%)" };
  const radiusX = 33;
  const radiusY = 29;
  const angle = -Math.PI / 2 + ((index - 1) / Math.max(1, total - 1)) * Math.PI * 2;
  return {
    left: `${50 + Math.cos(angle) * radiusX}%`,
    top: `${49 + Math.sin(angle) * radiusY}%`,
    transform: "translate(-50%, -50%)",
  };
}

function installTopologyNodeDragging(button, node) {
  const surface = els.topologyNodes;
  if (!surface) return;
  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const surfaceRect = surface.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    button.setPointerCapture(event.pointerId);
    const move = (moveEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 4) moved = true;
      const left = clamp(moveEvent.clientX - surfaceRect.left, button.offsetWidth / 2, surfaceRect.width - button.offsetWidth / 2);
      const top = clamp(moveEvent.clientY - surfaceRect.top, button.offsetHeight / 2, surfaceRect.height - button.offsetHeight / 2);
      button.style.left = `${left}px`;
      button.style.top = `${top}px`;
      button.style.transform = "translate(-50%, -50%)";
    };
    const end = (endEvent) => {
      button.removeEventListener("pointermove", move);
      button.removeEventListener("pointerup", end);
      button.removeEventListener("pointercancel", end);
      if (moved) {
        const left = parseFloat(button.style.left || "0");
        const top = parseFloat(button.style.top || "0");
        topologyNodePositions()[node.id] = {
          leftPct: left / Math.max(1, surfaceRect.width),
          topPct: top / Math.max(1, surfaceRect.height),
        };
        saveWidgetLayout();
        button.dataset.dragMoved = "true";
        window.setTimeout(() => {
          button.dataset.dragMoved = "";
        }, 0);
        endEvent.preventDefault();
        endEvent.stopPropagation();
        recordUserEvent("fleet.topology_node_moved", {
          target: `node:${node.id}`,
          summary: `Moved topology node ${node.id}`,
          data: { node_id: node.id, ...topologyNodePositions()[node.id] },
        });
      }
    };
    button.addEventListener("pointermove", move);
    button.addEventListener("pointerup", end, { once: true });
    button.addEventListener("pointercancel", end, { once: true });
  });
}

function renderTopology() {
  const nodes = state.nodes.length ? state.nodes : [normalizeNode({ id: "orchestrator", status: "unknown" })];
  els.selectedNode.textContent = state.selectedNode;
  els.topologyNodes.replaceChildren(
    ...nodes.map((node, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `topology-node${node.id === state.selectedNode ? " active" : ""}`;
      Object.assign(button.style, nodePosition(node, index, nodes.length));
      button.addEventListener("click", (event) => {
        if (button.dataset.dragMoved === "true") {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        selectNode(node.id);
      });
      button.addEventListener("contextmenu", (event) => showNodeContextMenu(node, event));
      installLongPressMenu(button, (event) => showNodeContextMenu(node, event));
      installTopologyNodeDragging(button, node);

      const title = document.createElement("div");
      title.className = "node-title";
      const strong = document.createElement("strong");
      strong.textContent = node.title;
      const dot = document.createElement("span");
      dot.className = `state-dot ${node.statusClass}`;
      title.append(strong, dot);

      const runtime = document.createElement("div");
      runtime.className = "node-meta";
      runtime.textContent = `${node.status} / ${node.runtime}`;

      const model = document.createElement("div");
      model.className = "node-meta";
      model.textContent = node.model || "Hermes runtime";

      button.append(title, runtime, model);
      return button;
    })
  );
}

function nodeById(nodeId) {
  return state.nodes.find((node) => node.id === nodeId) || null;
}

function nodeModelOverrides() {
  const layout = widgetLayout("topology");
  layout.nodeModels = layout.nodeModels && typeof layout.nodeModels === "object" ? layout.nodeModels : {};
  return layout.nodeModels;
}

function nodeModelOverride(nodeId) {
  const override = nodeModelOverrides()[nodeId];
  return override && typeof override === "object" ? override : {};
}

function formatNodeModel(name, provider) {
  const modelName = cleanText(name, "");
  const modelProvider = cleanText(provider, "");
  if (modelName && modelProvider) return `${modelProvider}/${modelName}`;
  return modelName || modelProvider || "";
}

function hideNodeContextMenu(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("node-menu")) return;
  state.activeNodeMenuId = "";
  if (els.nodeContextMenu) els.nodeContextMenu.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("node-menu", { skipHistory: true, replaceHistory: true });
  }
}

function positionNodeContextMenu(event) {
  if (!els.nodeContextMenu) return;
  els.nodeContextMenu.hidden = false;
  const rect = els.nodeContextMenu.getBoundingClientRect();
  const gap = 8;
  const maxLeft = window.innerWidth - rect.width - gap;
  const maxTop = window.innerHeight - rect.height - gap;
  const left = Math.max(gap, Math.min(maxLeft, event.clientX));
  const top = Math.max(gap, Math.min(maxTop, event.clientY));
  els.nodeContextMenu.style.left = `${left}px`;
  els.nodeContextMenu.style.top = `${top}px`;
}

function nodeContextActions(node) {
  const preferred = ["restart_node", "start_node", "stop_node", "update_node"];
  const aliases = {
    restart_node: ["restart_node", "restart"],
    start_node: ["start_node", "start"],
    stop_node: ["stop_node", "stop"],
    update_node: ["update_node", "update"],
  };
  return preferred.map((name) => {
    const action = node.actions.find((item) => (aliases[name] || [name]).includes(item.action));
    return action || {
      id: `${node.id}:${name}`,
      action: name,
      label: name.replace("_node", ""),
      endpoint: `/nodes/${encodeURIComponent(node.id)}/action`,
      method: "POST",
      payload_template: { action: name, payload: {} },
      enabled: true,
      destructive: name !== "start_node",
    };
  });
}

function showNodeContextMenu(node, event) {
  event.preventDefault();
  event.stopPropagation();
  if (!els.nodeContextMenu) return;
  state.activeNodeMenuId = node.id;
  selectNode(node.id);
  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.setAttribute("role", "menuitem");
  editButton.textContent = "Edit";
  editButton.addEventListener("click", (clickEvent) => {
    clickEvent.stopPropagation();
    hideNodeContextMenu({ skipHistory: true, replaceHistory: true });
    openNodeEditModal(node.id);
  });
  els.nodeContextMenu.replaceChildren(
    editButton,
    ...nodeContextActions(node).map((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "menuitem");
      button.className = action.destructive ? "danger" : "";
      button.textContent = actionLabel(action);
      button.disabled = action.enabled === false || state.actionBusy === action.id;
      button.title = action.disabled_reason || `${actionLabel(action)} ${node.id}`;
      button.addEventListener("click", (clickEvent) => {
        clickEvent.stopPropagation();
        hideNodeContextMenu({ skipHistory: true, replaceHistory: true });
        void runNodeAction(nodeById(node.id) || node, action);
      });
      return button;
    })
  );
  positionNodeContextMenu(event);
  pushUiNavigationLayer("node-menu", () => hideNodeContextMenu({ skipHistory: true, skipStack: true }));
  recordUserEvent("fleet.node_context_menu_requested", {
    target: `node:${node.id}`,
    summary: `Opened actions for ${node.id}`,
    data: { node_id: node.id },
  });
}

function openNodeEditModal(nodeId = state.activeNodeMenuId) {
  const node = nodeById(nodeId) || normalizeNode({ id: nodeId, status: "unknown" });
  if (!node?.id || !els.nodeEditModal) return;
  hideNodeContextMenu({ skipHistory: true, replaceHistory: true });
  state.activeNodeEditId = node.id;
  const override = nodeModelOverride(node.id);
  if (els.nodeEditModalTitle) els.nodeEditModalTitle.textContent = `Edit ${node.title}`;
  if (els.nodeEditModalMeta) els.nodeEditModalMeta.textContent = node.id;
  const [provider = "", name = ""] = node.model && node.model.includes("/")
    ? node.model.split("/", 2)
    : ["", node.model || ""];
  if (els.nodeEditModelNameInput) els.nodeEditModelNameInput.value = cleanText(override.name, name);
  if (els.nodeEditModelProviderInput) els.nodeEditModelProviderInput.value = cleanText(override.provider, provider);
  els.nodeEditModal.hidden = false;
  pushUiNavigationLayer("node-edit-modal", () => closeNodeEditModal({ skipHistory: true, skipStack: true }));
  recordUserEvent("fleet.node_edit_opened", {
    target: `node:${node.id}`,
    summary: `Opened editor for ${node.id}`,
    data: { node_id: node.id },
  });
}

function closeNodeEditModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("node-edit-modal")) return;
  if (els.nodeEditModal) els.nodeEditModal.hidden = true;
  state.activeNodeEditId = "";
  if (!options.skipStack) {
    closeUiNavigationLayer("node-edit-modal", { skipHistory: true, replaceHistory: true });
  }
}

function saveNodeEdit(event) {
  event?.preventDefault();
  const nodeId = state.activeNodeEditId;
  if (!nodeId) return;
  const name = cleanText(els.nodeEditModelNameInput?.value, "").slice(0, 96);
  const provider = cleanText(els.nodeEditModelProviderInput?.value, "").slice(0, 64);
  nodeModelOverrides()[nodeId] = { name, provider };
  saveWidgetLayout();
  state.nodes = state.nodes.map((node) => (node.id === nodeId ? normalizeNode(node.raw || node) : node));
  renderTopology();
  renderNodeList();
  closeNodeEditModal({ skipHistory: true, replaceHistory: true });
  recordUserEvent("fleet.node_edit_saved", {
    target: `node:${nodeId}`,
    summary: `Saved model for ${nodeId}`,
    data: { node_id: nodeId, model_name: name, provider },
  });
}

function resetNodeEdit() {
  const nodeId = state.activeNodeEditId;
  if (!nodeId) return;
  delete nodeModelOverrides()[nodeId];
  saveWidgetLayout();
  state.nodes = state.nodes.map((node) => (node.id === nodeId ? normalizeNode(node.raw || node) : node));
  renderTopology();
  renderNodeList();
  openNodeEditModal(nodeId);
  recordUserEvent("fleet.node_edit_reset", {
    target: `node:${nodeId}`,
    summary: `Reset model for ${nodeId}`,
    data: { node_id: nodeId },
  });
}

function renderNodeList() {
  const nodes = state.nodes.length ? state.nodes : [normalizeNode({ id: "orchestrator", status: "unknown" })];
  els.nodeList.replaceChildren(
    ...nodes.map((node) => {
      const card = document.createElement("article");
      card.className = `node-card${node.id === state.selectedNode ? " active" : ""}`;
      card.tabIndex = 0;
      card.addEventListener("click", () => selectNode(node.id));
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode(node.id);
        }
      });
      const title = document.createElement("strong");
      title.textContent = node.title;
      const meta = document.createElement("div");
      meta.className = "node-meta";
      meta.textContent = `${node.status} / ${node.runtime}`;
      const preview = document.createElement("div");
      preview.className = "node-meta";
      preview.textContent = node.taskPreview || "No active task preview";
      card.append(title, meta, preview, renderNodeActions(node));
      return card;
    })
  );
}

function actionLabel(action) {
  return cleanText(action.label || action.action, "Action");
}

function visibleNodeActions(node) {
  const aliases = {
    start_node: ["start_node", "start"],
    stop_node: ["stop_node", "stop"],
    restart_node: ["restart_node", "restart"],
    update_node: ["update_node", "update"],
  };
  const preferred = ["start_node", "stop_node", "restart_node", "update_node"];
  return preferred
    .map((name) => {
      const names = aliases[name] || [name];
      return node.actions.find((action) => names.includes(action.action)) || {
        id: `${node.id}:${name}`,
        action: name,
        label: name.replace("_node", "").replace("_", " "),
        endpoint: `/nodes/${encodeURIComponent(node.id)}/action`,
        method: "POST",
        payload_template: { action: name, payload: {} },
        enabled: true,
        destructive: name !== "start_node",
      };
    })
    .filter(Boolean);
}

function addNodeFromTopology() {
  const name = window.prompt("Node name");
  if (!name) return;
  const nodeId = name.trim();
  if (!nodeId) return;
  recordUserEvent("fleet.node_add_requested", {
    target: "topology:add-node",
    summary: `Requested node ${nodeId}`,
    data: { node_id: nodeId },
  });
  void bridgeJson("/nodes", {
    method: "POST",
    body: { id: nodeId, name: nodeId, start: true },
  }).then(() => refresh("manual")).catch((error) => {
    state.lastError = error.message;
    renderTaskOutput({ action: "add_node", node_id: nodeId, error: error.message });
  });
}

function renderNodeActions(node) {
  const wrap = document.createElement("div");
  wrap.className = "node-actions";
  const actions = visibleNodeActions(node);
  if (!actions.length) {
    const chip = document.createElement("span");
    chip.className = "node-action-note";
    chip.textContent = "No bridge actions";
    wrap.append(chip);
    return wrap;
  }
  actions.forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `node-action${action.destructive ? " danger" : ""}`;
    button.textContent = actionLabel(action);
    button.disabled = action.enabled === false || state.actionBusy === action.id;
    button.title = action.disabled_reason || `${actionLabel(action)} ${node.id}`;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      void runNodeAction(node, action);
    });
    wrap.append(button);
  });
  return wrap;
}

function renderTasks() {
  const tasks = state.tasks.slice(0, 8);
  els.taskList.replaceChildren();
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "task-card";
    empty.innerHTML = "<strong>No recent tasks</strong><div class=\"task-meta\">Bridge has no task history yet</div>";
    els.taskList.append(empty);
    return;
  }
  els.taskList.replaceChildren(
    ...tasks.map((task) => {
      const card = document.createElement("div");
      card.className = "task-card";
      const title = document.createElement("strong");
      title.textContent = cleanText(task.task_id || task.id, "task");
      const meta = document.createElement("div");
      meta.className = "task-meta";
      meta.textContent = `${cleanText(task.status, "unknown")} / ${cleanText(task.target_node, "node")}`;
      const preview = document.createElement("div");
      preview.className = "task-meta";
      preview.textContent = taskPreview(task);
      card.append(title, meta, preview);
      return card;
    })
  );
}

function sortedSecurityFindings() {
  return [...state.securityFindings].sort((a, b) => {
    const scoreDelta = Number(b.score || 0) - Number(a.score || 0);
    if (scoreDelta) return scoreDelta;
    return String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""));
  });
}

function securityStatusClass(status) {
  const value = String(status || "new").toLowerCase();
  if (["accepted", "mitigating", "new", "triaged"].includes(value)) return "warn";
  if (value === "resolved") return "ok";
  if (value === "rejected") return "muted";
  return "";
}

function securitySeverityClass(severity) {
  const value = String(severity || "low").toLowerCase();
  if (value === "critical") return "critical";
  if (value === "high") return "high";
  if (value === "medium") return "medium";
  return "low";
}

function renderSecuritySummary(container, loop = state.securityLoop) {
  if (!container) return;
  if (!isAdminUser()) {
    container.replaceChildren(metric("Security", "Admin only"));
    return;
  }
  if (!loop) {
    container.replaceChildren(
      metric("Attack", "hermes-attack"),
      metric("Defense", "hermes-defense"),
      metric("Findings", "pending"),
      metric("Freshness", "unknown")
    );
    return;
  }
  container.replaceChildren(
    metric("Attack", loop.actors?.attack || "hermes-attack"),
    metric("Defense", loop.actors?.defense || "hermes-defense"),
    metric("Open", String(loop.open_count || 0)),
    metric("Critical", String(loop.critical_count || 0)),
    metric("Accepted", String(loop.accepted_count || 0)),
    metric("Rejected", String(loop.rejected_count || 0)),
    metric("Top score", String(loop.top_score || 0)),
    metric("Latest", loop.latest_run_at ? loop.latest_run_at.replace("T", " ").replace("Z", "") : "none"),
    metric("Freshness", loop.stale ? "stale" : "live")
  );
}

function securityFindingById(findingId) {
  return state.securityFindings.find((finding) => finding.id === findingId) || null;
}

function securityFindingCard(finding, options = {}) {
  const card = document.createElement("article");
  card.className = `security-finding-card ${securitySeverityClass(finding.severity)}`;
  const head = document.createElement("div");
  head.className = "security-finding-head";
  const title = document.createElement("strong");
  title.textContent = finding.summary || "Security finding";
  const score = document.createElement("span");
  score.className = "security-score";
  score.textContent = String(finding.score || 0).padStart(2, "0");
  head.append(title, score);

  const meta = document.createElement("div");
  meta.className = "security-finding-meta";
  [
    finding.updated_at || finding.created_at || "time",
    finding.source_node || "hermes-attack",
    finding.target_surface || "surface",
    finding.category || "probe",
    finding.severity || "low",
    `conf ${Math.round(Number(finding.confidence || 0) * 100)}%`,
  ].forEach((value) => {
    const chip = document.createElement("span");
    chip.textContent = value;
    meta.append(chip);
  });

  const status = document.createElement("span");
  status.className = `security-status ${securityStatusClass(finding.status)}`;
  status.textContent = finding.status || "new";
  meta.append(status);

  const preview = document.createElement("p");
  preview.className = "security-evidence-preview";
  preview.textContent = truncateText(finding.evidence_preview || "No evidence preview supplied.", 220);

  const proposed = document.createElement("p");
  proposed.className = "security-proposed-action";
  proposed.textContent = truncateText(finding.proposed_action || "No proposed defense action yet.", 220);

  const actions = document.createElement("div");
  actions.className = "security-actions";
  const actionButtons = [
    ["accepted", "Accept"],
    ["rejected", "Reject"],
    ["resolved", "Mark Resolved"],
    ["watching", "Watch"],
  ];
  actionButtons.forEach(([nextStatus, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = state.securityBusy || finding.status === nextStatus;
    if (nextStatus === "rejected") button.className = "danger";
    button.addEventListener("click", () => void decideSecurityFinding(finding.id, nextStatus));
    actions.append(button);
  });

  const evidenceButton = document.createElement("button");
  evidenceButton.type = "button";
  evidenceButton.textContent = "Open Evidence";
  evidenceButton.addEventListener("click", () => openSecurityEvidenceModal(finding.id));
  actions.append(evidenceButton);

  if (finding.task_id) {
    const taskButton = document.createElement("button");
    taskButton.type = "button";
    taskButton.textContent = "Open Task";
    taskButton.addEventListener("click", () => openSecurityTask(finding.task_id));
    actions.append(taskButton);
  }

  const defenseButton = document.createElement("button");
  defenseButton.type = "button";
  defenseButton.textContent = options.compact ? "Ask Defense" : "Ask hermes-defense";
  defenseButton.addEventListener("click", () => askDefenseForFinding(finding, "mitigation"));
  actions.append(defenseButton);

  const planButton = document.createElement("button");
  planButton.type = "button";
  planButton.textContent = "Create PR Plan";
  planButton.addEventListener("click", () => askDefenseForFinding(finding, "pr-plan"));
  actions.append(planButton);

  card.append(head, meta, preview, proposed, actions);
  return card;
}

function renderSecurityQueue(container, options = {}) {
  if (!container) return;
  if (!isAdminUser()) {
    container.replaceChildren();
    return;
  }
  const findings = sortedSecurityFindings().slice(0, options.limit || 20);
  if (!findings.length) {
    const empty = document.createElement("article");
    empty.className = "security-finding-card empty";
    empty.innerHTML = "<strong>No findings yet</strong><p class=\"security-evidence-preview\">hermes-attack has not reported bounded probe findings.</p>";
    container.replaceChildren(empty);
    return;
  }
  container.replaceChildren(...findings.map((finding) => securityFindingCard(finding, options)));
}

function renderSecurityLoop() {
  const loop = state.securityLoop;
  const statusText = !isAdminUser()
    ? "admin"
    : loop?.stale
      ? "stale"
      : loop
        ? "live"
        : "pending";
  [els.securityLoopStatus, els.securityPanelStatus].forEach((chip) => {
    if (!chip) return;
    chip.textContent = statusText;
    chip.className = `widget-chip ${statusText === "live" ? "ok" : statusText === "stale" ? "err" : ""}`;
  });
  renderSecuritySummary(els.securityLoopSummary, loop);
  renderSecuritySummary(els.securityPanelSummary, loop);
  renderSecurityQueue(els.securityFindingQueue, { limit: 12, compact: false });
  renderSecurityQueue(els.securityPanelFindingQueue, { limit: 20, compact: true });
}

function renderRoleVisibility() {
  const admin = isAdminUser();
  document.querySelectorAll(".panel-tab").forEach((button) => {
    const panel = button.dataset.panel;
    if (!panel) return;
    button.hidden = isAdminPanel(panel) && !admin;
  });
  document.querySelectorAll(".widget[data-widget-id]").forEach((widget) => {
    const widgetId = widget.dataset.widgetId || "";
    const adminOnlyWidget = ["resources", "topology", "studio", "browser-proof", "drop-to-copy", "security-loop", "timeline"].includes(widgetId);
    if (adminOnlyWidget && !admin) widget.hidden = true;
  });
  if (!admin && isAdminPanel(state.activePanel)) setPanel("home");
}

async function loadSecurityLoop(origin = "auto") {
  if (!isAdminUser() || state.securityBusy) return;
  state.securityBusy = true;
  if (els.securityRefreshButton) els.securityRefreshButton.disabled = true;
  try {
    const payload = await fetchJson("/security-loop/findings?limit=80", { timeoutMs: 10000 });
    state.securityLoop = payload.security_loop || null;
    state.securityFindings = Array.isArray(payload.findings) ? payload.findings : [];
    renderSecurityLoop();
    if (origin === "manual") {
      recordUserEvent("security.loop_loaded", {
        target: "security-loop",
        summary: `Loaded ${state.securityFindings.length} security findings`,
        data: { finding_count: state.securityFindings.length, open_count: state.securityLoop?.open_count || 0 },
      });
    }
  } catch (error) {
    state.lastError = error.message;
    renderSecurityLoop();
    if (origin !== "auto") {
      recordUserEvent("security.loop_error", {
        target: "security-loop",
        summary: error.message,
        data: { error: error.message },
      });
    }
  } finally {
    state.securityBusy = false;
    if (els.securityRefreshButton) els.securityRefreshButton.disabled = false;
  }
}

async function decideSecurityFinding(findingId, status) {
  if (!SECURITY_FINDING_STATUSES.includes(status)) return;
  state.securityBusy = true;
  renderSecurityLoop();
  try {
    const payload = await fetchJson(`/security-loop/findings/${encodeURIComponent(findingId)}/decision`, {
      method: "POST",
      timeoutMs: 10000,
      body: { status },
    });
    const nextFinding = payload.finding;
    state.securityLoop = payload.security_loop || state.securityLoop;
    state.securityFindings = state.securityFindings.map((finding) => finding.id === findingId ? nextFinding : finding);
    renderSecurityLoop();
    if (state.securityEvidenceId === findingId) renderSecurityEvidenceModal();
    recordUserEvent("security.finding_decided", {
      target: `security:${findingId}`,
      summary: `${status} ${findingId}`,
      data: { finding_id: findingId, status },
    });
  } catch (error) {
    state.lastError = error.message;
  } finally {
    state.securityBusy = false;
    renderSecurityLoop();
  }
}

function openSecurityEvidenceModal(findingId) {
  state.securityEvidenceId = findingId;
  renderSecurityEvidenceModal();
  if (els.securityEvidenceModal) els.securityEvidenceModal.hidden = false;
  pushUiNavigationLayer("security-evidence-modal", () => closeSecurityEvidenceModal({ skipHistory: true, skipStack: true }));
}

function closeSecurityEvidenceModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("security-evidence-modal")) return;
  if (els.securityEvidenceModal) els.securityEvidenceModal.hidden = true;
  state.securityEvidenceId = "";
  if (!options.skipStack) {
    closeUiNavigationLayer("security-evidence-modal", { skipHistory: true, replaceHistory: true });
  }
}

function renderSecurityEvidenceModal() {
  const finding = securityFindingById(state.securityEvidenceId);
  if (!finding || !els.securityEvidenceBody) return;
  if (els.securityEvidenceTitle) els.securityEvidenceTitle.textContent = finding.summary || finding.id;
  if (els.securityEvidenceMeta) {
    els.securityEvidenceMeta.textContent = `${finding.source_node || "hermes-attack"} / ${finding.target_surface || "surface"} / score ${finding.score || 0}`;
  }
  const rows = [
    ["Status", finding.status],
    ["Severity", finding.severity],
    ["Confidence", `${Math.round(Number(finding.confidence || 0) * 100)}%`],
    ["Exploitability", `${Math.round(Number(finding.exploitability || 0) * 100)}%`],
    ["Category", finding.category],
    ["Task", finding.task_id || "none"],
    ["Proposed Action", finding.proposed_action || "none"],
    ["Decision", finding.decision_reason || "none"],
  ];
  const grid = document.createElement("div");
  grid.className = "security-evidence-grid";
  rows.forEach(([label, value]) => {
    grid.append(metric(label, cleanText(value, "-")));
  });
  const evidence = document.createElement("pre");
  evidence.textContent = finding.evidence_preview || "No evidence preview supplied.";
  els.securityEvidenceBody.replaceChildren(grid, evidence);
}

function openSecurityTask(taskId) {
  if (!taskId) return;
  setPanel("tasks");
  const task = state.tasks.find((item) => String(item.task_id || item.id || "") === String(taskId));
  renderTaskOutput(task || { task_id: taskId, status: "linked", message: "Refresh Tasks to load this bridge task." });
}

function defensePromptForFinding(finding, mode) {
  const ask = mode === "pr-plan"
    ? "Create a PR-ready remediation plan with tests, rollback, and exact files to inspect. Do not apply changes."
    : "Propose a bounded mitigation, verification steps, and any tests needed. Do not apply changes.";
  return [
    ask,
    "",
    `Finding: ${finding.summary || finding.id}`,
    `Severity: ${finding.severity}; confidence: ${finding.confidence}; score: ${finding.score}`,
    `Surface: ${finding.target_surface}; category: ${finding.category}`,
    `Evidence: ${finding.evidence_preview || "none"}`,
    `Proposed action: ${finding.proposed_action || "none"}`,
  ].join("\n");
}

function askDefenseForFinding(finding, mode = "mitigation") {
  if (!finding) return;
  setPanel("tasks");
  state.selectedNode = "hermes-defense";
  renderTaskOutput({ action: mode, status: "submitting", node_id: "hermes-defense", finding_id: finding.id });
  void submitTask(defensePromptForFinding(finding, mode));
}

function renderTaskOutput(task = null) {
  if (task) {
    els.taskOutput.textContent = JSON.stringify(task, null, 2);
    return;
  }
  const latest = state.tasks[0];
  if (latest) {
    els.taskOutput.textContent = `${cleanText(latest.status, "task")}\n${taskPreview(latest)}`;
  } else if (state.lastError) {
    els.taskOutput.textContent = state.lastError;
  } else {
    els.taskOutput.textContent = "Ready";
  }
}

function renderBrowserCapture(capture = null) {
  if (capture) {
    state.browserCapture = capture;
    state.browserSessionId = capture.sessionId || state.browserSessionId;
  }
  const current = state.browserCapture;
  if (!current) return;
  els.browserImage.src = current.image || "";
  els.browserImage.parentElement.classList.toggle("has-image", Boolean(current.image));
  els.browserImage.parentElement.classList.toggle("has-canvas", false);
  const stableStatus = state.browserLive && current.status !== "error" ? "live" : current.status || "captured";
  els.browserStatus.textContent = stableStatus === "screenshot" ? "live" : stableStatus;
  els.browserStatus.className = `widget-chip ${current.status === "error" ? "err" : "ok"}`;
  els.browserMeta.textContent = current.meta || current.url || "Remote Chromium capture";
}

function browserViewportSize() {
  const rect = els.browserScreen.getBoundingClientRect();
  return {
    width: Math.max(360, Math.min(1920, Math.round(rect.width || 1280))),
    height: Math.max(240, Math.min(1400, Math.round(rect.height || 800))),
  };
}

function browserStreamUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/browser/stream`;
}

function browserUrlHost(url) {
  try {
    return new URL(normalizeBrowserUrl(url)).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function sameBrowserDestination(a, b) {
  const hostA = browserUrlHost(a);
  const hostB = browserUrlHost(b);
  return Boolean(hostA && hostB && hostA === hostB);
}

function browserAddressValue() {
  return state.browserUrlDirty ? state.browserUrlDraft : els.browserUrlInput.value;
}

function setBrowserUrlInput(url, { force = false } = {}) {
  if (!url) return;
  if (state.browserPendingUrl) {
    if (!sameBrowserDestination(url, state.browserPendingUrl)) return;
    state.browserPendingUrl = "";
    force = true;
  }
  if (!force && (document.activeElement === els.browserUrlInput || state.browserUrlDirty)) return;
  state.browserUrlDirty = false;
  state.browserUrlDraft = url;
  els.browserUrlInput.value = url;
}

function isBrowserStreamOpen() {
  return state.browserSocket && state.browserSocket.readyState === WebSocket.OPEN;
}

function closeBrowserStream({ silent = false } = {}) {
  const socket = state.browserSocket;
  state.browserSocket = null;
  state.browserStreamToken += 1;
  window.clearTimeout(state.browserResizeTimer);
  if (socket && socket.readyState <= WebSocket.OPEN) {
    try {
      socket.close(1000, "client closing stream");
    } catch {
      // The socket is already going away.
    }
  }
  state.browserLive = false;
  recordUserEvent("browser.stream_closed", {
    target: "browser-proof",
    summary: silent ? "Browser stream closed silently" : "Browser stream stopped",
    data: { silent, had_socket: Boolean(socket), frame_count: state.browserFrameCount },
  });
  if (!silent) {
    setBrowserLiveButton();
    els.browserStatus.textContent = state.browserCapture ? "captured" : "pixels";
    els.browserStatus.className = "widget-chip";
    if (state.browserCapture) els.browserMeta.textContent = "Stream stopped; last frame remains in the widget.";
  }
}

function drawBrowserFrame(message) {
  const width = Number(message.width || state.browserCapture?.width || 1280);
  const height = Number(message.height || state.browserCapture?.height || 800);
  const frame = Number(message.frame || state.browserFrameCount + 1);
  state.browserFrameCount = Math.max(state.browserFrameCount, frame);
  state.browserSessionId = message.stream_id || state.browserSessionId;
  state.browserCapture = {
    width,
    height,
    url: message.url || state.browserCapture?.url || "",
    sessionId: state.browserSessionId,
    status: "stream",
    meta: `${message.url || "Host Chromium"} / ${width}x${height} / stream frame ${frame}`,
  };
  if (frame === 1 || frame % 12 === 0 || message.mode === "host_chromium_cdp_snapshot") {
    recordUserEvent("browser.frame_received", {
      target: "browser-proof",
      summary: `Browser frame ${frame} from ${browserUrlHost(message.url) || "unknown"}`,
      data: {
        url: message.url,
        frame,
        width,
        height,
        mode: message.mode || "host_chromium_cdp_screencast",
      },
    });
  }
  const canvas = els.browserCanvas;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const image = new Image();
  image.onload = () => {
    if (frame < state.browserFrameCount) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0, width, height);
    els.browserScreen.classList.add("has-canvas");
    els.browserScreen.classList.remove("has-image", "is-busy");
    els.browserStatus.textContent = "stream";
    els.browserStatus.className = "widget-chip ok";
    els.browserMeta.textContent = state.browserCapture.meta;
  };
  image.src = message.image;
}

function handleBrowserStreamMessage(message) {
  if (message.type === "ready") {
    state.browserSessionId = message.stream_id || "";
    state.browserCapture = {
      width: message.width,
      height: message.height,
      url: message.url,
      sessionId: state.browserSessionId,
      status: "stream",
      meta: `${message.url} / ${message.width}x${message.height} / websocket stream`,
    };
    setBrowserUrlInput(message.url);
    els.browserStatus.textContent = "streaming";
    els.browserStatus.className = "widget-chip ok";
    els.browserMeta.textContent = state.browserCapture.meta;
    recordUserEvent("browser.stream_ready", {
      target: "browser-proof",
      summary: `Browser stream ready for ${message.url}`,
      data: { url: message.url, width: message.width, height: message.height, mode: message.mode },
    });
    return;
  }
  if (message.type === "frame") {
    if (state.browserPendingUrl && !sameBrowserDestination(message.url, state.browserPendingUrl)) return;
    drawBrowserFrame(message);
    setBrowserUrlInput(message.url);
    return;
  }
  if (message.type === "state") {
    if (message.url) {
      setBrowserUrlInput(message.url);
      if (state.browserCapture) state.browserCapture.url = message.url;
    }
    if (message.status === "navigating") {
      els.browserScreen.classList.add("is-busy");
      els.browserStatus.textContent = "navigating";
      els.browserStatus.className = "widget-chip ok";
      els.browserMeta.textContent = `Navigating to ${message.url || "new page"}...`;
      recordUserEvent("browser.navigation_started", {
        target: "browser-proof",
        summary: `Navigating to ${message.url || "new page"}`,
        data: { url: message.url, stream_id: message.stream_id },
      });
    }
    return;
  }
  if (message.type === "ack") {
    els.browserStatus.textContent = "stream";
    els.browserStatus.className = "widget-chip ok";
    setBrowserUrlInput(message.url);
    if (message.action) {
      recordUserEvent("browser.action_ack", {
        target: "browser-proof",
        summary: `${message.action} acknowledged`,
        data: { action: message.action, url: message.url, stream_id: message.stream_id },
      });
    }
    return;
  }
  if (message.type === "error") {
    renderBrowserCapture({
      image: "",
      url: state.browserCapture?.url || els.browserUrlInput.value,
      sessionId: state.browserSessionId,
      status: "error",
      meta: message.message || "Browser stream error",
    });
    recordUserEvent("browser.stream_error", {
      target: "browser-proof",
      summary: message.message || "Browser stream error",
      data: { error: message.message, code: message.code },
    });
  }
}

function openBrowserStream(targetUrl) {
  if (!("WebSocket" in window)) return Promise.reject(new Error("WebSocket is not available in this browser."));
  closeBrowserStream({ silent: true });
  const viewport = browserViewportSize();
  const token = state.browserStreamToken + 1;
  state.browserStreamToken = token;
  state.browserFrameCount = 0;
  state.browserLive = true;
  const startedAt = performance.now();
  recordUserEvent("browser.stream_open_started", {
    target: "browser-proof",
    summary: `Opening browser stream for ${targetUrl}`,
    data: { url: targetUrl, viewport },
  });
  setBrowserLiveButton();
  els.browserScreen.classList.add("is-busy");
  els.browserScreen.classList.remove("has-image", "has-canvas");
  els.browserImage.src = "";

  return new Promise((resolve, reject) => {
    const socket = new WebSocket(browserStreamUrl());
    state.browserSocket = socket;
    let settled = false;
    const timeout = window.setTimeout(() => fail(new Error("Browser stream timed out before the first frame.")), 10000);

    const cleanup = () => {
      window.clearTimeout(timeout);
      els.browserScreen.classList.remove("is-busy");
      setBrowserLiveButton();
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (state.browserSocket === socket) state.browserSocket = null;
      try {
        socket.close();
      } catch {
        // The socket may not have completed its handshake yet.
      }
      reject(error);
      recordUserEvent("browser.stream_open_error", {
        target: "browser-proof",
        summary: error.message,
        data: { url: targetUrl, error: error.message },
        duration_ms: performance.now() - startedAt,
      });
    };
    const succeed = (message) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(message);
      recordUserEvent("browser.stream_open_finished", {
        target: "browser-proof",
        summary: `Browser stream opened ${targetUrl}`,
        data: { url: targetUrl, first_frame_url: message.url, frame: message.frame },
        duration_ms: performance.now() - startedAt,
      });
    };

    socket.addEventListener("open", () => {
      if (state.browserStreamToken !== token) return;
      socket.send(JSON.stringify({ type: "open", url: targetUrl, ...viewport }));
      els.browserStatus.textContent = "streaming";
      els.browserStatus.className = "widget-chip ok";
      els.browserMeta.textContent = `Opening ${targetUrl} as a host Chromium stream...`;
    });
    socket.addEventListener("message", (event) => {
      if (state.browserStreamToken !== token) return;
      let message = {};
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "error") {
        fail(new Error(message.message || "Browser stream failed."));
        return;
      }
      handleBrowserStreamMessage(message);
      if (message.type === "frame") succeed(message);
    });
    socket.addEventListener("error", () => fail(new Error("Browser stream websocket failed.")));
    socket.addEventListener("close", () => {
      if (state.browserStreamToken !== token) return;
      if (!settled) {
        fail(new Error("Browser stream closed before the first frame."));
        return;
      }
      if (state.browserSocket === socket) state.browserSocket = null;
      state.browserLive = false;
      setBrowserLiveButton();
      if (state.browserCapture?.status !== "error") {
        els.browserStatus.textContent = "closed";
        els.browserStatus.className = "widget-chip";
        els.browserMeta.textContent = "Stream closed; last frame remains in the widget.";
      }
    });
  });
}

function sendBrowserStreamAction(action, payload = {}) {
  if (!isBrowserStreamOpen()) return false;
  state.browserSocket.send(JSON.stringify({ type: "input", action, ...payload }));
  recordUserEvent(action === "navigate" ? "browser.navigation_requested" : "browser.input_forwarded", {
    target: "browser-proof",
    summary: action === "navigate" ? `Navigate to ${payload.url}` : `Forwarded ${action}`,
    data: {
      action,
      url: payload.url,
      x: payload.x,
      y: payload.y,
      delta_x: payload.delta_x,
      delta_y: payload.delta_y,
      key: payload.key,
      text_length: payload.text ? String(payload.text).length : undefined,
      text_preview: payload.text ? truncateText(payload.text, 24) : undefined,
    },
    redacted: Boolean(payload.text),
  });
  els.browserStatus.textContent = action === "navigate" ? "navigating" : "stream";
  els.browserStatus.className = "widget-chip ok";
  if (action === "navigate" && payload.url) {
    els.browserScreen.classList.add("is-busy");
    els.browserScreen.classList.remove("has-image", "has-canvas");
    els.browserImage.src = "";
    els.browserMeta.textContent = `Navigating to ${payload.url}...`;
  }
  return true;
}

function scheduleBrowserResizeSync() {
  if (!isBrowserStreamOpen()) return;
  window.clearTimeout(state.browserResizeTimer);
  state.browserResizeTimer = window.setTimeout(() => {
    const viewport = browserViewportSize();
    recordUserEvent("browser.resize_synced", {
      target: "browser-proof",
      summary: `Synced browser viewport ${viewport.width}x${viewport.height}`,
      data: viewport,
    });
    sendBrowserStreamAction("resize", viewport);
  }, 140);
}

function renderAll() {
  renderRoleVisibility();
  els.runtimeLabel.textContent = state.wasmReady ? `wasm add=${state.wasm.add(19, 23)}` : "wasm pending";
  renderSpaceTitle();
  renderSpaceLauncher();
  renderAppLayer();
  renderResources();
  renderDevices();
  renderTopology();
  renderNodeList();
  renderTasks();
  renderTaskOutput();
  renderTimeline();
  renderObservation();
  renderModules();
  renderSecurityLoop();
  renderAgentNodeSelect();
  renderLogin();
  renderRoleVisibility();
  syncSecurityPolling();
  if (els.configModal && !els.configModal.hidden) renderConfigModal();
  if (els.artifactsModal && !els.artifactsModal.hidden) renderArtifacts();
  if (devicesPageIsOpen()) renderDevices();
}

function artifactCard(title, meta, items = []) {
  const card = document.createElement("article");
  card.className = "artifact-card";
  const head = document.createElement("div");
  head.className = "artifact-card-head";
  const name = document.createElement("strong");
  name.textContent = title;
  const info = document.createElement("span");
  info.textContent = meta;
  head.append(name, info);
  const list = document.createElement("div");
  list.className = "artifact-card-items";
  list.replaceChildren(...items.map((item) => {
    const row = document.createElement("span");
    row.textContent = item;
    return row;
  }));
  card.append(head, list);
  return card;
}

function renderArtifacts() {
  if (!els.artifactList) return;
  const spaceItems = [
    "space-home",
    "space-admin",
    ...state.userSpaces.map((space) => `${space.title} (${space.id})`),
  ];
  const appItems = SPACE_APP_DEFINITIONS.map((app) => {
    const scopes = Object.entries(SPACE_APP_MAPPINGS)
      .filter(([, ids]) => ids.includes(app.id))
      .map(([scope]) => scope)
      .join("/");
    return `${app.label} -> ${scopes || "unmapped"}`;
  });
  const layoutItems = [
    "positions: browser-local",
    "widget geometry: browser-local",
    `space density: browser-local, 1x-${CANVAS_DENSITY_MAX}x`,
  ];
  els.artifactList.replaceChildren(
    artifactCard("spaces/", `${spaceItems.length} local`, spaceItems),
    artifactCard("apps-widgets/", `${appItems.length} mapped`, appItems),
    artifactCard("browser-layouts/", "not retained server-side", layoutItems)
  );
}

function mainDeviceCanEvolve() {
  return !state.deviceAuthority || state.deviceAuthority.main_device_online !== false;
}

function ensureMainDeviceForEvolution(action = "evolve artifacts") {
  if (mainDeviceCanEvolve()) return true;
  openDevicesModal({ origin: "main-device-required", skipHistory: true });
  recordUserEvent("account.main_device_required", {
    target: "devices",
    summary: "Main device is offline",
    data: {
      action,
      main_device_id: state.deviceAuthority?.main_device_id || "",
      current_device_id: state.deviceAuthority?.current_device_id || "",
    },
  });
  window.alert("Main device is offline. Switch the main device from Connected Devices to evolve artifacts here.");
  return false;
}

function openDevicesModal(options = {}) {
  setPanel("home", { updateUrl: false });
  renderDevices();
  if (els.devicesModal) els.devicesModal.hidden = false;
  if (!options.skipHistory) {
    pushUiNavigationLayer("devices-modal", () => closeDevicesModal({ skipHistory: true, skipStack: true }));
  }
  if (!state.devicesBusy) void loadDevices(options.origin || "devices-page").catch(() => {});
  recordUserEvent("home.devices_opened", {
    target: "home:devices",
    summary: "Opened connected devices",
  });
}

function closeDevicesModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("devices-modal")) return;
  if (els.devicesModal) els.devicesModal.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("devices-modal", { skipHistory: true, replaceHistory: true });
  }
}

function openArtifactsModal() {
  renderArtifacts();
  if (els.artifactsModal) els.artifactsModal.hidden = false;
  pushUiNavigationLayer("artifacts-modal", () => closeArtifactsModal({ skipHistory: true, skipStack: true }));
  recordUserEvent("workspace.artifacts_opened", {
    target: "artifacts",
    summary: "Opened local artifact inventory",
    data: { spaces: state.userSpaces.length, apps: SPACE_APP_DEFINITIONS.length },
  });
}

function closeArtifactsModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("artifacts-modal")) return;
  if (els.artifactsModal) els.artifactsModal.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("artifacts-modal", { skipHistory: true, replaceHistory: true });
  }
}

function userSpaceInitial(title) {
  const text = cleanText(title, "S");
  return text.slice(0, 1).toUpperCase();
}

function userSpaceById(spaceId) {
  return state.userSpaces.find((space) => space.id === spaceId) || null;
}

function activeSpaceTitle(panel = state.activePanel) {
  panel = normalizePanel(panel);
  if (panel === "home") return "space-home";
  if (isAdminPanel(panel)) return "space-admin";
  const space = userSpaceById(panel);
  return cleanText(space?.title || panel, panel);
}

function renderSpaceTitle() {
  if (els.spaceLabel) els.spaceLabel.textContent = activeSpaceTitle();
  if (els.configModalSpaceName) els.configModalSpaceName.textContent = activeSpaceTitle();
}

function hideSpaceContextMenu(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("space-menu")) return;
  state.activeSpaceMenuId = "";
  if (els.spaceContextMenu) els.spaceContextMenu.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("space-menu", { skipHistory: true, replaceHistory: true });
  }
}

function positionSpaceContextMenu(event) {
  if (!els.spaceContextMenu) return;
  els.spaceContextMenu.hidden = false;
  const rect = els.spaceContextMenu.getBoundingClientRect();
  const gap = 8;
  const maxLeft = window.innerWidth - rect.width - gap;
  const maxTop = window.innerHeight - rect.height - gap;
  const left = Math.max(gap, Math.min(maxLeft, event.clientX));
  const top = Math.max(gap, Math.min(maxTop, event.clientY));
  els.spaceContextMenu.style.left = `${left}px`;
  els.spaceContextMenu.style.top = `${top}px`;
}

function showSpaceContextMenu(space, event) {
  event.preventDefault();
  event.stopPropagation();
  state.activeSpaceMenuId = space.id;
  positionSpaceContextMenu(event);
  pushUiNavigationLayer("space-menu", () => hideSpaceContextMenu({ skipHistory: true, skipStack: true }));
  recordUserEvent("workspace.context_menu_requested", {
    target: `space:${space.id}`,
    summary: `Opened menu for ${space.title}`,
    data: {
      button: event.button,
      panel: state.activePanel,
      space_id: space.id,
      space_title: space.title,
      target: describeEventTarget(event.target),
    },
  });
}

function createAdminCrownIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("space-launch-crown");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  const crown = document.createElementNS("http://www.w3.org/2000/svg", "path");
  crown.setAttribute("d", "M3 6l5 5 4-7 4 7 5-5-3 12H6L3 6Z");

  const base = document.createElementNS("http://www.w3.org/2000/svg", "path");
  base.setAttribute("d", "M6 21h12");

  svg.append(crown, base);
  return svg;
}

function createAdminLauncherButton() {
  const button = document.createElement("button");
  button.className = "space-launch-button admin-launch-button";
  button.type = "button";
  button.dataset.panel = "admin";
  button.title = "space-admin";
  button.setAttribute("aria-label", "space-admin");
  button.classList.toggle("active", isAdminPanel(state.activePanel));

  const glyph = document.createElement("span");
  glyph.className = "space-launch-glyph admin-launch-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.append(createAdminCrownIcon());

  const label = document.createElement("span");
  label.textContent = "Admin";

  button.append(glyph, label);
  button.addEventListener("click", () => setPanel("admin"));
  return button;
}

async function copyActiveSpaceId() {
  const space = userSpaceById(state.activeSpaceMenuId);
  if (!space) return;
  try {
    await navigator.clipboard.writeText(space.id);
    recordUserEvent("workspace.space_id_copied", {
      target: `space:${space.id}`,
      summary: `Copied ${space.title} id`,
      data: { space_id: space.id, title: space.title },
    });
  } catch (error) {
    recordUserEvent("workspace.space_id_copy_error", {
      target: `space:${space.id}`,
      summary: error.message,
      data: { error: error.message },
    });
  } finally {
    hideSpaceContextMenu({ skipHistory: true, replaceHistory: true });
  }
}

function hideAppContextMenu(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("app-menu")) return;
  state.activeAppMenuId = "";
  state.activeAppMenuKind = "";
  if (els.appContextMenu) els.appContextMenu.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("app-menu", { skipHistory: true, replaceHistory: true });
  }
}

function positionFixedMenu(menu, event) {
  if (!menu) return;
  menu.hidden = false;
  const rect = menu.getBoundingClientRect();
  const gap = 8;
  const maxLeft = window.innerWidth - rect.width - gap;
  const maxTop = window.innerHeight - rect.height - gap;
  const left = Math.max(gap, Math.min(maxLeft, event.clientX || gap));
  const top = Math.max(gap, Math.min(maxTop, event.clientY || gap));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

function showAppContextMenu(widgetId, kind, event) {
  event.preventDefault();
  event.stopPropagation();
  if (!widgetId || !els.appContextMenu) return;
  state.activeAppMenuId = widgetId;
  state.activeAppMenuKind = kind || "app";
  if (els.editAppButton) els.editAppButton.textContent = "Edit";
  if (els.copyAppIdButton) els.copyAppIdButton.textContent = "Copy app id";
  positionFixedMenu(els.appContextMenu, event);
  pushUiNavigationLayer("app-menu", () => hideAppContextMenu({ skipHistory: true, skipStack: true }));
  recordUserEvent("workspace.app_context_menu_requested", {
    target: `${state.activeAppMenuKind}:${widgetId}`,
    summary: `Opened app menu for ${widgetId}`,
    data: { app_id: widgetId, kind: state.activeAppMenuKind },
  });
}

async function copyActiveAppId() {
  const widgetId = state.activeAppMenuId;
  if (!widgetId) return;
  try {
    await navigator.clipboard.writeText(widgetId);
    recordUserEvent("workspace.app_id_copied", {
      target: `app:${widgetId}`,
      summary: `Copied ${widgetId} id`,
      data: { app_id: widgetId },
    });
  } catch (error) {
    recordUserEvent("workspace.app_id_copy_error", {
      target: `app:${widgetId}`,
      summary: error.message,
      data: { app_id: widgetId, error: error.message },
    });
  } finally {
    hideAppContextMenu({ skipHistory: true, replaceHistory: true });
  }
}

function populateAppEditForm(widgetId) {
  const meta = widgetMeta(widgetId);
  const bounds = widgetDimensionBounds(widgetId, spaceSurface()?.getBoundingClientRect?.());
  if (els.appEditModalTitle) els.appEditModalTitle.textContent = `Edit ${widgetTitle(widgetId)}`;
  if (els.appEditModalMeta) els.appEditModalMeta.textContent = widgetId;
  if (els.appEditNameInput) els.appEditNameInput.value = cleanText(meta.title, widgetDefaultLabel(widgetId));
  if (els.appEditIconInput) els.appEditIconInput.value = cleanText(meta.iconText, widgetDefaultShort(widgetId));
  if (els.appEditImageInput) els.appEditImageInput.value = "";
  if (els.appEditMinWidthInput) els.appEditMinWidthInput.value = String(bounds.minWidth);
  if (els.appEditMaxWidthInput) els.appEditMaxWidthInput.value = String(bounds.maxWidth);
  if (els.appEditMinHeightInput) els.appEditMinHeightInput.value = String(bounds.minHeight);
  if (els.appEditMaxHeightInput) els.appEditMaxHeightInput.value = String(bounds.maxHeight);
}

function openAppEditModal(widgetId = state.activeAppMenuId) {
  if (!widgetId || !els.appEditModal) return;
  state.activeAppMenuId = widgetId;
  populateAppEditForm(widgetId);
  els.appEditModal.hidden = false;
  hideAppContextMenu({ skipHistory: true, replaceHistory: true });
  pushUiNavigationLayer("app-edit-modal", () => closeAppEditModal({ skipHistory: true, skipStack: true }));
  recordUserEvent("workspace.app_edit_opened", {
    target: `app:${widgetId}`,
    summary: `Opened editor for ${widgetId}`,
    data: { app_id: widgetId },
  });
}

function closeAppEditModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("app-edit-modal")) return;
  if (els.appEditModal) els.appEditModal.hidden = true;
  if (els.appEditImageInput) els.appEditImageInput.value = "";
  if (!options.skipStack) {
    closeUiNavigationLayer("app-edit-modal", { skipHistory: true, replaceHistory: true });
  }
}

function inputNumber(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

function selectedImageDataUrl(input) {
  const file = input?.files?.[0];
  if (!file || !file.type.startsWith("image/")) return Promise.resolve("");
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const raw = String(reader.result || "");
      const image = new Image();
      image.addEventListener("load", () => {
        const edge = 96;
        const scale = Math.min(1, edge / Math.max(image.width || edge, image.height || edge));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round((image.width || edge) * scale));
        canvas.height = Math.max(1, Math.round((image.height || edge) * scale));
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/png"));
      }, { once: true });
      image.addEventListener("error", () => resolve(raw.length < 180000 ? raw : ""), { once: true });
      image.src = raw;
    });
    reader.addEventListener("error", () => resolve(""));
    reader.readAsDataURL(file);
  });
}

async function saveAppEdit(event) {
  event?.preventDefault();
  const widgetId = state.activeAppMenuId;
  if (!widgetId) return;
  const current = widgetMeta(widgetId);
  const image = await selectedImageDataUrl(els.appEditImageInput);
  const minWidth = normalizeDimension(inputNumber(els.appEditMinWidthInput, current.minWidth || 320), 320, 180, 2400);
  const minHeight = normalizeDimension(inputNumber(els.appEditMinHeightInput, current.minHeight || 220), 220, 120, 1800);
  const maxWidth = Math.max(minWidth, normalizeDimension(inputNumber(els.appEditMaxWidthInput, current.maxWidth || 1800), 1800, minWidth, 4000));
  const maxHeight = Math.max(minHeight, normalizeDimension(inputNumber(els.appEditMaxHeightInput, current.maxHeight || 1200), 1200, minHeight, 3000));
  const layout = widgetLayout(widgetId);
  layout.meta = {
    ...current,
    title: cleanText(els.appEditNameInput?.value, widgetDefaultLabel(widgetId)).slice(0, 64),
    iconText: cleanText(els.appEditIconInput?.value, widgetDefaultShort(widgetId)).slice(0, 8),
    minWidth,
    maxWidth,
    minHeight,
    maxHeight,
    image: image || current.image || "",
  };
  const widget = widgetById(widgetId);
  if (widget && !widget.classList.contains("is-minimized") && !widget.classList.contains("is-maximized")) {
    layout.widthPx = clamp(Number(layout.widthPx || widget.offsetWidth), minWidth, maxWidth);
    layout.heightPx = clamp(Number(layout.heightPx || widget.offsetHeight), minHeight, maxHeight);
  }
  saveWidgetLayout();
  applyWidgetLayout();
  renderAppLayer();
  closeAppEditModal({ skipHistory: true, replaceHistory: true });
  recordUserEvent("workspace.app_edit_saved", {
    target: `app:${widgetId}`,
    summary: `Saved editor for ${widgetId}`,
    data: { app_id: widgetId, min_width: minWidth, max_width: maxWidth, min_height: minHeight, max_height: maxHeight },
  });
}

function resetAppEdit() {
  const widgetId = state.activeAppMenuId;
  if (!widgetId) return;
  const layout = widgetLayout(widgetId);
  delete layout.meta;
  saveWidgetLayout();
  applyWidgetLayout();
  renderAppLayer();
  populateAppEditForm(widgetId);
  recordUserEvent("workspace.app_edit_reset", {
    target: `app:${widgetId}`,
    summary: `Reset editor for ${widgetId}`,
    data: { app_id: widgetId },
  });
}

function deleteSpacePhrase(space) {
  return `DELETE ${space.title}`;
}

function renderDeleteSpaceModal() {
  const space = userSpaceById(state.deleteSpaceTargetId);
  if (!space || !els.deleteSpaceModal) return;
  const phrase = deleteSpacePhrase(space);
  if (els.deleteSpaceName) els.deleteSpaceName.textContent = space.title;
  if (els.deleteSpacePrompt) els.deleteSpacePrompt.textContent = phrase;
  if (els.confirmDeleteSpaceButton) {
    els.confirmDeleteSpaceButton.disabled = cleanText(els.deleteSpaceConfirmInput?.value, "") !== phrase;
  }
}

function openDeleteSpaceModal() {
  const space = userSpaceById(state.activeSpaceMenuId);
  if (!space || !els.deleteSpaceModal) return;
  hideSpaceContextMenu({ skipHistory: true, replaceHistory: true });
  state.deleteSpaceTargetId = space.id;
  if (els.deleteSpaceConfirmInput) els.deleteSpaceConfirmInput.value = "";
  renderDeleteSpaceModal();
  els.deleteSpaceModal.hidden = false;
  pushUiNavigationLayer("delete-space-modal", () => closeDeleteSpaceModal({ skipHistory: true, skipStack: true }));
  window.setTimeout(() => els.deleteSpaceConfirmInput?.focus(), 0);
  recordUserEvent("workspace.space_delete_prompt_opened", {
    target: `space:${space.id}`,
    summary: `Delete confirmation opened for ${space.title}`,
    data: { space_id: space.id, title: space.title },
  });
}

function closeDeleteSpaceModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("delete-space-modal")) return;
  if (els.deleteSpaceModal) els.deleteSpaceModal.hidden = true;
  state.deleteSpaceTargetId = "";
  if (els.deleteSpaceConfirmInput) els.deleteSpaceConfirmInput.value = "";
  if (!options.skipStack) {
    closeUiNavigationLayer("delete-space-modal", { skipHistory: true, replaceHistory: true });
  }
}

function confirmDeleteSpace() {
  if (!ensureMainDeviceForEvolution("delete space")) return;
  const space = userSpaceById(state.deleteSpaceTargetId);
  if (!space) return;
  if (cleanText(els.deleteSpaceConfirmInput?.value, "") !== deleteSpacePhrase(space)) {
    renderDeleteSpaceModal();
    return;
  }
  state.userSpaces = state.userSpaces.filter((item) => item.id !== space.id);
  delete state.spaceWidgetLayouts[space.id];
  saveLocalSpaceWidgetLayouts();
  saveUserSpaces();
  if (state.authUser) {
    void fetchJson("/spaces", {
      method: "POST",
      timeoutMs: 8000,
      body: { action: "delete", space_id: space.id },
    }).catch(() => {});
  }
  closeDeleteSpaceModal({ skipHistory: true, replaceHistory: true });
  if (state.activePanel === space.id) setPanel("home");
  renderSpaceLauncher();
  recordUserEvent("workspace.space_deleted", {
    target: `space:${space.id}`,
    summary: `Deleted ${space.title}`,
    data: { space_id: space.id, title: space.title },
  });
}

function renderSpaceLauncher() {
  if (!els.spaceLauncherList) return;
  els.spaceLauncherList.replaceChildren();
  if (isAdminUser()) els.spaceLauncherList.append(createAdminLauncherButton());
  state.userSpaces.forEach((space, index) => {
    const button = document.createElement("button");
    button.className = "space-launch-button";
    button.type = "button";
    button.dataset.spaceId = space.id;
    button.title = space.title;
    button.setAttribute("aria-label", space.title);
    button.classList.toggle("active", state.activePanel === space.id);

    const glyph = document.createElement("span");
    glyph.className = "space-launch-glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = userSpaceInitial(space.title);

    const label = document.createElement("span");
    label.textContent = `S${index + 1}`;

    button.append(glyph, label);
    button.addEventListener("click", () => setPanel(space.id));
    button.addEventListener("contextmenu", (event) => showSpaceContextMenu(space, event));
    els.spaceLauncherList.append(button);
  });
}

function createUserSpace() {
  if (!ensureMainDeviceForEvolution("create space")) return;
  const createdAt = new Date().toISOString();
  const nextNumber = state.userSpaces.length + 1;
  const space = {
    id: `space_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: `Space ${nextNumber}`,
    created_at: createdAt,
  };
  state.userSpaces.push(space);
  state.spaceWidgetLayouts[space.id] = defaultWidgetLayoutForPanel(space.id);
  saveLocalSpaceWidgetLayouts();
  saveUserSpaces();
  renderSpaceLauncher();
  setPanel(space.id);
  recordUserEvent("workspace.space_created", {
    target: `space:${space.id}`,
    summary: `Created ${space.title}`,
    data: { space_id: space.id, title: space.title, created_at: createdAt },
  });
}

function openHomeDevices() {
  openDevicesModal({ origin: "home-action" });
}

function openConfigModal() {
  renderConfigModal();
  if (els.configModal) els.configModal.hidden = false;
  pushUiNavigationLayer("config-modal", () => closeConfigModal({ skipHistory: true, skipStack: true }));
  void loadTimeline("config").catch(() => {});
  recordUserEvent("home.config_opened", {
    target: "home:config",
    summary: "Opened space config",
  });
}

function closeConfigModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("config-modal")) return;
  if (els.configModal) els.configModal.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("config-modal", { skipHistory: true, replaceHistory: true });
  }
}

function renderConfigModal() {
  if (!els.configDetails) return;
  renderSpaceTitle();
  const timelineButton = document.createElement("button");
  timelineButton.className = "config-action-button";
  timelineButton.type = "button";
  timelineButton.textContent = "Timeline";
  timelineButton.addEventListener("click", openTimelineFromConfig);
  const rows = [
    renderStorageControl(),
    renderCanvasDensityControl(),
  ];
  if (activeSpaceStorageId() === "home") rows.push(renderLauncherPreferenceControl());
  rows.push(timelineButton);
  els.configDetails.replaceChildren(...rows);
}

function storagePercent(used, total) {
  const usedNumber = Number(used);
  const totalNumber = Number(total);
  if (!Number.isFinite(usedNumber) || !Number.isFinite(totalNumber) || totalNumber <= 0) return 0;
  return clamp(Math.round((usedNumber / totalNumber) * 100), 0, 100);
}

function cloudStorageMetric() {
  const storage = state.userStorage || {};
  const cloud = storage.cloud && typeof storage.cloud === "object" ? storage.cloud : {};
  const total = Number(cloud.quota_bytes || cloud.total_bytes || 0);
  const used = Number(cloud.used_bytes || 0);
  const percent = storagePercent(used, total);
  return {
    used,
    total,
    percent,
    usedLabel: bytes(used),
    totalLabel: bytes(total),
    muted: total <= 0,
  };
}

function localStorageMetric() {
  const estimate = state.localStorageEstimate || {};
  const used = Number(estimate.usage || 0);
  const total = Number(estimate.quota || 0);
  const percent = storagePercent(used, total);
  return {
    used,
    total,
    percent,
    usedLabel: Number.isFinite(used) ? bytes(used) : "-",
    totalLabel: total > 0 ? bytes(total) : "browser managed",
    muted: total <= 0,
  };
}

function storageMetricRow(label, metric) {
  const row = document.createElement("div");
  row.className = `config-storage-meter${metric.muted ? " is-muted" : ""}`;
  const line = document.createElement("div");
  line.className = "config-storage-meter-line";
  const title = document.createElement("strong");
  title.textContent = `${label}:`;
  const value = document.createElement("span");
  value.textContent = `${metric.usedLabel}/${metric.totalLabel}`;
  const percent = document.createElement("span");
  percent.textContent = `${metric.percent}%`;
  line.append(title, value, percent);
  const bar = document.createElement("div");
  bar.className = "config-storage-meter-bar";
  bar.style.setProperty("--storage-progress", `${metric.percent}%`);
  row.append(line, bar);
  return row;
}

function renderStorageControl() {
  const wrap = document.createElement("div");
  wrap.className = "config-storage-card";
  const title = document.createElement("strong");
  title.textContent = "Storage";
  const cloud = storageMetricRow("Cloud", cloudStorageMetric());
  const local = storageMetricRow("Local", localStorageMetric());
  const actions = document.createElement("div");
  actions.className = "config-storage-actions";
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.textContent = "Export";
  exportButton.addEventListener("click", () => void exportStorageBackup());
  const importButton = document.createElement("button");
  importButton.type = "button";
  importButton.textContent = "Import";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json,.json";
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    input.value = "";
    if (file) void importStorageBackup(file);
  });
  importButton.addEventListener("click", () => input.click());
  actions.append(exportButton, importButton, input);
  wrap.append(title, cloud, local, actions);
  return wrap;
}

function readJsonFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      try {
        resolve(JSON.parse(String(reader.result || "{}")));
      } catch (error) {
        reject(error);
      }
    });
    reader.addEventListener("error", () => reject(reader.error || new Error("Could not read file.")));
    reader.readAsText(file);
  });
}

async function exportStorageBackup() {
  try {
    const payload = await fetchJson("/storage/export", { timeoutMs: 10000 });
    const backup = {
      ...payload,
      layout_policy: "client-local-by-default",
      widget_layouts: state.spaceWidgetLayouts || {},
      client_device_id: clientDeviceId(),
    };
    downloadJson(`wasm-agent-storage-${new Date().toISOString().slice(0, 10)}.json`, backup);
    recordUserEvent("storage.exported", {
      target: "storage",
      summary: "Exported local storage backup",
      data: { schema: backup.schema || "", includes_client_layouts: true },
    });
  } catch (error) {
    recordUserEvent("storage.export_error", {
      target: "storage",
      summary: error.message,
      data: { error: error.message },
    });
  }
}

async function importStorageBackup(file) {
  if (!ensureMainDeviceForEvolution("import storage")) return;
  try {
    const payload = await readJsonFile(file);
    const result = await fetchJson("/storage/import", {
      method: "POST",
      timeoutMs: 12000,
      body: {
        ...payload,
        widget_layouts: {},
        device_layouts: {},
      },
    });
    state.userSpaces = Array.isArray(result.spaces) ? result.spaces : state.userSpaces;
    state.userStorage = result.storage || state.userStorage;
    state.spaceWidgetLayouts = payload.widget_layouts && typeof payload.widget_layouts === "object"
      ? payload.widget_layouts
      : state.spaceWidgetLayouts;
    saveLocalSpaceWidgetLayouts();
    applySpaceWidgetLayout(state.activePanel);
    renderSpaceLauncher();
    renderConfigModal();
    recordUserEvent("storage.imported", {
      target: "storage",
      summary: "Imported local storage backup",
      data: { spaces: state.userSpaces.length },
    });
  } catch (error) {
    recordUserEvent("storage.import_error", {
      target: "storage",
      summary: error.message,
      data: { error: error.message },
    });
  }
}

function renderCanvasDensityControl() {
  const wrap = document.createElement("div");
  wrap.className = "config-density-control";
  const head = document.createElement("div");
  head.className = "config-density-head";
  const label = document.createElement("strong");
  label.textContent = "Space density";
  const value = document.createElement("span");
  value.className = "config-density-value";
  value.textContent = `${canvasDensity().toFixed(2).replace(/\.00$/, "")}x`;
  const input = document.createElement("input");
  input.className = "config-density-input";
  input.type = "number";
  input.min = "1";
  input.max = String(CANVAS_DENSITY_MAX);
  input.step = "0.25";
  input.inputMode = "decimal";
  input.setAttribute("aria-label", "Space density value");
  const dial = document.createElement("div");
  dial.className = "config-density-line";
  dial.tabIndex = 0;
  dial.setAttribute("role", "slider");
  dial.setAttribute("aria-label", "Space density");
  dial.setAttribute("aria-valuemin", "1");
  dial.setAttribute("aria-valuemax", String(CANVAS_DENSITY_MAX));
  dial.setAttribute("aria-valuestep", "0.25");
  const knob = document.createElement("span");
  knob.className = "config-density-line-knob";
  knob.setAttribute("aria-hidden", "true");
  dial.append(knob);
  head.append(label, value, input);
  wrap.append(head, dial);
  updateDensityDial(wrap);
  installDensityDial(wrap, dial);
  installDensityInput(wrap, input);
  return wrap;
}

function updateDensityDial(control = null) {
  const wrap = control || els.configDetails?.querySelector?.(".config-density-control");
  if (!wrap) return;
  const density = canvasDensity();
  const progress = (density - 1) / (CANVAS_DENSITY_MAX - 1);
  wrap.style.setProperty("--density-progress", `${Math.round(progress * 100)}%`);
  const value = wrap.querySelector(".config-density-value");
  if (value) value.textContent = `${density.toFixed(2).replace(/\.00$/, "")}x`;
  const input = wrap.querySelector(".config-density-input");
  if (input && document.activeElement !== input) input.value = String(density);
  const dial = wrap.querySelector(".config-density-line");
  if (dial) {
    dial.style.setProperty("--density-progress", `${Math.round(progress * 100)}%`);
    dial.setAttribute("aria-valuenow", String(density));
    dial.setAttribute("aria-valuetext", `${density}x`);
  }
}

function densityFromDialPointer(dial, event) {
  const rect = dial.getBoundingClientRect();
  const progress = clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  return normalizedCanvasDensity(1 + progress * (CANVAS_DENSITY_MAX - 1));
}

function installDensityInput(wrap, input) {
  if (!wrap || !input) return;
  const commit = (origin = "input") => {
    const next = normalizedCanvasDensity(input.value);
    freezeWidgetPixelLayout();
    setCanvasDensityValue(next, { control: wrap, origin, force: true });
  };
  input.addEventListener("change", () => commit("input"));
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    input.blur();
    commit("input-enter");
  });
}

function installDensityDial(wrap, dial) {
  if (!wrap || !dial) return;
  let dragging = false;
  let changed = false;
  const move = (event) => {
    if (!dragging) return;
    event.preventDefault();
    const previous = canvasDensity();
    const next = densityFromDialPointer(dial, event);
    changed = next !== previous || changed;
    setCanvasDensityValue(next, {
      control: wrap,
      persist: false,
      render: false,
    });
  };
  const end = (event) => {
    if (!dragging) return;
    dragging = false;
    dial.classList.remove("is-dragging");
    dial.removeEventListener("pointermove", move);
    dial.removeEventListener("pointerup", end);
    dial.removeEventListener("pointercancel", end);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    try {
      dial.releasePointerCapture(event.pointerId);
    } catch {
      // Capture may already be released by the browser.
    }
    if (changed) {
      commitCanvasDensityChange("dial");
      renderConfigModal();
    }
  };
  dial.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event)) return;
    event.preventDefault();
    freezeWidgetPixelLayout();
    dragging = true;
    changed = false;
    dial.classList.add("is-dragging");
    try {
      dial.setPointerCapture(event.pointerId);
    } catch {
      // Window listeners below keep the dial responsive when capture is unavailable.
    }
    move(event);
    dial.addEventListener("pointermove", move, { passive: false });
    dial.addEventListener("pointerup", end, { once: true });
    dial.addEventListener("pointercancel", end, { once: true });
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  });
  dial.addEventListener("keydown", (event) => {
    const delta = {
      ArrowLeft: -0.25,
      ArrowDown: -0.25,
      ArrowRight: 0.25,
      ArrowUp: 0.25,
      Home: 1 - canvasDensity(),
      End: CANVAS_DENSITY_MAX - canvasDensity(),
    }[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    freezeWidgetPixelLayout();
    setCanvasDensityValue(canvasDensity() + delta, { control: wrap, origin: "dial-key" });
  });
}

function renderLauncherPreferenceControl() {
  const label = document.createElement("label");
  label.className = "config-toggle-row";
  const text = document.createElement("span");
  text.innerHTML = "<strong>Navbar position</strong><small>Use top bar on narrow screens</small>";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(state.mobileLauncherTop);
  input.addEventListener("change", () => {
    state.mobileLauncherTop = input.checked;
    saveLauncherPreference();
    applyLauncherPreference();
    recordUserEvent("workspace.launcher_preference_changed", {
      target: "launcher",
      summary: input.checked ? "Mobile launcher moved to top" : "Mobile launcher kept on left",
      data: { mobile_top: input.checked },
    });
  });
  label.append(text, input);
  return label;
}

function openTimelineFromConfig() {
  setWidgetMinimized("timeline", false);
  void loadTimeline("config").catch(() => {});
  closeConfigModal({ skipHistory: true, replaceHistory: true });
  recordUserEvent("workspace.timeline_accessed", {
    target: `timeline:${activeSpaceStorageId()}`,
    summary: `Opened ${activeSpaceStorageId()} timeline`,
    data: { space_id: activeSpaceStorageId() },
  });
}

function openHomeModulesModal() {
  renderModules();
  if (els.homeModulesModal) els.homeModulesModal.hidden = false;
  pushUiNavigationLayer("home-modules-modal", () => closeHomeModulesModal({ skipHistory: true, skipStack: true }));
  recordUserEvent("home.modules_opened", {
    target: "home:modules",
    summary: "Opened home modules",
  });
}

function closeHomeModulesModal(options = {}) {
  if (!options.skipHistory && closeUiNavigationLayer("home-modules-modal")) return;
  if (els.homeModulesModal) els.homeModulesModal.hidden = true;
  if (!options.skipStack) {
    closeUiNavigationLayer("home-modules-modal", { skipHistory: true, replaceHistory: true });
  }
}

function selectNode(nodeId) {
  const previous = state.selectedNode;
  state.selectedNode = nodeId;
  els.selectedNode.textContent = nodeId;
  renderTopology();
  renderNodeList();
  if (previous !== nodeId) {
    recordUserEvent("fleet.node_selected", {
      target: `node:${nodeId}`,
      summary: `Selected node ${nodeId}`,
      data: { node_id: nodeId, previous_node_id: previous },
    });
  }
}

function panelFromPath() {
  const panel = normalizePanel(window.location.pathname.replace(/^\/+/, "") || "home");
  const spaceMatch = panel.match(/^spaces\/([^/]+)$/);
  if (spaceMatch && isUserSpacePanel(spaceMatch[1])) return spaceMatch[1];
  if (panel === "home" || ADMIN_PANEL_IDS.has(panel)) return panel;
  return "home";
}

function panelPath(panel) {
  panel = normalizePanel(panel);
  if (isUserSpacePanel(panel)) return `/spaces/${panel}`;
  if (ADMIN_PANEL_IDS.has(panel)) return `/${panel}`;
  return "/home";
}

function syncPanelUrl(panel) {
  const nextPath = panelPath(panel);
  const nextUrl = new URL(window.location.href);
  nextUrl.pathname = nextPath;
  if (state.agentOpen) {
    nextUrl.searchParams.set(CHAT_QUERY_KEY, CHAT_QUERY_VALUE);
  } else {
    nextUrl.searchParams.delete(CHAT_QUERY_KEY);
  }
  if (`${window.location.pathname}${window.location.search}` === `${nextUrl.pathname}${nextUrl.search}`) return;
  window.history.pushState(uiNavigationState(), "", nextUrl);
}

function setPanel(panel, options = {}) {
  panel = normalizePanel(panel);
  if (!isPanelAvailable(panel)) panel = "home";
  const previous = state.activePanel;
  state.spaceWidgetLayouts[activeSpaceStorageId(previous)] = state.widgetLayout;
  saveLocalSpaceWidgetLayouts();
  const userSpacePanel = isUserSpacePanel(panel);
  state.activePanel = panel;
  els.app.dataset.panel = userSpacePanel ? "user-space" : panel;
  els.app.dataset.activeSpace = userSpacePanel ? panel : "";
  els.panelTabs.forEach((button) => button.classList.toggle("active", button.dataset.panel === panel));
  els.panelButtons.forEach((button) => {
    if (button.classList.contains("launch")) button.classList.toggle("active", button.dataset.panel === panel);
    if (button.classList.contains("launcher-mark")) button.classList.toggle("active", button.dataset.panel === panel);
  });
  els.panelViews.forEach((view) => view.classList.toggle("active", view.dataset.view === panel));
  applySpaceWidgetLayout(panel);
  renderSpaceTitle();
  renderSpaceLauncher();
  syncResourcePolling();
  syncSecurityPolling();
  if (panel === "timeline" && isModuleEnabled("timeline")) void loadTimeline("panel").catch(() => {});
  if (options.updateUrl !== false) syncPanelUrl(panel);
  if (previous !== panel) {
    recordUserEvent("workspace.panel_selected", {
      target: `panel:${panel}`,
      summary: `Opened ${panel} panel`,
      data: { panel, previous_panel: previous },
    });
  }
}

function handleAppPopState() {
  setPanel(panelFromPath(), { updateUrl: false });
  syncUiNavigationWithHistory();
}

async function submitTask(prompt) {
  const text = cleanText(prompt, "");
  if (!text) return;
  const startedAt = performance.now();
  recordUserEvent("task.prompt_submitted", {
    target: `node:${state.selectedNode || "orchestrator"}`,
    summary: `Submitted prompt to ${state.selectedNode || "orchestrator"}`,
    data: {
      target_node: state.selectedNode || "orchestrator",
      prompt_preview: truncateText(text, 220),
      prompt_length: text.length,
    },
  });
  els.promptSendButton.disabled = true;
  els.taskOutput.textContent = "Submitting task...";
  try {
    const data = await bridgeJson("/task", {
      method: "POST",
      body: {
        prompt: text,
        target_node: state.selectedNode || "orchestrator",
        async: true,
      },
    });
    const task = data.task || {};
    state.taskId = task.task_id || "";
    renderTaskOutput(task);
    if (state.taskId) pollTask();
    recordUserEvent("task.submit_accepted", {
      target: `task:${state.taskId || "unknown"}`,
      summary: `Task ${state.taskId || "unknown"} accepted`,
      data: { task_id: state.taskId, status: task.status, target_node: task.target_node },
      duration_ms: performance.now() - startedAt,
    });
  } catch (error) {
    state.lastError = error.message;
    els.taskOutput.textContent = error.message;
    els.promptSendButton.disabled = false;
    recordUserEvent("task.submit_error", {
      target: `node:${state.selectedNode || "orchestrator"}`,
      summary: error.message,
      data: { error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  }
}

async function pollTask() {
  clearTimeout(state.taskTimer);
  if (!state.taskId) {
    els.promptSendButton.disabled = false;
    return;
  }
  try {
    const data = await bridgeJson(`/tasks/${encodeURIComponent(state.taskId)}`);
    const task = data.task || {};
    renderTaskOutput(task);
    if (["running", "queued", "submitted"].includes(task.status)) {
      state.taskTimer = window.setTimeout(pollTask, 1800);
    } else {
      state.taskId = "";
      els.promptSendButton.disabled = false;
      await refresh();
    }
  } catch (error) {
    els.taskOutput.textContent = error.message;
    els.promptSendButton.disabled = false;
  }
}

function clearTaskInputs() {
  clearTimeout(state.taskTimer);
  state.taskId = "";
  els.promptInput.value = "";
  els.taskOutput.textContent = "Ready";
  els.promptSendButton.disabled = false;
}

function logsText(payload) {
  const logs = payload.logs || payload;
  if (typeof logs === "string") return logs;
  if (Array.isArray(logs.lines)) return logs.lines.join("\n");
  if (Array.isArray(logs.entries)) return logs.entries.map((entry) => entry.line || JSON.stringify(entry)).join("\n");
  if (logs.raw?.stdout) return logs.raw.stdout;
  return JSON.stringify(logs, null, 2);
}

function bridgeActionResult(payload) {
  return payload.action_result || payload.result || payload;
}

async function loadLogs() {
  setPanel("logs");
  els.logsButton.disabled = true;
  els.logsOutput.textContent = "Loading logs...";
  const startedAt = performance.now();
  recordUserEvent("logs.load_started", {
    target: `node:${state.selectedNode}`,
    summary: `Loading logs for ${state.selectedNode}`,
    data: { node_id: state.selectedNode, lines: 120 },
  });
  try {
    const data = await bridgeJson(`/nodes/${encodeURIComponent(state.selectedNode)}/logs?lines=120`);
    els.logsOutput.textContent = logsText(data);
    state.lastLogSummary = {
      node_id: state.selectedNode,
      status: "loaded",
      length: els.logsOutput.textContent.length,
      loaded_at: new Date().toISOString(),
    };
    recordUserEvent("logs.loaded", {
      target: `node:${state.selectedNode}`,
      summary: `Loaded ${els.logsOutput.textContent.length} log characters`,
      data: state.lastLogSummary,
      duration_ms: performance.now() - startedAt,
    });
  } catch (error) {
    els.logsOutput.textContent = error.message;
    state.lastLogSummary = {
      node_id: state.selectedNode,
      status: "error",
      error: error.message,
      loaded_at: new Date().toISOString(),
    };
    recordUserEvent("logs.load_error", {
      target: `node:${state.selectedNode}`,
      summary: error.message,
      data: state.lastLogSummary,
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    els.logsButton.disabled = false;
  }
}

async function runNodeAction(node, action) {
  const label = actionLabel(action);
  if (action.destructive && !window.confirm(`${label} ${node.id}?`)) return;
  const startedAt = performance.now();
  recordUserEvent("node.action_requested", {
    target: `node:${node.id}`,
    summary: `${label} requested for ${node.id}`,
    data: {
      node_id: node.id,
      action: action.action,
      destructive: Boolean(action.destructive),
      mutates_fleet: Boolean(action.mutates_fleet),
    },
  });
  state.actionBusy = action.id || `${node.id}:${action.action}`;
  renderNodeList();
  renderTaskOutput({ action: action.action, status: "running", node_id: node.id });
  try {
    const data = await bridgeJson(action.endpoint || `/nodes/${encodeURIComponent(node.id)}/action`, {
      method: action.method || "POST",
      body: action.payload_template || { action: action.action, payload: {} },
    });
    const actionResult = bridgeActionResult(data);
    renderTaskOutput(actionResult);
    await refresh();
    recordUserEvent("node.action_finished", {
      target: `node:${node.id}`,
      summary: `${label} finished for ${node.id}`,
      data: { node_id: node.id, action: action.action },
      duration_ms: performance.now() - startedAt,
    });
  } catch (error) {
    state.lastError = error.message;
    renderTaskOutput({ action: action.action, error: error.message });
    recordUserEvent("node.action_error", {
      target: `node:${node.id}`,
      summary: error.message,
      data: { node_id: node.id, action: action.action, error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    state.actionBusy = "";
    renderNodeList();
  }
}

function normalizeBrowserUrl(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `https://${value}`;
}

async function browserRequest(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok || payload.ok === false) {
    throw new Error(payload?.error?.message || `HTTP ${response.status}`);
  }
  return payload;
}

async function openBrowserProof(url) {
  const targetUrl = normalizeBrowserUrl(url);
  if (!targetUrl) return;
  const startedAt = performance.now();
  state.browserUrlDirty = false;
  state.browserUrlDraft = targetUrl;
  state.browserPendingUrl = targetUrl;
  els.browserUrlInput.value = targetUrl;
  els.browserOpenButton.disabled = true;
  recordUserEvent("browser.url_submitted", {
    target: "browser-proof",
    summary: `Submitted ${targetUrl}`,
    data: { url: targetUrl, stream_open: isBrowserStreamOpen() },
  });
  els.browserStatus.textContent = "opening";
  els.browserStatus.className = "widget-chip";
  els.browserMeta.textContent = isBrowserStreamOpen() ? `Navigating to ${targetUrl}...` : "Launching Chromium...";
  let streamError = null;
  try {
    if (sendBrowserStreamAction("navigate", { url: targetUrl })) {
      state.browserLive = true;
      setBrowserLiveButton();
      els.browserScreen.focus();
      recordUserEvent("browser.navigation_dispatched", {
        target: "browser-proof",
        summary: `Dispatched stream navigation to ${targetUrl}`,
        data: { url: targetUrl },
        duration_ms: performance.now() - startedAt,
      });
      return;
    }
    await openBrowserStream(targetUrl);
    els.browserScreen.focus();
    recordUserEvent("browser.open_finished", {
      target: "browser-proof",
      summary: `Opened ${targetUrl}`,
      data: { url: targetUrl, mode: "stream" },
      duration_ms: performance.now() - startedAt,
    });
    return;
  } catch (error) {
    streamError = error;
    closeBrowserStream({ silent: true });
  }
  try {
    const viewport = browserViewportSize();
    const data = await browserRequest("/browser/open", { url: targetUrl, ...viewport });
    const browser = data.browser || {};
    renderBrowserCapture({
      image: browser.image,
      url: browser.url,
      sessionId: browser.session_id,
      status: "captured",
      meta: `${browser.url} / ${browser.width}x${browser.height} / interactive=${Boolean(browser.interactive)} / ${Math.round((browser.bytes || 0) / 1024)} KB${streamError ? " / stream fallback" : ""}`,
    });
    state.browserPendingUrl = "";
    setBrowserUrlInput(browser.url || targetUrl, { force: true });
    els.browserScreen.focus();
    startBrowserLive();
    recordUserEvent("browser.open_finished", {
      target: "browser-proof",
      summary: `Opened ${browser.url || targetUrl}`,
      data: { url: browser.url || targetUrl, mode: "fallback_capture", interactive: Boolean(browser.interactive) },
      duration_ms: performance.now() - startedAt,
    });
  } catch (error) {
    renderBrowserCapture({
      image: "",
      url: targetUrl,
      status: "error",
      meta: error.message,
    });
    state.browserPendingUrl = "";
    recordUserEvent("browser.open_error", {
      target: "browser-proof",
      summary: error.message,
      data: { url: targetUrl, error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    els.browserOpenButton.disabled = false;
  }
}

function browserImagePoint(event) {
  const current = state.browserCapture;
  if (!current || !current.width || !current.height) return null;
  const rect = els.browserScreen.getBoundingClientRect();
  const scaleX = rect.width / current.width;
  const scaleY = rect.height / current.height;
  const x = (event.clientX - rect.left) / scaleX;
  const y = (event.clientY - rect.top) / scaleY;
  if (x < 0 || y < 0 || x > current.width || y > current.height) return null;
  return { x: Math.round(x), y: Math.round(y) };
}

async function sendBrowserInput(action, payload = {}) {
  if (sendBrowserStreamAction(action, payload)) return Promise.resolve();
  if (!state.browserSessionId) return;
  state.browserQueue = state.browserQueue.then(
    () => sendBrowserInputNow(action, payload),
    () => sendBrowserInputNow(action, payload)
  );
  return state.browserQueue;
}

async function sendBrowserInputNow(action, payload = {}) {
  const liveRefresh = action === "screenshot" && payload.live;
  const startedAt = performance.now();
  if (!liveRefresh) {
    recordUserEvent("browser.input_forwarded", {
      target: "browser-proof",
      summary: `Forwarded ${action}`,
      data: {
        action,
        x: payload.x,
        y: payload.y,
        delta_x: payload.delta_x,
        delta_y: payload.delta_y,
        key: payload.key,
        text_length: payload.text ? String(payload.text).length : undefined,
        text_preview: payload.text ? truncateText(payload.text, 24) : undefined,
      },
      redacted: Boolean(payload.text),
    });
  }
  state.browserBusy = true;
  if (!liveRefresh) els.browserScreen.classList.add("is-busy");
  els.browserStatus.textContent = state.browserLive ? "live" : action;
  try {
    const data = await browserRequest("/browser/input", {
      session_id: state.browserSessionId,
      action,
      ...payload,
    });
    const browser = data.browser || {};
    renderBrowserCapture({
      image: browser.image,
      url: browser.url,
      sessionId: browser.session_id,
      status: liveRefresh ? "live" : "interactive",
      meta: `${browser.action || action} / ${browser.mode || "host_chromium_cdp_interactive_pixels"} / ${Math.round((browser.bytes || 0) / 1024)} KB`,
    });
    if (browser.url) els.browserUrlInput.value = browser.url;
    if (!liveRefresh) {
      recordUserEvent("browser.input_finished", {
        target: "browser-proof",
        summary: `${action} returned pixels`,
        data: { action, url: browser.url, bytes: browser.bytes },
        duration_ms: performance.now() - startedAt,
      });
    }
  } catch (error) {
    renderBrowserCapture({
      image: state.browserCapture?.image || "",
      url: state.browserCapture?.url || "",
      sessionId: state.browserSessionId,
      status: "error",
      meta: error.message,
    });
    recordUserEvent("browser.input_error", {
      target: "browser-proof",
      summary: error.message,
      data: { action, error: error.message },
      duration_ms: performance.now() - startedAt,
    });
  } finally {
    state.browserBusy = false;
    els.browserScreen.classList.remove("is-busy");
  }
}

function setBrowserLiveButton() {
  const streaming = isBrowserStreamOpen();
  const active = streaming || state.browserLive;
  els.browserLiveButton.classList.toggle("is-live", active);
  els.browserLiveButton.setAttribute("aria-pressed", active ? "true" : "false");
  els.browserLiveButton.textContent = streaming ? "Stream on" : state.browserLive ? "Live on" : "Live";
}

function startBrowserLive() {
  recordUserEvent("browser.live_started", {
    target: "browser-proof",
    summary: "Browser live mode started",
    data: { stream_open: isBrowserStreamOpen(), session_present: Boolean(state.browserSessionId) },
  });
  if (isBrowserStreamOpen()) {
    state.browserLive = true;
    setBrowserLiveButton();
    return;
  }
  if (!state.browserSessionId) return;
  state.browserLive = true;
  setBrowserLiveButton();
  scheduleBrowserLiveTick(650);
}

function stopBrowserLive() {
  recordUserEvent("browser.live_stopped", {
    target: "browser-proof",
    summary: "Browser live mode stopped",
    data: { stream_open: isBrowserStreamOpen(), frame_count: state.browserFrameCount },
  });
  if (isBrowserStreamOpen()) {
    closeBrowserStream();
    return;
  }
  state.browserLive = false;
  window.clearTimeout(state.browserLiveTimer);
  setBrowserLiveButton();
  if (state.browserCapture) renderBrowserCapture();
}

function toggleBrowserLive() {
  if (isBrowserStreamOpen() || state.browserLive) stopBrowserLive();
  else startBrowserLive();
}

function scheduleBrowserLiveTick(delay = 1100) {
  window.clearTimeout(state.browserLiveTimer);
  if (isBrowserStreamOpen()) return;
  if (!state.browserLive || !state.browserSessionId) return;
  state.browserLiveTimer = window.setTimeout(() => void browserLiveTick(), delay);
}

async function browserLiveTick() {
  if (!state.browserLive || !state.browserSessionId) return;
  if (!state.browserBusy) {
    await sendBrowserInput("screenshot", { live: true });
  }
  scheduleBrowserLiveTick();
}

function handledBrowserKey(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  if (event.key.length === 1) return true;
  return ["Enter", "Backspace", "Tab", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key);
}

function drawCanvas() {
  const canvas = els.spaceCanvas;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.floor(rect.width * dpr));
  const height = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, width, height);
}

function installSpacePanning() {
  const viewport = els.spaceViewport;
  if (!viewport) return;
  viewport.addEventListener("scroll", () => {
    updateSpaceNavigationHints();
    applyMaximizedWidgetLayouts();
    renderSpaceMiniMap();
  }, { passive: true });
  updateSpaceNavigationHints();
  viewport.addEventListener("pointerdown", (event) => {
    if (!isPrimaryPointer(event)) return;
    if (event.target.closest?.(".widget,.space-app-button,.home-actions,.space-title,.space-config-button,.modal-backdrop,.agent-overlay")) return;
    const canPanX = viewport.scrollWidth > viewport.clientWidth + 1;
    const canPanY = viewport.scrollHeight > viewport.clientHeight + 1;
    if (!canPanX && !canPanY) return;
    event.preventDefault();
    stopSpacePanMomentum();
    const startX = event.clientX;
    const startY = event.clientY;
    const startLeft = viewport.scrollLeft;
    const startTop = viewport.scrollTop;
    let lastX = startX;
    let lastY = startY;
    let lastTime = performance.now();
    let velocitySamples = [];
    let moved = false;
    let finished = false;
    viewport.classList.add("is-panning");
    setSpaceMiniMapVisible(true);
    try {
      viewport.setPointerCapture(event.pointerId);
    } catch {
      // Window listeners below keep panning responsive when capture is unavailable.
    }
    const move = (moveEvent) => {
      moveEvent.preventDefault();
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 3) moved = true;
      const now = performance.now();
      const dt = Math.max(1, now - lastTime);
      const velocityX = (moveEvent.clientX - lastX) / dt;
      const velocityY = (moveEvent.clientY - lastY) / dt;
      velocitySamples.push({ vx: velocityX, vy: velocityY, dt });
      let sampleWindowMs = 0;
      velocitySamples = velocitySamples.reverse().filter((sample) => {
        sampleWindowMs += sample.dt;
        return sampleWindowMs <= SPACE_PAN_MOMENTUM_SAMPLE_MS;
      }).reverse();
      lastX = moveEvent.clientX;
      lastY = moveEvent.clientY;
      lastTime = now;
      if (canPanX) viewport.scrollLeft = startLeft - (moveEvent.clientX - startX);
      if (canPanY) viewport.scrollTop = startTop - (moveEvent.clientY - startY);
      updateSpaceNavigationHints();
      renderSpaceMiniMap();
    };
    const end = (endEvent) => {
      if (finished) return;
      finished = true;
      viewport.classList.remove("is-panning");
      renderSpaceMiniMap();
      viewport.removeEventListener("pointermove", move);
      viewport.removeEventListener("pointerup", end);
      viewport.removeEventListener("pointercancel", end);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      try {
        viewport.releasePointerCapture(event.pointerId);
      } catch {
        // The browser may release capture before the cleanup handler runs.
      }
      if (moved) {
        endEvent.preventDefault();
        endEvent.stopPropagation();
        const releaseIdleMs = performance.now() - lastTime;
        const releaseVelocity = releaseIdleMs > SPACE_PAN_MOMENTUM_SAMPLE_MS
          ? { x: 0, y: 0 }
          : weightedSpacePanVelocity(velocitySamples);
        startSpacePanMomentum(viewport, releaseVelocity.x, releaseVelocity.y, canPanX, canPanY);
        recordUserEvent("workspace.canvas_panned", {
          target: `space:${activeSpaceStorageId()}`,
          summary: `Panned ${activeSpaceStorageId()} canvas`,
          data: {
            scroll_left: viewport.scrollLeft,
            scroll_top: viewport.scrollTop,
            release_velocity_x: releaseVelocity.x,
            release_velocity_y: releaseVelocity.y,
            release_idle_ms: releaseIdleMs,
            momentum: state.spacePanMomentumActive,
          },
        });
      } else {
        setSpaceMiniMapVisible(false);
      }
    };
    viewport.addEventListener("pointermove", move, { passive: false });
    viewport.addEventListener("pointerup", end, { once: true });
    viewport.addEventListener("pointercancel", end, { once: true });
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end, { once: true });
    window.addEventListener("pointercancel", end, { once: true });
  });
}

function installModalBackdropDismiss(modal, close) {
  if (!modal) return;
  let startedOnBackdrop = false;
  modal.addEventListener("pointerdown", (event) => {
    startedOnBackdrop = event.target === modal;
  });
  modal.addEventListener("click", (event) => {
    if (startedOnBackdrop && event.target === modal) close();
    startedOnBackdrop = false;
  });
}

function wireEvents() {
  syncVisualViewportSize();
  els.app.addEventListener("click", (event) => {
    recordUserEvent("workspace.click", {
      target: summarizeEventTarget(event.target),
      summary: `Clicked ${summarizeEventTarget(event.target)}`,
      data: {
        button: event.button,
        panel: state.activePanel,
        widget: event.target.closest?.("[data-widget-id]")?.dataset?.widgetId || "",
        target: describeEventTarget(event.target),
      },
    });
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#spaceContextMenu")) hideSpaceContextMenu();
    if (!event.target.closest?.("#nodeContextMenu")) hideNodeContextMenu();
    if (!event.target.closest?.("#appContextMenu")) hideAppContextMenu();
    if (!event.target.closest?.("#launcherLogin")) setLoginOpen(false);
  });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!closeTopUiNavigationLayer()) return;
    event.preventDefault();
    event.stopPropagation();
  });
  window.addEventListener("resize", () => hideSpaceContextMenu({ skipHistory: true, replaceHistory: true }));
  window.addEventListener("resize", () => hideNodeContextMenu({ skipHistory: true, replaceHistory: true }));
  window.addEventListener("resize", () => hideAppContextMenu({ skipHistory: true, replaceHistory: true }));
  const refreshViewportLayout = () => {
    syncVisualViewportSize();
    applyCanvasDensity();
    applyWidgetLayout();
  };
  window.addEventListener("resize", refreshViewportLayout);
  window.visualViewport?.addEventListener("resize", refreshViewportLayout);
  window.visualViewport?.addEventListener("scroll", refreshViewportLayout);
  els.spaceOrganizeButton?.addEventListener("click", organizeSpaceAppsInViewport);
  els.spaceConfigButton?.addEventListener("click", openConfigModal);
  els.addNodeButton?.addEventListener("click", addNodeFromTopology);
  els.promptSendButton.addEventListener("click", () => {
    const prompt = els.promptInput.value.trim();
    if (prompt) void submitTask(prompt);
  });
  els.clearButton.addEventListener("click", clearTaskInputs);
  els.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.shiftKey) {
      event.preventDefault();
      const prompt = els.promptInput.value.trim();
      if (prompt) void submitTask(prompt);
    }
  });
  els.logsButton.addEventListener("click", () => void loadLogs());
  els.browserForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void openBrowserProof(browserAddressValue());
  });
  els.browserUrlInput.addEventListener("input", () => {
    state.browserUrlDirty = true;
    state.browserUrlDraft = els.browserUrlInput.value;
  });
  els.browserUrlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void openBrowserProof(browserAddressValue());
    }
  });
  els.browserBackButton.addEventListener("click", () => void sendBrowserInput("back"));
  els.browserForwardButton.addEventListener("click", () => void sendBrowserInput("forward"));
  els.browserReloadButton.addEventListener("click", () => void sendBrowserInput("reload"));
  els.browserLiveButton.addEventListener("click", toggleBrowserLive);
  els.browserScreen.addEventListener("click", (event) => {
    const point = browserImagePoint(event);
    if (!point) return;
    els.browserScreen.focus();
    recordUserEvent("browser.click", {
      target: "browser-proof",
      summary: `Clicked browser pixels at ${point.x},${point.y}`,
      data: point,
    });
    void sendBrowserInput("click", point);
  });
  els.browserScreen.addEventListener("wheel", (event) => {
    const point = browserImagePoint(event);
    if (!point) return;
    event.preventDefault();
    recordUserEvent("browser.scroll", {
      target: "browser-proof",
      summary: `Scrolled browser pixels at ${point.x},${point.y}`,
      data: {
        ...point,
        delta_x: Math.round(event.deltaX),
        delta_y: Math.round(event.deltaY),
      },
    });
    void sendBrowserInput("scroll", {
      ...point,
      delta_x: event.deltaX,
      delta_y: event.deltaY,
    });
  }, { passive: false });
  els.browserScreen.addEventListener("keydown", (event) => {
    if (!handledBrowserKey(event)) return;
    event.preventDefault();
    if (event.key.length === 1) {
      recordUserEvent("browser.type_forwarded", {
        target: "browser-proof",
        summary: "Forwarded one typed character",
        data: { text_length: 1 },
        redacted: true,
      });
      void sendBrowserInput("type", { text: event.key });
    } else {
      recordUserEvent("browser.key_forwarded", {
        target: "browser-proof",
        summary: `Forwarded ${event.key}`,
        data: { key: event.key },
      });
      void sendBrowserInput("key", { key: event.key });
    }
  });
  if ("ResizeObserver" in window) {
    const browserResizeObserver = new ResizeObserver(scheduleBrowserResizeSync);
    browserResizeObserver.observe(els.browserScreen);
  } else {
    window.addEventListener("resize", scheduleBrowserResizeSync);
  }
  els.timelineRefreshButton.addEventListener("click", () => void loadTimeline("manual"));
  els.panelButtons.forEach((button) => button.addEventListener("click", () => setPanel(button.dataset.panel)));
  els.addSpaceButton?.addEventListener("click", createUserSpace);
  els.homeDevicesButton?.addEventListener("click", openHomeDevices);
  els.homeModulesButton?.addEventListener("click", openHomeModulesModal);
  els.homeArtifactsButton?.addEventListener("click", openArtifactsModal);
  els.devicesSyncButton?.addEventListener("click", () => void syncDevice());
  els.copySpaceIdButton?.addEventListener("click", () => void copyActiveSpaceId());
  els.deleteSpaceButton?.addEventListener("click", openDeleteSpaceModal);
  els.editAppButton?.addEventListener("click", () => openAppEditModal());
  els.copyAppIdButton?.addEventListener("click", () => void copyActiveAppId());
  els.deleteSpaceConfirmInput?.addEventListener("input", renderDeleteSpaceModal);
  els.confirmDeleteSpaceButton?.addEventListener("click", confirmDeleteSpace);
  els.cancelDeleteSpaceButton?.addEventListener("click", closeDeleteSpaceModal);
  els.closeDeleteSpaceButton?.addEventListener("click", closeDeleteSpaceModal);
  installModalBackdropDismiss(els.deleteSpaceModal, closeDeleteSpaceModal);
  els.closeConfigModalButton?.addEventListener("click", closeConfigModal);
  installModalBackdropDismiss(els.configModal, closeConfigModal);
  els.closeArtifactsModalButton?.addEventListener("click", closeArtifactsModal);
  installModalBackdropDismiss(els.artifactsModal, closeArtifactsModal);
  els.closeDevicesModalButton?.addEventListener("click", closeDevicesModal);
  installModalBackdropDismiss(els.devicesModal, closeDevicesModal);
  els.appEditForm?.addEventListener("submit", (event) => void saveAppEdit(event));
  els.resetAppEditButton?.addEventListener("click", resetAppEdit);
  els.closeAppEditModalButton?.addEventListener("click", closeAppEditModal);
  installModalBackdropDismiss(els.appEditModal, closeAppEditModal);
  els.nodeEditForm?.addEventListener("submit", saveNodeEdit);
  els.resetNodeEditButton?.addEventListener("click", resetNodeEdit);
  els.closeNodeEditModalButton?.addEventListener("click", closeNodeEditModal);
  installModalBackdropDismiss(els.nodeEditModal, closeNodeEditModal);
  els.securityRefreshButton?.addEventListener("click", () => void loadSecurityLoop("manual"));
  els.closeSecurityEvidenceButton?.addEventListener("click", closeSecurityEvidenceModal);
  installModalBackdropDismiss(els.securityEvidenceModal, closeSecurityEvidenceModal);
  els.closeHomeModulesModalButton?.addEventListener("click", closeHomeModulesModal);
  installModalBackdropDismiss(els.homeModulesModal, closeHomeModulesModal);
  els.loginButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    setLoginOpen(!state.loginOpen);
  });
  els.authGateLoginButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    setLoginOpen(true);
  });
  els.loginPopover?.addEventListener("click", (event) => event.stopPropagation());
  els.logoutButton?.addEventListener("click", () => void logout());
  els.agentAvatarButton.addEventListener("click", () => {
    if (state.agentDragSuppressClick) return;
    if (state.agentOpen) {
      closeAgentChat();
    } else {
      openAgentChat();
    }
  });
  els.agentCloseButton.addEventListener("click", closeAgentChat);
  els.agentSessionsButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAgentBalloon("sessions");
  });
  els.agentContextButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAgentBalloon("context");
  });
  els.agentSettingsButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAgentBalloon("settings");
  });
  els.agentPanel.addEventListener("click", (event) => {
    if (event.target.closest?.(".agent-balloon, .agent-tool-button")) return;
    setAgentBalloon("");
  });
  els.agentNewSessionButton.addEventListener("click", newAgentSession);
  els.agentNodeSelect?.addEventListener("change", () => setAgentTargetNode(els.agentNodeSelect.value));
  els.agentForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendAgentMessage(els.agentInput.value);
  });
  els.agentInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void sendAgentMessage(els.agentInput.value);
    }
  });
  els.agentAttachButton?.addEventListener("click", () => els.agentImageInput?.click());
  els.agentImageInput?.addEventListener("change", () => {
    handleAgentFiles(els.agentImageInput.files);
    els.agentImageInput.value = "";
  });
  els.agentInput.addEventListener("paste", (event) => {
    const items = event.clipboardData?.items;
    if (!items) return;
    const imageFiles = [];
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length) {
      event.preventDefault();
      handleAgentFiles(imageFiles);
    }
  });
  els.agentForm.addEventListener("dragover", (event) => {
    event.preventDefault();
    els.agentForm.classList.add("is-dragover");
  });
  els.agentForm.addEventListener("dragleave", () => {
    els.agentForm.classList.remove("is-dragover");
  });
  els.agentForm.addEventListener("drop", (event) => {
    event.preventDefault();
    els.agentForm.classList.remove("is-dragover");
    if (event.dataTransfer?.files?.length) {
      handleAgentFiles(event.dataTransfer.files);
    }
  });
  window.addEventListener("popstate", handleAppPopState);
  if ("ResizeObserver" in window) {
    const spaceResizeObserver = new ResizeObserver(() => {
      applyCanvasDensity();
      applyWidgetLayout();
    });
    spaceResizeObserver.observe(els.spaceViewport);
  }
  const resetAgentAfterViewportChange = () => {
    resetAgentToViewportCorner();
    saveAgentLayout();
  };
  window.addEventListener("resize", resetAgentAfterViewportChange);
  window.visualViewport?.addEventListener("resize", resetAgentAfterViewportChange);
  window.visualViewport?.addEventListener("scroll", () => {
    state.agentLayout = clampAgentLayout(state.agentLayout);
    els.agentOverlay.style.left = `${state.agentLayout.left}px`;
    els.agentOverlay.style.top = `${state.agentLayout.top}px`;
    placeAgentPanel();
  });
  installWidgetWindowControls();
  installWidgetDragging();
  installWidgetResizing();
  installSpacePanning();
  installAgentDragging();
  installAgentPanelDragging();
}

async function bootstrapAuthenticatedApp() {
  if (!state.authUser) {
    renderLogin();
    return;
  }
  if (state.authenticatedBootstrapped) {
    renderAuthGate();
    return;
  }
  state.authenticatedBootstrapped = true;
  applyModuleVisibility();
  renderModules();
  installDevHmrBridge();
  if (shouldStartDevHmr()) startDevHmr();
  if ("serviceWorker" in navigator && !window.__WASM_AGENT_DISABLE_SW__) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  await loadConfig();
  await loadAuthSession();
  if (!state.authUser) {
    state.authenticatedBootstrapped = false;
    renderAuthGate();
    return;
  }
  await loadDevices("bootstrap");
  await loadUserSpaces();
  await loadLocalStorageEstimate();
  await loadWasm();
  state.activeAgentSessionId = state.agentSessions[0]?.id || "";
  updateAgentSendButton();
  renderAgentSessions();
  renderAgentMessages();
  applyAgentLayout();
  setPanel(panelFromPath(), { updateUrl: false });
  initializeUiNavigationFromUrl();
  drawCanvas();
  renderAuthGate();
  await refresh("startup");
  if (!state.refreshInterval) state.refreshInterval = window.setInterval(refresh, 15000);
}

async function main() {
  applyLauncherPreference();
  wireEvents();
  renderAuthGate();
  await loadConfig();
  await loadAuthSession();
  if (!state.authUser) void renderGoogleSignInButton();
  await bootstrapAuthenticatedApp();
}

main().catch((error) => {
  state.lastError = error.message;
  renderAll();
});

export { CORE_WASM_BASE64 };
