from types import SimpleNamespace

from reuleauxcoder.app.commands.models import CommandEffect
from reuleauxcoder.domain.history import HistoryLedger
from reuleauxcoder.app.commands.service import record_command_control_event
from reuleauxcoder.app.commands.loader import create_builtin_action_registry
from reuleauxcoder.app.commands.capabilities import UIProfile


def _action(action_id):
    return next(
        action
        for action in create_builtin_action_registry().iter_actions(
            UIProfile("cli", "CLI")
        )
        if action.action_id == action_id
    )


def test_mutating_command_state_is_ledgered() -> None:
    ledger = HistoryLedger(session_id="session", agent_id="agent")
    persisted = []
    agent = SimpleNamespace(
        history_ledger=ledger,
        agent_id="agent",
        _current_turn_id=None,
        persist_runtime_snapshot=lambda: persisted.append(True),
    )
    effect = CommandEffect().finish(state_changes={"active_mode": "coder"})

    record_command_control_event(agent, _action("mode.switch"), effect)

    assert ledger.events[-1].kind == "runtime_config_changed"
    assert ledger.events[-1].payload["state_changes"] == {"active_mode": "coder"}
    assert persisted == [True]


def test_read_only_command_does_not_pollute_control_ledger() -> None:
    ledger = HistoryLedger()
    agent = SimpleNamespace(history_ledger=ledger)
    record_command_control_event(agent, _action("system.help"), CommandEffect())
    assert ledger.events == ()
