const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const pluginRoot = path.resolve(__dirname, "..");
const appJs = fs.readFileSync(path.join(pluginRoot, "public", "app.js"), "utf8");

function appSourceBetween(startMarker, endMarker) {
  const start = appJs.indexOf(startMarker);
  assert.notStrictEqual(start, -1, `${startMarker} was not found`);
  const end = appJs.indexOf(endMarker, start);
  assert.notStrictEqual(end, -1, `${endMarker} was not found after ${startMarker}`);
  return appJs.slice(start, end);
}

const navigationSource = appSourceBetween("function chatQueryIsOpen()", "function appendAgentMessage");

function createNavigationHarness(initialHref = "http://wasm.test/home") {
  const state = {
    activePanel: "home",
    agentOpen: false,
    uiNavigationStack: [],
    uiNavigationSeq: 0,
  };
  const window = {
    location: {},
    history: {
      state: null,
      stack: [],
      backCalls: 0,
      pushState(nextState, _title, url) {
        this.state = JSON.parse(JSON.stringify(nextState || null));
        setLocation(url);
        this.stack.push({ state: this.state, href: window.location.href });
      },
      replaceState(nextState, _title, url) {
        this.state = JSON.parse(JSON.stringify(nextState || null));
        setLocation(url);
        const entry = { state: this.state, href: window.location.href };
        if (this.stack.length) {
          this.stack[this.stack.length - 1] = entry;
        } else {
          this.stack.push(entry);
        }
      },
      back() {
        this.backCalls += 1;
        if (this.stack.length > 1) {
          this.stack.pop();
          const previous = this.stack[this.stack.length - 1];
          this.state = previous.state;
          setLocation(previous.href);
        }
      },
    },
  };
  let currentUrl = new URL(initialHref);
  function setLocation(url) {
    currentUrl = new URL(String(url), currentUrl.href);
    window.location.href = currentUrl.href;
    window.location.pathname = currentUrl.pathname;
    window.location.search = currentUrl.search;
  }
  setLocation(initialHref);
  window.history.stack.push({ state: window.history.state, href: window.location.href });

  const context = {
    URL,
    URLSearchParams,
    window,
    state,
    setAgentOpen(open) {
      state.agentOpen = Boolean(open);
    },
  };
  vm.createContext(context);
  vm.runInContext(`
    const CHAT_QUERY_KEY = "chat";
    const CHAT_QUERY_VALUE = "wasm-agent-chat";
    ${navigationSource}
    globalThis.__navigation = {
      openAgentChat,
      closeAgentChat,
      syncUiNavigationWithHistory,
      uiNavigationState,
    };
  `, context);
  return { state, window, navigation: context.__navigation };
}

function testManualChatMinimizeAfterSpaceChangeClosesInPlace() {
  const { state, window, navigation } = createNavigationHarness();

  navigation.openAgentChat();
  assert.strictEqual(state.agentOpen, true);
  assert.strictEqual(window.location.pathname, "/home");
  assert.strictEqual(window.location.search, "?chat=wasm-agent-chat");
  assert.strictEqual(window.history.state.uiLayer, "agent-chat");
  assert.strictEqual(window.history.state.uiLayerLocationKey, "/home?chat=wasm-agent-chat");

  const openedLayerId = window.history.state.uiLayerId;
  state.activePanel = "space_important";
  const spaceUrl = new URL(window.location.href);
  spaceUrl.pathname = "/spaces/space_important";
  window.history.pushState(navigation.uiNavigationState(), "", spaceUrl);
  assert.strictEqual(window.history.state.uiLayerId, openedLayerId);
  assert.strictEqual(window.history.state.uiLayerLocationKey, "/home?chat=wasm-agent-chat");
  assert.strictEqual(window.location.pathname, "/spaces/space_important");

  const backCallsBefore = window.history.backCalls;
  navigation.closeAgentChat();

  assert.strictEqual(window.history.backCalls, backCallsBefore, "manual chat minimize after a space change must not call browser Back");
  assert.strictEqual(state.agentOpen, false);
  assert.strictEqual(state.uiNavigationStack.length, 0);
  assert.strictEqual(window.location.pathname, "/spaces/space_important");
  assert.strictEqual(window.location.search, "");
  assert.strictEqual(window.history.state.uiLayer, "");
  assert.strictEqual(window.history.state.uiLayerId, "");
  assert.strictEqual(window.history.state.uiLayerLocationKey, "");
}

function testManualChatMinimizeOnOpeningRouteStillUsesLayerBackEntry() {
  const { state, window, navigation } = createNavigationHarness();

  navigation.openAgentChat();
  navigation.closeAgentChat();
  assert.strictEqual(window.history.backCalls, 1, "manual chat minimize on the opening route should consume the chat history layer");

  navigation.syncUiNavigationWithHistory();
  assert.strictEqual(state.agentOpen, false);
  assert.strictEqual(state.uiNavigationStack.length, 0);
  assert.strictEqual(window.location.pathname, "/home");
  assert.strictEqual(window.location.search, "");
}

testManualChatMinimizeAfterSpaceChangeClosesInPlace();
testManualChatMinimizeOnOpeningRouteStillUsesLayerBackEntry();

console.log("ui navigation history ok");
