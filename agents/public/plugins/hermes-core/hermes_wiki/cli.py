from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .bootstrap import ensure_layout
from .compression import build_compression_artifacts
from .config import detect_node_root, load_settings
from .doctrine import extract_doctrine_candidates
from .emergence import discover_emergent_concepts
from .governance import process_pending_proposals, queue_rollback_proposal, submit_proposal
from .graph import compile_graph
from .observability import build_lint_report, build_observability_snapshot
from .query import query_wiki
from .refactor import analyse_refactor_candidates
from .self_heal import run_self_heal


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes shared wiki engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="Ensure wiki runtime layout exists")
    bootstrap.add_argument("--node-root", default="", help="Node root to link /wiki inside")
    bootstrap.add_argument("--node-name", default="", help="Reserved for logging/compatibility")
    bootstrap.add_argument("--repair", action="store_true", help="Mark run as repair mode")
    bootstrap.add_argument("--json", action="store_true", help="Emit JSON output")

    rebuild = subparsers.add_parser("rebuild", help="Rebuild graph, compression, and observability artifacts")
    rebuild.add_argument("--json", action="store_true", help="Emit JSON output")

    submit = subparsers.add_parser("submit", help="Submit a proposal from a JSON payload")
    submit.add_argument("--payload-file", required=True, help="JSON file containing a proposal payload")
    submit.add_argument("--json", action="store_true", help="Emit JSON output")

    process = subparsers.add_parser("process", help="Process pending proposals through the coordinated writer")
    process.add_argument("--json", action="store_true", help="Emit JSON output")

    heal = subparsers.add_parser("self-heal", help="Run conservative wiki self-healing")
    heal.add_argument("--node-root", default="", help="Optional node root to repair /wiki link")
    heal.add_argument("--json", action="store_true", help="Emit JSON output")

    doctrine = subparsers.add_parser("doctrine", help="Generate doctrine candidates from operational history")
    doctrine.add_argument("--stage-proposals", action="store_true", help="Stage doctrine candidates as proposals")
    doctrine.add_argument("--json", action="store_true", help="Emit JSON output")

    akr = subparsers.add_parser("akr", help="Run adaptive knowledge refactoring analysis")
    akr.add_argument("--stage-proposals", action="store_true", help="Stage refactor suggestions as proposals")
    akr.add_argument("--json", action="store_true", help="Emit JSON output")

    ecd = subparsers.add_parser("ecd", help="Run emergent concept discovery")
    ecd.add_argument("--stage-proposals", action="store_true", help="Stage emergence candidates as proposals")
    ecd.add_argument("--json", action="store_true", help="Emit JSON output")

    query = subparsers.add_parser("query", help="Query the wiki with graph-aware budgeting")
    query.add_argument("query_text", help="Natural-language query")
    query.add_argument("--detail", action="store_true", help="Escalate to deeper context")
    query.add_argument("--json", action="store_true", help="Emit JSON output")

    observe = subparsers.add_parser("observe", help="Recompute lint and observability snapshots")
    observe.add_argument("--json", action="store_true", help="Emit JSON output")

    rollback = subparsers.add_parser("rollback", help="Create and process a rollback proposal for a page")
    rollback.add_argument("--target-path", required=True, help="Relative wiki path to restore")
    rollback.add_argument("--snapshot-path", default="", help="Optional relative snapshot path under meta/history/")
    rollback.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def cmd_bootstrap(args: argparse.Namespace) -> int:
    settings = load_settings()
    node_root = detect_node_root(args.node_root) if args.node_root else detect_node_root()
    result = ensure_layout(settings, node_root=node_root, repair=bool(args.repair))

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "enabled" if settings.enabled else "disabled"
        print(f"[wiki] status={status} root={settings.wiki_root}")
        if settings.enabled:
            if result["created_directories"]:
                print(f"[wiki] created_dirs={','.join(result['created_directories'])}")
            if result["seeded_files"]:
                print(f"[wiki] seeded={','.join(result['seeded_files'])}")
            if node_root is not None:
                print(f"[wiki] node_wiki_link={node_root / 'wiki'}")
    return 0


def _emit(payload: object, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload)
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    settings = load_settings()
    graph = compile_graph(settings)
    compression = build_compression_artifacts(settings, graph_payload=graph)
    lint = build_lint_report(settings, graph_payload=graph)
    observability = build_observability_snapshot(settings, graph_payload=graph, lint_report=lint)
    return _emit(
        {
            "graph": graph["metrics"],
            "compression": compression,
            "observability": {"health_score": observability["health_score"]},
        },
        args.json,
    )


def cmd_submit(args: argparse.Namespace) -> int:
    settings = load_settings()
    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    result = submit_proposal(settings, payload)
    return _emit(result, args.json)


def cmd_process(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = process_pending_proposals(settings)
    return _emit(result, args.json)


def cmd_self_heal(args: argparse.Namespace) -> int:
    settings = load_settings()
    node_root = detect_node_root(args.node_root) if args.node_root else detect_node_root()
    result = run_self_heal(settings, node_root=node_root)
    return _emit(result, args.json)


def cmd_doctrine(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = extract_doctrine_candidates(settings, stage_proposals=bool(args.stage_proposals))
    return _emit(result, args.json)


def cmd_akr(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = analyse_refactor_candidates(settings, stage_proposals=bool(args.stage_proposals))
    return _emit(result, args.json)


def cmd_ecd(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = discover_emergent_concepts(settings, stage_proposals=bool(args.stage_proposals))
    return _emit(result, args.json)


def cmd_query(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = query_wiki(settings, args.query_text, require_detail=bool(args.detail))
    if args.json:
        return _emit(result, True)
    print(result["context"])
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    settings = load_settings()
    graph = compile_graph(settings)
    lint = build_lint_report(settings, graph_payload=graph)
    snapshot = build_observability_snapshot(settings, graph_payload=graph, lint_report=lint)
    return _emit(snapshot, args.json)


def cmd_rollback(args: argparse.Namespace) -> int:
    settings = load_settings()
    proposal = queue_rollback_proposal(
        settings,
        target_path=str(args.target_path),
        snapshot_path=str(args.snapshot_path),
    )
    if proposal.get("proposal_id"):
        process_pending_proposals(settings)
    return _emit(proposal, args.json)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        return cmd_bootstrap(args)
    if args.command == "rebuild":
        return cmd_rebuild(args)
    if args.command == "submit":
        return cmd_submit(args)
    if args.command == "process":
        return cmd_process(args)
    if args.command == "self-heal":
        return cmd_self_heal(args)
    if args.command == "doctrine":
        return cmd_doctrine(args)
    if args.command == "akr":
        return cmd_akr(args)
    if args.command == "ecd":
        return cmd_ecd(args)
    if args.command == "query":
        return cmd_query(args)
    if args.command == "observe":
        return cmd_observe(args)
    if args.command == "rollback":
        return cmd_rollback(args)

    parser.error(f"unknown command: {args.command}")
    return 2
