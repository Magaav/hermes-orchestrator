"""Hermes-native discord-governance plugin."""

from .compat import ensure_governance_runtime


def register(ctx):
    del ctx
    ensure_governance_runtime()
