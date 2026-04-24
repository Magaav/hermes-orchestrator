#!/usr/bin/env python3
"""
Single bootstrap patch for Colmeio Discord customizations.

What it does:
1) Sync external runtime files to ~/.hermes/hooks/discord_slash_bridge/
2) Patch gateway/platforms/discord.py with a small stable bootstrap that:
   - loads external runtime from hooks
   - delegates unknown slash interactions and app command errors
   - applies command overrides at slash registration time

This replaces per-command patch scripts with one runtime bootstrap architecture.
"""

from __future__ import annotations

import shutil
import sys
import os
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

HOOK_PUBLIC_SRC_DIR = DISCORD_PLUGIN_ROOT / "hooks" / "discord_slash_bridge"
HOOK_PRIVATE_SRC_DIR = DISCORD_PRIVATE_ROOT / "hooks" / "discord_slash_bridge"
HOOK_DST_DIR = HERMES_HOME / "hooks" / "discord_slash_bridge"

HELPER_START = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_BEGIN"
HELPER_END = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_END"

INTERACTION_START = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_INTERACTION_BEGIN"
INTERACTION_END = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_INTERACTION_END"
OLD_INTERACTION_START = "COLMEIO_DISCORD_UNKNOWN_SLASH_INTERACTION_BEGIN"
OLD_INTERACTION_END = "COLMEIO_DISCORD_UNKNOWN_SLASH_INTERACTION_END"

ERROR_START = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_ERROR_BEGIN"
ERROR_END = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_ERROR_END"
OLD_ERROR_START = "COLMEIO_DISCORD_UNKNOWN_SLASH_ERROR_BEGIN"
OLD_ERROR_END = "COLMEIO_DISCORD_UNKNOWN_SLASH_ERROR_END"

TREE_BOOTSTRAP_START = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_TREE_BEGIN"
TREE_BOOTSTRAP_END = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_TREE_END"
SYNC_START = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_SYNC_BEGIN"
SYNC_END = "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_SYNC_END"

HELPER_BLOCK = """\
    # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_BEGIN
    def _colmeio_load_discord_slash_runtime(self):
        runtime = getattr(self, "_colmeio_discord_slash_runtime", None)
        if runtime is not None:
            return runtime

        try:
            from pathlib import Path as _BootPath
            hook_home = _BootPath(os.getenv("HERMES_HOME") or (_BootPath.home() / ".hermes"))
            hook_path = hook_home / "hooks" / "discord_slash_bridge" / "runtime.py"
            if not hook_path.exists():
                self._colmeio_discord_slash_runtime = None
                return None

            import importlib.util
            import sys as _sys

            spec = importlib.util.spec_from_file_location("colmeio_discord_slash_runtime", hook_path)
            if not spec or not spec.loader:
                self._colmeio_discord_slash_runtime = None
                return None

            mod = importlib.util.module_from_spec(spec)
            _sys.modules["colmeio_discord_slash_runtime"] = mod
            spec.loader.exec_module(mod)

            factory = getattr(mod, "create_runtime", None)
            if callable(factory):
                runtime = factory(self)
            else:
                cls = getattr(mod, "DiscordSlashRuntime", None)
                runtime = cls(self) if cls else None

            self._colmeio_discord_slash_runtime = runtime
            return runtime
        except Exception as e:
            logger.warning("Failed to load Colmeio Discord slash runtime: %s", e, exc_info=True)
            self._colmeio_discord_slash_runtime = None
            return None

    async def _colmeio_runtime_on_interaction(self, interaction: discord.Interaction) -> bool:
        runtime = self._colmeio_load_discord_slash_runtime()
        if runtime is None:
            return False
        handler = getattr(runtime, "on_interaction", None)
        if not callable(handler):
            return False
        try:
            return bool(await handler(interaction))
        except Exception as e:
            logger.debug("Colmeio slash runtime interaction hook failed: %s", e)
            return False

    async def _colmeio_runtime_on_app_command_error(self, interaction: discord.Interaction, error: Exception) -> bool:
        runtime = self._colmeio_load_discord_slash_runtime()
        if runtime is None:
            return False
        handler = getattr(runtime, "on_app_command_error", None)
        if not callable(handler):
            return False
        try:
            return bool(await handler(interaction, error))
        except Exception as e:
            _idata = {}
            try:
                parser = getattr(self, "_interaction_data_to_dict", None)
                if callable(parser):
                    _idata = parser(interaction) or {}
            except Exception:
                _idata = {}
            _cmd = str((_idata or {}).get("name") or "").strip().lower()
            logger.warning(
                "Colmeio slash runtime app-command error hook failed: command=%s interaction_id=%s error=%s",
                _cmd or "unknown",
                str(getattr(interaction, "id", "") or "unknown"),
                e,
                exc_info=True,
            )
            return False

    def _colmeio_runtime_bootstrap_tree(self, tree: Any) -> None:
        runtime = self._colmeio_load_discord_slash_runtime()
        if runtime is None:
            return
        bootstrap = getattr(runtime, "bootstrap_tree", None)
        if not callable(bootstrap):
            return
        try:
            bootstrap(tree)
        except Exception as e:
            logger.debug("Colmeio slash runtime tree bootstrap failed: %s", e)
    # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_END
"""

