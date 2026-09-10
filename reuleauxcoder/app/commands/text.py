"""Slash text diagnostics shared by command clients."""

from reuleauxcoder.app.commands.registry import ActionRegistry
from reuleauxcoder.app.commands.capabilities import UIProfile


def _extract_base_name(trigger_value: str) -> str:
    """Extract the base command name from a slash trigger value.

    ``/thinking`` → ``thinking``, ``/thinking inline`` → ``thinking``.
    """
    if not trigger_value.startswith("/"):
        return ""
    return trigger_value[1:].split()[0] if trigger_value[1:].strip() else ""


def _levenshtein(s: str, t: str) -> int:
    """Compute edit distance between two strings."""
    if len(s) < len(t):
        return _levenshtein(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, cs in enumerate(s, 1):
        curr = [i]
        for j, ct in enumerate(t, 1):
            curr.append(
                min(
                    curr[-1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if cs == ct else 1),
                )
            )
        prev = curr
    return prev[-1]


def _suggest_command(
    user_input: str,
    registry: ActionRegistry,
    ui_profile: UIProfile,
) -> str | None:
    """Return a suggestion string for a mistyped slash command, or None."""
    if not user_input.startswith("/"):
        return None

    # Extract the typed command base name
    typed = user_input[1:].lstrip().split()[0] if user_input[1:].strip() else ""
    if not typed:
        return None

    from reuleauxcoder.app.commands.specs import TriggerKind

    # Collect all unique base command names from slash triggers
    candidates: set[str] = set()
    for action in registry.iter_actions(ui_profile):
        for trigger in action.matching_triggers(ui_profile, kind=TriggerKind.SLASH):
            base = _extract_base_name(trigger.value)
            if base:
                candidates.add(base)

    if not candidates:
        return None

    # Find closest match by edit distance
    best: str | None = None
    best_dist: int = 999
    for candidate in sorted(candidates):
        if candidate == typed:
            return None  # exact match but parser rejected → subcommand error, don't suggest
        dist = _levenshtein(typed, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate

    # Threshold: max 2 edits, proportional to word length
    max_dist = max(1, min(2, len(typed) // 3 + 1))
    if best is not None and best_dist <= max_dist:
        return f"Unknown command '/{typed}'. Did you mean '/{best}'?"

    return f"Unknown command '/{typed}'."


def _invalid_command_usage(
    user_input: str,
    registry: ActionRegistry,
    ui_profile: UIProfile,
) -> str | None:
    """Explain malformed input for a known slash-command namespace."""
    if not user_input.startswith("/"):
        return None

    typed = user_input[1:].lstrip().split()[0] if user_input[1:].strip() else ""
    if not typed:
        return "Unknown command '/'. Use /help to list available commands."

    from reuleauxcoder.app.commands.specs import TriggerKind

    usages: list[str] = []
    for action in registry.iter_actions(ui_profile):
        for trigger in action.matching_triggers(ui_profile, kind=TriggerKind.SLASH):
            if (
                _extract_base_name(trigger.value) == typed
                and trigger.value not in usages
            ):
                usages.append(trigger.value)

    if not usages:
        return None
    rendered = "; ".join(usages)
    return f"Invalid '/{typed}' command. Usage: {rendered}"
