from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest

from reuleauxcoder.infrastructure.version_control import GitMonitor
from reuleauxcoder.infrastructure.version_control import (
    git_monitor as git_monitor_module,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "initial commit")
    return root


def test_workspace_snapshot_tracks_index_worktree_and_local_upstream(tmp_path):
    root = _repository(tmp_path)
    _git(root, "branch", "upstream")
    _git(root, "branch", "--set-upstream-to=upstream", "main")
    monitor = GitMonitor(root)
    monitor.snapshot(turn_id="before")
    (root / "second.txt").write_text("second\n")
    _git(root, "add", "second.txt")
    _git(root, "commit", "-m", "second")
    (root / "tracked.txt").write_text("staged\n")
    _git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("staged\nworktree\n")
    (root / "空 格.txt").write_text("untracked\n", encoding="utf-8")

    snapshot = monitor.workspace_snapshot()
    assert snapshot.available and snapshot.branch == "main"
    assert snapshot.upstream == "upstream"
    assert (snapshot.ahead, snapshot.behind) == (1, 0)
    assert (snapshot.additions, snapshot.deletions) == (2, 1)
    assert {file.path: (file.index, file.worktree) for file in snapshot.files} == {
        "tracked.txt": ("M", "M"),
        "空 格.txt": ("?", "?"),
    }
    # UI reads must not consume the model overlay's next-turn commit notice.
    assert monitor.snapshot(turn_id="after")["head_change"]["kind"] == "new_commits"
    _git(root, "reset", "--hard", "HEAD")
    _git(root, "checkout", "--detach", "upstream")
    detached = monitor.workspace_snapshot()
    assert detached.branch == "(detached)"
    assert detached.upstream is None and detached.ahead is None


def test_workspace_snapshot_reports_conflicts_and_unborn_repositories(tmp_path):
    root = _repository(tmp_path)
    _git(root, "checkout", "-b", "other")
    (root / "tracked.txt").write_text("other\n")
    _git(root, "commit", "-am", "other")
    _git(root, "checkout", "main")
    (root / "tracked.txt").write_text("main\n")
    _git(root, "commit", "-am", "main")
    with pytest.raises(subprocess.CalledProcessError):
        _git(root, "merge", "other")
    snapshot = GitMonitor(root).workspace_snapshot()
    assert [(file.path, file.conflict) for file in snapshot.files] == [
        ("tracked.txt", True)
    ]

    empty = tmp_path / "empty"
    empty.mkdir()
    assert not GitMonitor(empty).workspace_snapshot().available
    _git(empty, "init")
    (empty / "new.txt").write_text("new\n")
    unborn = GitMonitor(empty).workspace_snapshot()
    assert unborn.available and unborn.head == "(initial)"
    assert unborn.files[0].index == "?"
    assert unborn.additions is None


def test_workspace_snapshot_marks_partial_status_and_keeps_nul_delimited_paths(
    tmp_path,
):
    root = _repository(tmp_path)
    for index in range(30):
        (root / f"long-untracked-name-{index}.txt").write_text("new\n")
    snapshot = GitMonitor(root, max_output_bytes=256).workspace_snapshot()
    assert snapshot.available and snapshot.truncated
    assert all(file.path.endswith(".txt") for file in snapshot.files)
    if os.name != "nt":
        name = "tab\tline\nfile.txt"
        (root / name).write_text("special\n")
        assert name in {
            file.path for file in GitMonitor(root).workspace_snapshot().files
        }


