"""Tool handlers for the Canva plugin."""

from __future__ import annotations

import json
from pathlib import Path

from .client import CanvaApiError, CanvaClient
from .runtime import (
    lookup_cached_asset,
    recent_local_assets,
    remember_uploaded_asset,
    workspace_canva_dir as _workspace_canva_dir,
    workspace_canva_files_dir as _workspace_canva_files_dir,
    workspace_canva_logs_dir as _workspace_canva_logs_dir,
    write_operation_log as _write_operation_log,
)


def _client() -> CanvaClient:
    return CanvaClient()


def migrate_workspace_layout(**kwargs) -> dict:
    workspace_dir = _workspace_canva_dir(**kwargs)
    files_dir = _workspace_canva_files_dir(**kwargs)
    logs_dir = _workspace_canva_logs_dir(**kwargs)
    moved = []
    skipped = []
    for entry in workspace_dir.iterdir():
        if entry.name in {"files", "logs"}:
            continue
        if not entry.is_file():
            skipped.append({"path": str(entry), "reason": "not_a_file"})
            continue
        target = files_dir / entry.name
        if target.exists():
            skipped.append({"path": str(entry), "reason": "target_exists", "target": str(target)})
            continue
        entry.replace(target)
        moved.append({"from": str(entry), "to": str(target)})
    return {
        "workspace_dir": str(workspace_dir),
        "files_dir": str(files_dir),
        "logs_dir": str(logs_dir),
        "moved": moved,
        "skipped": skipped,
    }


def _success(action: str, result=None, **payload) -> str:
    tool_kwargs = payload.pop("_tool_kwargs", {})
    response = {"ok": True, "action": action}
    if result is not None:
        response["result"] = result
    response.update(payload)
    log_path = _write_operation_log(action, response, **tool_kwargs)
    response["log_path"] = log_path
    response["workspace_dir"] = str(_workspace_canva_dir(**tool_kwargs))
    response["files_dir"] = str(_workspace_canva_files_dir(**tool_kwargs))
    response["logs_dir"] = str(_workspace_canva_logs_dir(**tool_kwargs))
    return json.dumps(response, ensure_ascii=False)


def _failure(action: str, message: str, **payload) -> str:
    tool_kwargs = payload.pop("_tool_kwargs", {})
    response = {"ok": False, "action": action, "error": message}
    response.update(payload)
    log_path = _write_operation_log(action, response, **tool_kwargs)
    response["log_path"] = log_path
    response["workspace_dir"] = str(_workspace_canva_dir(**tool_kwargs))
    response["files_dir"] = str(_workspace_canva_files_dir(**tool_kwargs))
    response["logs_dir"] = str(_workspace_canva_logs_dir(**tool_kwargs))
    return json.dumps(response, ensure_ascii=False)


def _extract_asset_id(payload: dict) -> str:
    for candidate in (
        payload.get("asset", {}).get("id"),
        payload.get("job", {}).get("asset", {}).get("id"),
        payload.get("result", {}).get("asset", {}).get("id"),
    ):
        if candidate:
            return str(candidate)
    return ""


_CUSTOM_DIMENSION_PRESETS = {
    "instagram-post": (1080, 1080),
    "instagram_square": (1080, 1080),
    "social-post": (1080, 1080),
    "social_post": (1080, 1080),
    "thumbnail": (1280, 720),
    "cover": (1920, 1080),
    "presentation-cover": (1920, 1080),
    "presentation_cover": (1920, 1080),
}

_NATIVE_CANVA_PRESETS = {"doc", "email", "presentation", "whiteboard"}


def _resolve_design_surface(*, preset_name: str = "", width: int = 0, height: int = 0) -> dict:
    preset = str(preset_name or "").strip().lower().replace(" ", "-")
    if preset in _CUSTOM_DIMENSION_PRESETS:
        resolved_width, resolved_height = _CUSTOM_DIMENSION_PRESETS[preset]
        return {"preset_name": "", "width": resolved_width, "height": resolved_height, "surface_source": f"alias:{preset}"}
    if preset in _NATIVE_CANVA_PRESETS:
        return {"preset_name": preset, "width": int(width or 0), "height": int(height or 0), "surface_source": f"native_preset:{preset}"}
    if preset:
        return {"preset_name": preset, "width": int(width or 0), "height": int(height or 0), "surface_source": f"raw_preset:{preset}"}
    return {"preset_name": "", "width": int(width or 0), "height": int(height or 0), "surface_source": "custom_dimensions"}


