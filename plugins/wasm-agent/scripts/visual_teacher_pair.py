#!/usr/bin/env python3
"""Supervised CLI adapter for immutable visual-teacher pairs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier.visual_teacher_store import VisualTeacherError, VisualTeacherStore  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Register and approve supervised image-teacher pairs.")
    value.add_argument("--root", help="Override the private visual-teacher state root.")
    commands = value.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--source", required=True)
    register.add_argument("--mask", required=True)
    register.add_argument("--teacher-output", required=True)
    register.add_argument("--contract", required=True, help="Bounded JSON contract file; inline image data is forbidden.")
    register.add_argument("--teacher", required=True)
    register.add_argument("--session-id", required=True)
    register.add_argument("--operator", required=True)
    register.add_argument("--created-at", required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("--pair-id", required=True)
    approve.add_argument("--partition", choices=["training", "gold", "holdout"], required=True)
    approve.add_argument("--approver", required=True)
    approve.add_argument("--approved-at", required=True)
    approve.add_argument("--manifest-sha256", required=True)
    commands.add_parser("summary")
    return value


def main() -> int:
    arguments = parser().parse_args()
    store = VisualTeacherStore(arguments.root)
    try:
        if arguments.command == "register":
            contract = json.loads(Path(arguments.contract).read_text(encoding="utf-8"))
            result = store.register_candidate(
                source=Path(arguments.source).read_bytes(),
                mask=Path(arguments.mask).read_bytes(),
                teacher_output=Path(arguments.teacher_output).read_bytes(),
                contract=contract,
                provenance={
                    "teacher": arguments.teacher,
                    "session_id": arguments.session_id,
                    "operator": arguments.operator,
                    "created_at": arguments.created_at,
                },
            )
        elif arguments.command == "approve":
            result = store.approve(
                arguments.pair_id,
                partition=arguments.partition,
                approver=arguments.approver,
                approved_at=arguments.approved_at,
                expected_manifest_sha256=arguments.manifest_sha256,
            )
        else:
            result = store.summary()
    except (OSError, json.JSONDecodeError, VisualTeacherError) as exc:
        code = exc.code if isinstance(exc, VisualTeacherError) else "teacher_adapter_error"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(exc)}}))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
