from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
import time

from .broker import EventBroker
from .clone_manager import CloneManagerClient, CloneManagerError, discover_nodes
from .logs import allowed_channels, channel_log_path, normalize_log_line
from .settings import GatewaySettings


class FleetMonitor(Thread):
    def __init__(
        self,
        *,
        settings: GatewaySettings,
        client: CloneManagerClient,
        broker: EventBroker,
    ) -> None:
        super().__init__(name="fleet-monitor", daemon=True)
        self.settings = settings
        self.client = client
        self.broker = broker
        self._stop_event = Event()
        self._status_snapshot: dict[str, tuple[bool, str]] = {}
        self._file_offsets: dict[tuple[str, str], int] = {}

    def shutdown(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.broker.publish(
            "monitor",
            {
                "state": "started",
                "poll_interval_sec": self.settings.poll_interval_sec,
            },
        )
        while not self._stop_event.is_set():
            try:
                nodes = discover_nodes(self.settings)
                self._poll_status(nodes)
                self._poll_logs(nodes)
            except Exception as exc:
                self.broker.publish(
                    "monitor",
                    {
                        "state": "error",
                        "message": str(exc),
                    },
                )
            self._stop_event.wait(self.settings.poll_interval_sec)

        self.broker.publish("monitor", {"state": "stopped"})

    def _poll_status(self, nodes: list[str]) -> None:
        for node in nodes:
            try:
                payload = self.client.status(node)
            except CloneManagerError:
                continue
            container_state = payload.get("container_state") or {}
            running = bool(container_state.get("running"))
            status = str(container_state.get("status") or "unknown")
            prev = self._status_snapshot.get(node)
            current = (running, status)
            self._status_snapshot[node] = current
            if prev is None or prev != current:
                self.broker.publish(
                    "status",
                    {
                        "node": node,
                        "running": running,
                        "status": status,
                        "runtime_type": str(payload.get("runtime_type") or ""),
                        "state_mode": str(payload.get("state_mode") or ""),
                    },
                )

    def _poll_logs(self, nodes: list[str]) -> None:
        for node in nodes:
            for channel in sorted(ch for ch in allowed_channels() if ch != "all"):
                path = channel_log_path(node, channel, self.settings)
                self._emit_new_log_lines(node, channel, path)

    def _emit_new_log_lines(self, node: str, channel: str, path: Path) -> None:
        key = (node, channel)
        if not path.exists() or not path.is_file():
            self._file_offsets.pop(key, None)
            return

        try:
            size = path.stat().st_size
        except OSError:
            return

        offset = self._file_offsets.get(key, 0)
        if size < offset:
            offset = 0

        if size == offset:
            return

        lines: list[str] = []
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(offset)
            for raw in handle:
                lines.append(raw.rstrip("\n"))
            offset = handle.tell()

        self._file_offsets[key] = offset
        if not lines:
            return

        # Bound burst size to avoid flooding clients when a large file rotates.
        if len(lines) > 350:
            lines = lines[-350:]
            self.broker.publish(
                "log",
                {
                    "node": node,
                    "channel": channel,
                    "severity": "warning",
                    "message": "log burst truncated to latest 350 lines",
                },
            )

        for line in lines:
            event = normalize_log_line(node, channel, line)
            self.broker.publish("log", event.to_dict())
