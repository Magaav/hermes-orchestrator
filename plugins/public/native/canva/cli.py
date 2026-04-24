"""CLI and slash commands for the Canva plugin."""

from __future__ import annotations

import json

from .client import CanvaApiError, CanvaClient
from .tools import canva_create_comment_thread, canva_export_design


def handle_canva_status(raw_args: str) -> str:
    try:
        return json.dumps({"ok": True, "status": CanvaClient().auth_status(force_refresh=False)})
    except CanvaApiError as exc:
        return json.dumps({"ok": False, "error": str(exc), "status": exc.status})


def handle_canva_auth(raw_args: str) -> str:
    try:
        return json.dumps({"ok": True, "status": CanvaClient().auth_status(force_refresh=True)})
    except CanvaApiError as exc:
        return json.dumps({"ok": False, "error": str(exc), "status": exc.status})


def handle_canva_export(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    if len(parts) < 2:
        return json.dumps({"ok": False, "error": "Usage: /canva-export <design_id> <format_type> [filename_prefix]"})
    design_id, format_type = parts[0], parts[1]
    filename_prefix = parts[2] if len(parts) > 2 else design_id
    return canva_export_design({"design_id": design_id, "format_type": format_type, "filename_prefix": filename_prefix})


def handle_canva_comment(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    if len(parts) < 2:
        return json.dumps({"ok": False, "error": "Usage: /canva-comment <design_id> <message...>"})
    return canva_create_comment_thread({"design_id": parts[0], "message_plaintext": " ".join(parts[1:])})


def setup_cli(subparser):
    sub = subparser.add_subparsers(dest="canva_command")
    sub.add_parser("status", help="Show Canva auth/env status")
    sub.add_parser("auth", help="Force a Canva token refresh and show the result")
    sub.add_parser("capabilities", help="Show Canva account capabilities")
    list_parser = sub.add_parser("list", help="List Canva designs")
    list_parser.add_argument("--query", default="")
    list_parser.add_argument("--ownership", default="any")
    list_parser.add_argument("--sort-by", default="relevance")
    list_parser.add_argument("--limit", type=int, default=25)
    templates = sub.add_parser("templates", help="List Canva brand templates")
    templates.add_argument("--query", default="")
    templates.add_argument("--ownership", default="any")
    templates.add_argument("--dataset", default="any")
    templates.add_argument("--sort-by", default="relevance")
    templates.add_argument("--limit", type=int, default=25)
    dataset = sub.add_parser("dataset", help="Get a Canva brand template dataset")
    dataset.add_argument("brand_template_id")
    export_parser = sub.add_parser("export", help="Export and download a Canva design")
    export_parser.add_argument("design_id")
    export_parser.add_argument("format_type")
    export_parser.add_argument("--filename-prefix", default="")
    comment = sub.add_parser("comment", help="Create a Canva comment thread on a design")
    comment.add_argument("design_id")
    comment.add_argument("message")
    comment.add_argument("--assignee-id", default="")
    upload = sub.add_parser("upload", help="Upload a local asset into Canva")
    upload.add_argument("file_path")
    upload.add_argument("--name", default="")
    upload.add_argument("--tags", nargs="*", default=[])
    upload_url = sub.add_parser("upload-url", help="Upload an asset into Canva from a public URL")
    upload_url.add_argument("url")
    upload_url.add_argument("name")
    upload_url.add_argument("--tags", nargs="*", default=[])
    smoke = sub.add_parser("smoke", help="Run auth plus a small list-designs check")
    smoke.add_argument("--limit", type=int, default=3)
    subparser.set_defaults(func=handle_cli)


def handle_cli(args):
    command = getattr(args, "canva_command", "") or "status"
    client = CanvaClient()
    try:
        if command == "status":
            print(json.dumps({"ok": True, "status": client.auth_status(force_refresh=False)}, ensure_ascii=False))
            return
        if command == "auth":
            print(json.dumps({"ok": True, "status": client.auth_status(force_refresh=True)}, ensure_ascii=False))
            return
        if command == "capabilities":
            print(json.dumps({"ok": True, "result": client.get_capabilities()}, ensure_ascii=False))
            return
        if command == "list":
            payload = client.list_designs(
                query=getattr(args, "query", ""),
                ownership=getattr(args, "ownership", "any"),
                sort_by=getattr(args, "sort_by", "relevance"),
                limit=getattr(args, "limit", 25),
            )
            print(json.dumps({"ok": True, "result": payload}, ensure_ascii=False))
            return
        if command == "templates":
            payload = client.list_brand_templates(
                query=getattr(args, "query", ""),
                ownership=getattr(args, "ownership", "any"),
                dataset=getattr(args, "dataset", "any"),
                sort_by=getattr(args, "sort_by", "relevance"),
                limit=getattr(args, "limit", 25),
            )
            print(json.dumps({"ok": True, "result": payload}, ensure_ascii=False))
            return
        if command == "dataset":
            print(json.dumps({"ok": True, "result": client.get_brand_template_dataset(args.brand_template_id)}, ensure_ascii=False))
            return
        if command == "export":
            print(
                canva_export_design(
                    {
                        "design_id": args.design_id,
                        "format_type": args.format_type,
                        "filename_prefix": args.filename_prefix or args.design_id,
                    }
                )
            )
            return
        if command == "comment":
            print(
                canva_create_comment_thread(
                    {
                        "design_id": args.design_id,
                        "message_plaintext": args.message,
                        "assignee_id": getattr(args, "assignee_id", ""),
                    }
                )
            )
            return
        if command == "upload":
            print(json.dumps({"ok": True, "result": client.upload_asset(file_path=args.file_path, name=args.name, tags=args.tags)}, ensure_ascii=False))
            return
        if command == "upload-url":
            print(json.dumps({"ok": True, "result": client.upload_asset_from_url(url=args.url, name=args.name, tags=args.tags)}, ensure_ascii=False))
            return
        if command == "smoke":
            payload = {
                "auth": client.auth_status(force_refresh=True),
                "capabilities": client.get_capabilities(),
                "designs": client.list_designs(limit=getattr(args, "limit", 3)),
            }
            print(json.dumps({"ok": True, "result": payload}, ensure_ascii=False))
            return
        print(json.dumps({"ok": False, "error": f"Unknown command: {command}"}, ensure_ascii=False))
    except CanvaApiError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "status": exc.status}, ensure_ascii=False))
