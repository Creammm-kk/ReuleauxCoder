"""Tests for platform detection and shell resolution."""

import platform
import shutil

import pytest

from reuleauxcoder.infrastructure.platform import (
    PlatformInfo,
    ShellType,
    get_platform_info,
)


@pytest.mark.parametrize(
    "system, available, expected_shell, executable",
    [
        ("Linux", {"bash", "sh"}, ShellType.BASH, "bash"),
        ("Darwin", {"sh"}, ShellType.BASH, "sh"),
        ("Linux", set(), ShellType.UNKNOWN, None),
        ("Windows", {"bash", "pwsh", "powershell", "cmd"}, ShellType.BASH, "bash"),
        ("Windows", {"pwsh", "powershell", "cmd"}, ShellType.POWERSHELL_CORE, "pwsh"),
        ("Windows", {"powershell", "cmd"}, ShellType.POWERSHELL, "powershell"),
        ("Windows", {"cmd", "sh"}, ShellType.CMD, "cmd"),
        ("Windows", {"sh"}, ShellType.UNKNOWN, None),
    ],
)
def test_shell_resolution(system, available, expected_shell, executable, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(
        shutil, "which", lambda name: f"/bin/{name}" if name in available else None
    )
    info = PlatformInfo()

    assert info.get_preferred_shell() is expected_shell
    assert info.get_shell_path() == (f"/bin/{executable}" if executable else None)
    if executable is None:
        assert info.get_shell_executable() == []
        with pytest.raises(FileNotFoundError, match="no supported shell"):
            info.resolve_shell_invocation("echo hello")


def test_platform_info_is_singleton():
    assert get_platform_info() is get_platform_info()


def test_shell_invocation_preserves_command_text_verbatim(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/bash")
    info = PlatformInfo()
    command = "first && second\nprintf '$HOME'"

    invocation = info.resolve_shell_invocation(command)

    assert invocation.argv == ("/bin/bash", "-c", command)