def test_snapshot_separates_git_change_categories_and_collapses_directories(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    (root / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "staged.txt")
    bulk = root / "generated-tree"
    bulk.mkdir()
    for index in range(25):
        (bulk / f"item-{index}.txt").write_text("x", encoding="utf-8")

    snapshot = GitMonitor(root).snapshot(turn_id="turn-1")

    assert snapshot is not None and snapshot["available"] is True
    assert snapshot["branch"].startswith("main")
    assert "initial commit" in snapshot["head"]
    assert snapshot["changes"]["staged"] == {
        "count": 1,
        "items": ["added staged.txt"],
    }
    assert snapshot["changes"]["unstaged"] == {
        "count": 1,
        "items": ["modified tracked.txt"],
    }
    assert snapshot["changes"]["untracked"] == {
        "count": 1,
        "items": [
            "untracked generated-tree/ (directory collapsed; contents not scanned)"
        ],
    }


def test_status_byte_budget_returns_readable_lower_bound_marker(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for index in range(80):
        path = root / f"long-generated-file-{index:03d}-with-extra-name.txt"
        path.write_text("staged\n", encoding="utf-8")
    _git(root, "add", ".")
    monitor = GitMonitor(
        root,
        max_output_bytes=256,
        sample_limit=2,
        group_limit=1,
    )

    snapshot = monitor.snapshot(turn_id="turn-1")

    assert snapshot is not None
    assert snapshot["status_output_truncated"] is True
    staged = snapshot["changes"]["staged"]
    assert str(staged["count"]).startswith(">=")
    assert len(staged["items"]) <= 3
    assert "total unknown (scan truncated)" in staged["items"][-1]


def test_exact_sample_overflow_ends_with_and_more_marker(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    generated = root / "generated"
    generated.mkdir()
    for index in range(5):
        (generated / f"item-{index}.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "generated")

    snapshot = GitMonitor(root, sample_limit=2).snapshot(turn_id="turn-1")

    staged = snapshot["changes"]["staged"]
    assert staged["count"] == 5
    assert staged["items"][-1] == "… and 3 more (mostly generated/**)"


def test_head_change_notice_is_sticky_only_for_the_observing_turn(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    monitor = GitMonitor(root)
    assert "head_change" not in monitor.snapshot(turn_id="turn-1")

    (root / "second.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "second.txt")
    _git(root, "commit", "-m", "second commit")

    changed = monitor.snapshot(turn_id="turn-2")
    repeated = monitor.snapshot(turn_id="turn-2")
    next_turn = monitor.snapshot(turn_id="turn-3")

    assert changed["head_change"]["kind"] == "new_commits"
    assert changed["head_change"]["count"] == 1
    assert changed["head_change"]["commits"] == [
        f"{_git(root, 'rev-parse', '--short', 'HEAD')} second commit"
    ]
    assert repeated["head_change"] == changed["head_change"]
    assert "head_change" not in next_turn


def test_snapshot_cache_is_turn_scoped_and_explicitly_invalidated(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    monitor = GitMonitor(root, cache_ttl_seconds=60)
    original_git = monitor._git
    status_calls = 0

    def counted_git(*args, **kwargs):
        nonlocal status_calls
        if args and args[0] == "status":
            status_calls += 1
        return original_git(*args, **kwargs)

    monitor._git = counted_git  # type: ignore[method-assign]

    first = monitor.snapshot(turn_id="turn-1")
    first["branch"] = "mutated by caller"
    repeated = monitor.snapshot(turn_id="turn-1")
    assert status_calls == 1
    assert repeated["branch"] != "mutated by caller"

    monitor.invalidate()
    monitor.snapshot(turn_id="turn-1")
    assert status_calls == 2

    monitor.snapshot(turn_id="turn-2")
    assert status_calls == 3


def test_non_repository_reports_that_git_is_not_initialized(tmp_path: Path) -> None:
    assert GitMonitor(tmp_path).snapshot(turn_id="turn") == {
        "repository_root": str(tmp_path),
        "available": False,
        "reason": "not_initialized",
        "truncated": False,
    }


def test_repository_discovery_retries_on_the_next_turn(tmp_path: Path) -> None:
    monitor = GitMonitor(tmp_path)
    first = monitor.snapshot(turn_id="turn-1")
    assert first is not None and first["reason"] == "not_initialized"

    _git(tmp_path, "init")
    second = monitor.snapshot(turn_id="turn-2")

    assert second is not None
    assert second["available"] is True
    assert second["head"] == "no commits"


def test_missing_git_executable_is_distinct_from_an_uninitialized_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_monitor_module.subprocess, "Popen", _missing)

    snapshot = GitMonitor(tmp_path).snapshot(turn_id="turn")

    assert snapshot is not None
    assert snapshot["available"] is False
    assert snapshot["reason"] == "git_not_installed"
