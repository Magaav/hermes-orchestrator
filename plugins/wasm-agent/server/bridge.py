#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from routes import BridgeContext, BridgeSettings, SpaceUIHandler, SpaceUIServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="wasm-agent Hermes bridge server")
    parser.add_argument("--host", default=None, help="Bind host, defaults to HERMES_WASM_AGENT_BRIDGE_HOST or 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="Bind port, defaults to HERMES_WASM_AGENT_BRIDGE_PORT or 8790")
    return parser


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    try:
        settings = BridgeSettings.from_env(plugin_root)
    except ValueError as exc:
        print(f"wasm-agent bridge configuration error: {exc}", file=sys.stderr)
        return 1
    args = build_parser().parse_args()
    if args.host:
        settings = settings.__class__(**{**settings.__dict__, "host": args.host})
    if args.port:
        settings = settings.__class__(**{**settings.__dict__, "port": args.port})

    context = BridgeContext(settings)
    server = SpaceUIServer((settings.host, settings.port), SpaceUIHandler, context)
    print(
        f"wasm-agent bridge listening on http://{settings.host}:{settings.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("wasm-agent bridge stopping", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
