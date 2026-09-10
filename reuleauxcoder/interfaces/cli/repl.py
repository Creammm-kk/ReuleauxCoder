"""Linear CLI over the same JSON-RPC runtime used by the React TUI."""

import sys
import threading
from pathlib import Path

from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from reuleauxcoder import __version__
from reuleauxcoder.app.commands.specs import TriggerKind
from reuleauxcoder.app.rpc.client import RuntimeClient
from reuleauxcoder.app.ui_events import UIEvent, UIEventBus
from reuleauxcoder.infrastructure.fs.paths import ensure_user_dirs
from reuleauxcoder.interfaces.cli.input import CLIInput, PromptAction
from reuleauxcoder.interfaces.cli.registration import CLI_PROFILE
from reuleauxcoder.interfaces.cli.render import show_banner


def run_repl(
    runtime: RuntimeClient,
    ui_bus: UIEventBus,
    output_coordinator,
    interaction_coordinator,
    startup_events: tuple[UIEvent, ...] = (),
) -> None:
    ensure_user_dirs()
    show_banner(
        runtime.state.model,
        runtime.info["base_url"],
        __version__,
        startup_events=startup_events,
    )
    output = output_coordinator
    output.renderer.restore(runtime.info, runtime.state)
    exited = threading.Event()

    def completed(result):
        if result.control == "exit":
            exited.set()

    runtime.on_completed = completed
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    editor = None
    if interactive:
        words = sorted(
            {
                trigger.value
                for action in runtime.catalog.iter_actions(CLI_PROFILE)
                for trigger in action.matching_triggers(
                    CLI_PROFILE, kind=TriggerKind.SLASH
                )
            }
        )
        history_path = Path(
            runtime.info["history_file"] or ".rcoder/history"
        ).expanduser()
        history_path.parent.mkdir(parents=True, exist_ok=True)
        editor = CLIInput(
            runtime,
            output,
            exited,
            history=FileHistory(str(history_path)),
            completer=WordCompleter(words, sentence=True),
        )
    try:
        while not exited.is_set():
            output.drain()
            try:
                with interaction_coordinator.foreground_input() as available:
                    if not available:
                        break
                    value = editor.read() if editor else input()
            except EOFError:
                break
            except KeyboardInterrupt:
                if runtime.state.running:
                    runtime.interrupt()
                    continue
                break
            output.drain()
            if value is PromptAction.EXIT:
                break
            if value is PromptAction.INTERACTION:
                runtime.pump_interactions()
            elif value is PromptAction.INTERRUPT:
                runtime.interrupt()
            elif value is PromptAction.DETAILS:
                runtime.refresh()
                output.renderer.show_details(runtime.state, startup_events)
            elif value is PromptAction.TOOLS:
                output.renderer.show_tools()
            elif value.strip():
                admission = runtime.submit(value.strip())
                if admission.status == "steering":
                    ui_bus.info(f"Queued: {value.strip()}")
                elif admission.status == "rejected":
                    ui_bus.warning(
                        "Input was not accepted; try again when the turn finishes."
                    )
                if not interactive:
                    try:
                        runtime.wait_idle(pump=output.drain)
                    except KeyboardInterrupt:
                        runtime.interrupt()
                        runtime.wait_idle(pump=output.drain)
    finally:
        runtime.shutdown()
        output.drain()
        if runtime.state.exit_saved_session_id:
            ui_bus.success(f"Session saved: {runtime.state.exit_saved_session_id}.")
