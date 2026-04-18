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
_PRIMARY_NODE_DISCORD_COMMANDS_DIR = Path("/local/plugins/private/discord/commands")


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


_HERMES_HOME = _resolve_hermes_home()


class DiscordSlashRuntime:
    """External Discord slash runtime loaded from ~/.hermes/hooks.

    Responsibilities:
    - Override selected native commands at startup (/restart, /reboot, /metricas, /backup, /acl)
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
        self._hide_skill_group = self._is_enabled(raw_bridge.get("hide_skill_group"), default=False)
        raw_payload_exclude = raw_bridge.get("payload_exclude_commands")
        if isinstance(raw_payload_exclude, str):
            raw_payload_exclude = [raw_payload_exclude]
        elif not isinstance(raw_payload_exclude, list):
            raw_payload_exclude = []
        self._payload_exclude_commands = {
            self._normalize_command_name(entry)
            for entry in raw_payload_exclude
            if self._normalize_command_name(entry)
        }

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def bootstrap_tree(self, tree: Any) -> None:
        self._install_tree_acl_check(tree)

        native = self.registry.get("native_overrides") or {}
        if not isinstance(native, dict):
            native = {}

        self._bootstrap_restart(tree, native.get("restart") or {})
        self._bootstrap_reboot(tree, native.get("reboot") or {})
        self._bootstrap_metricas(tree, native.get("metricas") or {})
        self._bootstrap_backup(tree, native.get("backup") or {})
        self._bootstrap_acl(tree, native.get("acl") or {})
        self._bootstrap_model(tree, native.get("model") or {})

        if self._hide_skill_group:
            self._remove_chat_command(tree, "skill")

    def _install_tree_acl_check(self, tree: Any) -> None:
        if bool(getattr(tree, "_colmeio_role_acl_check_installed", False)):
            return

        checker_decorator = getattr(tree, "interaction_check", None)
        if not callable(checker_decorator):
            return

        @checker_decorator
        async def _colmeio_role_acl_interaction_check(interaction: Any) -> bool:
            try:
                if not self._is_chat_input(interaction):
                    return True

                data = self.handlers.interaction_data_to_dict(interaction)
                command_name = str((data or {}).get("name") or "").strip().lower().lstrip("/")
                if not command_name:
                    return True

                acl_command = self._resolve_acl_command_name(command_name)
                allowed, acl_msg, _ctx = await self.handlers.check_role_acl(interaction, acl_command)
                if allowed:
                    return True

                msg = acl_msg or f"🚫 ACL: `/{acl_command}` não permitido."
                await self.handlers.send_ephemeral(interaction, msg)
                return False
            except Exception as exc:
                logger.warning("Role ACL interaction check failed: %s", exc, exc_info=True)
                try:
                    await self.handlers.send_ephemeral(
                        interaction,
                        "🚫 ACL: falha ao validar permissões deste comando.",
                    )
                except Exception:
                    pass
                return False

        try:
            setattr(tree, "_colmeio_role_acl_check_installed", True)
        except Exception:
            pass

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

        excluded_names = self._payload_excluded_names()
        filtered_commands: list[Dict[str, Any]] = []
        seen_payload_names: set[str] = set()
        for cmd in commands:
            cmd_name = self._normalize_command_name(cmd.get("name"))
            if not cmd_name:
                continue
            if cmd_name in excluded_names:
                continue
            if cmd_name in seen_payload_names:
                continue
            seen_payload_names.add(cmd_name)
            filtered_commands.append(cmd)
        commands = filtered_commands

        created = 0
        for guild in guilds:
            if excluded_names:
                try:
                    await self._prune_guild_commands(
                        discord=discord,
                        client=client,
                        guild=guild,
                        app_id=app_id,
                        excluded_names=excluded_names,
                    )
                except Exception as exc:
                    logger.debug(
                        "Failed to prune excluded guild commands in guild %s: %s",
                        getattr(guild, "id", "unknown"),
                        exc,
                    )

            if not commands:
                continue

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

    async def _prune_guild_commands(
        self,
        *,
        discord: Any,
        client: Any,
        guild: Any,
        app_id: str,
        excluded_names: set[str],
    ) -> int:
        if not excluded_names:
            return 0

        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            return 0

        list_route = discord.http.Route(
            "GET",
            "/applications/{application_id}/guilds/{guild_id}/commands",
            application_id=app_id,
            guild_id=guild_id,
        )

        existing = await client.http.request(list_route)
        if not isinstance(existing, list):
            return 0

        pruned = 0
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            cmd_name = self._normalize_command_name(entry.get("name"))
            if cmd_name not in excluded_names:
                continue
            command_id = str(entry.get("id") or "").strip()
            if not command_id:
                continue

            delete_route = discord.http.Route(
                "DELETE",
                "/applications/{application_id}/guilds/{guild_id}/commands/{command_id}",
                application_id=app_id,
                guild_id=guild_id,
                command_id=command_id,
            )
            try:
                await client.http.request(delete_route)
                pruned += 1
            except Exception as exc:
                logger.debug(
                    "Failed to delete guild command `%s` (%s) in guild %s: %s",
                    cmd_name,
                    command_id,
                    guild_id,
                    exc,
                )
        return pruned

    @staticmethod
    def _resolve_payload_commands_path() -> Path | None:
        configured = str(os.getenv("DISCORD_COMMANDS_FILE", "") or "").strip()
        if configured:
            cfg_path = Path(configured).expanduser()
            if cfg_path.exists():
                return cfg_path
            logger.debug("DISCORD_COMMANDS_FILE is set but missing: %s", cfg_path)

        node_name = str(os.getenv("NODE_NAME", "") or "").strip()
        if node_name:
            profile_name = node_name[:-5] if node_name.lower().endswith(".json") else node_name
            candidate = _PRIMARY_NODE_DISCORD_COMMANDS_DIR / f"{profile_name}.json"
            if candidate.exists():
                return candidate
            logger.debug("NODE_NAME resolved payload is missing: %s", candidate)

        return None

    @staticmethod
    def _runtime_node_name() -> str:
        raw = str(os.getenv("NODE_NAME", "") or "").strip()
        if raw:
            return raw[:-5].lower() if raw.lower().endswith(".json") else raw.lower()

        try:
            parts = _HERMES_HOME.parts
            idx = parts.index("nodes")
            if idx + 1 < len(parts):
                return str(parts[idx + 1]).strip().lower()
        except Exception:
            pass

        return "orchestrator"

    def _backup_enabled_for_node(self, cfg: Dict[str, Any]) -> bool:
        raw_nodes = cfg.get("enabled_nodes")
        if not isinstance(raw_nodes, list):
            return True
        allowed = {
            str(entry or "").strip().lower()
            for entry in raw_nodes
            if str(entry or "").strip()
        }
        if not allowed:
            return True
        return self._runtime_node_name() in allowed

    @staticmethod
    def _normalize_command_name(value: Any) -> str:
        return str(value or "").strip().lower().lstrip("/")

    @staticmethod
    def _is_enabled(value: Any, *, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        raw = str(value).strip().lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "on"}

    def _native_override_command_names(self) -> set[str]:
        native = self.registry.get("native_overrides")
        if not isinstance(native, dict):
            return set()

        out: set[str] = set()
        for key, cfg in native.items():
            key_name = self._normalize_command_name(key)
            if not key_name:
                continue

            block = cfg if isinstance(cfg, dict) else {}
            if not self._is_enabled(block.get("enabled"), default=True):
                continue

            if key_name == "backup":
                cmd_name = self._normalize_command_name(
                    block.get("group_name") or block.get("command_name") or "backup"
                )
            else:
                cmd_name = key_name

            if cmd_name:
                out.add(cmd_name)

        return out

    def _payload_excluded_names(self) -> set[str]:
        excluded = set(self._payload_exclude_commands)
        excluded.update(self._native_override_command_names())
        excluded.add("skill")
        return {name for name in excluded if name}

    @staticmethod
    def _backup_node_choice_specs(cfg: Dict[str, Any]) -> list[Dict[str, str]]:
        raw = cfg.get("node_choices")
        if not isinstance(raw, list):
            raw = ["orchestrator", "all"]

        specs: list[Dict[str, str]] = []
        for item in raw:
            if isinstance(item, dict):
                value = str(item.get("value") or "").strip().lower()
                label = str(item.get("label") or value).strip()
            else:
                value = str(item or "").strip().lower()
                label = value
            if not value:
                continue
            if any(value == spec["value"] for spec in specs):
                continue
            specs.append({"value": value, "label": label or value})

        if not specs:
            specs = [{"value": "orchestrator", "label": "orchestrator"}, {"value": "all", "label": "all"}]
        return specs

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

        known = self._is_known_tree_command(interaction, command_name)
        if command_name not in self._force_bridge and known:
            return False

        acl_command = self._resolve_acl_command_name(command_name)
        role_allowed, role_msg, _role_ctx = await self.handlers.check_role_acl(interaction, acl_command)
        if not role_allowed:
            self._mark_handled(interaction)
            msg = role_msg or f"🚫 ACL: `/{acl_command}` não permitido."
            await self.handlers.send_ephemeral(interaction, msg)
            return True

        return await self._dispatch_bridge_command(interaction, command_name, data)

    async def on_app_command_error(self, interaction: Any, error: Exception) -> bool:
        if self._is_handled(interaction):
            return True

        data = self.handlers.interaction_data_to_dict(interaction)
        command_name = str((data or {}).get("name") or "").strip().lower().lstrip("/")
        if not command_name:
            command_name = self.handlers.unknown_slash_name_from_error(error)

        if not command_name:
            logger.warning(
                "Slash bridge could not resolve command from app-command error: type=%s interaction_id=%s error=%s data=%s",
                type(error).__name__,
                str(getattr(interaction, "id", "") or "unknown"),
                error,
                str(data)[:1200],
            )
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
            try:
                handled = await self._dispatch_bridge_command(interaction, command_name, data)
            except Exception as dispatch_exc:
                logger.warning(
                    "Slash bridge dispatch exception: command=%s type=%s not_found=%s known=%s interaction_id=%s error=%s data=%s",
                    command_name,
                    type(error).__name__,
                    not_found,
                    known,
                    str(getattr(interaction, "id", "") or "unknown"),
                    dispatch_exc,
                    str(data)[:1200],
                    exc_info=True,
                )
                raise

            if not handled:
                logger.warning(
                    "Slash bridge dispatch returned unhandled: command=%s type=%s not_found=%s known=%s interaction_id=%s data=%s",
                    command_name,
                    type(error).__name__,
                    not_found,
                    known,
                    str(getattr(interaction, "id", "") or "unknown"),
                    str(data)[:1200],
                )
            return handled

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
        if not self._backup_enabled_for_node(cfg):
            return

        import discord  # type: ignore

        command_name = str(cfg.get("group_name") or cfg.get("command_name") or "backup")
        command_desc = str(
            cfg.get("command_description")
            or cfg.get("subcommand_description")
            or "Create backup for one node or all nodes and mirror to Google Drive"
        )
        choice_specs = self._backup_node_choice_specs(cfg)
        node_choices = [
            discord.app_commands.Choice(name=entry["label"], value=entry["value"])
            for entry in choice_specs[:25]
        ]
        valid_nodes = {entry["value"] for entry in choice_specs}
        default_node = str(cfg.get("default_node") or "").strip().lower()
        if not default_node:
            default_node = choice_specs[0]["value"]
        if default_node not in valid_nodes:
            default_node = choice_specs[0]["value"]

        self._remove_chat_command(tree, command_name)

        @tree.command(name=command_name, description=command_desc)
        @discord.app_commands.describe(
            version="Version label (required). Example: 2.0",
            node="Node target (`orchestrator`, `colmeio`, `catatau`) or `all`",
        )
        @discord.app_commands.choices(node=node_choices)
        async def backup_command(interaction, version: str, node: str):
            await self.handlers.handle_backup_version(
                self.adapter,
                interaction,
                version=version,
                node=node or default_node,
                settings=cfg,
            )

    def _model_choice_specs(self, cfg: Dict[str, Any]) -> list[Dict[str, str]]:
        try:
            choices = self.handlers.list_model_choice_specs(settings=cfg)
        except Exception:
            choices = []
        return [dict(item) for item in choices if isinstance(item, dict)]

    def _known_acl_commands(self) -> list[str]:
        out: set[str] = {"status", "help", "usage", "provider", "acl"}

        native = self.registry.get("native_overrides")
        if isinstance(native, dict):
            for key, value in native.items():
                name = self._normalize_command_name(key)
                if not name:
                    continue
                if isinstance(value, dict) and self._is_enabled(value.get("enabled"), default=True) is False:
                    continue
                out.add(name)

        out.update(self._bridge_commands.keys())
        out.update(self._bridge_aliases.values())
        out.update(self._force_bridge)
        return sorted(item for item in out if item)

    @staticmethod
    def _autocomplete_simple_values(discord_mod: Any, values: list[str], current: str) -> list[Any]:
        query = str(current or "").strip().lower()
        out: list[Any] = []
        for value in values:
            token = str(value or "").strip()
            if not token:
                continue
            if query and query not in token.lower():
                continue
            out.append(discord_mod.app_commands.Choice(name=token, value=token))
            if len(out) >= 25:
                break
        return out

    @staticmethod
    def _autocomplete_csv_values(discord_mod: Any, values: list[str], current: str, *, normalize_command: bool = False) -> list[Any]:
        raw = str(current or "")
        parts = [part.strip() for part in raw.split(",")]
        if not parts:
            parts = [""]
        prefix_parts = [part for part in parts[:-1] if part]
        query = parts[-1].strip().lower()
        selected = {
            item.lower().lstrip("/") if normalize_command else item.lower()
            for item in prefix_parts
            if item
        }
        prefix = ", ".join(prefix_parts)

        out: list[Any] = []
        for value in values:
            token = str(value or "").strip()
            if not token:
                continue
            token_match = token.lower().lstrip("/") if normalize_command else token.lower()
            if token_match in selected:
                continue
            if query and query not in token_match:
                continue
            completed = f"{prefix}, {token}" if prefix else token
            out.append(discord_mod.app_commands.Choice(name=token, value=completed))
            if len(out) >= 25:
                break
        return out

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

    def _bootstrap_acl(self, tree: Any, cfg: Dict[str, Any]) -> None:
        if cfg.get("enabled", False) is False:
            return

        import discord  # type: ignore

        desc = str(cfg.get("description") or "Gerenciar ACL de comandos e canais")
        cmd_desc = str(cfg.get("command_description") or "Slash command alvo (ex.: metricas)")
        role_desc = str(cfg.get("role_description") or "Role mínima (ex.: gerente, admin ou @everyone)")
        channel_desc = str(cfg.get("channel_description") or "Canal alvo (channel_id numérico)")
        mode_desc = str(cfg.get("mode_description") or "Modo: default (livre) ou specific (condicionado)")
        model_key_desc = str(cfg.get("model_key_description") or "Obrigatório em mode:specific")
        instructions_desc = str(cfg.get("instructions_description") or "Instruções extras do canal (opcional)")
        allowed_commands_desc = str(cfg.get("allowed_commands_description") or "CSV de comandos permitidos (opcional)")
        allowed_skills_desc = str(cfg.get("allowed_skills_description") or "CSV de skills permitidas (opcional)")
        always_allowed_desc = str(cfg.get("always_allowed_description") or "CSV de comandos sempre permitidos (opcional)")
        default_action_desc = str(cfg.get("default_action_description") or "Ação padrão para texto livre (opcional)")
        free_text_policy_desc = str(cfg.get("free_text_policy_description") or "Política de texto livre (opcional)")
        label_desc = str(
            cfg.get("label_description")
            or cfg.get("store_description")
            or "Label fixa para automações do canal (opcional)"
        )
        command_specs = self.handlers.list_acl_command_names(extra_commands=self._known_acl_commands())
        role_specs = self.handlers.list_acl_role_specs()
        model_specs = self._model_choice_specs(cfg)
        skill_specs = self.handlers.list_skill_name_choices()
        default_action_specs = ["skill:add"]
        free_text_policy_specs = ["strict_item", "auto_add"]

        async def _acl_command_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_simple_values(discord, command_specs, current)

        async def _acl_role_autocomplete(_interaction: Any, current: str):
            query = str(current or "").strip().lower()
            out: list[Any] = []
            for entry in role_specs:
                token = str(entry.get("token") or "").strip()
                label = str(entry.get("label") or token).strip() or token
                if not token:
                    continue
                hay = f"{label} {token}".lower()
                if query and query not in hay:
                    continue
                name = f"{label} ({token})" if token != label else label
                out.append(discord.app_commands.Choice(name=name[:100], value=token))
                if len(out) >= 25:
                    break
            return out

        async def _acl_model_key_autocomplete(_interaction: Any, current: str):
            query = str(current or "").strip().lower()
            out: list[Any] = []
            for entry in model_specs:
                key = str(entry.get("key") or "").strip()
                label = str(entry.get("label") or key).strip() or key
                provider = str(entry.get("provider") or "").strip()
                model_name = str(entry.get("model") or "").strip()
                hay = f"{key} {label} {provider} {model_name}".lower()
                if query and query not in hay:
                    continue
                out.append(discord.app_commands.Choice(name=label[:100], value=key))
                if len(out) >= 25:
                    break
            return out

        async def _acl_allowed_commands_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_csv_values(discord, command_specs, current, normalize_command=True)

        async def _acl_always_allowed_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_csv_values(discord, command_specs, current, normalize_command=True)

        async def _acl_allowed_skills_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_csv_values(discord, skill_specs, current)

        async def _acl_default_action_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_simple_values(discord, default_action_specs, current)

        async def _acl_free_text_policy_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_simple_values(discord, free_text_policy_specs, current)

        async def _acl_label_autocomplete(_interaction: Any, current: str):
            return self._autocomplete_simple_values(discord, ["loja1", "loja2"], current)

        self._remove_chat_command(tree, "acl")
        acl_group = discord.app_commands.Group(name="acl", description=desc)

        @acl_group.command(name="command", description="Atualiza ACL de slash command por role")
        @discord.app_commands.describe(command=cmd_desc, role=role_desc)
        @discord.app_commands.autocomplete(command=_acl_command_autocomplete, role=_acl_role_autocomplete)
        async def acl_command(interaction, command: str, role: str):
            await self.handlers.handle_acl_command_update(
                self.adapter,
                interaction,
                command_value=command,
                role_value=role,
                settings=cfg,
            )

        @acl_group.command(name="channel", description="Atualiza ACL de canal e policy de execução")
        @discord.app_commands.describe(
            channel=channel_desc,
            mode=mode_desc,
            model_key=model_key_desc,
            instructions=instructions_desc,
            allowed_commands=allowed_commands_desc,
            allowed_skills=allowed_skills_desc,
            always_allowed_commands=always_allowed_desc,
            default_action=default_action_desc,
            free_text_policy=free_text_policy_desc,
            label=label_desc,
        )
        @discord.app_commands.choices(
            mode=[
                discord.app_commands.Choice(name="default", value="default"),
                discord.app_commands.Choice(name="specific", value="specific"),
            ]
        )
        @discord.app_commands.autocomplete(
            model_key=_acl_model_key_autocomplete,
            allowed_commands=_acl_allowed_commands_autocomplete,
            allowed_skills=_acl_allowed_skills_autocomplete,
            always_allowed_commands=_acl_always_allowed_autocomplete,
            default_action=_acl_default_action_autocomplete,
            free_text_policy=_acl_free_text_policy_autocomplete,
            label=_acl_label_autocomplete,
        )
        async def acl_channel(
            interaction,
            channel: str,
            mode: str,
            model_key: str = "",
            instructions: str = "",
            allowed_commands: str = "",
            allowed_skills: str = "",
            always_allowed_commands: str = "",
            default_action: str = "",
            free_text_policy: str = "",
            label: str = "",
        ):
            await self.handlers.handle_acl_channel_update(
                self.adapter,
                interaction,
                channel_value=channel,
                mode_value=mode,
                model_key=model_key,
                instructions=instructions,
                allowed_commands=allowed_commands,
                allowed_skills=allowed_skills,
                always_allowed_commands=always_allowed_commands,
                default_action=default_action,
                free_text_policy=free_text_policy,
                label=label,
                settings=cfg,
            )

        try:
            tree.add_command(acl_group)
        except Exception:
            logger.debug("Failed to add /acl command group", exc_info=True)

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

        cmd_cfg_raw = self._bridge_commands.get(target_name) or self._bridge_commands.get(name) or {}
        cmd_cfg = dict(cmd_cfg_raw) if isinstance(cmd_cfg_raw, dict) else {}
        if target_name == "model":
            native = self.registry.get("native_overrides") or {}
            native_model_cfg = native.get("model") if isinstance(native, dict) else {}
            if isinstance(native_model_cfg, dict):
                merged_cfg = dict(native_model_cfg)
                merged_cfg.update(cmd_cfg)
                cmd_cfg = merged_cfg

        acl_command = str(cmd_cfg.get("acl_command") or target_name)
        role_allowed, role_msg, role_ctx = await self.handlers.check_role_acl(interaction, acl_command)
        if not role_allowed:
            self._mark_handled(interaction)
            msg = role_msg or f"🚫 ACL: `/{acl_command}` não permitido."
            await self.handlers.send_ephemeral(interaction, msg)
            return True

        if str((role_ctx or {}).get("decision") or "") != "admin_bypass":
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

    def _resolve_acl_command_name(self, command_name: str) -> str:
        name = str(command_name or "").strip().lower().lstrip("/")
        if not name:
            return ""

        target_name = str(self._bridge_aliases.get(name, name) or "").strip().lower().lstrip("/")
        if not target_name:
            target_name = name

        cmd_cfg_raw = self._bridge_commands.get(target_name) or self._bridge_commands.get(name) or {}
        cmd_cfg = dict(cmd_cfg_raw) if isinstance(cmd_cfg_raw, dict) else {}

        if target_name == "model":
            native = self.registry.get("native_overrides") or {}
            native_model_cfg = native.get("model") if isinstance(native, dict) else {}
            if isinstance(native_model_cfg, dict):
                merged_cfg = dict(native_model_cfg)
                merged_cfg.update(cmd_cfg)
                cmd_cfg = merged_cfg

        acl_command = str(cmd_cfg.get("acl_command") or target_name).strip().lower().lstrip("/")
        return acl_command or target_name

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
