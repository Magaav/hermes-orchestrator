"""Shared runtime helpers for the browser-plus plugin."""

from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
import urllib.request
from urllib.parse import urlparse

from hermes_constants import resolve_node_workspace_root


INTERNAL_URL_PREFIXES = (
    "chrome://",
    "chrome-untrusted://",
    "devtools://",
    "chrome-extension://",
    "about:",
)

_URL_RE = re.compile(r"https?://[^\s)>]+", re.IGNORECASE)
_NON_SESSION_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_BROWSER_PLUS_KEYWORDS = {
    "browser",
    "browse",
    "browsing",
    "internet",
    "web",
    "search online",
    "look up",
    "open site",
    "open website",
    "visit",
    "navigate",
    "website",
    "web page",
    "webpage",
    "url",
    "click",
    "tab",
    "upload",
    "form",
    "login",
    "scrape",
    "scraping",
    "screenshot",
    "iframe",
    "dialog",
    "dropdown",
    "cookie",
    "automation",
    "chrome",
    "edge",
    "cdp",
    "browser use",
    "browser-use",
}
_INTERACTION_HINTS = {
    "upload": "interaction-skills/uploads.md",
    "file input": "interaction-skills/uploads.md",
    "dialog": "interaction-skills/dialogs.md",
    "alert": "interaction-skills/dialogs.md",
    "confirm": "interaction-skills/dialogs.md",
    "prompt": "interaction-skills/dialogs.md",
    "iframe": "interaction-skills/iframes.md",
    "cross-origin": "interaction-skills/cross-origin-iframes.md",
    "dropdown": "interaction-skills/dropdowns.md",
    "download": "interaction-skills/downloads.md",
    "cookie": "interaction-skills/cookies.md",
    "screenshot": "interaction-skills/screenshots.md",
    "shadow dom": "interaction-skills/shadow-dom.md",
    "scroll": "interaction-skills/scrolling.md",
    "tab": "interaction-skills/tabs.md",
    "print": "interaction-skills/print-as-pdf.md",
    "pdf": "interaction-skills/print-as-pdf.md",
    "network": "interaction-skills/network-requests.md",
}


def plugin_root() -> Path:
    return Path(__file__).resolve().parent


def _load_yaml_mapping(path: Path) -> dict:
    try:
        import yaml
    except Exception:
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def hermes_config_path() -> Path | None:
    hermes_home_raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if not hermes_home_raw:
        return None
    hermes_home = Path(hermes_home_raw).expanduser()
    if hermes_home.is_file():
        return hermes_home
    return hermes_home / "config.yaml"


def read_hermes_browser_cdp_url() -> str:
    config_path = hermes_config_path()
    if not config_path or not config_path.exists():
        return ""
    config = _load_yaml_mapping(config_path)
    browser_cfg = config.get("browser", {})
    if not isinstance(browser_cfg, dict):
        return ""
    return str(browser_cfg.get("cdp_url", "") or "").strip()


def configured_cdp_candidate() -> tuple[str, str] | None:
    for env_key in ("BU_CDP_WS", "BU_CDP_URL", "BROWSER_CDP_URL"):
        value = str(os.getenv(env_key, "") or "").strip()
        if value:
            return value, env_key
    config_value = read_hermes_browser_cdp_url()
    if config_value:
        return config_value, "browser.cdp_url"
    return None


def resolve_cdp_ws_endpoint(cdp_url: str, *, timeout: float = 10.0) -> str:
    raw = str(cdp_url or "").strip()
    if not raw:
        raise RuntimeError("CDP endpoint is empty")

    lowered = raw.lower()
    if lowered.startswith(("ws://", "wss://")):
        if "/devtools/browser/" in lowered:
            return raw
        tail = raw.split("://", 1)[1]
        if "/" in tail:
            return raw
        discovery_url = ("http://" if lowered.startswith("ws://") else "https://") + tail
    else:
        discovery_url = raw

    version_url = discovery_url if discovery_url.lower().endswith("/json/version") else discovery_url.rstrip("/") + "/json/version"
    try:
        payload = json.loads(urllib.request.urlopen(version_url, timeout=timeout).read() or b"{}")
    except Exception as exc:
        raise RuntimeError(f"Could not resolve {raw} via {version_url}: {exc}") from exc

    ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if not ws_url:
        raise RuntimeError(f"{version_url} did not return webSocketDebuggerUrl")
    return ws_url


