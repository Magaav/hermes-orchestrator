from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


_HANDLERS_CANDIDATES = (
    Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py"),
)
_HANDLERS_PATH = next((p for p in _HANDLERS_CANDIDATES if p.exists()), _HANDLERS_CANDIDATES[0])

_SPEC = importlib.util.spec_from_file_location("discord_slash_handlers_test_module", _HANDLERS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load handlers module from {_HANDLERS_PATH}")
_HANDLERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HANDLERS)


_MODEL_CFG = {
    "choices": [
        {
            "key": "gpt54",
            "label": "GPT-5.4 (OpenAI Codex)",
            "provider": "openai-codex",
            "model": "gpt-5.4",
        },
        {
            "key": "gpt53codex",
            "label": "GPT-5.3 Codex(OpenIA Codex)",
            "provider": "openai-codex",
            "model": "gpt-5.3-codex",
        },
    ]
}


class ModelChoiceResolutionTests(unittest.TestCase):
    def test_find_model_choice_accepts_user_label_variant(self) -> None:
        choices = _HANDLERS._normalize_model_choices(_MODEL_CFG)
        selected = _HANDLERS._find_model_choice("GPT5.3 Codex(OpenAI Codex)", choices)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["key"], "gpt53codex")
        self.assertEqual(selected["model"], "gpt-5.3-codex")

    def test_find_model_choice_accepts_provider_model_input(self) -> None:
        choices = _HANDLERS._normalize_model_choices(_MODEL_CFG)
        selected = _HANDLERS._find_model_choice("openai-codex:gpt-5.4", choices)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["key"], "gpt54")

    def test_extract_bridge_model_key_prefers_known_fields(self) -> None:
        self.assertEqual(
            _HANDLERS._extract_bridge_model_key({"modelo": "gpt53codex"}),
            "gpt53codex",
        )
        self.assertEqual(
            _HANDLERS._extract_bridge_model_key({"name": "gpt54"}),
            "gpt54",
        )
        self.assertEqual(
            _HANDLERS._extract_bridge_model_key({"only_field": "gpt54"}),
            "gpt54",
        )


class ModelBridgeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_switch_handler_routes_to_handle_model_switch(self) -> None:
        mocked = AsyncMock(return_value=True)
        with patch.object(_HANDLERS, "handle_model_switch", mocked):
            result = await _HANDLERS.run_bridge_handler(
                "model_switch",
                adapter=object(),
                interaction=object(),
                command_name="model",
                option_values={"modelo": "gpt53codex"},
                command_config=_MODEL_CFG,
            )

        self.assertTrue(result)
        mocked.assert_awaited_once()
        await_args = mocked.await_args
        self.assertEqual(await_args.kwargs.get("model_key"), "gpt53codex")
        self.assertEqual(await_args.kwargs.get("settings"), _MODEL_CFG)


if __name__ == "__main__":
    unittest.main()
