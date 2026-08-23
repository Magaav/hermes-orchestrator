"""Symmetric compact model projection for the V6 Agent IR."""
from __future__ import annotations

from typing import Any

from . import contracts


WIRE = "MF6/1"


def _j(value: Any) -> str:
    return contracts.canonical(value)


def _s(value: Any) -> str:
    return _j(str(value or ""))


def encode(value: dict[str, Any]) -> str:
    lines = [WIRE]
    if value.get("goal"):
        lines.append(f"G\t{_s(value['goal'])}")
    for item in value.get("capabilities") or []:
        if isinstance(item, dict):
            lines.append("\t".join(("C", str(item.get("id") or ""), str(item.get("kind") or ""), str(item.get("authority") or ""), _s(item.get("summary")))))
    state = value.get("state") if isinstance(value.get("state"), dict) else {}
    if state:
        lines.append("\t".join(("S", str(state.get("id") or ""), str(state.get("rev") or 0), str(state.get("status") or ""), _j(state.get("known") or []), _j(state.get("open") or []), _j(state.get("plan") or []))))
        for goal in state.get("goals") or []:
            lines.append("\t".join(("Q", str(goal.get("id") or ""), str(goal.get("cap") or ""), str(goal.get("status") or "pending"), _s(goal.get("outcome")), str(goal.get("operation") or ""))))
    for item in value.get("evidence") or []:
        if isinstance(item, dict):
            lines.append("\t".join(("E", str(item.get("id") or ""), str(item.get("kind") or ""), _s(item.get("subject")), _s(item.get("revision")), _s(item.get("summary")), str(item.get("detail_ref") or ""))))
            if isinstance(item.get("payload"), dict):
                lines.append("\t".join(("P", str(item.get("id") or ""), "untrusted-data", _j(item["payload"]))))
    for item in value.get("operations") or []:
        if isinstance(item, dict):
            lines.append("\t".join(("D", str(item.get("id") or ""), str(item.get("cap") or ""), _j(item.get("args") or {}), _j(item.get("after") or []), _j(item.get("expect") or {}))))
            if isinstance(item.get("say"), dict):
                lines.append("\t".join(("Y", str(item["say"].get("phase") or "acting"), _s(item["say"].get("message")))))
    for item in value.get("receipts") or []:
        if isinstance(item, dict):
            lines.append("\t".join(("R", str(item.get("id") or ""), str(item.get("op") or ""), "1" if item.get("ok") else "0", str(item.get("state") or ""), _j(item.get("observed") or {}), _j(item.get("proof") or []), _j(item.get("error") or {}))))
    for item in value.get("missing") or []:
        lines.append(f"M\t{_s(item)}")
    if value.get("ready") == "answer":
        lines.append("A\tanswer")
    if value.get("final"):
        lines.append(f"F\t{_s(value['final'])}")
    return "\n".join(lines)


def decode(text: str) -> dict[str, Any]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != WIRE:
        raise ValueError("projection_wire_invalid")
    result: dict[str, Any] = {"capabilities": [], "evidence": [], "payloads": [], "operations": [], "receipts": [], "missing": []}
    for line in lines[1:]:
        fields = line.split("\t")
        tag = fields[0]
        try:
            if tag == "G" and len(fields) == 2:
                result["goal"] = contracts.decode(fields[1])
            elif tag == "C" and len(fields) == 5:
                result["capabilities"].append({"id": fields[1], "kind": fields[2], "authority": fields[3], "summary": contracts.decode(fields[4])})
            elif tag == "S" and len(fields) == 7:
                result["state"] = {"id": fields[1], "rev": int(fields[2]), "status": fields[3], "known": contracts.decode(fields[4]), "open": contracts.decode(fields[5]), "plan": contracts.decode(fields[6]), "goals": []}
            elif tag == "Q" and len(fields) == 6 and isinstance(result.get("state"), dict):
                result["state"]["goals"].append({"id": fields[1], "cap": fields[2], "status": fields[3], "outcome": contracts.decode(fields[4]), "operation": fields[5]})
            elif tag == "E" and len(fields) == 7:
                result["evidence"].append({"id": fields[1], "kind": fields[2], "subject": contracts.decode(fields[3]), "revision": contracts.decode(fields[4]), "summary": contracts.decode(fields[5]), "detail_ref": fields[6]})
            elif tag == "P" and len(fields) == 4 and fields[2] == "untrusted-data":
                view = contracts.decode(fields[3])
                result["payloads"].append({"evidence": fields[1], "trust": fields[2], "view": view})
                owner = next((item for item in reversed(result["evidence"]) if item.get("id") == fields[1]), None)
                if owner is None:
                    raise ValueError("projection_record_invalid")
                owner["payload"] = view
            elif tag == "D" and len(fields) == 6:
                result["operations"].append({"id": fields[1], "cap": fields[2], "args": contracts.decode(fields[3]), "after": contracts.decode(fields[4]), "expect": contracts.decode(fields[5])})
            elif tag == "Y" and len(fields) == 3:
                update = {"phase": fields[1], "message": contracts.decode(fields[2])}
                if result["operations"]:
                    result["operations"][-1]["say"] = update
                else:
                    result.setdefault("commentary", []).append(update)
            elif tag == "R" and len(fields) == 8:
                result["receipts"].append({"id": fields[1], "op": fields[2], "ok": fields[3] == "1", "state": fields[4], "observed": contracts.decode(fields[5]), "proof": contracts.decode(fields[6]), "error": contracts.decode(fields[7])})
            elif tag == "M" and len(fields) == 2:
                result["missing"].append(contracts.decode(fields[1]))
            elif tag == "A" and fields == ["A", "answer"]:
                result["ready"] = "answer"
            elif tag == "F" and len(fields) == 2:
                result["final"] = contracts.decode(fields[1])
            else:
                raise ValueError("projection_record_invalid")
        except (contracts.ContractError, TypeError, ValueError, IndexError) as exc:
            raise ValueError("projection_record_invalid") from exc
    return result