INTERACTION_BLOCK = """\
            # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_INTERACTION_BEGIN
            @self._client.event
            async def on_interaction(interaction: discord.Interaction):
                try:
                    if int(getattr(interaction, "type", 0) or 0) != 2:
                        return

                    if await self._colmeio_runtime_on_interaction(interaction):
                        return

                    # Legacy fallback if helper still exists in this runtime file.
                    fallback = getattr(self, "_handle_unknown_slash_command", None)
                    if callable(fallback):
                        data = {}
                        parser = getattr(self, "_interaction_data_to_dict", None)
                        if callable(parser):
                            try:
                                data = parser(interaction)
                            except Exception:
                                data = {}
                        command_name = str((data or {}).get("name") or "").strip().lower()
                        if command_name:
                            tree = getattr(self._client, "tree", None)
                            known = False
                            if tree is not None:
                                try:
                                    guild = getattr(interaction, "guild", None)
                                    if guild is not None:
                                        known = tree.get_command(command_name, guild=guild) is not None
                                    if not known:
                                        known = tree.get_command(command_name) is not None
                                except Exception:
                                    known = False
                            if not known:
                                handled = await fallback(interaction)
                                if handled:
                                    return
                except Exception as e:
                    logger.debug("Colmeio interaction bridge hook failed: %s", e)
            # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_INTERACTION_END
"""

ERROR_BLOCK = """\
        # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_ERROR_BEGIN
        async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            data = {}
            try:
                parser = getattr(self, "_interaction_data_to_dict", None)
                if callable(parser):
                    data = parser(interaction) or {}
                elif isinstance(getattr(interaction, "data", None), dict):
                    data = dict(getattr(interaction, "data", {}) or {})
            except Exception:
                data = {}

            command_name = str((data or {}).get("name") or "").strip().lower().lstrip("/")
            options = (data or {}).get("options")
            error_ref = f"dcerr-{int(time.time())}-{str(getattr(interaction, 'id', 'na'))}"

            try:
                if await self._colmeio_runtime_on_app_command_error(interaction, error):
                    return
            except Exception as bridge_exc:
                logger.warning(
                    "Colmeio app command error bridge failed: ref=%s command=%s interaction_id=%s error=%s",
                    error_ref,
                    command_name or "unknown",
                    str(getattr(interaction, "id", "") or "unknown"),
                    bridge_exc,
                    exc_info=True,
                )

            logger.warning(
                "Discord slash command error: ref=%s type=%s command=%s user_id=%s channel_id=%s guild_id=%s options=%s response_done=%s error=%s",
                error_ref,
                type(error).__name__,
                command_name or "unknown",
                str(getattr(getattr(interaction, "user", None), "id", "") or "unknown"),
                str(getattr(getattr(interaction, "channel", None), "id", "") or "unknown"),
                str(getattr(getattr(interaction, "guild", None), "id", "") or "unknown"),
                str(options)[:1200],
                bool(getattr(getattr(interaction, "response", None), "is_done", lambda: False)()),
                error,
                exc_info=True,
            )
            try:
                if type(error).__name__ == "CommandNotFound":
                    msg = f"❌ Comando não reconhecido pelo gateway: `/{command_name or 'desconhecido'}`. Ref: `{error_ref}`"
                else:
                    msg = f"❌ Erro ao executar o comando. Ref: `{error_ref}`"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
        if callable(getattr(tree, "error", None)):
            tree.error(on_app_command_error)
        # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_ERROR_END
"""

