from __future__ import annotations

import re
from typing import Any

from . import entity_resolution
from . import route_contracts


def clipped(value: Any, limit: int = 160) -> str:
    return route_contracts.clipped(str(value or "").strip(), limit)


def repo_object_summary_reply(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> str:
    summaries = entity_resolution.source_summaries(local_tool_results)
    if not summaries:
        return local_tool_summary_reply("", local_tool_results)
    answer = " ".join(summaries).strip()
    resolved = entity_resolution.resolve(envelope)
    if entity_resolution.needs_runtime_scope_proof(envelope) and not entity_resolution.runtime_scope_proof_satisfied(envelope, local_tool_results):
        scope = str(resolved.get("scope_phrase") or resolved.get("scope_id") or "that space").strip()
        if scope and "runtime proof" not in answer.lower():
            answer = f"{answer} I do not have live {scope} runtime proof in this turn."
    return clipped(answer, 120000)


def local_tool_summary_reply(reply: str, local_tool_results: list[dict[str, Any]]) -> str:
    summaries: list[str] = []
    synthesized_intro = ""
    synthesized_history = ""
    code_memory_summaries: list[str] = []
    source_summaries = entity_resolution.source_summaries(local_tool_results)
    for item in local_tool_results[:8]:
        if not isinstance(item, dict):
            continue
        route_id = str(item.get("route_id") or "")
        if not route_id:
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        observations = summary.get("observations") if isinstance(summary.get("observations"), list) else []
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if item.get("tool") == "code.memory.search":
            query = str(result.get("query") or "").strip()
            engine = str(result.get("engine") or "").strip()
            code_items = result.get("items") if isinstance(result.get("items"), list) else []
            if code_items:
                details = [
                    f"Code memory search for `{query or route_id}` returned {len(code_items)} route-scoped result(s)"
                    + (f" via `{engine}`." if engine else ".")
                ]
                for code_item in code_items[:6]:
                    if not isinstance(code_item, dict):
                        continue
                    label = code_item.get("label") or code_item.get("kind") or code_item.get("type") or "match"
                    name = code_item.get("name") or code_item.get("qualified_name")
                    path = code_item.get("file") or code_item.get("file_path") or code_item.get("path")
                    line = code_item.get("line")
                    location = f"`{path}`" if path else ""
                    if line not in (None, "") and location:
                        location += f":{line}"
                    details.append(" - " + " ".join(str(part) for part in (label, name, location) if part))
                code_memory_summaries.append("\n".join(details))
                continue
        if item.get("tool") == "lookup.symbol":
            query = str(result.get("query") or "").strip()
            matches = result.get("matches") if isinstance(result.get("matches"), list) else []
            if matches:
                details = [f"Route symbol lookup for `{query or route_id}` returned {len(matches)} match(es)."]
                for match in matches[:8]:
                    if not isinstance(match, dict):
                        continue
                    path = match.get("path")
                    line = match.get("line")
                    text = clipped(str(match.get("text") or "").strip(), 180)
                    location = f"`{path}`" if path else ""
                    if line not in (None, "") and location:
                        location += f":{line}"
                    details.append(" - " + " ".join(part for part in (location, text) if part))
                summaries.append("\n".join(details))
                continue
        if not observations:
            continue
        route_entity = route_id.split(".")[1] if route_id.startswith("hermes-node.") and len(route_id.split(".")) >= 3 else route_id
        entity_label = route_entity.replace("-", " ").replace("_", " ").strip().title() or "The runtime entity"
        route_line = f"Kernel inspection resolved `{route_id}` for entity `{route_entity}`."
        details: list[str] = [route_line]
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            if obs.get("kind") == "runtime_entity":
                identity = obs.get("route_identity") if isinstance(obs.get("route_identity"), dict) else {}
                workspace_root = str(identity.get("workspace_root") or "").strip()
                data_roots = obs.get("data_roots") if isinstance(obs.get("data_roots"), list) else []
                data_root = ""
                for root in data_roots:
                    if isinstance(root, dict) and str(root.get("root") or "").strip():
                        data_root = str(root.get("root") or "").strip()
                        break
                details.append(
                    "Runtime route: "
                    f"surface `{identity.get('surface')}`, owner `{identity.get('owner')}`, root `{identity.get('workspace_root')}`."
                )
                investigation = obs.get("investigation") if isinstance(obs.get("investigation"), dict) else {}
                inferred = investigation.get("inferred_identity") if isinstance(investigation.get("inferred_identity"), list) else []
                if inferred:
                    details.append("Entity investigation inferred: " + ", ".join(f"`{item}`" for item in inferred[:5]) + ".")
                conversations = investigation.get("conversations") if isinstance(investigation.get("conversations"), dict) else {}
                conv_bits = []
                if conversations:
                    for key in ("sessions", "messages", "session_files"):
                        if conversations.get(key) not in (None, "", 0):
                            conv_bits.append(f"{key}={conversations.get(key)}")
                    if conv_bits:
                        details.append(f"Conversation/runtime memory evidence from `{conversations.get('source') or 'runtime store'}`: " + ", ".join(conv_bits) + ".")
                assets = investigation.get("data_assets") if isinstance(investigation.get("data_assets"), dict) else {}
                asset_bits = []
                for key in ("summary_md_count", "raw_paper_json_count", "pdf_count"):
                    if assets.get(key):
                        asset_bits.append(f"{key}={assets.get(key)}")
                if asset_bits:
                    details.append("Data asset evidence: " + ", ".join(asset_bits) + ".")
                documents = investigation.get("documents") if isinstance(investigation.get("documents"), list) else []
                for doc in documents[:3]:
                    if isinstance(doc, dict) and doc.get("path"):
                        details.append(f"`{doc.get('path')}` says: {clipped(str(doc.get('excerpt') or ''), 180)}")
                databases = investigation.get("databases") if isinstance(investigation.get("databases"), list) else []
                for db in databases[:3]:
                    if not isinstance(db, dict):
                        continue
                    tables = db.get("tables") if isinstance(db.get("tables"), dict) else {}
                    semantic = db.get("semantic_tables") if isinstance(db.get("semantic_tables"), list) else []
                    if tables:
                        table_text = ", ".join(f"{key}={value}" for key, value in list(tables.items())[:6])
                        details.append(f"`{db.get('path')}` table evidence: {table_text}.")
                    for table in semantic[:2]:
                        if isinstance(table, dict) and table.get("table"):
                            details.append(f"`{table.get('table')}` semantic evidence count={table.get('count')}.")
                metadata_files = obs.get("metadata_files") if isinstance(obs.get("metadata_files"), list) else []
                bootstrap_facts: list[str] = []
                for meta in metadata_files[:3]:
                    if not isinstance(meta, dict):
                        continue
                    parsed = meta.get("json") if isinstance(meta.get("json"), dict) else {}
                    if parsed:
                        facts = []
                        for key in ("bootstrapped_at", "reseeded_at", "state_code", "node_role", "timezone"):
                            if parsed.get(key) not in (None, ""):
                                facts.append(f"{key}={parsed.get(key)}")
                                if key in {"bootstrapped_at", "reseeded_at", "state_code"}:
                                    bootstrap_facts.append(f"{key}={parsed.get(key)}")
                        if facts:
                            details.append(f"`{meta.get('path')}`: " + ", ".join(facts) + ".")
                    elif meta.get("preview"):
                        details.append(f"`{meta.get('path')}` is readable ({meta.get('bytes')} bytes).")
                data_roots = obs.get("data_roots") if isinstance(obs.get("data_roots"), list) else []
                for root in data_roots[:2]:
                    if not isinstance(root, dict):
                        continue
                    details.append(f"Data root `{root.get('root')}` exposed {root.get('file_count')} bounded file receipts.")
                    for file_item in (root.get("files") if isinstance(root.get("files"), list) else [])[:4]:
                        if not isinstance(file_item, dict):
                            continue
                        tables = file_item.get("sqlite_tables") if isinstance(file_item.get("sqlite_tables"), dict) else {}
                        if tables:
                            table_text = ", ".join(f"{key}={value}" for key, value in list(tables.items())[:6])
                            details.append(f"`{file_item.get('path')}` tables: {table_text}.")
                        else:
                            details.append(f"`{file_item.get('path')}` is present ({file_item.get('bytes')} bytes).")
                if conversations or asset_bits or bootstrap_facts:
                    timeline_bits = []
                    if bootstrap_facts:
                        timeline_bits.append(", ".join(dict.fromkeys(bootstrap_facts)))
                    if conversations:
                        timeline_bits.append(
                            "runtime conversations "
                            + ", ".join(
                                f"{key}={conversations.get(key)}"
                                for key in ("sessions", "messages", "session_files")
                                if conversations.get(key)
                            )
                        )
                    if asset_bits:
                        timeline_bits.append("data corpus " + ", ".join(asset_bits))
                    details.append("What it has done over time, from bounded evidence: " + "; ".join(timeline_bits) + ".")
                    identity_phrase = ", ".join(f"`{value}`" for value in inferred[:3]) if inferred else "`runtime entity`"
                    root_phrase = f" and rooted at `{workspace_root}`" if workspace_root else ""
                    data_phrase = f", with related data under `{data_root}`" if data_root else ""
                    synthesized_intro = (
                        f"{entity_label} is represented in bounded workspace evidence as {identity_phrase}, "
                        f"exposed through `{route_id}`{root_phrase}{data_phrase}."
                    )
                    synthesized_history = (
                        "Over time, the bounded evidence shows "
                        f"{route_entity} has accumulated " + ", ".join([*conv_bits, *asset_bits, *dict.fromkeys(bootstrap_facts)]) + "."
                    )
            elif obs.get("kind") == "files":
                count = obs.get("count")
                if count is not None:
                    details.append(f"Route file lookup returned {count} declared path receipts.")
        if details:
            summaries.append("\n".join(dict.fromkeys(details)))
    if code_memory_summaries:
        proof_lines = list(dict.fromkeys(line for summary in code_memory_summaries for line in summary.splitlines() if line.strip()))
        clean_reply = str(reply or "").strip()
        if not clean_reply:
            clean_reply = " ".join(source_summaries).strip() or "The route-scoped code evidence identifies and locates the repo object anchors below. Use them as source anchors for definitions, registries, renderers, or helpers; this location evidence does not prove live runtime availability."
        return clipped(clean_reply.rstrip() + "\n\nCode memory proof:\n" + "\n".join(f"- {line}" for line in proof_lines), 120000)
    if not summaries:
        return reply
    proof_lines = list(dict.fromkeys(line for summary in summaries for line in summary.splitlines() if line.strip()))
    suffix = "\n\nKernel inspection proof:\n" + "\n".join(f"- {line}" for line in proof_lines)
    if "Kernel inspection proof:" in reply:
        return reply
    clean_reply = "\n\n".join(part for part in (synthesized_intro, synthesized_history) if part).strip()
    if not clean_reply:
        clean_reply = str(reply or "").strip() or "The declared runtime entity was inspected locally."
    return clipped(clean_reply.rstrip() + suffix, 120000)


def answer_still_requests_local_tools(reply: str, local_tool_results: list[dict[str, Any]]) -> bool:
    if not local_tool_results:
        return False
    text = str(reply or "").strip().lower()
    if not text:
        return True
    has_source_evidence = any(
        isinstance(item, dict)
        and item.get("tool") in {"code.memory.search", "file.read_bounded", "lookup.symbol"}
        and item.get("ok")
        for item in local_tool_results
    )
    runtime_caveat = re.search(
        r"\b(?:runtime|scope|availability).*\b(?:not\s+(?:proven|verified|inspected)|unverified|missing)\b"
        r"|\b(?:not\s+(?:proven|verified|inspected)|unverified|missing).*\b(?:runtime|scope|availability)\b"
        r"|\bi\s+(?:do\s+not|don't)\s+have\b.*\b(?:runtime|scope|availability)\b.*\bproof\b",
        text,
    )
    if has_source_evidence and runtime_caveat:
        return False
    return any(re.search(pattern, text) for pattern in (
        r"\bnot\s+inspected\s+yet\b",
        r"\bi\s+(?:do\s+not|don't)\s+(?:(?:yet\s+have|have)\s+inspected\s+evidence|have\s+inspected\s+evidence\s+yet)\b",
        r"\blet\s+me\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search|verify)\b",
        r"\bi(?:'ll| will| am going to)\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search|verify)\b",
        r"\bi\s+need\s+to\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search)\b",
        r"\bbefore\s+i\s+can\s+(?:answer|give|provide|instruct)\b",
        r"\bneed\s+to\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search)\b",
        r"\b(?:checking|inspecting|searching|looking\s+into)\b.*\b(?:repo|codebase|source|files?|definitions?)\b.*\bnow\b",
        r"\bdispatching\s+(?:inspection|inspect|local|kernel|tool|read|search)\s+actions?\s+now\b",
        r"\bdispatching\s+.*\b(?:inspect|inspection|kernel|tool|read|search).*\bnow\b",
        r"\bdispatch\s+kernel\.(?:inspect|resolve|prove|act|search)\b",
        r"\broute_to_kernel_inspect\b",
        r"\bpending\s*[:=]\s*[a-z0-9_-]+",
    ))


def stream_delta_should_emit(delta: str) -> bool:
    text = str(delta or "").strip().lower()
    if not text:
        return False
    return not any(re.search(pattern, text) for pattern in (
        r"\bnot\s+inspected\s+yet\b",
        r"\bi\s+(?:do\s+not|don't)\s+have\s+inspected\s+evidence\s+yet\b",
        r"\bneed\s+to\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search)\b",
        r"\bi\s+need\s+to\s+(?:inspect|read|recover|locate|check|look\s+up|look\s+into|search)\b",
        r"\b(?:checking|inspecting|searching|looking\s+into)\b.*\b(?:repo|codebase|source|files?|definitions?)\b.*\bnow\b",
        r"\bdispatch\s+kernel\.(?:inspect|resolve|prove|act|search)\b",
        r"\broute[_\s-]+to[_\s-]+kernel[_\s-]+inspect\b",
    ))
