"""Checkpoint unfinished output without inserting it into provider messages."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from reuleauxcoder.domain.history import HistoryEvent, HistoryLedger

if TYPE_CHECKING:
    from reuleauxcoder.domain.agent.events import AgentEvent


@dataclass
class _Stream:
    id: str
    kind: str
    turn_id: str | None
    tool_call_id: str | None
    tool_name: str | None
    parts: list[str] = field(default_factory=list)
    replace: bool = False


class OutputJournal:
    """Flush at most one second of pending output, or an earlier size boundary."""

    def __init__(
        self,
        ledger: HistoryLedger,
        *,
        agent_id: str,
        on_error: Callable[[Exception], None],
    ):
        self._ledger = ledger
        self._agent_id = agent_id
        self._on_error = on_error
        self._lock = threading.RLock()
        self._streams: dict[tuple, _Stream] = {}
        self._timer: threading.Timer | None = None
        self._pending_chars = 0

    def record(self, event: AgentEvent) -> None:
        from reuleauxcoder.domain.agent.events import AgentEventType

        if event.agent_id != self._agent_id:
            return
        kind = {
            AgentEventType.STREAM_TOKEN: "response",
            AgentEventType.STREAM_REASONING: "reasoning",
            AgentEventType.TOOL_OUTPUT_DELTA: "tool",
            AgentEventType.TOOL_CALL_END: "tool",
        }.get(event.event_type)
        with self._lock:
            if event.event_type in (AgentEventType.CHAT_START, AgentEventType.CHAT_END):
                self._flush_locked()
                self._streams.clear()
            elif event.event_type is AgentEventType.ASSISTANT_STREAM_INTERRUPTED:
                self._flush_locked()
                self._streams = {
                    key: stream
                    for key, stream in self._streams.items()
                    if stream.kind == "tool"
                }
            if kind is None:
                return
            final = event.event_type is AgentEventType.TOOL_CALL_END
            text = (
                (event.tool_result or "")
                if final
                else event.data.get("text" if kind == "tool" else "token", "")
            )
            if not text and not final:
                return
            key = (kind, event.correlation_id)
            stream = self._streams.get(key)
            if stream is None:
                stream = _Stream(
                    uuid.uuid4().hex,
                    kind,
                    event.turn_id,
                    event.correlation_id,
                    event.tool_name,
                )
                self._streams[key] = stream
            if final:
                self._pending_chars -= sum(map(len, stream.parts))
                stream.parts.clear()
                stream.replace = True
            stream.parts.append(text)
            self._pending_chars += len(text)
            if final or self._pending_chars >= 65536:
                self._flush_locked()
            elif self._timer is None:
                timer = threading.Timer(1.0, lambda: self._flush_scheduled(timer))
                timer.daemon = True
                self._timer = timer
                timer.start()

    def _flush_scheduled(self, timer: threading.Timer) -> None:
        try:
            with self._lock:
                if self._timer is timer:
                    self._flush_locked()
        except Exception as error:
            self._on_error(error)

    def _flush_locked(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        for stream in self._streams.values():
            if not stream.parts:
                continue
            text = "".join(stream.parts)
            self._ledger.append(
                "output_checkpoint",
                {
                    "stream_id": stream.id,
                    "kind": stream.kind,
                    "text": text,
                    "tool_call_id": stream.tool_call_id,
                    "tool_name": stream.tool_name,
                    "replace": stream.replace,
                },
                agent_id=self._agent_id,
                turn_id=stream.turn_id,
            )
            self._pending_chars -= len(text)
            stream.parts.clear()
            stream.replace = False

    @contextmanager
    def commit(self, message: dict) -> Iterator[dict]:
        """The committed message itself acknowledges its streams, atomically."""
        with self._lock:
            keys = [
                key
                for key, stream in self._streams.items()
                if (
                    message.get("role") == "assistant"
                    and stream.kind != "tool"
                    or message.get("role") == "tool"
                    and stream.kind == "tool"
                    and stream.tool_call_id == message.get("tool_call_id")
                )
            ]
            self._flush_locked()
            yield (
                {"output_stream_ids": [self._streams[key].id for key in keys]}
                if keys
                else {}
            )
            for key in keys:
                del self._streams[key]

    def close(self) -> None:
        with self._lock:
            self._flush_locked()
            self._streams.clear()


def interrupted_output(events: list[HistoryEvent]) -> list[tuple[int, str]]:
    """Project only streams not acknowledged by a complete provider message."""
    completed = {
        stream_id
        for event in events
        if event.kind == "message_committed"
        for stream_id in event.payload.get("output_stream_ids", ())
    }
    streams: dict[str, tuple[int, str, list[str]]] = {}
    for event in events:
        if event.kind != "output_checkpoint":
            continue
        data = event.payload
        stream_id = data["stream_id"]
        if stream_id in completed:
            continue
        label = data["kind"] + (
            f" / {data['tool_name']}" if data.get("tool_name") else ""
        )
        entry = streams.setdefault(stream_id, (event.seq, label, []))
        if data.get("replace"):
            entry[2].clear()
        entry[2].append(data["text"])
    return [
        (seq, f"[Recovered {label} — session interrupted]\n{''.join(parts)}")
        for seq, label, parts in streams.values()
    ]