def _pick_recent_local_asset(**kwargs) -> dict:
    candidates = recent_local_assets(limit=10, **kwargs)
    if not candidates:
        return {}
    return candidates[0]


def _normalize_design_brief_payload(args: dict) -> dict:
    prompt = str(args.get("prompt", "") or "").strip()
    brief = {
        "objective": prompt,
        "format": str(args.get("format_hint", "") or "").strip(),
        "audience": "",
        "tone": "",
        "copy": {"headline": "", "support_text": "", "cta": ""},
        "assets": {
            "paths": list(args.get("asset_paths") or []),
            "urls": list(args.get("asset_urls") or []),
            "asset_id": str(args.get("asset_id", "") or "").strip(),
            "brand_template_id": str(args.get("brand_template_id", "") or "").strip(),
        },
        "export": {"format": "png", "target_dir": "/workspace/canva/files"},
        "notes": [],
        "allow_blank": bool(args.get("allow_blank", False)),
    }
    lower = prompt.lower()
    format_map = {
        "poster": "poster",
        "flyer": "poster",
        "instagram": "instagram-post",
        "social": "social-post",
        "thumbnail": "thumbnail",
        "cover": "cover",
        "presentation": "presentation-cover",
    }
    if not brief["format"]:
        for needle, value in format_map.items():
            if needle in lower:
                brief["format"] = value
                break
    tone_map = ["premium", "bold", "minimal", "clean", "corporate", "retail", "friendly", "luxury", "editorial"]
    for tone in tone_map:
        if tone in lower:
            brief["tone"] = tone
            break
    audience_markers = ["for ", "audience:"]
    for marker in audience_markers:
        if marker in lower:
            idx = lower.find(marker)
            snippet = prompt[idx + len(marker):].split(".")[0].split("\n")[0].strip(" :")
            if snippet:
                brief["audience"] = snippet
                break
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if lines:
        brief["copy"]["headline"] = lines[0][:120]
        if len(lines) > 1:
            brief["copy"]["support_text"] = lines[1][:240]
        if len(lines) > 2:
            brief["copy"]["cta"] = lines[2][:80]
    return brief


def _qa_brief(brief: dict) -> dict:
    score = 0
    total = 0
    checklist = []
    for key, label in (
        ("objective", "objective"),
        ("format", "format"),
        ("audience", "audience"),
        ("tone", "tone"),
    ):
        present = bool(str(brief.get(key, "") or "").strip())
        checklist.append({"field": label, "present": present})
        total += 10
        score += 10 if present else 0
    copy = brief.get("copy") or {}
    for key, weight in (("headline", 20), ("support_text", 10), ("cta", 10)):
        present = bool(str(copy.get(key, "") or "").strip())
        checklist.append({"field": f"copy.{key}", "present": present})
        total += weight
        score += weight if present else 0
    assets = brief.get("assets") or {}
    asset_ready = bool((assets.get("paths") or []) or (assets.get("urls") or []) or str(assets.get("asset_id", "") or "").strip())
    template_ready = bool(str(assets.get("brand_template_id", "") or "").strip())
    allow_blank = bool(brief.get("allow_blank"))
    creative_input_ready = asset_ready or template_ready or allow_blank
    checklist.append({"field": "assets_or_template", "present": creative_input_ready})
    total += 30
    score += 30 if creative_input_ready else 0
    normalized_score = int(round((score / total) * 100)) if total else 0
    ready = normalized_score >= 75 and bool(copy.get("headline")) and creative_input_ready
    missing = [item["field"] for item in checklist if not item["present"]]
    blocked_reason = ""
    if not creative_input_ready:
        blocked_reason = "No asset, reusable local asset, brand template, or explicit blank-canvas intent is available."
    return {
        "score": normalized_score,
        "ready": ready,
        "missing": missing,
        "checklist": checklist,
        "asset_ready": asset_ready,
        "template_ready": template_ready,
        "allow_blank": allow_blank,
        "blocked_reason": blocked_reason,
    }


