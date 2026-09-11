"""Incremental, disposable history index. events.jsonl remains authoritative."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import sqlite3

from reuleauxcoder.domain.history_query import ArtifactPage, HistoryPage, HistoryRecord
from reuleauxcoder.domain.llm.context_messages import is_synthetic_context_message
from reuleauxcoder.infrastructure.persistence.session_paths import (
    is_safe_session_id,
    session_storage_path,
)
from reuleauxcoder.infrastructure.workspace import LocalWorkspacePort


PAGE_CHARS = 12_000
PAGE_ENCODED_CHARS = 24_000
CHUNK_CHARS = 4096
INDEX_BYTES = 8 * 1024 * 1024
SEARCH_CHUNKS = 256


class SessionHistory:
    """Read messages, events and artifacts using stable ledger identities.

    The initial index is built in bounded batches. Subsequent requests consume
    only appended records; payloads are chunked so reading a large message does
    not materialize its entire body. Indexing needs at most one JSONL record in
    memory, including when an older writer stored an unusually large event.
    """

    def __init__(self, sessions_dir: str | Path):
        self.workspace = LocalWorkspacePort(sessions_dir)

    def directory(self, session_id: str) -> Path:
        if not is_safe_session_id(session_id):
            raise ValueError("invalid session_id")
        directory = self.workspace.resolve(
            session_storage_path(self.workspace.root, session_id)
        )
        if not directory.is_dir():
            raise FileNotFoundError(f"Session not found: {session_id}")
        return directory

    def _connect(self, session_id: str):
        directory = self.directory(session_id)
        source = self.workspace.resolve(directory / "events.jsonl")
        database = self.workspace.resolve(directory / ".history.sqlite3")
        connection = sqlite3.connect(database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection, source

    def artifact(
        self,
        session_id: str,
        artifact_ref: str,
        *,
        offset: int = 0,
        limit: int = PAGE_CHARS,
        cursor: str | None = None,
    ) -> ArtifactPage:
        _limits(1, limit)
        if offset < 0 or Path(artifact_ref).is_absolute():
            raise ValueError("artifact_ref must be relative and offset non-negative")
        root = self.workspace.resolve(self.directory(session_id) / "artifacts")
        path = LocalWorkspacePort(root).resolve(root / artifact_ref)
        with path.open(encoding="utf-8", newline="") as stream:
            stat = os.fstat(stream.fileno())
            if cursor:
                position, offset, size, mtime = map(int, cursor.split(":"))
                if (size, mtime) != (stat.st_size, stat.st_mtime_ns):
                    raise ValueError(
                        "Artifact changed; restart the read without a cursor"
                    )
                if position < 0 or offset < 0:
                    raise ValueError("invalid artifact cursor")
                stream.seek(position)
            else:
                # Compatibility with character offsets; cursors seek directly.
                remaining = offset
                while remaining:
                    text = stream.read(min(CHUNK_CHARS, remaining))
                    if not text:
                        raise ValueError("offset exceeds artifact length")
                    remaining -= len(text)
            content = stream.read(limit)
            position = stream.tell()
            more = bool(stream.read(1))
            end = offset + len(content)
            return ArtifactPage(
                session_id,
                artifact_ref,
                content,
                offset,
                end if more else None,
                f"{position}:{end}:{stat.st_size}:{stat.st_mtime_ns}" if more else None,
                None if more else end,
            )

    def _sync(self, db: sqlite3.Connection, source: Path) -> tuple[int, int, int, bool]:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS source (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                device TEXT, inode TEXT, position INTEGER, mtime INTEGER,
                skipped INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
                turn_id TEXT, kind TEXT NOT NULL, role TEXT, created_at REAL,
                artifact_refs TEXT NOT NULL, total_chars INTEGER NOT NULL,
                message INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_turn ON events(turn_id, seq);
            CREATE INDEX IF NOT EXISTS events_message ON events(message, seq);
            CREATE TABLE IF NOT EXISTS chunks (
                seq INTEGER NOT NULL, offset INTEGER NOT NULL, content TEXT NOT NULL,
                PRIMARY KEY(seq, offset)
            );
        """)
        with source.open("rb") as stream, db:
            db.execute("BEGIN IMMEDIATE")
            stat = os.fstat(stream.fileno())
            previous = db.execute("SELECT * FROM source WHERE singleton = 1").fetchone()
            position = previous["position"] if previous else 0
            skipped = previous["skipped"] if previous else 0
            replaced = previous is not None and (
                (str(previous["device"]), str(previous["inode"]))
                != (str(stat.st_dev), str(stat.st_ino))
                or stat.st_size < position
                or (stat.st_size == position and stat.st_mtime_ns != previous["mtime"])
            )
            if previous is not None and not replaced and position == stat.st_size:
                return position, stat.st_size, skipped, False
            if replaced:
                db.execute("DELETE FROM chunks")
                db.execute("DELETE FROM events")
                position = skipped = 0
            stream.seek(position)
            end = min(stat.st_size, position + INDEX_BYTES)
            awaiting_tail = False
            while stream.tell() < end:
                raw = stream.readline()
                if not raw.endswith(b"\n"):
                    awaiting_tail = True
                    break  # A live writer may still be completing the final record.
                position = stream.tell()
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    skipped += 1  # Keep recovery gaps visible in every page.
                    continue
                content, message = _content(event)
                db.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["seq"],
                        event["event_id"],
                        event.get("turn_id"),
                        event["kind"],
                        event.get("role"),
                        event.get("created_at", event.get("timestamp", 0)),
                        json.dumps(event.get("artifact_refs", [])),
                        len(content),
                        message,
                    ),
                )
                db.executemany(
                    "INSERT INTO chunks VALUES (?, ?, ?)",
                    (
                        (event["seq"], offset, content[offset : offset + CHUNK_CHARS])
                        for offset in range(0, len(content), CHUNK_CHARS)
                    ),
                )
            db.execute(
                "INSERT OR REPLACE INTO source VALUES (1, ?, ?, ?, ?, ?)",
                (
                    str(stat.st_dev),
                    str(stat.st_ino),
                    position,
                    stat.st_mtime_ns,
                    skipped,
                ),
            )
        return position, max(position, stat.st_size), skipped, awaiting_tail

    @staticmethod
    def _record(db, row, offset: int, limit: int) -> HistoryRecord:
        start = offset // CHUNK_CHARS * CHUNK_CHARS
        chunks = db.execute(
            "SELECT content FROM chunks WHERE seq = ? AND offset >= ? AND offset < ? ORDER BY offset",
            (row["seq"], start, offset + limit),
        )
        content = "".join(chunk[0] for chunk in chunks)[
            offset - start : offset - start + limit
        ]
        next_offset = offset + len(content)
        return HistoryRecord(
            event_id=row["event_id"],
            seq=row["seq"],
            turn_id=row["turn_id"],
            kind=row["kind"],
            role=row["role"],
            created_at=row["created_at"],
            content=content,
            offset=offset,
            total_chars=row["total_chars"],
            next_offset=next_offset if next_offset < row["total_chars"] else None,
            artifact_refs=tuple(json.loads(row["artifact_refs"])),
        )

    def read(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        event_id: str | None = None,
        turn_id: str | None = None,
        start_seq: int = 1,
        limit: int = 50,
        max_chars: int = PAGE_CHARS,
        messages_only: bool = True,
        reverse: bool = False,
    ) -> HistoryPage:
        _limits(limit, max_chars)
        if start_seq < 1:
            raise ValueError("start_seq must be positive")
        seq, offset = _cursor(cursor) if cursor else (start_seq, 0)
        connection, source = self._connect(session_id)
        with closing(connection) as db:
            indexed = self._sync(db, source)
            # A newest-first view is meaningful only after reaching the tail.
            if reverse and indexed[0] < indexed[1] and not indexed[3]:
                return HistoryPage(session_id, (), cursor, *indexed)
            clauses, args = [], []
            if event_id:
                clauses.append("event_id = ?")
                args.append(event_id)
            elif cursor or not reverse:
                clauses.append("seq <= ?" if reverse else "seq >= ?")
                args.append(seq)
            if messages_only and not event_id:
                clauses.append("message = 1")
            if turn_id:
                clauses.append("turn_id = ?")
                args.append(turn_id)
            where = " AND ".join(clauses) or "1"
            rows = db.execute(
                f"SELECT * FROM events WHERE {where} ORDER BY seq {'DESC' if reverse else 'ASC'} LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
            records = []
            remaining = max_chars
            encoded_remaining = PAGE_ENCODED_CHARS
            next_cursor = None
            for row in rows:
                record_offset = offset if event_id or row["seq"] == seq else 0
                if record_offset > row["total_chars"]:
                    raise ValueError("cursor exceeds record length")
                if len(records) == limit or remaining == 0:
                    next_cursor = f"{row['seq']}:{record_offset}"
                    break
                record = self._record(db, row, record_offset, remaining)
                record, size = _fit_record(record, encoded_remaining)
                if record is None:
                    if not records:
                        raise ValueError(
                            "Record metadata exceeds the history page budget"
                        )
                    next_cursor = f"{row['seq']}:{record_offset}"
                    break
                records.append(record)
                encoded_remaining -= size
                remaining -= len(record.content)
                if record.next_offset is not None:
                    next_cursor = f"{record.seq}:{record.next_offset}"
                    break
            if (
                next_cursor is None
                and not reverse
                and not event_id
                and indexed[0] < indexed[1]
            ):
                next_cursor = _indexed_cursor(db, seq)
            return HistoryPage(session_id, tuple(records), next_cursor, *indexed)

    def search(
        self,
        session_id: str,
        pattern: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
        max_chars: int = PAGE_CHARS,
        messages_only: bool = True,
    ) -> HistoryPage:
        """Case-insensitive literal search, with a bounded scan and continuation."""
        _limits(limit, max_chars)
        if not 1 <= len(pattern) <= 256:
            raise ValueError("pattern must contain 1 to 256 characters")
        matcher = re.compile(re.escape(pattern), re.IGNORECASE)
        seq, offset = _cursor(cursor) if cursor else (1, 0)
        connection, source = self._connect(session_id)
        with closing(connection) as db:
            indexed = self._sync(db, source)
            chunks = db.execute(
                "SELECT c.seq, c.offset, c.content, e.message FROM chunks c JOIN events e USING(seq) "
                "WHERE (c.seq, c.offset) >= (?, ?) "
                "ORDER BY c.seq, c.offset LIMIT ?",
                (seq, offset, SEARCH_CHUNKS + 1),
            ).fetchall()
            records = []
            remaining = max_chars
            encoded_remaining = PAGE_ENCODED_CHARS
            next_cursor = None
            for index, chunk in enumerate(chunks):
                if index == SEARCH_CHUNKS or len(records) == limit or remaining == 0:
                    next_cursor = f"{chunk['seq']}:{chunk['offset']}"
                    break
                if messages_only and not chunk["message"]:
                    continue
                # The prefix also finds matches crossing chunk boundaries.
                prefix = db.execute(
                    "SELECT content FROM chunks WHERE seq = ? AND offset = ?",
                    (chunk["seq"], chunk["offset"] - CHUNK_CHARS),
                ).fetchone()
                lead = (
                    prefix[0][-len(pattern) + 1 :]
                    if prefix and len(pattern) > 1
                    else ""
                )
                haystack = lead + chunk["content"]
                found = matcher.search(haystack)
                if found is None:
                    continue
                row = db.execute(
                    "SELECT * FROM events WHERE seq = ?", (chunk["seq"],)
                ).fetchone()
                start = max(0, chunk["offset"] - len(lead) + found.start() - 120)
                record = self._record(db, row, start, min(remaining, 400))
                record, size = _fit_record(record, encoded_remaining)
                if record is None:
                    if not records:
                        raise ValueError(
                            "Record metadata exceeds the history page budget"
                        )
                    next_cursor = f"{chunk['seq']}:{chunk['offset']}"
                    break
                records.append(record)
                encoded_remaining -= size
                remaining -= len(record.content)
            if next_cursor is None and indexed[0] < indexed[1]:
                next_cursor = _indexed_cursor(db, seq)
            return HistoryPage(session_id, tuple(records), next_cursor, *indexed)


def _content(event: dict) -> tuple[str, bool]:
    payload = event["payload"]
    if event["kind"] == "message_committed":
        message = payload["message"]
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if message.get("reasoning_content"):
            content = (
                "[Reasoning]\n"
                + message["reasoning_content"]
                + "\n\n[Response]\n"
                + content
            )
        if message.get("tool_calls"):
            content += "\n" + json.dumps(message["tool_calls"], ensure_ascii=False)
        visible = message.get("role") in {
            "user",
            "assistant",
            "tool",
        } and not is_synthetic_context_message(message)
        return content, visible
    if event["kind"] == "output_checkpoint":
        return payload.get("text", ""), False
    return json.dumps(payload, ensure_ascii=False), False


def _cursor(value: str) -> tuple[int, int]:
    seq, offset = map(int, value.split(":"))
    if seq < 1 or offset < 0:
        raise ValueError("invalid history cursor")
    return seq, offset


def _indexed_cursor(db: sqlite3.Connection, start: int) -> str:
    last = db.execute("SELECT MAX(seq) FROM events").fetchone()[0]
    return f"{max(start, (last or 0) + 1)}:0"


def _fit_record(record: HistoryRecord, budget: int) -> tuple[HistoryRecord | None, int]:
    """Bound encoded content as well as metadata, including JSON escaping."""
    size = len(json.dumps(asdict(record), ensure_ascii=False)) + 2
    if size <= budget:
        return record, size
    overhead = (
        len(json.dumps(asdict(replace(record, content="")), ensure_ascii=False)) + 34
    )
    if budget <= overhead:
        return None, 0
    # Each source character encodes to at most six JSON characters. This keeps
    # continuation exact without repeated serialization or cutting JSON syntax.
    content = record.content[: (budget - overhead) // 6]
    if not content:
        return None, 0
    result = replace(record, content=content, next_offset=record.offset + len(content))
    return result, len(json.dumps(asdict(result), ensure_ascii=False)) + 2


def _limits(limit: int, max_chars: int) -> None:
    if not 1 <= limit <= 200 or not 1 <= max_chars <= PAGE_CHARS:
        raise ValueError(f"limit must be 1..200 and max_chars 1..{PAGE_CHARS}")
