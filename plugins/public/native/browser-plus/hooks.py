"""Prompt guidance hooks for the browser-plus plugin."""

from __future__ import annotations

from .runtime import (
    browser_plus_prefers_generic_routing,
    extract_urls,
    interaction_hints_for_message,
    looks_like_browser_plus_request,
    search_knowledge,
    suggest_knowledge_for_url,
)


def inject_browser_plus_turn_context(
    session_id: str = "",
    user_message: str = "",
    conversation_history=None,
    **kwargs,
):
    if not looks_like_browser_plus_request(user_message):
        return None

    urls = extract_urls(user_message)
    interaction_hints = interaction_hints_for_message(user_message)[:4]
    domain_hints = suggest_knowledge_for_url(urls[0], limit=4) if urls else []
    if not domain_hints and user_message:
        domain_hints = search_knowledge(user_message, kind="domain", limit=4)

    lines = [
        "[Browser Plus]",
        f"- Session: {session_id or 'unknown'}",
        "- Browser Plus is the Hermes-native port of browser-use/browser-harness for live CDP browser control.",
        "- Browser Plus honors Hermes live-browser settings from `/browser connect`, `BROWSER_CDP_URL`, and `browser.cdp_url` before falling back to its managed local Chromium session.",
        "- For browser tasks in this Hermes node, prefer the browser_plus_* toolset as the primary browser path over the legacy browser_navigate/browser_snapshot flow unless the task is simple text-only web retrieval.",
        "- Prefer browser_plus_status first to confirm the daemon, active tab, and dialog state.",
        "- First navigation should usually be browser_plus_new_tab so you do not clobber an existing user tab.",
        "- For real browser workflows, use browser_plus_screenshot plus browser_plus_click / browser_plus_press_key / browser_plus_type_text / browser_plus_eval_js.",
        "- Use browser_plus_cdp as the escape hatch when a workflow needs a raw CDP domain method.",
        "- Search browser_plus_search_knowledge before reinventing site-specific or interaction-specific flows.",
        "- Browser Use cloud helpers are available through browser_plus_start_remote_daemon, browser_plus_list_cloud_profiles, and browser_plus_sync_local_profile.",
    ]

    if browser_plus_prefers_generic_routing():
        lines.append(
            "- Routing policy: when the user asks to browse a site, open a URL, navigate the web, inspect a page, interact with forms, or use a real browser, choose browser_plus_* first."
        )
        lines.append(
            "- Keep using plain web_search/web_extract only for lightweight information retrieval where a real browser session is unnecessary."
        )

    if domain_hints:
        lines.append("- Relevant bundled domain knowledge:")
        lines.extend(f"  - {item['path']}" for item in domain_hints)
    if interaction_hints:
        lines.append("- Relevant bundled interaction knowledge:")
        lines.extend(f"  - {item['path']}" for item in interaction_hints)

    return {"context": "\n".join(lines)}
