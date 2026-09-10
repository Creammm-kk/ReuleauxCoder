from types import SimpleNamespace

import reuleauxcoder.interfaces.cli.repl as repl_module
from reuleauxcoder.app.commands.requests import CommandResult
from reuleauxcoder.app.rpc.models import RuntimeSnapshot
from reuleauxcoder.app.ui_events import UIEventBus


def test_repl_submits_through_runtime_and_observes_backend_exit(monkeypatch, tmp_path):
    operations = []
    runtime = SimpleNamespace(
        state=RuntimeSnapshot(model="test"),
        info={"base_url": "", "history_file": str(tmp_path / "history")},
        submit=lambda text: operations.append(text),
        wait_idle=lambda **kwargs: runtime.on_completed(CommandResult(control="exit")),
    )
    monkeypatch.setattr(repl_module, "ensure_user_dirs", lambda: None)
    monkeypatch.setattr(repl_module, "show_banner", lambda *args, **kwargs: None)
    inputs = iter(["/quit"])
    monkeypatch.setattr(repl_module, "pt_prompt", lambda *args, **kwargs: next(inputs))

    repl_module.run_repl(runtime, UIEventBus())

    assert operations == ["/quit"]
