from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PUBLIC_ROUTE_CONTRACT_KEYS = (
    "kind",
    "route_id",
    "surface",
    "owner",
    "workspace_root",
    "cwd",
    "allowed_read_roots",
    "allowed_write_roots",
    "likely_paths",
    "lookup_handles",
    "caps",
    "provider_policy",
    "budget",
    "proof",
    "checks",
    "source_index",
    "entities",
    "reason",
)


def clipped(value: Any, limit: int = 200) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)] + "...[clipped]"


def contract_path(plugin_root: Path, value: Any) -> str:
    raw = str(value or ".").strip() or "."
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = plugin_root / path
    return str(path.resolve())


def rel_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def normalize_contract(raw: dict[str, Any], plugin_root: Path) -> dict[str, Any]:
    route_id = clipped(str(raw.get("route_id") or raw.get("id") or "").strip(), 160)
    surface = clipped(str(raw.get("surface") or "").strip(), 120)
    workspace_root = contract_path(plugin_root, raw.get("workspace_root") or ".")

    def paths(key: str, fallback: list[str]) -> list[str]:
        values = raw.get(key)
        if not isinstance(values, list):
            values = fallback
        return [contract_path(plugin_root, item) for item in values[:24]]

    raw_checks = raw.get("checks") if isinstance(raw.get("checks"), list) else []
    checks: list[dict[str, Any]] = []
    for item in raw_checks[:24]:
        if not isinstance(item, dict):
            continue
        check_id = clipped(str(item.get("id") or item.get("check_id") or "").strip(), 120)
        command = item.get("command") if isinstance(item.get("command"), list) else []
        clean_command = [clipped(str(part or ""), 240) for part in command[:16] if str(part or "").strip()]
        if not check_id or not clean_command:
            continue
        timeout = item.get("timeout_sec", item.get("timeoutSec", 30))
        try:
            timeout_sec = max(1, min(180, int(timeout)))
        except (TypeError, ValueError):
            timeout_sec = 30
        checks.append({
            "id": check_id,
            "command": clean_command,
            "timeout_sec": timeout_sec,
            "description": clipped(str(item.get("description") or ""), 240),
        })
    aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
    source_index = raw.get("source_index") if isinstance(raw.get("source_index"), dict) else {}
    return {
        "kind": "route-contract",
        "route_id": route_id,
        "surface": surface,
        "owner": clipped(str(raw.get("owner") or "").strip(), 160),
        "workspace_root": workspace_root,
        "cwd": workspace_root,
        "allowed_read_roots": paths("allowed_read_roots", [raw.get("workspace_root") or "."]),
        "allowed_write_roots": paths("allowed_write_roots", []),
        "likely_paths": [
            clipped(rel_path(item), 240)
            for item in (raw.get("likely_paths") if isinstance(raw.get("likely_paths"), list) else [])[:80]
            if rel_path(item)
        ],
        "lookup_handles": [clipped(str(item or ""), 80) for item in (raw.get("lookup_handles") if isinstance(raw.get("lookup_handles"), list) else [])[:24]],
        "caps": [clipped(str(item or ""), 80) for item in (raw.get("caps") if isinstance(raw.get("caps"), list) else [])[:24]],
        "aliases": [clipped(str(item or ""), 120) for item in aliases[:24]],
        "provider_policy": raw.get("provider_policy") if isinstance(raw.get("provider_policy"), dict) else {},
        "source_index": source_index,
        "budget": raw.get("budget") if isinstance(raw.get("budget"), dict) else {},
        "proof": [clipped(str(item or ""), 80) for item in (raw.get("proof") if isinstance(raw.get("proof"), list) else [])[:24]],
        "checks": checks,
        "entities": [
            {
                "id": clipped(str(item.get("id") or item.get("name") or "").strip(), 120),
                "name": clipped(str(item.get("name") or item.get("id") or "").strip(), 160),
                "kind": clipped(str(item.get("kind") or "runtime-entity").strip(), 80),
                "node_id": clipped(str(item.get("node_id") or item.get("nodeId") or item.get("id") or "").strip(), 120),
                "selector": clipped(str(item.get("selector") or item.get("target") or "").strip(), 160),
                "route_symbol": clipped(str(item.get("route_symbol") or item.get("routeSymbol") or "").strip(), 160),
                "symbols": [
                    clipped(str(symbol or "").strip(), 160)
                    for symbol in (item.get("symbols") if isinstance(item.get("symbols"), list) else [])[:12]
                    if str(symbol or "").strip()
                ],
                "match_terms": [
                    clipped(str(term or "").strip(), 160)
                    for term in (item.get("match_terms") if isinstance(item.get("match_terms"), list) else [])[:12]
                    if str(term or "").strip()
                ],
                "proof": [
                    clipped(str(proof or "").strip(), 120)
                    for proof in (item.get("proof") if isinstance(item.get("proof"), list) else [])[:12]
                    if str(proof or "").strip()
                ],
            }
            for item in (raw.get("entities") if isinstance(raw.get("entities"), list) else [])[:24]
            if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
        ],
        "reason": "resolved declarative wasm-agent route contract",
    }


