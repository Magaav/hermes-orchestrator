#!/usr/bin/env python3
"""Reapply FIFO pending-queue + voice/audio queueing patches in gateway core.

Why:
- Preserve rapid follow-ups (no overwrite/drop while a turn is active)
- Keep audio/voice events queued sequentially, like text
- Avoid losing media metadata when processing pending events
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
_ENV_AGENT_ROOT = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()

def _candidate_agent_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    if _ENV_AGENT_ROOT:
        roots.append(Path(_ENV_AGENT_ROOT).expanduser())
    if HERMES_HOME.name == ".hermes":
        roots.append(HERMES_HOME.parent / "hermes-agent")
    roots.append(Path("/local/hermes-agent"))

    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return tuple(out)


BASE_PATH_CANDIDATES = tuple(root / "gateway" / "platforms" / "base.py" for root in _candidate_agent_roots())
RUN_PATH_CANDIDATES = tuple(root / "gateway" / "run.py" for root in _candidate_agent_roots())


def _find_path(candidates: tuple[Path, ...], label: str) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Could not find {label} in expected locations:\n"
        + "\n".join(f"- {p}" for p in candidates)
    )


def _replace_once(content: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in content:
        return content, False
    if old not in content:
        raise RuntimeError(f"anchor not found for {label}")
    return content.replace(old, new, 1), True


def _patch_base(content: str) -> tuple[str, bool]:
    changed = False

    content, did = _replace_once(
        content,
        "from typing import Dict, List, Optional, Any, Callable, Awaitable, Tuple\n",
        "from typing import Dict, List, Optional, Any, Callable, Awaitable, Tuple, Deque\n",
        "base typing import Deque",
    )
    changed |= did

    if "from collections import deque\n" not in content:
        anchor = "from typing import Dict, List, Optional, Any, Callable, Awaitable, Tuple, Deque\n"
        if anchor not in content:
            raise RuntimeError("anchor not found for base collections deque import")
        content = content.replace(anchor, anchor + "from collections import deque\n", 1)
        changed = True

    if "interrupt: bool = False" not in content:
        old = (
            "    # Timestamps\n"
            "    timestamp: datetime = field(default_factory=datetime.now)\n"
            "    \n"
            "    def is_command(self) -> bool:\n"
        )
        new = (
            "    # Timestamps\n"
            "    timestamp: datetime = field(default_factory=datetime.now)\n"
            "\n"
            "    # Interrupt flag - set when this message should interrupt an active session\n"
            "    interrupt: bool = False\n"
            "    \n"
            "    def is_command(self) -> bool:\n"
        )
        content, did = _replace_once(content, old, new, "base MessageEvent interrupt field")
        changed |= did

    content, did = _replace_once(
        content,
        "        self._pending_messages: Dict[str, MessageEvent] = {}\n",
        "        self._pending_messages: Dict[str, Deque[MessageEvent]] = {}\n",
        "base pending_messages annotation",
    )
    changed |= did

    if "Queuing voice/audio follow-up for session" not in content:
        old_variants = [
            (
                "            if event.message_type == MessageType.PHOTO:\n"
                "                logger.debug(\"[%s] Queuing photo follow-up for session %s without interrupt\", self.name, session_key)\n"
                "                existing = self._pending_messages.get(session_key)\n"
                "                if existing and existing.message_type == MessageType.PHOTO:\n"
                "                    existing.media_urls.extend(event.media_urls)\n"
                "                    existing.media_types.extend(event.media_types)\n"
                "                    if event.text:\n"
                "                        if not existing.text:\n"
                "                            existing.text = event.text\n"
                "                        elif event.text not in existing.text:\n"
                "                            existing.text = f\"{existing.text}\\n\\n{event.text}\".strip()\n"
                "                else:\n"
                "                    self._pending_messages[session_key] = event\n"
                "                return  # Don't interrupt now - will run after current task completes\n"
                "\n"
                "            # Default behavior for non-photo follow-ups: interrupt the running agent\n"
                "            logger.debug(\"[%s] New message while session %s is active — triggering interrupt\", self.name, session_key)\n"
                "            self._pending_messages[session_key] = event\n"
                "            # Signal the interrupt (the processing task checks this)\n"
                "            self._active_sessions[session_key].set()\n"
                "            return  # Don't process now - will be handled after current task finishes\n"
            ),
            (
                "            if event.message_type == MessageType.PHOTO:\n"
                "                logger.debug(\"[%s] Queuing photo follow-up for session %s without interrupt\", self.name, session_key)\n"
                "                existing = self._pending_messages.get(session_key)\n"
                "                if existing and existing.message_type == MessageType.PHOTO:\n"
                "                    existing.media_urls.extend(event.media_urls)\n"
                "                    existing.media_types.extend(event.media_types)\n"
                "                    if event.text:\n"
                "                        existing.text = self._merge_caption(existing.text, event.text)\n"
                "                else:\n"
                "                    self._pending_messages[session_key] = event\n"
                "                return  # Don't interrupt now - will run after current task completes\n"
                "\n"
                "            # Default behavior for non-photo follow-ups: interrupt the running agent\n"
                "            logger.debug(\"[%s] New message while session %s is active — triggering interrupt\", self.name, session_key)\n"
                "            self._pending_messages[session_key] = event\n"
                "            # Signal the interrupt (the processing task checks this)\n"
                "            self._active_sessions[session_key].set()\n"
                "            return  # Don't process now - will be handled after current task finishes\n"
            ),
            (
                "            if event.message_type == MessageType.PHOTO:\n"
                "                logger.debug(\"[%s] Queuing photo follow-up for session %s without interrupt\", self.name, session_key)\n"
                "                merge_pending_message_event(self._pending_messages, session_key, event)\n"
                "                return  # Don't interrupt now - will run after current task completes\n"
                "\n"
                "            # Default behavior for non-photo follow-ups: interrupt the running agent\n"
                "            logger.debug(\"[%s] New message while session %s is active — triggering interrupt\", self.name, session_key)\n"
                "            self._pending_messages[session_key] = event\n"
                "            # Signal the interrupt (the processing task checks this)\n"
                "            self._active_sessions[session_key].set()\n"
                "            return  # Don't process now - will be handled after current task finishes\n"
            ),
        ]
        new = (
            "            if event.message_type == MessageType.PHOTO:\n"
            "                logger.debug(\"[%s] Queuing photo follow-up for session %s without interrupt\", self.name, session_key)\n"
            "                self.enqueue_pending_message(\n"
            "                    session_key=session_key,\n"
            "                    event=event,\n"
            "                    interrupt=False,\n"
            "                    merge_photo=True,\n"
            "                )\n"
            "                return  # Don't interrupt now - will run after current task completes\n"
            "\n"
            "            # Voice/audio follow-ups should queue sequentially.\n"
            "            # This avoids dropping media while the current turn is still running.\n"
            "            if event.message_type in (MessageType.VOICE, MessageType.AUDIO):\n"
            "                logger.debug(\"[%s] Queuing voice/audio follow-up for session %s without interrupt\", self.name, session_key)\n"
            "                self.enqueue_pending_message(\n"
            "                    session_key=session_key,\n"
            "                    event=event,\n"
            "                    interrupt=False,\n"
            "                    merge_photo=False,\n"
            "                )\n"
            "                return  # Don't interrupt now - will run after current task completes\n"
            "\n"
            "            # Default behavior for non-photo follow-ups: interrupt the running agent\n"
            "            logger.debug(\"[%s] New message while session %s is active — triggering interrupt\", self.name, session_key)\n"
            "            self.enqueue_pending_message(\n"
            "                session_key=session_key,\n"
            "                event=event,\n"
            "                interrupt=True,\n"
            "                merge_photo=False,\n"
            "            )\n"
            "            # Signal the interrupt (the processing task checks this)\n"
            "            self._active_sessions[session_key].set()\n"
            "            return  # Don't process now - will be handled after current task finishes\n"
        )
        replaced = False
        for old in old_variants:
            if old in content:
                content = content.replace(old, new, 1)
                changed = True
                replaced = True
                break
        if not replaced:
            raise RuntimeError("anchor not found for base active-session queue behavior")

    if "pending_event = self.get_pending_message(session_key)" not in content:
        old = (
            "            # Check if there's a pending message that was queued during our processing\n"
            "            if session_key in self._pending_messages:\n"
            "                pending_event = self._pending_messages.pop(session_key)\n"
            "                logger.debug(\"[%s] Processing queued message from interrupt\", self.name)\n"
        )
        new = (
            "            # Check if there's a pending message that was queued during our processing\n"
            "            pending_event = self.get_pending_message(session_key)\n"
            "            if pending_event is not None:\n"
            "                logger.debug(\"[%s] Processing queued message from interrupt\", self.name)\n"
        )
        content, did = _replace_once(content, old, new, "base pending message retrieval")
        changed |= did

    if "def enqueue_pending_message(" not in content:
        old = (
            "    def has_pending_interrupt(self, session_key: str) -> bool:\n"
            "        \"\"\"Check if there's a pending interrupt for a session.\"\"\"\n"
            "        return session_key in self._active_sessions and self._active_sessions[session_key].is_set()\n"
            "    \n"
            "    def get_pending_message(self, session_key: str) -> Optional[MessageEvent]:\n"
            "        \"\"\"Get and clear any pending message for a session.\"\"\"\n"
            "        return self._pending_messages.pop(session_key, None)\n"
        )
        new = (
            "    def has_pending_interrupt(self, session_key: str) -> bool:\n"
            "        \"\"\"Check if there's a pending interrupt for a session.\"\"\"\n"
            "        return session_key in self._active_sessions and self._active_sessions[session_key].is_set()\n"
            "\n"
            "    def _ensure_pending_queue(self, session_key: str) -> Deque[MessageEvent]:\n"
            "        \"\"\"Get or create a FIFO queue for a session.\"\"\"\n"
            "        queue = self._pending_messages.get(session_key)\n"
            "        if queue is None:\n"
            "            queue = deque()\n"
            "            self._pending_messages[session_key] = queue\n"
            "            return queue\n"
            "\n"
            "        # Backward compatibility: legacy callers may have written a single\n"
            "        # MessageEvent directly into _pending_messages.\n"
            "        if isinstance(queue, deque):\n"
            "            return queue\n"
            "\n"
            "        legacy_event = queue\n"
            "        queue = deque()\n"
            "        if legacy_event is not None:\n"
            "            queue.append(legacy_event)\n"
            "        self._pending_messages[session_key] = queue\n"
            "        return queue\n"
            "\n"
            "    def enqueue_pending_message(\n"
            "        self,\n"
            "        session_key: str,\n"
            "        event: MessageEvent,\n"
            "        interrupt: bool = False,\n"
            "        merge_photo: bool = False,\n"
            "    ) -> None:\n"
            "        \"\"\"Add a message to the pending FIFO queue for a session.\"\"\"\n"
            "        queue = self._ensure_pending_queue(session_key)\n"
            "\n"
            "        # Merge photo bursts into the last queued photo event.\n"
            "        if merge_photo and event.message_type == MessageType.PHOTO and queue:\n"
            "            last = queue[-1]\n"
            "            if last.message_type == MessageType.PHOTO:\n"
            "                last.media_urls.extend(event.media_urls)\n"
            "                last.media_types.extend(event.media_types)\n"
            "                if event.text:\n"
            "                    if not last.text:\n"
            "                        last.text = event.text\n"
            "                    elif event.text not in last.text:\n"
            "                        last.text = f\"{last.text}\\n\\n{event.text}\".strip()\n"
            "                return\n"
            "\n"
            "        event.interrupt = bool(interrupt)\n"
            "        queue.append(event)\n"
            "\n"
            "    def prepend_pending_message(self, session_key: str, event: MessageEvent) -> None:\n"
            "        \"\"\"Put a message back at the front of the session queue.\"\"\"\n"
            "        queue = self._ensure_pending_queue(session_key)\n"
            "        queue.appendleft(event)\n"
            "\n"
            "    def get_pending_message(self, session_key: str) -> Optional[MessageEvent]:\n"
            "        \"\"\"Get the next pending message (FIFO) for a session.\"\"\"\n"
            "        queue = self._pending_messages.get(session_key)\n"
            "        if not queue:\n"
            "            return None\n"
            "\n"
            "        # Backward compatibility for legacy single-event storage.\n"
            "        if not isinstance(queue, deque):\n"
            "            self._pending_messages.pop(session_key, None)\n"
            "            return queue\n"
            "\n"
            "        event = queue.popleft()\n"
            "        if not queue:\n"
            "            self._pending_messages.pop(session_key, None)\n"
            "        return event\n"
            "\n"
            "    def pop_pending_interrupt_message(self, session_key: str) -> Optional[MessageEvent]:\n"
            "        \"\"\"Pop the oldest pending interrupt event for this session.\"\"\"\n"
            "        queue = self._pending_messages.get(session_key)\n"
            "        if not queue:\n"
            "            return None\n"
            "\n"
            "        # Backward compatibility for legacy single-event storage.\n"
            "        if not isinstance(queue, deque):\n"
            "            event = queue\n"
            "            if getattr(event, \"interrupt\", False):\n"
            "                self._pending_messages.pop(session_key, None)\n"
            "                return event\n"
            "            return None\n"
            "\n"
            "        for idx, event in enumerate(queue):\n"
            "            if getattr(event, \"interrupt\", False):\n"
            "                del queue[idx]\n"
            "                if not queue:\n"
            "                    self._pending_messages.pop(session_key, None)\n"
            "                return event\n"
            "        return None\n"
            "\n"
            "    def clear_pending_messages(self, session_key: str) -> int:\n"
            "        \"\"\"Clear all pending messages for a session and return count.\"\"\"\n"
            "        queue = self._pending_messages.pop(session_key, None)\n"
            "        if not queue:\n"
            "            return 0\n"
            "        if isinstance(queue, deque):\n"
            "            return len(queue)\n"
            "        return 1\n"
        )
        content, did = _replace_once(content, old, new, "base queue helper methods")
        changed |= did

    return content, changed


def _patch_run(content: str) -> tuple[str, bool]:
    changed = False

    # /stop pending-clear behavior
    old = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter and hasattr(adapter, 'get_pending_message'):\n"
        "                    adapter.get_pending_message(_quick_key)  # consume and discard\n"
    )
    new = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter and hasattr(adapter, 'clear_pending_messages'):\n"
        "                    adapter.clear_pending_messages(_quick_key)\n"
        "                elif adapter and hasattr(adapter, 'get_pending_message'):\n"
        "                    adapter.get_pending_message(_quick_key)  # legacy fallback: consume one\n"
    )
    content, did = _replace_once(content, old, new, "run stop clear_pending_messages")
    changed |= did

    # /new pending-clear behavior
    old = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter and hasattr(adapter, 'get_pending_message'):\n"
        "                    adapter.get_pending_message(_quick_key)  # consume and discard\n"
        "                self._pending_messages.pop(_quick_key, None)\n"
    )
    new = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter and hasattr(adapter, 'clear_pending_messages'):\n"
        "                    adapter.clear_pending_messages(_quick_key)\n"
        "                elif adapter and hasattr(adapter, 'get_pending_message'):\n"
        "                    adapter.get_pending_message(_quick_key)  # legacy fallback: consume one\n"
        "                self._pending_messages.pop(_quick_key, None)\n"
    )
    content, did = _replace_once(content, old, new, "run new clear_pending_messages")
    changed |= did

    # /queue branch uses adapter helper
    old = (
        "                    adapter._pending_messages[_quick_key] = queued_event\n"
        "                return \"Queued for the next turn.\"\n"
    )
    new = (
        "                    if hasattr(adapter, \"enqueue_pending_message\"):\n"
        "                        adapter.enqueue_pending_message(\n"
        "                            session_key=_quick_key,\n"
        "                            event=queued_event,\n"
        "                            interrupt=False,\n"
        "                            merge_photo=False,\n"
        "                        )\n"
        "                    else:\n"
        "                        adapter._pending_messages[_quick_key] = queued_event\n"
        "                return \"Queued for the next turn.\"\n"
    )
    content, did = _replace_once(content, old, new, "run queue helper")
    changed |= did

    if "PRIORITY voice/audio follow-up for session" not in content:
        old_variants = [
            (
                "            if event.message_type == MessageType.PHOTO:\n"
                "                logger.debug(\"PRIORITY photo follow-up for session %s — queueing without interrupt\", _quick_key[:20])\n"
                "                adapter = self.adapters.get(source.platform)\n"
                "                if adapter:\n"
                "                    # Reuse adapter queue semantics so photo bursts merge cleanly.\n"
                "                    if _quick_key in adapter._pending_messages:\n"
                "                        existing = adapter._pending_messages[_quick_key]\n"
                "                        if getattr(existing, \"message_type\", None) == MessageType.PHOTO:\n"
                "                            existing.media_urls.extend(event.media_urls)\n"
                "                            existing.media_types.extend(event.media_types)\n"
                "                            if event.text:\n"
                "                                if not existing.text:\n"
                "                                    existing.text = event.text\n"
                "                                elif event.text not in existing.text:\n"
                "                                    existing.text = f\"{existing.text}\\n\\n{event.text}\".strip()\n"
                "                        else:\n"
                "                            adapter._pending_messages[_quick_key] = event\n"
                "                    else:\n"
                "                        adapter._pending_messages[_quick_key] = event\n"
                "                return None\n"
                "\n"
                "            running_agent = self._running_agents.get(_quick_key)\n"
            ),
            (
                "            if event.message_type == MessageType.PHOTO:\n"
                "                logger.debug(\"PRIORITY photo follow-up for session %s — queueing without interrupt\", _quick_key[:20])\n"
                "                adapter = self.adapters.get(source.platform)\n"
                "                if adapter:\n"
                "                    # Reuse adapter queue semantics so photo bursts merge cleanly.\n"
                "                    if _quick_key in adapter._pending_messages:\n"
                "                        existing = adapter._pending_messages[_quick_key]\n"
                "                        if getattr(existing, \"message_type\", None) == MessageType.PHOTO:\n"
                "                            existing.media_urls.extend(event.media_urls)\n"
                "                            existing.media_types.extend(event.media_types)\n"
                "                            if event.text:\n"
                "                                existing.text = BasePlatformAdapter._merge_caption(existing.text, event.text)\n"
                "                        else:\n"
                "                            adapter._pending_messages[_quick_key] = event\n"
                "                    else:\n"
                "                        adapter._pending_messages[_quick_key] = event\n"
                "                return None\n"
                "\n"
                "            running_agent = self._running_agents.get(_quick_key)\n"
            ),
        ]
        new = (
            "            if event.message_type == MessageType.PHOTO:\n"
            "                logger.debug(\"PRIORITY photo follow-up for session %s — queueing without interrupt\", _quick_key[:20])\n"
            "                adapter = self.adapters.get(source.platform)\n"
            "                if adapter:\n"
            "                    if hasattr(adapter, \"enqueue_pending_message\"):\n"
            "                        adapter.enqueue_pending_message(\n"
            "                            session_key=_quick_key,\n"
            "                            event=event,\n"
            "                            interrupt=False,\n"
            "                            merge_photo=True,\n"
            "                        )\n"
            "                    else:\n"
            "                        adapter._pending_messages[_quick_key] = event\n"
            "                return None\n"
            "\n"
            "            if event.message_type in (MessageType.VOICE, MessageType.AUDIO):\n"
            "                logger.debug(\"PRIORITY voice/audio follow-up for session %s — queueing without interrupt\", _quick_key[:20])\n"
            "                adapter = self.adapters.get(source.platform)\n"
            "                if adapter:\n"
            "                    if hasattr(adapter, \"enqueue_pending_message\"):\n"
            "                        adapter.enqueue_pending_message(\n"
            "                            session_key=_quick_key,\n"
            "                            event=event,\n"
            "                            interrupt=False,\n"
            "                            merge_photo=False,\n"
            "                        )\n"
            "                    else:\n"
            "                        adapter._pending_messages[_quick_key] = event\n"
            "                return None\n"
            "\n"
            "            running_agent = self._running_agents.get(_quick_key)\n"
        )
        replaced = False
        for old in old_variants:
            if old in content:
                content = content.replace(old, new, 1)
                changed = True
                replaced = True
                break
        if not replaced:
            raise RuntimeError("anchor not found for run photo+voice priority queue")

    # Sentinel-setup queue uses helper
    old = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter:\n"
        "                    adapter._pending_messages[_quick_key] = event\n"
        "                return None\n"
    )
    new = (
        "                adapter = self.adapters.get(source.platform)\n"
        "                if adapter:\n"
        "                    if hasattr(adapter, \"enqueue_pending_message\"):\n"
        "                        adapter.enqueue_pending_message(\n"
        "                            session_key=_quick_key,\n"
        "                            event=event,\n"
        "                            interrupt=False,\n"
        "                            merge_photo=(event.message_type == MessageType.PHOTO),\n"
        "                        )\n"
        "                    else:\n"
        "                        adapter._pending_messages[_quick_key] = event\n"
        "                return None\n"
    )
    content, did = _replace_once(content, old, new, "run sentinel enqueue helper")
    changed |= did

    # monitor_for_interrupt: pop explicit interrupt event
    old = (
        "                        pending_event = adapter.get_pending_message(session_key)\n"
        "                        pending_text = pending_event.text if pending_event else None\n"
    )
    new = (
        "                        if hasattr(adapter, \"pop_pending_interrupt_message\"):\n"
        "                            pending_event = adapter.pop_pending_interrupt_message(session_key)\n"
        "                        else:\n"
        "                            pending_event = adapter.get_pending_message(session_key)\n"
        "                        pending_text = pending_event.text if pending_event else None\n"
    )
    content, did = _replace_once(content, old, new, "run monitor interrupt pop")
    changed |= did

    # interrupted branch: pop explicit interrupt event.
    # Support both legacy flow (direct pending_event retrieval) and newer flow
    # that uses _dequeue_pending_text(adapter, session_key).
    old = (
        "                    pending_event = adapter.get_pending_message(session_key)\n"
        "                    if pending_event:\n"
        "                        pending = pending_event.text\n"
    )
    new = (
        "                    if hasattr(adapter, \"pop_pending_interrupt_message\"):\n"
        "                        pending_event = adapter.pop_pending_interrupt_message(session_key)\n"
        "                    else:\n"
        "                        pending_event = adapter.get_pending_message(session_key)\n"
        "                    if pending_event:\n"
        "                        pending = pending_event.text\n"
    )
    if old in content:
        content, did = _replace_once(content, old, new, "run interrupted pop")
        changed |= did
    else:
        alt_old = (
            "                if result.get(\"interrupted\"):\n"
            "                    pending = _dequeue_pending_text(adapter, session_key)\n"
            "                    if not pending and result.get(\"interrupt_message\"):\n"
            "                        pending = result.get(\"interrupt_message\")\n"
        )
        alt_new = (
            "                if result.get(\"interrupted\"):\n"
            "                    if hasattr(adapter, \"pop_pending_interrupt_message\"):\n"
            "                        pending_event = adapter.pop_pending_interrupt_message(session_key)\n"
            "                    else:\n"
            "                        pending_event = adapter.get_pending_message(session_key)\n"
            "                    pending = None\n"
            "                    if pending_event:\n"
            "                        pending = pending_event.text\n"
            "                        if not pending and getattr(pending_event, \"media_urls\", None):\n"
            "                            pending = _build_media_placeholder(pending_event)\n"
            "                    if not pending and result.get(\"interrupt_message\"):\n"
            "                        pending = result.get(\"interrupt_message\")\n"
        )
        content, did = _replace_once(content, alt_old, alt_new, "run interrupted pop")
        changed |= did

    # normal-completion branch: keep media events queued with metadata
    if "_is_text_only =" not in content:
        old = (
            "                    pending_event = adapter.get_pending_message(session_key)\n"
            "                    if pending_event:\n"
            "                        pending = pending_event.text\n"
            "                        logger.debug(\"Processing queued message after agent completion: '%s...'\", pending[:40])\n"
        )
        new = (
            "                    pending_event = adapter.get_pending_message(session_key)\n"
            "                    if pending_event:\n"
            "                        _is_text_only = (\n"
            "                            pending_event.message_type in (MessageType.TEXT, MessageType.COMMAND)\n"
            "                            and not pending_event.media_urls\n"
            "                        )\n"
            "                        if _is_text_only:\n"
            "                            pending = pending_event.text\n"
            "                            logger.debug(\n"
            "                                \"Processing queued text message after agent completion: '%s...'\",\n"
            "                                pending[:40],\n"
            "                            )\n"
            "                        else:\n"
            "                            # Preserve media events (audio/photo/docs) so they\n"
            "                            # re-enter the normal adapter pipeline with their\n"
            "                            # attachment metadata intact.\n"
            "                            if hasattr(adapter, \"prepend_pending_message\"):\n"
            "                                adapter.prepend_pending_message(session_key, pending_event)\n"
            "                            elif hasattr(adapter, \"enqueue_pending_message\"):\n"
            "                                adapter.enqueue_pending_message(\n"
            "                                    session_key=session_key,\n"
            "                                    event=pending_event,\n"
            "                                    interrupt=False,\n"
            "                                    merge_photo=False,\n"
            "                                )\n"
            "                            else:\n"
            "                                adapter._pending_messages[session_key] = pending_event\n"
        )
        if old in content:
            content, did = _replace_once(content, old, new, "run normal completion pending handling")
            changed |= did
        else:
            alt_old = (
                "                else:\n"
                "                    pending = _dequeue_pending_text(adapter, session_key)\n"
                "                    if pending:\n"
                "                        logger.debug(\"Processing queued message after agent completion: '%s...'\", pending[:40])\n"
            )
            alt_new = (
                "                else:\n"
                "                    pending_event = adapter.get_pending_message(session_key)\n"
                "                    if pending_event:\n"
                "                        _is_text_only = (\n"
                "                            pending_event.message_type in (MessageType.TEXT, MessageType.COMMAND)\n"
                "                            and not pending_event.media_urls\n"
                "                        )\n"
                "                        if _is_text_only:\n"
                "                            pending = pending_event.text\n"
                "                            logger.debug(\n"
                "                                \"Processing queued text message after agent completion: '%s...'\",\n"
                "                                pending[:40],\n"
                "                            )\n"
                "                        else:\n"
                "                            if hasattr(adapter, \"prepend_pending_message\"):\n"
                "                                adapter.prepend_pending_message(session_key, pending_event)\n"
                "                            elif hasattr(adapter, \"enqueue_pending_message\"):\n"
                "                                adapter.enqueue_pending_message(\n"
                "                                    session_key=session_key,\n"
                "                                    event=pending_event,\n"
                "                                    interrupt=False,\n"
                "                                    merge_photo=False,\n"
                "                                )\n"
                "                            else:\n"
                "                                adapter._pending_messages[session_key] = pending_event\n"
            )
            content, did = _replace_once(content, alt_old, alt_new, "run normal completion pending handling")
            changed |= did

    # recursion-depth fallback queueing
    if "queued_event = MessageEvent(" not in content:
        old = (
            "                    adapter = self.adapters.get(source.platform)\n"
            "                    if adapter and hasattr(adapter, 'queue_message'):\n"
            "                        adapter.queue_message(session_key, pending)\n"
            "                    return result_holder[0] or {\"final_response\": response, \"messages\": history}\n"
        )
        new = (
            "                    adapter = self.adapters.get(source.platform)\n"
            "                    if adapter and hasattr(adapter, 'queue_message'):\n"
            "                        adapter.queue_message(session_key, pending)\n"
            "                    elif adapter and hasattr(adapter, \"enqueue_pending_message\"):\n"
            "                        queued_event = MessageEvent(\n"
            "                            text=pending,\n"
            "                            message_type=MessageType.TEXT,\n"
            "                            source=source,\n"
            "                            message_id=event_message_id,\n"
            "                        )\n"
            "                        adapter.enqueue_pending_message(\n"
            "                            session_key=session_key,\n"
            "                            event=queued_event,\n"
            "                            interrupt=False,\n"
            "                            merge_photo=False,\n"
            "                        )\n"
            "                    return result_holder[0] or {\"final_response\": response, \"messages\": history}\n"
        )
        content, did = _replace_once(content, old, new, "run recursion fallback enqueue helper")
        changed |= did

    return content, changed


def _already_patched(base_content: str, run_content: str) -> bool:
    """Best-effort detection for anchor drift on already-patched trees."""
    base_ok = (
        "Deque[MessageEvent]" in base_content
        and "def enqueue_pending_message(" in base_content
    )
    run_ok = (
        "adapter.enqueue_pending_message(" in run_content
        and "pending_event = adapter.get_pending_message(session_key)" in run_content
    )
    return base_ok and run_ok


def reapply() -> int:
    try:
        base_path = _find_path(BASE_PATH_CANDIDATES, "gateway/platforms/base.py")
        run_path = _find_path(RUN_PATH_CANDIDATES, "gateway/run.py")
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    base_original = base_path.read_text(encoding="utf-8")
    run_original = run_path.read_text(encoding="utf-8")

    try:
        base_new, base_changed = _patch_base(base_original)
    except Exception as exc:
        if _already_patched(base_original, run_original):
            print("✅ Gateway FIFO queue patch already present (anchor drift tolerated).")
            return 0
        print(f"❌ Failed to patch FIFO queue behavior (base.py): {exc}", file=sys.stderr)
        return 1

    run_new = run_original
    run_changed = False
    try:
        run_new, run_changed = _patch_run(run_original)
    except Exception as exc:
        # Newer hermes-agent builds moved run.py interrupt/queue flow and no longer
        # expose the legacy anchors this patch relied on. Keep startup resilient.
        if "anchor not found" in str(exc):
            print(f"⚠️  Skipping run.py FIFO patch due anchor drift: {exc}")
        else:
            print(f"❌ Failed to patch FIFO queue behavior (run.py): {exc}", file=sys.stderr)
            return 1

    if not base_changed and not run_changed:
        print("✅ Gateway FIFO queue patch already applied.")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if base_changed:
        base_backup = backup_dir / f"base.py.fifo_queue_patch.{stamp}.bak"
        base_backup.write_text(base_original, encoding="utf-8")
        base_path.write_text(base_new, encoding="utf-8")
        print(f"✅ Applied FIFO queue patch to: {base_path}")
        print(f"   Backup: {base_backup}")

    if run_changed:
        run_backup = backup_dir / f"run.py.fifo_queue_patch.{stamp}.bak"
        run_backup.write_text(run_original, encoding="utf-8")
        run_path.write_text(run_new, encoding="utf-8")
        print(f"✅ Applied FIFO queue patch to: {run_path}")
        print(f"   Backup: {run_backup}")

    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
