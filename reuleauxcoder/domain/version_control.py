"""Read-only workspace facts shared with frontends."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GitFile:
    path: str
    index: str
    worktree: str
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class GitWorkspace:
    available: bool
    branch: str = ""
    head: str = ""
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    files: tuple[GitFile, ...] = ()
    additions: int | None = None
    deletions: int | None = None
    truncated: bool = False
    reason: str | None = None
