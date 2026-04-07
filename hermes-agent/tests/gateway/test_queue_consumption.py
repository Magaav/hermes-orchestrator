"""Tests for /queue message consumption after normal agent completion.

Verifies that messages queued via /queue are kept in FIFO order without
triggering interrupts, then consumed after the active task completes.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    PlatformConfig,
    Platform,
)


# ---------------------------------------------------------------------------
# Minimal adapter for testing pending message storage
# ---------------------------------------------------------------------------

class _StubAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="test"), Platform.TELEGRAM)

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self._mark_disconnected()

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        from gateway.platforms.base import SendResult
        return SendResult(success=True, message_id="msg-1")

    async def get_chat_info(self, chat_id):
        return {"id": chat_id, "type": "dm"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQueueMessageStorage:
    """Verify /queue stores messages correctly in the adapter FIFO queue."""

    def test_queue_stores_message_in_pending(self):
        adapter = _StubAdapter()
        session_key = "telegram:user:123"
        event = MessageEvent(
            text="do this next",
            message_type=MessageType.TEXT,
            source=MagicMock(chat_id="123", platform=Platform.TELEGRAM),
            message_id="q1",
        )
        adapter.enqueue_pending_message(
            session_key=session_key,
            event=event,
            interrupt=False,
            merge_photo=False,
        )

        assert adapter.get_pending_message(session_key).text == "do this next"
        assert adapter.get_pending_message(session_key) is None

    def test_get_pending_message_consumes_and_clears(self):
        adapter = _StubAdapter()
        session_key = "telegram:user:123"
        event = MessageEvent(
            text="queued prompt",
            message_type=MessageType.TEXT,
            source=MagicMock(chat_id="123", platform=Platform.TELEGRAM),
            message_id="q2",
        )
        adapter.enqueue_pending_message(
            session_key=session_key,
            event=event,
            interrupt=False,
            merge_photo=False,
        )

        retrieved = adapter.get_pending_message(session_key)
        assert retrieved is not None
        assert retrieved.text == "queued prompt"
        # Should be consumed (cleared)
        assert adapter.get_pending_message(session_key) is None

    def test_queue_does_not_set_interrupt_event(self):
        """The whole point of /queue — no interrupt signal."""
        adapter = _StubAdapter()
        session_key = "telegram:user:123"

        # Simulate an active session (agent running)
        adapter._active_sessions[session_key] = asyncio.Event()

        # Store a queued message (what /queue does)
        event = MessageEvent(
            text="queued",
            message_type=MessageType.TEXT,
            source=MagicMock(),
            message_id="q3",
        )
        adapter.enqueue_pending_message(
            session_key=session_key,
            event=event,
            interrupt=False,
            merge_photo=False,
        )

        # The interrupt event should NOT be set
        assert not adapter._active_sessions[session_key].is_set()
        assert not adapter.has_pending_interrupt(session_key)

    def test_regular_message_sets_interrupt_event(self):
        """Regular messages with interrupt=True set the interrupt flag on the event."""
        adapter = _StubAdapter()
        session_key = "telegram:user:123"

        # Simulate regular message arrival (what handle_message does)
        event = MessageEvent(
            text="new message",
            message_type=MessageType.TEXT,
            source=MagicMock(),
            message_id="m1",
        )
        assert not event.interrupt  # Initially False

        adapter.enqueue_pending_message(
            session_key=session_key,
            event=event,
            interrupt=True,
            merge_photo=False,
        )

        # The event in the queue should have interrupt=True
        pending = adapter.get_pending_message(session_key)
        assert pending is not None
        assert pending.interrupt is True


class TestQueueConsumptionAfterCompletion:
    """Verify that pending messages are consumed after normal completion."""

    def test_pending_message_available_after_normal_completion(self):
        """After agent finishes without interrupt, pending message should
        still be retrievable from adapter._pending_messages."""
        adapter = _StubAdapter()
        session_key = "telegram:user:123"

        # Simulate: agent starts, /queue stores a message, agent finishes
        adapter._active_sessions[session_key] = asyncio.Event()
        event = MessageEvent(
            text="process this after",
            message_type=MessageType.TEXT,
            source=MagicMock(),
            message_id="q4",
        )
        adapter.enqueue_pending_message(
            session_key=session_key,
            event=event,
            interrupt=False,
            merge_photo=False,
        )

        # Agent finishes (no interrupt)
        del adapter._active_sessions[session_key]

        # The queued message should still be retrievable
        retrieved = adapter.get_pending_message(session_key)
        assert retrieved is not None
        assert retrieved.text == "process this after"

    def test_multiple_queues_are_consumed_fifo(self):
        """If user /queue's multiple times, all prompts are preserved in order."""
        adapter = _StubAdapter()
        session_key = "telegram:user:123"

        for text in ["first", "second", "third"]:
            event = MessageEvent(
                text=text,
                message_type=MessageType.TEXT,
                source=MagicMock(),
                message_id=f"q-{text}",
            )
            adapter.enqueue_pending_message(
                session_key=session_key,
                event=event,
                interrupt=False,
                merge_photo=False,
            )

        assert adapter.get_pending_message(session_key).text == "first"
        assert adapter.get_pending_message(session_key).text == "second"
        assert adapter.get_pending_message(session_key).text == "third"
        assert adapter.get_pending_message(session_key) is None
