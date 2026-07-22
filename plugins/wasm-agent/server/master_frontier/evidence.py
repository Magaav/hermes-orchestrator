from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from . import repository_reads


SCHEMA = "EVIDENCE/1"
MAX_EVIDENCE_BYTES = 64_000
MAX_MODEL_EVIDENCE_BYTES = 12_000
MAX_SEARCH_LINE_BYTES = 16 * 1024
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".md", ".html", ".css", ".toml", ".yaml", ".yml"}
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
    return repository_reads.redact(text)[0]


def _excluded(relative: str, patterns: list[str], *, directory: bool) -> bool:
    value = relative.replace("\\", "/").lstrip("./")
    candidates = [value]
    if directory:
        candidates.extend((value + "/_", value + "/placeholder.py"))
    return any(fnmatch.fnmatch(candidate, pattern.lstrip("./")) for pattern in patterns for candidate in candidates)


def _stream_files(base: Path, root: Path, excludes: list[str]) -> Any:
    """Walk without materializing a whole repository tree in memory."""
    if base.is_file():
        yield base
        return
    pending = [base]
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        child = Path(entry.path)
                        try: relative = str(child.relative_to(root))
                        except ValueError: relative = str(child)
                        if entry.name not in {".git", "state", "node_modules", "__pycache__"} and not _excluded(relative, excludes, directory=True):
                            pending.append(child)
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                except OSError:
                    continue


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
    candidate_limit = max(50, max_results * 10)
    candidates_pruned = False
    # Index ingestion and deterministic fallback have different economics:
    # keep max_file_bytes as the index payload cap, and widen only the streamed
    # fallback through the separately declared per-file scan bound.
    try:
        indexed_file_bytes = max(1024, int(policy.get("max_file_bytes") or 262144))
    except (TypeError, ValueError):
        indexed_file_bytes = 262144
    try:
        max_total_scan_bytes = max(1024, min(64_000_000, int(policy.get("max_total_bytes") or 8_000_000)))
    except (TypeError, ValueError):
        max_total_scan_bytes = 8_000_000
    try:
        max_file_scan_bytes = max(1024, min(
            max_total_scan_bytes,
            int(policy.get("max_scan_bytes_per_file") or indexed_file_bytes),
        ))
    except (TypeError, ValueError):
        max_file_scan_bytes = min(indexed_file_bytes, max_total_scan_bytes)

    def add_match(item: dict[str, Any]) -> None:
        nonlocal candidates_pruned
        matches.append(item)
        if len(matches) < candidate_limit * 2:
            return
        matches.sort(key=lambda value: (
            -int(bool(value.get("symbol"))),
            -sum(1 for term in value.get("query_terms") or [] if str(term).lower() in str(value.get("file") or "").lower()),
            str(value.get("file") or ""), int(value.get("line") or 0),
        ))
        del matches[candidate_limit:]
        candidates_pruned = True

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
                    add_match({"file": str(raw["file"]), "line": raw.get("line"), "symbol": str(raw.get("name") or raw.get("qualified_name") or ""), "excerpt": redact(str(raw.get("summary") or raw.get("name") or ""))[:1200], "module": str(raw.get("module") or ""), "owner": str(route.get("owner") or ""), "classification": "direct", "trust": "untrusted_source"})
        else: limitations.append("semantic code memory is stale or unavailable; deterministic route fallback used")
    else:
        lanes["semantic"] = "unavailable"; subops.append({"lane": "semantic", "status": "unavailable", "count": 0}); limitations.append("semantic search unavailable")

    interpretations = request.get("interpretations") if isinstance(request.get("interpretations"), list) else []
    patterns = _query_patterns(query, interpretations)
    terms = [term for term, _pattern in patterns]
    symbol_pattern = re.compile(r"^\s*(?:class|def|function|const|let|var|interface|type)\s+([A-Za-z_$][\w$]*)")
    files_seen = 0; total_read = 0; scan_truncated_files = 0; clipped_lines = 0
    total_scan_exhausted = False

    def finish_match(item: dict[str, Any], context_lines: list[str]) -> None:
        item["excerpt"] = redact("\n".join(context_lines))[:1800]
        add_match(item)

    for include in sorted(includes):
        base = (root / include).resolve()
        if not _inside(base, allowed) or not base.exists(): excluded_roots.append(include); continue
        searched.append(str(base.relative_to(root)) if base != root else ".")
        for path in _stream_files(base, root, excludes):
            stop(); rel = str(path.relative_to(root)).replace("\\", "/")
            if any(fnmatch.fnmatch(rel, pattern.lstrip("./")) for pattern in excludes): continue
            if path.suffix.lower() not in TEXT_SUFFIXES: continue
            try:
                repository_reads.resolve(route, str(path))
            except repository_reads.RepositoryReadError:
                continue
            files_seen += 1
            if files_seen > max_files: limitations.append("file limit reached"); break
            remaining_total = max_total_scan_bytes - total_read
            if remaining_total <= 0:
                total_scan_exhausted = True
                limitations.append("search byte universe limit reached")
                break
            try:
                file_bytes = path.stat().st_size
                file_budget = min(max_file_scan_bytes, remaining_total)
                iterator_limit = None if file_bytes <= file_budget else file_budget
                filename_terms = [term for term, pattern in patterns if pattern.search(rel)]
                first_lines: list[str] = []
                previous: deque[str] = deque(maxlen=2)
                pending: list[dict[str, Any]] = []
                scan: dict[str, Any] = {}
                with path.open("rb") as handle:
                    for line_number, raw_line, line_clipped in repository_reads.iter_bounded_lines(
                        handle, max_bytes=iterator_limit,
                        max_line_bytes=MAX_SEARCH_LINE_BYTES, stats=scan,
                    ):
                        if line_number % 256 == 0:
                            stop()
                        line = raw_line.decode("utf-8", errors="replace")
                        clipped_lines += int(line_clipped)
                        display_line = line[:320]
                        if len(first_lines) < 5:
                            first_lines.append(display_line)

                        still_pending: list[dict[str, Any]] = []
                        for entry in pending:
                            entry["context"].append(display_line)
                            entry["remaining"] -= 1
                            if entry["remaining"] <= 0:
                                finish_match(entry["item"], entry["context"])
                            else:
                                still_pending.append(entry)
                        pending = still_pending

                        matched_terms = [term for term, pattern in patterns if pattern.search(line)]
                        symbol = symbol_pattern.match(line)
                        if matched_terms or (symbol and any(symbol.group(1).lower() == term.lower() for term in terms)):
                            pending.append({
                                "item": {
                                    "file": rel, "line": line_number,
                                    "symbol": symbol.group(1) if symbol else "",
                                    "module": str(Path(rel).parent).replace("/", "."),
                                    "owner": str(route.get("owner") or ""),
                                    "classification": "direct", "trust": "untrusted_source",
                                    "query_terms": matched_terms,
                                },
                                "context": [*previous, display_line], "remaining": 2,
                            })
                        previous.append(display_line)
                for entry in pending:
                    finish_match(entry["item"], entry["context"])
            except OSError:
                continue
            scanned = int(scan.get("bytes_scanned") or 0)
            total_read += scanned
            if file_bytes > scanned:
                scan_truncated_files += 1
                if file_budget >= remaining_total:
                    total_scan_exhausted = True
                else:
                    limitations.append("per-file scan byte limit reached")
            if filename_terms:
                add_match({"file": rel, "line": 1, "symbol": "", "excerpt": redact("\n".join(first_lines))[:1800], "module": str(Path(rel).parent).replace("/", "."), "owner": str(route.get("owner") or ""), "classification": "direct", "trust": "untrusted_source", "query_terms": filename_terms})
            if total_scan_exhausted:
                limitations.append("search byte universe limit reached")
                break
        if "file limit reached" in limitations or "search byte universe limit reached" in limitations: break
    if scan_truncated_files:
        limitations.append("one or more files exceeded a declared deterministic scan bound")
    if clipped_lines:
        limitations.append("one or more logical lines exceeded the bounded search line buffer")
    if candidates_pruned:
        limitations.append("candidate ranking retained only the strongest bounded matches")
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
        "matches": matches, "coverage": [{
            "universe": searched, "files_considered": min(files_seen, max_files),
            "bytes_read": total_read, "bytes_scanned": total_read,
            "max_total_bytes": max_total_scan_bytes,
            "max_scan_bytes_per_file": max_file_scan_bytes,
            "stream_chunk_bytes": repository_reads.STREAM_CHUNK_BYTES,
            "line_buffer_bytes_max": MAX_SEARCH_LINE_BYTES,
            "files_scan_truncated": scan_truncated_files,
            "lanes": lanes, "complete": not limitations and bool(searched),
        }],
        "limitations": sorted(set(limitations)), "contradictions": [], "detail_refs": [],
        "elapsed_ms": int((monotonic() - started) * 1000), "cancelled": False,
    }
    for item in packet["matches"]:
        item["handle"] = content_handle(item, route_id=packet["route_id"], workspace_scope=packet["workspace_scope"], freshness=freshness)
    while len(canonical(packet)) > max_bytes and packet["matches"]:
        removed = packet["matches"].pop(); packet["detail_refs"].append({"handle": removed["handle"], "reason": "packet_byte_bound"})
    return validate(packet, max_bytes=max_bytes)
