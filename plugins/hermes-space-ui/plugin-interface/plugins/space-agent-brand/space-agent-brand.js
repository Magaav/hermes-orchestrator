const HERMES_AGENT_ICON_SRC =
  "/mod/hermes/space-agent-brand/assets/source/hermes-space-ui-agent-nous.png";

const AVATAR_SELECTOR = [
  "img.onscreen-agent-avatar-image",
  "img.agent-page-avatar-image",
  "img.message-avatar-image"
].join(",");

function resolveUrl(path) {
  try {
    return new URL(path, globalThis.location?.origin || "http://localhost").href;
  } catch {
    return path;
  }
}

function applyHermesAgentIcon(root = document) {
  const resolvedSrc = resolveUrl(HERMES_AGENT_ICON_SRC);
  const avatars =
    typeof root?.querySelectorAll === "function"
      ? root.querySelectorAll(AVATAR_SELECTOR)
      : [];

  for (const avatar of avatars) {
    if (!(avatar instanceof HTMLImageElement)) {
      continue;
    }

    if (avatar.src !== resolvedSrc) {
      avatar.src = HERMES_AGENT_ICON_SRC;
    }

    avatar.decoding = "async";
    avatar.dataset.hermesSpaceAgentIcon = "true";
  }
}

export function installHermesSpaceAgentBrand() {
  applyHermesAgentIcon();

  if (globalThis.__hermesSpaceAgentBrandObserver) {
    return;
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node instanceof Element) {
          applyHermesAgentIcon(node);
        }
      }
    }
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  globalThis.__hermesSpaceAgentBrandObserver = observer;
}

export default installHermesSpaceAgentBrand;