def resolve_workspace_root(**kwargs) -> Path:
    return resolve_node_workspace_root(
        current_working_directory=str(kwargs.get("current_working_directory", "") or ""),
        cwd=str(kwargs.get("cwd", "") or ""),
        runtime_dir_name="browser-plus",
    )


def workspace_browser_plus_dir(**kwargs) -> Path:
    base = resolve_workspace_root(**kwargs) / "browser-plus"
    base.mkdir(parents=True, exist_ok=True)
    return base


def workspace_browser_plus_files_dir(**kwargs) -> Path:
    path = workspace_browser_plus_dir(**kwargs) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_browser_plus_logs_dir(**kwargs) -> Path:
    path = workspace_browser_plus_dir(**kwargs) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_browser_plus_screenshots_dir(**kwargs) -> Path:
    path = workspace_browser_plus_files_dir(**kwargs) / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_screenshot_path(session_name: str, **kwargs) -> Path:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return workspace_browser_plus_screenshots_dir(**kwargs) / f"{timestamp}-{normalize_session_name(session_name)}.png"


def write_operation_log(action: str, payload: dict, **kwargs) -> str:
    logs_dir = workspace_browser_plus_logs_dir(**kwargs)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = logs_dir / f"{timestamp}-{action}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(serialized, encoding="utf-8")
    (logs_dir / f"latest-{action}.json").write_text(serialized, encoding="utf-8")
    return str(path)


