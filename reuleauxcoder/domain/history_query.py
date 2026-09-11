"""Bounded history projections shared by tools and frontend transports."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    event_id: str
    seq: int
    turn_id: str | None
    kind: str
    role: str | None
    created_at: float
    content: str
    offset: int
    total_chars: int
    next_offset: int | None
    artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryPage:
    session_id: str
    records: tuple[HistoryRecord, ...]
    next_cursor: str | None
    indexed_bytes: int
    source_bytes: int
    skipped_records: int
    awaiting_tail: bool = False

    @property
    def indexing(self) -> bool:
        return self.indexed_bytes < self.source_bytes


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    session_id: str
    artifact_ref: str
    content: str
    offset: int
    next_offset: int | None
    next_cursor: str | None
    total_chars: int | None
