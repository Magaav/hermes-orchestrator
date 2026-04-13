from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import discord
from discord import ui

logger = logging.getLogger(__name__)

# Importa o store de confirmações pendentes
sys.path.insert(0, str(Path(__file__).parent))
try:
    from falta_confirmation_store import add_pending, get_and_clear
except ImportError:
    # Fallback se arquivo não existir ainda (pode ser criado depois)
    def add_pending(*args, **kwargs): pass
    def get_and_clear(*args, **kwargs): return None


class SuspiciousItemConfirmationView(ui.View):
    """View com botões para confirmar item suspeito.

    Estrutura de cada botão:
    - 3 botões de sugestões (guesses) → executa add direto
    - 1 botão "Vou digitar" → não faz nada, só marca que user quer digitar
    """

    def __init__(
        self,
        channel_id: str,
        user_id: str,
        store: str,
        original_text: str,
        guesses: list[str],
        *,
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.channel_id = channel_id
        self.user_id = user_id
        self.store = store
        self.original_text = original_text

        # Armazena confirmação para quando botão for clicado
        add_pending(channel_id, user_id, store, original_text, guesses)

        # Botões de sugestões (máximo 3)
        for i, guess in enumerate(guesses[:3]):
            label = guess[:80]  # Discord label limit
            style = discord.ButtonStyle.secondary
            btn = ui.Button(
                style=style,
                label=f"✅ {label}",
                custom_id=f"conf_guess_{i}",
                row=0,
            )
            btn.callback = self._make_callback(guess)
            self.add_item(btn)

        # Botão "Vou digitar outro"
        custom_btn = ui.Button(
            style=discord.ButtonStyle.primary,
            label="✏️ Vou digitar outro",
            custom_id="conf_type_custom",
            row=1,
        )
        custom_btn.callback = self._callback_custom
        self.add_item(custom_btn)

    async def _make_callback(self, chosen_item: str):
        async def callback(interaction: discord.Interaction):
            # Confirmação via botão: re-executa pipeline com item escolhido
            await interaction.response.defer(ephemeral=True)

            python_bin = self._resolve_python_bin()
            script_path = self._resolve_pipeline_script()

            cmd = [
                python_bin, str(script_path),
                "add",
                "--itens", chosen_item,
                "--loja", self.store,
                "--channel-id", self.channel_id,
                "--author-id", self.user_id,
                "--author-name", interaction.user.display_name,
                "--trigger-mode", "discord_button_confirm",
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                out_text = (stdout or b"").decode(errors="ignore").strip()
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Erro ao adicionar `{chosen_item}`: {exc}",
                    ephemeral=True,
                )
                return

            # Limpa pending e edita mensagem original com resultado
            get_and_clear(self.channel_id, self.user_id, self.store)
            msg = out_text if out_text else f"✅ `{chosen_item}` adicionado."
            try:
                await interaction.edit_original_response(
                    content=msg[:1900],
                    view=None,
                )
            except Exception:
                await interaction.followup.send(msg[:1900], ephemeral=True)

        return callback

    async def _callback_custom(self, interaction: discord.Interaction):
        """User quer digitar manualmente — só limpa pending."""
        await interaction.response.defer(ephemeral=True)
        get_and_clear(self.channel_id, self.user_id, self.store)
        await interaction.followup.send(
            "Digite o nome correto do item 👇",
            ephemeral=True,
        )

    @staticmethod
    def _resolve_python_bin() -> str:
        candidates = (
            "/local/hermes-agent/.venv/bin/python",
            "/local/hermes-agent/.venv/bin/python3",
            "/usr/bin/python3",
        )
        for c in candidates:
            if Path(c).exists():
                return c
        return "python3"

    @staticmethod
    def _resolve_pipeline_script() -> Path:
        hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
        candidates = [
            hermes_home / "skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
            "/local/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
        ]
        for p in candidates:
            if p.exists():
                return p
        return candidates[0]

    async def on_timeout(self) -> None:
        """View expirou — limpa pending."""
        get_and_clear(self.channel_id, self.user_id, self.store)
