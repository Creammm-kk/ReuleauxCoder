"""Action registry and parser/dispatcher helpers."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from typing import get_args, get_type_hints

from reuleauxcoder.app.commands.models import (
    CommandContext,
    CommandEffect,
)
from reuleauxcoder.app.commands.requests import ActionRequest
from reuleauxcoder.app.commands.specs import (
    ActionSpec,
    ActionDescription,
    ActionCatalog,
    ActionParameter,
    CommandParseContext,
    TriggerKind,
)
from reuleauxcoder.app.commands.capabilities import UIProfile


@dataclass(frozen=True, slots=True)
class ParsedAction:
    """A parsed command paired with the action spec that matched it."""

    command: object
    action: ActionSpec

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
        names = tuple(
            field.name
            for field in fields(ActionDescription)
            if field.name != "parameters"
        )
        return ActionCatalog(
            tuple(
                ActionDescription(
                    **{name: getattr(action, name) for name in names},
                    parameters=self._parameters(action),
                )
                for action in self._actions.values()
            )
        )

    @staticmethod
    def _parameters(action: ActionSpec) -> tuple[ActionParameter, ...]:
        if action.command_type is object:
            return ()
        hints = get_type_hints(action.command_type)
        result = []
        for item in fields(action.command_type):
            hint = hints[item.name]
            types = get_args(hint) or (hint,)
            nullable = type(None) in types
            primitive = next(value for value in types if value is not type(None))
            kind = {str: "text", int: "integer", bool: "boolean"}[primitive]
            result.append(
                ActionParameter(
                    item.name,
                    kind,
                    item.default is MISSING and not nullable,
                    nullable,
                    item.default if item.default is not MISSING else None,
                )
            )
        return tuple(result)

    def resolve(self, request: ActionRequest, ui_profile: UIProfile) -> ParsedAction:
        """Resolve a structured invocation under the same availability rules as text."""
        action = self._actions.get(request.action_id)
        if action is None or not action.is_available_in(ui_profile):
            raise ValueError(f"Unavailable action: {request.action_id}")
        if not isinstance(request.command, action.command_type):
            raise TypeError(f"Invalid parameters for action: {request.action_id}")
        return ParsedAction(request.command, action)

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
    ) -> ParsedAction | None:
        """Try to parse user input using available action parsers."""
        parse_ctx = CommandParseContext(ui_profile=ui_profile)
        for action in self.iter_actions(ui_profile):
            if action.parser is None:
                continue
            if not action.matching_triggers(ui_profile, kind=TriggerKind.SLASH):
                continue
            parsed = action.parser(user_input, parse_ctx)
            if parsed is not None:
                return ParsedAction(command=parsed, action=action)
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
