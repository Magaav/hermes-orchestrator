"""Plugin hooks for Canva workflow guidance and inbound asset staging."""

from __future__ import annotations

from .runtime import (
    extract_local_paths_from_history,
    extract_local_paths_from_message,
    looks_like_canva_request,
    recent_local_assets,
    stage_inbound_assets,
    workspace_canva_files_dir,
    workspace_canva_logs_dir,
)


def inject_canva_turn_context(
    session_id: str = "",
    user_message: str = "",
    platform: str = "",
    conversation_history=None,
    **kwargs,
):
    candidate_paths = extract_local_paths_from_message(user_message)
    history_paths = extract_local_paths_from_history(conversation_history)
    for path in history_paths:
        if path not in candidate_paths:
            candidate_paths.append(path)
    canva_intent = looks_like_canva_request(user_message)
    if not candidate_paths and not canva_intent:
        return None
    staged_payload = stage_inbound_assets(candidate_paths, **kwargs) if candidate_paths else None
    staged_paths = [item["staged_path"] for item in (staged_payload or {}).get("staged", [])]
    recent_assets = recent_local_assets(limit=8, **kwargs)
    lines = [
        "[Canva plugin workflow]",
        f"- Session: {session_id or 'unknown'}",
        f"- Export final deliverables only to {workspace_canva_files_dir(**kwargs)}",
        f"- Record Canva operation logs under {workspace_canva_logs_dir(**kwargs)}",
        "- Prefer this sequence: canva_get_capabilities -> canva_list_local_assets -> canva_normalize_design_brief -> canva_qa_design_brief -> playbook tool -> canva_get_design -> canva_export_design",
        "- Reuse local staged assets before re-downloading or re-uploading anything",
        "- Treat SVG/vector attachments as uploadable Canva assets, not vision inputs",
        "- Do not create a blank design unless the user explicitly asked for a blank canvas",
        "- Instagram/social posts should use 1080x1080 custom dimensions, not the unsupported preset name instagram-post",
        "- Export only final candidates to avoid wasting Canva tokens",
    ]
    if staged_paths:
        lines.append("- Staged local thread assets:")
        lines.extend(f"  - {path}" for path in staged_paths[:8])
    elif candidate_paths:
        lines.append("- The user included local attachment paths, but none required staging.")
    elif recent_assets:
        lines.append("- Recent reusable local Canva assets already in inbox:")
        lines.extend(f"  - {item['path']}" for item in recent_assets[:8])
    if canva_intent:
        lines.append("- If no reusable local asset or brand_template_id is available, stop and ask for a reattachment/template instead of creating a blank design.")
        lines.append("- Do not claim the Canva Connect API can add text/layers programmatically. For rich manual composition, only suggest Hermes built-in browser tooling if the user wants that fallback.")
    return {"context": "\n".join(lines)}
