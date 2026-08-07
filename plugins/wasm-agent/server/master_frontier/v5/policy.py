from __future__ import annotations

from typing import Any

from .. import authority
from . import task_policy, tool_stage


TOOLS = authority.V5_TOOLS
SAFE_AUTONOMOUS_EDIT_OPERATIONS = ("create", "replace", "append")
TOOL_REQUIRED_REPAIR_CODES = frozenset({
    "fresh_tool_evidence_required",
    "implementation_action_required",
    "operation_proof_required",
    "patch_missing_operations",
    "verification_proof_required",
    "worktree_postimage_mismatch",
})


def allowed_edit_operations(route: dict[str, Any] | None = None) -> tuple[str, ...]:
    scoped = route if isinstance(route, dict) else {}
    declared = scoped.get("allowed_edit_operations")
    if isinstance(declared, list):
        allowed = tuple(
            name for name in ("create", "replace", "append", "move", "delete")
            if name in {str(item or "").strip().lower() for item in declared}
        )
        return allowed
    if task_policy.llm_autonomous(scoped) and task_policy.requires_mutation(scoped):
        return SAFE_AUTONOMOUS_EDIT_OPERATIONS
    return ("create", "replace", "append", "move", "delete")


def tool_descriptors() -> list[dict[str, Any]]:
    return [
        {"name": "search", "description": "Find relevant files, source text, and symbols in the routed workspace.", "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}}},
        {"name": "read", "description": "Read exact bounded content from a routed workspace file.", "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}}},
        {"name": "memory", "description": "Read exact recent turns from one account-scoped session pointer listed in session_memory.", "input_schema": {"type": "object", "required": ["pointer"], "properties": {"pointer": {"type": "string", "pattern": "^sm1\\.[A-Za-z0-9_-]+$"}, "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "additionalProperties": False}},
        {"name": "inspect", "description": "Inspect a live runtime entity. Returns a bounded snapshot; pass its opaque proof_id to resolve scoped proof.", "input_schema": {"type": "object", "required": ["target", "id"], "properties": {"target": {"type": "string", "enum": ["run", "service", "device", "application", "runtime_entity"]}, "id": {"type": "string", "minLength": 1, "maxLength": 120}, "proof_id": {"type": "string", "pattern": "^run-store-[0-9a-f]{24}$"}, "fields": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}},
        {"name": "browser", "description": "Inspect or operate the user-authorized browser through bounded CDP actions. Snapshot first and use returned element refs; no arbitrary script execution.", "input_schema": {"type": "object", "required": ["operation"], "properties": {"operation": {"type": "string", "enum": ["snapshot", "navigate", "click", "type", "key"]}, "url": {"type": "string", "maxLength": 2000}, "ref": {"type": "integer", "minimum": 1, "maximum": 160}, "value": {"type": "string", "maxLength": 4000}, "key": {"type": "string", "maxLength": 80}}, "additionalProperties": False}},
        {"name": "client", "description": "Inspect or control the live Electron application client. Use this—not browser/CDP—to open an app widget or navigate its native Browser widget. Actions return an acknowledged, failed, or pending command receipt.", "input_schema": {"type": "object", "required": ["operation"], "properties": {"operation": {"type": "string", "enum": ["inspect", "open_widget", "browser_navigate", "command_status"]}, "client_id": {"type": "string", "maxLength": 120}, "widget_id": {"type": "string", "maxLength": 80}, "url": {"type": "string", "maxLength": 2000}, "command_id": {"type": "string", "maxLength": 120}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False}},
        {"name": "edit", "description": "Create, edit, move, or delete files through one bounded route-scoped transaction. Append uses content. Replace may use unique find+replace or expected_sha256+content for a whole-file postimage. Bind edits to observed content with expected_sha256 or expected_absent.", "input_schema": {"type": "object", "required": ["operations"], "properties": {"operations": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "object", "required": ["op", "path"], "properties": {"op": {"type": "string", "enum": ["create", "replace", "append", "move", "delete"]}, "path": {"type": "string"}, "destination": {"type": "string"}, "content": {"type": "string", "minLength": 1}, "find": {"type": "string"}, "replace": {"type": "string"}, "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "expected_absent": {"type": "boolean"}}, "additionalProperties": False}}, "dry_run": {"type": "boolean"}}, "additionalProperties": False}},
        {"name": "test", "description": "Run one focused check registered by the resolved route contract.", "input_schema": {"type": "object", "required": ["check_id"], "properties": {"check_id": {"type": "string"}}, "additionalProperties": False}},
        {"name": "diff", "description": "Inspect the current route-scoped git diff summary and changed files.", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "prove", "description": "Collect route, timeline, checks, and exact usage proof for this run and session.", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    ]


def executive_descriptor() -> dict[str, Any]:
    fields = {name: {"type": "string", "maxLength": limit} for name, limit in {
        "goal": 1200, "situation": 2400, "plan": 2400, "hypotheses": 2000,
        "open": 1600, "next": 1200, "done": 1600,
    }.items()}
    fields["outcomes"] = {
        "type": "array", "maxItems": 12, "items": {
            "type": "object", "required": ["id", "state", "objective"],
            "properties": {
                "id": {"type": "string", "maxLength": 80},
                "state": {"type": "string", "enum": ["open", "done", "dropped", "blocked"]},
                "objective": {"type": "string", "maxLength": 600},
                "requires": {"type": "string", "enum": ["search", "read", "memory", "inspect", "browser", "client", "edit", "test", "diff", "prove"]},
                "evidence": {"type": "string", "maxLength": 600},
                "reason": {"type": "string", "maxLength": 600},
            }, "additionalProperties": False,
        },
    }
    fields["decision"] = {
        "type": "object", "required": ["state", "candidate"],
        "properties": {
            "state": {"type": "string", "enum": ["selected", "blocked", "rejected", "overscoped"]},
            "candidate": {"type": "string", "maxLength": 1200},
            "targets": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 240}},
            "acceptance": {"type": "string", "maxLength": 1600},
            "blocker": {"type": "string", "maxLength": 1200},
            "next_action": {"type": "string", "maxLength": 600},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "additionalProperties": False,
    }
    return {
        "name": "checkpoint",
        "description": "Replace your durable executive capsule, optional outcomes, and operational decision. A decision records candidate, target paths, acceptance criterion, blocker, next action, and confidence without hidden reasoning.",
        "input_schema": {"type": "object", "properties": fields, "additionalProperties": False},
    }


def descriptors_for(route: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    descriptors = [item for item in tool_descriptors() if authority.tool_allowed(item["name"], route)]
    if isinstance(route, dict):
        check_ids = [
            str(item.get("id") or "").strip()
            for item in (route.get("checks") or [])[:24]
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        test = next((item for item in descriptors if item["name"] == "test"), None)
        memory = next((item for item in descriptors if item["name"] == "memory"), None)
        manifest = route.get("session_memory") if isinstance(route.get("session_memory"), dict) else {}
        pointers = [
            str(item.get("p") or "")
            for item in (manifest.get("sessions") if isinstance(manifest.get("sessions"), list) else [])[:24]
            if isinstance(item, dict) and str(item.get("p") or "")
        ]
        if memory is not None and pointers:
            memory["input_schema"]["properties"]["pointer"]["enum"] = pointers
        evidence_paths = list(dict.fromkeys(
            str(path).strip()
            for item in (route.get("checks") or [])[:24]
            if isinstance(item, dict)
            for path in (item.get("evidence_paths") or [])[:12]
            if str(path).strip()
        ))[:24]
        read = next((item for item in descriptors if item["name"] == "read"), None)
        if read is not None and evidence_paths:
            read["description"] += " Required implementation evidence paths: " + ", ".join(evidence_paths) + "."
        if test is not None and check_ids:
            test["input_schema"]["properties"]["check_id"]["enum"] = check_ids
            check_surfaces = []
            for item in (route.get("checks") or [])[:24]:
                if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                    continue
                paths = [
                    str(path).strip() for path in (item.get("evidence_paths") or [])[:12]
                    if str(path).strip()
                ]
                check_surfaces.append(
                    str(item["id"]).strip() + (f" (evidence: {', '.join(paths)})" if paths else "")
                )
            test["description"] += " Allowed checks: " + "; ".join(check_surfaces) + "."
    if isinstance(route, dict) and task_policy.llm_autonomous(route) and task_policy.requires_mutation(route):
        edit = next((item for item in descriptors if item["name"] == "edit"), None)
        if edit is not None:
            edit["input_schema"]["properties"].pop("dry_run", None)
            edit["input_schema"]["properties"]["operations"]["items"]["properties"]["op"]["enum"] = list(allowed_edit_operations(route))
    if isinstance(route, dict) and str((route.get("task_contract") or {}).get("decision_mode") or "") == "llm_autonomous":
        descriptors.insert(0, executive_descriptor())
    return descriptors


def active_descriptors(route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = descriptors_for(route)
    names = tool_stage.active_names(route, state, [item["name"] for item in descriptors])
    active = [item for item in descriptors if item["name"] in names]
    read = next((item for item in active if item["name"] == "read"), None)
    error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    existing_targets = sorted({
        str(path).strip() for path in (error.get("durable_targets") or []) if str(path).strip()
    }) if error.get("code") == "patch_preimage_exists" else []
    if read is not None and existing_targets:
        read["input_schema"]["properties"]["path"]["enum"] = existing_targets
        read["input_schema"]["properties"].pop("start_line", None)
        read["input_schema"]["properties"].pop("end_line", None)
        read["description"] += " Read the complete existing edit target now: " + ", ".join(existing_targets) + "."
    focus_owners = sorted(tool_stage.unresolved_focus_owner_paths(state))
    if read is not None and focus_owners and not existing_targets:
        read["input_schema"]["properties"]["path"]["enum"] = focus_owners
        read["input_schema"]["properties"].pop("start_line", None)
        read["input_schema"]["properties"].pop("end_line", None)
        read["description"] += " Read the complete discovered owner now: " + ", ".join(focus_owners) + "."
    missing = tool_stage.missing_declared_evidence(route, state)
    if read is not None and missing and missing != ["owner:uncovered"]:
        read["description"] += " Read these exact missing ranges next: " + ", ".join(missing) + "."
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    required_owners = {
        str(path).strip() for path in (route.get("required_owner_paths") or []) if str(path).strip()
    }
    changed = {str(path).strip() for path in (ledger.get("changed_files") or []) if str(path).strip()}
    proven_owners = tool_stage.owner_reads_after_latest_mutation(state, required_owners, changed)
    missing_owners = sorted(required_owners - changed - proven_owners)
    revision = int(ledger.get("revision") or 0)
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    repairing_failed_check = check.get("rev") == revision and check.get("ok") is False
    if missing_owners and revision > 0 and not repairing_failed_check and read is not None:
        read["input_schema"]["properties"]["path"]["enum"] = missing_owners
        read["input_schema"]["properties"].pop("start_line", None)
        read["input_schema"]["properties"].pop("end_line", None)
        read["description"] += " Read the complete required owner now: " + ", ".join(missing_owners) + "."
    edit = next((item for item in active if item["name"] == "edit"), None)
    if edit is not None and revision > 0 and missing_owners and not repairing_failed_check:
        operation = edit["input_schema"]["properties"]["operations"]["items"]
        operation["properties"]["path"]["enum"] = missing_owners
        operation["properties"]["op"]["enum"] = ["replace"]
        operation["required"] = ["op", "path"]
        operation["properties"].pop("expected_sha256", None)
        operation["properties"].pop("expected_absent", None)
        edit["description"] = (
            "Update the required owner from the immediately preceding complete read. Prefer the smallest unique "
            "find/replace; use content only when a whole-file replacement is necessary. The runtime binds the "
            "observed SHA precondition automatically. Exact owner: "
            + ", ".join(missing_owners) + "."
        )
    repair_paths = sorted(tool_stage.existing_target_repair_paths(state))
    if edit is not None and repair_paths:
        operation = edit["input_schema"]["properties"]["operations"]["items"]
        operation["properties"]["path"]["enum"] = repair_paths
        operation["properties"]["op"]["enum"] = ["replace"]
        edit["description"] = (
            "Update only the exact existing target from the immediately preceding complete read. Prefer a small "
            "unique find/replace; the runtime binds its observed SHA automatically. Exact target: "
            + ", ".join(repair_paths) + "."
        )
    return active


def provider_tools(route: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}} for item in descriptors_for(route)]


def active_provider_tools(route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}} for item in active_descriptors(route, state)]


def provider_tool_choice(state: dict[str, Any]) -> str:
    error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    return "required" if str(error.get("code") or "") in TOOL_REQUIRED_REPAIR_CODES else "auto"


def allowed(name: str, route: dict[str, Any] | None = None) -> bool:
    # The loop uses the route-less form only to recognize the fixed vocabulary.
    # Execution must always use the route-aware form below.
    if name == "checkpoint":
        return route is None or bool(isinstance(route, dict) and str((route.get("task_contract") or {}).get("decision_mode") or "") == "llm_autonomous")
    return authority.known_tool(name) if route is None else authority.tool_allowed(name, route)
