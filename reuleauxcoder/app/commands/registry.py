"""Action registry and parser/dispatcher helpers."""

from __future__ import annotations

from dataclasses import dataclass, fields

from reuleauxcoder.app.commands.models import (
    CommandContext,
    CommandEffect,
)
from reuleauxcoder.app.commands.requests import ActionRequest
from reuleauxcoder.app.commands.specs import (
    ActionSpec,
    ActionDescription,
    ActionCatalog,
    CommandParseContext,
    TriggerKind,
)
from reuleauxcoder.app.commands.capabilities import UIProfile


@dataclass(frozen=True, slots=True)
class ParsedAction:
    """A parsed command paired with the action spec that matched it."""

    command: object
    action: ActionSpec
    registry: "ActionRegistry"

    @property
    def request(self) -> ActionRequest:
        return ActionRequest(self.action.action_id, self.command)


class ActionRegistry:
    """Static action registry for explicit declarative specs."""

    def __init__(self, actions: list[ActionSpec] | None = None):
        self._actions: dict[str, ActionSpec] = {}
        self.register_many(actions or [])

    def register(self, action: ActionSpec) -> None:
        """Register one action spec."""
        if action.action_id in self._actions:
            raise ValueError(f"Duplicate command action: {action.action_id}")
        self._actions[action.action_id] = action

    @property
    def catalog(self) -> ActionCatalog:
        names = tuple(field.name for field in fields(ActionDescription))
        return ActionCatalog(
            tuple(
                ActionDescription(**{name: getattr(action, name) for name in names})
                for action in self._actions.values()
            )
        )

    def resolve(self, request: ActionRequest, ui_profile: UIProfile) -> ParsedAction:
        """Resolve a structured invocation under the same availability rules as text."""
        action = self._actions.get(request.action_id)
        if action is None or not action.is_available_in(ui_profile):
            raise ValueError(f"Unavailable action: {request.action_id}")
        if not isinstance(request.command, action.command_type):
            raise TypeError(f"Invalid parameters for action: {request.action_id}")
        return ParsedAction(request.command, action, self)

    def register_many(self, actions: list[ActionSpec] | tuple[ActionSpec, ...]) -> None:
        """Register multiple action specs."""
        for action in actions:
            self.register(action)

    def iter_actions(self, ui_profile: UIProfile) -> list[ActionSpec]:
        """Return actions available for a UI profile."""
        return [
            action
            for action in self._actions.values()
            if action.is_available_in(ui_profile)
        ]

    def parse(
        self,
        user_input: str,
        *,
        ui_profile: UIProfile,
        current_session_id: str | None = None,
    ) -> ParsedAction | None:
        """Try to parse user input using available action parsers."""
        parse_ctx = CommandParseContext(current_session_id=current_session_id, ui_profile=ui_profile)
        for action in self.iter_actions(ui_profile):
            if action.parser is None:
                continue
            if not action.matching_triggers(ui_profile, kind=TriggerKind.SLASH):
                continue
            parsed = action.parser(user_input, parse_ctx)
            if parsed is not None:
                return ParsedAction(command=parsed, action=action, registry=self)
        return None

    def dispatch(self, parsed: ParsedAction, ctx: CommandContext) -> CommandEffect:
        """Dispatch a parsed action to its handler."""
        if parsed.action.handler is None:
            return ctx.effect.finish(control="continue")
        result = parsed.action.handler(parsed.command, ctx)
        if result is not ctx.effect:
            raise RuntimeError(
                f"Command handler {parsed.action.action_id} returned a foreign effect"
            )
        return result
