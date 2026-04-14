#!/usr/bin/env python3
"""
Apply Channel ACL customizations to hermes-agent run.py.

This script is idempotent and designed to survive upstream changes by:
1) copying hook files to ~/.hermes/hooks/channel_acl/
2) inserting marker-delimited patch blocks into run.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
DISCORD_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISCORD_PRIVATE_ROOT = Path(
    str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "/local/plugins/private/discord")
).resolve()
HOOK_PUBLIC_SOURCE = DISCORD_PLUGIN_ROOT / "hooks" / "channel_acl"
HOOK_PRIVATE_SOURCE = DISCORD_PRIVATE_ROOT / "hooks" / "channel_acl"
HOOK_DEST = HERMES_HOME / "hooks" / "channel_acl"


def _run_path_candidates() -> list[Path]:
    env_root = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser() / "gateway" / "run.py")
    candidates.extend(
        [
            Path("/local/hermes-agent/gateway/run.py"),
            HERMES_HOME / "hermes-agent" / "gateway" / "run.py",
            Path("/local/.hermes/hermes-agent/gateway/run.py"),
            Path("/home/ubuntu/.hermes/hermes-agent/gateway/run.py"),
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _resolve_run_py() -> Path | None:
    for candidate in _run_path_candidates():
        if candidate.exists():
            return candidate
    return None

NORMALIZE_MARKER = "COLMEIO_CHANNEL_ACL_NORMALIZE_BEGIN"
NORMALIZE_END_MARKER = "COLMEIO_CHANNEL_ACL_NORMALIZE_END"
MODEL_MARKER = "COLMEIO_CHANNEL_ACL_MODEL_BEGIN"
MODEL_END_MARKER = "COLMEIO_CHANNEL_ACL_MODEL_END"
STATUS_MARKER = "COLMEIO_CHANNEL_ACL_STATUS_BEGIN"
STATUS_END_MARKER = "COLMEIO_CHANNEL_ACL_STATUS_END"

NORMALIZE_BLOCK = """\
            # COLMEIO_CHANNEL_ACL_NORMALIZE_BEGIN
            # Channel ACL: normalize text to channel purpose.
            _normalized = None
            _blocked = False
            _block_msg = None
            try:
                _hook_home = Path(__import__("os").getenv("HERMES_HOME") or (Path.home() / ".hermes"))
                _hook_path = _hook_home / "hooks" / "channel_acl" / "handler.py"
                if _hook_path.exists():
                    import importlib.util, sys as _sys
                    _spec = importlib.util.spec_from_file_location("colmeio_channel_acl", _hook_path)
                    if _spec and _spec.loader:
                        _mod = importlib.util.module_from_spec(_spec)
                        _sys.modules["colmeio_channel_acl"] = _mod
                        _spec.loader.exec_module(_mod)
                        _norm = getattr(_mod, "normalize_to_channel_skill", None)
                        if callable(_norm):
                            _action, _result = _norm(source, message_text)
                            if _action == "BLOCK":
                                _blocked = True
                                _block_msg = _result
                            elif _action in ("FALTAS_ADD", "SKILL_ADD"):
                                _normalized = _result
                                if source and source.user_id:
                                    _normalized = f"{_normalized} [author_id:{source.user_id}]"
            except Exception:
                pass
            if _normalized is not None:
                message_text = _normalized
            if _blocked:
                _adapter = self.adapters.get(source.platform)
                if _adapter:
                    _meta = {"thread_id": source.thread_id} if source.thread_id else None
                    await _adapter.send(source.chat_id, _block_msg or "Blocked.", metadata=_meta)
                return
            # COLMEIO_CHANNEL_ACL_NORMALIZE_END

"""

MODEL_BLOCK = """\
            # COLMEIO_CHANNEL_ACL_MODEL_BEGIN
            try:
                _hook_home = Path(__import__("os").getenv("HERMES_HOME") or (Path.home() / ".hermes"))
                _hook_path = _hook_home / "hooks" / "channel_acl" / "handler.py"
                if _hook_path.exists():
                    import importlib.util, sys as _sys
                    _spec = importlib.util.spec_from_file_location("colmeio_channel_acl", _hook_path)
                    if _spec and _spec.loader:
                        _mod = importlib.util.module_from_spec(_spec)
                        _sys.modules["colmeio_channel_acl"] = _mod
                        _spec.loader.exec_module(_mod)
                        _enforce = getattr(_mod, "enforce_channel_model", None)
                        if callable(_enforce):
                            turn_route = _enforce(source, turn_route)
            except Exception:
                pass

            _sp_addon = turn_route.get("system_prompt_addon")
            if _sp_addon:
                combined_ephemeral = (combined_ephemeral + "\\n\\n" + _sp_addon).strip()
            # COLMEIO_CHANNEL_ACL_MODEL_END