def load_contracts(registry_path: Path, plugin_root: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    routes = payload.get("routes") if isinstance(payload, dict) else []
    if not isinstance(routes, list):
        return []
    contracts: list[dict[str, Any]] = []
    for item in routes[:80]:
        if not isinstance(item, dict):
            continue
        contract = normalize_contract(item, plugin_root)
        if contract.get("route_id") and contract.get("workspace_root"):
            contracts.append(contract)
    return contracts


def tokens_from_structured_value(value: Any) -> list[str]:
    tokens: list[str] = []
    if isinstance(value, dict):
        for key in ("route_id", "route", "surface", "surface_hint", "screen"):
            raw = str(value.get(key) or "").strip()
            if raw:
                tokens.append(raw)
        route_contract = value.get("route_contract")
        if isinstance(route_contract, dict):
            tokens.extend(tokens_from_structured_value(route_contract))
        for key in ("compact_state", "workspace", "active_space"):
            child = value.get(key)
            if isinstance(child, dict):
                tokens.extend(tokens_from_structured_value(child))
        return tokens
    if isinstance(value, str):
        for part in re.split(r"[\s,;]+", value):
            if ":" not in part:
                continue
            key, raw = part.split(":", 1)
            if key.strip().lower() in {"route", "route_id", "surface"} and raw.strip():
                tokens.append(raw.strip())
    return tokens


def route_tokens(action: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for source in (action, envelope):
        if isinstance(source, dict):
            tokens.extend(tokens_from_structured_value(source))
            tokens.extend(tokens_from_structured_value(source.get("state_summary")))
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        normalized = clipped(str(token or "").strip().lower(), 160)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def public_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: contract[key] for key in PUBLIC_ROUTE_CONTRACT_KEYS if key in contract}


def match_tokens(contract: dict[str, Any]) -> set[str]:
    values = {
        str(contract.get("route_id") or "").strip().lower(),
        str(contract.get("surface") or "").strip().lower(),
    }
    return {value for value in values if value}


def entity_match_tokens(contract: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    entities = contract.get("entities") if isinstance(contract.get("entities"), list) else []
    for item in entities[:24]:
        if not isinstance(item, dict):
            continue
        for key in ("name",):
            value = str(item.get(key) or "").strip().lower()
            if value:
                tokens.add(value)
        match_terms = item.get("match_terms") if isinstance(item.get("match_terms"), list) else []
        for term in match_terms[:12]:
            value = str(term or "").strip().lower()
            if value:
                tokens.add(value)
    return tokens


def resolve_runtime_entity_contract(text: str, contracts: list[dict[str, Any]]) -> dict[str, Any] | None:
    haystack = str(text or "").lower()
    if not haystack:
        return None
    for contract in contracts:
        for token in entity_match_tokens(contract):
            if token and re.search(rf"(?<![a-z0-9_-]){re.escape(token)}(?![a-z0-9_-])", haystack):
                return public_contract(contract)
    return None


def resolve_contract(
    contracts: list[dict[str, Any]],
    *,
    route_id: Any = "",
    surface: Any = "",
    surface_hint: Any = "",
    contract_hint: Any = None,
) -> dict[str, Any] | None:
    tokens: set[str] = set()
    for source in (
        {"route_id": route_id, "surface": surface},
        {"surface": surface_hint},
        contract_hint if isinstance(contract_hint, dict) else {},
    ):
        tokens.update(route_tokens({}, source))
    for contract in contracts:
        if tokens & match_tokens(contract):
            return public_contract(contract)
    return None


def requested_paths(action: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def visit(value: Any) -> None:
        if len(paths) >= 24:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"path", "root", "workspace_root", "cwd", "directory", "dir"} and isinstance(child, str):
                    paths.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value[:24]:
                visit(child)
        elif isinstance(value, str):
            for match in re.findall(r"(?<![A-Za-z0-9_./-])/(?:local|home|tmp|var|opt)/[A-Za-z0-9_./@+-]+", value):
                paths.append(match)

    visit(action)
    visit({"objective": envelope.get("objective"), "evidence_refs": envelope.get("evidence_refs")})
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        clean = clipped(str(path or "").strip(), 500)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def path_inside(path: Path, roots: list[str]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def explicit_route_ids(action: dict[str, Any], contracts: list[dict[str, Any]]) -> list[str]:
    known = {
        clipped(str(contract.get("route_id") or "").strip().lower(), 160)
        for contract in contracts
        if str(contract.get("route_id") or "").strip()
    }
    candidates: list[str] = []

    def visit(value: Any) -> None:
        if len(candidates) >= 24:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"route_id", "route", "target_route_id", "targetrouteid"} and isinstance(child, str):
                    candidates.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value[:24]:
                visit(child)

    visit({key: action.get(key) for key in ("route_id", "route", "target_route_id", "targetRouteId")})
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        normalized = clipped(str(candidate or "").strip().lower(), 160)
        if normalized in known and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def dispatch_workspace_contract(action: dict[str, Any], envelope: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_route_id = {
        str(contract.get("route_id") or "").strip().lower(): public_contract(contract)
        for contract in contracts
        if str(contract.get("route_id") or "").strip()
    }
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(contract: dict[str, Any] | None) -> None:
        if not isinstance(contract, dict):
            return
        route_id = str(contract.get("route_id") or "").strip().lower()
        if not route_id or route_id in seen:
            return
        seen.add(route_id)
        candidates.append(contract)

    for route_id in explicit_route_ids(action, contracts):
        add_candidate(by_route_id.get(route_id))
    tokens = set(route_tokens(
        {
            key: action.get(key)
            for key in ("route_id", "route", "surface", "surface_hint", "target_route_id", "targetRouteId")
        },
        {
            key: envelope.get(key)
            for key in ("route_id", "route", "surface", "surface_hint", "route_contract", "compact_state", "workspace", "active_space")
        },
    ))
    if tokens:
        for contract in contracts:
            if tokens & match_tokens(contract):
                add_candidate(public_contract(contract))
    # A client contract is only a selector hint. Authority, roots, checks, and
    # budgets must always come from the server-owned registry above.
    add_candidate(resolve_contract(
        contracts,
        route_id=action.get("route_id") or envelope.get("route_id") or envelope.get("route"),
        surface=action.get("surface") or envelope.get("surface"),
        contract_hint=envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else None,
    ))
    paths = requested_paths(action, envelope)
    if paths:
        resolved_paths: list[Path] = []
        for raw_path in paths:
            try:
                resolved_paths.append(Path(raw_path).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
        if resolved_paths:
            for contract in candidates:
                allowed_roots = contract.get("allowed_read_roots") if isinstance(contract.get("allowed_read_roots"), list) else []
                if all(path_inside(path, [str(root) for root in allowed_roots]) for path in resolved_paths):
                    return contract
    return candidates[0] if candidates else None
