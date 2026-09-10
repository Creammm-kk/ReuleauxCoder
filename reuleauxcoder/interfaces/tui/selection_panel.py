"""Non-blocking selection panel state for the terminal UI."""

from __future__ import annotations

from dataclasses import dataclass

from reuleauxcoder.app.commands.panels import PanelDefinition, PanelItem


@dataclass(slots=True)
class SelectionPanel:
    """Command-owned panel definition plus the highlighted row."""

    definition: PanelDefinition
    index: int = 0

    @classmethod
    def from_definition(cls, definition: PanelDefinition) -> "SelectionPanel":
        """Open mutable cursor state over an immutable command panel."""
        index = next(
            (i for i, item in enumerate(definition.items) if item.current),
            0,
        )
        return cls(definition=definition, index=index)

    @property
    def selected(self) -> PanelItem | None:
        items = self.definition.items
        if not items:
            return None
        return items[min(self.index, len(items) - 1)]

    def refresh(self, definition: PanelDefinition) -> None:
        """Update items while keeping the highlight on the same label."""
        selected = self.selected
        self.definition = definition
        items = definition.items
        self.index = min(self.index, max(0, len(items) - 1))
        if selected is not None:
            self.index = next(
                (i for i, item in enumerate(items) if item.label == selected.label),
                self.index,
            )