def _resolve_or_create_asset(args: dict, **kwargs) -> dict:
    client = _client()
    asset_id = str(args.get("asset_id", "") or "").strip()
    if asset_id:
        return {"asset_id": asset_id, "source": "existing"}
    asset_path = str(args.get("asset_path", "") or "").strip()
    selected_local_asset = None
    upload_errors = []
    candidate_paths = []
    if asset_path:
        candidate_paths.append({"path": asset_path, "source": "explicit_asset_path"})
    else:
        for candidate in recent_local_assets(limit=10, **kwargs):
            candidate_paths.append({"path": str(candidate.get("path", "") or ""), "source": "recent_local_asset", "candidate": candidate})
    for candidate in candidate_paths:
        asset_path = str(candidate.get("path", "") or "").strip()
        if not asset_path:
            continue
        local_path = Path(asset_path)
        selected_local_asset = candidate.get("candidate") or {}
        cached = lookup_cached_asset(local_path, **kwargs)
        if cached.get("asset_id"):
            return {
                "asset_id": str(cached["asset_id"]),
                "source": "cached_local_asset",
                "local_asset_path": str(local_path),
                "cached_asset": cached,
                "selected_local_asset": selected_local_asset,
            }
        try:
            uploaded = client.upload_asset(file_path=local_path, name=str(args.get("title", "") or "") or local_path.stem)
            resolved_asset_id = _extract_asset_id(uploaded)
            if resolved_asset_id:
                cache_entry = remember_uploaded_asset(local_path, resolved_asset_id, name=str(args.get("title", "") or "") or local_path.stem, source="upload_asset", **kwargs)
            else:
                cache_entry = {}
            return {
                "asset_id": resolved_asset_id,
                "source": "uploaded_file" if candidate.get("source") == "explicit_asset_path" else "uploaded_recent_inbox_asset",
                "upload_result": uploaded,
                "local_asset_path": str(local_path),
                "cache_entry": cache_entry,
                "selected_local_asset": selected_local_asset,
            }
        except Exception as exc:
            upload_errors.append({"path": str(local_path), "error": str(exc)})
            if candidate.get("source") == "explicit_asset_path":
                break
    asset_url = str(args.get("asset_url", "") or "").strip()
    if asset_url:
        uploaded = client.upload_asset_from_url(url=asset_url, name=str(args.get("title", "") or "") or "canva-asset")
        return {"asset_id": _extract_asset_id(uploaded), "source": "uploaded_url", "upload_result": uploaded}
    return {
        "asset_id": "",
        "source": "none",
        "available_local_assets": recent_local_assets(limit=10, **kwargs),
        "upload_errors": upload_errors,
    }


