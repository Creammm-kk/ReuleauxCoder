from types import SimpleNamespace

import pytest

from reuleauxcoder.app.commands.models import (
    CommandEffect,
)
from reuleauxcoder.app.commands.view_models import HelpViewModel
from reuleauxcoder.app.commands.registry import ActionRegistry
from reuleauxcoder.app.commands.specs import ActionSpec
from reuleauxcoder.interfaces.cli.commands import _apply_command_effect
from reuleauxcoder.interfaces.events import UIEventBus


def _action(handler) -> ActionSpec:
    return ActionSpec(
        action_id="test",
        feature_id="test",
        description="test",
        ui_targets=frozenset({"cli"}),
        handler=handler,
    )


def test_dispatch_records_notifications_in_returned_effect() -> None:
    effect = CommandEffect()
    ctx = SimpleNamespace(effect=effect)

    def handler(command, command_ctx):
        command_ctx.effect.success("done")
        return command_ctx.effect.finish(control="continue")

    action = _action(handler)
    parsed = SimpleNamespace(action=action, command=object())
    result = ActionRegistry().dispatch(parsed, ctx)

    assert result is effect
    assert [notice.message for notice in result.notifications] == ["done"]


@pytest.mark.parametrize(
    "action, title, expected_title, focus",
    [
        ("open", "Help", "Help", True),
        ("refresh", "Updated help", "Updated help", False),
        ("refresh", None, "help", False),
    ],
)
def test_cli_applies_command_effect_once(action, title, expected_title, focus) -> None:
    result = CommandEffect()
    result.info("hello")
    model = HelpViewModel(sections=())
    getattr(result, f"{action}_view")(model, title=title, reuse_key="help-panel")
    result.finish()
    bus = UIEventBus()

    _apply_command_effect(result, bus)

    notice, view_event = bus.history_snapshot()
    assert notice.message == "hello"
    assert view_event.message == f"{action.capitalize()} view: {expected_title}"
    assert result.views[0].view_model is model
    assert result.views[0].view_type == "help"
    payload = view_event.payload
    assert payload.view_model is model
    assert payload.view_type == "help"
    assert payload.action == action
    assert payload.title == expected_title
    assert payload.focus is focus
    assert payload.reuse_key == "help-panel"
