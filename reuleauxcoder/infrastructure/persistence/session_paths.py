"""Portable, injective filesystem names for persisted session identities."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path


_ENCODED_PREFIX = "~rcsid-"
_ENCODED_COMPONENT = re.compile(r"~rcsid-[a-z2-7]+")
_ON_WINDOWS = os.name == "nt"
_DIRECT_COMPONENT = re.compile(r"[a-z0-9][a-z0-9_-]*")
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def is_safe_session_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None
        and ".." not in value
    )


def session_path_component(session_id: str) -> str:
    """Map an already-validated session ID to a Windows-safe component.

    Generated lowercase IDs keep their historical paths. IDs with colons,
    dots, uppercase characters, reserved-prefix ambiguity, or other portable
    filesystem hazards use lowercase base32. The tagged mapping is injective
    even on case-insensitive filesystems.
    """
    if (
        _DIRECT_COMPONENT.fullmatch(session_id) is not None
        and not session_id.startswith(_ENCODED_PREFIX)
        and session_id not in _WINDOWS_RESERVED_COMPONENTS
    ):
        return session_id
    encoded = base64.b32encode(session_id.encode("ascii")).decode("ascii")
    return _ENCODED_PREFIX + encoded.rstrip("=").lower()


def session_path_candidates(session_id: str) -> tuple[str, ...]:
    """Return the canonical name followed by a pre-mapping compatibility name."""
    canonical = session_path_component(session_id)
    if canonical == session_id:
        return (canonical,)
    if _ON_WINDOWS and not _is_windows_compatible_component(session_id):
        return (canonical,)
    return canonical, session_id


def session_storage_path(root: Path, session_id: str, *, suffix: str = "") -> Path:
    """Locate an already-validated identity, preserving legacy and broken paths.

    Callers own confinement and error reporting; lstat preserves broken links
    and inaccessible candidates so restoration cannot silently choose another file.
    """
    for component in session_path_candidates(session_id):
        candidate = root / f"{component}{suffix}"
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return candidate
        return candidate
    return root / f"{session_path_component(session_id)}{suffix}"


def is_encoded_session_path_component(value: str) -> bool:
    """Return whether a directory name has the reserved encoded shape."""
    return _ENCODED_COMPONENT.fullmatch(value) is not None


def _is_windows_compatible_component(value: str) -> bool:
    if any(char in '<>:"/\\|?*' for char in value):
        return False
    if value.endswith((" ", ".")):
        return False
    return value.split(".", 1)[0].lower() not in _WINDOWS_RESERVED_COMPONENTS