TREE_BOOTSTRAP_BLOCK = """\
        # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_TREE_BEGIN
        try:
            self._colmeio_runtime_bootstrap_tree(tree)
        except Exception as e:
            logger.debug("Colmeio runtime bootstrap invocation failed: %s", e)
        # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_TREE_END
        try:
            _metricas_known = tree.get_command("metricas") is not None
            _runtime_loaded = self._colmeio_load_discord_slash_runtime() is not None
            logger.info(
                "[%s] Slash bootstrap check: runtime_loaded=%s metricas_registered=%s",
                self.name,
                _runtime_loaded,
                _metricas_known,
            )
        except Exception as e:
            logger.debug("[%s] Slash bootstrap verification failed: %s", self.name, e)
"""

SYNC_BLOCK = """\
                # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_SYNC_BEGIN
                try:
                    runtime = adapter_self._colmeio_load_discord_slash_runtime()
                    if runtime is not None:
                        sync_payload = getattr(runtime, "sync_external_payload_commands", None)
                        if callable(sync_payload):
                            _merged = await sync_payload()
                            if _merged:
                                logger.info(
                                    "[%s] Upserted %d external payload slash command(s)",
                                    adapter_self.name,
                                    _merged,
                                )
                except Exception as _col_exc:
                    logger.debug("[%s] External payload upsert failed: %s", adapter_self.name, _col_exc)
                # COLMEIO_DISCORD_COMMAND_BOOTSTRAP_SYNC_END
"""


def _find_discord_py() -> Path:
    for path in DISCORD_PATH_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find discord.py in expected locations:\n"
        + "\n".join(f"- {p}" for p in DISCORD_PATH_CANDIDATES)
    )


def _copy_tree(src: Path, dst: Path, *, skip_names: set[str] | None = None) -> None:
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"hook source directory not found: {src}")

    dst.mkdir(parents=True, exist_ok=True)
    skip = set(skip_names or set())

    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part == "__pycache__" for part in rel.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if rel.name in skip:
            continue

        out = dst / rel
        if path.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue

        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def _sync_hook_dir(public_src: Path, private_src: Path, dst: Path) -> None:
    _copy_tree(public_src, dst, skip_names={"config.yaml", "registry.yaml"})
    if not private_src.exists() or not private_src.is_dir():
        raise FileNotFoundError(f"private hook source directory not found: {private_src}")
    for name in ("config.yaml", "registry.yaml"):
        src = private_src / name
        if not src.exists():
            raise FileNotFoundError(f"missing private slash-bridge runtime file: {src}")
        out = dst / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)


def _replace_marker_block(content: str, start_marker: str, end_marker: str, block: str) -> tuple[str, bool]:
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
        return content, True

    return content[:block_start] + block + content[block_end:], True


def _upsert_helper_block(content: str) -> str:
    content, found = _replace_marker_block(content, HELPER_START, HELPER_END, HELPER_BLOCK)
    if found:
        return content

    anchor = "\n    def _register_slash_commands(self) -> None:\n"
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError("Could not find _register_slash_commands anchor for helper block insertion.")
    return content[:idx] + "\n" + HELPER_BLOCK + content[idx:]