def _playbook_response(playbook: str, args: dict, *, preset_name: str = "", width: int = 0, height: int = 0, **kwargs) -> str:
    try:
        requested_template_id = str(args.get("brand_template_id", "") or "").strip()
        brief = {
            "objective": str(args.get("title", "") or f"{playbook} design").strip(),
            "format": playbook,
            "audience": str(args.get("audience", "") or "").strip(),
            "tone": str(args.get("tone", "") or "").strip(),
            "copy": {
                "headline": str(args.get("headline", "") or "").strip(),
                "support_text": str(args.get("support_text", "") or "").strip(),
                "cta": str(args.get("cta", "") or "").strip(),
            },
            "assets": {
                "asset_id": str(args.get("asset_id", "") or "").strip(),
                "paths": [str(args.get("asset_path", "") or "").strip()] if str(args.get("asset_path", "") or "").strip() else [],
                "urls": [str(args.get("asset_url", "") or "").strip()] if str(args.get("asset_url", "") or "").strip() else [],
                "brand_template_id": requested_template_id,
            },
            "export": {
                "format": str(args.get("export_format", "png") or "png").strip(),
                "filename_prefix": str(args.get("filename_prefix", "") or "").strip(),
                "target_dir": "/workspace/canva/files",
            },
            "allow_blank": bool(args.get("allow_blank", False)),
        }
        asset_resolution = _resolve_or_create_asset(args, **kwargs)
        if asset_resolution.get("local_asset_path") and not brief["assets"]["paths"]:
            brief["assets"]["paths"] = [str(asset_resolution["local_asset_path"])]
        if asset_resolution.get("asset_id") and not brief["assets"]["asset_id"]:
            brief["assets"]["asset_id"] = str(asset_resolution["asset_id"])
        qa = _qa_brief(brief)
        surface = _resolve_design_surface(preset_name=preset_name, width=width, height=height)
        design_request = {
            "title": str(args.get("title", "") or brief["copy"]["headline"] or playbook.title()).strip(),
            "preset_name": surface["preset_name"],
            "width": surface["width"],
            "height": surface["height"],
            "asset_id": asset_resolution.get("asset_id", ""),
            "export_format": brief["export"]["format"],
            "filename_prefix": brief["export"]["filename_prefix"] or str(args.get("title", "") or playbook).strip().lower().replace(" ", "-"),
            "surface_source": surface["surface_source"],
        }
        recommendations = []
        available_local_assets = recent_local_assets(limit=10, **kwargs)
        if not qa["ready"]:
            recommendations.append("Brief is underspecified or blocked. Add missing creative input before creating or exporting any design.")
        if not design_request["asset_id"] and not requested_template_id and not bool(args.get("allow_blank", False)):
            recommendations.append("No asset or brand template is available. Do not create a blank design.")
        if brief["copy"]["headline"] and len(brief["copy"]["headline"]) > 60:
            recommendations.append("Shorten the headline for stronger Canva hierarchy.")
        if not qa["ready"] and not bool(args.get("allow_blank", False)):
            return _failure(
                action=f"make_{playbook}",
                message=qa["blocked_reason"] or "The Canva workflow is not executable yet.",
                brief=brief,
                qa=qa,
                asset_resolution=asset_resolution,
                available_local_assets=available_local_assets,
                recommended_workflow=[
                    "list_local_assets_or_stage_assets",
                    "reuse_asset_or_provide_brand_template",
                    "run_playbook_again",
                ],
                design_request=design_request,
                recommendations=recommendations,
                _tool_kwargs=kwargs,
            )
        return _success(
            action=f"make_{playbook}",
            result={
                "brief": brief,
                "qa": qa,
                "asset_resolution": asset_resolution,
                "recommended_workflow": [
                    "autofill_design" if requested_template_id else "reuse_asset",
                    "create_design_with_asset",
                    "inspect_design",
                    "export_final",
                ],
                "design_request": design_request,
                "recommendations": recommendations,
                "available_local_assets": available_local_assets,
                "execution_ready": True,
            },
            _tool_kwargs=kwargs,
        )
    except CanvaApiError as exc:
        return _failure(f"make_{playbook}", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure(f"make_{playbook}", f"Unexpected Canva playbook failure: {exc}", _tool_kwargs=kwargs)


def canva_get_capabilities(args: dict, **kwargs) -> str:
    try:
        result = _client().get_capabilities()
        return _success("get_capabilities", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("get_capabilities", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("get_capabilities", f"Unexpected Canva capabilities failure: {exc}", _tool_kwargs=kwargs)


def canva_create_design(args: dict, **kwargs) -> str:
    try:
        surface = _resolve_design_surface(
            preset_name=str(args.get("preset_name", "") or "").strip(),
            width=int(args.get("width", 0) or 0),
            height=int(args.get("height", 0) or 0),
        )
        preset_name = surface["preset_name"]
        width = int(surface["width"] or 0)
        height = int(surface["height"] or 0)
        if not preset_name and (width <= 0 or height <= 0):
            return _failure("create_design", "Provide preset_name or both width and height.", _tool_kwargs=kwargs)
        asset_id = str(args.get("asset_id", "") or "").strip()
        if not asset_id and not bool(args.get("allow_blank", False)):
            return _failure(
                "create_design",
                "Blank design creation is blocked by default. Provide asset_id or set allow_blank=true only when the user explicitly wants a blank canvas.",
                _tool_kwargs=kwargs,
            )
        result = _client().create_design(
            title=str(args.get("title", "") or ""),
            preset_name=preset_name,
            width=width,
            height=height,
            asset_id=asset_id,
        )
        return _success("create_design", result=result, resolved_surface=surface, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("create_design", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("create_design", f"Unexpected Canva create failure: {exc}", _tool_kwargs=kwargs)


def canva_list_designs(args: dict, **kwargs) -> str:
    try:
        result = _client().list_designs(
            query=str(args.get("query", "") or ""),
            ownership=str(args.get("ownership", "any") or "any"),
            sort_by=str(args.get("sort_by", "relevance") or "relevance"),
            limit=int(args.get("limit", 25) or 25),
            continuation=str(args.get("continuation", "") or ""),
        )
        return _success("list_designs", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("list_designs", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("list_designs", f"Unexpected Canva list failure: {exc}", _tool_kwargs=kwargs)


def canva_get_design(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        if not design_id:
            return _failure("get_design", "design_id is required.", _tool_kwargs=kwargs)
        client = _client()
        result = {"design": client.get_design(design_id)}
        if bool(args.get("include_pages")):
            result["pages"] = client.get_design_pages(design_id)
        if bool(args.get("include_export_formats")):
            result["export_formats"] = client.get_export_formats(design_id)
        return _success("get_design", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("get_design", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("get_design", f"Unexpected Canva get failure: {exc}", _tool_kwargs=kwargs)


def canva_update_design(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        if not design_id:
            return _failure("update_design", "design_id is required.", _tool_kwargs=kwargs)
        surface = _resolve_design_surface(
            preset_name=str(args.get("preset_name", "") or "").strip(),
            width=int(args.get("width", 0) or 0),
            height=int(args.get("height", 0) or 0),
        )
        preset_name = surface["preset_name"]
        width = int(surface["width"] or 0)
        height = int(surface["height"] or 0)
        if not preset_name and (width <= 0 or height <= 0):
            return _failure("update_design", "Provide preset_name or both width and height for the resize copy.", _tool_kwargs=kwargs)
        result = _client().resize_design(design_id=design_id, preset_name=preset_name, width=width, height=height)
        return _success("update_design", result=result, update_mode="resize_copy", resolved_surface=surface, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("update_design", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("update_design", f"Unexpected Canva update failure: {exc}", _tool_kwargs=kwargs)


def canva_export_design(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        format_type = str(args.get("format_type", "") or "").strip()
        if not design_id or not format_type:
            return _failure("export_design", "design_id and format_type are required.", _tool_kwargs=kwargs)
        export_spec = {"type": format_type}
        for key in ("pages", "width", "height", "quality", "export_quality", "transparent_background", "lossless", "as_single_image"):
            value = args.get(key)
            if value is not None and value != "":
                export_spec[key] = value
        download_dir = _workspace_canva_files_dir(**kwargs)
        result = _client().export_design(
            design_id=design_id,
            export_spec=export_spec,
            download_dir=download_dir,
            filename_prefix=str(args.get("filename_prefix", "") or design_id),
        )
        return _success("export_design", result=result, export_dir=str(download_dir), downloads=result.get("downloads", []), _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("export_design", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("export_design", f"Unexpected Canva export failure: {exc}", _tool_kwargs=kwargs)


def canva_list_export_formats(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        if not design_id:
            return _failure("list_export_formats", "design_id is required.", _tool_kwargs=kwargs)
        result = _client().get_export_formats(design_id)
        return _success("list_export_formats", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("list_export_formats", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("list_export_formats", f"Unexpected Canva export-format failure: {exc}", _tool_kwargs=kwargs)


def canva_upload_asset(args: dict, **kwargs) -> str:
    try:
        file_path = str(args.get("file_path", "") or "").strip()
        if not file_path:
            return _failure("upload_asset", "file_path is required.", _tool_kwargs=kwargs)
        result = _client().upload_asset(
            file_path=Path(file_path),
            name=str(args.get("name", "") or ""),
            tags=list(args.get("tags") or []),
        )
        return _success("upload_asset", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("upload_asset", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("upload_asset", f"Unexpected Canva asset upload failure: {exc}", _tool_kwargs=kwargs)


def canva_upload_asset_from_url(args: dict, **kwargs) -> str:
    try:
        url = str(args.get("url", "") or "").strip()
        name = str(args.get("name", "") or "").strip()
        if not url or not name:
            return _failure("upload_asset_from_url", "url and name are required.", _tool_kwargs=kwargs)
        result = _client().upload_asset_from_url(url=url, name=name, tags=list(args.get("tags") or []))
        return _success("upload_asset_from_url", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("upload_asset_from_url", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("upload_asset_from_url", f"Unexpected Canva URL asset upload failure: {exc}", _tool_kwargs=kwargs)


def canva_list_local_assets(args: dict, **kwargs) -> str:
    try:
        limit = int(args.get("limit", 10) or 10)
        result = {"assets": recent_local_assets(limit=limit, **kwargs)}
        return _success("list_local_assets", result=result, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("list_local_assets", f"Unexpected local asset listing failure: {exc}", _tool_kwargs=kwargs)


def canva_list_brand_templates(args: dict, **kwargs) -> str:
    try:
        result = _client().list_brand_templates(
            query=str(args.get("query", "") or ""),
            ownership=str(args.get("ownership", "any") or "any"),
            dataset=str(args.get("dataset", "any") or "any"),
            sort_by=str(args.get("sort_by", "relevance") or "relevance"),
            limit=int(args.get("limit", 25) or 25),
            continuation=str(args.get("continuation", "") or ""),
        )
        return _success("list_brand_templates", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("list_brand_templates", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("list_brand_templates", f"Unexpected Canva brand-template listing failure: {exc}", _tool_kwargs=kwargs)


def canva_get_brand_template_dataset(args: dict, **kwargs) -> str:
    try:
        brand_template_id = str(args.get("brand_template_id", "") or "").strip()
        if not brand_template_id:
            return _failure("get_brand_template_dataset", "brand_template_id is required.", _tool_kwargs=kwargs)
        result = _client().get_brand_template_dataset(brand_template_id)
        return _success("get_brand_template_dataset", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("get_brand_template_dataset", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("get_brand_template_dataset", f"Unexpected Canva dataset lookup failure: {exc}", _tool_kwargs=kwargs)


def canva_autofill_design(args: dict, **kwargs) -> str:
    try:
        brand_template_id = str(args.get("brand_template_id", "") or "").strip()
        data = args.get("data")
        if not brand_template_id or not isinstance(data, dict) or not data:
            return _failure("autofill_design", "brand_template_id and a non-empty data object are required.", _tool_kwargs=kwargs)
        result = _client().create_autofill_design(
            brand_template_id=brand_template_id,
            data=data,
            title=str(args.get("title", "") or ""),
        )
        return _success("autofill_design", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("autofill_design", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("autofill_design", f"Unexpected Canva autofill failure: {exc}", _tool_kwargs=kwargs)


def canva_create_comment_thread(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        message_plaintext = str(args.get("message_plaintext", "") or "").strip()
        if not design_id or not message_plaintext:
            return _failure("create_comment_thread", "design_id and message_plaintext are required.", _tool_kwargs=kwargs)
        result = _client().create_comment_thread(
            design_id=design_id,
            message_plaintext=message_plaintext,
            assignee_id=str(args.get("assignee_id", "") or ""),
        )
        return _success("create_comment_thread", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("create_comment_thread", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("create_comment_thread", f"Unexpected Canva comment-thread creation failure: {exc}", _tool_kwargs=kwargs)


def canva_get_comment_thread(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        thread_id = str(args.get("thread_id", "") or "").strip()
        if not design_id or not thread_id:
            return _failure("get_comment_thread", "design_id and thread_id are required.", _tool_kwargs=kwargs)
        result = _client().get_comment_thread(design_id=design_id, thread_id=thread_id)
        return _success("get_comment_thread", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("get_comment_thread", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("get_comment_thread", f"Unexpected Canva comment-thread lookup failure: {exc}", _tool_kwargs=kwargs)


def canva_create_comment_reply(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        thread_id = str(args.get("thread_id", "") or "").strip()
        message_plaintext = str(args.get("message_plaintext", "") or "").strip()
        if not design_id or not thread_id or not message_plaintext:
            return _failure("create_comment_reply", "design_id, thread_id, and message_plaintext are required.", _tool_kwargs=kwargs)
        result = _client().create_comment_reply(
            design_id=design_id,
            thread_id=thread_id,
            message_plaintext=message_plaintext,
        )
        return _success("create_comment_reply", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("create_comment_reply", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("create_comment_reply", f"Unexpected Canva comment-reply creation failure: {exc}", _tool_kwargs=kwargs)


def canva_list_comment_replies(args: dict, **kwargs) -> str:
    try:
        design_id = str(args.get("design_id", "") or "").strip()
        thread_id = str(args.get("thread_id", "") or "").strip()
        if not design_id or not thread_id:
            return _failure("list_comment_replies", "design_id and thread_id are required.", _tool_kwargs=kwargs)
        result = _client().list_comment_replies(
            design_id=design_id,
            thread_id=thread_id,
            continuation=str(args.get("continuation", "") or ""),
        )
        return _success("list_comment_replies", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("list_comment_replies", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("list_comment_replies", f"Unexpected Canva comment-replies listing failure: {exc}", _tool_kwargs=kwargs)


def canva_get_asset(args: dict, **kwargs) -> str:
    try:
        asset_id = str(args.get("asset_id", "") or "").strip()
        if not asset_id:
            return _failure("get_asset", "asset_id is required.", _tool_kwargs=kwargs)
        return _success("get_asset", result=_client().get_asset(asset_id), _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("get_asset", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("get_asset", f"Unexpected Canva asset lookup failure: {exc}", _tool_kwargs=kwargs)


def canva_update_asset(args: dict, **kwargs) -> str:
    try:
        asset_id = str(args.get("asset_id", "") or "").strip()
        if not asset_id:
            return _failure("update_asset", "asset_id is required.", _tool_kwargs=kwargs)
        result = _client().update_asset(
            asset_id=asset_id,
            name=str(args.get("name", "") or ""),
            tags=args.get("tags"),
        )
        return _success("update_asset", result=result, _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("update_asset", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("update_asset", f"Unexpected Canva asset update failure: {exc}", _tool_kwargs=kwargs)


def canva_delete_asset(args: dict, **kwargs) -> str:
    try:
        asset_id = str(args.get("asset_id", "") or "").strip()
        if not asset_id:
            return _failure("delete_asset", "asset_id is required.", _tool_kwargs=kwargs)
        return _success("delete_asset", result=_client().delete_asset(asset_id), _tool_kwargs=kwargs)
    except CanvaApiError as exc:
        return _failure("delete_asset", str(exc), status=exc.status, payload=exc.payload, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("delete_asset", f"Unexpected Canva asset deletion failure: {exc}", _tool_kwargs=kwargs)


def canva_normalize_design_brief(args: dict, **kwargs) -> str:
    try:
        prompt = str(args.get("prompt", "") or "").strip()
        if not prompt:
            return _failure("normalize_design_brief", "prompt is required.", _tool_kwargs=kwargs)
        brief = _normalize_design_brief_payload(args)
        return _success("normalize_design_brief", result={"brief": brief, "qa": _qa_brief(brief)}, _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("normalize_design_brief", f"Unexpected Canva brief normalization failure: {exc}", _tool_kwargs=kwargs)


def canva_qa_design_brief(args: dict, **kwargs) -> str:
    try:
        brief = args.get("brief")
        if not isinstance(brief, dict) or not brief:
            return _failure("qa_design_brief", "brief must be a non-empty object.", _tool_kwargs=kwargs)
        return _success("qa_design_brief", result=_qa_brief(brief), _tool_kwargs=kwargs)
    except Exception as exc:
        return _failure("qa_design_brief", f"Unexpected Canva brief QA failure: {exc}", _tool_kwargs=kwargs)


def canva_make_poster_from_asset(args: dict, **kwargs) -> str:
    return _playbook_response(
        "poster_from_asset",
        args,
        width=int(args.get("width", 1408) or 1408),
        height=int(args.get("height", 768) or 768),
        **kwargs,
    )


def canva_make_social_post(args: dict, **kwargs) -> str:
    return _playbook_response(
        "social_post",
        args,
        width=int(args.get("width", 1080) or 1080),
        height=int(args.get("height", 1080) or 1080),
        **kwargs,
    )


def canva_make_cover_from_image(args: dict, **kwargs) -> str:
    return _playbook_response(
        "cover_from_image",
        args,
        width=int(args.get("width", 1920) or 1920),
        height=int(args.get("height", 1080) or 1080),
        **kwargs,
    )
