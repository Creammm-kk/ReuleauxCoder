"""Complete UTF-8 JSON messages over a memory channel or newline-framed streams."""

from __future__ import annotations

import queue
import threading
from typing import BinaryIO, Protocol


class MessageTransport(Protocol):
    def send(self, message: str) -> None: ...
    def receive(self) -> str | None: ...
    def close(self) -> None: ...


class MemoryTransport:
    def __init__(self, incoming, outgoing, closed, lock):
        self._incoming = incoming
        self._outgoing = outgoing
        self._closed = closed
        self._lock = lock

    @classmethod
    def pair(cls) -> tuple[MemoryTransport, MemoryTransport]:
        left, right = queue.Queue(), queue.Queue()
        closed = threading.Event()
        lock = threading.Lock()
        return cls(left, right, closed, lock), cls(right, left, closed, lock)

    def send(self, message: str) -> None:
        with self._lock:
            if self._closed.is_set():
                raise ConnectionError("RPC transport closed")
            self._outgoing.put(message)

    def receive(self) -> str | None:
        return self._incoming.get()

    def close(self) -> None:
        with self._lock:
            if not self._closed.is_set():
                self._closed.set()
                self._incoming.put(None)
                self._outgoing.put(None)


class StreamTransport:
    """One compact JSON document per line; stdout belongs exclusively to RPC."""

    MAX_MESSAGE_BYTES = 16 * 1024 * 1024

    def __init__(self, reader: BinaryIO, writer: BinaryIO):
        self.reader = reader
        self.writer = writer

    def send(self, message: str) -> None:
        data = message.encode("utf-8")
        if b"\n" in data or len(data) > self.MAX_MESSAGE_BYTES:
            raise ValueError("Invalid RPC frame size or embedded newline")
        self.writer.write(data + b"\n")
        self.writer.flush()

    def receive(self) -> str | None:
        data = self.reader.readline(self.MAX_MESSAGE_BYTES + 2)
        if not data:
            return None
        if len(data) > self.MAX_MESSAGE_BYTES + 1 or not data.endswith(b"\n"):
            raise ValueError("Truncated or oversized RPC frame")
        return data.decode("utf-8").rstrip("\r\n")

    def close(self) -> None:
        self.writer.close()
