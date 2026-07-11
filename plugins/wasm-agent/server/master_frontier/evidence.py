from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


SCHEMA = "EVIDENCE/1"
MAX_EVIDENCE_BYTES = 64_000
MAX_MODEL_EVIDENCE_BYTES = 12_000
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".md", ".html", ".css", ".toml", ".yaml", ".yml"}
SECRET = re.compile(r"(?i)(api[_-]?key|authorization|token|password)\s*[:=]\s*[^\s,;]+")
QUERY_STOPWORDS = {
    "about", "adjacent", "analysis", "component", "definition", "error", "files",
    "handling", "input", "logic", "presentation", "props", "referencing", "render",
    "results", "route", "summary", "tests", "that", "under", "within",
}


class EvidenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


@dataclass
class DiscoveryJournal:
    """Persistable idempotency/order guard for interruption and late receipts."""
    state_revision: int
    cancelled: bool = False
    completed: dict[str, dict[str, Any]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def accept(self, operation_id: str, receipt_revision: int, receipt: dict[str, Any]) -> dict[str, Any] | None:
        if self.cancelled or receipt_revision != self.state_revision: return None
        if operation_id in self.completed: return self.completed[operation_id]
        self.completed[operation_id] = receipt; self.order.append(operation_id)
        return receipt

    def cancel(self) -> None:
        self.cancelled = True

    def checkpoint(self) -> dict[str, Any]:
        return {"state_revision": self.state_revision, "cancelled": self.cancelled, "completed": self.completed, "order": self.order}

    @classmethod
    def restore(cls, value: dict[str, Any]) -> "DiscoveryJournal":
        return cls(int(value.get("state_revision") or 0), bool(value.get("cancelled")), dict(value.get("completed") or {}), list(value.get("order") or []))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def redact(text: str) -> str:
    return SECRET.sub(lambda m: m.group(1) + "=[REDACTED]", text)


def content_handle(item: dict[str, Any], *, route_id: str, workspace_scope: str, freshness: dict[str, Any]) -> str:
    bound = {"content": item.get("excerpt", ""), "file": item.get("file", ""), "line": item.get("line"), "symbol": item.get("symbol", ""), "route_id": route_id, "workspace_scope": workspace_scope, "freshness": freshness}
    return "sha256:" + hashlib.sha256(canonical(bound)).hexdigest()


def validate(packet: dict[str, Any], *, max_bytes: int = MAX_EVIDENCE_BYTES) -> dict[str, Any]:
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        raise EvidenceError("evidence_schema_invalid", "Evidence must use EVIDENCE/1.")
    for key in ("operation_id", "request_id", "route_id", "workspace_scope", "capability_used"):
        if not str(packet.get(key) or ""): raise EvidenceError("evidence_identity_missing", f"{key} is required.")
    for key in ("searched_roots", "excluded_roots", "suboperations", "matches", "coverage", "limitations", "contradictions", "detail_refs"):
        if not isinstance(packet.get(key), list): raise EvidenceError("evidence_field_invalid", f"{key} must be a list.")
    handles: set[str] = set()
    for item in packet["matches"]:
        expected = content_handle(item, route_id=packet["route_id"], workspace_scope=packet["workspace_scope"], freshness=packet["freshness"])
        if item.get("handle") != expected: raise EvidenceError("evidence_integrity_failed", "Evidence handle does not bind content and scope.")
        if expected in handles: raise EvidenceError("evidence_handle_duplicate", "Evidence handles must be unique.")
        handles.add(expected)
    if len(canonical(packet)) > max_bytes: raise EvidenceError("evidence_byte_limit", "Evidence packet exceeds its byte bound.")
    return packet


def model_projection(packet: dict[str, Any], *, max_bytes: int = MAX_MODEL_EVIDENCE_BYTES) -> dict[str, Any]:
    validate(packet)
    projected = deepcopy(packet)
    projected["model_visible"] = True
    while len(canonical(projected)) > max_bytes and projected["matches"]:
        removed = projected["matches"].pop()
        projected["detail_refs"].append({"handle": removed["handle"], "reason": "model_projection_byte_bound"})
    if len(canonical(projected)) > max_bytes:
        projected["suboperations"] = [
            {key: item.get(key) for key in ("lane", "status", "count")}
            for item in projected["suboperations"]
            if isinstance(item, dict)
        ]
    if len(canonical(projected)) > max_bytes:
        raise EvidenceError("model_evidence_byte_limit", "Evidence metadata cannot fit the model projection bound.")
    return projected


def merge(first: dict[str, Any], second: dict[str, Any], *, max_bytes: int = MAX_EVIDENCE_BYTES) -> dict[str, Any]:
    validate(first, max_bytes=max_bytes); validate(second, max_bytes=max_bytes)
    if (first["route_id"], first["workspace_scope"]) != (second["route_id"], second["workspace_scope"]):
        raise EvidenceError("evidence_scope_mismatch", "Compound receipts from different scopes cannot be merged.")
    merged = {**second, "operation_id": first["operation_id"] + "+" + second["operation_id"]}
    for key in ("searched_roots", "excluded_roots", "limitations", "contradictions"):
        merged[key] = list(dict.fromkeys([*first[key], *second[key]]))
    merged["suboperations"] = [*first["suboperations"], *second["suboperations"]]
    coverage_by_value = {
        canonical(item): item
        for item in [*first["coverage"], *second["coverage"]]
        if isinstance(item, dict)
    }
    merged["coverage"] = list(coverage_by_value.values())
    merged["detail_refs"] = [*first["detail_refs"], *second["detail_refs"]]
    by_handle = {item["handle"]: item for item in [*first["matches"], *second["matches"]]}
    merged["matches"] = list(by_handle.values())
    merged["query_interpretation"] = {"original": first["query_interpretation"].get("original"), "attempted": list(dict.fromkeys([*first["query_interpretation"].get("attempted", []), *second["query_interpretation"].get("attempted", [])]))}
    while len(canonical(merged)) > max_bytes and merged["matches"]:
        removed = merged["matches"].pop(); merged["detail_refs"].append({"handle": removed["handle"], "reason": "merged_packet_byte_bound"})
    return validate(merged, max_bytes=max_bytes)


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _query_patterns(query: str, interpretations: list[Any]) -> list[tuple[str, re.Pattern[str]]]:
    phrases = [query, *[str(item).strip() for item in interpretations if str(item).strip()]]
    atoms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", query.lower()):
        if len(token) >= 4 and token not in QUERY_STOPWORDS:
            atoms.extend((token, token.replace("-", " ").replace("_", " ")))
    terms = list(dict.fromkeys([*phrases, *atoms]))[:24]
    return [(term, re.compile(re.escape(term), re.IGNORECASE)) for term in terms]


def compound_discover(
    request: dict[str, Any], route: dict[str, Any], *,
    semantic_search: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cancelled: Callable[[], bool] | None = None, monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started = monotonic(); cancelled = cancelled or (lambda: False)
    operation_id = str(request.get("operation_id") or ""); request_id = str(request.get("request_id") or "")
    query = str(request.get("query") or "").strip()
    root = Path(str(route.get("workspace_root") or "")).resolve()
    if not operation_id or not request_id or not query or not root.is_dir():
        raise EvidenceError("discovery_request_invalid", "Operation, request, query, and workspace are required.")
    max_results = max(1, min(50, int(request.get("max_results") or 12)))
    max_files = max(1, min(20_000, int(request.get("max_files") or 4000)))
    max_bytes = max(1024, min(MAX_EVIDENCE_BYTES, int(request.get("max_bytes") or MAX_EVIDENCE_BYTES)))
    timeout_ms = max(1, min(30_000, int(request.get("timeout_ms") or 5000)))
    policy = route.get("source_index") if isinstance(route.get("source_index"), dict) else {}
    includes = [str(item) for item in policy.get("include_roots") or ["."]]
    excludes = [str(item).replace("\\", "/") for item in policy.get("exclude_globs") or []]
    allowed = [Path(str(item)).resolve() for item in route.get("allowed_read_roots") or [root]]
    searched: list[str] = []; excluded_roots: list[str] = list(excludes); subops: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []; limitations: list[str] = []; lanes: dict[str, str] = {}
    freshness = {"state": "unavailable", "trusted": False}

    def stop() -> None:
        if cancelled(): raise EvidenceError("discovery_cancelled", "Compound discovery was cancelled.")
        if (monotonic() - started) * 1000 > timeout_ms: raise EvidenceError("discovery_timeout", "Compound discovery exceeded its deadline.")

    stop()
    if semantic_search:
        stop(); semantic = semantic_search({"query": query, "limit": max_results, "structural": True})
        freshness = semantic.get("freshness") if isinstance(semantic.get("freshness"), dict) else freshness
        ok = bool(semantic.get("ok")) and freshness.get("trusted") is True
        lanes["semantic"] = "searched" if ok else str(semantic.get("code") or "unavailable")
        subops.append({"lane": "semantic", "status": lanes["semantic"], "count": len(semantic.get("items") or [])})
        if ok:
            for raw in semantic.get("items") or []:
                if isinstance(raw, dict) and raw.get("file"):
                    matches.append({"file": str(raw["file"]), "line": raw.get("line"), "symbol": str(raw.get("name") or raw.get("qualified_name") or ""), "excerpt": redact(str(raw.get("summary") or raw.get("name") or ""))[:1200], "module": str(raw.get("module") or ""), "owner": str(route.get("owner") or ""), "classification": "direct", "trust": "untrusted_source"})
        else: limitations.append("semantic code memory is stale or unavailable; deterministic route fallback used")
    else:
        lanes["semantic"] = "unavailable"; subops.append({"lane": "semantic", "status": "unavailable", "count": 0}); limitations.append("semantic search unavailable")

    interpretations = request.get("interpretations") if isinstance(request.get("interpretations"), list) else []
    patterns = _query_patterns(query, interpretations)
    terms = [term for term, _pattern in patterns]
    symbol_pattern = re.compile(r"^\s*(?:class|def|function|const|let|var|interface|type)\s+([A-Za-z_$][\w$]*)")
    files_seen = 0; total_read = 0
    for include in sorted(includes):
        base = (root / include).resolve()
        if not _inside(base, allowed) or not base.exists(): excluded_roots.append(include); continue
        searched.append(str(base.relative_to(root)) if base != root else ".")
        iterator = [base] if base.is_file() else sorted(path for path in base.rglob("*") if path.is_file())
        for path in iterator:
            stop(); rel = str(path.relative_to(root)).replace("\\", "/")
            if any(fnmatch.fnmatch(rel, pattern.lstrip("./")) for pattern in excludes): continue
            if path.suffix.lower() not in TEXT_SUFFIXES: continue
            files_seen += 1
            if files_seen > max_files: limitations.append("file limit reached"); break
            try:
                data = path.read_bytes()[: int(policy.get("max_file_bytes") or 262144)]
            except OSError: continue
            total_read += len(data)
            if total_read > int(policy.get("max_total_bytes") or 8_000_000): limitations.append("search byte universe limit reached"); break
            text = data.decode("utf-8", errors="replace"); lines = text.splitlines()
            filename_terms = [term for term, pattern in patterns if pattern.search(rel)]
            if filename_terms:
                matches.append({"file": rel, "line": 1, "symbol": "", "excerpt": redact("\n".join(lines[:5]))[:1800], "module": str(Path(rel).parent).replace("/", "."), "owner": str(route.get("owner") or ""), "classification": "direct", "trust": "untrusted_source", "query_terms": filename_terms})
            for index, line in enumerate(lines):
                matched_terms = [term for term, pattern in patterns if pattern.search(line)]
                symbol = symbol_pattern.match(line)
                if not matched_terms and not (symbol and any(symbol.group(1).lower() == term.lower() for term in terms)): continue
                lo, hi = max(0, index - 2), min(len(lines), index + 3)
                matches.append({"file": rel, "line": index + 1, "symbol": symbol.group(1) if symbol else "", "excerpt": redact("\n".join(lines[lo:hi]))[:1800], "module": str(Path(rel).parent).replace("/", "."), "owner": str(route.get("owner") or ""), "classification": "direct", "trust": "untrusted_source", "query_terms": matched_terms})
                if len(matches) >= max_results * 100:
                    limitations.append("candidate limit reached")
                    break
            if "candidate limit reached" in limitations: break
        if "candidate limit reached" in limitations or "file limit reached" in limitations or "search byte universe limit reached" in limitations: break
    fallback_status = "searched" if searched else "unavailable"
    if not searched:
        limitations.append("no declared searchable root available")
    lanes.update({"exact_text": fallback_status, "symbol": fallback_status, "content_file": fallback_status, "structural": fallback_status})
    subops.extend({"lane": lane, "status": fallback_status, "count": len(matches)} for lane in ("exact_text", "symbol", "content_file", "structural"))
    unique: list[dict[str, Any]] = []; seen_locations: set[tuple[str, Any, str]] = set()
    for item in matches:
        key = (item["file"], item.get("line"), item.get("excerpt", ""))
        if key in seen_locations: continue
        seen_locations.add(key); unique.append(item)
    def relevance(item: dict[str, Any]) -> tuple[int, int, str, int]:
        file_name = str(item.get("file") or "").lower()
        matched = [str(term).lower() for term in item.get("query_terms") or []]
        filename_hits = sum(1 for term in matched if term and term in file_name)
        distinctive_hits = sum(1 for term in matched if "-" in term or " " in term)
        return (-filename_hits, -distinctive_hits, file_name, int(item.get("line") or 0))

    matches = sorted(unique, key=relevance)[:max_results]
    packet = {
        "schema": SCHEMA, "operation_id": operation_id, "request_id": request_id,
        "route_id": str(route.get("route_id") or ""), "workspace_scope": str(root),
        "capability_used": "compound.source.discovery", "capability_health": lanes,
        "freshness": freshness, "searched_roots": searched, "excluded_roots": sorted(set(excluded_roots)),
        "query_interpretation": {"original": query, "attempted": terms}, "suboperations": subops,
        "matches": matches, "coverage": [{"universe": searched, "files_considered": min(files_seen, max_files), "bytes_read": total_read, "lanes": lanes, "complete": not limitations and bool(searched)}],
        "limitations": sorted(set(limitations)), "contradictions": [], "detail_refs": [],
        "elapsed_ms": int((monotonic() - started) * 1000), "cancelled": False,
    }
    for item in packet["matches"]:
        item["handle"] = content_handle(item, route_id=packet["route_id"], workspace_scope=packet["workspace_scope"], freshness=freshness)
    while len(canonical(packet)) > max_bytes and packet["matches"]:
        removed = packet["matches"].pop(); packet["detail_refs"].append({"handle": removed["handle"], "reason": "packet_byte_bound"})
    return validate(packet, max_bytes=max_bytes)
