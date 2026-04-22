"""Hermes-native discord-slash-commands plugin."""

from .compat import ensure_discord_slash_runtime


def register(ctx):
    del ctx
    ensure_discord_slash_runtime()