"""

STATUS_BLOCK = """\
        # COLMEIO_CHANNEL_ACL_STATUS_BEGIN
        # Add channel context and model routing details to /status output.
        _raw_channel_id = str(getattr(source, "chat_id", "") or "")
        _thread_id = str(getattr(source, "thread_id", "") or "")
        _parent_id = str(getattr(source, "chat_id_alt", "") or "")
        _channel_id = _parent_id or _raw_channel_id

        _channel_info_lines = [
            "",
            "**Channel Info**",
            f"  channel_id: `{_channel_id or 'n/a'}`",
        ]
        if _thread_id:
            _channel_info_lines.append(f"  thread_id: `{_thread_id}`")
        lines.extend(_channel_info_lines)

        try:
            _route_model = _resolve_gateway_model()
        except Exception:
            _route_model = "MiniMax-M2.7"
        try:
            _base_runtime = _resolve_runtime_agent_kwargs() or {}
        except Exception:
            _base_runtime = {}
        _route_provider = str(_base_runtime.get("provider", "") or "")
        _routing_note = "default (no channel rule matched)"
        try:
            _hook_home = Path(__import__("os").getenv("HERMES_HOME") or (Path.home() / ".hermes"))
            _hook_path = _hook_home / "hooks" / "channel_acl" / "handler.py"
            if _hook_path.exists():
                import importlib.util, sys as _sys
                _spec = importlib.util.spec_from_file_location("colmeio_channel_acl", _hook_path)
                if _spec and _spec.loader:
                    _mod = importlib.util.module_from_spec(_spec)
                    _sys.modules["colmeio_channel_acl"] = _mod
                    _spec.loader.exec_module(_mod)
                    _enforce = getattr(_mod, "enforce_channel_model", None)
                    if callable(_enforce):
                        _primary = {
                            "model": _route_model,
                            "provider": _route_provider,
                            "runtime": dict(_base_runtime),
                        }
                        _fake_route = _enforce(source, dict(_primary))
                        _forced_model = _fake_route.get("model") or _route_model
                        _forced_provider = (_fake_route.get("runtime") or {}).get("provider") or _route_provider

                        if _forced_model != _route_model or _forced_provider != _route_provider:
                            _routing_note = "channel-acl forced (condicionado)"
                        else:
                            _get_routing = getattr(_mod, "get_channel_routing", None)
                            if callable(_get_routing):
                                _mode, _cfg = _get_routing(
                                    _channel_id,
                                    _thread_id or None,
                                    _parent_id or None,
                                )
                                if _mode == "condicionado":
                                    _routing_note = "channel-acl matched (condicionado)"
                        _route_model = _forced_model
                        _route_provider = _forced_provider
        except Exception:
            pass

        lines.extend([
            "",
            "**Model Routing**",
            f"  model: `{_route_model or 'n/a'}`",
            f"  provider: `{_route_provider or 'n/a'}`",
            f"  route: {_routing_note}",
        ])
        # COLMEIO_CHANNEL_ACL_STATUS_END

