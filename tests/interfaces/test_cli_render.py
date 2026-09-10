from unittest.mock import Mock

import pytest

from rich.markdown import Markdown

from reuleauxcoder.app.commands.view_models import HelpViewModel
from reuleauxcoder.domain.agent.events import AgentEvent
from reuleauxcoder.domain.runtime.events import agent_event_to_runtime_event
from reuleauxcoder.interfaces.cli.render import CLIRenderer
from reuleauxcoder.interfaces.cli.views.registry import create_cli_view_registry
from reuleauxcoder.app.ui_events import UIEvent, UIEventBus, UIEventKind
from reuleauxcoder.interfaces.view_registry import ViewRendererRegistry
from reuleauxcoder.presentation.models import AssistantCell, NoticeCell, ToolCell


def _renderer() -> CLIRenderer:
    return CLIRenderer(view_registry=ViewRendererRegistry([]))


def render_agent_event(renderer: CLIRenderer, event: AgentEvent) -> None:
    renderer.on_runtime_event(agent_event_to_runtime_event(event))


def test_cli_renderer_buffers_until_tool_output_then_flushes_plain_text() -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()

    render_agent_event(renderer, AgentEvent.stream_token("hello "))
    render_agent_event(renderer, AgentEvent.stream_token("world"))
    render_agent_event(
        renderer, AgentEvent.tool_call_start("shell", {"command": "pwd"})
    )
    render_agent_event(
        renderer, AgentEvent.chat_end("hello world", render_response=False)
    )

    renderer.render_content_markdown.assert_called_once_with("hello world")
    renderer.render_plain_text.assert_called_once_with("\n")


def test_cli_renderer_renders_chat_end_when_requested() -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()

    render_agent_event(
        renderer, AgentEvent.chat_end("final answer", render_response=True)
    )

    renderer.render_content_markdown.assert_called_once_with("final answer")


@pytest.mark.parametrize(
    "streamed", ["hello world", "hello"], ids=["complete", "partial"]
)
def test_cli_renderer_finalizes_stream_without_replaying_chat_end(streamed) -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()

    render_agent_event(renderer, AgentEvent.stream_token(streamed))
    render_agent_event(
        renderer, AgentEvent.chat_end("hello world", render_response=False)
    )

    renderer.render_content_markdown.assert_called_once_with(streamed)
    renderer.render_plain_text.assert_called_once_with("\n")


def test_cli_renderer_tracks_completed_content_and_tool_blocks() -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()

    render_agent_event(renderer, AgentEvent.stream_token("hello"))
    render_agent_event(
        renderer,
        AgentEvent.tool_call_start("shell", {"command": "pwd"}, tool_call_id="call-1"),
    )
    render_agent_event(
        renderer,
        AgentEvent.tool_call_end("shell", "ok", success=True, tool_call_id="call-1"),
    )

    assert renderer._active_content_block is None
    assistant, tool = renderer.reducer.state.transcript.cells
    assert isinstance(assistant, AssistantCell)
    assert assistant.text == "hello"
    assert isinstance(tool, ToolCell)
    assert tool.arguments == {"command": "pwd"}
    assert tool.outcome is not None and tool.outcome.model_text == "ok"


def test_cli_renderer_tracks_notification_block_after_stream() -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()

    render_agent_event(renderer, AgentEvent.stream_token("hello"))
    renderer.on_ui_event(UIEvent.info("debug note", kind=UIEventKind.SYSTEM))

    assert renderer._active_content_block is None
    assistant, notice = renderer.reducer.state.transcript.cells
    assert isinstance(assistant, AssistantCell)
    assert assistant.text == "hello"
    assert isinstance(notice, NoticeCell)
    assert notice.message == "debug note"
    assert notice.category == UIEventKind.SYSTEM.value


def test_help_view_closes_active_stream_block() -> None:
    renderer = CLIRenderer(view_registry=create_cli_view_registry())
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()
    bus = UIEventBus()
    bus.subscribe(renderer.on_ui_event)

    render_agent_event(renderer, AgentEvent.stream_token("hello"))
    bus.open_view(HelpViewModel(sections=()), title="Help")

    assert renderer._active_content_block is None
    assert renderer.reducer.state.transcript.cells[0].text == "hello"
    renderer.render_content_markdown.assert_called_once_with("hello")
    renderer.render_plain_text.assert_called_once_with("\n")


def test_cli_renderer_flushes_completed_paragraph_as_markdown() -> None:
    renderer = _renderer()
    renderer.render_content_markdown = Mock()
    renderer.render_plain_text = Mock()

    render_agent_event(renderer, AgentEvent.stream_token("# Title\nline 1\n\nrest"))

    # With markdown-it block commitment, "# Title" (heading) and "line 1"
    # (paragraph) are two complete blocks; only "rest" stays pending.
    renderer.render_content_markdown.assert_called_once_with("# Title\nline 1\n")
    assert renderer._active_content_block is not None
    assert renderer._active_content_block.pending_text == "\nrest"
    renderer.render_plain_text.assert_not_called()


def test_cli_renderer_falls_back_to_plain_text_when_markdown_render_fails() -> None:
    renderer = _renderer()
    renderer.console = Mock()
    renderer.console.print.side_effect = [RuntimeError("boom"), None]

    renderer.render_content_markdown("**hi**")

    first_call, second_call = renderer.console.print.call_args_list
    assert isinstance(first_call.args[0], Markdown)
    assert first_call.kwargs == {"end": ""}
    assert second_call.args == ("**hi**",)
    assert second_call.kwargs == {"end": "", "markup": False, "highlight": False}
