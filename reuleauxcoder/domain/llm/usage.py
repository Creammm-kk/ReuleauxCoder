"""Request-scoped accounting shared by main, summary and isolated worker calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

usage_recorder: ContextVar[Callable[[], Callable[[dict], None] | None] | None] = (
    ContextVar("usage_recorder", default=None)
)


@contextmanager
def track_usage(recorder):
    token = usage_recorder.set(recorder)
    try:
        yield
    finally:
        usage_recorder.reset(token)