"""


def apply_hook_files() -> None:
    HOOK_DEST.mkdir(parents=True, exist_ok=True)
    sources = {
        "handler.py": HOOK_PUBLIC_SOURCE / "handler.py",
        "config.yaml": HOOK_PRIVATE_SOURCE / "config.yaml",
        "HOOK.yaml": HOOK_PUBLIC_SOURCE / "HOOK.yaml",
    }
    for name, src in sources.items():
        dst = HOOK_DEST / name
        if not src.exists():
            raise FileNotFoundError(f"Missing hook source file: {src}")
        dst.write_bytes(src.read_bytes())
        print(f"  [ok] {name} -> {dst}")


def insert_before_anchor(content: str, marker: str, anchor: str, block: str) -> tuple[str, bool]:
    if marker in content:
        return content, False
    if anchor not in content:
        raise RuntimeError(f"anchor not found for {marker}: {anchor!r}")
    return content.replace(anchor, block + anchor, 1), True


def replace_marker_block(content: str, start_marker: str, end_marker: str, block: str) -> tuple[str, bool]:
    start = content.find(start_marker)
    if start == -1:
        return content, False
    end = content.find(end_marker, start)
    if end == -1:
        raise RuntimeError(f"found {start_marker} but missing {end_marker}")

    block_start = content.rfind("\n", 0, start)
    block_start = 0 if block_start == -1 else block_start + 1
    block_end = content.find("\n", end)
    block_end = len(content) if block_end == -1 else block_end + 1

    old_block = content[block_start:block_end]
    if old_block == block:
        return content, False
    return content[:block_start] + block + content[block_end:], True


def insert_before_first_available(
    content: str,
    marker: str,
    anchors: list[str],
    block: str,
) -> tuple[str, bool]:
    if marker in content:
        return content, False
    for anchor in anchors:
        if anchor in content:
            return content.replace(anchor, block + anchor, 1), True
    raise RuntimeError(f"anchor not found for {marker}: {anchors!r}")


def insert_after_anchor(content: str, marker: str, anchor: str, block: str) -> tuple[str, bool]:
    if marker in content:
        return content, False
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError(f"anchor not found for {marker}: {anchor!r}")
    idx_after = idx + len(anchor)
    return content[:idx_after] + block + content[idx_after:], True


def insert_after_first_available(
    content: str,
    marker: str,
    anchors: list[str],
    block: str,
) -> tuple[str, bool]:
    if marker in content:
        return content, False
    for anchor in anchors:
        idx = content.find(anchor)
        if idx != -1:
            idx_after = idx + len(anchor)
            return content[:idx_after] + block + content[idx_after:], True
    raise RuntimeError(f"anchor not found for {marker}: {anchors!r}")


def patch_status_block(content: str) -> tuple[str, bool]:
    replaced_content, replaced = replace_marker_block(
        content, STATUS_MARKER, STATUS_END_MARKER, STATUS_BLOCK
    )
    if replaced:
        return replaced_content, True
    content = replaced_content

    fn_start = content.find("    async def _handle_status_command(self, event: MessageEvent) -> str:\n")
    if fn_start == -1:
        raise RuntimeError("could not find _handle_status_command in run.py")

    fn_end = content.find("\n    async def ", fn_start + 1)
    if fn_end == -1:
        fn_end = len(content)

    section = content[fn_start:fn_end]
    return_anchor = '        return "\\n".join(lines)\n'
    if return_anchor not in section:
        raise RuntimeError("could not find return line inside _handle_status_command")

    section = section.replace(return_anchor, STATUS_BLOCK + return_anchor, 1)
    return content[:fn_start] + section + content[fn_end:], True


def apply_run_py_patches() -> int:
    run_path = _resolve_run_py()
    if run_path is None:
        print("[error] run.py not found in expected locations:", file=sys.stderr)
        for candidate in _run_path_candidates():
            print(f"  - {candidate}", file=sys.stderr)
        return 1

    original = run_path.read_text(encoding="utf-8")
    content = original
    applied: list[str] = []

    try:
        content, changed = replace_marker_block(
            content,
            NORMALIZE_MARKER,
            NORMALIZE_END_MARKER,
            NORMALIZE_BLOCK,
        )
        if changed:
            applied.append("normalize(refresh)")

        content, changed = insert_before_first_available(
            content,
            NORMALIZE_MARKER,
            [
                "            # Run the agent\n            agent_result = await self._run_agent(\n",
                "            agent_result = await self._run_agent(\n",
            ],
            NORMALIZE_BLOCK,
        )
        if changed:
            applied.append("normalize")

        content, changed = replace_marker_block(
            content,
            MODEL_MARKER,
            MODEL_END_MARKER,
            MODEL_BLOCK,
        )
        if changed:
            applied.append("model(refresh)")

        content, changed = insert_after_first_available(
            content,
            MODEL_MARKER,
            [
                "            turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs, source=source)\n",
                "            turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs)\n",
                "            turn_route = self._resolve_turn_agent_config(prompt, model, runtime_kwargs, source=source)\n",
                "            turn_route = self._resolve_turn_agent_config(prompt, model, runtime_kwargs)\n",
            ],
            MODEL_BLOCK,
        )
        if changed:
            applied.append("model")

        content, changed = patch_status_block(content)
        if changed:
            applied.append("status")
    except Exception as exc:
        print(f"[error] failed to patch run.py: {exc}", file=sys.stderr)
        return 1

    if content == original:
        print("  [ok] run.py patches already applied")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"run.py.colmeio_channel_acl.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")
    run_path.write_text(content, encoding="utf-8")
    print(f"  [ok] run.py patched: {run_path}")
    print(f"  [ok] backup: {backup}")
    print(f"  [ok] applied blocks: {', '.join(applied)}")
    return 0


def main() -> int:
    print("[apply] Channel ACL hook + run.py patches")
    print(f"[apply] source(public): {HOOK_PUBLIC_SOURCE}")
    print(f"[apply] source(private): {HOOK_PRIVATE_SOURCE}")
    print(f"[apply] run.py: {_resolve_run_py() or _run_path_candidates()[0]}")

    try:
        apply_hook_files()
    except Exception as exc:
        print(f"[error] failed to copy hook files: {exc}", file=sys.stderr)
        return 1

    return apply_run_py_patches()


if __name__ == "__main__":
    raise SystemExit(main())
