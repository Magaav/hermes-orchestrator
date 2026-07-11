from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_FRONTMATTER_FIELD = re.compile(r"^\s*(name|version):\s*[\"']?([^\"'\n]+)", re.MULTILINE)
_SKILL_VIEW_TOOLS = {"skill_view", "skills_view"}
_SUCCESSFUL_TOOL_STATUSES = {"complete", "completed", "done", "ok", "success", "succeeded"}
DEFAULT_SKILLS_ROOT = Path("/local/skills")


def requested_skill_id(body: dict[str, Any]) -> str:
    value = str(body.get("skill_id") or body.get("skill") or "").strip().lower().replace("_", "-")
    return value if _SAFE_ID.fullmatch(value) else ""


def _skill_paths(root: Path, skill_id: str) -> Iterable[Path]:
    direct = (root / "custom" / skill_id / "SKILL.md", root / skill_id / "SKILL.md")
    seen: set[Path] = set()
    for path in (*direct, *sorted(root.glob(f"**/{skill_id}/SKILL.md"))):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        yield resolved


def skill_manifest(skill_id: str, *, skills_root: Path = DEFAULT_SKILLS_ROOT) -> dict[str, Any]:
    normalized = str(skill_id or "").strip().lower().replace("_", "-")
    missing = {"id": normalized, "available": False, "version": "", "source": ""}
    if not _SAFE_ID.fullmatch(normalized) or not skills_root.is_dir():
        return missing
    for path in _skill_paths(skills_root, normalized):
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")[:32_000]
            fields = {key: value.strip() for key, value in _FRONTMATTER_FIELD.findall(raw)}
            if fields.get("name", path.parent.name).lower().replace("_", "-") != normalized:
                continue
            relative = path.relative_to(skills_root.parent).as_posix()
            return {
                "id": normalized,
                "available": True,
                "version": fields.get("version", ""),
                "source": relative,
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
            }
        except OSError:
            continue
    return missing


def skill_directive(skill: dict[str, Any]) -> str:
    skill_id = str(skill.get("id") or "")
    return (
        f"Required skill contract: `{skill_id}`. Before execution, load that exact skill with "
        f"skill_view(name=\"{skill_id}\") and follow its SKILL.md instructions. "
        "Return explicit receipt fields for requested, available, loaded, and successfully_used; "
        "prose alone is not execution proof."
    )


def _skill_view_name(arguments: Any) -> str:
    parsed = arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (TypeError, ValueError):
            return ""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("name"), str):
        return ""
    name = parsed["name"].strip().lower().replace("_", "-")
    return name if _SAFE_ID.fullmatch(name) else ""


def _skill_view_succeeded(call: dict[str, Any]) -> bool:
    if call.get("error") not in (None, False, ""):
        return False
    status = str(call.get("status") or "").strip().lower()
    return status in _SUCCESSFUL_TOOL_STATUSES


def skill_receipt(skill: dict[str, Any], bridge_trace: dict[str, Any] | None) -> dict[str, Any]:
    skill_id = str(skill.get("id") or "")
    calls = bridge_trace.get("tool_calls") if isinstance(bridge_trace, dict) and isinstance(bridge_trace.get("tool_calls"), list) else []
    views = [call for call in calls if isinstance(call, dict) and str(call.get("name") or "").lower() in _SKILL_VIEW_TOOLS]
    matched_views = [call for call in views if _skill_view_name(call.get("arguments")) == skill_id]
    requested = bool(skill_id)
    available = bool(skill.get("available"))
    loaded = bool(matched_views)
    finish_reason = str((bridge_trace or {}).get("finish_reason") or (bridge_trace or {}).get("status") or "").strip().lower()
    run_succeeded = finish_reason in _SUCCESSFUL_TOOL_STATUSES
    successfully_used = available and run_succeeded and any(_skill_view_succeeded(call) for call in matched_views)
    return {
        **skill,
        "requested": requested,
        "available": available,
        "loaded": loaded,
        "successfully_used": successfully_used,
        "tool_seen": bool(views),
        "argument_matched": loaded,
        "used": successfully_used,
    }
