from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue
from threading import Lock
from typing import Any


@dataclass
class StreamEvent:
    event: str
    data: dict[str, Any]


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[Queue[StreamEvent]] = set()
        self._lock = Lock()

    def subscribe(self) -> Queue[StreamEvent]:
        queue: Queue[StreamEvent] = Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: Queue[StreamEvent]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload.setdefault("emitted_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        message = StreamEvent(event=event, data=payload)
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except Exception:
                # Drop backpressure-heavy queues.
                self.unsubscribe(subscriber)
