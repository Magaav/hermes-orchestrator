#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from master_frontier import provider_transport


class ProviderTransportTests(unittest.TestCase):
    def test_default_allows_reasoning_synthesis(self) -> None:
        self.assertEqual(provider_transport.timeout_sec({}), 90.0)

    def test_override_is_bounded_and_invalid_values_fail_to_default(self) -> None:
        key = provider_transport.TIMEOUT_ENV
        self.assertEqual(provider_transport.timeout_sec({key: "5"}), 15.0)
        self.assertEqual(provider_transport.timeout_sec({key: "240"}), 180.0)
        self.assertEqual(provider_transport.timeout_sec({key: "invalid"}), 90.0)
        self.assertEqual(provider_transport.timeout_sec({key: "nan"}), 90.0)

    def test_server_owned_remaining_wall_budget_can_only_reduce_timeout(self) -> None:
        self.assertEqual(provider_transport.timeout_sec({}, requested=7), 7.0)
        self.assertEqual(provider_transport.timeout_sec({}, requested=900), 90.0)
        self.assertEqual(provider_transport.timeout_sec({}, requested=0.5), 0.5)
        self.assertEqual(provider_transport.timeout_sec({}, requested=0), 0.001)

    def test_stream_parser_enforces_one_absolute_deadline_across_chunks(self) -> None:
        class ContinuousLine:
            def read1(self, _size: int) -> bytes:
                return b'data: {"type":"delta"'

        clock = iter((10.1, 10.4, 11.1))
        with self.assertRaisesRegex(TimeoutError, "wall-clock deadline"):
            list(provider_transport.iter_sse_json(ContinuousLine(), deadline=11.0, monotonic=lambda: next(clock)))

    def test_stream_parser_preserves_sse_event_shape(self) -> None:
        response = BytesIO(b'event: update\ndata: {"value": 1}\n\ndata: [DONE]\n\n')
        self.assertEqual(
            list(provider_transport.iter_sse_json(response, deadline=20.0, monotonic=lambda: 10.0)),
            [{"value": 1, "event": "update"}],
        )

    def test_nonstream_body_enforces_deadline_while_bytes_keep_arriving(self) -> None:
        class ContinuousBody:
            def read1(self, _size: int) -> bytes:
                return b"x" * 32

        clock = iter((10.1, 10.5, 11.1))
        with self.assertRaisesRegex(TimeoutError, "wall-clock deadline"):
            provider_transport.read_bytes(
                ContinuousBody(), deadline=11.0, monotonic=lambda: next(clock),
            )

    def test_deadline_guard_interrupts_one_blocked_http_read(self) -> None:
        released = threading.Event()

        class Socket:
            def shutdown(self, _how: int) -> None:
                released.set()

        class Response:
            fp = type("Fp", (), {"raw": type("Raw", (), {"_sock": Socket()})()})()

            def close(self) -> None:
                released.set()

        with self.assertRaisesRegex(TimeoutError, "wall-clock deadline"):
            with provider_transport.deadline_guard(Response(), deadline=time.monotonic() + 0.02):
                self.assertTrue(released.wait(0.2))


if __name__ == "__main__":
    unittest.main()
