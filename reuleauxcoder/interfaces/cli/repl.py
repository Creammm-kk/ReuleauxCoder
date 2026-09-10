"""Interactive REPL loop."""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import cast

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory

from reuleauxcoder import __version__
from reuleauxcoder.infrastructure.fs.paths import ensure_user_dirs
from reuleauxcoder.app.rpc.client import RuntimeClient
from reuleauxcoder.interfaces.cli.render import show_banner
from reuleauxcoder.interfaces.cli.prompt import (
    FORGE_USER_PROMPT_STYLE,
    forge_active_prompt,
)
from reuleauxcoder.app.ui_events import UIEvent, UIEventBus


def run_repl(
    runtime: RuntimeClient,
    ui_bus: UIEventBus,
    output_coordinator=None,
    interaction_coordinator=None,
    startup_events: tuple[UIEvent, ...] = (),
) -> None:
    ensure_user_dirs()
    show_banner(
        runtime.state.model,
        runtime.info["base_url"],
        __version__,
        startup_events=startup_events,
    )

    hist_path = (
        str(Path(runtime.info["history_file"]).expanduser())
        if runtime.info["history_file"]
        else None
    )
    history = (
        FileHistory(hist_path)
        if hist_path
        else FileHistory(str(Path.cwd() / ".rcoder" / "history"))
    )
    while True:
        if output_coordinator is not None:
            output_coordinator.drain()
        try:
            foreground = getattr(interaction_coordinator, "foreground_input", None)
            if callable(foreground):
                with cast(AbstractContextManager[bool], foreground()) as available:
                    if not available:
                        break
                    user_input = pt_prompt(
                        forge_active_prompt,
                        history=history,
                        style=FORGE_USER_PROMPT_STYLE,
                    ).strip()
            else:
                user_input = pt_prompt(
                    forge_active_prompt,
                    history=history,
                    style=FORGE_USER_PROMPT_STYLE,
                ).strip()
        except (EOFError, KeyboardInterrupt):
            ui_bus.info("\nBye!")
            runtime.shutdown()
            if output_coordinator is not None:
                output_coordinator.drain()
            break

        if output_coordinator is not None:
            output_coordinator.drain()

        if not user_input:
            continue

        exited = []
        runtime.on_completed = lambda result: exited.append(result.control == "exit")
        try:
            runtime.submit(user_input)
            runtime.wait_idle(
                pump=output_coordinator.drain if output_coordinator else lambda: None
            )
            if output_coordinator is not None:
                output_coordinator.drain()
            if any(exited):
                break
        except KeyboardInterrupt:
            runtime.interrupt()
            runtime.wait_idle(
                pump=output_coordinator.drain if output_coordinator else lambda: None
            )
            ui_bus.warning("Interrupted.")