def _upsert_interaction_block(content: str) -> str:
    content, found = _replace_marker_block(content, INTERACTION_START, INTERACTION_END, INTERACTION_BLOCK)
    if found:
        return content

    content, found = _replace_marker_block(content, OLD_INTERACTION_START, OLD_INTERACTION_END, INTERACTION_BLOCK)
    if found:
        return content

    anchor = "\n            @self._client.event\n            async def on_message(message: DiscordMessage):\n"
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError("Could not find on_message anchor to insert interaction hook block.")

    return content[:idx] + "\n" + INTERACTION_BLOCK + content[idx:]


def _upsert_error_block(content: str) -> str:
    content, found = _replace_marker_block(content, ERROR_START, ERROR_END, ERROR_BLOCK)
    if found:
        return content

    content, found = _replace_marker_block(content, OLD_ERROR_START, OLD_ERROR_END, ERROR_BLOCK)
    if found:
        return content

    anchor = "\n        @tree.command("
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError("Could not find first @tree.command anchor for error hook insertion.")

    tree_line = "tree = self._client.tree"
    tree_idx = content.rfind(tree_line, 0, idx)
    if tree_idx == -1:
        raise RuntimeError("Could not find `tree = self._client.tree` before command registration.")

    line_end = content.find("\n", tree_idx)
    if line_end == -1:
        line_end = len(content)
    insert_at = line_end + 1
    return content[:insert_at] + "\n" + ERROR_BLOCK + content[insert_at:]


def _upsert_tree_bootstrap_call(content: str) -> str:
    content, found = _replace_marker_block(content, TREE_BOOTSTRAP_START, TREE_BOOTSTRAP_END, TREE_BOOTSTRAP_BLOCK)
    if found:
        return content

    anchor = "\n    def _build_slash_event(self, interaction: discord.Interaction, text: str) -> MessageEvent:\n"
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError("Could not find _build_slash_event anchor for tree bootstrap insertion.")

    return content[:idx] + "\n" + TREE_BOOTSTRAP_BLOCK + content[idx:]


def _upsert_post_sync_block(content: str) -> str:
    content, found = _replace_marker_block(content, SYNC_START, SYNC_END, SYNC_BLOCK)
    if found:
        return content

    anchor = "\n                adapter_self._ready_event.set()\n"
    idx = content.find(anchor)
    if idx == -1:
        raise RuntimeError("Could not find ready_event.set anchor for payload sync insertion.")

    return content[:idx] + "\n" + SYNC_BLOCK + content[idx:]


def reapply() -> int:
    try:
        discord_path = _find_discord_py()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    try:
        _sync_hook_dir(HOOK_PUBLIC_SRC_DIR, HOOK_PRIVATE_SRC_DIR, HOOK_DST_DIR)
    except Exception as exc:
        print(f"❌ Failed to sync slash runtime hooks: {exc}", file=sys.stderr)
        return 1

    content = discord_path.read_text(encoding="utf-8")
    original = content

    try:
        content = _upsert_helper_block(content)
        content = _upsert_interaction_block(content)
        content = _upsert_error_block(content)
        content = _upsert_tree_bootstrap_call(content)
        content = _upsert_post_sync_block(content)
    except Exception as exc:
        print(f"❌ Failed to patch discord.py bootstrap: {exc}", file=sys.stderr)
        return 1

    if content == original:
        print("✅ Discord command bootstrap already applied.")
        print(f"   Hook runtime synced to: {HOOK_DST_DIR}")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"discord.py.command_bootstrap.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")
    discord_path.write_text(content, encoding="utf-8")

    print(f"✅ Applied Discord command bootstrap to: {discord_path}")
    print(f"   Hook runtime synced to: {HOOK_DST_DIR}")
    print(f"   Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
