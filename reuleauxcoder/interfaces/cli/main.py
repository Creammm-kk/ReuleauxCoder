"""CLI entry point - thin wrapper around the shared entrypoint.

This module handles CLI-specific concerns:
- Argument parsing
- One-shot prompt mode
- REPL loop
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text

from reuleauxcoder.interfaces.cli.args import parse_args
from reuleauxcoder.interfaces.cli.registration import create_cli_registration
from reuleauxcoder.interfaces.cli.render import CLIRenderer
from reuleauxcoder.presentation import PresentationPolicy
from reuleauxcoder.interfaces.cli.output import CLIOutputCoordinator
from reuleauxcoder.interfaces.cli.repl import run_repl
from reuleauxcoder.interfaces.cli.theme import DEFAULT_CLI_THEME
from reuleauxcoder.interfaces.entrypoint import AppRunner, AppOptions
from reuleauxcoder.presentation.semantics import DisplayTone
from reuleauxcoder.domain.context.manager import (
    has_cached_tiktoken_vocabulary,
    prepare_tiktoken_encoder,
)
from reuleauxcoder.services.config.loader import ExampleConfigError
from reuleauxcoder.infrastructure.persistence.session_store import SessionRestoreError


def _run_once(runtime, prompt: str, output: CLIOutputCoordinator):
    """Run a single prompt and exit."""
    runtime.submit(prompt)
    runtime.wait_idle(pump=output.drain)
    output.drain()


def _terminal_status(
    message: str,
    *,
    tone: DisplayTone = DisplayTone.NEUTRAL,
    console_override: Console | None = None,
) -> None:
    """Render styled status while no interactive renderer owns the terminal."""
    target = console_override or Console(
        file=sys.stderr,
        highlight=False,
        soft_wrap=True,
    )
    line = Text()
    line.append("rcoder", style=DEFAULT_CLI_THEME.style(DisplayTone.ACCENT))
    line.append(": ", style=DEFAULT_CLI_THEME.style(DisplayTone.MUTED))
    line.append(message, style=DEFAULT_CLI_THEME.style(tone))
    target.print(line, soft_wrap=True)


def main():
    """CLI main entry point."""
    args = parse_args()

    # Build options from CLI args
    options = AppOptions(
        config_path=Path(args.config) if args.config else None,
        model=args.model,
        resume_session_id=args.resume,
        auto_resume_latest=True,
        server_mode=args.server,
    )
    startup_progress_active = True

    def report_startup(message: str) -> None:
        if startup_progress_active:
            _terminal_status(message, tone=DisplayTone.NEUTRAL)

    startup_progress = (
        report_startup
        if not getattr(args, "prompt", None)
        and not args.server
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        else None
    )

    if getattr(args, "rpc_stdio", False):
        from reuleauxcoder.interfaces.entrypoint.rpc import run_stdio

        return run_stdio(options)

    # Initialize application using shared entrypoint
    runner = None
    try:
        if startup_progress is not None and not has_cached_tiktoken_vocabulary():
            prepare_tiktoken_encoder(progress=report_startup)
        runner = AppRunner(options, startup_progress=startup_progress)
        ctx = runner.initialize()
        startup_progress_active = False
    except ExampleConfigError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except SessionRestoreError as error:
        if runner is not None:
            try:
                runner.cleanup()
            except Exception:
                pass
        _terminal_status(str(error), tone=DisplayTone.ERROR)
        return 1
    except KeyboardInterrupt:
        if runner is not None:
            try:
                runner.cleanup()
            except Exception:
                pass
        print("Interrupted.", file=sys.stderr)
        return 130
    except BaseException:
        if runner is not None:
            runner.cleanup()
        raise

    from reuleauxcoder.app.ui_events import UIEventBus
    from reuleauxcoder.interfaces.entrypoint.rpc import connect_local

    remote_exec = ctx.config.remote_exec
    host_mode = args.server or (remote_exec.enabled and remote_exec.host_mode)
    frontend_bus = ctx.ui_bus if host_mode else UIEventBus()
    cli_ui = create_cli_registration(frontend_bus)
    if host_mode:
        renderer = CLIRenderer(
            view_registry=cli_ui.view_registry,
            policy=PresentationPolicy.from_ui_config(ctx.config.ui),
            root_agent_id=ctx.agent.agent_id,
        )
        output = CLIOutputCoordinator(renderer)
        frontend_bus.subscribe(output.on_ui_event)
        frontend_bus.info("Remote relay host mode active. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(0.1)
                output.drain()
        except KeyboardInterrupt:
            pass
        finally:
            output.close()
            runner.cleanup()
        return

    use_tui = not args.prompt and sys.stdin.isatty() and sys.stdout.isatty()
    connection = None
    output = None
    try:
        if not ctx.config.api_key:
            _terminal_status("No API key found in config.yaml.", tone=DisplayTone.ERROR)
            return 1
        if use_tui:
            from reuleauxcoder.interfaces.tui import (
                MiniTUIApplication,
                MiniTUIEventAdapter,
                MiniTUIInteractor,
            )

            interactor = MiniTUIInteractor(frontend_bus)
            connection = connect_local(ctx, cli_ui.profile, frontend_bus, interactor)
            runtime = connection.client
            event_adapter = MiniTUIEventAdapter(
                root_agent_id=runtime.state.agent_id,
                session_generation=runtime.state.session_generation,
                incident_sink=runtime.report_runtime_issue,
                performance_sink=runtime.record_performance,
            )
            frontend_bus.subscribe(event_adapter.on_ui_event)
            info = runtime.info
            event_adapter.append_restored_conversation(info["recent_conversation"])
            if info["plan"] is not None:
                event_adapter.restore_control_state(
                    info["plan"], info["progress"], session_id=runtime.state.session_id
                )
            application = MiniTUIApplication(
                runtime=runtime,
                ui_bus=frontend_bus,
                ui_profile=cli_ui.profile,
                interactor=interactor,
                event_adapter=event_adapter,
                startup_events=info["startup_events"],
            )
            _terminal_status("Starting terminal UI...", tone=DisplayTone.ACCENT)
            application.run()
            if application.saved_session_id:
                _terminal_status(
                    f"Session saved: {application.saved_session_id}.",
                    tone=DisplayTone.SUCCESS,
                )
        else:
            connection = connect_local(
                ctx,
                cli_ui.profile,
                frontend_bus,
                cli_ui.interactor,
                foreground_interactions=True,
            )
            runtime = connection.client
            renderer = CLIRenderer(
                view_registry=cli_ui.view_registry,
                policy=PresentationPolicy.from_ui_config(ctx.config.ui),
                root_agent_id=runtime.state.agent_id,
            )
            output = CLIOutputCoordinator(renderer)
            frontend_bus.subscribe(output.on_ui_event)
            if args.prompt:
                _run_once(runtime, args.prompt, output)
            else:
                run_repl(
                    runtime,
                    frontend_bus,
                    output,
                    cli_ui.interactor,
                    runtime.info["startup_events"],
                )
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            if output is not None:
                output.close()
            cli_ui.interactor.shutdown()
            runner.cleanup()
