"""UI Git sampling, independent of the model's turn-scoped HEAD notices."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reuleauxcoder.domain.version_control import GitFile, GitWorkspace

if TYPE_CHECKING:
    from reuleauxcoder.infrastructure.version_control.git_monitor import _CommandResult


def read_workspace(git: Callable[..., _CommandResult]) -> GitWorkspace:
    status = git(
        "-c",
        "status.relativePaths=false",
        "status",
        "--porcelain=v2",
        "-z",
        "--branch",
        "--untracked-files=all",
        "--no-renames",
    )
    if (
        status.timed_out
        or status.launch_error
        or (status.returncode and not status.truncated)
    ):
        return GitWorkspace(available=False, reason="Git status unavailable")
    headers = {}
    files = []
    # Only terminated records are safe to use if the output budget was exhausted.
    for raw in status.stdout.split(b"\0")[:-1]:
        text = raw.decode("utf-8", errors="replace")
        if text.startswith("# "):
            key, value = text[2:].split(" ", 1)
            headers[key] = value
        elif text.startswith("? "):
            files.append(GitFile(text[2:], "?", "?"))
        elif text.startswith(("1 ", "u ")):
            parts = text.split(" ", 10 if text[0] == "u" else 8)
            files.append(GitFile(parts[-1], parts[1][0], parts[1][1], text[0] == "u"))
    head = headers.get("branch.oid", "")
    ahead = behind = None
    if "branch.ab" in headers:
        ahead_text, behind_text = headers["branch.ab"].split()
        ahead, behind = int(ahead_text[1:]), int(behind_text[1:])
    additions = deletions = None
    if head and head != "(initial)":
        result = git(
            "diff",
            "--numstat",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--no-relative",
            "HEAD",
            "--",
        )
        if not result.returncode and not result.timed_out and not result.truncated:
            additions = deletions = 0
            for entry in result.stdout.split(b"\0")[:-1]:
                added, removed, _ = entry.split(b"\t", 2)
                if added != b"-":
                    additions += int(added)
                    deletions += int(removed)
    return GitWorkspace(
        available=True,
        branch=headers.get("branch.head", ""),
        head=head,
        upstream=headers.get("branch.upstream"),
        ahead=ahead,
        behind=behind,
        files=tuple(files),
        additions=additions,
        deletions=deletions,
        truncated=status.truncated,
    )
