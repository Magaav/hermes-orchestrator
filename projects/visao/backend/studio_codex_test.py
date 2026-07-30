#!/usr/bin/env python3
"""Contract tests for the redacted Studio Codex bridge."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import studio_codex  # pylint: disable=wrong-import-position


class FakeConnection:
    account: dict[str, object] | None = None

    def __init__(self, _timeout_seconds: int):
        self.events = iter(
            [
                {
                    "method": "account/login/completed",
                    "params": {"loginId": "login-1", "success": True},
                }
            ]
        )

    def initialize(self) -> None:
        return None

    def request(self, _request_id: int, method: str, _params: dict[str, object]) -> dict[str, object]:
        if method == "account/read":
            return {"account": self.account, "secret": "must-not-leak"}
        return {
            "loginId": "login-1",
            "verificationUrl": "https://auth.openai.com/codex/device",
            "userCode": "ABCD-1234",
            "accessToken": "must-not-leak",
        }

    def event(self) -> dict[str, object]:
        return next(self.events)

    def close(self) -> None:
        return None


class StudioCodexContractTest(unittest.TestCase):
    def test_status_is_green_only_for_connected_account_and_redacts_identity(self) -> None:
        FakeConnection.account = {
            "type": "chatgpt",
            "planType": "plus",
            "email": "private@example.test",
            "accessToken": "must-not-leak",
        }
        output = io.StringIO()
        with (
            patch.object(studio_codex, "CodexConnection", FakeConnection),
            patch.object(studio_codex, "codex_credentials"),
            redirect_stdout(output),
        ):
            self.assertEqual(studio_codex.status(), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["account"], {"state": "connected", "authMode": "chatgpt", "planType": "plus"})
        self.assertEqual(payload["runtime"]["state"], "ready")
        self.assertEqual(payload["datacenter"]["state"], "ready")
        self.assertNotIn("private@example.test", output.getvalue())
        self.assertNotIn("must-not-leak", output.getvalue())

    def test_device_login_emits_only_user_ceremony_fields(self) -> None:
        output = io.StringIO()
        with patch.object(studio_codex, "CodexConnection", FakeConnection), redirect_stdout(output):
            self.assertEqual(studio_codex.login(), 0)

        frames = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(frames[0]["event"], "login-started")
        self.assertEqual(frames[0]["userCode"], "ABCD-1234")
        self.assertEqual(frames[1], {"event": "login-completed", "success": True})
        self.assertNotIn("must-not-leak", output.getvalue())


if __name__ == "__main__":
    unittest.main()
