"""Frontend snapshots contain data, never live runtime objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    revision: int = 0
    session_id: str | None = None
    agent_id: str | None = None
    session_generation: int = 0
    running: bool = False
    stopping: bool = False
    interrupt_pending: bool = False
    queued_commands: tuple[str, ...] = ()
    queued_steering: tuple[str, ...] = ()
    model: str = ""
    context_tokens: int = 0
    context_limit: int = 0
    mcp_enabled: int = 0
    mcp_tools: int = 0
    mcp_state: str = "ready"
    workspace: str = ""
    exit_saved_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class Submission:
    status: str
    state: RuntimeSnapshot
