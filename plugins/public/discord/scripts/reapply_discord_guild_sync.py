#!/usr/bin/env python3
"""
Reapply Discord guild-level slash sync after hermes-agent updates.

Why:
- Older Hermes builds used coarse-grained startup sync and optional
  guild-copy behavior.
- Newer Hermes builds support native drift-based sync policies, which
  should not be overwritten by this compatibility patcher.

Default behavior:
- If Hermes already provides `DISCORD_COMMAND_SYNC_POLICY`, this patcher is a
  no-op and leaves the native sync implementation in place.
- On older builds, keep global commands only (no guild copy) to avoid
  duplicate entries in Discord's slash picker.
- Enable copy-global-to-guild only when explicitly requested via:
  DISCORD_GUILD_SYNC_GLOBAL_TO_GUILD=true
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
_ENV_AGENT_ROOT = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()

def _candidate_agent_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    if _ENV_AGENT_ROOT:
        roots.append(Path(_ENV_AGENT_ROOT).expanduser())
    if HERMES_HOME.name == ".hermes":
        roots.append(HERMES_HOME.parent / "hermes-agent")
    roots.append(Path("/local/hermes-agent"))

    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return tuple(out)


DISCORD_PATH_CANDIDATES = tuple(root / "gateway" / "platforms" / "discord.py" for root in _candidate_agent_roots())

MARKER_START = "COLMEIO_DISCORD_GUILD_SYNC_BEGIN"
MARKER_END = "COLMEIO_DISCORD_GUILD_SYNC_END"

INSERT_BLOCK_TEMPLATE = textwrap.dedent(
    """\
    # COLMEIO_DISCORD_GUILD_SYNC_BEGIN
    _enable_guild_copy = os.getenv(
        "DISCORD_GUILD_SYNC_GLOBAL_TO_GUILD", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    if _enable_guild_copy:
        guilds = list(getattr(self._client, "guilds", []) or [])
        if guilds:
            for _guild in guilds:
                try:
                    self._client.tree.copy_global_to(guild=_guild)
                    _g_synced = await self._client.tree.sync(guild=_guild)
                    logger.info(
                        "[%s] Synced %d guild slash command(s) for guild %s",
                        self.name,
                        len(_g_synced),
                        getattr(_guild, "id", "unknown"),
                    )
                except Exception as _g_exc:
                    logger.debug(
                        "[%s] Guild slash sync failed for guild %s: %s",
                        self.name,
                        getattr(_guild, "id", "unknown"),
                        _g_exc,
                    )
    # COLMEIO_DISCORD_GUILD_SYNC_END
    """
)


def _render_block(indent: str) -> str:
    lines = INSERT_BLOCK_TEMPLATE.rstrip("\n").splitlines()
    return "".join(f"{indent}{line}\n" for line in lines)


def _find_discord_py() -> Path:
    for path in DISCORD_PATH_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find discord.py in expected locations:\n"
        + "\n".join(f"- {p}" for p in DISCORD_PATH_CANDIDATES)
    )


def _replace_marker_block(content: str, start_marker: str, end_marker: str) -> tuple[str, bool]:
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

    marker_line_start = content.rfind("\n", 0, start)
    marker_line_start = 0 if marker_line_start == -1 else marker_line_start + 1
    marker_line_end = content.find("\n", marker_line_start)
    marker_line_end = len(content) if marker_line_end == -1 else marker_line_end
    marker_line = content[marker_line_start:marker_line_end]
    indent = re.match(r"[ \t]*", marker_line).group(0)
    block = _render_block(indent)

    old_block = content[block_start:block_end]
    if old_block == block:
        return content, False
    return content[:block_start] + block + content[block_end:], True


def _insert_after_global_sync_log(content: str) -> tuple[str, bool]:
    if MARKER_START in content:
        return content, False

    pattern = re.compile(
        r'(?P<line>(?P<indent>[ \t]*)logger\.info\("\[%s\] Synced %d slash command\(s\)",\s*(?:adapter_self|self)\.name,\s*len\(synced\)\)\n)'
    )
    m = pattern.search(content)
    if not m:
        raise RuntimeError("Could not find global slash sync log line to anchor guild sync patch.")
    insert_at = m.end("line")
    return content[:insert_at] + _render_block(m.group("indent")) + content[insert_at:], True


def reapply() -> int:
    try:
        discord_path = _find_discord_py()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    original = discord_path.read_text(encoding="utf-8")
    if "def _get_discord_command_sync_policy" in original:
        print("✅ Native Discord command sync policy detected; skipping guild sync compatibility patch.")
        return 0
    content = original
    applied: list[str] = []

    try:
        content, changed = _replace_marker_block(content, MARKER_START, MARKER_END)
        if changed:
            applied.append("guild_sync(refresh)")
        if MARKER_START not in content:
            content, inserted = _insert_after_global_sync_log(content)
            if inserted:
                applied.append("guild_sync")
    except Exception as exc:
        print(f"❌ Failed to patch discord.py (guild sync): {exc}", file=sys.stderr)
        return 1

    if content == original:
        print("✅ Discord guild sync patch already applied.")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"discord.py.guild_sync_patch.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")
    discord_path.write_text(content, encoding="utf-8")
    print(f"✅ Applied Discord guild sync patch to: {discord_path}")
    print(f"   Backup: {backup}")
    print(f"   Blocks: {', '.join(applied) if applied else 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
