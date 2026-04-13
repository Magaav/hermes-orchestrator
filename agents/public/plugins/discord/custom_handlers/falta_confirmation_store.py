"""Módulo de estado para confirmações pendentes de items suspeitos."""

from dataclasses import dataclass
from typing import Any
import time

@dataclass
class PendingConfirmation:
    channel_id: str
    user_id: str
    original_text: str          # texto STT original
    store: str                 # loja1 ou loja2
    guesses: list[str]         # sugestões do suspicious detector
    timestamp: float           # time.time() para TTL

# key: (channel_id, user_id, store)
_PENDING: dict[tuple[str, str, str], PendingConfirmation] = {}

TTL_S = 120.0  # 2 minutos para responder

def add_pending(channel_id: str, user_id: str, store: str,
                original_text: str, guesses: list[str]) -> None:
    key = (channel_id, user_id, store)
    _PENDING[key] = PendingConfirmation(
        channel_id=channel_id,
        user_id=user_id,
        store=store,
        original_text=original_text,
        guesses=guesses,
        timestamp=time.time(),
    )

def get_and_clear(channel_id: str, user_id: str, store: str) -> PendingConfirmation | None:
    key = (channel_id, user_id, store)
    conf = _PENDING.pop(key, None)
    if conf and (time.time() - conf.timestamp) > TTL_S:
        return None
    return conf

def cleanup_expired() -> None:
    now = time.time()
    expired = [
        k for k, v in _PENDING.items()
        if (now - v.timestamp) > TTL_S
    ]
    for k in expired:
        del _PENDING[k]
