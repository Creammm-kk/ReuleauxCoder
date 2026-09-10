"""Shared UI registration primitives for interface composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from reuleauxcoder.app.commands.capabilities import UIProfile

if TYPE_CHECKING:
    from reuleauxcoder.app.interaction_contracts import UIInteractor
    from reuleauxcoder.interfaces.view_registry import ViewRendererRegistry


@dataclass(frozen=True, slots=True)
class UIRegistration:
    """Concrete UI registration containing its view and interaction adapters."""

    profile: UIProfile
    view_registry: ViewRendererRegistry
    interactor: UIInteractor


class UIRegistry:
    """Static registry of available UI implementations."""

    def __init__(self, registrations: list[UIRegistration]):
        self._registrations = {
            registration.profile.ui_id: registration for registration in registrations
        }

    def get(self, ui_id: str) -> UIRegistration | None:
        """Return a registered UI if present."""
        return self._registrations.get(ui_id)

    def require(self, ui_id: str) -> UIRegistration:
        """Return a registered UI or raise if it does not exist."""
        registration = self.get(ui_id)
        if registration is None:
            raise KeyError(f"Unknown UI: {ui_id}")
        return registration

    def list(self) -> list[UIRegistration]:
        """List registered UIs."""
        return list(self._registrations.values())
