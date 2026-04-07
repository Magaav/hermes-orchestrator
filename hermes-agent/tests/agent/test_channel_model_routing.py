from types import SimpleNamespace

from agent.channel_model_routing import resolve_channel_turn_route


def _source(chat_id: str, thread_id: str | None = None, platform: str = "discord"):
    return SimpleNamespace(
        platform=SimpleNamespace(value=platform),
        chat_id=chat_id,
        thread_id=thread_id,
    )


def test_no_route_when_disabled():
    out = resolve_channel_turn_route(
        "qual o horário?",
        {"enabled": False, "rules": []},
        _source("123"),
        {"model": "gpt-5.3-codex"},
    )
    assert out is None


def test_blocks_complex_message_in_operational_channel():
    cfg = {
        "enabled": True,
        "rules": [
            {
                "platform": "discord",
                "chat_ids": ["1487099467726328038"],
                "provider": "openrouter",
                "model": "liquid/lfm-2.5-1.2b-instruct:free",
                "block_complex": True,
                "complex_block_message": "canal operacional",
            }
        ],
    }
    out = resolve_channel_turn_route(
        "implementar uma rota nova no sistema",
        cfg,
        _source("1487099467726328038"),
        {"model": "gpt-5.3-codex"},
    )
    assert out is not None
    assert out.get("blocked") is True
    assert "operacional" in out.get("block_message", "")


def test_returns_none_when_rule_matches_but_runtime_unavailable(monkeypatch):
    cfg = {
        "enabled": True,
        "rules": [
            {
                "platform": "discord",
                "chat_ids": ["1487099467726328038"],
                "provider": "nvidia",
                "model": "meta/llama-3.1-8b-instruct",
            }
        ],
    }

    monkeypatch.setattr(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    out = resolve_channel_turn_route(
        "listar faltas loja 1",
        cfg,
        _source("1487099467726328038"),
        {"model": "gpt-5.3-codex"},
    )
    assert out is None
