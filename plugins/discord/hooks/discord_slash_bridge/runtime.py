from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)
_PRIMARY_DISCORD_COMMANDS = Path("/local/plugins/discord/discord_commands.json")
_PRIMARY_NODE_DISCORD_COMMANDS_DIR = Path("/local/plugins/discord/commands")
_LEGACY_DISCORD_COMMANDS = (
    Path("/local/workspace/discord/discord_commands.json"),
    Path("/local/workspace/colmeio/discord/discord_commands.json"),
)
_LEGACY_NODE_DISCORD_COMMANDS_DIRS = (
    Path("/local/workspace/discord/commands"),
    Path("/local/workspace/colmeio/discord/commands"),
)


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


_HERMES_HOME = _resolve_hermes_home()


class DiscordSlashRuntime:
    """External Discord slash runtime loaded from ~/.hermes/hooks.

    Responsibilities:
    - Override selected native commands at startup (/restart, /reboot, /metricas, /backup version)
    - Bridge unknown slash commands (from Discord API payload registration) to handlers
    - Keep behavior outside hermes-agent core so updates are easy to reapply
    """

    def __init__(self, adapter: Any, hook_dir: Path | None = None):
        self.adapter = adapter
        self.hook_dir = Path(hook_dir or (_HERMES_HOME / "hooks" / "discord_slash_bridge"))
        self.config = self._load_yaml(self.hook_dir / "config.yaml")
        self.registry = self._load_yaml(self.hook_dir / "registry.yaml")
        self.handlers = self._load_handlers_module(self.hook_dir / "handlers.py")
        self._handled_ids: set[str] = set()

        self._bridge_aliases = self._normalized_map(
            (self.config.get("aliases") or {}) | ((self.registry.get("slash_bridge") or {}).get("aliases") or {})
        )
        self._bridge_blocked = self._normalized_map(
            (self.config.get("blocked") or {}) | ((self.registry.get("slash_bridge") or {}).get("blocked") or {})
        )

        raw_bridge = (self.registry.get("slash_bridge") or {})
        raw_commands = raw_bridge.get("commands") or {}
        if not isinstance(raw_commands, dict):
            raw_commands = {}
        self._bridge_commands: Dict[str, Dict[str, Any]] = {}
        for key, value in raw_commands.items():
            name = str(key or "").strip().lower().lstrip("/")
            if not name:
                continue
            if isinstance(value, dict):
                self._bridge_commands[name] = value
            else:
                self._bridge_commands[name] = {}

        force_bridge = raw_bridge.get("force_bridge_commands") or []
        self._force_bridge = {
            str(entry or "").strip().lower().lstrip("/")
            for entry in force_bridge
            if str(entry or "").strip()
        }

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def bootstrap_tree(self, tree: Any) -> None:
        native = self.registry.get("native_overrides") or {}
        if not isinstance(native, dict):
            native = {}

        self._bootstrap_restart(tree, native.get("restart") or {})
        self._bootstrap_reboot(tree, native.get("reboot") or {})
        self._bootstrap_metricas(tree, native.get("metricas") or {})
        self._bootstrap_backup(tree, native.get("backup") or {})
        self._bootstrap_model(tree, native.get("model") or {})

    async def sync_external_payload_commands(self) -> int:
        """Upsert external guild commands from the resolved payload JSON.

        This protects payload-managed commands (e.g. /clean) from being removed by
        guild tree.sync() on startup.
        """
        payload_path = self._resolve_payload_commands_path()
        if payload_path is None:
            return 0
        if not payload_path.exists():
            return 0

        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to parse payload commands JSON: %s", exc)
            return 0

        if not isinstance(payload, list):
            return 0

        commands: list[Dict[str, Any]] = [c for c in payload if isinstance(c, dict) and c.get("name")]
        if not commands:
            return 0

        client = getattr(self.adapter, "_client", None)
        if client is None:
            return 0

        guilds = list(getattr(client, "guilds", []) or [])
        if not guilds:
            return 0

        app_id = str(
            os.getenv("DISCORD_APP_ID", "").strip()
            or getattr(client, "application_id", "")
            or getattr(getattr(client, "user", None), "id", "")
        ).strip()
        if not app_id:
            logger.debug("Cannot upsert payload commands: missing app id")
            return 0

        try:
            import discord  # type: ignore
        except Exception:
            return 0

        created = 0
        for guild in guilds:
            route = discord.http.Route(
                "POST",
                "/applications/{application_id}/guilds/{guild_id}/commands",
                application_id=app_id,
                guild_id=getattr(guild, "id", None),
            )
            for cmd in commands:
                max_attempts = 4
                for attempt in range(1, max_attempts + 1):
                    try:
                        await client.http.request(route, json=cmd)
                        created += 1
                        break
                    except Exception as exc:
                        status = int(getattr(exc, "status", 0) or 0)
                        if status == 429 and attempt < max_attempts:
                            retry_after = float(getattr(exc, "retry_after", 0) or 0)
                            if retry_after <= 0:
                                raw = str(getattr(exc, "text", "") or "")
                                try:
                                    parsed = json.loads(raw) if raw else {}
                                    retry_after = float(parsed.get("retry_after", 0) or 0)
                                except Exception:
                                    retry_after = 0
                            retry_after = min(max(retry_after, 0.5), 10.0)
                            logger.debug(
                                "Rate-limited upserting `%s` in guild %s (attempt %d/%d); retrying in %.2fs",
                                cmd.get("name"),
                                getattr(guild, "id", "unknown"),
                                attempt,
                                max_attempts,
                                retry_after,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        logger.debug(
                            "Failed to upsert external payload command `%s` in guild %s: %s",
                            cmd.get("name"),
                            getattr(guild, "id", "unknown"),
                            exc,
                        )
                        break
        return created

    @staticmethod
    def _resolve_payload_commands_path() -> Path | None:
        configured = str(os.getenv("DISCORD_COMMANDS_FILE", "") or "").strip()
        if configured:
            cfg_path = Path(configured).expanduser()
            if cfg_path.exists():
                return cfg_path

        profile = (
            str(os.getenv("DISCORD_COMMANDS_PROFILE", "") or "").strip()
            or str(os.getenv("COLMEIO_CLONE_NAME", "") or "").strip()
        )
        if profile:
            profile_name = profile[:-5] if profile.lower().endswith(".json") else profile
            for commands_dir in (_PRIMARY_NODE_DISCORD_COMMANDS_DIR, *_LEGACY_NODE_DISCORD_COMMANDS_DIRS):
                candidate = commands_dir / f"{profile_name}.json"
                if candidate.exists():
                    return candidate

        for candidate in (_PRIMARY_DISCORD_COMMANDS, *_LEGACY_DISCORD_COMMANDS):
            if candidate.exists():
                return candidate
        return _PRIMARY_DISCORD_COMMANDS

    # ------------------------------------------------------------------
    # Interaction bridge
    # ------------------------------------------------------------------

    async def on_interaction(self, interaction: Any) -> bool:
        if not self._is_chat_input(interaction):
            return False

        if self._is_handled(interaction):
            return True

        data = self.handlers.interaction_data_to_dict(interaction)
        command_name = str((data or {}).get("name") or "").strip().lower().lstrip("/")
        if not command_name:
            return False

        if command_name not in self._force_bridge and self._is_known_tree_command(interaction, command_name):
            return False

        return await self._dispatch_bridge_command(interaction, command_name, data)

    async def on_app_command_error(self, interaction: Any, error: Exception) -> bool:
        if self._is_handled(interaction):
            return True

        data = self.handlers.interaction_data_to_dict(interaction)
        command_name = str((data or {}).get("name") or "").strip().lower().lstrip("/")
        if not command_name:
            command_name = self.handlers.unknown_slash_name_from_error(error)

        if not command_name:
            return False

        try:
            import discord  # type: ignore
            not_found = isinstance(error, discord.app_commands.errors.CommandNotFound)
        except Exception:
            not_found = (error.__class__.__name__ == "CommandNotFound")

        known = self._is_known_tree_command(interaction, command_name)
        if not_found or (not known) or (command_name in self._force_bridge):
            if not data:
                data = {"name": command_name, "options": []}
            elif not data.get("name"):
                data["name"] = command_name
            return await self._dispatch_bridge_command(interaction, command_name, data)

        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _bootstrap_restart(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", True) is False:
            return

        desc = str(cfg.get("description") or "Restart the Hermes gateway")
        self._remove_chat_command(tree, "restart")

        @tree.command(name="restart", description=desc)
        async def slash_restart(interaction):
            await self.handlers.handle_restart(self.adapter, interaction, cfg)

    def _bootstrap_reboot(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", True) is False:
            return

        desc = str(cfg.get("description") or "Reboot the Hermes container")
        self._remove_chat_command(tree, "reboot")

        @tree.command(name="reboot", description=desc)
        async def slash_reboot(interaction):
            await self.handlers.handle_reboot(self.adapter, interaction, cfg)

    def _bootstrap_metricas(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", True) is False:
            return

        desc = str(cfg.get("description") or "Show Colmeio metrics dashboard")
        self._remove_chat_command(tree, "metricas")

        import discord  # type: ignore

        @tree.command(name="metricas", description=desc)
        @discord.app_commands.describe(
            dias="Janela em dias (1-365)",
            formato="Formato do dashboard",
            skill="Filtrar por skill (opcional)",
        )
        @discord.app_commands.choices(formato=[
            discord.app_commands.Choice(name="texto", value="texto"),
            discord.app_commands.Choice(name="json", value="json"),
            discord.app_commands.Choice(name="csv", value="csv"),
        ])
        async def slash_metricas(interaction, dias: int = 30, formato: str = "texto", skill: str = ""):
            options = {
                "dias": dias,
                "formato": formato,
            }
            if str(skill or "").strip():
                options["skill"] = str(skill).strip()
            await self.handlers.handle_metricas(
                self.adapter,
                interaction,
                option_values=options,
                settings=cfg,
                command_name="metricas",
            )

    def _bootstrap_backup(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", True) is False:
            return

        import discord  # type: ignore

        group_name = str(cfg.get("group_name") or "backup")
        group_desc = str(cfg.get("group_description") or "Backup Hermes agent files")
        sub_name = str(cfg.get("subcommand_name") or "version")
        sub_desc = str(cfg.get("subcommand_description") or "Create a versioned backup tar.gz")

        self._remove_chat_command(tree, group_name)

        group = discord.app_commands.Group(name=group_name, description=group_desc)

        @group.command(name=sub_name, description=sub_desc)
        @discord.app_commands.describe(version="Version label. Example: 1.0")
        async def backup_version(interaction, version: str):
            await self.handlers.handle_backup_version(
                self.adapter,
                interaction,
                version=version,
                settings=cfg,
            )

        try:
            tree.add_command(group)
        except Exception as exc:
            logger.warning("Failed to register /%s command group: %s", group_name, exc)

    @staticmethod
    def _model_choice_specs(cfg: Dict[str, Any]) -> list[Dict[str, str]]:
        raw = cfg.get("choices")
        if not isinstance(raw, list):
            raw = []
        normalized: list[Dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            label = str(item.get("label") or "").strip()
            provider = str(item.get("provider") or "").strip()
            model = str(item.get("model") or "").strip()
            if not key or not label or not provider or not model:
                continue
            normalized.append(
                {
                    "key": key,
                    "label": label,
                    "provider": provider,
                    "model": model,
                }
            )
        return normalized

    def _bootstrap_model(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", True) is False:
            return

        import discord  # type: ignore

        desc = str(cfg.get("description") or "Show or change the default model")
        option_description = str(cfg.get("option_description") or "Select the default model")
        choices_cfg = self._model_choice_specs(cfg)
        app_choices = [discord.app_commands.Choice(name=entry["label"], value=entry["key"]) for entry in choices_cfg][:25]

        self._remove_chat_command(tree, "model")

        async def _model_autocomplete(_interaction: Any, current: str):
            query = str(current or "").strip().lower()
            if not query:
                return app_choices

            filtered: list[Any] = []
            for entry in choices_cfg:
                hay = " ".join(
                    (
                        entry.get("label", ""),
                        entry.get("key", ""),
                        entry.get("provider", ""),
                        entry.get("model", ""),
                    )
                ).lower()
                if query in hay:
                    filtered.append(discord.app_commands.Choice(name=entry["label"], value=entry["key"]))
                if len(filtered) >= 25:
                    break
            return filtered

        @tree.command(name="model", description=desc)
        @discord.app_commands.describe(modelo=option_description)
        @discord.app_commands.autocomplete(modelo=_model_autocomplete)
        async def slash_model(interaction, modelo: str):
            await self.handlers.handle_model_switch(
                self.adapter,
                interaction,
                model_key=modelo,
                settings=cfg,
            )

    def _remove_chat_command(self, tree: Any, name: str) -> None:
        cmd_name = str(name or "").strip().lstrip("/")
        if not cmd_name:
            return
        try:
            tree.remove_command(cmd_name)
            return
        except TypeError:
            pass
        except Exception:
            pass

        try:
            import discord  # type: ignore
            tree.remove_command(cmd_name, type=discord.AppCommandType.chat_input)
        except Exception:
            pass

    async def _dispatch_bridge_command(self, interaction: Any, command_name: str, data: Dict[str, Any]) -> bool:
        name = str(command_name or "").strip().lower().lstrip("/")
        if not name:
            return False

        if name in self._bridge_blocked:
            self._mark_handled(interaction)
            msg = self._bridge_blocked.get(name) or "🚫 This command is not allowed."
            await self.handlers.send_ephemeral(interaction, msg)
            return True

        target_name = str(self._bridge_aliases.get(name, name) or "").strip().lower().lstrip("/")
        if not target_name:
            return False

        if target_name in self._bridge_blocked:
            self._mark_handled(interaction)
            msg = self._bridge_blocked.get(target_name) or "🚫 This command is not allowed."
            await self.handlers.send_ephemeral(interaction, msg)
            return True

        cmd_cfg = self._bridge_commands.get(target_name) or self._bridge_commands.get(name) or {}
        acl_command = str(cmd_cfg.get("acl_command") or target_name)
        allowed, acl_msg = self.handlers.check_command_acl(self.adapter, interaction, acl_command)
        if not allowed:
            self._mark_handled(interaction)
            msg = acl_msg or f"🚫 O comando `/{target_name}` não é permitido neste canal."
            await self.handlers.send_ephemeral(interaction, msg)
            return True

        options = (data or {}).get("options") or []
        option_values = self.handlers.unknown_slash_option_values(options)

        handler_name = str(cmd_cfg.get("handler") or "").strip()
        if handler_name:
            self._mark_handled(interaction)
            return await self.handlers.run_bridge_handler(
                handler_name,
                self.adapter,
                interaction,
                command_name=target_name,
                option_values=option_values,
                command_config=cmd_cfg,
            )

        dispatch_target = str(cmd_cfg.get("dispatch") or target_name)
        followup_message = cmd_cfg.get("followup_message")
        cleanup = bool(cmd_cfg.get("cleanup", True))

        self._mark_handled(interaction)
        return await self.handlers.dispatch_slash_to_gateway(
            self.adapter,
            interaction,
            dispatch_target,
            options,
            followup_message=followup_message,
            cleanup=cleanup,
        )

    def _is_known_tree_command(self, interaction: Any, command_name: str) -> bool:
        tree = getattr(getattr(self.adapter, "_client", None), "tree", None)
        if tree is None:
            return False

        name = str(command_name or "").strip().lower().lstrip("/")
        if not name:
            return False

        try:
            guild = getattr(interaction, "guild", None)
            if guild is not None and tree.get_command(name, guild=guild) is not None:
                return True
        except Exception:
            pass

        try:
            return tree.get_command(name) is not None
        except Exception:
            return False

    def _is_chat_input(self, interaction: Any) -> bool:
        try:
            if int(getattr(interaction, "type", 0) or 0) != 2:
                return False
        except Exception:
            return False

        data = self.handlers.interaction_data_to_dict(interaction)
        try:
            dtype = int((data or {}).get("type") or 1)
        except Exception:
            dtype = 1
        return dtype == 1

    def _is_handled(self, interaction: Any) -> bool:
        try:
            if bool(getattr(interaction, "_colmeio_registry_handled", False)):
                return True
        except Exception:
            pass

        iid = str(getattr(interaction, "id", "") or "")
        return bool(iid and iid in self._handled_ids)

    def _mark_handled(self, interaction: Any) -> None:
        try:
            setattr(interaction, "_colmeio_registry_handled", True)
        except Exception:
            pass

        iid = str(getattr(interaction, "id", "") or "")
        if not iid:
            return
        self._handled_ids.add(iid)

    @staticmethod
    def _normalized_map(raw: Any) -> Dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, str] = {}
        for key, value in raw.items():
            k = str(key or "").strip().lower().lstrip("/")
            if not k:
                continue
            out[k] = str(value or "").strip()
        return out

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.debug("Failed to load YAML %s: %s", path, exc)
            return {}

    def _load_handlers_module(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"discord slash handlers file not found: {path}")

        mod_name = "colmeio_discord_slash_handlers"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if not spec or not spec.loader:
            raise RuntimeError(f"failed to create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module


def create_runtime(adapter: Any) -> DiscordSlashRuntime:
    return DiscordSlashRuntime(adapter)
