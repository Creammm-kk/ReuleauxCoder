"""Prompt Toolkit layout and lifecycle orchestration for the production TUI."""

from __future__ import annotations

from pathlib import Path
import threading

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.layout import (
    BufferControl,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.processors import ConditionalProcessor, PasswordProcessor
from prompt_toolkit.data_structures import Point
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import Frame

from reuleauxcoder import __version__
from reuleauxcoder.domain.runtime.events import (
    AssistantStreamInterrupted,
    RuntimeEvent,
    UserSteeringApplied,
)
from reuleauxcoder.app.rpc.client import RuntimeClient
from reuleauxcoder.app.commands.requests import ActionRequest
from reuleauxcoder.interfaces.tui.command_popup import (
    PopupEntry,
    build_popup_entries,
    filter_entries,
)
from reuleauxcoder.interfaces.tui.selection_host import SelectionHost
from reuleauxcoder.interfaces.tui.style import (
    ALTERNATE_SCROLL_DISABLE,
    ALTERNATE_SCROLL_ENABLE,
    MINI_TUI_MOUSE_SUPPORT,
    MINI_TUI_STYLE,
)
from reuleauxcoder.interfaces.tui.virtual_transcript import VirtualTranscriptControl
from reuleauxcoder.app.ui_events import (
    UIEvent,
    UIEventKind,
)
from reuleauxcoder.app.interaction_contracts import (
    ChooseOneRequest,
    ConfirmRequest,
    InputTextRequest,
    ReviewRequest,
)
from reuleauxcoder.interfaces.tui.interaction import (
    MiniTUIInteractor,
    interaction_lines as _interaction_lines,
)
from reuleauxcoder.interfaces.tui.input_router import build_key_bindings
from reuleauxcoder.interfaces.tui.formatting import (
    clip as _clip,
    fit_styled_row as _fit_styled_row,
    wrapped_row_count as _wrapped_row_count,
)
from reuleauxcoder.interfaces.tui.execution_panel import _execution_panel_rows
from reuleauxcoder.interfaces.tui.event_adapter import MiniTUIEventAdapter


class MiniTUIApplication:
    """Persistent top panel, scrollable transcript and modal bottom input."""

    def __init__(
        self,
        *,
        ui_bus,
        ui_profile,
        runtime: RuntimeClient,
        interactor: MiniTUIInteractor,
        event_adapter: MiniTUIEventAdapter,
        startup_events: tuple[UIEvent, ...] = (),
    ) -> None:
        self.ui_bus = ui_bus
        self.runtime = runtime
        self.interactor = interactor
        self.events = event_adapter
        self.running = False
        self.cancelling = False
        self.round_interrupt_applying = False
        self.exit_confirm = False
        self._closed = False
        self._animation_stop = threading.Event()
        self._animation_thread: threading.Thread | None = None
        self._width = 100
        self._follow_transcript = True
        self._transcript_scroll = 0
        self._transcript_max_scroll = 0
        self._last_terminal_rows = 0
        self._last_terminal_columns = 0
        self.session_header_expanded = True
        self.startup_lines = tuple(
            event.message.splitlines()[0]
            for event in startup_events
            if event.message.strip() and event.kind is not UIEventKind.MCP
        )[:6]
        self.events.runtime_event_handler = self._on_runtime_event

        history_path = (
            str(Path(runtime.info["history_file"]).expanduser())
            if runtime.info["history_file"]
            else str(Path.cwd() / ".rcoder" / "history")
        )
        self.input_buffer = Buffer(
            history=FileHistory(history_path),
            multiline=False,
            accept_handler=self._accept_buffer,
        )
        self.interaction_input_buffer = Buffer(
            multiline=False,
            accept_handler=self._accept_interaction_buffer,
        )
        self._interaction_input_owner: tuple[str, str] | None = None
        self.panel_control = FormattedTextControl(self._panel_text)
        self._popup_entries: tuple[PopupEntry, ...] = build_popup_entries(
            runtime.catalog, ui_profile
        )
        self._popup_index = 0
        self._popup_last_text = ""
        self._popup_dismissed = False
        self.selection_host = SelectionHost(
            build_panel=runtime.build_panel,
            input_text=lambda: self.input_buffer.text,
            submit_action=self._submit_panel_action,
            invalidate=self.invalidate,
        )
        self.events.interactive_view_handler = self.selection_host.open_view
        self.transcript_control = VirtualTranscriptControl(
            self.events.transcript_layout,
            self._transcript_cursor_position,
        )
        self.transcript_window = Window(
            self.transcript_control,
            wrap_lines=False,
            always_hide_cursor=True,
            get_vertical_scroll=lambda _window: self._transcript_scroll,
            right_margins=[
                ScrollbarMargin(
                    display_arrows=True,
                    up_arrow_symbol="▲",
                    down_arrow_symbol="▼",
                )
            ],
        )
        # Compatibility alias for the scroll state machine. Unlike
        # ScrollablePane, Window paints only its visible viewport and does not
        # allocate a transcript-height off-screen Screen on every frame.
        self.transcript_pane = self.transcript_window
        self.interaction_control = FormattedTextControl(self._interaction_text)
        self.popup_control = FormattedTextControl(self._popup_text)
        self.popup_window = Window(
            self.popup_control,
            height=self._popup_height,
            style="class:popup",
        )
        self.selection_control = FormattedTextControl(self.selection_host.text)
        self.selection_window = Window(
            self.selection_control,
            height=self.selection_host.height,
            style="class:popup",
        )
        self.input_window = Window(
            BufferControl(
                buffer=self.input_buffer,
            ),
            height=self._input_height,
            wrap_lines=True,
            style="class:input",
        )
        self.interaction_input_window = Window(
            BufferControl(
                buffer=self.interaction_input_buffer,
                input_processors=[
                    ConditionalProcessor(
                        PasswordProcessor(char="•"),
                        Condition(self._secret_input_active),
                    )
                ],
            ),
            height=self._interaction_input_height,
            wrap_lines=True,
            style="class:input",
        )
        body = HSplit(
            [
                Frame(
                    Window(self.panel_control, height=self._panel_height),
                    title=lambda: f" FORGE · v{__version__} · F2 DETAILS ",
                    style="class:frame.border",
                ),
                self.transcript_window,
                Frame(
                    HSplit(
                        [
                            self.selection_window,
                            self.popup_window,
                            Window(
                                self.interaction_control,
                                height=self._interaction_height,
                                wrap_lines=True,
                            ),
                            self.interaction_input_window,
                            self.input_window,
                        ]
                    ),
                    title=self._input_title,
                    style="class:frame.border",
                ),
            ]
        )
        self.application = Application(
            layout=Layout(body, focused_element=self.input_window),
            key_bindings=build_key_bindings(self),
            full_screen=True,
            style=MINI_TUI_STYLE,
            mouse_support=MINI_TUI_MOUSE_SUPPORT,
            min_redraw_interval=1 / 30,
            max_render_postpone_time=0.05,
            before_render=self._before_render,
        )
        self.events.bind_invalidator(self.invalidate)
        self.interactor.bind_invalidator(self._interaction_changed)
        runtime.on_state = self._on_state
        runtime.on_completed = self._on_completed
        runtime.on_command = self.events.append_user_command
        self._on_state(runtime.state)

    def run(self) -> None:
        self._animation_stop.clear()
        self._animation_thread = threading.Thread(
            target=self._animation_loop,
            name="rcoder-ui-animation",
            daemon=True,
        )
        self._animation_thread.start()
        try:
            self.application.run(
                pre_run=lambda: self._set_alternate_scroll(enabled=True)
            )
        finally:
            self._set_alternate_scroll(enabled=False)
            self._animation_stop.set()
            if self._animation_thread is not None:
                self._animation_thread.join(timeout=0.5)
            self._save_exit_session()

    @property
    def saved_session_id(self) -> str | None:
        return self.runtime.state.exit_saved_session_id

    def _animation_loop(self) -> None:
        ticks = 0
        while not self._animation_stop.wait(0.1):
            ticks += 1
            if ticks % 5 == 0:
                try:
                    self.runtime.refresh()
                except (ConnectionError, TimeoutError) as error:
                    self.application.loop.call_soon_threadsafe(
                        lambda error=error: self.application.exit(exception=error)
                    )
                    return
            if self.events.has_animation_lease():
                self.invalidate()

    def invalidate(self) -> None:
        if not self._closed:
            try:
                self.application.invalidate()
            except RuntimeError:
                pass

    def _accept_buffer(self, buffer: Buffer) -> bool:
        popup = self._popup_candidates()
        if popup:
            entry = popup[min(self._popup_index, len(popup) - 1)]
            if entry.completion != buffer.text.strip():
                # Adopt the highlighted candidate without submitting.
                self._popup_adopt()
                return True
        raw_text = buffer.text
        text = raw_text.strip()
        active_request = self.interactor.active_request
        if active_request is not None:
            # Binary approvals borrow the input focus but not its contents.
            # The buffer may contain a chat draft from before the request
            # arrived; Enter accepts the advertised default without consuming
            # that draft, just like the dedicated Y / N bindings below.
            if isinstance(active_request, (ConfirmRequest, ReviewRequest)):
                self.interactor.submit("")
                return True
            # Choice/text prompts own a separate transient interaction buffer;
            # never consume a chat draft if focus briefly lags a state change.
            return True
        if not text:
            buffer.reset()
            return True
        admission = self.runtime.submit(text)
        if admission.status != "rejected":
            buffer.reset()
        self.exit_confirm = False
        self.session_header_expanded = False
        self.invalidate()
        return True

    def _accept_interaction_buffer(self, buffer: Buffer) -> bool:
        request = self.interactor.active_request
        if request is None:
            buffer.reset()
            return True
        raw_text = buffer.text
        self.interactor.submit(
            raw_text if isinstance(request, InputTextRequest) else raw_text.strip()
        )
        if self.interactor.active_request is not request:
            buffer.reset()
        return True

    def _secret_input_active(self) -> bool:
        request = self.interactor.active_request
        return isinstance(request, InputTextRequest) and request.secret

    def _interaction_input_active(self) -> bool:
        request = self.interactor.active_request
        if isinstance(request, (ChooseOneRequest, InputTextRequest)):
            return True
        return (
            isinstance(request, ReviewRequest)
            and self.interactor.review_state.stage == "feedback"
        )

    def _interaction_input_height(self) -> int:
        return 1 if self._interaction_input_active() else 0

    def _interaction_changed(self) -> None:
        request = self.interactor.active_request
        stage = (
            self.interactor.review_state.stage
            if isinstance(request, ReviewRequest)
            else "input"
        )
        owner = (
            (request.request_id, stage)
            if request is not None and self._interaction_input_active()
            else None
        )
        if owner != self._interaction_input_owner:
            self.interaction_input_buffer.reset()
            self._interaction_input_owner = owner
        try:
            target = (
                self.interaction_input_window
                if owner is not None
                else self.input_window
            )
            self.application.layout.focus(target)
        except (RuntimeError, ValueError):
            pass
        self.invalidate()

    def _submit_panel_action(self, request: ActionRequest) -> None:
        self.runtime.submit(request)

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event.payload, AssistantStreamInterrupted):
            self.round_interrupt_applying = True
        elif isinstance(event.payload, UserSteeringApplied):
            self.round_interrupt_applying = False

    def _on_state(self, state) -> None:
        self.running = state.running
        self.cancelling = state.stopping and state.running
        if not state.running:
            self.round_interrupt_applying = False
        self.invalidate()

    def _on_completed(self, result) -> None:
        if result.session_changed and result.plan is not None:
            self.events.restore_control_state(
                result.plan, result.progress, session_id=result.session_id
            )
        if result.clear_transcript:
            self.events.clear_transcript()
            self._follow_transcript = True
            self._transcript_scroll = 0
            self.transcript_pane.vertical_scroll = 0
        if result.control == "exit":
            self.application.loop.call_soon_threadsafe(self.application.exit)
        self.invalidate()

    def _queued_commands(self) -> tuple[str, ...]:
        return self.runtime.state.queued_commands

    @property
    def current_session_id(self) -> str | None:
        return self.runtime.state.session_id

    def _panel_text(self) -> FormattedText:
        try:
            self._width = self.application.output.get_size().columns - 4
        except Exception:
            pass
        self.events.set_viewport_width(max(20, self._width - 1))
        return FormattedText(
            fragment for row in self._panel_rows() for fragment in (*row, ("", "\n"))
        )

    def _panel_height(self) -> int:
        return len(self._panel_rows())

    def _panel_rows(self) -> tuple[tuple[tuple[str, str], ...], ...]:
        details = (
            # MODEL lives in the always-visible right-side context tail.
            f"ROOT {self.runtime.state.workspace}",
            f"SESSION {self.current_session_id or 'new'}",
            self._mcp_panel_detail(),
            *self.startup_lines,
        )
        rows = _execution_panel_rows(
            self.events.panel_view(),
            width=max(20, self._width),
            expanded=self.session_header_expanded,
            details=details,
        )
        tail = self._context_tail()
        if tail and rows:
            width = max(20, self._width)
            first = rows[0]
            used = sum(get_cwidth(text) for _style, text in first)
            tail_width = sum(get_cwidth(text) for _style, text in tail)
            padding = " " * max(1, width - used - tail_width)
            rows = (_fit_styled_row([*first, ("", padding), *tail], width), *rows[1:])
        return rows

    def _mcp_panel_detail(self) -> str:
        state = self.runtime.state
        connecting = " connecting ·" if state.mcp_state == "connecting" else ""
        return f"MCP{connecting} {state.mcp_enabled} enabled · {state.mcp_tools} tools"

    def _context_tail(self) -> tuple[tuple[str, str], ...]:
        state = self.runtime.state
        fragments = [("class:panel.label.secondary", f" {state.model} ")]
        if state.context_limit:
            ratio = max(0.0, min(1.0, state.context_tokens / state.context_limit))
            filled = round(ratio * 8)
            bar = "█" * filled + "·" * (8 - filled)
            style = (
                "class:success"
                if ratio < 0.6
                else ("class:warning" if ratio < 0.8 else "class:error")
            )
            fragments.extend(
                ((style, bar), ("class:panel.value", f" {ratio * 100:.0f}%"))
            )
        return tuple(fragments)

    def _input_height(self) -> int:
        """Grow the single-line input visually as wrapped rows (capped)."""
        # Hide the input lane while an approval/review is pending so the draft
        # buffer is preserved and single-key Y / N bindings take over. The
        # session picker keeps it visible: the buffer doubles as its filter.
        if self.interactor.active_request is not None:
            return 0
        if self.selection_host.active and not self.selection_host.filterable:
            return 0
        try:
            columns = self.application.output.get_size().columns
        except Exception:
            columns = self._width
        content_width = max(20, columns - 4)
        return _wrapped_row_count(self.input_buffer.text, content_width, cap=8)

    def _queued_steering(self) -> tuple[str, ...]:
        return self.runtime.state.queued_steering

    def _popup_candidates(self) -> tuple[PopupEntry, ...]:
        if self.interactor.active_request is not None or self.selection_host.active:
            return ()
        text = self.input_buffer.text
        if text != self._popup_last_text:
            self._popup_last_text = text
            self._popup_index = 0
            self._popup_dismissed = False
        if self._popup_dismissed:
            return ()
        return filter_entries(self._popup_entries, text)

    def _popup_height(self) -> int:
        return min(8, len(self._popup_candidates()))

    def _popup_adopt(self) -> None:
        candidates = self._popup_candidates()
        if not candidates:
            return
        entry = candidates[min(self._popup_index, len(candidates) - 1)]
        text = entry.completion + (" " if entry.has_arg else "")
        self.input_buffer.text = text
        self.input_buffer.cursor_position = len(text)
        self.invalidate()

    def _popup_text(self) -> FormattedText:
        candidates = self._popup_candidates()
        if not candidates:
            return FormattedText([])
        limit = 8
        index = min(self._popup_index, len(candidates) - 1)
        start = max(0, min(index - limit // 2, max(0, len(candidates) - limit)))
        fragments: list[tuple[str, str]] = []
        for offset, entry in enumerate(candidates[start : start + limit]):
            i = start + offset
            marker = "›" if i == index else " "
            cmd = f" {marker} {entry.completion}"
            pad = " " * max(1, 24 - len(cmd))
            if i == index:
                fragments.append(
                    ("class:popup.selected", cmd + pad + entry.description + "\n")
                )
            else:
                fragments.append(("class:popup.cmd", cmd))
                fragments.append(("class:popup", pad + entry.description + "\n"))
        return FormattedText(fragments)

    def _interaction_height(self) -> int:
        request = self.interactor.active_request
        if request is None:
            queued_count = len(self._queued_steering()) + len(self._queued_commands())
            if not queued_count:
                return 1
            return 1 + min(3, queued_count) + int(queued_count > 3)
        return min(
            8,
            max(
                2,
                len(
                    _interaction_lines(
                        request,
                        self.interactor.review_state,
                    )
                ),
            ),
        )

    def _interaction_text(self) -> FormattedText:
        request = self.interactor.active_request
        if request is not None:
            return FormattedText(
                [
                    (
                        "class:warning" if "⚠" in line else "class:interaction",
                        line + "\n",
                    )
                    for line in _interaction_lines(
                        request,
                        self.interactor.review_state,
                    )
                ]
            )
        if self.exit_confirm:
            return FormattedText(
                [
                    (
                        "class:warning",
                        "Press Ctrl+C again to exit; Esc keeps the session.\n",
                    )
                ]
            )
        if self.cancelling:
            return FormattedText([("class:warning", "Cancelling the current turn…\n")])
        if self.running:
            round_interrupt_pending = bool(self.runtime.state.interrupt_pending)
            if round_interrupt_pending:
                status = (
                    "Applying queued steering…"
                    if self.round_interrupt_applying
                    else "Interrupting the current request…"
                )
                return FormattedText(
                    [
                        ("class:warning", status + "\n"),
                        (
                            "class:muted",
                            "Press Ctrl+C again to discard it and cancel the turn\n",
                        ),
                    ]
                )
            queued_steering = self._queued_steering()
            queued_commands = self._queued_commands()
            pending = [
                ("class:user", f" ↳ steer next: {_clip(text, 48)}\n")
                for text in queued_steering
            ]
            pending.extend(
                ("class:command", f" ⌛ when idle: {_clip(text, 48)}\n")
                for text in queued_commands
            )
            lines = pending[:3]
            if len(pending) > 3:
                lines.append(("class:muted", f" … {len(pending) - 3} more queued\n"))
            if queued_commands and queued_steering:
                hint = "Ctrl+C applies steering now; commands still run when idle\n"
            elif queued_commands:
                hint = "Ctrl+C cancels the turn and runs queued commands next\n"
            elif queued_steering:
                hint = "Ctrl+C interrupts the request and applies queued steering\n"
            else:
                hint = "Agent running · Enter queues a steer · Ctrl+C cancels\n"
            lines.append(("class:muted", hint))
            return FormattedText(lines)
        return FormattedText(
            [
                (
                    "class:muted",
                    "/help · wheel/PageUp scroll · drag to select/copy\n",
                )
            ]
        )

    def _input_title(self) -> str:
        return " REVIEW " if self.interactor.active_request else " YOU "

    def _should_route_arrows_to_transcript(self) -> bool:
        return self.interactor.active_request is not None or not self.input_buffer.text

    def _set_alternate_scroll(self, *, enabled: bool) -> None:
        """Let the terminal translate wheel motion to Up/Down without mouse capture."""
        try:
            self.application.output.write_raw(
                ALTERNATE_SCROLL_ENABLE if enabled else ALTERNATE_SCROLL_DISABLE
            )
            self.application.output.flush()
        except (AttributeError, OSError, RuntimeError):
            # Minimal/dumb outputs can omit raw terminal control support.
            return

    def _report_ui_projection_failure(
        self,
        subsystem: str,
        error: BaseException,
        *,
        request_repaint: bool = True,
    ) -> None:
        reporter = getattr(self.events, "report_projection_failure", None)
        if not callable(reporter):
            return
        try:
            reporter(
                subsystem,
                error,
                request_repaint=request_repaint,
            )
        except KeyboardInterrupt:
            raise
        except BaseException:
            # Final UI observer boundary; never cover the original render fault.
            return

    def _before_render(self, _app) -> None:
        """Clamp scrolling and follow new output only while tail-follow is on."""
        try:
            size = self.application.output.get_size()
            content_width = max(20, size.columns - 1)
            layout, rebased_scroll = self.events.transcript_layout_rebased(
                content_width,
                self._transcript_scroll,
            )
            content_height = layout.line_count
            resized = size.rows != self._last_terminal_rows or size.columns != getattr(
                self, "_last_terminal_columns", size.columns
            )
            if resized:
                try:
                    self._sync_process_terminal_size(size.rows, size.columns)
                except KeyboardInterrupt:
                    raise
                except BaseException as error:
                    self._report_ui_projection_failure("terminal_resize", error)
            viewport = max(
                1,
                (
                    size.rows - self._panel_height() - self._interaction_height() - 6
                    if resized or not self.transcript_control.last_height
                    else self.transcript_control.last_height
                ),
            )
            self._last_terminal_rows = size.rows
            self._last_terminal_columns = size.columns
            maximum = max(0, content_height - viewport)
            self._transcript_max_scroll = maximum
            if self._follow_transcript:
                self._transcript_scroll = maximum
            else:
                self._transcript_scroll = min(rebased_scroll, maximum)
                if self._transcript_scroll >= maximum:
                    self._follow_transcript = True
            self.transcript_pane.vertical_scroll = self._transcript_scroll
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            # Rendering must stay available on minimal/dumb terminal outputs.
            self._report_ui_projection_failure(
                "before_render",
                error,
                request_repaint=False,
            )
            return

    def _sync_process_terminal_size(self, rows: int, columns: int) -> None:
        self.runtime.resize(rows, columns)

    def _transcript_page_size(self) -> int:
        try:
            rows = self.application.output.get_size().rows
        except Exception:
            rows = 24
        return max(3, rows // 2)

    def _transcript_cursor_position(self) -> Point:
        return Point(x=0, y=max(0, self._transcript_scroll))

    def _scroll_transcript(self, delta: int) -> None:
        target = max(
            0,
            min(
                self._transcript_max_scroll,
                self._transcript_scroll + delta,
            ),
        )
        self._transcript_scroll = target
        self.transcript_pane.vertical_scroll = target
        # Scrolling up opts out of tail-follow. Returning to the current bottom
        # opts back in, so subsequent streaming chunks remain visible.
        self._follow_transcript = target >= self._transcript_max_scroll
        self.invalidate()

    def _save_exit_session(self) -> None:
        self._closed = True
        self.interactor.cancel_active("session closed")
        try:
            self.runtime.shutdown()
        finally:
            self.events.close()

    def _prepare_forced_exit(self, reason: str) -> None:
        self.interactor.cancel_active(reason)