def normalize_session_name(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "default"
    cleaned = _NON_SESSION_CHARS_RE.sub("-", raw).strip("._-")
    if not cleaned:
        return "default"
    return cleaned[:64]


def resolve_session_name(args: dict | None = None, **kwargs) -> str:
    payload = args or {}
    candidates = (
        payload.get("session_name"),
        kwargs.get("session_name"),
        kwargs.get("task_id"),
        kwargs.get("session_id"),
        os.getenv("BROWSER_PLUS_SESSION_NAME"),
        "default",
    )
    for candidate in candidates:
        if str(candidate or "").strip():
            return normalize_session_name(candidate)
    return "default"


def session_socket_path(name: str) -> str:
    return f"/tmp/bp-{normalize_session_name(name)}.sock"


def session_pid_path(name: str) -> str:
    return f"/tmp/bp-{normalize_session_name(name)}.pid"


def session_log_path(name: str) -> str:
    return f"/tmp/bp-{normalize_session_name(name)}.log"


def send_request(
    session_name: str,
    request: dict,
    *,
    timeout: float = 30.0,
    auto_start: bool = True,
) -> dict:
    target_session = normalize_session_name(session_name)
    errors: list[str] = []
    for attempt in range(2):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        try:
            client.connect(session_socket_path(target_session))
            client.sendall((json.dumps(request) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = client.recv(1 << 20)
                if not chunk:
                    break
                data += chunk
            if not data:
                raise RuntimeError("browser-plus daemon returned an empty response")
            response = json.loads(data.decode("utf-8"))
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            return response
        except Exception as exc:
            errors.append(str(exc))
            if not auto_start or attempt > 0:
                raise RuntimeError("; ".join(error for error in errors if error))
            from .admin import ensure_daemon

            ensure_daemon(name=target_session)
        finally:
            try:
                client.close()
            except Exception:
                pass
    raise RuntimeError("; ".join(error for error in errors if error))


def list_knowledge_files(kind: str = "all") -> List[Path]:
    root = plugin_root()
    groups = {
        "domain": root / "domain-skills",
        "interaction": root / "interaction-skills",
        "reference": root / "references",
    }
    selected = []
    if kind in ("all", "", None):
        selected = list(groups.values())
    elif kind == "domain":
        selected = [groups["domain"]]
    elif kind == "interaction":
        selected = [groups["interaction"]]
    elif kind == "reference":
        selected = [groups["reference"]]
    else:
        selected = [groups["domain"], groups["interaction"], groups["reference"]]

    files: List[Path] = []
    for base in selected:
        if not base.exists():
            continue
        files.extend(sorted(path for path in base.rglob("*.md") if path.is_file()))
    return files


def relative_knowledge_path(path: Path) -> str:
    return str(path.relative_to(plugin_root()))


def read_knowledge(rel_path: str) -> dict:
    cleaned = str(rel_path or "").strip().lstrip("/")
    if not cleaned:
        raise ValueError("knowledge path is required")
    candidate = (plugin_root() / cleaned).resolve()
    root = plugin_root().resolve()
    if root not in {candidate, *candidate.parents}:
        raise ValueError("knowledge path escapes the plugin root")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"knowledge file not found: {cleaned}")
    content = candidate.read_text(encoding="utf-8")
    return {
        "path": relative_knowledge_path(candidate),
        "content": content,
        "title": content.splitlines()[0] if content else candidate.name,
    }


def _content_preview(content: str, limit: int = 260) -> str:
    compact = " ".join(line.strip() for line in content.splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def search_knowledge(query: str = "", *, kind: str = "all", limit: int = 8) -> List[dict]:
    tokens = [token for token in re.split(r"\W+", (query or "").lower()) if token]
    results: list[tuple[int, dict]] = []
    for path in list_knowledge_files(kind=kind):
        rel_path = relative_knowledge_path(path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        lowered_path = rel_path.lower()
        lowered_content = content.lower()
        title = next((line.strip() for line in content.splitlines() if line.strip()), path.name)
        if not tokens:
            score = 1
        else:
            score = 0
            for token in tokens:
                if token in lowered_path:
                    score += 8
                if token in title.lower():
                    score += 5
                if token in lowered_content:
                    score += 1
        if score <= 0:
            continue
        results.append(
            (
                score,
                {
                    "path": rel_path,
                    "title": title,
                    "preview": _content_preview(content),
                },
            )
        )
    results.sort(key=lambda item: (-item[0], item[1]["path"]))
    return [payload for _, payload in results[: max(1, int(limit or 8))]]


def suggest_knowledge_for_url(url: str, *, limit: int = 5) -> List[dict]:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return []
    labels = [label for label in host.split(".") if label]
    candidates: List[str] = []
    for candidate in (
        host,
        host.replace(".", "-"),
        "-".join(labels[:2]) if len(labels) >= 2 else "",
        labels[0] if labels else "",
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    hits: List[dict] = []
    for candidate in candidates:
        path = plugin_root() / "domain-skills" / candidate
        if not path.exists():
            continue
        for file_path in sorted(path.rglob("*.md")):
            hits.append(
                {
                    "path": relative_knowledge_path(file_path),
                    "title": file_path.stem,
                    "preview": _content_preview(file_path.read_text(encoding="utf-8", errors="ignore")),
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


def extract_urls(text: str) -> List[str]:
    return [match.group(0).rstrip(".,)") for match in _URL_RE.finditer(text or "")]


def looks_like_browser_plus_request(message: str) -> bool:
    lower = str(message or "").lower()
    if extract_urls(lower):
        return True
    return any(keyword in lower for keyword in _BROWSER_PLUS_KEYWORDS)


def browser_plus_prefers_generic_routing() -> bool:
    value = str(os.getenv("BROWSER_PLUS_PREFER_GENERIC_BROWSING", "true") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def interaction_hints_for_message(message: str) -> List[dict]:
    lower = str(message or "").lower()
    hits: List[dict] = []
    seen: set[str] = set()
    for keyword, rel_path in _INTERACTION_HINTS.items():
        if keyword not in lower or rel_path in seen:
            continue
        seen.add(rel_path)
        try:
            item = read_knowledge(rel_path)
        except Exception:
            continue
        hits.append(
            {
                "path": item["path"],
                "title": item["title"],
                "preview": _content_preview(item["content"]),
            }
        )
    return hits


def current_tab_payload(
    tabs: Sequence[dict],
    current_target_id: str | None,
) -> dict | None:
    for tab in tabs:
        if tab.get("targetId") == current_target_id:
            return tab
    return None
