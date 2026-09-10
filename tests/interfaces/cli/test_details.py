from io import StringIO

from rich.console import Console

from reuleauxcoder.app.rpc.models import RuntimeSnapshot
from reuleauxcoder.app.ui_events import ReasoningNoticePayload, UIEvent
from reuleauxcoder.domain.agent.tool_outcome import ToolOutcome
from reuleauxcoder.domain.plan import PlanItem, PlanState, ProgressState
from reuleauxcoder.domain.runtime.events import (
    RuntimeEvent,
    ToolCallFinished,
    ToolCallStarted,
    ToolOutputDelta,
)
from reuleauxcoder.interfaces.cli.render import CLIRenderer


def test_cli_full_details_preserve_output_beyond_compact_preview():
    stream = StringIO()
    renderer = CLIRenderer(
        console_override=Console(file=stream, width=100), live_activity=False
    )
    for payload in (
        ToolCallStarted("call", "shell", {"command": "long output"}),
        ToolOutputDelta("call", "[red]literal live output[/red]\n"),
        ToolCallFinished(
            "call",
            "shell",
            ToolOutcome(content="\n".join(f"result-{i}" for i in range(80))),
        ),
    ):
        renderer.on_runtime_event(RuntimeEvent(payload=payload))
    assert "[red]literal live output[/red]" in stream.getvalue()
    stream.seek(0)
    stream.truncate()
    renderer.show_tools()
    renderer.on_ui_event(
        UIEvent.info(
            "\n\n".join(f"reason-{i}" for i in range(80)),
            payload=ReasoningNoticePayload(title="Reasoning"),
        )
    )
    text = stream.getvalue()
    assert "long output" in text
    assert all(f"result-{i}" in text and f"reason-{i}" in text for i in range(80))
    renderer.close()


def test_cli_restores_conversation_and_execution_details():
    stream = StringIO()
    renderer = CLIRenderer(
        console_override=Console(file=stream, width=100), live_activity=False
    )
    state = RuntimeSnapshot(
        agent_id="root", session_id="restored", session_generation=2
    )
    renderer.restore(
        {
            "recent_conversation": [
                {"role": "user", "content": "[red]原始内容[/red]"},
                {"role": "assistant", "content": "**恢复回答**"},
            ],
            "plan": PlanState(
                "root",
                2,
                revision=3,
                items=(PlanItem("检查迁移", "检查中", "in_progress"),),
            ),
            "progress": ProgressState(summary="正在验证", next="完成迁移", revision=2),
        },
        state,
    )
    renderer.show_details(state)
    text = stream.getvalue()
    assert "[red]原始内容[/red]" in text
    assert "恢复回答" in text
    assert "检查迁移" in text
    assert "正在验证" in text
    assert "完成迁移" in text
    renderer.close()
